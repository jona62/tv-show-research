"""Cross-process cache ownership using independent SQLite states and fake providers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from urllib.error import HTTPError, URLError
import json
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'pipeline'), str(Path(__file__).parent)]
from backend.http_client import Client, State, Response, cache_key
from backend import telemetry
from test_http_client import Pool, Clock, OK, URL


class DurableSingleflightTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'http.sqlite3'

    def state(self, clock=time.time):
        state = State(self.path, clock=clock)
        self.addCleanup(state.db.close)
        return state

    def test_two_clients_with_independent_connections_fetch_one_validated_answer(self):
        recorder = telemetry.configure(Path(self.folder.name) / 'metrics.jsonl', background=False)
        self.addCleanup(telemetry.stop)
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        pool = Pool(OK)
        original = pool.request
        def slow(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(*args, **kwargs)
        pool.request = slow
        owner = Client(self.state(), pool)
        published, put = [], owner.state.put
        def save(*args):
            put(*args)
            published.append(owner.state.db.execute('SELECT fetched FROM http_cache').fetchone()[0])
        owner.state.put = save
        other_state, unused = self.state(), Pool()
        acquire = other_state.acquire
        def observe(*args):
            result = acquire(*args)
            if result is False:
                waiting.set()
            return result
        other_state.acquire = observe
        follower = Client(other_state, unused)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(owner.json, URL, ttl=60)
            self.assertTrue(entered.wait(1))
            second = workers.submit(follower.json, URL, ttl=60)
            self.assertTrue(waiting.wait(1))
            release.set()
            self.assertEqual(first.result(2), {'value': 1})
            self.assertEqual(second.result(2), {'value': 1})
        self.assertEqual(len(pool.calls), 1)
        self.assertFalse(unused.calls)
        # Joining a fetch must not rewrite its timestamp and extend its TTL.
        self.assertEqual(other_state.db.execute('SELECT fetched FROM http_cache').fetchone()[0], published[0])
        self.assertEqual(owner.state.db.execute('SELECT COUNT(*) FROM http_leases').fetchone()[0], 0)
        counters = recorder.snapshot()['counters']
        self.assertEqual(counters['cache.shared_http_lease.api.coalesced'], 1)
        self.assertEqual(counters['upstream.tvmaze.attempts'], 1)

    def test_crashed_writer_expires_and_its_late_release_cannot_remove_the_new_owner(self):
        clock = Clock()
        first, next_state = self.state(clock), self.state(clock)
        key = cache_key(URL)
        self.assertTrue(first.acquire(key, 'crashed', 1))
        self.assertFalse(next_state.acquire(key, 'next', 1))
        clock.now += 2
        self.assertTrue(next_state.acquire(key, 'next', 1))
        first.release(key, 'crashed')
        self.assertFalse(first.acquire(key, 'late', 1))
        next_state.release(key, 'next')
        reader = Client(first, Pool(OK), clock.sleep, clock)
        self.assertEqual(reader.json(URL, ttl=60), {'value': 1})

    def test_active_lease_count_and_lifetime_are_bounded_and_expired_entries_are_removed(self):
        clock, state = Clock(), self.state()
        state.clock = clock
        for index in range(512):
            self.assertTrue(state.acquire(str(index), 'owner', 100000))
        self.assertIsNone(state.acquire('over-capacity', 'owner', 1))
        self.assertEqual(state.db.execute('SELECT COUNT(*) FROM http_leases').fetchone()[0], 512)
        clock.now += 121
        self.assertTrue(state.acquire('new', 'owner', 1))
        self.assertEqual(state.db.execute('SELECT COUNT(*) FROM http_leases').fetchone()[0], 1)

    def test_invalid_or_oversized_owner_answers_release_without_publishing(self):
        clock, state = Clock(), self.state()
        state.clock = clock
        pool = Pool((200, {}, b'not json'), (200, {}, b'x' * 20), OK)
        reader = Client(state, pool, clock.sleep, clock)
        for options in ({}, {'max_bytes': 10}):
            with self.assertRaises(ValueError):
                reader.json(URL, ttl=60, **options)
            self.assertIsNone(state.get(cache_key(URL), 60))
            self.assertEqual(state.db.execute('SELECT COUNT(*) FROM http_leases').fetchone()[0], 0)
        self.assertEqual(reader.json(URL, ttl=60), {'value': 1})

    def test_waiter_budget_timeout_uses_existing_transient_stale_fallback(self):
        state, key = self.state(), cache_key(URL)
        state.put(key, Response(OK[2], OK[1]))
        with state.db:
            state.db.execute('UPDATE http_cache SET fetched=fetched-120')
        self.assertTrue(state.acquire(key, 'slow-owner', 2))
        unused, began = Pool(), time.monotonic()
        reader = Client(state, unused)
        value = reader.get(URL, ttl=60, stale=3600, budget=.04)
        self.assertTrue(value.stale)
        self.assertEqual(json.loads(value.body), {'value': 1})
        self.assertLess(time.monotonic() - began, .3)
        self.assertFalse(unused.calls)
        with self.assertRaises(URLError):
            reader.get(URL, ttl=60, budget=.04)

    def test_force_zero_ttl_and_authorized_reads_do_not_join_durable_leases(self):
        for options in ({'ttl': 0}, {'ttl': 60, 'force': True},
                        {'ttl': 60, 'headers': {'Authorization': 'Bearer private'}},
                        {'ttl': 60, 'headers': {'COOKIE': 'session=private'}}):
            state = self.state()
            with state.db:
                state.db.execute('DELETE FROM http_cache')
                state.db.execute('DELETE FROM http_leases')
            self.assertTrue(state.acquire(cache_key(URL), 'another-process', 30))
            pool = Pool(OK)
            reader = Client(state, pool)
            self.assertEqual(reader.json(URL, **options), {'value': 1})
            self.assertEqual(len(pool.calls), 1)
            self.assertEqual(state.db.execute('SELECT owner FROM http_leases').fetchone()[0], 'another-process')
            stored = repr(state.db.execute('SELECT * FROM http_leases').fetchall())
            self.assertNotIn('private', stored)

    def test_rejected_owner_response_is_not_cached_or_replaced_with_stale(self):
        clock, state = Clock(), self.state()
        state.clock = clock
        state.put(cache_key(URL), Response(OK[2], OK[1]))
        clock.now += 61
        reader = Client(state, Pool((403, {}, b'rejected')), clock.sleep, clock)
        with self.assertRaises(HTTPError):
            reader.get(URL, ttl=60, stale=3600)
        self.assertIsNone(state.get(cache_key(URL), 60))
        self.assertEqual(state.db.execute('SELECT COUNT(*) FROM http_leases').fetchone()[0], 0)


if __name__ == '__main__':
    main()
