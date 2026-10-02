from unittest import TestCase, main
from request_limits import Budget, Requests, address

class LimitsTests(TestCase):
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
    def test_global_budget_cannot_be_bypassed_with_fresh_addresses(self):
        requests=Requests(Budget(rate=1,burst=2),Budget(rate=1,burst=1))
        self.assertEqual(requests.take('198.51.100.1'),0)
        self.assertGreater(requests.take('198.51.100.2'),0)

if __name__=='__main__':main()
