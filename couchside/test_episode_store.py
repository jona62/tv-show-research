"""Persistent ratings, concurrent readers, refresh policy and provider fallbacks; no network."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from unittest import TestCase, main
import threading
import time

from episode_store import DAY, MAX_AGE, Store, Episodes, Tmdb, choose_rating, merge
from live import LiveError

EPISODES = [
    {'id': 1, 'season': 1, 'number': 1, 'name': 'Pilot', 'rating': 8.1,
     'airdate': '2020-01-01', 'summary': 'The complete description.', 'image': None},
    {'id': 2, 'season': 1, 'number': 2, 'name': 'Next', 'rating': None,
     'airdate': '2020-01-08', 'summary': 'The next description.', 'image': None},
]


class FakeLive:
    def __init__(self):
        self.calls = 0
        self.failed = False

    def episode_ratings(self, show_id):
        self.calls += 1
        if self.failed:
            raise LiveError('Busy', 503)
        return EPISODES

    def show(self, show_id):
        return {'imdb': 'tt0123456'}


class RatingsTests(TestCase):
    def test_out_of_order_lanes_preserve_new_episodes_scores_and_freshness(self):
        self.service.get(1)
        old_at, old = self.store.get(1)
        self.now += 1
        eps = [*EPISODES, {**EPISODES[-1], 'id': 3, 'number': 3}]
        updated = {**old, 'tvmaze': eps, 'episodes': eps}
        self.store.put(1, updated)
        tvmaze_at = self.now
        self.now += 1
        scores = {'1:2': {'rating': 9.2, 'votes': 50, 'airdate': '2020-01-08'}}
        provider = {**old, 'tmdb': scores, 'tmdb_at': self.now, 'episodes': merge(old['tvmaze'], scores)}
        self.store.put(1, provider, fetched_at=old_at)
        at, result = self.store.get(1)
        self.assertEqual(at, tvmaze_at, 'enrichment does not renew TVmaze freshness')
        self.assertEqual(len(result['episodes']), 3)
        self.assertEqual(result['episodes'][1]['rating'], 9.2)
        self.now += 1
        self.store.put(1, updated)
        self.assertEqual(self.store.get(1)[1]['episodes'][1]['rating_source'], 'TMDB')

    def test_slow_season_enrichment_cannot_block_a_new_matrix(self):
        entered, release = threading.Event(), threading.Event()
        class Provider:
            def ratings(inner, show_id, live):
                entered.set()
                release.wait(3)
                return {}
        self.service.get(1)
        self.service.tmdb = Provider()
        self.service.queue_enrichment(1)
        workers = [threading.Thread(target=self.service.run), threading.Thread(target=self.service.enrich)]
        self.service.interval = .01
        for worker in workers:
            worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.service.matrices([2])['pending'], [2])
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not self.store.get(2):
                time.sleep(.01)
            self.assertTrue(self.store.get(2), 'TVmaze matrix is ready while TMDB is still busy')
            self.assertFalse(release.is_set())
        finally:
            release.set()
            self.service.stop.set()
            self.service.ready.set()
            for worker in workers:
                worker.join(2)

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000
        self.clock = lambda: self.now
        self.path = Path(self.folder.name) / 'ratings.sqlite3'
        self.store = Store(self.path, clock=self.clock)
        self.addCleanup(self.store.db.close)
        self.live = FakeLive()
        self.service = Episodes(self.store, self.live, clock=self.clock, ended=(1,))

    def test_cache_survives_server_restart(self):
        self.service.get(1)
        second = Store(self.path, clock=self.clock)
        self.addCleanup(second.db.close)
        restarted = Episodes(second, self.live, clock=self.clock)
        self.live.failed = True
        self.assertEqual(restarted.get(1)['episodes'][0]['rating'], 8.1)
        self.assertEqual(self.live.calls, 1)

    def test_stale_answers_are_immediate_and_refresh_is_queued_once(self):
        self.service.get(1)
        self.service.get(2)
        self.now += DAY + 1
        self.live.failed = True
        self.service.get(1)
        self.service.get(2)
        self.service.get(2)
        self.assertEqual(list(self.service.pending), [2])
        self.assertEqual(self.live.calls, 2)
        self.now += 6 * DAY
        self.service.get(1)
        self.assertIn(1, self.service.pending)

    def test_compact_batch_does_not_fetch_missing_shows_or_include_descriptions(self):
        self.service.get(1)
        body = self.service.matrices([1, 2, 3])
        self.assertEqual(body['pending'], [2, 3])
        self.assertEqual(len(body['shows']), 1)
        self.assertNotIn('summary', body['shows'][0]['episodes'][0])
        self.assertNotIn('image', body['shows'][0]['episodes'][0])
        self.assertEqual(self.live.calls, 1)

    def test_concurrent_first_visits_make_one_upstream_request(self):
        entered, release = threading.Event(), threading.Event()
        original = self.live.episode_ratings
        def delayed(show_id):
            entered.set()
            release.wait(2)
            return original(show_id)
        self.live.episode_ratings = delayed
        with ThreadPoolExecutor(max_workers=8) as pool:
            requests = [pool.submit(self.service.get, 1) for _ in range(8)]
            self.assertTrue(entered.wait(1))
            release.set()
            self.assertTrue(all(f.result()['episodes'][0]['rating'] == 8.1 for f in requests))
        self.assertEqual(self.live.calls, 1)

    def test_outage_keeps_good_data_and_cold_failure_rests(self):
        self.service.get(1)
        self.live.failed = True
        self.now += 8 * DAY
        with self.assertRaises(LiveError):
            self.service.refresh(1)
        self.assertEqual(self.service.get(1)['episodes'][0]['rating'], 8.1)
        with self.assertRaises(LiveError):
            self.service.get(2)
        before = self.live.calls
        with self.assertRaises(LiveError):
            self.service.get(2)
        self.assertEqual(before, self.live.calls)

    def test_scores_are_chosen_by_source_and_votes_without_inventing_missing_ratings(self):
        self.assertEqual(choose_rating(8.1, {'rating': 9.1, 'votes': 20}), (9.1, 'TMDB', 20))
        self.assertEqual(choose_rating(8.1, {'rating': 9.1, 'votes': 3}), (8.1, 'TVmaze', None))
        self.assertEqual(choose_rating(None, {'rating': 9.1, 'votes': 3}), (9.1, 'TMDB', 3))
        self.assertEqual(choose_rating(None), (None, None, None))
        merged = merge(EPISODES, {'1:1': {'rating': 9.1, 'votes': 30, 'airdate': '1990-01-01'}})
        self.assertEqual(merged[0]['rating_source'], 'TVmaze')

    def test_failed_provider_refresh_keeps_fallback_and_retention_is_bounded(self):
        class Provider:
            failed = False
            def ratings(inner, show_id, live):
                if inner.failed:
                    raise LiveError('Unavailable')
                return {'1:2': {'rating': 9.2, 'votes': 50, 'airdate': '2020-01-08'}}
        provider = self.service.tmdb = Provider()
        self.service.refresh(1)
        provider.failed = True
        self.now += 8 * DAY
        self.service.refresh(1)
        self.assertEqual(self.service.get(1)['episodes'][1]['rating_source'], 'TMDB')
        self.now += MAX_AGE
        # Original fallback is too old, even if the surrounding TVmaze cache was refreshed.
        self.service.refresh(1)
        self.assertIsNone(self.service.get(1)['episodes'][1]['rating'])
        self.assertEqual(self.service.matrices([1])['shows'][0]['sources'], 'TVmaze')
        self.now += MAX_AGE + 1
        self.assertIsNone(self.store.get(1))

    def test_lru_uses_recent_access_when_storage_limit_is_reached(self):
        self.store.most = 2
        self.service.get(1)
        self.now += 4000
        self.service.get(2)
        self.now += 4000
        self.service.get(1)
        self.now += 1
        self.service.get(3)
        self.assertIsNotNone(self.store.get(1))
        self.assertIsNone(self.store.get(2))

    def test_tmdb_matches_external_id_and_skips_unrated_and_special_episodes(self):
        calls = []
        def fetch(path):
            calls.append(path)
            if '/find/' in path:
                return {'tv_results': [{'id': 100}]}
            if path == '/tv/100':
                return {'seasons': [{'season_number': 0}, {'season_number': 1}]}
            return {'episodes': [
                {'season_number': 1, 'episode_number': 1, 'vote_average': 8.98, 'vote_count': 40},
                {'season_number': 1, 'episode_number': 2, 'vote_average': 0, 'vote_count': 0},
                {'season_number': 1, 'episode_number': 3, 'vote_average': 9, 'vote_count': 0},
                {'season_number': 2, 'episode_number': 1, 'vote_average': 9, 'vote_count': 50},
            ]}
        provider = Tmdb('test', fetch=fetch)
        result = provider.ratings(1, self.live)
        self.assertEqual(result, {'1:1': {'rating': 9.0, 'votes': 40, 'airdate': None}})
        self.assertIn('/find/tt0123456?external_source=imdb_id', calls)
        self.assertNotIn('/tv/100/season/0', calls)

    def test_tmdb_throttle_rest_and_rejected_credentials_do_not_repeat_calls(self):
        for status in (429, 401):
            calls = []
            def fetch(path):
                calls.append(path)
                raise HTTPError(path, status, 'Busy', {'Retry-After': '120'}, None)
            provider = Tmdb('test', fetch=fetch)
            with self.assertRaises(LiveError):
                provider.get('/tv/1')
            with self.assertRaises(LiveError):
                provider.get('/tv/1')
            self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    main()
