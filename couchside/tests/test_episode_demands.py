"""Follower requests reach the elected warmer without duplicating provider work."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.episode_store import DAY, Episodes, Store, merge
from backend.live import LiveError


EPISODES = [{'id': 101, 'season': 1, 'number': 1, 'name': 'Pilot', 'rating': 8,
             'rating_source': 'TVmaze', 'airdate': '2020-01-01', 'summary': 'Complete details',
             'image': {'original': 'https://images.example/pilot.jpg'}}]


class DemandTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000
        self.clock = lambda: self.now
        self.path = Path(self.folder.name) / 'episodes.sqlite3'
        self.owner_store, self.follower_store = Store(self.path, clock=self.clock), Store(self.path, clock=self.clock)
        for store in (self.owner_store, self.follower_store):
            self.addCleanup(store.close)
        self.calls, self.tmdb_calls = [], []
        test = self
        class Live:
            def episode_ratings(self, show_id):
                test.calls.append(show_id)
                return EPISODES
        class Tmdb:
            def ratings(self, show_id, live):
                test.tmdb_calls.append(show_id)
                return {'1:1': {'rating': 9.2, 'votes': 50, 'airdate': '2020-01-01'}}
        self.owner = Episodes(self.owner_store, Live(), Tmdb(), clock=self.clock, interval=.01)
        self.follower = Episodes(self.follower_store, Live(), Tmdb(), clock=self.clock)

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.01)
        self.fail('The elected worker did not consume a follower demand.')

    def workers(self, *targets):
        threads = [threading.Thread(target=target) for target in targets]
        def stop():
            self.owner.stop.set()
            self.owner.ready.set()
            for thread in threads:
                thread.join(3)
                self.assertFalse(thread.is_alive())
        self.addCleanup(stop)
        for thread in threads:
            thread.start()

    def test_missing_follower_batch_warms_full_records_and_provider_scores_once(self):
        self.workers(self.owner.run, self.owner.enrich)
        for _ in range(10):
            self.assertEqual(self.follower.batch([1])['pending'], [1])
        self.wait_for(lambda: self.follower_store.get(1) and
                      self.follower_store.get(1)[1]['episodes'][0]['rating_source'] == 'TMDB')
        body = self.follower.batch([1])
        self.assertFalse(body['pending'])
        self.assertFalse(body['shows'][0]['refreshing'])
        self.assertEqual(body['shows'][0]['episodes'][0]['id'], 101)
        self.assertEqual(body['shows'][0]['episodes'][0]['summary'], 'Complete details')
        self.assertEqual(self.calls, [1])
        self.assertEqual(self.tmdb_calls, [1])
        self.wait_for(lambda: self.owner_store.next_demand('tvmaze') is None and
                      self.owner_store.next_demand('tmdb') is None)

    def test_stale_follower_data_refreshes_but_fresh_data_queues_nothing(self):
        value = {'id': 1, 'tvmaze': EPISODES, 'episodes': merge(EPISODES, {}),
                 'tmdb': {}, 'tmdb_at': self.now}
        self.owner_store.put(1, value)
        self.assertFalse(self.follower.batch([1])['shows'][0]['refreshing'])
        self.assertIsNone(self.owner_store.next_demand('tvmaze'))
        self.assertIsNone(self.owner_store.next_demand('tmdb'))
        self.now += DAY + 1
        with patch('backend.episode_store.MAX_DEMANDS', 2):
            self.owner_store.demand(2, 'tvmaze')
            self.owner_store.demand(3, 'tvmaze')
            self.assertTrue(self.follower.batch([1])['shows'][0]['refreshing'])
        self.assertEqual(self.owner_store.next_demand('tvmaze'), 1)
        self.assertEqual(self.owner_store.next_demand('tmdb'), 1)
        self.workers(self.owner.run, self.owner.enrich)
        self.wait_for(lambda: not self.follower.batch([1])['shows'][0]['refreshing'])
        self.assertEqual(self.calls, [1])
        self.assertEqual(self.tmdb_calls, [1])

    def test_queue_is_durable_coalesced_bounded_and_does_not_flush_episode_memory(self):
        value = {'id': 1, 'tvmaze': EPISODES, 'episodes': EPISODES, 'tmdb': {}, 'tmdb_at': self.now}
        self.owner_store.put(1, value)
        cached = self.owner_store.get(1)
        generation = self.owner_store.current_revision()
        with patch('backend.episode_store.MAX_DEMANDS', 3):
            for _ in range(10):
                self.follower_store.demand(2, 'tvmaze')
            self.follower_store.demand(3, 'tvmaze')
            self.follower_store.demand(4, 'tmdb')
            self.assertFalse(self.follower_store.demand(5, 'tvmaze'))
            self.assertTrue(self.follower_store.demand(5, 'tvmaze', urgent=True))
            self.assertEqual(self.owner_store.demands.execute('SELECT count(*) FROM demands').fetchone()[0], 3)
            self.assertEqual(self.owner_store.next_demand('tvmaze'), 5)
        self.assertEqual(self.owner_store.current_revision(), generation)
        self.assertIs(self.owner_store.get(1)[1], cached[1])
        reopened = Store(self.path, clock=self.clock)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.next_demand('tvmaze'), 5)
        reopened.finish_demand(5, 'tvmaze', retry=60)
        self.assertNotEqual(self.owner_store.next_demand('tvmaze'), 5)
        self.now += 60
        self.assertEqual(self.owner_store.next_demand('tvmaze'), 5)

    def test_failure_retains_demand_and_shared_cooldown(self):
        def fail(show_id):
            self.calls.append(show_id)
            raise LiveError('Provider is resting.', 503)
        self.owner.live.episode_ratings = fail
        self.follower.batch([2])
        self.workers(self.owner.run)
        self.wait_for(lambda: self.calls == [2] and self.owner_store.next_demand('tvmaze') is None)
        for _ in range(5):
            self.follower.batch([2])
        self.assertIsNone(self.follower_store.next_demand('tvmaze'))
        self.now += 60
        self.wait_for(lambda: self.calls == [2, 2])


if __name__ == '__main__':
    main()
