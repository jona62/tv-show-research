"""Loopback preview bootstrap keeps ownership and existing preference data."""
from email.message import Message
from http.cookies import SimpleCookie
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'couchside'))
from backend.account_http import AccountRoutes
from backend.accounts import AccountService
from backend.feature_flags import FeatureFlags
from local_account import ACCOUNT_ID, bootstrap

STATE = {'version': 3, 'profile': [{'id': 169, 'weight': .7}], 'saved': [{'id': 618}],
         'settings': {'known_min': 85}, 'onboarded': True}


class Handler:
    def __init__(self, state=STATE, cookie='', host='localhost:8766', peer='127.0.0.1', origin=None):
        raw = json.dumps({'state': state}).encode()
        self.headers = Message()
        for key, value in {'Host': host, 'Origin': origin or 'http://' + host,
                           'Content-Type': 'application/json', 'X-Account-Request': '1',
                           'Content-Length': str(len(raw)), 'Cookie': cookie}.items():
            self.headers[key] = value
        self.client_address, self.command = (peer, 10000), 'POST'
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()
        self.connection = type('Connection', (), {'settimeout': lambda *_: None})()

    def answer(self, body, content_type, status, extra=(), pack=None):
        self.status, self.extra = status, extra
        return body

    def response(self):
        return json.loads(self.wfile.getvalue())

    def session_cookie(self):
        return next((value.split(';')[0] for name, value in self.extra if name == 'Set-Cookie'), '')


class LocalAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.service = AccountService(Path(self.tmp.name) / 'accounts.sqlite3', validate_domain=False)
        self.routes = AccountRoutes(lambda: self.service, features=FeatureFlags(local_development=True))

    def tearDown(self):
        self.tmp.cleanup()

    def test_guest_preferences_persist_under_one_development_owner(self):
        first = Handler()
        bootstrap(first, self.routes)
        self.assertEqual(first.status, 200)
        self.assertEqual(first.cache_control, 'private, no-store')
        self.assertEqual(first.response()['user']['id'], ACCOUNT_ID)
        self.assertEqual(first.response()['state'], STATE)
        cookie = SimpleCookie(first.session_cookie())
        token = cookie['couchside-dev-session'].value
        self.assertEqual(self.service.session(token)['state'], STATE)
        self.service.save(token, first.response()['csrf'], {**STATE, 'saved': []}, 0)
        another_browser = Handler()
        bootstrap(another_browser, self.routes)
        self.assertEqual(another_browser.response()['user']['id'], ACCOUNT_ID)
        self.assertEqual(another_browser.response()['state']['saved'], [])
        self.assertEqual(another_browser.response()['state']['profile'], STATE['profile'])

    def test_valid_normal_session_is_preserved(self):
        token, account = self.service.signup('other@gmail.com', 'a private local test passphrase', STATE)
        handler = Handler(cookie='couchside-dev-session=' + token)
        bootstrap(handler, self.routes)
        self.assertEqual(handler.response()['user'], account['user'])
        self.assertEqual(handler.session_cookie(), '')

    def test_remote_context_and_cross_origin_cannot_bootstrap(self):
        for options, status in [({'host': 'example.com'}, 503), ({'peer': '192.0.2.1'}, 503),
                                ({'origin': 'https://example.com'}, 403)]:
            with self.subTest(options=options):
                handler = Handler(**options)
                bootstrap(handler, self.routes)
                self.assertEqual(handler.status, status)
                self.assertEqual(handler.session_cookie(), '')
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 0)

    def test_production_policy_has_no_bootstrap(self):
        self.routes.features = FeatureFlags()
        handler = Handler()
        bootstrap(handler, self.routes)
        self.assertEqual(handler.status, 404)
        self.assertEqual(handler.session_cookie(), '')


if __name__ == '__main__':
    unittest.main()
