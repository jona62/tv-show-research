"""Provider admission, retry limits, pooling errors and persistent cache recovery; no external calls."""
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from unittest import TestCase, main
import io
import json
import threading
import time

from urllib3 import HTTPResponse
from urllib3.exceptions import ReadTimeoutError, SSLError
from http_client import Client, State, Response, cache_key, retry_after


class Clock:
    def __init__(self):
        self.now, self.sleeps = 1000., []
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Pool:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []
    def request(self, method, url, **options):
        self.calls.append((method, url, options))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, headers, body = answer
        return HTTPResponse(status=status, headers=headers, body=io.BytesIO(body), preload_content=False)


OK = (200, {'Content-Type': 'application/json'}, b'{"value":1}')
URL = 'https://api.tvmaze.com/shows/169'


class NetworkingTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.path = Path(self.tmp.name) / 'http.sqlite3'
        self.state = State(self.path, clock=self.clock)
        self.addCleanup(self.state.db.close)

    def reader(self, *answers):
        pool = Pool(*answers)
        return Client(self.state, pool, self.clock.sleep, self.clock), pool

    def test_status_and_connection_retries_are_bounded_and_use_fixed_admission(self):
        reader, pool = self.reader((503, {}, b'busy'), ReadTimeoutError(None, URL, 'timeout'), OK)
        self.assertEqual(reader.json(URL), {'value': 1})
        self.assertEqual(len(pool.calls), 3)
        self.assertGreaterEqual(sum(self.clock.sleeps), 1)
        self.assertTrue(all(call[2]['retries'] is False for call in pool.calls))
        reader, pool = self.reader(*[(500, {}, b'failed')] * 5)
        with self.assertRaises(HTTPError):
            reader.get(URL)
        self.assertEqual(len(pool.calls), 3)

    def test_retry_after_is_shared_with_other_clients_and_never_retried_early(self):
        reader, pool = self.reader((429, {'Retry-After': '120'}, b'busy'))
        with self.assertRaises(HTTPError):
            reader.get(URL, budget=8)
        self.assertEqual(len(pool.calls), 1)
        other = State(self.path, clock=self.clock)
        self.addCleanup(other.db.close)
        self.assertGreater(other.delay('api.tvmaze.com', .5), 110)
        self.assertEqual(other.delay('api.themoviedb.org', .3), 0)

    def test_auth_missing_and_tls_errors_are_not_retried_or_hidden_by_stale_data(self):
        self.state.put(cache_key(URL), Response(OK[2], OK[1]))
        self.clock.now += 61
        for status in (401, 403, 404):
            self.clock.now += 100
            reader, pool = self.reader((status, {}, b'no'))
            with self.assertRaises(HTTPError):
                reader.get(URL, ttl=60, stale=3600)
            self.assertEqual(len(pool.calls), 1)
        self.clock.now += 100
        reader, pool = self.reader(SSLError('bad certificate'))
        with self.assertRaises(URLError):
            reader.get(URL)
        self.assertEqual(len(pool.calls), 1)

    def test_fresh_cache_survives_restart_and_stale_covers_transient_outages_only(self):
        reader, pool = self.reader(OK)
        self.assertEqual(reader.json(URL, ttl=60), {'value': 1})
        other = State(self.path, clock=self.clock)
        self.addCleanup(other.db.close)
        new_pool = Pool()
        reopened = Client(other, new_pool, self.clock.sleep, self.clock)
        self.assertEqual(reopened.json(URL, ttl=60), {'value': 1})
        self.assertFalse(new_pool.calls)
        self.clock.now += 61
        reader, pool = self.reader(*[(502, {}, b'no')] * 3)
        self.assertEqual(reader.json(URL, ttl=60, stale=3600), {'value': 1})
        self.clock.now += 4000
        reader, pool = self.reader(*[(502, {}, b'no')] * 3)
        with self.assertRaises(HTTPError):
            reader.json(URL, ttl=60, stale=3600)

    def test_oversized_or_invalid_answers_are_not_cached_and_credentials_are_not_stored(self):
        reader, pool = self.reader((200, {}, b'x' * 20), (200, {}, b'not json'))
        with self.assertRaises(ValueError):
            reader.get(URL, max_bytes=10, ttl=60)
        with self.assertRaises(ValueError):
            reader.json(URL, ttl=60)
        self.assertIsNone(self.state.get(cache_key(URL), 60))
        self.assertEqual(cache_key(URL + '?api_key=secret&language=en'), cache_key(URL + '?language=en'))

    def test_shared_admission_is_atomic_across_connections(self):
        other = State(self.path, clock=self.clock)
        self.addCleanup(other.db.close)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda state: state.delay('api.tvmaze.com', 1), [self.state, other]))
        self.assertEqual(sorted(results), [0, 1])

    def test_simultaneous_reads_share_one_request(self):
        entered, release = threading.Event(), threading.Event()
        pool = Pool(OK)
        original = pool.request
        def slow(*args, **kwargs):
            entered.set();release.wait(2)
            return original(*args, **kwargs)
        pool.request = slow
        reader = Client(self.state, pool, self.clock.sleep, self.clock)
        with ThreadPoolExecutor(max_workers=8) as workers:
            answers = [workers.submit(reader.json, URL, ttl=60) for _ in range(8)]
            self.assertTrue(entered.wait(1));release.set()
            self.assertTrue(all(answer.result(2) == {'value': 1} for answer in answers))
        self.assertEqual(len(pool.calls), 1)

    def test_retry_after_dates_and_malformed_values(self):
        self.assertEqual(retry_after('7'), 7)
        self.assertAlmostEqual(retry_after(formatdate(time.time() + 30, usegmt=True)), 30, delta=2)
        self.assertEqual(retry_after('wrong'), 10)
        self.assertEqual(retry_after('999999'), 999999)

    def test_redirects_spend_the_same_budget_without_leaking_credentials(self):
        reader,pool=self.reader((302,{'Location':'/new'},b''),OK)
        self.assertEqual(reader.json(URL),{'value':1})
        self.assertEqual(len(pool.calls),2)
        self.assertAlmostEqual(sum(self.clock.sleeps),10/18)
        reader,pool=self.reader((302,{'Location':'https://another.example/'},b''))
        with self.assertRaises(HTTPError):
            reader.get(URL,headers={'Authorization':'Bearer secret'})
        self.assertEqual(len(pool.calls),1)


if __name__ == '__main__':
    main()
