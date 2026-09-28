"""Serve the app and stateless recommendations. Standard library only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import os
import threading

from engine import Engine
from fallback import Remote, answer
from page import fill
import follow
import starters

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / 'public'
SLOTS = threading.BoundedSemaphore(3)
# TVmaze's search, asked when the catalogue's comes up short. TVmaze allows about 20
# calls every 10 seconds from this host, which Couchside shares: this app takes 4.
TVMAZE = Remote(calls=4)
# The app keeps its tab in the path, so these are the page too and a refresh keeps the tab.
PAGES = ('/', '/index.html', '/saved', '/taste', '/shows')


def model_dir():
    """One model copy serves every app. Deployed, MODEL_DIR names it, and may be a link
    the refresher moves to each new model; locally a build of our own or the repository's
    model/ is used."""
    for candidate in (os.environ.get('MODEL_DIR'), HERE / 'model', HERE.parent / 'model'):
        if candidate and (Path(candidate) / 'catalog.json.gz').exists():
            return Path(candidate)
    raise SystemExit('No model found. Set MODEL_DIR, or run python3 app/build.py locally.')


SOURCE = model_dir()
# Read from wherever the link led at startup, so a model replaced mid-load cannot mix
# two versions; follow.py notices the move and the restart loads the new one whole.
MODEL = Path(os.path.realpath(SOURCE))
ENGINE = Engine(MODEL)
# The first-visit pool, built from the same model (starters.py).
STARTERS = starters.Starters(ENGINE)
# The built page leaves this model's count, date and first-visit data to be filled here.
TEMPLATE = PUBLIC / 'index.html'
PAGE = fill(TEMPLATE.read_text(), ENGINE).encode() if TEMPLATE.exists() else b''


def read_ids(payload):
    """The id list an imported transfer code resolves to titles."""
    if not isinstance(payload, dict):
        raise ValueError('Send a list of show ids.')
    ids = payload.get('ids', [])
    if not isinstance(ids, list) or len(ids) > 300:
        raise ValueError('Ask for up to 300 shows at a time.')
    if any(type(i) is not int for i in ids):
        raise ValueError('Show ids must be whole numbers.')
    return ids


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

    def send_page(self, head=False):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(PAGE)))
        self.end_headers()
        if not head:
            self.wfile.write(PAGE)

    def do_HEAD(self):
        if PAGE and urlsplit(self.path).path in PAGES:
            self.send_page(head=True)
        else:
            super().do_HEAD()

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
                return
            try:
                self.send_json(answer(ENGINE, query, TVMAZE))
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass    # the page moved on to a longer search while TVmaze answered
            return
        if path == '/api/starters':
            self.starters()
            return
        if path.startswith('/api/'):
            self.send_json({'error': 'Not found.'}, 404)
            return
        if PAGE and path in PAGES:
            self.send_page()
            return
        super().do_GET()

    def starters(self):
        """First-visit shows for a seed, a round, the shows picked so far and a language,
        each as a chip needs it and with why it is there."""
        try:
            seed, rnd, picked, lang, count = starters.parse(parse_qs(urlsplit(self.path).query),
                                                            self.headers.get('Accept-Language', ''))
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)
            return
        shows = ENGINE.shows
        self.send_json({'round': rnd, 'shows': [
            {**{k: shows[i][k] for k in ('id', 'name', 'year', 'channel')}, 'why': why}
            for i, why, _facet in STARTERS.choose(seed, rnd, picked, lang, count)]})

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ('/api/recommend', '/api/shows'):
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
            payload = json.loads(body)
            if route == '/api/shows':
                self.send_json({'shows': ENGINE.cards(read_ids(payload))})
            else:
                self.send_json(ENGINE.calculate(payload))
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
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
    follow.start(os.environ.get('MODEL_DIR') or SOURCE, MODEL)
    port = int(os.environ.get('PORT', '8080'))
    ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(PUBLIC))).serve_forever()
