"""Run with the isolated load-test interpreter; these tests never send traffic."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import locustfile
from protocol_metrics import ProtocolMetrics
from workload import Configuration, Persona


class Response:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.headers = headers
        self.content = json.dumps(body).encode() if body is not None else None
        self.result = None

    def json(self):
        return json.loads(self.content)

    def success(self):
        self.result = True

    def failure(self, value):
        self.result = Exception(value)


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    @contextmanager
    def request(self, method, path, **arguments):
        self.calls.append((method, path, arguments))
        response = self.responses.pop(0)
        yield response
        error = response.result if isinstance(response.result, Exception) else None
        locustfile.measured_request(123, response, error, arguments['context'])


class ProtocolAccounting(unittest.TestCase):
    def setUp(self):
        self.previous = locustfile.RUNTIME
        self.metrics = locustfile.RUNTIME = ProtocolMetrics(Configuration(retry_attempts=0))
        self.user = object.__new__(locustfile.CouchsideUser)
        self.user.headers = {}
        self.user.persona = Persona(self.metrics.config, 0)

    def tearDown(self):
        locustfile.RUNTIME = self.previous

    def test_transport_failure_without_headers_is_counted_and_releases_the_gate(self):
        self.user.client = Client([Response(0)])
        self.assertIsNone(self.user.request('GET', '/api/search?q=test', 'transport'))
        self.assertEqual(self.metrics.requests, 1)
        self.assertEqual(self.metrics.statuses, {'0': 1})
        self.assertEqual(self.metrics.summary()['request_latency']['failed']['count'], 1)
        self.assertEqual(self.metrics.summary()['definitive_request_counts']['total'], 1)
        self.assertEqual(self.metrics.summary()['definitive_request_counts']['failed'], 1)
        self.assertEqual(self.metrics.active, 0)

    def test_safe_retry_keeps_the_failure_separate_from_the_successful_response(self):
        self.metrics.config = Configuration(retry_attempts=1)
        self.user.client = Client([Response(429, {'error': 'busy'}, {'Retry-After': '2'}),
                                   Response(200, {'shows': []}, {})])
        with patch.object(locustfile.gevent, 'sleep') as sleep:
            self.assertEqual(self.user.request('GET', '/api/search?q=test', 'retry'), {'shows': []})
        self.assertGreaterEqual(sleep.call_args.args[0], 2)
        self.assertEqual(self.metrics.statuses, {'429': 1, '200': 1})
        latency = self.metrics.summary()['request_latency']
        self.assertEqual(latency['failed']['count'], 1)
        self.assertEqual(latency['api_successful']['count'], 1)
        self.assertEqual(self.metrics.retries, 1)

    def test_account_writes_are_never_automatically_retried(self):
        self.metrics.config = Configuration(retry_attempts=2)
        self.user.client = Client([Response(503, {'error': 'busy'}, {})])
        self.assertIsNone(self.user.request('POST', '/api/account/state', 'write', {}, retry=False))
        self.assertEqual(len(self.user.client.calls), 1)
        self.assertEqual(self.metrics.retries, 0)

    def test_guest_session_401_has_its_own_expected_latency_bucket(self):
        self.user.client = Client([Response(401, {'error': 'sign in'}, {})])
        self.user.request('GET', '/api/account/session', 'guest', expected_status=(401,))
        self.assertEqual(self.metrics.statuses, {'401_expected': 1})
        latency = self.metrics.summary()['request_latency']
        self.assertEqual(latency['expected_non_2xx']['count'], 1)
        self.assertEqual(latency['failed']['count'], 0)
        self.assertEqual(self.metrics.summary()['definitive_request_counts'],
                         {'total': 1, 'successful_2xx': 0, 'failed': 0, 'expected_non_2xx': 1,
                          'api_successful_2xx': 0})

    def test_exact_peak_survives_slower_snapshots_and_differs_from_started_users(self):
        self.metrics.users.update(guest=8000, authenticated=2000)
        locustfile.spawned_users(10000)
        environment = SimpleNamespace(runner=SimpleNamespace(user_count=9974),
                                      stats=SimpleNamespace(total=SimpleNamespace(current_rps=0, num_failures=0)))
        self.metrics.capture(environment)
        summary = self.metrics.summary()
        self.assertEqual(summary['peak_virtual_users'], 10000)
        self.assertEqual(summary['started_virtual_users'], 10000)
        self.assertEqual(summary['samples'][-1]['virtual_users'], 9974)


if __name__ == '__main__':
    unittest.main()
