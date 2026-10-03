"""Bounded asynchronous transport around the existing HTTP/domain boundary.

Idle connections and slow uploads use no handler threads. Public reads, CPU work,
account writes/password work and live provider requests have independent queues.
The existing route handler retains validation, CSRF, cookies, SEO and cache rules.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
import fcntl
import io
import logging
import os
from pathlib import Path
import time

LOG = logging.getLogger(__name__)


class MemoryConnection:
    """Legacy readers already receive a complete, deadline-bounded ASGI upload."""
    timeout = None

    def gettimeout(self):
        return self.timeout

    def settimeout(self, timeout):
        self.timeout = timeout


def handler_type(base):
    class Request(base):
        def __init__(self, scope, body):
            self.command = scope['method']
            self.path = scope.get('raw_path', scope['path'].encode()).decode('latin1')
            if scope.get('query_string'):
                self.path += '?' + scope['query_string'].decode('latin1')
            self.request_version = 'HTTP/' + scope.get('http_version', '1.1')
            self.requestline = self.command + ' ' + self.path + ' ' + self.request_version
            self.client_address = scope.get('client') or ('127.0.0.1', 0)
            self.directory = str(Path(__file__).resolve().parents[1] / 'public')
            self.headers = Message()
            cookies = []
            for key, value in scope['headers']:
                if key.lower() == b'cookie':
                    cookies.append(value.decode('latin1'))
                else:
                    self.headers[key.decode('latin1')] = value.decode('latin1')
            if cookies:
                self.headers['Cookie'] = '; '.join(cookies)
            self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
            self.connection, self.close_connection = MemoryConnection(), False
            self.status, self.response_headers = 500, []
            self._headers_buffer = []
            self._metrics_status, self._metrics_bytes = None, 0

        def send_response(self, code, message=None):
            self.status = self._metrics_status = code

        def send_header(self, key, value):
            self.response_headers.append((key.lower().encode('latin1'), str(value).encode('latin1')))

        def flush_headers(self):
            pass

        def run(self):
            method = getattr(self, 'do_' + self.command, None)
            if method is None:
                self.send_error(405, 'Method not allowed.')
            else:
                method()
            return self.status, self.response_headers, self.wfile.getvalue()
    return Request


class Busy(Exception):
    pass


class UploadError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Lane:
    def __init__(self, name, workers, capacity):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self.slots, self.capacity, self.waiting = asyncio.Semaphore(workers), capacity, 0

    async def run(self, work):
        if self.waiting >= self.capacity:
            raise Busy()
        self.waiting += 1
        try:
            async with self.slots:
                # Shield keeps the slot until domain work finishes on shutdown.
                future = asyncio.get_running_loop().run_in_executor(self.executor, work)
                try:
                    return await asyncio.shield(future)
                except asyncio.CancelledError:
                    # Graceful shutdown may cancel a task more than once. Keep
                    # shielding the actual thread work so a second cancellation
                    # cannot release admission while it is still running.
                    while not future.done():
                        try:
                            await asyncio.shield(future)
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            break
                    if not future.cancelled():
                        future.exception()
                    raise
        finally:
            self.waiting -= 1

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


class BackgroundOwner:
    """One host-local owner warms shared caches; other workers can take over."""
    def __init__(self, start):
        self.start, self.file = start, None

    def elect(self):
        if self.file is not None:
            return
        root = Path(os.environ.get('RATINGS_CACHE') or Path(__file__).resolve().parents[2] / 'data/cache/episode-ratings.sqlite3').parent
        root.mkdir(parents=True, exist_ok=True)
        candidate = (root / 'couchside-warm.lock').open('a')
        try:
            fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            candidate.close()
            return
        self.file = candidate
        try:
            self.start()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


class Application:
    def __init__(self, handler=None, background=True):
        from . import server
        self.server = server
        self.handler = handler or handler_type(server.Handler)
        self.lanes = {name: Lane(name, workers, capacity) for name, workers, capacity in (
            ('public', 8, 256), ('engine', 1, 64), ('account', 4, 64),
            ('password', 2, 16), ('live', 8, 64))}
        server.LIBRARY.can_keep_ahead = lambda: self.lanes['engine'].waiting <= 1
        self.uploads = asyncio.Semaphore(32)
        self.owner = BackgroundOwner(server.start_background) if background else None
        self.election = None

    def lane(self, scope):
        path = scope['path']
        if path.startswith('/api/account/'):
            return 'password' if path.rsplit('/', 1)[-1] in ('signup', 'login', 'password') else 'account'
        if path in ('/api/features', '/api/tracking'):
            return 'account'
        if path == '/api/tracking/catalogue':
            return 'live'
        if scope['method'] == 'POST' and path in ('/api/home', '/api/browse', '/api/title', '/api/taste'):
            return 'engine'
        if path in (*self.server.LIVE_ROUTES, *self.server.PEOPLE_ROUTES, '/api/backdrop', '/api/icon', '/api/search'):
            return 'live'
        return 'public'

    async def upload(self, scope, receive):
        lengths = [value for key, value in scope['headers'] if key.lower() == b'content-length']
        if len(lengths) != 1 or any(key.lower() == b'transfer-encoding' for key, _ in scope['headers']):
            raise UploadError(400, 'Send a fixed-length JSON body.')
        try:
            expected = int(lengths[0])
        except ValueError:
            expected = 0
        if scope['path'] == '/api/tracking':
            limit = 4096
        elif scope['path'].startswith('/api/account/'):
            route = scope['path'].rsplit('/', 1)[-1]
            limit = 262144 if route in ('signup', 'login', 'state') else 4096
        else:
            limit = self.server.MOST_BODY
        if not 0 < expected <= limit:
            raise UploadError(413, 'That request is too large or empty.')
        chunks, count = [], 0
        async with asyncio.timeout(self.server.BODY_TIMEOUT):
            async with self.uploads:
                while True:
                    event = await receive()
                    if event['type'] == 'http.disconnect':
                        raise ConnectionError()
                    chunk = event.get('body', b'')
                    count += len(chunk)
                    if count > expected:
                        raise UploadError(400, 'The body does not match its declared length.')
                    chunks.append(chunk)
                    if not event.get('more_body', False):
                        if count != expected:
                            raise UploadError(400, 'The body does not match its declared length.')
                        return b''.join(chunks)

    async def elect(self):
        while True:
            self.server.ADDED.restore(self.server.ADDED_SNAPSHOT)
            try:
                self.owner.elect()
            except Exception:
                LOG.exception('Background worker startup failed')
            await asyncio.sleep(5)

    async def lifespan(self, receive, send):
        while True:
            event = await receive()
            if event['type'] == 'lifespan.startup':
                self.server.telemetry.configure_from_env()
                if self.owner:
                    self.server.start_worker()
                    self.election = asyncio.create_task(self.elect())
                await send({'type': 'lifespan.startup.complete'})
            elif event['type'] == 'lifespan.shutdown':
                if self.election:
                    self.election.cancel()
                    await asyncio.gather(self.election, return_exceptions=True)
                await asyncio.gather(*(asyncio.to_thread(lane.close) for lane in self.lanes.values()))
                if self.owner:
                    drained = not self.owner.file or await asyncio.to_thread(self.server.stop_background)
                    if drained:
                        self.owner.close()
                    else:
                        # A provider read may outlive the graceful deadline.
                        # Process exit releases this lock; releasing it here
                        # would let a follower overlap the still-active owner.
                        LOG.warning('Provider worker is draining; ownership retained until process exit')
                self.server.telemetry.stop()
                await send({'type': 'lifespan.shutdown.complete'})
                return

    async def disconnected(self, receive):
        while True:
            if (await receive())['type'] == 'http.disconnect':
                return
            # GET can still have its initial empty http.request event. Yield
            # for non-disconnect events rather than monopolizing the loop.
            await asyncio.sleep(0)

    async def execute(self, scope, receive, work):
        pending = asyncio.create_task(self.lanes[self.lane(scope)].run(work))
        disconnected = asyncio.create_task(self.disconnected(receive))
        try:
            done, _ = await asyncio.wait((pending, disconnected), return_when=asyncio.FIRST_COMPLETED)
            if disconnected in done:
                disconnected.result()
                raise ConnectionError()
            return pending.result()
        finally:
            # Cancellation while queued releases admission immediately; Lane
            # keeps an active thread's slot until its domain work finishes.
            for task in (pending, disconnected):
                if not task.done():
                    task.cancel()
            drain = asyncio.gather(pending, disconnected, return_exceptions=True)
            cancelled = False
            while not drain.done():
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:
                    cancelled = True
            drain.result()
            if cancelled:
                raise asyncio.CancelledError()

    async def response(self, scope, receive, request):
        if scope['path'] in ('/api/features', '/api/tracking', '/api/tracking/catalogue'):
            request.cache_control = 'private, no-store'
        try:
            body = await self.upload(scope, receive) if scope['method'] == 'POST' else b''
            request.rfile = io.BytesIO(body)
            # The watcher must never compete with upload() for body events.
            return await self.execute(scope, receive, request.run)
        except Busy:
            request.send_json({'error': 'Requests are busy. Please retry shortly.'}, 503, retry_after=1)
        except UploadError as exc:
            request.send_json({'error': exc.message}, exc.status)
            request.send_header('Connection', 'close')
        except (TimeoutError, OverflowError) as exc:
            request.send_json({'error': 'The upload timed out.' if isinstance(exc, TimeoutError) else 'That request is too large.'},
                              408 if isinstance(exc, TimeoutError) else 413)
            request.send_header('Connection', 'close')
        except ConnectionError:
            raise
        except Exception:
            LOG.exception('HTTP route failed: %s', scope['path'])
            request.response_headers.clear()
            request.wfile = io.BytesIO()
            request.send_json({'error': 'Please try again shortly.'}, 500)
        return request.status, request.response_headers, request.wfile.getvalue()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.lifespan(receive, send)
        if scope['type'] != 'http':
            return
        started = time.monotonic()
        request = self.handler(scope, b'')
        status, size, cache = 499, 0, None
        try:
            try:
                status, headers, body = await self.response(scope, receive, request)
            except ConnectionError:
                return
            await send({'type': 'http.response.start', 'status': status, 'headers': headers})
            await send({'type': 'http.response.body', 'body': b'' if scope['method'] == 'HEAD' else body})
            size = 0 if scope['method'] == 'HEAD' else len(body)
            cache = 'not_modified' if status == 304 else None
        except OSError:
            status = 499
            return
        except asyncio.CancelledError:
            status = 499
            raise
        finally:
            self.server.telemetry.record_request(scope['method'], scope['path'], status,
                (time.monotonic() - started) * 1000, bytes=size, cache=cache)


def create_app():
    return Application()
