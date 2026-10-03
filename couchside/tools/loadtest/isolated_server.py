"""Run the actual backend on loopback with disposable databases and unchanged limits."""
from argparse import ArgumentParser
from contextlib import closing
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import os
import secrets
import signal
import sqlite3
import sys
import threading
import time

APP = Path(__file__).resolve().parents[2]
ROOT = APP.parent


def disposable_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    marker = path / '.couchside-loadtest'
    if not marker.exists() and any(path.iterdir()):
        raise ValueError('Choose an empty directory for disposable load-test data.')
    marker.touch()
    return path.resolve()


def copy_cache(source, target):
    for name in ('http.sqlite3', 'artwork.sqlite3', 'episode-ratings.sqlite3'):
        original = source / name
        if original.is_file() and not (target / name).exists():
            with closing(sqlite3.connect(original.as_uri() + '?mode=ro', uri=True)) as reader:
                with closing(sqlite3.connect(target / name)) as writer, writer:
                    reader.backup(writer)


def prepare_accounts(directory, count):
    from backend.accounts import AccountService, HASHER, digest, SESSION_SECONDS
    from backend.account_validation import compact_state
    path = directory / 'accounts.sqlite3'
    pool = directory / 'accounts-private.json'
    if pool.exists():
        return pool
    service = AccountService(path)
    password, suffix = secrets.token_urlsafe(24), secrets.token_hex(4)
    encoded = HASHER.hash(password)
    state = compact_state({'version': 3, 'profile': [], 'saved': [],
                           'settings': {'known_min': 85}, 'onboarded': True})
    accounts = []
    # Provisioned fixtures are outside the timed run. Login still verifies Argon2id.
    with service.store.connection(write=True) as connection:
        for index in range(count):
            owner, token, csrf = secrets.token_urlsafe(16), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            email = f'couchside-load-{suffix}-{index}@example.com'
            connection.execute('INSERT INTO accounts VALUES (?, ?, ?, ?, ?, 0, ?)',
                               (owner, email, email, encoded, json.dumps(state), time.time()))
            connection.execute('INSERT INTO account_sessions VALUES (?, ?, ?, ?)',
                               (digest(token), owner, csrf, time.time() + SESSION_SECONDS))
            accounts.append({'email': email, 'password': password, 'token': token,
                             'owner': owner, 'csrf': csrf, 'revision': 0, 'state': state})
    descriptor = os.open(pool, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump({'cookie_name': 'couchside-dev-session', 'accounts': accounts}, output)
    return pool


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18120)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--cache-mode', choices=('warm', 'cold'), default='warm')
    parser.add_argument('--copy-from', type=Path, default=ROOT / 'data/cache')
    parser.add_argument('--accounts', type=int, default=2000)
    parser.add_argument('--allow-outbound', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or args.accounts < 0:
        parser.error('Choose a valid port and a nonnegative account count.')
    directory = disposable_directory(args.data_dir)
    cache = directory / 'cache'
    cache.mkdir(exist_ok=True)
    if args.cache_mode == 'warm':
        copy_cache(args.copy_from.resolve(), cache)
    os.environ.update(ACCOUNT_DB=str(directory / 'accounts.sqlite3'),
                      OUTBOUND_CACHE=str(cache / 'http.sqlite3'), RATINGS_CACHE=str(cache / 'episode-ratings.sqlite3'),
                      ARTWORK_CACHE=str(cache / 'artwork.sqlite3'),
                      COUCHSIDE_METRICS_FILE=str(directory / 'server-metrics.jsonl'),
                      COUCHSIDE_METRICS_INTERVAL='1', ACCOUNT_HTTPS_ONLY='0')
    os.environ.pop('ACCOUNT_ORIGIN', None)
    os.environ['COUCHSIDE_LOAD_TEST_NO_OUTBOUND'] = '0' if args.allow_outbound else '1'
    sys.path.insert(0, str(APP))
    from backend import telemetry
    telemetry.configure_from_env()
    prepare_accounts(directory, args.accounts)
    from backend import server

    class IsolatedHandler(server.Handler):
        def parse_request(self):
            parsed = super().parse_request()
            if parsed:
                identity = self.headers.get('X-Couchside-Load-Identity') or self.headers.get('X-Couchside-Loadtest-User')
                if identity and len(identity) <= 128:
                    # Emulate distinct clients behind a trusted proxy, only on this loopback test server.
                    value = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:12], 'big')
                    forwarded = 'fd00:0:' + ':'.join(f'{(value >> shift) & 65535:x}' for shift in (80, 64, 48, 32, 16, 0))
                    self.headers.replace_header('X-Forwarded-For', forwarded) if 'X-Forwarded-For' in self.headers else self.headers.add_header('X-Forwarded-For', forwarded)
            return parsed

    listener = ThreadingHTTPServer(('127.0.0.1', args.port), partial(IsolatedHandler, directory=str(server.PUBLIC)))
    def finish(_signal, _frame):
        threading.Thread(target=listener.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    print(json.dumps({'ready': True, 'port': listener.server_port, 'cache_mode': args.cache_mode,
                      'outbound_allowed': args.allow_outbound, 'accounts': args.accounts,
                      'admission_api_rps': 24, 'engine_slots': 3}), flush=True)
    try:
        listener.serve_forever(poll_interval=.2)
    finally:
        listener.server_close()
        telemetry.stop()


if __name__ == '__main__':
    main()
