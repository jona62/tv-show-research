"""Account HTTP boundary: request validation, cookies and CSRF before domain work.

The public reverse proxy terminates TLS. ACCOUNT_HTTPS_ONLY makes its cookies
secure; local development is allowed only through a loopback host and peer.
"""
from http.cookies import CookieError, SimpleCookie
import ipaddress
import json
import logging
import os
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from .accounts import AccountError
from .request_limits import Budget, address, trusted_proxy_ips

PREFIX = '/api/account/'
POSTS = {'signup', 'login', 'state', 'logout', 'password'}
TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')
HOST = re.compile(r'^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?$')


def loopback(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AccountRoutes:
    def __init__(self, service, https_only=False, origin=None):
        trusted_proxy_ips()
        self.service = service
        self.https_only = https_only
        self.origin = origin.rstrip('/') if origin else None
        workers = max(1, int(os.environ.get('COUCHSIDE_WORKERS', '1')))
        self.attempts = Budget(rate=1 / (60 * workers), burst=max(1, 10 / workers))
        self.read_slots = threading.BoundedSemaphore(16)
        self.body_timeout = 10

    def context(self, handler):
        hosts = handler.headers.get_all('Host', [])
        if len(hosts) != 1 or not HOST.fullmatch(hosts[0]):
            raise AccountError(400, 'Send a valid host.')
        host = hosts[0].lower()
        try:
            parsed = urlsplit('http://' + host)
            if parsed.port is not None and not 0 < parsed.port <= 65535:
                raise ValueError()
        except ValueError:
            raise AccountError(400, 'Send a valid host.') from None
        if self.https_only:
            origin = self.origin or 'https://' + host
            secure = True
        elif loopback(parsed.hostname) and loopback(handler.client_address[0]):
            origin, secure = 'http://' + host, False
        else:
            raise AccountError(503, 'Account access requires HTTPS.')
        cookie = '__Host-couchside-session' if secure else 'couchside-dev-session'
        return origin, cookie, secure

    def token(self, handler, name):
        try:
            cookies = SimpleCookie()
            cookies.load(handler.headers.get('Cookie', ''))
            token = cookies[name].value if name in cookies else ''
        except CookieError:
            token = ''
        return token if TOKEN.fullmatch(token) else ''

    def cookie(self, name, token, secure, clear=False):
        value = f'{name}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={0 if clear else 30 * 86400}'
        return value + ('; Secure' if secure else '')

    def reply(self, handler, value, status=200, headers=()):
        # Session responses are never cached, tagged or compressed.
        handler.cache_control = 'no-store'
        body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        sent = handler.answer(body, 'application/json; charset=utf-8', status,
                              extra=headers, pack=lambda _: None)
        if sent is not None:
            handler.wfile.write(sent)

    def payload(self, handler, route, origin):
        if handler.headers.get_all('Origin', []) != [origin]:
            raise AccountError(403, 'Open Couchside directly to use your account.')
        if handler.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
            raise AccountError(403, 'Use your account from Couchside.')
        if handler.headers.get('X-Account-Request') != '1':
            raise AccountError(403, 'Use your account from Couchside.')
        if handler.headers.get_content_type() != 'application/json':
            raise AccountError(415, 'Send application/json.')
        lengths = handler.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or handler.headers.get('Transfer-Encoding'):
            raise AccountError(400, 'Send a fixed-length JSON body.')
        try:
            length = int(lengths[0])
        except ValueError:
            length = 0
        limit = 262144 if route in ('signup', 'login', 'state') else 4096
        if not 0 < length <= limit:
            raise AccountError(413, 'That account request is too large.')
        if not self.read_slots.acquire(blocking=False):
            raise AccountError(429, 'Account requests are busy. Try again shortly.', retry_after=2)
        try:
            # An absolute deadline also bounds bodies arriving one byte at a time.
            deadline, chunks, remaining = time.monotonic() + self.body_timeout, [], length
            while remaining:
                wait = deadline - time.monotonic()
                if wait <= 0:
                    raise TimeoutError()
                handler.connection.settimeout(wait)
                chunk = handler.rfile.read1(min(remaining, 65536))
                if not chunk:
                    raise ValueError()
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b''.join(chunks)
            if len(raw) != length:
                raise ValueError()
            payload = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except TimeoutError:
            raise AccountError(408, 'That account request timed out. Please try again.') from None
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise AccountError(400, 'Send valid JSON.') from None
        finally:
            self.read_slots.release()
        if not isinstance(payload, dict):
            raise AccountError(400, 'Send account details as an object.')
        return payload

    def handle(self, handler, path):
        if not path.startswith(PREFIX):
            return False
        route = path[len(PREFIX):]
        try:
            origin, cookie, secure = self.context(handler)
            if handler.command == 'GET' and route == 'session':
                revisions, owners = handler.headers.get_all('X-Account-Revision', []), handler.headers.get_all('X-Account-Owner', [])
                conditional = handler.headers.get_all('X-Account-Conditional', [])
                if len(revisions) > 1 or len(owners) > 1 or (revisions and not re.fullmatch(r'[0-9]{1,16}', revisions[0])):
                    raise AccountError(400, 'The list revision is invalid.')
                if conditional and conditional != ['1']:
                    raise AccountError(400, 'The account poll is invalid.')
                since = int(revisions[0]) if revisions else 0
                self.reply(handler, self.service().session(self.token(handler, cookie), since,
                           owners[0] if owners else None, conditional=bool(conditional)))
                return True
            if handler.command != 'POST' or route not in POSTS:
                raise AccountError(404, 'Not found.')
            payload = self.payload(handler, route, origin)
            if route in ('signup', 'login', 'password'):
                wait = self.attempts.take(address(handler.client_address[0], handler.headers.get('X-Forwarded-For', '')))
                if wait:
                    raise AccountError(429, 'Too many attempts. Try again shortly.', retry_after=wait)
            service = self.service()
            token = self.token(handler, cookie)
            csrf = handler.headers.get('X-CSRF-Token', '')
            if route == 'signup':
                new, response = service.signup(payload.get('email'), payload.get('password'), payload.get('state'))
            elif route == 'login':
                new, response = service.login(payload.get('email'), payload.get('password'), payload.get('guest_state'))
            elif route == 'password':
                new, response = service.change_password(token, csrf, payload.get('current_password'), payload.get('password'))
            elif route == 'state':
                if type(payload.get('sync_version')) is not int or payload['sync_version'] != 2:
                    raise AccountError(409, 'Couchside was updated. Refresh this page to finish syncing. '
                                       'Your changes are safe on this device.', data={'upgrade': True})
                response = service.save(token, csrf, payload.get('state'), payload.get('revision'), payload.get('removed'))
                self.reply(handler, response)
                return True
            else:
                service.logout(token, csrf)
                self.reply(handler, {'ok': True}, headers=(('Set-Cookie', self.cookie(cookie, '', secure, clear=True)),))
                return True
            # Authentication never reuses a session supplied by the browser.
            self.reply(handler, response, 201 if route == 'signup' else 200,
                       (('Set-Cookie', self.cookie(cookie, new, secure)),))
        except AccountError as exc:
            if handler.command == 'POST':
                # Early rejection can leave unread bytes; retire the connection.
                handler.close_connection = True
            headers = (('Retry-After', str(exc.retry_after or 2)),) if exc.status in (429, 503) else ()
            self.reply(handler, {'error': exc.message, **(exc.data or {})}, exc.status, headers)
        except (sqlite3.Error, OSError):
            logging.error('Account storage is unavailable')
            handler.close_connection = True
            self.reply(handler, {'error': 'Accounts are temporarily unavailable. Try again shortly.'}, 503,
                       (('Retry-After', '5'),))
        return True
