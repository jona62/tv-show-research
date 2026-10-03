"""Transport parity, upload boundaries and independent admission lanes."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.asgi import Application, Lane, Busy, BackgroundOwner


class TransportTests(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.env = patch.dict(os.environ, {'RATINGS_CACHE': str(root / 'episodes.sqlite3'),
            'ACCOUNT_DB': str(root / 'accounts.sqlite3'), 'OUTBOUND_CACHE': str(root / 'http.sqlite3'),
            'ARTWORK_CACHE': str(root / 'artwork.sqlite3'), 'COUCHSIDE_LOAD_TEST_NO_OUTBOUND': '1'})
        cls.env.start()
        from backend import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.folder.cleanup()

    async def asyncSetUp(self):
        self.app = Application(background=False)
        self.addCleanup(lambda: [lane.close() for lane in self.app.lanes.values()])

    async def request(self, path, method='GET', body=b'', headers=(), receive=None, client=('127.0.0.1', 1234), events=False):
        scope = {'type': 'http', 'path': path.split('?')[0], 'raw_path': path.split('?')[0].encode(),
                 'query_string': path.partition('?')[2].encode(), 'method': method, 'http_version': '1.1',
                 'client': client, 'headers': [(b'host', b'localhost'), *headers]}
        sent = []
        incoming = asyncio.Queue()
        incoming.put_nowait({'type': 'http.request', 'body': body})
        async def outgoing(event):
            sent.append(event)
        await self.app(scope, receive or incoming.get, outgoing)
        if events:
            return sent
        return sent[0]['status'], dict(sent[0]['headers']), sent[1]['body']

    async def test_public_batches_keep_etags_gzip_head_and_security(self):
        path = '/api/show-cards?ids=82,182,123,2,541'
        status, headers, body = await self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual([show['id'] for show in json.loads(body)['shows']], [82,182,123,2,541])
        self.assertIn(b'public', headers[b'cache-control'])
        self.assertIn(b'content-security-policy', headers)
        status, fresh, empty = await self.request(path, headers=((b'if-none-match', headers[b'etag']),))
        self.assertEqual((status, empty), (304, b''))
        self.assertNotIn(b'content-length', fresh)
        status, head, empty = await self.request(path, 'HEAD')
        self.assertEqual((status, empty), (200, b''))
        self.assertEqual(int(head[b'content-length']), len(body))
        _, compressed, _ = await self.request(path, headers=((b'accept-encoding', b'gzip'),))
        self.assertEqual(compressed[b'content-encoding'], b'gzip')
        self.assertNotEqual(compressed[b'etag'], headers[b'etag'])

    async def test_account_duplicate_host_and_cross_origin_still_rejected(self):
        status, headers, body = await self.request('/api/account/session', headers=((b'host', b'evil.example'),))
        self.assertEqual(status, 400)
        self.assertEqual(headers[b'cache-control'], b'no-store')
        payload = b'{"email":"test@example.com","password":"a long password"}'
        headers = ((b'content-type', b'application/json'), (b'content-length', str(len(payload)).encode()),
                   (b'origin', b'https://evil.example'), (b'x-account-request', b'1'))
        self.assertEqual((await self.request('/api/account/login', 'POST', payload, headers))[0], 403)

    async def test_upload_limits_and_content_type_survive_adapter(self):
        payload = b'{"ids":[82]}'
        self.assertEqual((await self.request('/api/shows', 'POST', payload,
            ((b'content-length', str(len(payload)).encode()),)))[0], 415)
        status, _, body = await self.request('/api/shows', 'POST', payload,
            ((b'content-length', str(len(payload)).encode()), (b'content-type', b'application/json')))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['shows'][0]['id'], 82)
        self.assertEqual((await self.request('/api/shows', 'POST', b'x' * (self.server.MOST_BODY + 1),
            ((b'content-length', str(self.server.MOST_BODY + 1).encode()),)))[0], 413)

    async def test_upload_framing_is_exact_and_early_rejections_do_not_read_bodies(self):
        payload = b'{"ids":[82]}'
        content_type = ((b'content-type', b'application/json'),)
        for length in (len(payload) - 1, len(payload) + 1):
            status, headers, _ = await self.request('/api/shows', 'POST', payload,
                (*content_type, (b'content-length', str(length).encode())))
            self.assertEqual(status, 400)
            self.assertEqual(headers[b'connection'], b'close')
        async def forbidden_receive():
            self.fail('Invalid framing must be rejected before receiving any upload.')
        for headers, expected in (
            (content_type, 400),
            ((*content_type, (b'content-length', b'12'), (b'content-length', b'12')), 400),
            ((*content_type, (b'content-length', b'12'), (b'transfer-encoding', b'chunked')), 400),
            ((*content_type, (b'content-length', b'999999999')), 413),
        ):
            self.assertEqual((await self.request('/api/shows', 'POST', headers=headers,
                receive=forbidden_receive))[0], expected)
        self.assertEqual((await self.request('/api/account/password', 'POST',
            headers=(*content_type, (b'content-length', b'4097')), receive=forbidden_receive))[0], 413)

    async def test_slow_upload_does_not_block_a_public_read(self):
        async def delayed():
            await asyncio.sleep(.15)
            return {'type': 'http.request', 'body': b'{}'}
        upload = asyncio.create_task(self.request('/api/shows', 'POST',
            headers=((b'content-length', b'2'), (b'content-type', b'application/json')), receive=delayed))
        await asyncio.sleep(.02)
        started = time.monotonic()
        self.assertEqual((await self.request('/healthz'))[0], 200)
        self.assertLess(time.monotonic() - started, .1)
        await upload

    async def test_upload_timeout_closes_the_connection(self):
        async def delayed():
            await asyncio.sleep(.05)
            return {'type': 'http.request', 'body': b'{}'}
        with patch.object(self.server, 'BODY_TIMEOUT', .01):
            status, headers, _ = await self.request('/api/shows', 'POST',
                headers=((b'content-length', b'2'), (b'content-type', b'application/json')), receive=delayed)
        self.assertEqual(status, 408)
        self.assertEqual(headers[b'connection'], b'close')

    async def test_split_cookies_reach_accounts_without_cache_or_compression(self):
        tokens = []
        token = 'a' * 43
        class Service:
            def session(self, actual, *args, **kwargs):
                tokens.append(actual)
                return {'account': {'email': 'private@example.com'}, 'state': {'list': ['x'] * 200}}
        with patch.object(self.server.ACCOUNT_ROUTES, 'service', return_value=Service()):
            status, headers, body = await self.request('/api/account/session', headers=(
                (b'cookie', b'other=1'), (b'cookie', ('couchside-dev-session=' + token).encode()),
                (b'accept-encoding', b'gzip'), (b'if-none-match', b'*')))
        self.assertEqual(status, 200)
        self.assertEqual(tokens, [token])
        self.assertEqual(json.loads(body)['account']['email'], 'private@example.com')
        self.assertEqual(headers[b'cache-control'], b'no-store')
        self.assertNotIn(b'etag', headers)
        self.assertNotIn(b'content-encoding', headers)

    async def test_explicit_gateway_trust_keeps_account_attempt_limits_per_client(self):
        from backend.account_http import AccountRoutes
        from backend.accounts import AccountError
        from backend.request_limits import Budget
        calls = []
        class Service:
            def login(self, email, password, guest_state):
                calls.append(email)
                raise AccountError(401, 'Invalid credentials.')
        payload = b'{"email":"viewer@example.com","password":"long test password"}'
        common = ((b'content-type', b'application/json'), (b'content-length', str(len(payload)).encode()),
                  (b'origin', b'https://localhost'), (b'x-account-request', b'1'))
        with patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': '172.16.0.1,100.107.153.113'}):
            routes = AccountRoutes(lambda: Service(), https_only=True)
            routes.attempts = Budget(rate=1 / 60, burst=1)
            with patch.object(self.server, 'ACCOUNT_ROUTES', routes):
                async def login(peer, identity):
                    forwarded = f'192.0.2.99, {identity}, 100.107.153.113'
                    return (await self.request('/api/account/login', 'POST', payload,
                        (*common, (b'x-forwarded-for', forwarded.encode())), client=(peer, 1234)))[0]
                self.assertEqual(await login('172.16.0.1', '203.0.113.1'), 401)
                self.assertEqual(await login('172.16.0.1', '203.0.113.1'), 429)
                self.assertEqual(await login('172.16.0.1', '203.0.113.2'), 401)
                self.assertEqual(await login('172.16.0.2', '203.0.113.3'), 401)
                self.assertEqual(await login('172.16.0.2', '203.0.113.4'), 429)
        self.assertEqual(len(calls), 3)

    async def test_cpu_lane_queue_does_not_block_public_read(self):
        gate = threading.Event()
        active = asyncio.create_task(self.app.lanes['engine'].run(lambda: gate.wait(1)))
        await asyncio.sleep(.02)
        self.assertEqual((await self.request('/healthz'))[0], 200)
        gate.set()
        await active

    async def until(self, condition):
        async with asyncio.timeout(1):
            while not condition():
                await asyncio.sleep(.001)

    async def test_disconnect_removes_queued_get_and_post_without_running_handlers(self):
        calls = []
        base = self.app.handler
        class Request(base):
            def run(self):
                calls.append(self.command)
                return 200, [], b''
        lane = self.app.lanes['engine']
        for method, path in (('GET', '/api/show-cards?ids=82'), ('POST', '/api/account/state')):
            entered, release = threading.Event(), threading.Event()
            def occupy():
                entered.set()
                release.wait(2)
            active = asyncio.create_task(lane.run(occupy))
            await self.until(entered.is_set)
            incoming = asyncio.Queue()
            incoming.put_nowait({'type': 'http.request', 'body': b'{}' if method == 'POST' else b''})
            headers = ((b'content-type', b'application/json'), (b'content-length', b'2'))
            with patch.object(self.app, 'handler', Request), patch.object(self.app, 'lane', return_value='engine'), \
                    patch.object(self.server.telemetry, 'record_request') as metrics:
                queued = asyncio.create_task(self.request(path, method, headers=headers,
                    receive=incoming.get, events=True))
                try:
                    await self.until(lambda: lane.waiting == 2)
                    incoming.put_nowait({'type': 'http.disconnect'})
                    self.assertEqual(await asyncio.wait_for(queued, .5), [])
                    self.assertEqual(calls, [])
                    self.assertEqual(lane.waiting, 1)
                    self.assertEqual(metrics.call_args.args[2], 499)
                    self.assertEqual(metrics.call_args.kwargs['bytes'], 0)
                finally:
                    release.set()
                    if not queued.done():
                        queued.cancel()
                    await asyncio.gather(queued, active, return_exceptions=True)
            self.assertEqual(lane.waiting, 0)

    async def test_active_disconnect_finishes_mutation_and_holds_slot_without_response(self):
        entered, release, calls = threading.Event(), threading.Event(), []
        base = self.app.handler
        class Request(base):
            def run(self):
                body = self.rfile.read()
                entered.set()
                release.wait(2)
                calls.append(body)
                return 200, [], b'completed mutation'
        incoming = asyncio.Queue()
        body = b'{"saved":[82]}'
        incoming.put_nowait({'type': 'http.request', 'body': body})
        headers = ((b'content-type', b'application/json'), (b'content-length', str(len(body)).encode()))
        lane = self.app.lanes['engine']
        with patch.object(self.app, 'handler', Request), patch.object(self.app, 'lane', return_value='engine'), \
                patch.object(self.server.telemetry, 'record_request') as metrics:
            active = asyncio.create_task(self.request('/api/account/state', 'POST', headers=headers,
                receive=incoming.get, events=True))
            try:
                await self.until(entered.is_set)
                incoming.put_nowait({'type': 'http.disconnect'})
                await asyncio.sleep(.02)
                self.assertFalse(active.done())
                self.assertEqual(lane.waiting, 1)
                self.assertTrue(lane.slots.locked())
                self.assertEqual(calls, [])
            finally:
                release.set()
            self.assertEqual(await asyncio.wait_for(active, .5), [])
            self.assertEqual(calls, [body])
            self.assertEqual(lane.waiting, 0)
            self.assertEqual(metrics.call_args.args[2], 499)
            self.assertEqual(metrics.call_args.kwargs['bytes'], 0)

    async def test_disconnect_watcher_starts_after_complete_chunked_upload(self):
        finish_upload, requested_tail, watcher_cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls, receiving, bodies = 0, False, []
        first, tail = b'{"ids":', b'[82]}'
        async def receive():
            nonlocal calls, receiving
            self.assertFalse(receiving, 'The upload and watcher must not race receive().')
            receiving = True
            calls += 1
            try:
                if calls == 1:
                    return {'type': 'http.request', 'body': first, 'more_body': True}
                if calls == 2:
                    requested_tail.set()
                    await finish_upload.wait()
                    return {'type': 'http.request', 'body': tail, 'more_body': False}
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    watcher_cancelled.set()
                    raise
            finally:
                receiving = False
        base = self.app.handler
        class Request(base):
            def run(self):
                bodies.append(self.rfile.read())
                return 200, [], b'ok'
        headers = ((b'content-type', b'application/json'), (b'content-length', str(len(first + tail)).encode()))
        with patch.object(self.app, 'handler', Request):
            active = asyncio.create_task(self.request('/api/shows', 'POST', headers=headers, receive=receive))
            await asyncio.wait_for(requested_tail.wait(), .5)
            self.assertEqual(bodies, [])
            self.assertEqual(calls, 2)
            finish_upload.set()
            status, _, body = await asyncio.wait_for(active, .5)
        self.assertEqual((status, body), (200, b'ok'))
        self.assertEqual(bodies, [first + tail])
        self.assertTrue(watcher_cancelled.is_set())

    async def test_repeated_transport_cancellation_drains_active_work_before_releasing_admission(self):
        entered, release = threading.Event(), threading.Event()
        def work():
            entered.set()
            release.wait(2)
        lane, incoming = self.app.lanes['engine'], asyncio.Queue()
        active = asyncio.create_task(self.app.execute({'method': 'POST', 'path': '/api/home'}, incoming.get, work))
        try:
            await self.until(entered.is_set)
            active.cancel()
            await asyncio.sleep(.01)
            active.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(active.done())
            self.assertEqual(lane.waiting, 1)
            self.assertTrue(lane.slots.locked())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await active
        self.assertEqual(lane.waiting, 0)

    async def test_closed_response_stream_records_cancellation_instead_of_success(self):
        scope = {'type': 'http', 'path': '/healthz', 'method': 'GET', 'headers': [(b'host', b'localhost')]}
        incoming = asyncio.Queue()
        incoming.put_nowait({'type': 'http.request', 'body': b''})
        async def send(event):
            raise OSError('Disconnected socket')
        with patch.object(self.server.telemetry, 'record_request') as metrics:
            await self.app(scope, incoming.get, send)
        self.assertEqual(metrics.call_args.args[2], 499)
        self.assertEqual(metrics.call_args.kwargs['bytes'], 0)

    async def test_queued_foreground_defers_home_speculation_in_filtered_views(self):
        lane = self.app.lanes['engine']
        filtered = self.server.DISCOVERY.view({'genres': ['Drama']})
        try:
            lane.waiting = 1
            self.assertTrue(self.server.LIBRARY.can_keep_ahead())
            self.assertTrue(filtered.can_keep_ahead())
            lane.waiting = 2
            self.assertFalse(self.server.LIBRARY.can_keep_ahead())
            self.assertFalse(filtered.can_keep_ahead())
        finally:
            lane.waiting = 0

    async def test_bounded_lane_and_single_background_owner(self):
        lane, gate = Lane('test', 1, 1), threading.Event()
        active = asyncio.create_task(lane.run(lambda: gate.wait(1)))
        await asyncio.sleep(.02)
        with self.assertRaises(Busy):
            await lane.run(lambda: None)
        gate.set()
        await active
        lane.close()
        starts = []
        first, second = BackgroundOwner(lambda: starts.append(1)), BackgroundOwner(lambda: starts.append(2))
        first.elect(); second.elect()
        self.assertEqual(starts, [1])
        first.close(); second.elect()
        self.assertEqual(starts, [1,2])
        second.close()

    async def test_repeated_cancellation_keeps_admission_until_thread_finishes(self):
        lane, entered, release = Lane('cancel-test', 1, 1), threading.Event(), threading.Event()
        self.addCleanup(lane.close)
        def work():
            entered.set()
            release.wait(2)
        active = asyncio.create_task(lane.run(work))
        while not entered.is_set():
            await asyncio.sleep(.001)
        try:
            active.cancel()
            await asyncio.sleep(.01)
            active.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(active.done())
            with self.assertRaises(Busy):
                await lane.run(lambda: None)
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await active
        self.assertEqual(lane.waiting, 0)

    async def test_shutdown_retains_ownership_while_a_provider_call_is_draining(self):
        owner = BackgroundOwner(lambda: None)
        owner.elect()
        self.addCleanup(owner.close)
        self.app.owner = owner
        sent = []
        async def receive():
            return {'type': 'lifespan.shutdown'}
        async def send(event):
            sent.append(event)
        with patch.object(self.server, 'stop_background', return_value=False) as stop, \
                patch.object(self.server.telemetry, 'stop'):
            await self.app.lifespan(receive, send)
        stop.assert_called_once_with()
        self.assertIsNotNone(owner.file)
        follower = BackgroundOwner(lambda: self.fail('A draining owner must retain the provider lock.'))
        follower.elect()
        self.addCleanup(follower.close)
        self.assertIsNone(follower.file)
        self.assertEqual(sent, [{'type': 'lifespan.shutdown.complete'}])

    async def test_background_stop_interrupts_hour_wait_and_preserves_provider_drain(self):
        from backend.added import Added
        entered = threading.Event()
        def updates(*args, **kwargs):
            entered.set()
            return {}
        added = Added(SimpleNamespace(get=updates), newest=1, reach=10)
        worker = threading.Thread(target=added.run, daemon=True)
        worker.start()
        while not entered.is_set():
            await asyncio.sleep(.001)
        ratings = SimpleNamespace(stop=threading.Event(), ready=threading.Event(), workers=[])
        with patch.object(self.server, 'ADDED', added), patch.object(self.server, 'RATINGS', ratings), \
                patch.object(self.server, 'BACKGROUND_THREADS', [worker]):
            self.assertTrue(await asyncio.to_thread(self.server.stop_background, .5))
        self.assertTrue(ratings.stop.is_set())
        self.assertTrue(ratings.ready.is_set())
        self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    main()
