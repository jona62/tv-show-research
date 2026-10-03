"""Public batches preserve complete episodes, cache only finished data and coalesce work."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
import gzip
import json
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.episode_store import DAY, Store, Episodes, merge
from backend.public_api import PublicAPI, CARDS, RATINGS
from backend.public_data import CacheBusy, PreparedCache, prepare


EPISODES = [
    {'id': 100, 'season': 1, 'number': 1, 'name': 'Pilot', 'rating': 8.1,
     'airdate': '2020-01-01', 'runtime': 60, 'summary': '<p>A full summary.</p>',
     'image': {'original': 'https://images.example/100.jpg'}},
    {'id': 101, 'season': 1, 'number': 2, 'name': 'Unrated', 'rating': None,
     'airdate': '2020-01-08', 'runtime': 42, 'summary': 'Another full summary.', 'image': None},
]


class Library:
    def __init__(self):
        self.e = SimpleNamespace(by_id={1: 0, 2: 1, 3: 2})
        self.calls = 0

    def cards(self, ids):
        self.calls += 1
        return [{'id': show_id, 'name': f'Show {show_id}', 'poster': 'https://images.example/poster.jpg'} for show_id in ids]


class PublicAPITests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000.0
        self.clock = lambda: self.now
        self.store = Store(Path(self.folder.name) / 'episodes.sqlite3', clock=self.clock)
        self.addCleanup(self.store.db.close)
        self.ratings = Episodes(self.store, SimpleNamespace(), clock=self.clock)
        self.library = Library()
        self.cache = PreparedCache(clock=self.clock)
        self.api = PublicAPI(self.library, self.ratings, 'model-one', cache=self.cache)

    def save(self, show_id=1, episodes=EPISODES, scores=None):
        scores = scores or {}
        return self.store.put(show_id, {'id': show_id, 'tvmaze': episodes,
                                       'episodes': merge(episodes, scores), 'tmdb': scores, 'tmdb_at': self.now})

    def request(self, path=RATINGS, ids='1'):
        return self.api.get(path, {'ids': [ids]})

    def test_complete_batch_preserves_ids_descriptions_images_and_missing_scores(self):
        self.save(1)
        self.save(2)
        response = self.request(ids='2,1,2')
        body = json.loads(response.body)
        self.assertEqual([row['id'] for row in body['shows']], [2, 1])
        first = body['shows'][0]
        self.assertEqual(first['episodes'][0]['id'], 100)
        self.assertEqual(first['episodes'][0]['summary'], EPISODES[0]['summary'])
        self.assertEqual(first['episodes'][0]['image'], EPISODES[0]['image'])
        self.assertIsNone(first['episodes'][1]['rating'])
        self.assertIsNone(first['episodes'][1]['rating_source'])
        self.assertEqual(first['fetchedAt'], self.now)
        self.assertEqual(first['expiresAt'], self.now + DAY)
        self.assertTrue(first['revision'])
        self.assertEqual(body['catalogueVersion'], 'model-one')
        self.assertEqual(response.cache_control, 'public, max-age=300')
        self.assertEqual(len(self.cache.entries), 1)

    def test_legacy_singleton_and_matrix_do_not_mark_stale_tvmaze_as_fresh(self):
        self.save(1)
        single = self.ratings.get(1)
        batched = self.ratings.batch([1])['shows'][0]
        self.assertEqual(single, batched)
        self.assertFalse(single['refreshing'])
        self.now += DAY + 1
        single = self.ratings.get(1)
        matrix = self.ratings.matrices([1])['shows'][0]
        self.assertTrue(single['refreshing'])
        self.assertTrue(matrix['refreshing'])
        self.assertLess(single['expiresAt'], self.now)
        self.assertEqual(single['episodes'][0]['summary'], EPISODES[0]['summary'])
        self.assertEqual(self.store.next_demand('tvmaze'), 1)

    def test_pending_unknown_and_valid_records_coexist_without_provider_calls(self):
        self.save(1)
        response = self.request(ids='1,2,999')
        body = json.loads(response.body)
        self.assertEqual([row['id'] for row in body['shows']], [1])
        self.assertEqual(body['pending'], [2])
        self.assertEqual(body['missing'], [999])
        self.assertIn(2, self.ratings.pending)
        self.assertEqual(response.cache_control, 'no-store')
        self.assertFalse(self.cache.entries)
        self.save(2)
        response = self.request(ids='1,2')
        self.assertEqual(response.max_age, 300)

    def test_cards_use_only_public_catalog_and_preserve_valid_ids_with_missing(self):
        response = self.request(CARDS, '2,999,1')
        self.assertEqual(json.loads(response.body)['missing'], [999])
        self.assertEqual([row['id'] for row in json.loads(response.body)['shows']], [2, 1])
        self.assertEqual(response.cache_control, 'no-store')
        response = self.request(CARDS, '2,1')
        self.request(CARDS, '2,1')
        self.assertEqual(self.library.calls, 2)
        self.assertNotIn('profile', json.loads(response.body))
        with self.assertRaises(ValueError):
            self.api.get(CARDS, {'ids': ['1'], 'profile': ['private']})

    def test_cached_newer_card_callback_preserves_order_and_excludes_private_fields(self):
        def newer(ids):
            self.assertEqual(ids, (9, 10))
            return [{'id': 9, 'name': 'New series', 'poster': 'https://images.example/new.jpg',
                     'csrf': 'private', 'profile': [1], 'match': 99},
                    {'id': 900, 'name': 'Unrequested series'}]
        self.api.cards_for_missing = newer
        response = self.request(CARDS, '9,1,10')
        body = json.loads(response.body)
        self.assertEqual([show['id'] for show in body['shows']], [9, 1])
        self.assertEqual(body['missing'], [10])
        self.assertIsNone(body['shows'][0]['match'])
        self.assertNotIn('csrf', response.body.decode())
        self.assertNotIn('profile', response.body.decode())
        self.api.cards_for_missing = lambda ids: [{'id': 9, 'name': 'First title'}]
        first = self.request(CARDS, '1,9')
        self.assertEqual(first.max_age, 300)
        self.api.cards_for_missing = lambda ids: [{'id': 9, 'name': 'Updated title'}]
        second = self.request(CARDS, '1,9')
        self.assertNotEqual(first.etag, second.etag)

    def test_invalid_ids_are_rejected_before_reading_data(self):
        for value in ('', '0', '-1', '01', '1.0', '1,', '9999999999', ','.join(['1'] * 41)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request(ids=value)
        with self.assertRaises(ValueError):
            self.api.get(CARDS, {'ids': ['1', '2']})
        self.assertIsNone(self.api.get('/api/account/session', {}))
        self.assertFalse(self.library.calls)

    def test_rating_change_without_summary_change_invalidates_prepared_response(self):
        self.save()
        first = self.request()
        counts_revision = self.store.revision
        self.now += 1
        self.save(scores={'1:1': {'rating': 9.3, 'votes': 30, 'airdate': '2020-01-01'}})
        second = self.request()
        self.assertEqual(self.store.revision, counts_revision)
        self.assertNotEqual(first.etag, second.etag)
        one, two = json.loads(first.body)['shows'][0], json.loads(second.body)['shows'][0]
        self.assertNotEqual(one['revision'], two['revision'])
        self.assertEqual(two['episodes'][0]['rating'], 9.3)
        self.assertEqual(two['episodes'][0]['rating_source'], 'TMDB')

    def test_other_worker_recency_live_details_and_unrelated_ratings_preserve_cached_records(self):
        self.save(1)
        self.save(2)
        self.now += 3601
        writer = Store(Path(self.folder.name) / 'episodes.sqlite3', clock=self.clock)
        self.addCleanup(writer.close)
        with patch.object(self.api, 'episodes', wraps=self.api.episodes) as build:
            first = self.request()
            card = self.request(CARDS)
            decoded = self.store.get(1)[1]
            writer.touch(2)
            writer.put_live('/shows/2', {'name': 'A live title'})
            self.assertIs(self.store.get(1)[1], decoded)
            self.assertIs(self.request().body, first.body)
            self.assertIs(self.request(CARDS).body, card.body)
            changed = {'id': 2, 'tvmaze': EPISODES, 'episodes': merge(EPISODES, {'1:1': {'rating': 9.3, 'votes': 30}}),
                       'tmdb': {'1:1': {'rating': 9.3, 'votes': 30}}, 'tmdb_at': self.now}
            writer.put(2, changed)
            self.assertIs(self.store.get(1)[1], decoded)
            self.assertIs(self.request().body, first.body)
            self.assertIs(self.request(CARDS).body, card.body)
            self.assertEqual(build.call_count, 1)
            changed['id'] = 1
            writer.put(1, changed)
            self.assertNotEqual(self.request().etag, first.etag)
            self.assertEqual(build.call_count, 2)
            self.assertEqual(json.loads(self.request().body)['shows'][0]['episodes'][0]['rating'], 9.3)

    def test_direct_writer_deletion_and_reinsertion_cannot_revive_a_prepared_version(self):
        self.save()
        first = self.request()
        original_revision = self.store.record_revisions((1,))[0]
        writer = Store(Path(self.folder.name) / 'episodes.sqlite3', clock=self.clock)
        self.addCleanup(writer.close)
        writer.db.execute('DELETE FROM episodes WHERE id=1')
        writer.db.commit()
        pending = json.loads(self.request().body)
        self.assertEqual(pending['pending'], [1])
        self.assertEqual(pending['shows'], [])
        value = {'id': 1, 'tvmaze': EPISODES, 'episodes': merge(EPISODES, {}), 'tmdb': {}, 'tmdb_at': self.now}
        data = gzip.compress(json.dumps(value).encode())
        writer.db.execute('INSERT INTO episodes VALUES (?, ?, ?, ?, ?)', (1, self.now, self.now, data, data))
        writer.db.commit()
        self.assertGreater(self.store.record_revisions((1,))[0], original_revision)
        restored = json.loads(self.request().body)
        self.assertEqual(restored['shows'][0]['episodes'], json.loads(first.body)['shows'][0]['episodes'])
        self.assertEqual(restored['pending'], [])
        self.assertNotEqual(restored['shows'][0]['revision'], json.loads(first.body)['shows'][0]['revision'])
        value['episodes'][0]['name'] = 'An updated episode'
        writer.db.execute('UPDATE episodes SET data=?, matrix=? WHERE id=1',
                          (gzip.compress(json.dumps(value).encode()), gzip.compress(json.dumps(value).encode())))
        writer.db.commit()
        self.assertEqual(json.loads(self.request().body)['shows'][0]['episodes'][0]['name'], 'An updated episode')
        writer.db.execute('UPDATE episodes SET id=2 WHERE id=1')
        writer.db.commit()
        self.assertIsNone(self.store.get(1))
        self.assertEqual(self.store.get(2)[1]['episodes'][0]['name'], 'An updated episode')

    def test_cards_cache_does_not_cross_summary_freshness_deadline(self):
        self.save()
        self.now += 180 * DAY - 10
        self.assertEqual(self.request(CARDS).max_age, 10)
        self.now += 8
        self.assertEqual(self.request(CARDS).max_age, 2)
        self.now += 3
        self.assertEqual(self.request(CARDS).max_age, 300)

    def test_model_identity_and_cache_ttl_invalidate_cards(self):
        first = self.request(CARDS)
        self.api.catalogue_version = 'model-two'
        second = self.request(CARDS)
        self.assertNotEqual(first.etag, second.etag)
        self.now += 301
        self.request(CARDS)
        self.assertEqual(self.library.calls, 3)

    def test_enriching_or_stale_records_are_not_shared_cache_entries(self):
        self.save()
        self.ratings.tmdb = SimpleNamespace(disabled=False)
        self.now += DAY + 1
        response = self.request()
        self.assertTrue(json.loads(response.body)['shows'][0]['refreshing'])
        self.assertEqual(response.cache_control, 'no-store')
        self.assertFalse(self.cache.entries)
        self.assertIn(1, self.ratings.enrichment)
        self.assertIn(1, self.ratings.pending)

    def test_cache_freshness_never_crosses_source_refresh_boundary(self):
        self.save()
        self.now += DAY - 10
        first = self.request()
        self.assertEqual(first.max_age, 10)
        self.now += 8
        self.assertEqual(self.request().max_age, 2)
        self.now += 3
        self.assertEqual(self.request().cache_control, 'no-store')


class PreparedCacheTests(TestCase):
    def test_representation_validators_head_and_gzip_quality(self):
        prepared = prepare({'content': 'Couchside ' * 1000}, max_age=300)
        plain = prepared.select('gzip;q=0')
        zipped = prepared.select('gzip')
        self.assertEqual(gzip.decompress(zipped.body), plain.body)
        self.assertNotEqual(dict(plain.headers)['ETag'], dict(zipped.headers)['ETag'])
        self.assertEqual(prepared.select('gzip', 'W/' + prepared.gzip_etag).status, 304)
        self.assertEqual(prepared.select('', prepared.gzip_etag).status, 200)
        head = prepared.select('gzip', head=True)
        self.assertEqual(head.body, b'')
        self.assertEqual(dict(head.headers)['Content-Length'], str(len(zipped.body)))
        response = prepare({'pending': [1]}).select('', '*')
        self.assertEqual(response.status, 200)
        self.assertNotIn('ETag', dict(response.headers))

    def test_lru_bounds_bytes_and_does_not_cache_oversized_or_error_results(self):
        one = prepare({'name': 'one'}, max_age=300)
        two = prepare({'name': 'two'}, max_age=300)
        cache = PreparedCache(max_bytes=one.size + two.size, most=2)
        cache.get('one', lambda: one)
        cache.get('two', lambda: two)
        cache.get('one', lambda: one)
        cache.get('three', lambda: one)
        self.assertEqual(list(cache.entries), ['one', 'three'])
        self.assertLessEqual(cache.bytes, cache.max_bytes)
        large = prepare({'name': 'too large' * 1000}, max_age=300)
        cache.get('large', lambda: large)
        cache.get('error', lambda: prepare({'error': 'busy'}, status=503))
        cache.get('pending', lambda: prepare({'pending': [1]}))
        self.assertNotIn('large', cache.entries)
        self.assertNotIn('error', cache.entries)
        self.assertNotIn('pending', cache.entries)

    def test_concurrent_misses_share_builder_and_failures_can_be_retried(self):
        cache = PreparedCache()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def build():
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(2))
            return prepare({'shows': [1]}, max_age=300)
        with ThreadPoolExecutor(max_workers=8) as workers:
            futures = [workers.submit(cache.get, 'same', build) for _ in range(8)]
            self.assertTrue(entered.wait(1))
            release.set()
            values = [future.result(2) for future in futures]
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(value.body == values[0].body for value in values))
        self.assertFalse(cache.pending)
        def fail():
            raise ValueError('invalid public fixture')
        with self.assertRaises(ValueError):
            cache.get('broken', fail)
        self.assertFalse(cache.pending)
        self.assertEqual(cache.get('broken', lambda: prepare({'ok': True}, 300)).status, 200)

    def test_distinct_inflight_preparation_is_bounded(self):
        cache = PreparedCache(max_pending=1)
        entered, release = threading.Event(), threading.Event()
        def build():
            entered.set()
            self.assertTrue(release.wait(2))
            return prepare({'ok': True}, 300)
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(cache.get, 'one', build)
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(CacheBusy):
                    cache.get('two', build)
            finally:
                release.set()
            self.assertEqual(future.result(2).status, 200)


if __name__ == '__main__':
    main()
