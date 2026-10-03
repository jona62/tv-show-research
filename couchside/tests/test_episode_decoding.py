"""Decoded episode caches remain bounded and coherent across threads and WAL writers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import gzip
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.episode_store import MAX_AGE, Store
from backend.public_api import PublicAPI, RATINGS
from backend.episode_store import Episodes
from types import SimpleNamespace


def record(show_id=1, rating=8):
    episodes = [{'id': show_id * 100, 'season': 1, 'number': 1, 'name': 'Pilot',
                 'rating': rating, 'rating_source': 'TVmaze', 'runtime': 30,
                 'summary': 'Complete description ' * 20,
                 'image': {'original': 'https://images.example/episode.jpg'}}]
    return {'id': show_id, 'episodes': episodes, 'tvmaze': episodes, 'tmdb': {}, 'tmdb_at': 1000}


class DecodedStoreTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000.
        self.clock = lambda: self.now
        self.path = Path(self.folder.name) / 'episodes.sqlite3'
        self.store = Store(self.path, clock=self.clock)
        self.addCleanup(self.store.db.close)

    def test_full_and_compact_records_decode_once_and_have_distinct_cache_variants(self):
        self.store.put(1, record())
        original = gzip.decompress
        with patch('backend.episode_store.gzip.decompress', wraps=original) as decode:
            first = self.store.get(1, with_revision=True)
            second = self.store.get(1, with_revision=True)
            matrix = self.store.get(1, compact=True)
            self.store.get(1, compact=True)
        self.assertEqual(decode.call_count, 2)
        self.assertIs(first[1], second[1])
        self.assertEqual(first[2], second[2])
        self.assertIn('summary', first[1]['episodes'][0])
        self.assertNotIn('summary', matrix[1]['episodes'][0])
        self.assertGreater(self.store.decoded_bytes, 0)

    def test_memory_lru_bounds_actual_decoded_objects_and_skips_oversized_records(self):
        self.store.memory_most = 2
        for show_id in (1, 2, 3):
            self.store.put(show_id, record(show_id))
        self.store.get(1)
        self.store.get(2)
        self.store.get(1)
        self.store.get(3)
        self.assertEqual(list(self.store.memory), [(1, False), (3, False)])
        self.store.memory_bytes = 1
        self.store.memory.clear()
        self.store.decoded_bytes = 0
        self.assertIsNotNone(self.store.get(1))
        self.assertFalse(self.store.memory)
        self.assertEqual(self.store.decoded_bytes, 0)

    def test_decode_does_not_hold_the_database_lock_and_concurrent_readers_share_work(self):
        self.store.put(1, record())
        entered, release = threading.Event(), threading.Event()
        original = gzip.decompress
        calls = []
        def slow(blob):
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(2))
            return original(blob)
        with patch('backend.episode_store.gzip.decompress', side_effect=slow):
            with ThreadPoolExecutor(max_workers=9) as workers:
                futures = [workers.submit(self.store.get, 1) for _ in range(8)]
                try:
                    self.assertTrue(entered.wait(1))
                    self.assertIsNone(workers.submit(self.store.get, 2).result(.5))
                finally:
                    release.set()
                values = [future.result(2) for future in futures]
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(value[1]['episodes'][0]['rating'] == 8 for value in values))
        self.assertFalse(self.store.decoding)

    def test_refresh_overtaking_decode_never_installs_the_old_record(self):
        self.store.put(1, record())
        entered, release = threading.Event(), threading.Event()
        original = gzip.decompress
        first = True
        def delayed(blob):
            nonlocal first
            if first:
                first = False
                entered.set()
                self.assertTrue(release.wait(2))
            return original(blob)
        with patch('backend.episode_store.gzip.decompress', side_effect=delayed):
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(self.store.get, 1)
                try:
                    self.assertTrue(entered.wait(1))
                    self.now += 1
                    self.store.put(1, record(rating=9))
                finally:
                    release.set()
                self.assertEqual(future.result(2)[1]['episodes'][0]['rating'], 9)
        self.assertEqual(self.store.get(1)[1]['episodes'][0]['rating'], 9)

    def test_external_writer_invalidates_decoded_and_prepared_cache_without_restart(self):
        self.store.put(1, record())
        library = SimpleNamespace(e=SimpleNamespace(by_id={1: 0}))
        service = Episodes(self.store, SimpleNamespace(), clock=self.clock)
        api = PublicAPI(library, service, 'test-model')
        first = api.get(RATINGS, {'ids': ['1']})
        original_revision = self.store.current_revision()
        writer = Store(self.path, clock=self.clock)
        self.addCleanup(writer.db.close)
        self.now += 1
        writer.put(1, record(rating=9.2))
        second = api.get(RATINGS, {'ids': ['1']})
        self.assertGreater(self.store.current_revision(), original_revision)
        self.assertNotEqual(first.etag, second.etag)
        self.assertEqual(self.store.get(1)[1]['episodes'][0]['rating'], 9.2)

    def test_external_summary_refresh_propagates_counts_without_losing_other_writes(self):
        self.store.put(1, record())
        writer = Store(self.path, clock=self.clock)
        self.addCleanup(writer.db.close)
        initial = self.store.revision
        self.now += 1
        writer.put(1, record(rating=9))
        self.store.sync_metadata()
        self.assertEqual(self.store.revision, initial)
        self.assertEqual(self.store.summaries[1]['at'], self.now)
        longer = record()
        longer['episodes'] = [*longer['episodes'], {**longer['episodes'][0], 'id': 101, 'number': 2}]
        longer['tvmaze'] = longer['episodes']
        self.now += 1
        writer.put(1, longer)
        writer.put(2, record(2))
        self.store.sync_metadata()
        self.assertGreater(self.store.revision, initial)
        self.assertEqual(self.store.summaries[1]['episodes'], 2)
        self.assertIn(2, self.store.summaries)
        self.store.put(3, record(3))
        writer.sync_metadata()
        self.assertEqual(set(writer.summaries), {1, 2, 3})

    def test_different_process_connections_merge_provider_updates_without_lost_episodes(self):
        old = record()
        self.store.put(1, old)
        other = Store(self.path, clock=self.clock)
        self.addCleanup(other.db.close)
        scores = {'1:1': {'rating': 9.2, 'votes': 30}}
        enriched = {**old, 'tmdb': scores, 'tmdb_at': 1001,
                    'episodes': [{**old['episodes'][0], 'rating': 9.2, 'rating_source': 'TMDB'}]}
        newer = record()
        newer['episodes'] = [*newer['episodes'], {**newer['episodes'][0], 'id': 101, 'number': 2}]
        newer['tvmaze'] = newer['episodes']
        entered, release = threading.Event(), threading.Event()
        original, first = gzip.compress, True
        def delayed(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                self.assertTrue(release.wait(2))
            return original(*args, **kwargs)
        self.now = 1002
        with patch('backend.episode_store.gzip.compress', side_effect=delayed):
            with ThreadPoolExecutor(max_workers=2) as workers:
                enrichment = workers.submit(self.store.put, 1, enriched, 1000)
                try:
                    self.assertTrue(entered.wait(1))
                    update = workers.submit(other.put, 1, newer, 1002)
                    with self.assertRaises(TimeoutError):
                        update.result(.05)
                finally:
                    release.set()
                enrichment.result(2)
                update.result(2)
        fetched, saved = self.store.get(1)
        self.assertEqual(fetched, 1002)
        self.assertEqual(len(saved['episodes']), 2)
        self.assertEqual(saved['episodes'][0]['rating'], 9.2)
        self.assertEqual(saved['episodes'][0]['rating_source'], 'TMDB')

    def test_disk_eviction_and_expiry_cannot_be_bypassed_by_decoded_memory(self):
        self.store.most = 1
        self.store.put(1, record())
        self.store.get(1)
        self.now += 4000
        self.store.put(2, record(2))
        self.assertIsNone(self.store.get(1))
        self.assertFalse(any(key[0] == 1 for key in self.store.memory))
        self.store.get(2)
        self.now += MAX_AGE + 1
        self.assertIsNone(self.store.get(2))
        self.assertEqual(self.store.decoded_bytes, 0)


if __name__ == '__main__':
    main()
