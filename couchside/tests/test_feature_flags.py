"""Static eligibility and private feature reads using real account sessions."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.account_http import AccountRoutes
from backend.accounts import AccountService, SESSION_SECONDS
from backend.feature_flags import FeatureFlags

EMAIL = 'jonathanjamesm66@gmail.com'
PASSWORD = 'a long private test passphrase'
STATE = {'version': 3, 'profile': [], 'saved': [], 'settings': {'known_min': 85}, 'onboarded': False}
DENIED = {'user_id': None, 'experimental_allowed': False, 'features': {'watch_tracking': False}}


def config(**changes):
    return {'version': 1, 'enabled': True, 'user_ids': [], 'emails': [EMAIL],
            'features': {'watch_tracking': True}, **changes}


class FeatureConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'features.json'
        self.user = {'id': 'normal-account-id', 'email': EMAIL}

    def tearDown(self):
        self.tmp.cleanup()

    def flags(self, value):
        self.path.write_text(json.dumps(value))
        return FeatureFlags(self.path)

    def test_email_or_exact_account_id_and_independent_feature_switch(self):
        policy = self.flags(config())
        self.assertTrue(policy.enabled_for(self.user))
        self.assertTrue(policy.enabled_for({**self.user, 'email': EMAIL.upper()}))
        for email in ('other@gmail.com', 'jonathanjamesm66+alias@gmail.com', 'jonathan.jamesm66@gmail.com'):
            self.assertFalse(policy.enabled_for({**self.user, 'email': email}))
        policy = self.flags(config(emails=[], user_ids=['normal-account-id']))
        self.assertTrue(policy.enabled_for({**self.user, 'email': 'other@gmail.com'}))
        self.assertFalse(policy.enabled_for({**self.user, 'id': 'NORMAL-ACCOUNT-ID'}))
        self.assertFalse(policy.enabled_for(None))
        self.assertFalse(policy.enabled_for({'email': EMAIL}))
        policy = self.flags(config(features={'watch_tracking': False}))
        self.assertTrue(policy.eligible(self.user))
        self.assertFalse(policy.enabled_for(self.user))
        self.assertFalse(policy.enabled_for(self.user, 'unknown_feature'))

    def test_global_disabled_denies_allowlisted_identity(self):
        policy = self.flags(config(enabled=False))
        self.assertEqual(policy.envelope(self.user), {**DENIED, 'user_id': self.user['id']})

    def test_missing_invalid_ambiguous_and_oversized_config_fail_closed(self):
        with self.assertLogs(level='WARNING'):
            self.assertEqual(FeatureFlags(self.path).envelope(self.user), {**DENIED, 'user_id': self.user['id']})
        invalid = [None, [], {}, config(version=True), config(version=2), config(enabled=1),
                   config(user_ids=['bad id']), config(user_ids=[7]), config(emails=[EMAIL + ' ']),
                   config(emails='*'), config(features={'watch_tracking': 'true'}),
                   config(features={'typo_feature': True}), {**config(), 'public': True}]
        for value in invalid:
            with self.subTest(value=value), self.assertLogs(level='WARNING'):
                self.assertFalse(self.flags(value).enabled_for(self.user))
        for raw in ('{', '{"version":1,"version":1}', 'NaN', '"' + 'x' * 65536 + '"'):
            self.path.write_text(raw)
            with self.subTest(raw=raw[:50]), self.assertLogs(level='WARNING'):
                self.assertFalse(FeatureFlags(self.path).enabled_for(self.user))

    def test_policy_is_static_until_reconstructed(self):
        policy = self.flags(config())
        self.path.write_text(json.dumps(config(enabled=False)))
        self.assertTrue(policy.enabled_for(self.user))
        self.assertFalse(FeatureFlags(self.path).enabled_for(self.user))

    def test_checked_in_policy_has_only_confirmed_email(self):
        path = Path(__file__).resolve().parents[1] / 'backend/feature-flags.json'
        value = json.loads(path.read_text())
        self.assertEqual(value['emails'], [EMAIL])
        self.assertEqual(value['user_ids'], [])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.routes.handle(self, urlsplit(self.path).path)

    do_POST = do_GET
    do_HEAD = do_GET

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


class FeatureHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.policy_path = Path(self.tmp.name) / 'features.json'
        self.policy_path.write_text(json.dumps(config()))
        self.service = AccountService(Path(self.tmp.name) / 'accounts.sqlite3', validate_domain=False)
        self.token, self.account = self.service.signup(EMAIL, PASSWORD, STATE)
        self.other_token, self.other = self.service.signup('other@gmail.com', PASSWORD, STATE)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.routes = AccountRoutes(lambda: self.service, features=FeatureFlags(self.policy_path))
        self.worker = threading.Thread(target=self.http.serve_forever)
        self.worker.start()
        self.origin = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.worker.join(2)
        self.http.server_close()
        self.tmp.cleanup()

    def call(self, path='/api/features', token=None, headers=None, body=None):
        supplied = {'Accept-Encoding': 'gzip', 'If-None-Match': '*', **(headers or {})}
        if token:
            supplied['Cookie'] = 'couchside-dev-session=' + token
        payload = None if body is None else json.dumps(body).encode()
        if payload is not None:
            supplied.update({'Origin': self.origin, 'Content-Type': 'application/json', 'X-Account-Request': '1'})
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        connection.request('GET' if payload is None else 'POST', path, payload, supplied)
        response = connection.getresponse()
        status, returned, raw = response.status, dict(response.getheaders()), response.read()
        connection.close()
        self.assertEqual(returned['Cache-Control'], 'private, no-store' if not path.startswith('/api/account/') else 'no-store')
        self.assertNotIn('ETag', returned)
        self.assertNotIn('Content-Encoding', returned)
        return status, returned, json.loads(raw)

    def test_guest_denied_and_client_identity_claims_are_ignored(self):
        claims = {'X-Account-Owner': self.account['user']['id'], 'X-User-Id': self.account['user']['id'],
                  'X-User-Email': EMAIL}
        self.assertEqual(self.call(headers=claims)[2], DENIED)
        path = '/api/features?user_id=' + self.account['user']['id'] + '&email=' + EMAIL
        self.assertEqual(self.call(path, headers=claims)[2], DENIED)
        allowed = self.call(token=self.token)[2]
        self.assertEqual(allowed, {'user_id': self.account['user']['id'], 'experimental_allowed': True,
                                  'features': {'watch_tracking': True}})
        unlisted = self.call(path, token=self.other_token, headers=claims)[2]
        self.assertEqual(unlisted, {**DENIED, 'user_id': self.other['user']['id']})
        self.assertNotIn(EMAIL, json.dumps(allowed))
        self.assertNotIn('state', allowed)
        self.assertNotIn('csrf', allowed)
        self.assertNotIn('emails', allowed)

    def test_expired_revoked_and_invalid_sessions_never_grant_features(self):
        status, _, _ = self.call('/api/account/logout', self.token,
                                {'X-CSRF-Token': self.account['csrf']}, body={})
        self.assertEqual(status, 200)
        status, headers, value = self.call(token=self.token)
        self.assertEqual((status, value), (200, DENIED))
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.call(token='a' * 43)[2], DENIED)
        with patch.object(self.service, 'clock', return_value=self.service.clock() + SESSION_SECONDS + 1):
            self.assertEqual(self.call(token=self.other_token)[2], DENIED)

    def test_normal_id_allowlist_and_global_kill_switch_over_http(self):
        self.policy_path.write_text(json.dumps(config(emails=[], user_ids=[self.other['user']['id']])))
        self.http.routes.features = FeatureFlags(self.policy_path)
        self.assertTrue(self.call(token=self.other_token)[2]['features']['watch_tracking'])
        self.assertFalse(self.call(token=self.token)[2]['experimental_allowed'])
        self.policy_path.write_text(json.dumps(config(enabled=False)))
        self.http.routes.features = FeatureFlags(self.policy_path)
        self.assertEqual(self.call(token=self.token)[2], {**DENIED, 'user_id': self.account['user']['id']})

    def test_get_only_and_storage_failure_are_private_and_fail_closed(self):
        status, _, _ = self.call(token=self.token, body={'user_id': self.account['user']['id'], 'email': EMAIL})
        self.assertEqual(status, 405)
        with patch.object(self.service, 'identity', side_effect=OSError('private path')):
            with self.assertLogs(level='ERROR'):
                status, _, value = self.call(token=self.token)
        self.assertEqual(status, 503)
        self.assertNotIn('private path', json.dumps(value))
        self.assertNotIn('features', value)

    def test_secure_session_namespace_and_head_rejection(self):
        self.http.routes.https_only = True
        self.assertEqual(self.call(token=self.token)[2], DENIED, 'development cookies cannot authenticate a secure host')
        actual = self.call(headers={'Cookie': '__Host-couchside-session=' + self.token})[2]
        self.assertTrue(actual['features']['watch_tracking'])
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        connection.request('HEAD', '/api/features')
        response = connection.getresponse()
        self.assertEqual(response.status, 405)
        self.assertEqual(response.getheader('Cache-Control'), 'private, no-store')
        self.assertEqual(response.read(), b'')
        connection.close()

    def test_tracking_routes_reuse_session_csrf_eligibility_and_private_responses(self):
        from backend.tracking import TrackingService
        catalogue = {'id': 169, 'revision': 'catalogue-1', 'expiresAt': self.service.clock() + 600,
                     'ended': False, 'episodes': [{'id': 12192, 'season': 1, 'number': 1, 'airdate': '2008-01-20'}]}
        calls = []
        def provider(show_id):
            calls.append(show_id)
            return catalogue
        service = TrackingService(self.service, provider,
            authorize=lambda connection, row: self.http.routes.features.enabled_for(dict(row)))
        self.http.routes.tracking = lambda: service
        self.assertEqual(self.call('/api/tracking')[0], 401)
        self.assertEqual(self.call('/api/tracking', token=self.other_token)[0], 403)
        self.assertEqual(self.call('/api/tracking/catalogue?id=169', token=self.other_token)[0], 403)
        self.assertEqual(calls, [], 'unlisted accounts must never reach the catalogue provider')
        self.assertEqual(self.call('/api/tracking/catalogue?id=169', token=self.token)[2]['catalogue_revision'], 'catalogue-1')
        for path in ('/api/tracking/catalogue?id=0', '/api/tracking/catalogue?id=169&id=82',
                     '/api/tracking/catalogue?id=169&user_id=someone'):
            self.assertEqual(self.call(path, token=self.token)[0], 400)
        payload = {'operation_id': 'test-intent-0001', 'base_revision': 0, 'show_id': 169,
                   'action': 'intent', 'intent': 'watching', 'progress_known': True}
        self.assertEqual(self.call('/api/tracking', token=self.token, body=payload)[0], 403)
        status, _, body = self.call('/api/tracking', token=self.token,
                                  headers={'X-CSRF-Token': self.account['csrf']}, body=payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(body['tracking_revision'], 1)
        self.assertEqual(body['user_id'], self.account['user']['id'])
        self.assertEqual(self.call('/api/tracking', token=self.token)[2]['tracking'][0]['intent'], 'watching')
        self.http.routes.features = self.flags_disabled()
        self.assertEqual(self.call('/api/tracking', token=self.token)[0], 403)

    def flags_disabled(self):
        self.policy_path.write_text(json.dumps(config(enabled=False)))
        return FeatureFlags(self.policy_path)


if __name__ == '__main__':
    unittest.main()
