"""Serve the public site and stateless recommendations over a private model."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import os
import threading
from .recommender import Engine

PUBLIC = Path(__file__).resolve().parents[1] / 'public'
ENGINE = Engine()
SLOTS = threading.BoundedSemaphore(3)

class Handler(SimpleHTTPRequestHandler):
    def redirect_research(self):
        path = urlsplit(self.path)
        if path.path != '/research.html':
            return False
        location = '/pages/research.html' + ('?' + path.query if path.query else '')
        self.send_response(308)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()
        return True

    def do_HEAD(self):
        if not self.redirect_research():
            super().do_HEAD()

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control', 'no-store' if self.path.startswith('/api/') else 'no-cache')
        super().end_headers()

    def send_json(self, value, status=200):
        body=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.redirect_research():
            return
        path=urlsplit(self.path)
        if path.path=='/api/search':
            query=parse_qs(path.query).get('q',[''])[0]
            if len(query)>100:
                self.send_json({'error':'Search queries must be 100 characters or fewer.'},400)
            else:
                self.send_json({'shows':ENGINE.search(query),'catalog_count':ENGINE.n,'date':ENGINE.date})
            return
        if path.path.startswith('/api/'):
            self.send_json({'error':'Not found.'},404)
            return
        if urlsplit(self.path).path == '/healthz':
            body = b'{"status":"ok"}\n'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path!='/api/recommend':
            self.send_json({'error':'Not found.'},404)
            return
        try:
            length=int(self.headers.get('Content-Length','0'))
        except ValueError:
            length=0
        if not 0<length<=16384:
            self.send_json({'error':'Send a JSON profile under 16KB.'},413)
            return
        if self.headers.get_content_type()!='application/json':
            self.send_json({'error':'Send application/json.'},415)
            return
        if not SLOTS.acquire(blocking=False):
            self.send_json({'error':'The recommender is busy. Try again in a moment.'},503)
            return
        try:
            self.connection.settimeout(10)
            body=json.loads(self.rfile.read(length))
            self.send_json(ENGINE.calculate(body))
        except (json.JSONDecodeError,UnicodeDecodeError):
            self.send_json({'error':'Send a valid JSON profile.'},400)
        except ValueError as exc:
            self.send_json({'error':str(exc)},400)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            pass
        finally:
            SLOTS.release()

    def list_directory(self, path):
        self.send_error(404)
        return None

if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), partial(Handler, directory=str(PUBLIC)))
    server.serve_forever()
