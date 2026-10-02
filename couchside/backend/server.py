"""Serve Couchside with the standard HTTP server and a shared urllib3 outbound client."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as Unfinished
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import gc
import gzip
import hashlib
import html
import io
import json
import os
import re
import threading
import time

from .added import Added
from .recommendation.engine import Engine, MAX_LIST
from .episode_store import Store as EpisodeStore, Episodes, Tmdb as EpisodeTmdb
from .recommendation.discovery import Discovery, read_filters, fits, sort_key
from .fallback import Remote, answer
from .recommendation.library import Library, DESCRIPTION, MAX_SAVED
from .recommendation.insights import Insights
from .live import (Live, LiveError, Icons, KINOCHECK, ITUNES, trim_videos, trim_seasons,
                  match_rating, itunes_search)
from .people import PERSON, GUESTS, WIKIDATA, WIKIPEDIA, Biographies, trim_person, trim_guests, credits, public
from .recommendation.related import Related
from . import follow
from .recommendation import starters
from . import tmdb
from .request_limits import Requests
from .accounts import AccountService
from .account_http import AccountRoutes

HERE = Path(__file__).resolve().parents[1]
PUBLIC = HERE / 'public'
SLOTS = threading.BoundedSemaphore(3)
BODY_SLOTS = threading.BoundedSemaphore(16)
BODY_TIMEOUT = 10
# A title page asks for details, trailers and a rating at once while the hero behind it
# asks for its own, so this holds a dozen; each source still keeps its own rate limit.
LIVE_SLOTS = threading.BoundedSemaphore(12)
REQUESTS = Requests()
_accounts = None
_accounts_lock = threading.Lock()


def accounts():
    """Account data lives outside release checkouts; opening is lazy for builds/tests."""
    global _accounts
    with _accounts_lock:
        if _accounts is None:
            path = os.environ.get('ACCOUNT_DB') or HERE.parent / 'data/accounts/couchside.sqlite3'
            _accounts = AccountService(path)
    return _accounts


ACCOUNT_ROUTES = AccountRoutes(accounts, https_only=os.environ.get('ACCOUNT_HTTPS_ONLY') == '1',
                               origin=os.environ.get('ACCOUNT_ORIGIN'))
# The app keeps its page in the path, so these are the page too and a refresh stays put.
PAGES = ('/', '/index.html', '/new', '/list', '/search', '/browse', '/welcome', '/compare')
POSTS = ('/api/home', '/api/title', '/api/shows', '/api/browse', '/api/taste')
# Every request carries the whole list: 3,000 ratings packed as ids and rating codes
# (engine.CODES) are about 21 KB at most. A request for more of the home page carries
# the rows it shows too (up to library.LONGEST, about 130 bytes each at most) and what
# the browser has shown lately (up to 300 titles), so bodies may run past 70KB.
MOST_BODY = 98304
# A list brought in from another device is looked up in one go: every rating and every
# saved show.
MOST_IDS = MAX_LIST + MAX_SAVED
LIVE_ROUTES = ('/api/extra', '/api/episodes', '/api/episode', '/api/episode-ratings', '/api/trailer', '/api/rating')
# Someone in a cast, by TVmaze person id: who they are and what they are in, and apart from
# that, since Wikidata can take seconds to answer, their biography.
PEOPLE_ROUTES = ('/api/person', '/api/biography')
# Posters come from TVmaze, trailer thumbnails from YouTube's image server, backdrops
# and service logos from TMDB's, and a trailer plays in YouTube's no-cookie player only
# once someone presses play.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data: https://static.tvmaze.com https://i.ytimg.com https://image.tmdb.org; "
       "frame-src https://www.youtube-nocookie.com; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
# A worker's own fetches answer to the policy its script came with, and the service
# worker fetches the images it keeps.
WORKER_CSP = ("default-src 'self'; "
              "connect-src 'self' https://static.tvmaze.com https://i.ytimg.com https://image.tmdb.org")
# A search answers from the catalogue, and from TVmaze's search, which fallback.py keeps
# for an hour, so browsers keep an answer five minutes and then ask with its ETag.
SEARCH_CACHE = 'public, max-age=300'
# A file asked for by the hash build.py gave it (?v=) is those bytes for as long as anything
# asks for it, so it is kept a year and never checked; a new build asks for new addresses.
BUILT_CACHE = 'public, max-age=31536000, immutable'
# Icons and pictures asked for by their plain names change only when brand/make.py runs, so
# they are kept a day; code and pages without a hash are checked every time, by their tag.
IMAGE_CACHE = 'public, max-age=86400'
IMAGE_KINDS = ('image/png', 'image/jpeg', 'image/x-icon', 'image/svg+xml')
# Text shrinks to a quarter or less gzipped: the page, its scripts and styles, JSON, SVG and
# the manifest. A body under SMALLEST goes as it is, since gzip's framing would eat most of
# what it saves, and so does one that gzip barely shrinks.
COMPRESSIBLE = re.compile(r'text/|application/(?:json|javascript|manifest\+json)|image/(?:svg\+xml|x-icon)')
SMALLEST = 1024
# Answers are made for each request and gzipped at zlib's usual level, about a quarter of a
# millisecond for a home page; files are gzipped once, at the most.
LEVEL, FILE_LEVEL = 6, 9
SHARE = re.compile(r'<!--share.*?<!--/share-->', re.S)
HOST = re.compile(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::\d{1,5})?', re.I)
HOLES = re.compile(r'__(BOOTSTRAP|CATALOG_COUNT|DATASET_DATE)__')
CREDIT = re.compile(r'[ \t]*<!--tmdb\b.*?-->\n?(.*?)[ \t]*<!--/tmdb-->\n?', re.S)


def model_dir():
    """One model copy serves every app. Deployed, MODEL_DIR names it, and may be a link
    the refresher moves to each new model; locally the repository's data/model/ is used."""
    for candidate in (os.environ.get('MODEL_DIR'), HERE.parent / 'data/model'):
        if candidate and (Path(candidate) / 'catalog.json.gz').exists():
            return Path(candidate)
    raise SystemExit('No model found. Set MODEL_DIR, or use a checkout with data/model/.')


def art_file(model):
    """A model the refresher built carries posters to match its catalog; the frozen one
    has none, and uses the copy kept here."""
    return model / 'art.bin.gz' if (model / 'art.bin.gz').is_file() else HERE / 'assets/model/art.bin.gz'


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


def zipped_tag(tag):
    """The tag of a body's gzipped bytes: other bytes, so another tag (RFC 9110 8.8.3)."""
    return tag[:-1] + '-gz"'


def accepts_gzip(header):
    """Whether Accept-Encoding lets gzip through: named, or covered by *, and not at q=0."""
    weights = {}
    for part in (header or '').split(','):
        coding, *params = part.split(';')
        weight = 1.0
        for param in params:
            key, _, value = param.partition('=')
            if key.strip().lower() == 'q':
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        weights[coding.strip().lower()] = weight
    return weights.get('gzip', weights.get('x-gzip', weights.get('*', 0.0))) > 0


def worth_packing(kind, body):
    return len(body) >= SMALLEST and bool(COMPRESSIBLE.match(kind))


def packed(body, level=LEVEL):
    """body gzipped with no timestamp, so the same bytes always pack the same, or None when
    gzip saves under a tenth of them."""
    out = gzip.compress(body, level, mtime=0)
    return out if len(out) < 0.9 * len(body) else None


class Built:
    """The public bundle's files as they are sent: each file's bytes, their gzip, its tag and
    its hash as build.py writes it (?v=), worked out once and again only when the file
    changes on disk, as a build does under a server running locally."""

    def __init__(self):
        self.files, self.lock = {}, threading.Lock()

    def get(self, path, kind):
        """(body, gzipped or None, tag, hash) for the file at path."""
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
        kept = self.files.get(path)
        if kept and kept[0] == stamp:
            return kept[1]
        body = Path(path).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        found = (body, packed(body, FILE_LEVEL) if worth_packing(kind, body) else None, f'"{digest[:20]}"', digest[:16])
        with self.lock:
            self.files[path] = (stamp, found)
        return found


class Pages:
    """The page gzipped, by its tag: it differs only by the title a link opens and the host,
    so a few hundred cover nearly every request, and the rest are packed again."""

    def __init__(self, most=256):
        self.most, self.kept = most, {}

    def get(self, tag, body):
        found = self.kept.get(tag)
        if found is None:
            if len(self.kept) >= self.most:
                self.kept.clear()
            found = self.kept[tag] = packed(body)
        return found


def fill(template, engine, library, credit):
    """The page with this model's count, date, newest show and first-visit posters, filled
    once at startup. TMDB's credit stays only when there is TMDB data to credit."""
    boot = {'date': engine.date, 'count': engine.n, 'newest': max(engine.by_id), 'starters': library.starters,
            'genres': library.genres, 'languages': sorted(v for v in getattr(engine, 'metadata', {}).get('language', []) if v)}
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
# TVmaze numbers shows as it adds them, so a show added since this model was built has an
# id past the newest the catalogue holds, and its title page comes from TVmaze alone
# (newer_title). An id more than NEWER_REACH past it, some five months of TVmaze's
# additions at about 31 a day, is never asked about.
NEWEST = max(ENGINE.by_id)
NEWER_REACH = 5000
LIBRARY = Library(ENGINE, art_file(MODEL))
INSIGHTS = Insights(ENGINE)
# A search's row of shows like it is the title page's own More like this for a show it
# names, and a search for a film finds shows like it through the model's film index.
RELATED = Related(LIBRARY, MODEL / 'films.json.gz')
TMDB = tmdb.load(MODEL / 'tmdb.json.gz', ENGINE.by_id)
# TVmaze allows about 20 calls every 10 seconds from this host, shared with Next Watch:
# 12 for title pages here (a show newer than the catalogue's whole page among them, one
# call like any show's details, and the shows TVmaze added since, kept for search), 4 for
# this app's search and 4 for Next Watch's.
EPISODE_STORE = EpisodeStore(os.environ.get('RATINGS_CACHE') or HERE.parent / 'data/cache/episode-ratings.sqlite3')
LIVE = Live(calls=12, store=EPISODE_STORE)
RATINGS = Episodes(EPISODE_STORE, LIVE,
                   ended=(s['id'] for s in ENGINE.shows if s.get('status') == 'Ended'))
RATING_KEY = os.environ.get('TMDB_API_KEY', '')
if RATING_KEY:
    RATINGS.tmdb = EpisodeTmdb(RATING_KEY, tmdb.ids(MODEL / 'tmdb.json.gz'))
DISCOVERY = Discovery(LIBRARY, RATINGS.store, MODEL / 'tmdb.json.gz')
LIBRARY.discovery = DISCOVERY
TVMAZE = Remote(calls=4)
# The shows TVmaze lists past the catalogue's newest, read about hourly and each asked for
# once, so search finds them on every query, a show named like an older one too (added.py).
ADDED = Added(LIVE, NEWEST, NEWER_REACH)
TEMPLATE = PUBLIC / 'index.html'
PAGE = fill(TEMPLATE.read_text(), ENGINE, LIBRARY, bool(TMDB)) if TEMPLATE.exists() else ''
# Every page says which build it is, read with the page at startup, so the service worker
# keeps a page only beside files of the same build.
BUILD = build_of(PUBLIC)
LOST = (PUBLIC / 'pages/404.html').read_bytes() if (PUBLIC / 'pages/404.html').exists() else b''
FILES = Built()
PACKED_PAGES = Pages()
# KinoCheck allows 1,000 calls a day and iTunes about 20 a minute, so both cache for days.
KINO = Live(base=KINOCHECK, ttl=3 * 86400, size=3000, calls=20, period=60)
STORE = Live(base=ITUNES, ttl=7 * 86400, size=3000, calls=15, period=60)
# Wikidata's query service and Wikipedia ask for a steady trickle, and what they say of a
# person seldom changes, so their answers are kept a day.
BIOGRAPHIES = Biographies(Live(base=WIKIDATA, ttl=86400, size=3000, calls=30, period=60),
                          Live(base=WIKIPEDIA, ttl=86400, size=3000, calls=60, period=60))
# A person's guest parts are asked for while TVmaze answers for the person, on these.
AHEAD = ThreadPoolExecutor(max_workers=8, thread_name_prefix='people')
ICONS = Icons()
# The model's objects live as long as the server, so the garbage collector leaves them
# alone from here: a full collection walking them cost a long list's request up to 150 ms.
gc.collect()
gc.freeze()


def newer(show_id):
    """Whether show_id may be a show TVmaze added since the catalogue was built (NEWEST)."""
    return type(show_id) is int and NEWEST < show_id <= NEWEST + NEWER_REACH


def details(found):
    """A show's live details as a page reads them: what TVmaze says of the show itself
    stays here, for a title newer than the catalogue (newer_title)."""
    return {key: value for key, value in found.items() if key != 'about'}


def newer_title(show_id):
    """The title page of a show newer than the catalogue, from the TVmaze answer its live
    details come from, sent with them, so the page asks TVmaze for nothing more but its
    seasons' episodes. It holds the show as TVmaze has it and nothing only the catalogue
    gives: no match, no reason it surfaced and no shows like it, which need its plot,
    themes and Wikidata facts in the model's own terms. TMDB's data covers catalogue shows
    alone, so its trailers, rating and where to watch come from the live sources, as they
    do for any show TMDB lacks. The nightly build brings the rest."""
    found = LIVE.show(show_id)
    if not found['about']:
        raise LiveError('TVmaze has no details for this show.', 404)
    return {'show': {**found['about'], 'because': None, 'newer': True}, 'details': details(found),
            'more': [], 'fans': [], 'tmdb': None}


def trailers(show_id):
    """A show's trailers from TMDB when it has any, else KinoCheck's official ones, found
    by the IMDb id TVmaze keeps for it."""
    known = TMDB.get(show_id)
    if known and known['videos']:
        return known['videos']
    imdb = LIVE.show(show_id)['imdb']
    return KINO.get(f'/shows?imdb_id={imdb}&language=en', trim_videos, missing=[]) if imdb else []


def episode(episode_id):
    """One episode in full, for a show in this catalog or newer than it. TVmaze is asked by
    the episode's own id, so which show it belongs to is known only from the answer."""
    found = LIVE.episode(episode_id)
    if found['show'] not in ENGINE.by_id and not newer(found['show']):
        raise LiveError('That episode is not in this catalog.', 404)
    cached = RATINGS.saved(found['show'])
    picked = next((e for e in cached['episodes'] if e['id'] == episode_id), None) if cached else None
    if picked:
        found = {**found, **{key: picked[key] for key in ('rating', 'rating_source', 'rating_votes')}}
    return found


def named(show_id):
    """A show's name, its first year and the year it ended: the catalogue's, or TVmaze's
    for a show newer than it."""
    i = ENGINE.by_id.get(show_id)
    if i is None:
        about = LIVE.show(show_id)['about'] or {}
        return about.get('name') or '', about.get('year'), about.get('ended')
    show = ENGINE.shows[i]
    return show['name'], show['year'], LIBRARY.ended[i] or None


def age(show_id):
    """The US age rating, TMDB's first, and the Apple TV link for shows sold on iTunes.
    iTunes is asked only for what TMDB lacks: a rating, or anywhere to watch, since the
    page shows Apple TV only when TMDB lists no services."""
    known = TMDB.get(show_id) or {}
    rating = known.get('rating')
    if rating and known.get('providers'):
        return {'rating': rating, 'apple': None}
    name, start, end = named(show_id)
    try:
        seasons = STORE.get(itunes_search(name), trim_seasons, missing=[])
    except LiveError:
        if rating:
            return {'rating': rating, 'apple': None}
        raise
    found = match_rating(seasons, name, start, end)
    return {'rating': rating or found['rating'], 'apple': found['apple']}


def someone(person_id):
    """A TVmaze person as trimmed, with the shows they are a regular in and helped make. A
    person TVmaze does not have is kept as such, like a show with no trailer."""
    found = LIVE.get(PERSON.format(id=person_id), trim_person, missing=False)
    if not found:
        raise LiveError('TVmaze has no details for this person.', 404)
    return found


def person(person_id):
    """A person's page: who they are and what they are in, each show the catalogue holds as
    its card (people.credits). Their guest parts are asked for alongside, and their
    biography is begun as soon as TVmaze has answered, for the page to ask for next. Guest
    parts that cannot be had leave the rest."""
    guests = AHEAD.submit(LIVE.get, GUESTS.format(id=person_id), trim_guests, [])
    who = someone(person_id)
    BIOGRAPHIES.start(who)
    try:
        appeared = guests.result(timeout=20)
    except (LiveError, Unfinished):
        appeared = []
    return {'person': public(who), **credits(LIBRARY, who, appeared)}


def biography(person_id):
    """What Wikidata and Wikipedia say of a person, or None (people.Biographies)."""
    return BIOGRAPHIES.get(someone(person_id))


def decorate(value, matrix=False):
    """Deliver cached matrices beside cards, and warm the next visible cards early."""
    if not matrix:
        return value
    ids = []
    def visit(item):
        if isinstance(item, dict):
            if 'poster' in item and item.get('id') in ENGINE.by_id and item['id'] not in ids:
                ids.append(item['id'])
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            # The first six cards of every row come before cards reached horizontally.
            for child in item[:6]:
                visit(child)
    visit(value)
    value['matrices'] = RATINGS.matrices(ids[:48])
    return value


def search(q, filters=None):
    """A search's answer: its title matches, best first, the shows TVmaze knows that the
    catalogue does not yet (fallback.py), the ones it added since that match first among
    them (added.py), and a row of shows like it (related.py), or None for the row:
    {'title': 'More like Game of Thrones', 'kind', 'shows': cards}."""
    rules = read_filters(filters)
    if rules:
        hits = ENGINE.titles.find(q, limit=ENGINE.n).hits if q.strip() else [(i, None) for i in DISCOVERY.view(rules).shelf]
        matches = [(i, aka) for i, aka in hits if fits(DISCOVERY.record(i), rules)]
        order = DISCOVERY.order([i for i, _aka in matches], rules)
        aliases = dict(matches)
        found = {'shows': [{**LIBRARY.card(i), 'aka': aliases[i]} for i in order[:60]], 'missing': [], 'missing_first': False}
    else:
        found = ADDED.join(answer(ENGINE, q, TVMAZE, LIBRARY.card), q)
    row = RELATED.of(q, found['shows'])
    found['related'] = {**row, 'shows': [LIBRARY.card(j) for j in row['shows'] if fits(DISCOVERY.record(j), rules)]} if row else None
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
            ('og:image', f'{site}/assets/images/og.jpg' if site else '/assets/images/og.jpg'), ('og:image:width', '1200'), ('og:image:height', '630'),
            ('og:image:alt', 'The Couchside wordmark beside a wall of TV show posters'),
            ('og:url', f'{site}/' if site else ''), ('twitter:card', 'summary_large_image')]
    show = ENGINE.shows[i]
    summary = show['summary'] or DESCRIPTION
    if len(summary) > 200:
        summary = summary[:200].rsplit(' ', 1)[0] + '…'
    year = f" ({show['year']})" if show['year'] else ''
    return f"{show['name']} · Couchside", [
        ('og:title', f"{show['name']}{year} on Couchside"), ('og:description', summary),
        ('og:image', LIBRARY.poster(i, 'original_untouched') or (f'{site}/assets/images/og.jpg' if site else '')),
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


class BodyError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    cache_control = None
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.webmanifest': 'application/manifest+json',
                      '.ico': 'image/x-icon', '.js': 'text/javascript', '.svg': 'image/svg+xml',
                      '.txt': 'text/plain; charset=utf-8', '.html': 'text/html; charset=utf-8'}

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        if ACCOUNT_ROUTES.https_only:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
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

    def answer(self, body, kind, status=200, validate=False, extra=(), tag=None, pack=packed):
        """Sends the status and headers for body and returns the bytes to follow them: the
        body, gzipped for a browser that takes gzip when it is text worth packing, or None
        for a bodiless 304 when validate is set and the browser already holds these very
        bytes (If-None-Match). Gzipped bytes carry a tag of their own, and whatever could be
        packed says it varies by Accept-Encoding, so no cache hands one to a browser that
        asked for the other. tag is the body's own when it is known already, and pack makes
        (or finds) the gzipped bytes, or None when they are not worth sending."""
        tag = (tag or etag(body)) if validate and status == 200 else None
        varies = worth_packing(kind, body)
        sent = pack(body) if varies and accepts_gzip(self.headers.get('Accept-Encoding')) else None
        if sent is not None and tag:
            tag = zipped_tag(tag)
        fresh = tag and held(self.headers.get('If-None-Match'), tag)
        self.send_response(304 if fresh else status)
        if not fresh:
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body if sent is None else sent)))
            if sent is not None:
                self.send_header('Content-Encoding', 'gzip')
        if varies:
            self.send_header('Vary', 'Accept-Encoding')
        if tag:
            self.send_header('ETag', tag)
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        return None if fresh else body if sent is None else sent

    def send_body(self, body, kind, status=200, validate=False, head=False, extra=()):
        """An answer (answer), with its bytes unless it is to a HEAD."""
        payload = self.answer(body, kind, status, validate, extra)
        if payload is not None and not head:
            self.wfile.write(payload)

    def send_page(self, query, head=False):
        """The page for this address, gzipped once for each version of it (Pages)."""
        body = render_page(self.headers, query)
        tag = etag(body)
        payload = self.answer(body, 'text/html; charset=utf-8', validate=True, tag=tag,
                              pack=lambda page: PACKED_PAGES.get(tag, page), extra=(('X-Build', BUILD),) if BUILD else ())
        if payload is not None and not head:
            self.wfile.write(payload)

    def send_head(self):
        """A file of the build, from what is kept of it (Built): kept a year when asked for
        by its hash, a day for an icon or picture, and otherwise checked by its tag every
        time. The standard handler copies what this returns, for a GET, and sends anything
        that is not a file its own way."""
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().send_head()
        kind = self.guess_type(path)
        body, gz, tag, digest = FILES.get(path, kind)
        version = parse_qs(urlsplit(self.path).query).get('v', [''])[0]
        self.cache_control = BUILT_CACHE if version == digest else IMAGE_CACHE if kind in IMAGE_KINDS else 'no-cache'
        payload = self.answer(body, kind, validate=True, tag=tag, pack=lambda _body: gz)
        return None if payload is None else io.BytesIO(payload)

    def do_HEAD(self):
        self.cache_control = None
        parts = urlsplit(self.path)
        if parts.path in PAGES:
            self.send_page(parse_qs(parts.query), head=True)
        else:
            super().do_HEAD()

    def send_json(self, value, status=200, validate=False, retry_after=None):
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        extra = (('Retry-After', str(retry_after or 2)),) if status in (429, 503) else ()
        self.send_body(body, 'application/json; charset=utf-8', status, validate, extra=extra)

    def admitted(self):
        wait = REQUESTS.take(self.client_address[0], self.headers.get('X-Forwarded-For', ''))
        if not wait:
            return True
        # A rejected POST body is left unread, so this connection must not be reused.
        self.close_connection = True
        self.send_body(json.dumps({'error': 'Requests are catching up. We will retry shortly.'}).encode(),
                       'application/json; charset=utf-8', 429,
                       extra=(('Retry-After', str(wait)), ('Connection', 'close')))
        return False

    def do_GET(self):
        self.cache_control = None
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path.startswith('/api/') and not self.admitted():
            return
        if ACCOUNT_ROUTES.handle(self, path):
            return
        if path == '/healthz':
            self.send_json({'status': 'ok'})
            return
        if path == '/api/search':
            q = query.get('q', [''])[0]
            if len(q) > 100:
                self.send_json({'error': 'Search terms must be 100 characters or fewer.'}, 400)
                return
            try:
                rules = json.loads(query.get('filters', ['{}'])[0])
                found = decorate(search(q, rules), query.get('matrix') == ['1'])
                self.cache_control = SEARCH_CACHE if not rules and 'matrix' not in query else 'no-store'
                self.send_json(found, validate=True)
            except (ValueError, TypeError) as exc:
                self.send_json({'error': str(exc)}, 400)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass    # the page moved on to a longer search while TVmaze answered
            return
        if path in LIVE_ROUTES:
            self.live(path, query)
            return
        if path == '/api/episode-matrices':
            try:
                raw = query.get('ids', [''])[0].split(',')
                if not 1 <= len(raw) <= 40 or any(not re.fullmatch(r'[1-9][0-9]{0,8}', key) for key in raw):
                    raise ValueError('Choose between 1 and 40 shows.')
                ids = list(dict.fromkeys(map(int, raw)))
                if any(show_id not in ENGINE.by_id and not newer(show_id) for show_id in ids):
                    raise ValueError('That show is not in this catalog.')
                self.send_json(RATINGS.matrices(ids))
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
            return
        if path in PEOPLE_ROUTES:
            self.people(path, query)
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
                if show_id not in ENGINE.by_id and not newer(show_id):
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
                self.send_json({'details': details(LIVE.show(show_id))})
            elif path == '/api/episodes':
                self.send_json({'episodes': LIVE.episodes(show_id, season)})
            elif path == '/api/episode-ratings':
                self.send_json(RATINGS.get(show_id))
            elif path == '/api/episode':
                self.send_json({'episode': episode(episode_id)})
            elif path == '/api/trailer':
                self.send_json({'videos': trailers(show_id)})
            else:
                self.send_json(age(show_id))
        except LiveError as exc:
            self.send_json({'error': str(exc)}, exc.status, retry_after=exc.retry_after)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            LIVE_SLOTS.release()

    def people(self, path, query):
        """A person's page or biography. People are not in the catalogue, so any TVmaze
        person id will do, and TVmaze says whether there is one."""
        try:
            person_id = number(query, 'id', 'the person')
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)
            return
        if not LIVE_SLOTS.acquire(blocking=False):
            self.send_json({'error': 'Busy right now. Try again in a moment.'}, 503)
            return
        try:
            if path == '/api/person':
                self.send_json(person(person_id))
            else:
                self.send_json({'biography': biography(person_id)})
        except LiveError as exc:
            self.send_json({'error': str(exc)}, exc.status, retry_after=exc.retry_after)
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
            self.send_json({'error': str(exc)}, exc.status, retry_after=exc.retry_after)
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

    def json_payload(self):
        """Read a fixed-size body within one deadline and a bounded upload slot."""
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
            raise BodyError(400, 'Send a fixed-length JSON body.')
        try:
            length = int(lengths[0])
        except ValueError:
            length = 0
        if not 0 < length <= MOST_BODY:
            raise BodyError(413, f'Send a JSON body under {MOST_BODY // 1024}KB.')
        if self.headers.get_content_type() != 'application/json':
            raise BodyError(415, 'Send application/json.')
        if not BODY_SLOTS.acquire(blocking=False):
            raise BodyError(503, 'Uploads are busy. Try again in a moment.')
        previous_timeout = self.connection.gettimeout()
        try:
            deadline, chunks, remaining = time.monotonic() + BODY_TIMEOUT, [], length
            while remaining:
                wait = deadline - time.monotonic()
                if wait <= 0:
                    raise TimeoutError()
                self.connection.settimeout(wait)
                chunk = self.rfile.read1(min(remaining, 65536))
                if not chunk:
                    raise ValueError()
                chunks.append(chunk)
                remaining -= len(chunk)
            return json.loads(b''.join(chunks), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except TimeoutError:
            raise BodyError(408, 'That request timed out. Please try again.') from None
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise BodyError(400, 'Send valid JSON.') from None
        finally:
            try:
                self.connection.settimeout(previous_timeout)
            finally:
                BODY_SLOTS.release()

    def do_POST(self):
        self.cache_control = None
        if not self.admitted():
            return
        route = urlsplit(self.path).path
        if ACCOUNT_ROUTES.handle(self, route):
            return
        if route not in POSTS:
            self.close_connection = True
            self.send_json({'error': 'Not found.'}, 404)
            return
        try:
            payload = self.json_payload()
        except BodyError as exc:
            # A partial/rejected body must never become the next HTTP/1.1 request.
            self.close_connection = True
            self.send_json({'error': str(exc)}, exc.status)
            return
        # A title newer than the catalogue waits on TVmaze, not on the engine, so it takes a
        # live source's slot rather than one of the engine's few.
        if route == '/api/title' and isinstance(payload, dict) and newer(payload.get('id')):
            self.live_title(payload['id'])
            return
        if not SLOTS.acquire(blocking=False):
            self.send_json({'error': 'Busy right now. Try again in a moment.'}, 503)
            return
        try:
            if route == '/api/shows':
                self.send_json(decorate({'shows': LIBRARY.cards(read_ids(payload))}, payload.get('matrix') is True))
            elif not isinstance(payload, dict):
                raise ValueError('Send your list and settings as an object.')
            elif route == '/api/taste':
                self.send_json(INSIGHTS.describe(payload))
            elif route == '/api/home':
                # The first eight rows and the featured shows, the visit's hero first, or, for a
                # request that says which rows it already shows, the next ones
                # (library.Library.home). Each featured show carries TMDB's data, as a title does.
                home = DISCOVERY.view(payload.get('filters')).home(payload)
                if home.get('hero'):
                    for show in (home['hero'], *home.get('featured', ())):
                        show['tmdb'] = TMDB.get(show['id'])
                self.send_json(decorate(home, payload.get('matrix') is True))
            elif route == '/api/browse':
                view = DISCOVERY.view(payload.get('filters'))
                result = view.browse(payload)
                rules = read_filters(payload.get('filters'))
                for row in result['rows']:
                    ordered = DISCOVERY.order([ENGINE.by_id[c['id']] for c in row['items']], rules)
                    cards = {c['id']: c for c in row['items']}
                    row['items'] = [cards[ENGINE.shows[i]['id']] for i in ordered]
                self.send_json(decorate(result, payload.get('matrix') is True))
            else:
                # TMDB's rating, trailers, backdrop and where to watch come with the title,
                # so the page asks the live sources only for what TMDB lacks.
                title = LIBRARY.title(payload)
                if not isinstance(payload.get('recommendation_filters', {}), dict):
                    raise ValueError('Send recommendation filters as an object.')
                for section in ('more', 'fans'):
                    raw = payload.get('recommendation_filters', {}).get(section)
                    if raw:
                        title[section] = DISCOVERY.view(raw).title(payload)[section]
                        rules = read_filters(raw)
                        if rules.get('sort'):
                            title[section].sort(key=lambda s: sort_key({**s, **DISCOVERY.metadata(s['id'])}, rules['sort'], ENGINE.popularity[ENGINE.by_id[s['id']]]))
                title['tmdb'] = TMDB.get(title['show']['id'])
                self.send_json(decorate(title, payload.get('matrix') is True))
        except ValueError as exc:
            self.send_json({'error': str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            SLOTS.release()

    def live_title(self, show_id):
        """The title page of a show newer than the catalogue (newer_title), on a live
        source's slot."""
        if not LIVE_SLOTS.acquire(blocking=False):
            self.send_json({'error': 'Busy right now. Try again in a moment.'}, 503)
            return
        try:
            self.send_json(newer_title(show_id))
        except LiveError as exc:
            self.send_json({'error': str(exc)}, exc.status, retry_after=exc.retry_after)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            LIVE_SLOTS.release()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    follow.start(os.environ.get('MODEL_DIR') or SOURCE, MODEL)
    # What searching by meaning reads is built behind the first requests, not before them.
    threading.Thread(target=RELATED.warm, daemon=True).start()
    # The shows TVmaze has added since the catalogue, read at once and about hourly after.
    threading.Thread(target=ADDED.run, name='added', daemon=True).start()
    # Warm a broader catalogue gradually, leaving live-request capacity for visitors.
    # Data stays on the workspace volume, so this work also benefits later visits.
    popular = sorted(range(ENGINE.n), key=lambda i: (ENGINE.popularity[i], ENGINE.shows[i].get('rating') or 0), reverse=True)
    RATINGS.start(ENGINE.shows[i]['id'] for i in popular[:2000])
    port = int(os.environ.get('PORT', '8082'))
    ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(PUBLIC))).serve_forever()
