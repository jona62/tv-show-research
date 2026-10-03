"""Native two-worker HTTP and shared-demand integration, with fake provider data.

This exercises Uvicorn's real TCP transport and the production adapter/cache/store
components. A small route fixture replaces the model and providers; it is not an
application load test and makes no external requests.
"""
import gzip
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
import json, os, sys, threading, time, types
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from backend.asgi import Application, handler_type
from backend.episode_store import Episodes, Store
from backend.public_api import PublicAPI
from backend.public_data import prepare
from backend import telemetry

STORE = Store(os.environ['RATINGS_CACHE'])
def record_call(source, show_id):
    with open(os.environ['TEST_CALLS'], 'a') as out:
        out.write(json.dumps([source, show_id, os.getpid()]) + '\\n')
class Live:
    def episode_ratings(self, show_id):
        record_call('tvmaze', show_id)
        return [{'id': 101, 'season': 1, 'number': 1, 'name': 'Pilot', 'rating': 8,
                 'airdate': '2020-01-01', 'runtime': 42, 'summary': 'Complete details. ' * 100,
                 'image': {'original': 'https://images.example/pilot.jpg'}}]
class Tmdb:
    def ratings(self, show_id, live):
        record_call('tmdb', show_id)
        return {'1:1': {'rating': 9.2, 'votes': 50, 'airdate': '2020-01-01'}}
SERVICE = Episodes(STORE, Live(), Tmdb(), interval=.01)
LIBRARY = SimpleNamespace(e=SimpleNamespace(by_id={1: 0}),
    cards=lambda ids: [{'id': i, 'name': 'Fixture show', 'summary': 'Card details. ' * 100} for i in ids if i == 1])
PUBLIC = PublicAPI(LIBRARY, SERVICE, 'native-test')
class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def respond(self, response):
        selected = response.select(self.headers.get('Accept-Encoding', ''),
            self.headers.get('If-None-Match'), head=self.command == 'HEAD')
        self.send_response(selected.status)
        for key, value in selected.headers:
            self.send_header(key, value)
        self.send_header('X-Test-Worker', str(os.getpid()))
        self.send_header('X-Test-Owner', str(int(SERVICE.started)))
        self.end_headers()
        self.wfile.write(selected.body)
    def send_json(self, value, status=200, **kwargs):
        self.respond(prepare(value, status=status))
    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == '/probe':
            return self.send_json({'pid': os.getpid(), 'owner': SERVICE.started})
        if parts.path == '/calls':
            path = Path(os.environ['TEST_CALLS'])
            return self.send_json([json.loads(line) for line in path.read_text().splitlines()] if path.exists() else [])
        answer = PUBLIC.get(parts.path, parse_qs(parts.query))
        self.respond(answer or prepare({'error': 'Not found.'}, status=404))
    def do_HEAD(self):
        self.do_GET()
    def do_POST(self):
        self.send_json({'echo': json.loads(self.rfile.read()), 'pid': os.getpid()})
def stop_background(timeout=2):
    SERVICE.stop.set(); SERVICE.ready.set()
    deadline = time.monotonic() + timeout
    for worker in SERVICE.workers:
        worker.join(max(0, deadline - time.monotonic()))
    return not any(worker.is_alive() for worker in SERVICE.workers)
stub = types.ModuleType('backend.server')
stub.LIBRARY = LIBRARY
stub.Handler, stub.MOST_BODY, stub.BODY_TIMEOUT = Handler, 98304, 2
stub.LIVE_ROUTES, stub.PEOPLE_ROUTES = (), ()
stub.ADDED = SimpleNamespace(restore=lambda path: None)
stub.ADDED_SNAPSHOT = ''
stub.start_worker = lambda: None
stub.start_background = lambda: SERVICE.start()
stub.stop_background, stub.telemetry = stop_background, telemetry
sys.modules['backend.server'] = stub
def create_app():
    return Application(handler=handler_type(Handler))
'''


@skipUnless(importlib.util.find_spec('uvicorn'), 'Requires the production Uvicorn runtime.')
class NativeMultiworkerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        root = Path(cls.folder.name)
        (root / 'native_fixture.py').write_text(FIXTURE)
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            cls.port = available.getsockname()[1]
        env = {**os.environ, 'RATINGS_CACHE': str(root / 'episodes.sqlite3'),
               'TEST_CALLS': str(root / 'calls.jsonl'), 'COUCHSIDE_WORKERS': '2',
               'COUCHSIDE_LOAD_TEST_NO_OUTBOUND': '1', 'MODEL_POLL_SECONDS': '0',
               'PYTHONPATH': os.pathsep.join((str(root), str(Path(__file__).resolve().parents[1])))}
        cls.log = (root / 'uvicorn.log').open('w+')
        cls.process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'native_fixture:create_app',
            '--factory', '--host', '127.0.0.1', '--port', str(cls.port), '--workers', '2',
            '--no-access-log', '--timeout-graceful-shutdown', '3'],
            env=env, cwd=root, stdout=cls.log, stderr=cls.log)
        cls.connections = []
        cls.peers = {}
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline and len(cls.peers) < 2:
                connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=2)
                try:
                    connection.request('GET', '/probe')
                    response = connection.getresponse()
                    probe = json.loads(response.read())
                    cls.connections.append(connection)
                    cls.peers[probe['pid']] = (connection, probe['owner'])
                except (OSError, http.client.HTTPException):
                    connection.close()
                    time.sleep(.03)
            if len(cls.peers) != 2 or sum(owner for _, owner in cls.peers.values()) != 1:
                cls.log.flush()
                raise AssertionError('Two workers with one elected owner did not start: ' +
                                     (root / 'uvicorn.log').read_text())
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for connection in cls.connections:
            connection.close()
        cls.process.terminate()
        try:
            cls.process.wait(8)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(3)
        cls.log.close()
        cls.folder.cleanup()

    def request(self, connection, path, method='GET', body=None, headers=None):
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_native_representations_and_follower_refresh_across_workers(self):
        follower = next(connection for connection, owner in self.peers.values() if not owner)
        owner = next(connection for connection, elected in self.peers.values() if elected)
        path = '/api/show-cards?ids=1'
        status, headers, body = self.request(follower, path)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['shows'][0]['id'], 1)
        status, head, empty = self.request(follower, path, 'HEAD')
        self.assertEqual((status, empty), (200, b''))
        self.assertEqual(int(head['content-length']), len(body))
        status, fresh, empty = self.request(follower, path, headers={'If-None-Match': headers['etag']})
        self.assertEqual((status, empty), (304, b''))
        self.assertNotIn('content-length', fresh)
        status, packed, compressed = self.request(follower, path, headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(packed['content-encoding'], 'gzip')
        self.assertEqual(gzip.decompress(compressed), body)
        self.assertNotEqual(packed['etag'], headers['etag'])
        status, _, echo = self.request(follower, '/echo', 'POST', b'{"ids":[1]}',
                                      {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(echo)['echo'], {'ids': [1]})

        path = '/api/episode-ratings-batch?ids=1'
        status, pending_headers, pending_body = self.request(follower, path)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(pending_body)['pending'], [1])
        self.assertEqual(pending_headers['cache-control'], 'no-store')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, mature_headers, full_body = self.request(follower, path)
            full = json.loads(full_body)
            if full['shows'] and not full['shows'][0]['refreshing']:
                break
            time.sleep(.03)
        self.assertEqual(full['pending'], [])
        episode = full['shows'][0]['episodes'][0]
        self.assertEqual((episode['id'], episode['rating'], episode['rating_source']), (101, 9.2, 'TMDB'))
        self.assertTrue(episode['summary'].startswith('Complete details.'))
        self.assertIn('original', episode['image'])
        self.assertIn('public', mature_headers['cache-control'])
        _, _, same = self.request(owner, path)
        self.assertEqual(json.loads(same), full)
        _, _, calls_body = self.request(follower, '/calls')
        calls = json.loads(calls_body)
        self.assertEqual([(source, show) for source, show, _ in calls], [('tvmaze', 1), ('tmdb', 1)])
        self.assertTrue(all(pid != int(pending_headers['x-test-worker']) for _, _, pid in calls))


if __name__ == '__main__':
    main()
