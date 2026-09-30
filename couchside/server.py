"""Serve Couchside: the page, its rows, title pages and live details. Standard library only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import gc
import hashlib
import html
import json
import os
import re
import threading

from engine import Engine, MAX_LIST
from fallback import Remote, answer
from library import Library, DESCRIPTION, MAX_SAVED
from live import (Live, LiveError, Icons, KINOCHECK, ITUNES, trim_videos, trim_seasons,
                  match_rating, itunes_search)
from related import Related
import follow
import starters
import tmdb

HERE = Path(__file__).resolve().parent
PUBLIC = HERE / 'public'
SLOTS = threading.BoundedSemaphore(3)
# A title page asks for details, trailers and a rating at once while the hero behind it
# asks for its own, so this holds a dozen; each source still keeps its own rate limit.
LIVE_SLOTS = threading.BoundedSemaphore(12)
# The app keeps its page in the path, so these are the page too and a refresh stays put.
PAGES = ('/', '/index.html', '/new', '/list', '/search', '/browse', '/welcome')
POSTS = ('/api/home', '/api/title', '/api/shows', '/api/browse')
# Every request carries the whole list: 3,000 ratings packed as ids and rating codes
# (engine.CODES) are about 21 KB at most. A request for more of the home page carries
# the rows it shows too (up to library.LONGEST, about 130 bytes each at most) and what
# the browser has shown lately (up to 300 titles), so bodies may run past 70KB.
MOST_BODY = 98304
# A list brought in from another device is looked up in one go: every rating and every
# saved show.
MOST_IDS = MAX_LIST + MAX_SAVED
LIVE_ROUTES = ('/api/extra', '/api/episodes', '/api/episode', '/api/trailer', '/api/rating')
# Posters come from TVmaze, trailer thumbnails from YouTube's image server, backdrops
# and service logos from TMDB's, and a trailer plays in YouTube's no-cookie player only
# once someone presses play.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data: https://static.tvmaze.com https://i.ytimg.com https://image.tmdb.org; "
       "frame-src https://www.youtube-nocookie.com; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
# A worker's own fetches answer to the policy its script came with, and the service
# worker fetches the images it keeps.
WORKER_CSP = ("default-src 'self'; "
              "connect-src 'self' https://static.tvmaze.com https://i.ytimg.com https://image.tmdb.org")
# A search answers from the catalogue, and from TVmaze's search, which fallback.py keeps
# for an hour, so browsers keep an answer five minutes and then ask with its ETag.
SEARCH_CACHE = 'public, max-age=300'
SHARE = re.compile(r'<!--share.*?<!--/share-->', re.S)
HOST = re.compile(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::\d{1,5})?', re.I)
HOLES = re.compile(r'__(BOOTSTRAP|CATALOG_COUNT|DATASET_DATE)__')
CREDIT = re.compile(r'[ \t]*<!--tmdb\b.*?-->\n?(.*?)[ \t]*<!--/tmdb-->\n?', re.S)


def model_dir():
    """One model copy serves every app. Deployed, MODEL_DIR names it, and may be a link
    the refresher moves to each new model; locally the repository's own model/ beside
    this directory is used."""
    for candidate in (os.environ.get('MODEL_DIR'), HERE / 'model', HERE.parent / 'model'):
        if candidate and (Path(candidate) / 'catalog.json.gz').exists():
            return Path(candidate)
    raise SystemExit('No model found. Set MODEL_DIR, or run from a checkout with model/ beside this app.')


def art_file(model):
    """A model the refresher built carries posters to match its catalog; the frozen one
    has none, and uses the copy kept here."""
    return model / 'art.bin.gz' if (model / 'art.bin.gz').is_file() else HERE / 'art.bin.gz'


def build_of(public):
    """The build the served files are, as build.py stamped it into the service worker."""
    try:
        found = re.search(r"^const VERSION = '([0-9a-f]+)';", (public / 'sw.js').read_text(), re.M)
    except OSError:
        return ''
    return found[1] if found else ''


def etag(body):
    """A strong validator: the same bytes, the same tag."""
    return '"' + hashlib.sha256(body).hexdigest()[:20] + '"'


def held(header, tag):
    """Whether If-None-Match names this tag, compared weakly as RFC 9110 has it for GET."""
    names = {name.strip().removeprefix('W/') for name in (header or '').split(',')}
    return '*' in names or tag in names


def fill(template, engine, library, credit):
    """The page with this model's count, date and first-visit posters, filled once at
    startup. TMDB's credit stays only when there is TMDB data to credit."""
    boot = {'date': engine.date, 'count': engine.n, 'starters': library.starters, 'genres': library.genres}
    # Every < in the data is escaped, so no show's name can close or confuse the script block.
    payload = json.dumps(boot, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    values = {'BOOTSTRAP': payload, 'CATALOG_COUNT': f'{engine.n:,}', 'DATASET_DATE': html.escape(engine.date)}
    page = HOLES.sub(lambda m: values[m[1]], template)
    return CREDIT.sub(lambda m: m[1] if credit else '', page)


SOURCE = model_dir()
# Read from wherever the link led at startup, so a model replaced mid-load cannot mix
# two versions; follow.py notices the move and the restart loads the new one whole.
MODEL = Path(os.path.realpath(SOURCE))
ENGINE = Engine(MODEL)
LIBRARY = Library(ENGINE, art_file(MODEL))
# A search's row of shows like it is the title page's own More like this for a show it
# names, and a search for a film finds shows like it through the model's film index.
RELATED = Related(LIBRARY, MODEL / 'films.json.gz')
TMDB = tmdb.load(MODEL / 'tmdb.json.gz', ENGINE.by_id)
# TVmaze allows about 20 calls every 10 seconds from this host, shared with Next Watch:
# 12 for title pages here, 4 for this app's search and 4 for Next Watch's.
LIVE = Live(calls=12)
TVMAZE = Remote(calls=4)
TEMPLATE = PUBLIC / 'index.html'
PAGE = fill(TEMPLATE.read_text(), ENGINE, LIBRARY, bool(TMDB)) if TEMPLATE.exists() else ''
# Every page says which build it is, read with the page at startup, so the service worker
# keeps a page only beside files of the same build.
BUILD = build_of(PUBLIC)
LOST = (PUBLIC / '404.html').read_bytes() if (PUBLIC / '404.html').exists() else b''
# KinoCheck allows 1,000 calls a day and iTunes about 20 a minute, so both cache for days.
KINO = Live(base=KINOCHECK, ttl=3 * 86400, size=3000, calls=20, period=60)
STORE = Live(base=ITUNES, ttl=7 * 86400, size=3000, calls=15, period=60)
ICONS = Icons()
# The model's objects live as long as the server, so the garbage collector leaves them
# alone from here: a full collection walking them cost a long list's request up to 150 ms.
gc.collect()
gc.freeze()


def trailers(show_id):
    """A show's trailers from TMDB when it has any, else KinoCheck's official ones, found
    by the IMDb id TVmaze keeps for it."""
    known = TMDB.get(show_id)
    if known and known['videos']:
        return known['videos']
    imdb = LIVE.show(show_id)['imdb']
    return KINO.get(f'/shows?imdb_id={imdb}&language=en', trim_videos, missing=[]) if imdb else []


def episode(episode_id):
    """One episode in full, for a show in this catalog. TVmaze is asked by the episode's
    own id, so which show it belongs to is known only from the answer."""
    found = LIVE.episode(episode_id)
    if found['show'] not in ENGINE.by_id:
        raise LiveError('That episode is not in this catalog.', 404)
    return found


def age(show_id):
    """The US age rating, TMDB's first, and the Apple TV link for shows sold on iTunes.
    iTunes is asked only for what TMDB lacks: a rating, or anywhere to watch, since the
    page shows Apple TV only when TMDB lists no services."""
    known = TMDB.get(show_id) or {}
    rating = known.get('rating')
    if rating and known.get('providers'):
        return {'rating': rating, 'apple': None}
    i = ENGINE.by_id[show_id]
    show = ENGINE.shows[i]
    try:
        seasons = STORE.get(itunes_search(show['name']), trim_seasons, missing=[])
    except LiveError:
        if rating:
            return {'rating': rating, 'apple': None}
        raise
    found = match_rating(seasons, show['name'], show['year'], LIBRARY.ended[i] or None)
    return {'rating': rating or found['rating'], 'apple': found['apple']}


def search(q):
    """A search's answer: its title matches, best first, the shows TVmaze knows that the
    catalogue does not yet (fallback.py), and a row of shows like it (related.py), or
    None for the row: {'title': 'More like Game of Thrones', 'kind', 'shows': cards}."""
    found = answer(ENGINE, q, TVMAZE, LIBRARY.card)
    row = RELATED.of(q, found['shows'])
    found['related'] = {**row, 'shows': [LIBRARY.card(j) for j in row['shows']]} if row else None
    return found


def origin(headers):
    """This site's own address, for share tags, which need absolute URLs."""
    host = headers.get('Host', '')
    if not HOST.fullmatch(host):
        return ''
    # A public host is always served over https. The proxy in front of this server may
    # report its own inner hop as http, so only a local run is taken at its word.
    local = host.split(':')[0] in ('localhost', '127.0.0.1')
    scheme = 'https' if not local or headers.get('X-Forwarded-Proto') == 'https' else 'http'
    return f'{scheme}://{host}'


def share_tags(site, show_id):
    """What a link preview shows: the app itself, or the title a link opens."""
    i = ENGINE.by_id.get(show_id) if show_id is not None else None
    if i is None:
        return 'Couchside', [
            ('og:title', 'Couchside'), ('og:description', DESCRIPTION),
            ('og:image', f'{site}/og.jpg' if site else '/og.jpg'), ('og:image:width', '1200'), ('og:image:height', '630'),
            ('og:image:alt', 'The Couchside wordmark beside a wall of TV show posters'),
            ('og:url', f'{site}/' if site else ''), ('twitter:card', 'summary_large_image')]
    show = ENGINE.shows[i]
    summary = show['summary'] or DESCRIPTION
    if len(summary) > 200:
        summary = summary[:200].rsplit(' ', 1)[0] + '…'
    year = f" ({show['year']})" if show['year'] else ''
    return f"{show['name']} · Couchside", [
        ('og:title', f"{show['name']}{year} on Couchside"), ('og:description', summary),
        ('og:image', LIBRARY.poster(i, 'original_untouched') or (f'{site}/og.jpg' if site else '')),
        ('og:image:alt', f"Poster for {show['name']}"),
        ('og:url', f'{site}/?show={show_id}' if site else ''), ('twitter:card', 'summary')]


def render_page(headers, query):
    raw = query.get('show', [''])[0]
    title, tags = share_tags(origin(headers), int(raw) if raw.isdigit() and len(raw) < 10 else None)
    lines = ['<meta property="og:site_name" content="Couchside">', '<meta property="og:type" content="website">']
    for key, value in tags:
        if value:
            kind = 'name' if key.startswith('twitter:') else 'property'
            lines.append(f'<meta {kind}="{key}" content="{html.escape(value, quote=True)}">')
    page = SHARE.sub(lambda _m: '<!--share-->\n' + '\n'.join(lines) + '\n<!--/share-->', PAGE, count=1)
    return page.replace('<title>Couchside</title>', f'<title>{html.escape(title)}</title>', 1).encode()


def number(query, key, label):
    value = query.get(key, [''])[0]
    if not value.isdigit() or len(value) > 9:
        raise ValueError(f'Send {label} as a whole number.')
    return int(value)


def read_ids(payload):
    if not isinstance(payload, dict):
        raise ValueError('Send a list of show ids.')
    ids = payload.get('ids', [])
    if not isinstance(ids, list) or len(ids) > MOST_IDS:
        raise ValueError(f'Ask for up to {MOST_IDS:,} shows at a time.')
    if any(type(i) is not int for i in ids):
        raise ValueError('Show ids must be whole numbers.')
    return ids


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    cache_control = None
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.webmanifest': 'application/manifest+json',
                      '.ico': 'image/x-icon', '.js': 'text/javascript', '.svg': 'image/svg+xml',
                      '.txt': 'text/plain; charset=utf-8', '.html': 'text/html; charset=utf-8'}

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        # Posters come from TVmaze's image server; it needs no referrer to serve them.
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', WORKER_CSP if urlsplit(self.path).path == '/sw.js' else CSP)
        self.send_header('Cache-Control', self.cache_control
                         or ('no-store' if self.path.startswith('/api/') else 'no-cache'))
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        """A path that leads nowhere gets the app's own page rather than a bare error."""
        if code != 404 or not LOST or urlsplit(self.path).path.startswith('/api/'):
            super().send_error(code, message, explain)
            return
        self.cache_control = None
        self.send_response(404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(LOST)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(LOST)

    def send_body(self, body, kind, status=200, validate=False, head=False, extra=()):
        """The body, or a bodiless 304 when validate is set and the browser already holds
        these very bytes (If-None-Match)."""
        tag = etag(body) if validate and status == 200 else None
        fresh = tag and held(self.headers.get('If-None-Match'), tag)
        self.send_response(304 if fresh else status)
        if not fresh:
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
        if tag:
            self.send_header('ETag', tag)
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        if not fresh and not head:
            self.wfile.write(body)

    def send_page(self, query, head=False):
        self.send_body(render_page(self.headers, query), 'text/html; charset=utf-8', validate=True, head=head,
                       extra=(('X-Build', BUILD),) if BUILD else ())

    def do_HEAD(self):
        self.cache_control = None
        parts = urlsplit(self.path)
        if parts.path in PAGES:
            self.send_page(parse_qs(parts.query), head=True)
        else:
            super().do_HEAD()

    def send_json(self, value, status=200, validate=False):
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        self.send_body(body, 'application/json; charset=utf-8', status, validate)

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
                return
            try:
                found = search(q)
                self.cache_control = SEARCH_CACHE
                self.send_json(found, validate=True)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass    # the page moved on to a longer search while TVmaze answered
            return
        if path in LIVE_ROUTES:
            self.live(path, query)
            return
        if path == '/api/icon':
            self.icon(query.get('host', [''])[0])
            return
        if path == '/api/starters':
            try:
                seed, rnd, picked, lang, count = starters.parse(query, self.headers.get('Accept-Language', ''))
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
                return
            self.send_json({'round': rnd, 'shows': LIBRARY.starters_for(seed, rnd, picked, lang, count)})
            return
        if path.startswith('/api/'):
            self.send_json({'error': 'Not found.'}, 404)
            return
        if path in PAGES:
            self.send_page(query)
            return
        super().do_GET()

    def live(self, path, query):
        try:
            # An episode is asked for by its own TVmaze id; everything else by its show's.
            if path == '/api/episode':
                episode_id = number(query, 'id', 'the episode')
            else:
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
            elif path == '/api/episode':
                self.send_json({'episode': episode(episode_id)})
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
        if not 0 < length <= MOST_BODY:
            self.send_json({'error': f'Send a JSON body under {MOST_BODY // 1024}KB.'}, 413)
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
                # The first eight rows and the hero, or, for a request that says which rows
                # it already shows, the next ones (library.Library.home).
                home = LIBRARY.home(payload)
                if home.get('hero'):
                    home['hero']['tmdb'] = TMDB.get(home['hero']['id'])
                self.send_json(home)
            elif route == '/api/browse':
                self.send_json(LIBRARY.browse(payload))
            else:
                # TMDB's rating, trailers, backdrop and where to watch come with the title,
                # so the page asks the live sources only for what TMDB lacks.
                title = LIBRARY.title(payload)
                title['tmdb'] = TMDB.get(title['show']['id'])
                self.send_json(title)
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
    follow.start(os.environ.get('MODEL_DIR') or SOURCE, MODEL)
    # What searching by meaning reads is built behind the first requests, not before them.
    threading.Thread(target=RELATED.warm, daemon=True).start()
    port = int(os.environ.get('PORT', '8082'))
    ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(PUBLIC))).serve_forever()
