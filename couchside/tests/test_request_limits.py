
from pathlib import Path
import os
import sys

# Direct script runs and unittest discovery share the app package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest import TestCase, main
from unittest.mock import patch
from backend.request_limits import Budget, Requests, address

class LimitsTests(TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': ''})
        self.environment.start()
        self.addCleanup(self.environment.stop)
    def test_fixed_budget_recovers_and_addresses_are_independent(self):
        now=[0]
        budget=Budget(rate=2,burst=2,clock=lambda:now[0],most=3)
        self.assertEqual([budget.take('a') for _ in range(3)],[0,0,1])
        self.assertEqual(budget.take('b'),0)
        now[0]=.5
        self.assertEqual(budget.take('a'),0)
        for name in ('c','d','e'):budget.take(name)
        self.assertEqual(len(budget.clients),3)
    def test_only_local_proxy_headers_are_trusted(self):
        self.assertEqual(address('198.51.100.1','203.0.113.2'),'198.51.100.1')
        self.assertEqual(address('127.0.0.1','fake, 203.0.113.2'),'203.0.113.2')
        self.assertEqual(address('127.0.0.1','invalid'),'127.0.0.1')

    def test_only_configured_gateway_accepts_forwarded_clients(self):
        forwarded = '192.0.2.99, 203.0.113.2'
        self.assertEqual(address('172.16.0.1', forwarded), '172.16.0.1')
        with patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': '172.16.0.1, 2001:db8::1'}):
            self.assertEqual(address('172.16.0.1', forwarded), '203.0.113.2')
            self.assertEqual(address('172.16.0.2', forwarded), '172.16.0.2')
            self.assertEqual(address('10.0.0.1', forwarded), '10.0.0.1')
            self.assertEqual(address('198.51.100.1', forwarded), '198.51.100.1')
            self.assertEqual(address('2001:db8::1', '2001:db8::42'), '2001:db8::42')
            self.assertEqual(address('172.16.0.1', 'invalid'), '172.16.0.1')

    def test_invalid_proxy_configuration_fails_before_serving(self):
        for configured in ('172.16.0.0/12', '*', 'gateway.example', '172.16.0.1:8082'):
            with patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': configured}):
                with self.assertRaisesRegex(ValueError, 'exact IP addresses'):
                    Requests()

    def test_two_verified_proxies_walk_from_the_right_and_stop_at_the_client(self):
        with patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': '172.16.0.1,100.107.153.113'}):
            self.assertEqual(address('172.16.0.1', '192.0.2.99, 203.0.113.2, 100.107.153.113'), '203.0.113.2')
            # Private and other Tailscale addresses are clients unless explicitly
            # configured. Never skip a range or trust a spoofed leftmost value.
            for client in ('10.0.0.42', '172.16.0.2', '100.81.133.94'):
                self.assertEqual(address('172.16.0.1', f'192.0.2.99, {client}, 100.107.153.113'), client)
                self.assertEqual(address(client, '203.0.113.2, 100.107.153.113'), client)
            self.assertEqual(address('198.51.100.1', '203.0.113.2, 100.107.153.113'), '198.51.100.1')
            self.assertEqual(address('172.16.0.1', '203.0.113.2, invalid, 100.107.153.113'), '172.16.0.1')
            self.assertEqual(address('172.16.0.1', '172.16.0.1, 100.107.153.113'), '172.16.0.1')
            self.assertEqual(address('172.16.0.1', ''), '172.16.0.1')

    def test_mapped_ipv4_addresses_use_the_same_proxy_and_client_identity(self):
        with patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': '::ffff:172.16.0.1,100.107.153.113'}):
            self.assertEqual(address('172.16.0.1', '::ffff:203.0.113.2, ::ffff:100.107.153.113'), '203.0.113.2')
            self.assertEqual(address('::ffff:172.16.0.1', '203.0.113.2, 100.107.153.113'), '203.0.113.2')
            self.assertEqual(address('::ffff:198.51.100.1', '203.0.113.2'), '198.51.100.1')

    def test_configured_proxy_preserves_separate_clients_and_existing_budgets(self):
        with patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': '172.16.0.1'}):
            requests = Requests(Budget(rate=1, burst=1, clock=lambda: 0))
            self.assertEqual(requests.take('172.16.0.1', '203.0.113.1'), 0)
            self.assertGreater(requests.take('172.16.0.1', '203.0.113.1'), 0)
            self.assertEqual(requests.take('172.16.0.1', '203.0.113.2'), 0)
            self.assertEqual(requests.take('172.16.0.2', '203.0.113.3'), 0)
            self.assertGreater(requests.take('172.16.0.2', '203.0.113.4'), 0)
    def test_global_budget_cannot_be_bypassed_with_fresh_addresses(self):
        requests=Requests(Budget(rate=1,burst=2),Budget(rate=1,burst=1))
        self.assertEqual(requests.take('198.51.100.1'),0)
        self.assertGreater(requests.take('198.51.100.2'),0)
    def test_default_budget_accepts_independent_clients_without_fixed_global_ceiling(self):
        requests = Requests()
        self.assertTrue(all(requests.take(f'198.51.{i // 256}.{i % 256}') == 0 for i in range(1000)))

    def test_ten_thousand_active_identities_do_not_reset_an_exhausted_budget(self):
        budget = Budget(rate=1, burst=1, clock=lambda: 1000)
        self.assertEqual(budget.take('existing-client'), 0)
        self.assertGreater(budget.take('existing-client'), 0)
        for identity in range(10000):
            self.assertEqual(budget.take(str(identity)), 0)
        self.assertGreater(budget.take('existing-client'), 0)
        self.assertLessEqual(len(budget.clients), budget.most)

if __name__=='__main__':main()
