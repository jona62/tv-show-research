"""Exercise the account HTTP security boundary with real persistence and cookies."""

from pathlib import Path
import sys

# Direct script runs and unittest discovery share the app package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection
from tempfile import TemporaryDirectory
import json
import threading
import time
import unittest

from backend.account_http import AccountRoutes
from backend.accounts import AccountService


PASSWORD = 'a long private passphrase'
STATE = {'version': 3, 'profile': [{'id': 169, 'weight': 1}], 'saved': [{'id': 82}],
         'settings': {'known_min': 85}, 'onboarded': True}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.routes.handle(self, self.path)

    do_POST = do_GET

    def answer(self, body, kind, status=200, extra=(), pack=None):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', self.cache_control)
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        return body

    def log_message(self, *args):
        pass


class AccountHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.service = AccountService(Path(self.tmp.name) / 'accounts.sqlite3', validate_domain=False)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.routes = AccountRoutes(lambda: self.service)
        self.worker = threading.Thread(target=self.http.serve_forever)
        self.worker.start()
        self.host = f'127.0.0.1:{self.http.server_port}'
        self.origin = 'http://' + self.host

    def tearDown(self):
        self.http.shutdown()
        self.worker.join(2)
        self.http.server_close()
        self.tmp.cleanup()

    def call(self, route, body=None, headers=None, raw=None):
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        supplied = {'Origin': self.origin, 'Content-Type': 'application/json', 'X-Account-Request': '1'}
        supplied.update(headers or {})
        connection.request('POST' if data is not None else 'GET', '/api/account/' + route, data, supplied)
        response = connection.getresponse()
        status, result_headers, content = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, result_headers, json.loads(content)

    def signup(self):
        status, headers, body = self.call('signup', {'email': 'viewer@gmail.com', 'password': PASSWORD, 'state': STATE})
        self.assertEqual(status, 201, body)
        return headers['Set-Cookie'].split(';')[0], body

    def test_signup_session_sync_logout_and_cache_policy(self):
        cookie, account = self.signup()
        status, headers, body = self.call('session', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('ETag', headers)
        self.assertNotIn('Content-Encoding', headers)
        self.assertEqual(body['state'], STATE)
        csrf = {'Cookie': cookie, 'X-CSRF-Token': account['csrf']}
        status, _, body = self.call('state', {'state': STATE, 'revision': 0}, csrf)
        self.assertEqual((status, body['revision']), (200, 1))
        status, _, conflict = self.call('state', {'state': STATE, 'revision': 0}, csrf)
        self.assertEqual((status, conflict['revision']), (409, 1))
        status, headers, _ = self.call('logout', {}, csrf)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.call('session', headers={'Cookie': cookie})[0], 401)

    def test_cross_origin_and_missing_custom_header_rejected(self):
        for headers in ({'Origin': 'https://attacker.example'}, {'X-Account-Request': ''},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Content-Type': 'text/plain'}):
            status, _, _ = self.call('signup', {'email': 'viewer@gmail.com', 'password': PASSWORD, 'state': STATE}, headers)
            self.assertIn(status, (403, 415))

    def test_mutations_need_csrf_and_session(self):
        cookie, _ = self.signup()
        self.assertEqual(self.call('state', {'state': STATE, 'revision': 0})[0], 401)
        self.assertEqual(self.call('logout', {}, {'Cookie': cookie})[0], 403)
        self.assertEqual(self.call('logout', {}, {'Cookie': cookie, 'X-CSRF-Token': 'wrong'})[0], 403)

    def test_secure_production_cookie_and_exact_origin(self):
        self.http.routes = AccountRoutes(lambda: self.service, https_only=True)
        self.origin = 'https://' + self.host
        status, headers, _ = self.call('signup', {'email': 'viewer@gmail.com', 'password': PASSWORD, 'state': STATE})
        self.assertEqual(status, 201)
        cookie = headers['Set-Cookie']
        for attribute in ('__Host-couchside-session=', 'Path=/', 'HttpOnly', 'SameSite=Lax', 'Secure'):
            self.assertIn(attribute, cookie)
        self.assertNotIn('Domain=', cookie)
        self.assertEqual(self.call('login', {'email': 'viewer@gmail.com', 'password': PASSWORD},
                                   {'Origin': 'http://' + self.host})[0], 403)

    def test_oversized_malformed_and_nonfinite_json(self):
        for raw, expected in ((b'{"password":"' + b'x' * 5000 + b'"}', 413),
                              (b'{"password":NaN}', 400), (b'[]', 400), (b'{', 400)):
            self.assertEqual(self.call('login', raw=raw)[0], expected)

    def test_malformed_host_and_non_ascii_csrf_are_client_errors(self):
        self.assertEqual(self.call('session', headers={'Host': '[:::]'})[0], 400)
        self.assertEqual(self.call('session', headers={'Host': 'localhost:99999'})[0], 400)
        cookie, _ = self.signup()
        self.assertEqual(self.call('logout', {}, {'Cookie': cookie, 'X-CSRF-Token': '\u00ff'})[0], 403)

    def test_strict_ip_attempt_budget_before_password_work(self):
        from backend.request_limits import Budget
        self.http.routes.attempts = Budget(rate=1 / 60, burst=1)
        self.call('login', {'email': 'viewer@gmail.com', 'password': PASSWORD})
        status, headers, _ = self.call('login', {'email': 'other@gmail.com', 'password': PASSWORD})
        self.assertEqual(status, 429)
        self.assertGreater(int(headers['Retry-After']), 0)

    def test_slow_upload_has_a_total_deadline(self):
        self.http.routes.body_timeout = .15
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=2)
        connection.putrequest('POST', '/api/account/login')
        for key, value in {'Origin': self.origin, 'Content-Type': 'application/json',
                           'X-Account-Request': '1', 'Content-Length': '100'}.items():
            connection.putheader(key, value)
        connection.endheaders()
        started = time.monotonic()
        connection.send(b'{')
        time.sleep(.09)
        connection.send(b' ')
        response = connection.getresponse()
        self.assertEqual(response.status, 408)
        self.assertLess(time.monotonic() - started, .22)
        response.read()
        connection.close()

    def test_saturated_upload_slots_reject_before_reading(self):
        for _ in range(16):
            self.assertTrue(self.http.routes.read_slots.acquire(blocking=False))
        try:
            self.assertEqual(self.call('login', {'email': 'viewer@gmail.com', 'password': PASSWORD})[0], 429)
        finally:
            for _ in range(16):
                self.http.routes.read_slots.release()


if __name__ == '__main__':
    unittest.main()
