"""Metadata-cache and real HTTP accounting regressions; no sockets are opened."""
from collections import Counter
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import locustfile
import configargparse
import run
from protocol_metrics import ProtocolMetrics
from test_protocol import Client, Response
from workload import Configuration, SimulatedPublicCache, sorted_public_ids


def card(sid, **extra):
    return {'id': sid, 'name': f'Show {sid}', 'genres': ['Drama'], **extra}


def ratings(sid, **extra):
    return {'id': sid, 'fetchedAt': 900, 'expiresAt': 1200, 'episodes': [
        {'id': sid * 10, 'season': 1, 'number': 1, 'rating': 8.2,
         'name': 'Pilot', 'summary': 'Public episode summary', 'image': {'original': 'ignored'}}], **extra}


class MetadataEligibility(unittest.TestCase):
    def setUp(self):
        self.clock = 1000
        self.counts = Counter()
        self.cache = SimulatedPublicCache(now=lambda: self.clock, record=self.record)

    def record(self, kind, outcome, count):
        self.counts[f'{kind}.{outcome}'] += count

    def put(self, kind, values, version='v1', **extra):
        self.cache.put_batch(kind, [value['id'] for value in values],
                             {'shows': values, 'catalogueVersion': version, **extra})

    def test_valid_ids_are_deduplicated_and_numerically_sorted(self):
        self.assertEqual(sorted_public_ids([82, 2, 82, 123, 2.0, 0, True, '3', -1,
                                            2147483648, float('inf'), 10 ** 10000]), [2, 82, 123])

    def test_first_read_misses_repeated_read_hits_and_only_missing_ids_remain(self):
        self.assertEqual(self.cache.missing('card', [82, 2, 82]), [2, 82])
        self.put('card', [card(82), card(2)])
        self.assertEqual(self.cache.missing('card', [123, 82, 2, 2]), [123])
        self.assertEqual(self.counts['card.hit'], 2)
        self.assertEqual(self.counts['card.miss'], 3)

    def test_entries_retain_metadata_only_after_input_is_mutated(self):
        value = ratings(82)
        self.put('ratings', [value])
        value['episodes'][0]['rating'] = -5
        value['episodes'].append({'private': 'must not be retained'})
        self.assertEqual(self.cache.missing('ratings', [82]), [])
        entry = self.cache.entries[('ratings', 82)]
        self.assertEqual({field.name for field in fields(entry)},
                         {'at', 'expires', 'bytes', 'version', 'fetched_at'})
        self.assertFalse(any(isinstance(getattr(entry, field.name), (dict, list)) for field in fields(entry)))

    def test_source_expiry_and_five_minute_age_are_both_enforced(self):
        self.put('ratings', [ratings(82, expiresAt=1002)])
        self.put('card', [card(82, expiresAt=1001)])  # Browser card allowlist excludes source dates.
        self.clock = 1002
        self.assertEqual(self.cache.missing('ratings', [82]), [82])
        self.assertEqual(self.cache.missing('card', [82]), [])
        self.clock = 1300
        self.assertEqual(self.cache.missing('card', [82]), [82])
        self.assertEqual(self.cache.used_bytes, 0)

    def test_catalogue_version_invalidates_all_public_kinds(self):
        self.put('card', [card(82)])
        self.put('ratings', [ratings(82)])
        self.put('card', [card(2)], version='v2')
        self.assertEqual(self.cache.missing('ratings', [82]), [82])
        self.assertEqual(self.cache.missing('card', [82, 2]), [82])
        self.assertEqual(self.counts['card.version_invalidated'], 1)
        self.assertEqual(self.counts['ratings.version_invalidated'], 1)

    def test_pending_missing_refreshing_expired_and_failed_records_never_become_hits(self):
        self.cache.put_batch('ratings', [2, 82, 123, 169], {'catalogueVersion': 'v1',
            'shows': [ratings(2), ratings(82), ratings(123, refreshing=True), ratings(169, expiresAt=999)],
            'pending': [2], 'missing': [82]})
        self.assertEqual(self.cache.missing('ratings', [169, 123, 82, 2]), [2, 82, 123, 169])
        self.cache.put_batch('card', [82], None)
        self.cache.put_batch('card', [82], {'shows': 'invalid'})
        self.assertEqual(self.cache.missing('card', [82]), [82])
        self.assertEqual(self.counts['ratings.pending'], 1)
        self.assertEqual(self.counts['card.failed_batch'], 1)
        self.assertEqual(self.counts['card.invalid_batch'], 1)

    def test_malformed_episode_metadata_is_a_miss_without_crashing_the_journey(self):
        mutations = ({'id': True}, {'season': 0}, {'number': 1.2}, {'rating': -1},
                     {'rating': 11}, {'rating': float('nan')}, {'rating': '8'},
                     {'id': 2147483648}, {'season': 10 ** 10000})
        for mutation in mutations:
            with self.subTest(mutation=list(mutation)):
                value = ratings(82)
                value['episodes'][0].update(mutation)
                self.put('ratings', [value])
                self.assertEqual(self.cache.missing('ratings', [82]), [82])
        self.put('card', [{'id': 82, 'name': None}])
        self.assertEqual(self.cache.missing('card', [82]), [82])

    def test_empty_completed_ratings_are_valid_but_compact_matrices_are_not(self):
        self.put('ratings', [ratings(82, episodes=[])])
        self.assertEqual(self.cache.missing('ratings', [82]), [])
        self.cache.put_batch('ratings', [2], {'shows': [{'id': 2, 'seasons': [1]}]})
        self.assertEqual(self.cache.missing('ratings', [2]), [2])

    def test_record_budget_and_byte_budget_evict_least_recently_used(self):
        self.cache.max_records = 2
        self.put('card', [card(2), card(82)])
        self.assertEqual(self.cache.missing('card', [2]), [])
        self.put('card', [card(123)])
        self.assertEqual(set(self.cache.entries), {('card', 2), ('card', 123)})
        self.cache.max_bytes = self.cache.entries[('card', 123)].bytes + 1
        self.put('card', [card(169)])
        self.assertLessEqual(self.cache.used_bytes, self.cache.max_bytes)
        self.assertEqual(set(self.cache.entries), {('card', 169)})
        self.assertGreaterEqual(self.counts['card.evicted'], 2)

    def test_oversized_and_unrequested_records_are_not_retained(self):
        self.cache.max_bytes = 500
        self.put('card', [card(82, summary='x' * 501)])
        self.assertEqual(self.cache.missing('card', [82]), [82])
        self.cache.put_batch('card', [82], {'shows': [card(2)], 'catalogueVersion': 'v1'})
        self.assertFalse(self.cache.entries)

    def test_old_provider_snapshot_cannot_replace_newer_fetched_data(self):
        self.put('ratings', [ratings(82, fetchedAt=990, expiresAt=1250)])
        original = self.cache.entries[('ratings', 82)]
        self.put('ratings', [ratings(82, fetchedAt=950, expiresAt=1100)])
        self.assertIs(self.cache.entries[('ratings', 82)], original)
        self.assertEqual(self.counts['ratings.older_record'], 1)


class ComparisonProtocolFlow(unittest.TestCase):
    def setUp(self):
        self.previous = locustfile.RUNTIME
        self.metrics = locustfile.RUNTIME = ProtocolMetrics(Configuration(retry_attempts=0, simulate_public_cache=True))
        self.user = object.__new__(locustfile.CouchsideUser)
        self.user.headers = {}
        self.user.public_cache = SimulatedPublicCache(record=self.metrics.record_public_cache)
        self.user.persona = SimpleNamespace(random=SimpleNamespace(random=lambda: 1),
                                           comparison=lambda: ([82, 2, 82], '/compare?compare=82,2,82'))

    def tearDown(self):
        locustfile.RUNTIME = self.previous

    @staticmethod
    def ids(call):
        return parse_qs(urlsplit(call[1]).query)['ids'][0]

    def test_cache_avoids_only_reused_public_batches_without_synthetic_http_successes(self):
        expiry = self.user.public_cache.now() + 200
        self.user.client = Client([Response(200, {'shows': [card(82), card(2)], 'catalogueVersion': 'v1'}),
                                  Response(200, {'shows': [ratings(82, expiresAt=expiry), ratings(2, expiresAt=expiry)],
                                                 'catalogueVersion': 'v1'})])
        self.user.compare()
        self.user.compare()
        self.assertEqual([self.ids(call) for call in self.user.client.calls], ['2,82', '2,82'])
        summary = self.metrics.summary()
        self.assertEqual(summary['definitive_request_counts']['total'], 2)
        self.assertEqual(summary['request_latency']['api_successful']['count'], 2)
        self.assertIsNone(summary['browser_cache_hits'])
        self.assertEqual(summary['simulated_public_cache']['counters']['card.hit'], 2)
        self.assertEqual(summary['simulated_public_cache']['counters']['ratings.request_avoided'], 1)

    def test_partial_reuse_requests_sorted_missing_ids_for_each_kind(self):
        self.user.public_cache.put_batch('card', [82], {'shows': [card(82)], 'catalogueVersion': 'v1'})
        self.user.client = Client([Response(200, {'shows': [card(2)], 'catalogueVersion': 'v1'}),
                                  Response(200, {'shows': [], 'pending': [82, 2], 'catalogueVersion': 'v1'})])
        self.user.compare()
        self.assertEqual([self.ids(call) for call in self.user.client.calls], ['2', '2,82'])
        self.assertEqual(self.metrics.simulated_public_cache['ratings.pending'], 2)

    def test_failed_response_is_measured_and_remains_a_miss_next_time(self):
        self.user.client = Client([Response(503, {'error': 'busy'}),
                                  Response(200, {'shows': [], 'pending': [82, 2]}),
                                  Response(200, {'shows': [card(82), card(2)]}),
                                  Response(200, {'shows': [], 'pending': [82, 2]})])
        self.user.compare()
        self.user.compare()
        self.assertEqual(len(self.user.client.calls), 4)
        self.assertEqual(self.metrics.summary()['definitive_request_counts']['failed'], 1)
        self.assertEqual(self.metrics.simulated_public_cache['card.failed_batch'], 1)
        self.assertEqual(self.metrics.simulated_public_cache['ratings.request_avoided'], 0)

    def test_api_diagnostic_mode_always_sends_sorted_full_ids(self):
        self.metrics.config = Configuration(retry_attempts=0)
        self.user.public_cache = None
        self.user.client = Client([Response(200, {'shows': []}) for _ in range(4)])
        self.user.compare()
        self.user.compare()
        self.assertEqual([self.ids(call) for call in self.user.client.calls], ['2,82'] * 4)
        self.assertEqual(self.metrics.summary()['definitive_request_counts']['total'], 4)
        self.assertFalse(self.metrics.summary()['simulated_public_cache']['enabled'])
        self.assertEqual(self.metrics.simulated_public_cache, {})

    def test_private_and_personal_requests_still_execute_with_a_reused_public_cache(self):
        self.user.persona.body = lambda **extra: {'profile': {'ids': [], 'weights': ''}, **extra}
        self.user.client = Client([Response(200, {'rows': []}), Response(200, {'shows': []}),
                                  Response(401, {'error': 'guest'})])
        self.user.post('/api/home', 'home/feed')
        self.user.request('POST', '/api/shows', 'guest/list-show-lookup', {'ids': [82]})
        self.user.request('GET', '/api/account/session', 'account/session', expected_status=(401,))
        self.assertEqual([call[1] for call in self.user.client.calls],
                         ['/api/home', '/api/shows', '/api/account/session'])
        self.assertEqual(self.metrics.summary()['definitive_request_counts']['total'], 3)
        self.assertEqual(self.metrics.simulated_public_cache, {})

    def test_separate_users_do_not_share_simulated_entries(self):
        self.user.public_cache.put_batch('card', [82], {'shows': [card(82)]})
        other = SimulatedPublicCache(record=self.metrics.record_public_cache)
        self.assertEqual(self.user.public_cache.missing('card', [82]), [])
        self.assertEqual(other.missing('card', [82]), [82])


class OptInConfiguration(unittest.TestCase):
    def test_locust_flag_is_disabled_by_default_and_enabled_explicitly(self):
        parser = configargparse.ArgumentParser()
        locustfile.add_options(parser)
        with patch.dict('os.environ', {}, clear=True):
            for arguments, expected in (([], False), (['--workload-simulate-public-cache'], True)):
                with self.subTest(arguments=arguments):
                    environment = SimpleNamespace(parsed_options=parser.parse_args(arguments),
                                                  runner=None, host='http://localhost:18120')
                    self.assertIs(locustfile.configuration(environment).simulate_public_cache, expected)

    def test_launcher_forwards_only_the_explicit_cache_mode_and_keeps_load_settings(self):
        args = SimpleNamespace(locust_python='/isolated/python', origin='http://localhost:18120',
                               seed=123, max_inflight=256, think_min=3, think_max=12,
                               auth_fraction=.2, accounts=None, gateway_key_path=None,
                               media=True, simulate_public_cache=False)
        stage = {'target_users': 10000, 'spawn_per_second': 500,
                 'run_seconds': 90, 'connection_model': 'pooled'}
        ordinary = run.locust_command(args, stage, 1, Path('/isolated/results'))
        self.assertNotIn('--workload-simulate-public-cache', ordinary)
        args.simulate_public_cache = True
        simulated = run.locust_command(args, stage, 1, Path('/isolated/results'))
        self.assertEqual(simulated, ordinary + ['--workload-simulate-public-cache'])
        for name, value in (('--users', '10000'), ('--spawn-rate', '500'),
                            ('--workload-max-inflight', '256'), ('--workload-connection-model', 'pooled')):
            self.assertEqual(simulated[simulated.index(name) + 1], value)


if __name__ == '__main__':
    unittest.main()
