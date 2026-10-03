"""Opt-in load metrics count actual cache layers and physical provider attempts."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
from urllib.error import URLError
from urllib3 import HTTPResponse
import io
import json
import os
import threading
import time
from http import HTTPStatus

from backend import telemetry
from backend.backdrops import Backdrops
from backend.episode_store import Store
from backend.http_client import Client, Response, State, cache_key
from backend.live import Live, SHOW
from backend.recommendation.library import Library

URL = 'https://api.tvmaze.com/shows/169?api_key=credential&q=private-search'
IMAGE = 'https://image.tmdb.org/t/p/w1280/a-show.jpg'
JPEG = b'\xff\xd8\xffpicture'


class Clock:
    def __init__(self):
        self.now = 1000.

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Pool:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, **options):
        self.calls.append(url)
        status, body = self.answers.pop(0)
        return HTTPResponse(status=status, headers={'Content-Type': 'application/json'},
                            body=io.BytesIO(body), preload_content=False)


class TelemetryTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'metrics.jsonl'
        self.recorder = telemetry.configure(self.path, background=False)
        self.addCleanup(telemetry.stop)
        self.clock = Clock()
        self.state = State(Path(self.folder.name) / 'http.sqlite3', clock=self.clock)
        self.addCleanup(self.state.db.close)

    def counters(self):
        return self.recorder.snapshot()['counters']

    def reader(self, *answers):
        pool = Pool(*answers)
        return Client(self.state, pool, self.clock.sleep, self.clock), pool

    def test_disabled_default_records_and_writes_nothing(self):
        telemetry.configure()
        before = self.path.read_bytes()
        telemetry.cache('live_memory', 'hit')
        telemetry.upstream_attempt('api.tvmaze.com')
        telemetry.record_request('GET', '/api/search?q=secret', 200, 1)
        self.assertFalse(telemetry.enabled())
        self.assertFalse(telemetry.flush())
        self.assertEqual(self.path.read_bytes(), before)

    def test_multithread_counters_and_histograms_do_not_lose_increments(self):
        def produce(_):
            for _ in range(1000):
                telemetry.cache('live_memory', 'hit')
                telemetry.record_request('POST', '/api/title', 200, 7, bytes=20)
        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(produce, range(8)))
        snapshot = self.recorder.snapshot()
        self.assertEqual(snapshot['counters']['cache.live_memory.api.hit'], 8000)
        self.assertEqual(snapshot['counters']['http.POST.api.title.bytes'], 160000)
        latency = snapshot['latency_ms']['http.POST.api.title']
        self.assertEqual(latency['count'], 8000)
        self.assertEqual(latency['sum'], 56000)
        self.assertEqual(sum(latency['buckets']), 8000)

    def test_export_never_contains_urls_queries_credentials_or_dynamic_labels(self):
        for n in range(1000):
            telemetry.record_request('GET', f'/api/search?q=secret-{n}', 200, 2)
            telemetry.record_request('GET', f'/api/accounts/{n}?email=private@example.com', 429, 2)
            telemetry.upstream_attempt(f'private-{n}.example.com')
            telemetry.cache(f'unknown-{n}', 'hit')
        self.assertTrue(telemetry.flush(final=True))
        raw = self.path.read_text()
        self.assertTrue(json.loads(raw)['final'])
        self.assertLess(len(self.counters()), 20)
        self.assertNotIn('secret-', raw)
        self.assertNotIn('example.com', raw)
        self.assertNotIn('email', raw)
        self.assertEqual(self.counters()['upstream.other.attempts'], 1000)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_failed_metric_export_does_not_fail_the_app(self):
        recorder = telemetry.Recorder(Path(self.folder.name), interval=.2)
        self.assertFalse(recorder.flush())
        self.assertEqual(recorder.snapshot()['counters']['metrics.export_errors'], 1)

    def test_malformed_request_path_and_http_status_enum_remain_bounded(self):
        telemetry.record_request('GET', 'http://[invalid', HTTPStatus.BAD_REQUEST, 1)
        self.assertEqual(self.counters()['http.GET.other.status.4xx'], 1)

    def test_disconnected_requests_have_a_bounded_cancelled_counter(self):
        for n in range(100):
            telemetry.record_request('POST', f'/api/home?private={n}', 499, 10)
        counts = self.counters()
        self.assertEqual(counts['http.POST.api.home.cancelled'], 100)
        self.assertEqual(counts['http.POST.api.home.status.4xx'], 100)
        self.assertEqual(counts['http.POST.api.home.bytes'], 0)
        self.assertLess(len(counts), 6)

    def test_retries_are_physical_attempts_and_cache_hits_are_not(self):
        reader, pool = self.reader((503, b'busy'), (200, b'{"value":1}'))
        self.assertEqual(reader.json(URL, ttl=60), {'value': 1})
        self.assertEqual(reader.json(URL, ttl=60), {'value': 1})
        counts = self.counters()
        self.assertEqual(len(pool.calls), 2)
        self.assertEqual(counts['upstream.tvmaze.attempts'], 2)
        self.assertEqual(counts['upstream.tvmaze.http_error'], 1)
        self.assertEqual(counts['upstream.tvmaze.success'], 1)
        self.assertEqual(counts['upstream.tvmaze.decoded_bytes'], 15)
        self.assertEqual(counts['cache.shared_http_disk.api.miss'], 1)
        self.assertEqual(counts['cache.shared_http_disk.api.hit'], 1)
        self.assertNotIn('credential', json.dumps(self.recorder.snapshot()))

    def test_no_outbound_mode_serves_disk_and_stale_without_physical_attempts(self):
        self.state.put(cache_key(URL), Response(b'{"value":1}', {}))
        reader, pool = self.reader()
        callback = Mock()
        with patch.dict(os.environ, {'COUCHSIDE_LOAD_TEST_NO_OUTBOUND': '1'}):
            self.assertEqual(reader.json(URL, ttl=60, on_attempt=callback), {'value': 1})
            self.clock.now += 61
            self.assertEqual(reader.json(URL, ttl=60, stale=3600, on_attempt=callback), {'value': 1})
            with self.assertRaises(URLError):
                reader.get(URL + '&new=1', ttl=60, on_attempt=callback)
        self.assertFalse(pool.calls)
        callback.assert_not_called()
        self.assertEqual(self.counters()['upstream.tvmaze.blocked'], 2)
        self.assertEqual(self.counters()['cache.shared_http_disk.api.stale'], 1)
        self.assertNotIn('upstream.tvmaze.attempts', self.counters())

    def test_concurrent_requests_share_one_physical_attempt_with_exact_coalescing(self):
        entered, release = threading.Event(), threading.Event()
        reader, pool = self.reader((200, b'{}'))
        original = pool.request
        def waiting(*args, **options):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(*args, **options)
        pool.request = waiting
        with ThreadPoolExecutor(max_workers=8) as workers:
            futures = [workers.submit(reader.get, URL, ttl=60) for _ in range(8)]
            self.assertTrue(entered.wait(1))
            deadline = time.monotonic() + 2
            while self.counters().get('cache.shared_http_inflight.api.coalesced', 0) < 7 and time.monotonic() < deadline:
                time.sleep(.005)
            release.set()
            self.assertTrue(all(f.result(2).body == b'{}' for f in futures))
        self.assertEqual(self.counters()['upstream.tvmaze.attempts'], 1)
        self.assertEqual(self.counters()['cache.shared_http_inflight.api.coalesced'], 7)

    def test_backdrops_separate_source_memory_from_durable_image_cache(self):
        reader, _ = self.reader((200, JPEG))
        service = Backdrops(lambda show: IMAGE, reader=reader, clock=self.clock)
        self.assertEqual(service.get(169).body, JPEG)
        self.assertEqual(service.get(169).body, JPEG)
        counts = self.counters()
        self.assertEqual(counts['cache.artwork_source_memory.image.miss'], 1)
        self.assertEqual(counts['cache.artwork_source_memory.image.hit'], 1)
        self.assertEqual(counts['cache.shared_http_disk.image.hit'], 1)
        self.assertEqual(counts['upstream.tmdb_image.attempts'], 1)

    def test_episode_matrix_memory_and_disk_hits_are_separate(self):
        store = Store(Path(self.folder.name) / 'episodes.sqlite3', clock=self.clock)
        self.addCleanup(store.db.close)
        self.assertIsNone(store.get(169, compact=True))
        eps = [{'id': 1, 'season': 1, 'number': 1, 'name': 'Pilot', 'rating': 8, 'runtime': 30}]
        store.put(169, {'id': 169, 'episodes': eps, 'tvmaze': eps, 'tmdb': {}, 'tmdb_at': 1000})
        self.assertTrue(store.get(169, compact=True))
        self.assertTrue(store.get(169, compact=True))
        self.assertEqual(self.counters()['cache.episodes_disk.api.miss'], 1)
        self.assertEqual(self.counters()['cache.episodes_disk.api.hit'], 1)
        self.assertEqual(self.counters()['cache.episodes_memory.api.hit'], 1)

    def test_live_details_disk_survives_restart_and_counts_served_freshness(self):
        store = Store(Path(self.folder.name) / 'episodes.sqlite3', clock=self.clock)
        self.addCleanup(store.db.close)
        raw = {'id': 169, 'name': 'A show', '_embedded': {'cast': [], 'seasons': []}}
        first = Live(fetch=lambda path: raw, store=store, ttl=60, clock=self.clock)
        first.show(169)
        first.show(169)
        second = Live(fetch=Mock(side_effect=AssertionError('No lookup needed')), store=store, ttl=60, clock=self.clock)
        second.show(169)
        self.assertEqual(self.counters()['cache.live_memory.api.hit'], 1)
        self.assertEqual(self.counters()['cache.live_detail_disk.api.hit'], 1)
        self.clock.now += 61
        stale = Live(fetch=Mock(side_effect=URLError('offline')), store=store, ttl=60, clock=self.clock)
        stale.show(169)
        self.assertEqual(self.counters()['cache.live_detail_disk.api.stale'], 1)
        self.assertEqual(self.counters()['cache.live_stale.api.hit'], 1)

    def test_snapshot_exporter_stops_and_invalid_interval_uses_default(self):
        telemetry.stop()
        with patch.dict(os.environ, {'COUCHSIDE_METRICS_FILE': str(self.path), 'COUCHSIDE_METRICS_INTERVAL': 'nan'}):
            recorder = telemetry.configure_from_env()
            self.assertEqual(recorder.interval, 5)
            telemetry.cache('live_memory', 'hit')
            telemetry.stop()
        self.assertFalse(recorder.worker.is_alive())
        self.assertTrue(json.loads(self.path.read_text().splitlines()[-1])['final'])

    def test_home_continuation_reports_only_usable_cache_hits(self):
        library = object.__new__(Library)
        library.kept, library.kept_lock = OrderedDict(), threading.Lock()
        prepared, answer = (), (['row'], False, {'message': ''})
        def lay(held, prepared, shown):
            held.answers = lambda shown, count: answer
        library.lay_out = lay
        self.assertEqual(library.keep('hashed-key', prepared, [], 8), answer)
        self.assertEqual(library.keep('hashed-key', prepared, [], 8), answer)
        self.assertEqual(self.counters()['cache.home_pages.api.miss'], 1)
        self.assertEqual(self.counters()['cache.home_pages.api.hit'], 1)
        self.assertNotIn('hashed-key', json.dumps(self.recorder.snapshot()))


if __name__ == '__main__':
    main()
