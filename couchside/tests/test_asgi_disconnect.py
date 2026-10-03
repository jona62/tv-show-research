"""Real Uvicorn disconnects cancel queued work without loading the catalogue."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest import TestCase, main, skipUnless


FIXTURE = '''
import asyncio, os, sys, time, types
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from backend.asgi import Application, Lane, handler_type
from backend import telemetry

ROOT = Path(os.environ['TEST_ROOT'])
def mark(name):
    (ROOT / name).touch()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/hold':
            mark('holder-entered')
            deadline = time.monotonic() + 10
            while not (ROOT / 'release').exists() and time.monotonic() < deadline:
                time.sleep(.005)
        elif self.path == '/queued':
            mark('queued-handler-ran')
        body = b'complete'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def send_json(self, value, status=200, **kwargs):
        body = b'error'
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

stub = types.ModuleType('backend.server')
stub.LIBRARY = SimpleNamespace()
stub.Handler, stub.MOST_BODY, stub.BODY_TIMEOUT = Handler, 98304, 2
stub.LIVE_ROUTES, stub.PEOPLE_ROUTES = (), ()
stub.telemetry = telemetry
sys.modules['backend.server'] = stub

class ProbeApplication(Application):
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] != '/queued':
            return await super().__call__(scope, receive, send)
        pending = asyncio.create_task(super().__call__(scope, receive, send))
        while not pending.done():
            if self.lanes['public'].waiting == 2:
                mark('second-request-queued')
                break
            await asyncio.sleep(.001)
        return await pending

def create_app():
    app = ProbeApplication(handler=handler_type(Handler), background=False)
    app.lanes['public'].close()
    app.lanes['public'] = Lane('native-disconnect', 1, 4)
    return app
'''


@skipUnless(importlib.util.find_spec('uvicorn'), 'Requires the production Uvicorn runtime.')
class NativeDisconnectTests(TestCase):
    def wait_for(self, condition, message):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.01)
        self.fail(message)

    def test_closed_tcp_client_never_runs_its_queued_handler(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'disconnect_fixture.py').write_text(FIXTURE)
            with socket.socket() as available:
                available.bind(('127.0.0.1', 0))
                port = available.getsockname()[1]
            metrics = root / 'metrics.jsonl'
            env = {**os.environ, 'TEST_ROOT': str(root), 'COUCHSIDE_METRICS_FILE': str(metrics),
                   'COUCHSIDE_METRICS_INTERVAL': '.2', 'COUCHSIDE_LOAD_TEST_NO_OUTBOUND': '1',
                   'PYTHONPATH': os.pathsep.join((str(root), str(Path(__file__).resolve().parents[1])))}
            with (root / 'uvicorn.log').open('w+') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'disconnect_fixture:create_app',
                    '--factory', '--host', '127.0.0.1', '--port', str(port), '--no-access-log',
                    '--no-proxy-headers', '--timeout-graceful-shutdown', '3'],
                    env=env, cwd=root, stdout=log, stderr=log)
                first, second = None, None
                try:
                    def ready():
                        if process.poll() is not None:
                            log.flush()
                            self.fail('Uvicorn fixture exited: ' + (root / 'uvicorn.log').read_text())
                        try:
                            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                                return True
                        except OSError:
                            return False
                    self.wait_for(ready, 'Uvicorn did not start.')
                    first = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                    first.request('GET', '/hold')
                    self.wait_for(lambda: (root / 'holder-entered').exists(), 'The first handler did not occupy its slot.')
                    second = socket.create_connection(('127.0.0.1', port), timeout=3)
                    second.sendall(b'GET /queued HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                    self.wait_for(lambda: (root / 'second-request-queued').exists(), 'The second request was not actually queued.')
                    second.shutdown(socket.SHUT_RDWR)
                    second.close()
                    second = None

                    def cancelled():
                        if not metrics.exists():
                            return False
                        for line in metrics.read_text().splitlines():
                            try:
                                counts = json.loads(line)['counters']
                            except json.JSONDecodeError:
                                continue  # A metrics append may still be in progress.
                            if counts.get('http.GET.page.cancelled', 0) == 1:
                                return True
                        return False
                    self.wait_for(cancelled, 'The TCP disconnect was not recorded while the first handler remained active.')
                    self.assertFalse((root / 'queued-handler-ran').exists())
                    (root / 'release').touch()
                    response = first.getresponse()
                    self.assertEqual((response.status, response.read()), (200, b'complete'))
                    first.request('GET', '/probe')
                    response = first.getresponse()
                    self.assertEqual((response.status, response.read()), (200, b'complete'))
                    self.assertFalse((root / 'queued-handler-ran').exists())
                finally:
                    (root / 'release').touch()
                    if second:
                        second.close()
                    if first:
                        first.close()
                    process.terminate()
                    try:
                        process.wait(5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(3)


if __name__ == '__main__':
    main()
