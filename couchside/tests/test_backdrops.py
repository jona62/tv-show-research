"""Backdrop intent sharing, durable cache, provider safety and public HTTP caching."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib3 import HTTPResponse
import io
import os
import threading

from backend.backdrops import Backdrops, backdrop_width, cache_path, image_kind
from backend.http_client import Client, State, cache_key
from backend.live import Live, LiveError

URL = 'https://image.tmdb.org/t/p/w1280/a-show.jpg'
TVMAZE = 'https://static.tvmaze.com/uploads/images/original_untouched/1/1234.jpg'
JPEG = b'\xff\xd8\xff' + b'picture' * 100


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
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, headers, body = answer
        return HTTPResponse(status=status, headers=headers, body=io.BytesIO(body), preload_content=False)


OK = (200, {'Content-Type': 'image/jpeg'}, JPEG)


class BackdropTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'artwork.sqlite3'
        self.clock = Clock()
        self.state = State(self.path, clock=self.clock)
        self.addCleanup(self.state.db.close)

    def reader(self, *answers, state=None):
        pool = Pool(*answers)
        return Client(state or self.state, pool, self.clock.sleep, self.clock), pool

    def test_second_browser_and_restart_reuse_durable_image_without_provider_request(self):
        reader, pool = self.reader(OK)
        resolve = Mock(return_value=URL)
        service = Backdrops(resolve, reader, self.clock)
        self.assertEqual(service.get(169).body, JPEG)
        self.assertEqual(service.get(169).body, JPEG)
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(pool.calls, [URL])
        reopened = State(self.path, clock=self.clock)
        self.addCleanup(reopened.db.close)
        reader, new_pool = self.reader(state=reopened)
        self.assertEqual(Backdrops(resolve, reader, self.clock).get(169).body, JPEG)
        self.assertFalse(new_pool.calls)

    def test_concurrent_intent_and_open_share_metadata_and_image(self):
        entered, release = threading.Event(), threading.Event()
        def resolve(show_id):
            entered.set()
            self.assertTrue(release.wait(2))
            return URL
        resolve = Mock(side_effect=resolve)
        reader, pool = self.reader(OK)
        service = Backdrops(resolve, reader, self.clock)
        with ThreadPoolExecutor(max_workers=8) as workers:
            values = [workers.submit(service.get, 169) for _ in range(8)]
            self.assertTrue(entered.wait(1))
            release.set()
            self.assertTrue(all(value.result(2).body == JPEG for value in values))
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(pool.calls, [URL])
        self.assertFalse(service.inflight)

    def test_display_variants_cache_each_size_and_preserve_the_original(self):
        small = b'\xff\xd8\xffsmall picture'
        reader, pool = self.reader((200, {'Content-Type': 'image/jpeg'}, small), OK)
        resolve = Mock(return_value=URL)
        service = Backdrops(resolve, reader, self.clock)
        self.assertEqual(service.get(169, width=780).body, small)
        self.assertEqual(service.get(169, width=780).body, small)
        self.assertEqual(service.get(169, width=1280).body, JPEG)
        self.assertEqual(service.get(169).body, JPEG)
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(pool.calls, [URL.replace('/w1280/', '/w780/'), URL])
        # Provider raster sources that have no display variant retain their quality.
        reader, pool = self.reader(OK)
        service = Backdrops(lambda show_id: TVMAZE, reader, self.clock)
        service.get(169, width=780)
        self.assertEqual(pool.calls, [TVMAZE])

    def test_different_widths_coalesce_the_show_metadata_lookup(self):
        entered, release = threading.Event(), threading.Event()
        def resolve(show_id):
            entered.set()
            self.assertTrue(release.wait(2))
            return URL
        resolve = Mock(side_effect=resolve)
        reader, pool = self.reader(OK, OK)
        service = Backdrops(resolve, reader, self.clock)
        with ThreadPoolExecutor(max_workers=2) as workers:
            values = [workers.submit(service.get, 169, width) for width in (780, 1280)]
            self.assertTrue(entered.wait(1))
            release.set()
            self.assertTrue(all(value.result(2).body == JPEG for value in values))
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(set(pool.calls), {URL.replace('/w1280/', '/w780/'), URL})
        self.assertFalse(service.inflight)
        self.assertFalse(service.resolving)

    def test_supported_widths_are_strict_and_missing_variant_falls_back(self):
        self.assertIsNone(backdrop_width({}))
        self.assertEqual(backdrop_width({'w': ['780']}), 780)
        self.assertEqual(backdrop_width({'w': ['1280']}), 1280)
        for values in (['original'], ['781'], ['0780'], ['780', '1280'], [''], []):
            with self.subTest(values=values), self.assertRaises(ValueError):
                backdrop_width({'w': values})
        reader, pool = self.reader((404, {}, b'gone'), OK)
        service = Backdrops(lambda show_id: URL, reader, self.clock)
        self.assertEqual(service.get(169, width=780).body, JPEG)
        self.assertEqual(service.get(169, width=780).body, JPEG)
        self.assertEqual(pool.calls, [URL.replace('/w1280/', '/w780/'), URL])
        with self.assertRaises(ValueError):
            service.get(169, width=9999)

    def test_missing_art_and_provider_404_have_short_negative_cache(self):
        reader, pool = self.reader((404, {}, b'gone'), OK)
        resolve = Mock(return_value=None)
        service = Backdrops(resolve, reader, self.clock)
        self.assertIsNone(service.get(169))
        self.assertIsNone(service.get(169))
        self.assertEqual(resolve.call_count, 1)
        self.assertFalse(pool.calls)
        self.clock.now += 301
        resolve.return_value = URL
        self.assertIsNone(service.get(169))
        self.assertIsNone(service.get(169))
        self.assertEqual(pool.calls, [URL])
        self.clock.now += 301
        self.assertEqual(service.get(169).body, JPEG)
        self.assertEqual(pool.calls, [URL, URL])

    def test_metadata_cache_is_bounded_and_refreshes_to_new_artwork(self):
        reader, pool = self.reader(OK, OK)
        resolve = Mock(side_effect=lambda show_id: URL)
        service = Backdrops(resolve, reader, self.clock, size=2, ttl=60)
        for show_id in (1, 2, 3):
            service.get(show_id)
        self.assertEqual(list(service.sources), [2, 3])
        self.clock.now += 61
        resolve.side_effect = None
        resolve.return_value = TVMAZE
        self.assertEqual(service.get(3).body, JPEG)
        self.assertEqual(pool.calls, [URL, TVMAZE])

    def test_url_allowlist_rejects_ssrf_query_credentials_and_non_raster_paths(self):
        reader, pool = self.reader()
        unsafe = ['http://image.tmdb.org/t/p/w1280/a-show.jpg',
                  'https://image.tmdb.org.evil.test/t/p/w1280/a-show.jpg',
                  'https://image.tmdb.org:443/t/p/w1280/a-show.jpg',
                  'https://user@image.tmdb.org/t/p/w1280/a-show.jpg',
                  URL + '?target=http://127.0.0.1', URL + '#fragment',
                  'https://image.tmdb.org/t/p/w1280/../a-show.jpg',
                  'https://image.tmdb.org/t/p/w1280/unsafe.svg',
                  'https://static.tvmaze.com/anything.jpg']
        for url in unsafe:
            with self.subTest(url=url), self.assertRaises(LiveError):
                Backdrops(lambda show_id: url, reader).get(169)
        self.assertFalse(pool.calls)

    def test_bad_raster_and_oversized_answers_are_not_cached(self):
        reader, pool = self.reader((200, {'Content-Type': 'image/jpeg'}, b'<svg>not a raster</svg>'), OK)
        service = Backdrops(lambda show_id: URL, reader, self.clock)
        with self.assertRaises(LiveError):
            service.get(169)
        self.assertIsNone(self.state.get(cache_key(URL), 86400))
        with patch('backend.backdrops.MAX_IMAGE', 32), self.assertRaises(LiveError):
            service.get(169)
        self.assertIsNone(self.state.get(cache_key(URL), 86400))
        self.assertEqual(len(pool.calls), 2)

    def test_image_store_evicts_old_bytes_without_evicting_metadata_cache(self):
        self.state.max_bytes = 5000
        blob = b'\x89PNG\r\n\x1a\n' + os.urandom(4000)
        reader, pool = self.reader((200, {}, blob), (200, {}, blob))
        service = Backdrops(lambda show_id: URL if show_id == 1 else TVMAZE, reader, self.clock)
        service.get(1)
        self.clock.now += 1
        service.get(2)
        self.assertIsNone(self.state.get(cache_key(URL), 86400))
        self.assertIsNotNone(self.state.get(cache_key(TVMAZE), 86400))
        total = self.state.db.execute('SELECT SUM(LENGTH(body)) FROM http_cache').fetchone()[0]
        self.assertLessEqual(total, 5000)
        self.assertEqual(len(service.sources), 2)

    def test_only_transient_outages_can_serve_retained_image(self):
        reader, pool = self.reader(OK, *[(500, {}, b'unavailable')] * 3, (404, {}, b'gone'))
        service = Backdrops(lambda show_id: URL, reader, self.clock)
        service.get(169)
        self.clock.now += 8 * 86400
        value = service.get(169)
        self.assertEqual(value.body, JPEG)
        self.assertTrue(value.stale)
        self.assertIsNone(service.get(169))
        self.assertEqual(len(pool.calls), 5)

    def test_outage_does_not_poison_missing_art_cache_and_redirect_cannot_escape_host(self):
        resolve = Mock(side_effect=[LiveError('Details temporarily unavailable.'), URL])
        reader, pool = self.reader((302, {'Location': 'https://127.0.0.1/private'}, b''), OK)
        service = Backdrops(resolve, reader, self.clock)
        with self.assertRaises(LiveError):
            service.get(169)
        with self.assertRaises(LiveError):
            service.get(169)
        self.assertEqual(service.get(169).body, JPEG)
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(pool.calls, [URL, URL])

    def test_persistent_default_follows_outbound_store_and_raster_types_are_safe(self):
        with patch.dict(os.environ, {'OUTBOUND_CACHE': '/shared/cache/http.sqlite3'}, clear=True):
            self.assertEqual(cache_path(), Path('/shared/cache/artwork.sqlite3'))
        with patch.dict(os.environ, {'ARTWORK_CACHE': '/other/art.sqlite3'}, clear=True):
            self.assertEqual(cache_path(), Path('/other/art.sqlite3'))
        self.assertEqual(image_kind(JPEG), 'image/jpeg')
        self.assertEqual(image_kind(b'\x89PNG\r\n\x1a\nrest'), 'image/png')
        self.assertEqual(image_kind(b'RIFF\x00\x00\x00\x00WEBPrest'), 'image/webp')


class BackdropHttpTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {'RATINGS_CACHE': str(Path(cls.folder.name) / 'episodes.sqlite3')})
        cls.environment.start()
        from backend import server
        cls.server = server
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.PUBLIC)))
        cls.worker = threading.Thread(target=cls.http.serve_forever)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.worker.join(2)
        cls.http.server_close()
        cls.server.RATINGS.store.db.close()
        cls.environment.stop()
        cls.folder.cleanup()

    def setUp(self):
        self.state = State(Path(self.folder.name) / self._testMethodName)
        self.addCleanup(self.state.db.close)
        self.pool = Pool(OK)
        self.resolve = Mock(return_value=URL)
        self.service = Backdrops(self.resolve, Client(self.state, self.pool))
        self.replace = patch.object(self.server, 'BACKDROPS', self.service)
        self.replace.start()
        self.addCleanup(self.replace.stop)

    def call(self, path='/api/backdrop?id=169', method='GET', headers=None):
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=10)
        connection.request(method, path, headers=headers or {})
        answer = connection.getresponse()
        result = answer.status, dict(answer.getheaders()), answer.read()
        connection.close()
        return result

    def test_two_browser_sessions_etag_and_head_share_public_image(self):
        status, headers, body = self.call(headers={'Cookie': 'session=one'})
        self.assertEqual((status, body), (200, JPEG))
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        self.assertEqual(headers['Cache-Control'], 'public, max-age=86400')
        self.assertNotIn('Set-Cookie', headers)
        self.assertNotIn('Vary', headers)
        status, second_headers, second = self.call(headers={'Cookie': 'session=two', 'If-None-Match': headers['ETag']})
        self.assertEqual((status, second), (304, b''))
        self.assertEqual(second_headers['ETag'], headers['ETag'])
        status, head_headers, head = self.call(method='HEAD')
        self.assertEqual((status, head), (200, b''))
        self.assertEqual(head_headers['Content-Length'], str(len(JPEG)))
        self.assertEqual(self.resolve.call_count, 1)
        self.assertEqual(self.pool.calls, [URL])

    def test_invalid_ids_and_missing_images_do_not_call_providers(self):
        for query in ('', '?id=no', '?id=0', '?id=999999999', '?url=' + URL,
                      '?id=169&w=original', '?id=169&w=9999', '?id=169&w=780&w=1280'):
            status, headers, body = self.call('/api/backdrop' + query)
            self.assertEqual(status, 400)
            self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertFalse(self.pool.calls)
        self.assertFalse(self.resolve.called)
        self.resolve.return_value = None
        for method in ('GET', 'HEAD'):
            status, headers, body = self.call(method=method)
            self.assertEqual(status, 404)
            self.assertEqual(headers['Cache-Control'], 'public, max-age=300')
            if method == 'HEAD':
                self.assertEqual(body, b'')
        self.assertEqual(self.resolve.call_count, 1)

    def test_http_display_variant_uses_bounded_provider_size_and_normal_browser_cache(self):
        status, headers, body = self.call('/api/backdrop?id=169&w=780')
        self.assertEqual((status, body), (200, JPEG))
        self.assertEqual(headers['Cache-Control'], 'public, max-age=86400')
        status, _, body = self.call('/api/backdrop?id=169&w=780', headers={'If-None-Match': headers['ETag']})
        self.assertEqual((status, body), (304, b''))
        self.assertEqual(self.pool.calls, [URL.replace('/w1280/', '/w780/')])
        self.assertEqual(self.resolve.call_count, 1)

    def test_temporary_failures_and_slot_limits_are_not_browser_cached(self):
        self.resolve.side_effect = LiveError('Service resting.', 503, 12)
        status, headers, body = self.call()
        self.assertEqual(status, 503)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Retry-After'], '12')
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        with patch.object(self.server, 'ARTWORK_SLOTS', semaphore):
            status, headers, body = self.call(method='HEAD')
        self.assertEqual(status, 503)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(body, b'')
        self.assertFalse(self.pool.calls)

    def test_source_prefers_tmdb_and_reuses_tvmaze_details_without_second_api_call(self):
        live_fetch = Mock(return_value={'id': 169, 'name': 'A show', '_embedded': {
            'cast': [], 'seasons': [], 'images': [{'type': 'background', 'main': True,
                'resolutions': {'original': {'url': TVMAZE}}}]}})
        live = Live(fetch=live_fetch)
        with patch.object(self.server, 'TMDB', {169: {'backdrop': URL}}), patch.object(self.server, 'LIVE', live):
            self.assertEqual(self.server.backdrop_source(169), URL)
            self.assertFalse(live_fetch.called)
        with patch.object(self.server, 'TMDB', {}), patch.object(self.server, 'LIVE', live):
            self.assertEqual(self.server.backdrop_source(169), TVMAZE)
            self.assertEqual(live.show(169)['backdrop'], TVMAZE)
            self.assertEqual(self.server.backdrop_source(169), TVMAZE)
            self.assertEqual(live_fetch.call_count, 1)


if __name__ == '__main__':
    main()
