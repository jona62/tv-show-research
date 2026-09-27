"""Serve Couchside: the page, its rows, title pages and live details. Standard library only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import os
import threading

from engine import Engine
from library import Library
from live import (Live, LiveError, Icons, KINOCHECK, ITUNES, trim_videos, trim_seasons,
                  match_rating, itunes_search)

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / 'public'
SLOTS = threading.BoundedSemaphore(3)
LIVE_SLOTS = threading.BoundedSemaphore(4)
# The app keeps its page in the path, so these are the page too and a refresh stays put.
PAGES = ('/new', '/list', '/search', '/browse')
POSTS = ('/api/home', '/api/title', '/api/shows', '/api/browse')
LIVE_ROUTES = ('/api/extra', '/api/episodes', '/api/trailer', '/api/rating')
# Posters come from TVmaze, trailer thumbnails from YouTube's image server, and a
# trailer plays in YouTube's no-cookie player only once someone presses play.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data: https://static.tvmaze.com https://i.ytimg.com; "
       "frame-src https://www.youtube-nocookie.com; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def model_dir():
    """One model copy serves every app. Deployed, MODEL_DIR names it; locally the
    repository's own model/ beside this directory is used."""
    for candidate in (os.environ.get('MODEL_DIR'), HERE / 'model', HERE.parent / 'model'):
        if candidate and (Path(candidate) / 'catalog.json.gz').exists():
            return Path(candidate)
    raise SystemExit('No model found. Set MODEL_DIR, or run from a checkout with model/ beside this app.')


ENGINE = Engine(model_dir())
LIBRARY = Library(ENGINE, HERE / 'art.bin.gz')
LIVE = Live()
# KinoCheck allows 1,000 calls a day and iTunes about 20 a minute, so both cache for days.
KINO = Live(base=KINOCHECK, ttl=3 * 86400, size=3000, calls=20, period=60)
STORE = Live(base=ITUNES, ttl=7 * 86400, size=3000, calls=15, period=60)
ICONS = Icons()


def trailers(show_id):
    """Official trailers for a show, found by the IMDb id TVmaze keeps for it."""
    imdb = LIVE.show(show_id)['imdb']
    return KINO.get(f'/shows?imdb_id={imdb}&language=en', trim_videos, missing=[]) if imdb else []


def age(show_id):
    """The US age rating and Apple TV link, for shows sold on iTunes."""
    i = ENGINE.by_id[show_id]
    show = ENGINE.shows[i]
    seasons = STORE.get(itunes_search(show['name']), trim_seasons, missing=[])
    return match_rating(seasons, show['name'], show['year'], LIBRARY.ended[i] or None)


def number(query, key, label):
    value = query.get(key, [''])[0]
    if not value.isdigit() or len(value) > 9:
        raise ValueError(f'Send {label} as a whole number.')
    return int(value)


def read_ids(payload):
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

    cache_control = None

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        # Posters come from TVmaze's image server; it needs no referrer to serve them.
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('Cache-Control', self.cache_control
                         or ('no-store' if self.path.startswith('/api/') else 'no-cache'))
        super().end_headers()

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.cache_control = None
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path == '/healthz':
            self.send_json({'status': 'ok'})
            return
        if path == '/api/search':
            q = query.get('q', [''])[0]
            if len(q) > 100:
                self.send_json({'error': 'Search terms must be 100 characters or fewer.'}, 400)
            else:
                self.send_json({'shows': LIBRARY.search(q)})
            return
        if path in LIVE_ROUTES:
            self.live(path, query)
            return
        if path == '/api/icon':
            self.icon(query.get('host', [''])[0])
            return
        if path.startswith('/api/'):
            self.send_json({'error': 'Not found.'}, 404)
            return
        if path in PAGES:
            self.path = '/'
        super().do_GET()

    def live(self, path, query):
        try:
            show_id = number(query, 'id', 'the show')
            if show_id not in ENGINE.by_id:
                raise ValueError('That show is not in this catalog.')
            season = number(query, 'season', 'the season') if path == '/api/episodes' else None
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)
            return
        if not LIVE_SLOTS.acquire(blocking=False):
            self.send_json({'error': 'Busy right now. Try again in a moment.'}, 503)
            return
        try:
            if path == '/api/extra':
                self.send_json({'details': LIVE.show(show_id)})
            elif path == '/api/episodes':
                self.send_json({'episodes': LIVE.episodes(show_id, season)})
            elif path == '/api/trailer':
                self.send_json({'videos': trailers(show_id)})
            else:
                self.send_json(age(show_id))
        except LiveError as exc:
            self.send_json({'error': str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            LIVE_SLOTS.release()

    def icon(self, host):
        if not LIVE_SLOTS.acquire(blocking=False):
            self.send_json({'error': 'Busy right now. Try again in a moment.'}, 503)
            return
        try:
            kind, body = ICONS.get(host)
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)
            return
        except LiveError as exc:
            self.send_json({'error': str(exc)}, exc.status)
            return
        finally:
            LIVE_SLOTS.release()
        self.cache_control = 'public, max-age=604800'
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def do_POST(self):
        self.cache_control = None
        route = urlsplit(self.path).path
        if route not in POSTS:
            self.send_json({'error': 'Not found.'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if not 0 < length <= 16384:
            self.send_json({'error': 'Send a JSON body under 16KB.'}, 413)
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
                self.send_json({'shows': LIBRARY.cards(read_ids(payload))})
            elif not isinstance(payload, dict):
                raise ValueError('Send your list and settings as an object.')
            elif route == '/api/home':
                self.send_json(LIBRARY.home(payload))
            elif route == '/api/browse':
                self.send_json(LIBRARY.browse(payload))
            else:
                self.send_json(LIBRARY.title(payload))
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            self.send_json({'error': 'Send valid JSON.'}, 400)
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
    port = int(os.environ.get('PORT', '8082'))
    ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(PUBLIC))).serve_forever()
