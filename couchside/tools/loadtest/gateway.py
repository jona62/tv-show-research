"""Signed virtual client identities, exclusively for disposable gateway load tests.

Normal production never imports this factory. Both server and generator require
an audience-bound private key file; an unsigned request keeps normal admission.
"""
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path


def key_from(path, origin=None):
    value = json.loads(Path(path).read_text())
    if not isinstance(value.get('key'), str) or len(value['key']) < 64:
        raise ValueError('Choose a private load-test key of at least 32 bytes.')
    if origin and value.get('origin') != origin.rstrip('/'):
        raise ValueError('The private load-test key belongs to another target.')
    return value


def signature(key, identity):
    return hmac.new(key.encode(), identity.encode(), hashlib.sha256).hexdigest()


def forwarded(identity):
    value = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:12], 'big')
    return 'fd00:0:' + ':'.join(f'{(value >> shift) & 65535:x}' for shift in (80,64,48,32,16,0))


def signed_scope(scope, key):
    headers = dict(scope['headers'])
    identity = headers.get(b'x-couchside-load-identity', b'').decode('ascii', errors='replace')
    signed = headers.get(b'x-couchside-load-signature', b'').decode('ascii', errors='replace')
    if not identity or len(identity) > 128 or not hmac.compare_digest(signature(key, identity), signed):
        return scope
    return {**scope, 'client': ('127.0.0.1', 0),
            'headers': [(name, value) for name, value in scope['headers'] if name != b'x-forwarded-for'] +
                       [(b'x-forwarded-for', forwarded(identity).encode())]}


def proxy_shape(scope, key=None):
    """Classify an unsigned proxy path without recording client addresses."""
    from backend.request_limits import address, trusted_proxy_ips
    peer = (scope.get('client') or ('', 0))[0]
    chain = dict(scope['headers']).get(b'x-forwarded-for', b'').decode('latin1')
    def kind(value):
        try:
            parsed = ipaddress.ip_address(value.strip())
            return 'trusted' if parsed.is_loopback or parsed in trusted_proxy_ips() else 'private' if parsed.is_private else 'public'
        except ValueError:
            return 'invalid'
    selected = address(peer, chain)
    result = {'event': 'isolated_proxy_path', 'peer': kind(peer),
            'forwarded': [kind(hop) for hop in chain.split(',')] if chain else [],
            'selected': kind(selected), 'selected_equals_peer': selected == peer}
    probe = dict(scope['headers']).get(b'x-couchside-proxy-probe')
    if key and probe in (b'desktop', b'generator'):
        result.update(probe=probe.decode(), client_fingerprint=signature(key, selected))
    return result


def create_app():
    from backend.asgi import Application
    account = Path(os.environ['ACCOUNT_DB'])
    if os.environ.get('COUCHSIDE_LOAD_TEST_ISOLATED') != '1' or not (account.parent / '.couchside-loadtest').exists():
        raise ValueError('Signed load identities require a marked disposable account directory.')
    value = key_from(os.environ['COUCHSIDE_LOAD_GATEWAY_KEY'])
    application = Application()
    observe = 4 if os.environ.get('COUCHSIDE_LOAD_PROXY_OBSERVATIONS') == '1' else 0
    async def isolated(scope, receive, send):
        nonlocal observe
        if scope['type'] == 'http':
            if observe and scope['path'] == '/healthz' and dict(scope['headers']).get(b'x-couchside-proxy-probe') in (b'desktop', b'generator'):
                print(json.dumps(proxy_shape(scope, value['key'])), flush=True)
                observe -= 1
            scope = signed_scope(scope, value['key'])
        async def noindex(event):
            if event['type'] == 'http.response.start':
                event = {**event, 'headers': [*event['headers'], (b'x-robots-tag', b'noindex, nofollow')]}
            await send(event)
        return await application(scope, receive, noindex)
    return isolated
