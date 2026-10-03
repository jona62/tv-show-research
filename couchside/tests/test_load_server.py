"""Real HTTP telemetry and disposable load-server isolation; no provider traffic."""
from contextlib import closing, redirect_stdout
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
import hashlib
import io
import json
import os
import sqlite3
import sys
import threading
import time

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from backend import telemetry

spec = spec_from_file_location('couchside_isolated_test_server', APP / 'tools/loadtest/isolated_server.py')
isolated = module_from_spec(spec)
spec.loader.exec_module(isolated)


class RequestTelemetryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.environment = patch.dict(os.environ, {
            'RATINGS_CACHE': str(root / 'episodes.sqlite3'),
            'ACCOUNT_DB': str(root / 'accounts.sqlite3'),
            'OUTBOUND_CACHE': str(root / 'http.sqlite3'),
            'ARTWORK_CACHE': str(root / 'artwork.sqlite3'),
            'COUCHSIDE_LOAD_TEST_NO_OUTBOUND': '1',
        })
        cls.environment.start()
        # Import the actual handler; its normal entry point and background workers
        # do not run in unit tests. All possible writable stores are disposable.
        from backend import server
        cls.server = server

        class FixtureHandler(server.Handler):
            def respond(self):
                if self.headers.get('If-None-Match') == '"fixture"':
                    self.send_response(304)
                    self.end_headers()
                    return
                if self.path.startswith('/slow'):
                    time.sleep(.03)
                body = b'fixture'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('ETag', '"fixture"')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            do_GET = do_HEAD = respond

        cls.listener = ThreadingHTTPServer(('127.0.0.1', 0), partial(FixtureHandler, directory=str(root)))
        cls.worker = threading.Thread(target=cls.listener.serve_forever)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.listener.shutdown()
        cls.worker.join(2)
        cls.listener.server_close()
        telemetry.stop()
        cls.environment.stop()
        cls.folder.cleanup()

    def setUp(self):
        self.metrics = Path(self.folder.name) / (self._testMethodName + '.jsonl')
        self.recorder = telemetry.configure(self.metrics, background=False)
        self.addCleanup(telemetry.stop)
        self.connection = HTTPConnection('127.0.0.1', self.listener.server_port, timeout=3)
        self.addCleanup(self.connection.close)

    def request(self, method='GET', path='/fixture', headers=None):
        self.connection.request(method, path, headers=headers or {})
        response = self.connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())

    def wait_count(self, key, count):
        deadline = time.monotonic() + 2
        while self.recorder.snapshot()['counters'].get(key, 0) < count and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertEqual(self.recorder.snapshot()['counters'].get(key, 0), count)

    def test_keepalive_idle_is_excluded_but_handler_work_is_measured(self):
        self.assertEqual(self.request()[1], b'fixture')
        self.wait_count('http.GET.page.requests', 1)
        socket = self.connection.sock
        time.sleep(.25)
        self.assertEqual(self.request(path='/slow')[1], b'fixture')
        self.wait_count('http.GET.page.requests', 2)
        self.assertIs(self.connection.sock, socket, 'The idle interval must use the same keep-alive connection')
        latency = self.recorder.snapshot()['latency_ms']['http.GET.page']
        self.assertGreaterEqual(latency['max'], 20)
        self.assertLess(latency['max'], 200, 'Idle socket wait must not inflate request processing time')

    def test_head_and_not_modified_do_not_count_a_response_body(self):
        self.assertEqual(self.request()[1], b'fixture')
        status, body, headers = self.request('HEAD')
        self.assertEqual((status, body), (200, b''))
        self.assertEqual(headers['Content-Length'], '7')
        self.assertEqual(self.request(headers={'If-None-Match': '"fixture"'})[:2], (304, b''))
        self.wait_count('http.GET.page.requests', 2)
        counts = self.recorder.snapshot()['counters']
        self.assertEqual(counts['http.GET.page.bytes'], 7)
        self.assertEqual(counts['http.HEAD.page.bytes'], 0)
        self.assertEqual(counts['http.GET.page.cache.not_modified'], 1)
        self.assertEqual(counts['http.GET.page.status.3xx'], 1)

    def test_disabled_metrics_leave_http_behavior_and_record_nothing(self):
        telemetry.configure()
        before = self.metrics.read_bytes()
        with patch.object(telemetry, 'record_request', wraps=telemetry.record_request) as record:
            self.assertEqual(self.request()[:2], (200, b'fixture'))
            self.assertEqual(self.request('HEAD')[:2], (200, b''))
            record.assert_not_called()
        self.assertEqual(self.metrics.read_bytes(), before)

    def test_queries_are_removed_from_actual_http_metrics(self):
        self.assertEqual(self.request(path='/api/search?q=private-search&email=private@example.com')[0], 200)
        self.wait_count('http.GET.api.search.requests', 1)
        self.assertTrue(telemetry.flush())
        output = self.metrics.read_text()
        self.assertNotIn('private-search', output)
        self.assertNotIn('example.com', output)


class IsolatedServerSafetyTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.addCleanup(telemetry.stop)

    def make_cache(self, root):
        root.mkdir()
        for name in ('http.sqlite3', 'artwork.sqlite3', 'episode-ratings.sqlite3'):
            with closing(sqlite3.connect(root / name)) as connection:
                connection.execute('CREATE TABLE fixture (value INTEGER)')
                connection.execute('INSERT INTO fixture VALUES (42)')
                connection.commit()
        return root

    def test_nonempty_unowned_directory_is_rejected_without_changes(self):
        folder = self.root / 'unowned'
        folder.mkdir()
        sentinel = folder / 'keep-me.txt'
        sentinel.write_text('existing user content')
        with self.assertRaises(ValueError):
            isolated.disposable_directory(folder)
        self.assertEqual(sentinel.read_text(), 'existing user content')
        self.assertEqual(list(folder.iterdir()), [sentinel])

    def test_source_caches_open_readonly_and_target_edits_do_not_change_them(self):
        source = self.make_cache(self.root / 'source')
        target = self.root / 'copy'
        target.mkdir()
        before = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in source.iterdir()}
        real_connect = sqlite3.connect
        with patch.object(isolated.sqlite3, 'connect', wraps=real_connect) as connect:
            isolated.copy_cache(source, target)
        source_calls = [call for call in connect.call_args_list if str(call.args[0]).startswith('file:')]
        self.assertEqual(len(source_calls), 3)
        self.assertTrue(all(str(call.args[0]).endswith('?mode=ro') and call.kwargs['uri'] for call in source_calls))
        with closing(real_connect(target / 'http.sqlite3')) as writer:
            writer.execute('UPDATE fixture SET value=99')
            writer.commit()
        after = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in source.iterdir()}
        self.assertEqual(before, after)
        with closing(real_connect(source / 'http.sqlite3')) as reader:
            self.assertEqual(reader.execute('SELECT value FROM fixture').fetchone(), (42,))

    def test_fixture_credentials_are_private_and_account_store_is_disposable(self):
        target = isolated.disposable_directory(self.root / 'fixture')
        pool = isolated.prepare_accounts(target, 2)
        body = json.loads(pool.read_text())
        self.assertEqual(pool.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(body['accounts']), 2)
        self.assertEqual(len({a['owner'] for a in body['accounts']}), 2)
        self.assertEqual(len({a['token'] for a in body['accounts']}), 2)
        with closing(sqlite3.connect(target / 'accounts.sqlite3')) as reader:
            passwords = [row[0] for row in reader.execute('SELECT password_hash FROM accounts')]
            self.assertEqual(len(passwords), 2)
            self.assertTrue(all(value.startswith('$argon2id$') for value in passwords))
            self.assertTrue(all(body['accounts'][0]['password'] not in value for value in passwords))

    def test_launcher_overrides_live_store_paths_and_blocks_outbound_by_default(self):
        source = self.make_cache(self.root / 'source')
        target = self.root / 'owned'
        paths = {}
        listener = Mock(server_port=18199)
        def serving(**kwargs):
            for key in ('ACCOUNT_DB', 'OUTBOUND_CACHE', 'RATINGS_CACHE', 'ARTWORK_CACHE'):
                paths[key] = Path(os.environ[key]).resolve()
            paths['no_outbound'] = os.environ['COUCHSIDE_LOAD_TEST_NO_OUTBOUND']
        listener.serve_forever.side_effect = serving
        arguments = ['isolated_server.py', '--port', '0', '--data-dir', str(target), '--copy-from', str(source), '--accounts', '2']
        inherited = {key: str(source / name) for key, name in (
            ('ACCOUNT_DB', 'live-accounts.sqlite3'), ('OUTBOUND_CACHE', 'http.sqlite3'),
            ('RATINGS_CACHE', 'episode-ratings.sqlite3'), ('ARTWORK_CACHE', 'artwork.sqlite3'))}
        inherited['COUCHSIDE_LOAD_TEST_NO_OUTBOUND'] = '0'
        output = io.StringIO()
        with patch.dict(os.environ, inherited), patch.object(sys, 'argv', arguments), \
                patch.object(isolated, 'ThreadingHTTPServer', return_value=listener) as http, \
                patch.object(isolated.signal, 'signal'), redirect_stdout(output):
            isolated.main()
        self.assertEqual(http.call_args.args[0], ('127.0.0.1', 0))
        self.assertTrue(all(path.is_relative_to(target.resolve()) for key, path in paths.items() if key != 'no_outbound'))
        self.assertEqual(len({path for key, path in paths.items() if key != 'no_outbound'}), 4)
        self.assertEqual(paths['no_outbound'], '1')
        self.assertFalse((source / 'live-accounts.sqlite3').exists())
        ready = json.loads(output.getvalue().strip())
        self.assertFalse(ready['outbound_allowed'])
        self.assertEqual(ready['admission_api_rps'], 24)
        self.assertEqual(ready['engine_slots'], 3)
        self.assertNotIn('password', output.getvalue())
        listener.server_close.assert_called_once()


if __name__ == '__main__':
    main()
