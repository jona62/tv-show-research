"""Computed answer isolation, bounded retention, freshness keys and vector parity."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
import json
import os
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'couchside'))
from backend.recommendation.response_cache import Answers, response
from backend.recommendation import engine as ranking
from backend.recommendation.library import Taste, Library


class AnswerTests(TestCase):
    def test_explicit_reset_prevents_older_inflight_work_from_republishing(self):
        answers = Answers()
        entered, release = threading.Event(), threading.Event()
        def old():
            entered.set()
            self.assertTrue(release.wait(2))
            return {'revision': 'old'}
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(answers.get, 'same', old)
            self.assertTrue(entered.wait(1))
            answers.clear()
            self.assertEqual(answers.get('same', lambda: {'revision': 'new'}), {'revision': 'new'})
            release.set()
            self.assertEqual(pending.result(2), {'revision': 'old'})
        self.assertEqual(answers.get('same', lambda: self.fail('Reuse the new generation')), {'revision': 'new'})
        self.assertEqual(answers.bytes, sum(len(value[1]) for value in answers.kept.values()))

    def test_added_sort_retains_personalized_order_and_excludes_zero_scores(self):
        library = SimpleNamespace(ids=[82, 169, 396], rules={'sort': 'added'},
                                  discovery=SimpleNamespace(order=lambda items, rules: items))
        taste = SimpleNamespace(lib=library, candidates=[0, 1, 2], scores=[.2, .8, 0.])
        self.assertEqual(Taste.ranked(taste), [1, 0])

    def test_environment_capacity_is_opt_in_bounded_and_invalid_values_keep_defaults(self):
        names = ('COUCHSIDE_RECOMMENDATION_CACHE_ENTRIES', 'COUCHSIDE_RECOMMENDATION_CACHE_MB')
        with patch.dict(os.environ, {name: '' for name in names}):
            defaults = Answers()
            self.assertEqual((defaults.most, defaults.max_bytes), (1024, 32 * 1024 * 1024))
        with patch.dict(os.environ, dict(zip(names, ('10000', '128')))):
            configured = Answers()
            self.assertEqual((configured.most, configured.max_bytes), (10000, 128 * 1024 * 1024))
            explicit = Answers(most=2, max_bytes=25)
            self.assertEqual((explicit.most, explicit.max_bytes), (2, 25))
        with patch.dict(os.environ, dict(zip(names, ('900000', '900000')))):
            bounded = Answers()
            self.assertEqual((bounded.most, bounded.max_bytes), (50000, 512 * 1024 * 1024))
        with patch.dict(os.environ, dict(zip(names, ('-1', 'unlimited')))):
            invalid = Answers()
            self.assertEqual((invalid.most, invalid.max_bytes), (1024, 32 * 1024 * 1024))

    def test_readers_and_http_decorators_cannot_change_cached_answers(self):
        answers = Answers()
        original = answers.get('same', lambda: {'shows': [{'id': 82}]})
        original['shows'][0]['private_decoration'] = True
        restored = answers.get('same', lambda: self.fail('An unchanged request should reuse computation'))
        self.assertEqual(restored, {'shows': [{'id': 82}]})
        restored['shows'].clear()
        self.assertEqual(answers.get('same', lambda: None), {'shows': [{'id': 82}]})

    def test_recent_entries_survive_lru_eviction_and_byte_budget_is_exact(self):
        answers = Answers(most=2, max_bytes=25)
        answers.get('a', lambda: {'id': 1})
        answers.get('b', lambda: {'id': 2})
        answers.get('a', lambda: None)
        answers.get('c', lambda: {'id': 3})
        self.assertEqual(list(answers.kept), ['a', 'c'])
        self.assertEqual(answers.bytes, sum(len(value[1]) for value in answers.kept.values()))
        answers.get('huge', lambda: {'text': 'x' * 100})
        self.assertNotIn('huge', answers.kept)
        self.assertLessEqual(answers.bytes, 25)

    def test_expired_answers_and_failed_computation_are_not_reused(self):
        now = [100.]
        answers = Answers(ttl=10, clock=lambda: now[0])
        answers.get('a', lambda: {'id': 1})
        now[0] += 11
        self.assertEqual(answers.get('a', lambda: {'id': 2}), {'id': 2})
        with self.assertRaises(ValueError):
            answers.get('error', lambda: (_ for _ in ()).throw(ValueError('invalid state')))
        self.assertFalse(answers.pending)
        self.assertNotIn('error', answers.kept)

    def test_concurrent_readers_compute_once_and_receive_independent_objects(self):
        entered, release = threading.Event(), threading.Event()
        answers = Answers()
        def calculate():
            entered.set()
            self.assertTrue(release.wait(2))
            return {'shows': [82]}
        with ThreadPoolExecutor(max_workers=8) as workers:
            futures = [workers.submit(answers.get, 'same', calculate) for _ in range(8)]
            self.assertTrue(entered.wait(1))
            deadline = time.monotonic() + 1
            while answers.coalesced < 7 and time.monotonic() < deadline:
                time.sleep(.002)
            release.set()
            values = [future.result(2) for future in futures]
        self.assertEqual(answers.misses, 1)
        self.assertEqual(answers.coalesced, 7)
        values[0]['shows'].append(169)
        self.assertTrue(all(value == {'shows': [82]} for value in values[1:]))

    def test_every_personalization_input_and_metadata_revision_partition_answers(self):
        class Library:
            e, ahead, rules = object(), False, {}
            discovery = SimpleNamespace(store=SimpleNamespace(revision=0))
            answers = Answers()
            calls = 0
            @response
            def home(self, body):
                self.calls += 1
                return {'body': body, 'rules': self.rules}
        library = Library()
        body = {'profile': [{'id': 82, 'weight': 1}], 'settings': {'known_min': 85},
                'list': [169], 'seed': 'a', 'day': '2026-10-03', 'visit': 'b'}
        first = library.home(body)
        self.assertEqual(library.home(json.loads(json.dumps(body))), first)
        self.assertEqual(library.calls, 1)
        for key, value in [('profile', [{'id': 82, 'weight': 0}]), ('settings', {'known_min': 60}),
                           ('list', []), ('seed', 'c'), ('day', '2026-10-04'), ('visit', 'd'),
                           ('seen', {'82': 3}), ('shown', [{'key': 'row'}]), ('count', 4)]:
            library.home({**body, key: value})
        self.assertEqual(library.calls, 10)
        library.rules = {'genres': ['Medical']}
        library.home(body)
        library.discovery.store.revision += 1
        library.home(body)
        self.assertEqual(library.calls, 12)


class VectorParityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ranking.Engine(ROOT / 'data/model')

    def test_queued_foreground_skips_speculation_and_pagination_matches_quiet_load(self):
        library = Library(self.engine, ROOT / 'couchside/assets/model/art.bin.gz')
        body = {'profile': [{'id': 82, 'weight': 1}, {'id': 169, 'weight': .7}],
                'settings': {}, 'day': '2026-10-03', 'seed': '1111111111111111'}
        library.can_keep_ahead = lambda: False
        first = library.home(body)
        self.assertFalse(library.kept)
        shown = [{'key': row['key'], 'ids': [show['id'] for show in row.get('items', [])[:6]],
                  'tier': row.get('tier', 0)} for row in first['rows']]
        on_demand = library.home({**body, 'shown': shown})
        library.kept.clear()
        library.answers.clear()
        library.can_keep_ahead = lambda: True
        self.assertEqual(library.home(body), first)
        page = next(iter(library.kept.values()))
        self.assertTrue(page.ready.wait(5))
        self.assertEqual(library.home({**body, 'shown': shown}), on_demand)

    def test_native_closeness_is_bit_exact_to_scalar_for_default_and_custom_weights(self):
        engine = self.engine
        for sid in (82, 169, 396):
            for weights in ((45, 30, 25, 35), (70, 10, 20, 0)):
                engine.components.cache_clear()
                engine.blended.cache_clear()
                native = engine.blended(engine.by_id[sid], *weights).tobytes()
                with patch.object(ranking, 'np', None):
                    engine.components.cache_clear()
                    engine.blended.cache_clear()
                    scalar = engine.blended(engine.by_id[sid], *weights).tobytes()
                self.assertEqual(native, scalar)

    def test_native_interest_ranking_matches_scalar_scale_exclusions_and_later_scores(self):
        engine = self.engine
        profile = [{'id': 82, 'weight': 1}, {'id': 169, 'weight': .7}, {'id': 396, 'weight': 1}, {'id': 123, 'weight': -1}]
        candidates = [i for i, show in enumerate(engine.shows) if engine.popularity[i] >= 85 and show['id'] not in {p['id'] for p in profile}]
        def score():
            aff = ranking.Closeness(engine, ranking.DEFAULT_SETTINGS)
            result = engine.ranking(profile[:-1], profile[-1:], aff, ranking.DEFAULT_SETTINGS)
            initial = result.score(candidates)
            later = result.score([engine.by_id[82], engine.by_id[123]])
            return initial.tobytes(), later.tobytes(), result.group
        native = score()
        with patch.object(ranking, 'np', None):
            scalar = score()
        self.assertEqual(native, scalar)


if __name__ == '__main__':
    main()
