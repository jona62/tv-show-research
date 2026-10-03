"""Exercise attribution and privacy rules independently of a live load run."""
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import importlib.util
import json
import sys
import threading
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools/loadtest/browser_journeys.py'
spec = importlib.util.spec_from_file_location('couchside_browser_journeys', MODULE)
journeys = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = journeys
spec.loader.exec_module(journeys)


class BrowserJourneyTests(unittest.TestCase):
    def test_seeded_plans_are_reproducible_varied_and_bounded(self):
        first = journeys.make_plan(17, 0, 0)
        self.assertEqual(first, journeys.make_plan(17, 0, 0))
        plans = [journeys.make_plan(17, user, iteration) for user in range(12) for iteration in range(2)]
        self.assertGreater(len({json.dumps(plan, sort_keys=True) for plan in plans}), 20)
        self.assertEqual({plan['mobile'] for plan in plans}, {True, False})
        self.assertTrue(all(2 <= len(plan['shows']) <= 5 and len(set(plan['shows'])) == len(plan['shows']) for plan in plans))
        supplied = journeys.make_plan(17, 0, 0, [82, 82, 182])
        self.assertEqual(set(supplied['shows']), {82, 182})
        for pool in ([82], [82, -1]):
            with self.assertRaises(ValueError):
                journeys.make_plan(1, 0, 0, pool)

    def test_http_cache_sw_cache_and_real_worker_fetch_do_not_double_count_wire(self):
        recorder = journeys.NetworkRecorder('http://127.0.0.1:18091')
        def request(target, identifier, url, worker=False, response=None, cached=False, bytes=0):
            recorder.event('Network.requestWillBeSent', {'requestId': identifier, 'request': {'url': url, 'method': 'GET'}}, target, worker)
            if cached:
                recorder.event('Network.requestServedFromCache', {'requestId': identifier}, target)
            recorder.event('Network.responseReceived', {'requestId': identifier, 'response': {'status': 200, **(response or {})}}, target)
            recorder.event('Network.loadingFinished', {'requestId': identifier, 'encodedDataLength': bytes}, target)
        request('page', '1', 'http://127.0.0.1:18091/api/backdrop?id=82', response={'fromServiceWorker': True,
            'serviceWorkerResponseSource': 'network'}, bytes=10000)
        request('worker', '1', 'http://127.0.0.1:18091/api/backdrop?id=82', worker=True, bytes=3500)
        request('page', '2', 'https://static.tvmaze.com/poster.jpg', cached=True, bytes=9000)
        request('page', '3', 'http://127.0.0.1:18091/api/backdrop?id=182', response={'fromServiceWorker': True,
            'serviceWorkerResponseSource': 'cache-storage'}, bytes=10000)
        summary = recorder.summary()
        self.assertEqual(summary['wire_bytes'], 3500)
        self.assertEqual(summary['api_calls'], 1)
        self.assertEqual(summary['logical_api_requests'], 2)
        self.assertEqual(summary['http_cache_hits'], 1)
        self.assertEqual(summary['service_worker_deliveries'], 2)
        self.assertEqual(summary['service_worker_cache_storage_responses'], 1)
        self.assertEqual(summary['worker_network_requests'], 1)
        self.assertFalse(summary['observed_no_new_requests'])
        self.assertTrue(recorder.summary(4)['observed_no_new_requests'])
        self.assertEqual(recorder.summary(4)['http_cache_hits'], 0, 'No request is reuse, not a fabricated cache hit')

    def test_failures_cancellations_and_redirects_stay_observable(self):
        recorder = journeys.NetworkRecorder('http://localhost')
        start = {'requestId': '1', 'request': {'url': 'http://localhost/api/search?q=Crimnal', 'method': 'GET'}}
        recorder.event('Network.requestWillBeSent', start)
        recorder.event('Network.loadingFailed', {'requestId': '1', 'errorText': 'net::ERR_ABORTED', 'canceled': True})
        recorder.event('Network.requestWillBeSent', {**start, 'requestId': '2'})
        recorder.event('Network.responseReceived', {'requestId': '2', 'response': {'status': 503}})
        recorder.event('Network.loadingFinished', {'requestId': '2', 'encodedDataLength': 80})
        recorder.event('Network.requestWillBeSent', {**start, 'requestId': '3'})
        recorder.event('Network.requestWillBeSent', {**start, 'requestId': '3', 'redirectResponse': {'status': 302, 'encodedDataLength': 100}})
        summary = recorder.summary()
        self.assertEqual(summary['cancelled_requests'], 1)
        self.assertEqual(summary['failed_requests'], 0)
        self.assertEqual(summary['http_errors'], 1)
        self.assertEqual(summary['requests_started'], 4)
        self.assertEqual(summary['requests_finished'], 3)
        self.assertEqual(summary['wire_bytes'], 180)

    def test_private_auth_pool_and_transfer_values_are_not_serialized(self):
        self.assertEqual(journeys.safe_url('http://localhost/#t=private-list-copy'), 'http://localhost/')
        self.assertEqual(journeys.safe_url('data:image/png;base64,private-image'), 'data:')
        error = journeys.safe_error('fill("secret-password") account load-test@example.com token abc123 #t=private-list-copy',
            {'email': 'load-test@example.com', 'password': 'secret-password', 'token': 'abc123'})
        for secret in ('secret-password', 'load-test@example.com', 'abc123', 'private-list-copy'):
            self.assertNotIn(secret, error)
        with TemporaryDirectory() as folder:
            file = Path(folder) / 'pool.json'
            file.write_text(json.dumps({'cookie_name': 'couchside-dev-session', 'accounts': [
                {'email': 'load-test@example.com', 'password': 'secret-password', 'token': 'abc123'}]}))
            self.assertEqual(len(journeys.load_auth_pool(file)), 1)
            file.write_text('{"accounts":[{"token":"abc123"}]}')
            with self.assertRaises(ValueError):
                journeys.load_auth_pool(file)

    def test_fatal_journey_retains_completed_action_evidence_and_redacts_error(self):
        journey = journeys.Journey('http://localhost', 0, 0, journeys.make_plan(1, 0, 0),
            journeys.NetworkRecorder('http://localhost'), None, Path('/tmp'), 'test',
            {'email': 'test@example.com', 'password': 'secret-password'})
        journey.actions = [{'name': 'first-page', 'ok': True, 'request_start': 0, 'request_end': 0, 'duration_ms': 12}]
        result = journey.report(fatal=RuntimeError('fill("secret-password") timed out'))
        self.assertEqual(len(result['actions']), 1)
        self.assertTrue(result['actions'][0]['network']['observed_no_new_requests'])
        self.assertNotIn('secret-password', result['fatal_error'])
        self.assertIn('[redacted]', result['fatal_error'])

    def test_unavailable_or_reset_worker_counters_are_not_reported_as_zero_hits(self):
        self.assertEqual(journeys.count_delta({'available': False}, {'available': True, 'counts': {'imageHits': 5}}), {'available': False})
        self.assertEqual(journeys.count_delta({'available': True, 'counts': {'imageHits': 2}},
            {'available': True, 'counts': {'imageHits': 5}}), {'available': True, 'counts': {'imageHits': 3}})
        self.assertFalse(journeys.count_delta({'available': True, 'counts': {'imageHits': 5}},
            {'available': True, 'counts': {'imageHits': 2}})['available'])


class BrowserNetworkIntegration(unittest.IsolatedAsyncioTestCase):
    """A real local server/worker proves CDP attribution without cache interception."""
    async def test_worker_fetch_and_cached_delivery_keep_separate_ownership(self):
        counts = {}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                counts[self.path] = counts.get(self.path, 0) + 1
                kind, cache = 'text/plain', 'no-store'
                if self.path == '/':
                    kind = 'text/html'
                    body = b'''<script>(async()=>{await navigator.serviceWorker.register('/sw.js');
                    await navigator.serviceWorker.ready;if(!navigator.serviceWorker.controller)
                    await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
                    window.ready=true;})();</script>'''
                elif self.path == '/sw.js':
                    kind = 'text/javascript'
                    body = b'''self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
                    self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
                    self.addEventListener('fetch',event=>{if(new URL(event.request.url).pathname==='/asset')
                    event.respondWith((async()=>{const cache=await caches.open('test-images');
                    const kept=await cache.match(event.request);if(kept)return kept;
                    const answer=await fetch(event.request);await cache.put(event.request,answer.clone());return answer;})());});'''
                else:
                    body, cache = b'A small genuinely transferred response.', 'public, max-age=86400'
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', cache)
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                recorder = journeys.NetworkRecorder(origin)
                observer = journeys.BrowserNetwork(browser, recorder)
                await observer.start()
                context = await browser.new_context(service_workers='allow')
                page = await context.new_page()
                await observer.page(context, page, 'primary')
                await page.goto(origin, wait_until='domcontentloaded')
                await page.wait_for_function('window.ready===true')
                await page.evaluate("""()=>{localStorage.setItem('couchside-v1',JSON.stringify({saved:[{id:82}]}));
                    localStorage.setItem('couchside-account-active-v1',JSON.stringify({id:'test-owner'}));
                    localStorage.setItem('couchside-account-v1:test-owner',JSON.stringify({local:{saved:[{id:182}]}}));}""")
                self.assertEqual((await page.evaluate(journeys.LOCAL_STATE_SCRIPT))['saved'], [{'id': 182}],
                                 'Authenticated list checks must inspect the owner cache and preserve the guest list')
                await page.evaluate("localStorage.removeItem('couchside-account-active-v1')")
                self.assertEqual((await page.evaluate(journeys.LOCAL_STATE_SCRIPT))['saved'], [{'id': 82}])
                await page.evaluate("async()=>{await(await fetch('/asset')).text();await(await fetch('/asset')).text();"
                                    "await(await fetch('/plain')).text();await(await fetch('/plain')).text();}")
                await asyncio.sleep(.2)
                self.assertEqual(counts['/asset'], 1, 'A Cache Storage hit does not make a second physical fetch')
                self.assertEqual(counts['/plain'], 1, 'Normal browser HTTP caching stays enabled')
                asset = [record for record in recorder.records if record['url'].endswith('/asset')]
                self.assertEqual(sum(record['worker_owned'] for record in asset), 1)
                self.assertEqual(sum(record['service_worker'] for record in asset), 2)
                self.assertGreater(sum(record['wire_bytes'] for record in asset), 0)
                self.assertTrue(all(record['wire_bytes'] == 0 for record in asset if record['service_worker']))
                self.assertGreaterEqual(recorder.summary()['http_cache_hits'], 1)
                self.assertFalse(observer.errors, observer.errors)
                await browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
