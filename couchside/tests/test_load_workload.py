"""Traffic reproducibility, realistic list payloads and isolated-identity restrictions."""
from collections import Counter
import importlib.util
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit


TOOLS = Path(__file__).resolve().parents[1] / 'tools/loadtest'
SPEC = importlib.util.spec_from_file_location('couchside_load_workload', TOOLS / 'workload.py')
workload = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workload
SPEC.loader.exec_module(workload)


class RandomizedLoadWorkload(unittest.TestCase):
    def test_seeded_personas_have_repeatable_choices_without_synchronized_users(self):
        config = workload.Configuration()
        first, again, other = (workload.Persona(config, index) for index in (71, 71, 72))
        capture = lambda user: [(user.journey(), user.show(), user.query(), user.comparison()) for _ in range(100)]
        sequence = capture(first)
        self.assertEqual(sequence, capture(again))
        self.assertNotEqual(sequence, capture(other))
        self.assertEqual(set(name for name, *_rest in sequence), set(workload.JOURNEYS))

    def test_journey_mix_covers_every_weighted_surface(self):
        user = workload.Persona(workload.Configuration(), 18)
        counts = Counter(user.journey() for _ in range(10000))
        self.assertEqual(set(counts), set(workload.JOURNEYS))
        for name, weight in workload.JOURNEYS.items():
            self.assertLess(abs(counts[name] / 10000 - weight / 100), .015)

    def test_comparisons_are_unique_and_include_long_short_and_unrelated_pools(self):
        user = workload.Persona(workload.Configuration(), 81)
        pairs, modes, views, long_shows = set(), set(), set(), set()
        for _ in range(200):
            ids, route = user.comparison()
            self.assertGreaterEqual(len(ids), 2)
            self.assertLessEqual(len(ids), 5)
            self.assertEqual(len(ids), len(set(ids)))
            params = parse_qs(urlsplit(route).query)
            self.assertEqual(params['compare'][0], ','.join(map(str, ids)))
            modes.update(params['mode'])
            views.update(params['compare-view'])
            long_shows.update(set(ids) & {1505, 2103})
            pairs.add(tuple(sorted(ids)))
        self.assertEqual(modes, {'all', 'single'})
        self.assertEqual(views, {'grid', 'timeline'})
        self.assertEqual(long_shows, {1505, 2103})
        self.assertGreater(len(pairs), 80)

    def test_guest_list_model_and_compact_payload_preserve_all_ratings(self):
        user = workload.Persona(workload.Configuration(), 100)
        for _ in range(500):
            user.edit_list()
        body, state = user.body(), user.state()
        self.assertEqual(len(body['profile']['ids']), len(body['profile']['weights']))
        self.assertEqual(len(state['profile']), len({p['id'] for p in state['profile']}))
        self.assertEqual(body['list'], [show['id'] for show in state['saved']])
        restored = workload.Persona(workload.Configuration(), 101)
        restored.absorb(state)
        self.assertEqual(restored.state(), state)

    def test_authenticated_users_are_spread_through_every_stage_with_unique_accounts(self):
        for population in (100, 1000, 10000):
            chosen = [workload.account_assignment(index, .2) for index in range(population)]
            accounts = [index for index in chosen if index is not None]
            self.assertEqual(len(accounts), population // 5)
            self.assertEqual(accounts, list(range(population // 5)))
            self.assertEqual([index for index, account in enumerate(chosen) if account is not None][:3], [4, 9, 14])
        self.assertIsNone(workload.account_assignment(8, 0))
        self.assertEqual(workload.account_assignment(8, 1), 8)

    def test_home_pagination_sends_only_six_visible_show_ids_per_row(self):
        rows = [{'key': 'popular', 'items': [{'id': sid} for sid in range(1, 21)]},
                {'key': 'more', 'tier': 1, 'items': [{'id': 23}]}]
        shown = workload.shown_rows(rows)
        self.assertEqual(shown, [{'key': 'popular', 'ids': [1, 2, 3, 4, 5, 6], 'tier': 0},
                                 {'key': 'more', 'ids': [23], 'tier': 1}])

    def test_isolated_synthetic_proxy_identities_never_accept_remote_targets(self):
        config = workload.Configuration(synthetic_identities=True)
        for host, isolated in (('https://couchside.example', True), ('http://127.0.0.1:18099', False),
                               ('http://localhost.evil.test', True), ('http://10.0.0.1:18099', True)):
            with self.subTest(host=host, isolated=isolated), self.assertRaises(ValueError):
                config.validate(host, isolated=isolated)
        for host in ('http://127.0.0.1:18099', 'http://localhost:18099', 'http://[::1]:18099'):
            config.validate(host, isolated=True)

    def test_invalid_load_configuration_fails_before_sending_requests(self):
        for options in ({'think_min': -1}, {'think_min': 12, 'think_max': 3},
                        {'max_inflight': 0}, {'warm_probability': 2}, {'auth_fraction': -1}, {'retry_attempts': 3},
                        {'worker_count': 0}, {'worker_index': 2, 'worker_count': 2},
                        {'connection_model': 'invalid'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                workload.Configuration(**options).validate('http://localhost:18099')

    def test_pooled_connections_require_an_explicitly_isolated_local_target(self):
        config = workload.Configuration(connection_model='pooled')
        config.validate('http://localhost:18099', isolated=True)
        for host, isolated in (('https://public.example', True), ('http://localhost:18099', False)):
            with self.subTest(host=host, isolated=isolated), self.assertRaises(ValueError):
                config.validate(host, isolated=isolated)


if __name__ == '__main__':
    unittest.main()
