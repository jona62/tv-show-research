"""Serve the app and stateless recommendations. Standard library only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import os
import threading

from engine import Engine

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / 'public'
SLOTS = threading.BoundedSemaphore(3)


def model_dir():
    """The model ships beside the app; a local checkout can share the research copy."""
    for candidate in (os.environ.get('MODEL_DIR'), HERE / 'model', HERE.parent / 'site' / 'model'):
        if candidate and (Path(candidate) / 'catalog.json.gz').exists():
            return Path(candidate)
    raise SystemExit('No model found. Run python3 app/build.py first.')


ENGINE = Engine(model_dir())


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control', 'no-store' if self.path.startswith('/api/') else 'no-cache')
        super().end_headers()

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            self.send_json({'status': 'ok'})
            return
        if path == '/api/search':
            query = parse_qs(urlsplit(self.path).query).get('q', [''])[0]
            if len(query) > 100:
                self.send_json({'error': 'Search terms must be 100 characters or fewer.'}, 400)
            else:
                self.send_json({'shows': ENGINE.search(query)})
            return
        if path.startswith('/api/'):
            self.send_json({'error': 'Not found.'}, 404)
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/api/recommend':
            self.send_json({'error': 'Not found.'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if not 0 < length <= 16384:
            self.send_json({'error': 'Send a JSON list under 16KB.'}, 413)
            return
        if self.headers.get_content_type() != 'application/json':
            self.send_json({'error': 'Send application/json.'}, 415)
            return
        body = self.rfile.read(length)
        if not SLOTS.acquire(blocking=False):
            self.send_json({'error': 'Busy right now. Try again in a moment.'}, 503)
            return
        try:
            self.send_json(ENGINE.calculate(json.loads(body)))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json({'error': 'Send a valid JSON list.'}, 400)
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            SLOTS.release()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(PUBLIC))).serve_forever()
