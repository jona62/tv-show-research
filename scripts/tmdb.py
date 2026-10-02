"""Where to watch, age ratings, trailers and backdrops from TMDB, for display only.

The refresher runs this after each build, as a process of its own. A show is matched
to TMDB by the IMDb id TVmaze keeps for it, or failing that its TheTVDB id, and every
answer, misses included, is remembered in MODEL_ROOT/tmdb/ids.json; a miss is asked
again after 30 days. Each night shows are fetched in turn, first those with nothing
yet, then the 3,000 most popular, then the stalest, until TMDB_DAILY_LIMIT requests
are spent: one for each show's details, and one for each season asked for its
trailers. TMDB keeps many shows' trailers on their seasons rather than on the show
(Breaking Bad has none of its own, but a trailer on season 1 and a teaser on its
last), so a show with no trailer or teaser of its own is asked for the videos of its
first and latest seasons too, and a night with many of those fetches fewer shows;
the rest wait, and come first the next night. Answers are trimmed
to what the apps show and kept in MODEL_ROOT/tmdb/cache.json.gz, and a version gets a
tmdb.json.gz holding only the shows in its own catalog. TMDB allows caching for six
months, so a record older than 180 days is dropped.

Nothing here feeds the model or its vectors, or the ranking. Outbound reads use urllib3.

    TMDB_API_KEY=... python tmdb.py --root MODEL_ROOT --version DIR
    python tmdb.py --version DIR --carry OLD_VERSION/tmdb.json.gz

TMDB_API_KEY takes a v4 read access token (sent as a bearer token) or a v3 key (sent
as the api_key parameter). TMDB_REGION (US), TMDB_MIN_POPULARITY (60, TVmaze's 0 to
100 weight) and TMDB_DAILY_LIMIT (6000 requests for a show's details or a season's
videos, so at most 6,000 shows) tune the rest.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
import argparse
import gzip
import http.client
import json
import math
import os
import re
import ssl
import sys
import threading
import time
import traceback
import zlib
from urllib.error import HTTPError, URLError
from http_client import client

HOST = 'api.themoviedb.org'
REGION = 'US'
MIN_POPULARITY = 60
DAILY_LIMIT = 6000                # requests a night for a show's details or a season's videos
TOP = 3000                        # the most popular shows, refreshed every night the budget allows
WORKERS = 6
RATE = 20.0                       # requests a second, across every worker
MAX_AGE = timedelta(days=180)     # TMDB's limit on keeping its data
MISS_RETRY = timedelta(days=30)   # a show TMDB does not know is asked about again after this
FRESH = timedelta(hours=20)       # a record this young is not fetched again the same day
GIVE_UP = 25                      # shows failing in a row before the step stops
MAX_BODY = 4 << 20
MAX_JSON = 32 << 20
REJECTED = 'TMDB key rejected'
KINDS = ('flatrate', 'free', 'ads', 'rent', 'buy')
TRAILER_TYPES = ('Trailer', 'Teaser')
YOUTUBE = re.compile(r'[A-Za-z0-9_-]{11}')
IMAGE = re.compile(r'/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|svg|webp)')
IMDB = re.compile(r'tt\d{5,10}')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
REGION_CODE = re.compile(r'[A-Z]{2}')
FIND = '/3/find/{id}?external_source={source}'
# Written out by hand: urlencode would turn the slash in watch/providers into %2F.
DETAILS = ('/3/tv/{id}?language=en-US&append_to_response=content_ratings,watch/providers,videos'
           '&include_video_language=en,null')
# A season's videos, asked for with the same languages as a show's own.
SEASON_VIDEOS = '/3/tv/{id}/season/{season}/videos?language=en-US&include_video_language=en,null'
AGENT = 'tv-model-refresher/1.0 (+https://github.com/jona62/tv-show-research)'


class KeyRejected(Exception):
    """TMDB answered 401: the key is wrong or has been revoked."""


class TmdbError(Exception):
    """TMDB kept failing, or answered something that cannot be used."""


def iso(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_time(value):
    """A timestamp written by iso(), or None."""
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def young(record, now, limit=MAX_AGE):
    moment = parse_time(record.get('fetched_at')) if isinstance(record, dict) else None
    return moment is not None and now - moment < limit


# Talking to TMDB -------------------------------------------------------------------

class Auth:
    """A v4 read access token goes in the Authorization header; a v3 key rides in the
    query string. Neither is ever part of a message this module prints."""

    def __init__(self, key):
        self.key = (key or '').strip()
        if not self.key:
            raise ValueError('TMDB_API_KEY is empty.')
        self.bearer = self.key.startswith('eyJ')

    def headers(self):
        return {'Authorization': f'Bearer {self.key}'} if self.bearer else {}

    def sign(self, path):
        if self.bearer:
            return path
        return f"{path}{'&' if '?' in path else '?'}api_key={quote(self.key, safe='')}"

    def redact(self, text):
        return str(text).replace(self.key, '[key]').replace(quote(self.key, safe=''), '[key]')

    def __repr__(self):
        return f"Auth({'bearer token' if self.bearer else 'api_key'})"


class Limiter:
    """Admits one request at a time, spaced to the rate, and holds every worker back
    after a 429 or a failure."""

    def __init__(self, rate=RATE, clock=time.monotonic, sleep=time.sleep):
        self.gap = 1.0 / rate
        self.clock, self.sleep = clock, sleep
        self.turn = threading.Lock()
        self.state = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.turn:
            while True:
                with self.state:
                    delay = self.next - self.clock()
                    if delay <= 0:
                        self.next = self.clock() + self.gap
                        return
                # Short naps, so a hold placed meanwhile is still honoured.
                self.sleep(min(delay, 1.0))

    def hold(self, seconds):
        with self.state:
            self.next = max(self.next, self.clock() + seconds)


def retry_after(value, default=10.0):
    """Seconds to wait from a Retry-After header: a number, an HTTP date, or 10."""
    if value:
        try:
            return min(max(float(value), 1.0), 120.0)
        except ValueError:
            try:
                wait = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
                return min(max(wait, 1.0), 120.0)
            except (TypeError, ValueError):
                pass
    return default


def where(path):
    """A path fit for a log line: never the query string, which may carry a v3 key."""
    return path.split('?', 1)[0]


def connect_https(timeout=20):
    return http.client.HTTPSConnection(HOST, timeout=timeout, context=ssl.create_default_context())


class Client:
    """GETs against the TMDB API over one kept-alive connection per worker thread."""

    def __init__(self, auth, limiter=None, connect=connect_https, attempts=5, log=print):
        self.auth, self.limiter, self.connect = auth, limiter or Limiter(), connect
        self.attempts, self.log = attempts, log
        self.local = threading.local()
        self.rejected = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0

    def get(self, path):
        """The JSON TMDB answers for a path, or None for a 404. Raises KeyRejected on a
        401, and TmdbError once the retries run out."""
        if self.connect is connect_https:
            return self._shared(path)
        problem = 'no answer'
        for attempt in range(self.attempts):
            if self.rejected.is_set():
                raise KeyRejected(REJECTED)
            self.limiter.wait()
            with self.lock:
                self.calls += 1
            try:
                status, wait, body = self._send(path)
            except (OSError, http.client.HTTPException, zlib.error) as exc:
                self._drop()
                problem = type(exc).__name__
                self.limiter.hold(min(2 ** attempt, 30))
                continue
            if status == 200:
                try:
                    return json.loads(body)
                except ValueError:
                    raise TmdbError(f'TMDB sent something other than JSON for {where(path)}') from None
            if status == 404:
                return None
            if status == 401:
                self.rejected.set()
                raise KeyRejected(REJECTED)
            if status == 429:
                problem = 'rate limited'
                self.limiter.hold(retry_after(wait))
                continue
            if status >= 500:
                problem = f'status {status}'
                self.limiter.hold(min(2 ** attempt, 30))
                continue
            raise TmdbError(f'TMDB answered {status} for {where(path)}')
        raise TmdbError(f'TMDB gave up on {where(path)} ({problem})')

    def _shared(self, path):
        if self.rejected.is_set():
            raise KeyRejected(REJECTED)
        def attempted():
            with self.lock:
                self.calls += 1
        try:
            return client().json('https://' + HOST + self.auth.sign(path),
                headers={'Accept': 'application/json', **self.auth.headers()},
                ttl=20 * 3600, budget=90, timeout=20, max_bytes=MAX_JSON, on_attempt=attempted)
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (401, 403):
                self.rejected.set()
                raise KeyRejected(REJECTED) from None
            raise TmdbError(f'TMDB answered {error.code} for {where(path)}') from None
        except (URLError, ValueError):
            raise TmdbError(f'TMDB could not refresh {where(path)}') from None

    def _send(self, path):
        conn = getattr(self.local, 'conn', None)
        if conn is None:
            conn = self.local.conn = self.connect()
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'gzip', 'User-Agent': AGENT,
                   **self.auth.headers()}
        conn.request('GET', self.auth.sign(path), headers=headers)
        response = conn.getresponse()
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            self._drop()
            raise http.client.HTTPException('answer too large')
        if (response.getheader('Content-Encoding') or '').lower() == 'gzip':
            inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)
            body = inflate.decompress(body, MAX_JSON)
            if inflate.unconsumed_tail:
                raise http.client.HTTPException('answer too large')
        return response.status, response.getheader('Retry-After'), body

    def _drop(self):
        conn = getattr(self.local, 'conn', None)
        self.local.conn = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


def find_tmdb_id(client, imdb, tvdb):
    """TMDB's id for a show, looked up by IMDb id and then TheTVDB id: (id, source),
    or (None, None) when TMDB has neither."""
    for value, source in ((imdb, 'imdb_id'), (tvdb, 'tvdb_id')):
        if not value:
            continue
        answer = client.get(FIND.format(id=quote(str(value), safe=''), source=source))
        for result in (answer.get('tv_results') if isinstance(answer, dict) else None) or []:
            if isinstance(result, dict) and type(result.get('id')) is int and result['id'] > 0:
                return result['id'], source
    return None, None


# Trimming an answer to what the apps show ------------------------------------------

def image(value):
    return value if isinstance(value, str) and IMAGE.fullmatch(value) else None


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return round(float(value), 3)
    return None


def trim_rating(block, region):
    """The age rating TMDB lists for the region, such as TV-MA."""
    results = block.get('results') if isinstance(block, dict) else None
    for entry in results if isinstance(results, list) else []:
        if isinstance(entry, dict) and entry.get('iso_3166_1') == region:
            rating = entry.get('rating')
            if isinstance(rating, str) and rating.strip() and len(rating.strip()) <= 16:
                return rating.strip()
    return None


def trim_providers(block, region):
    """Where the show can be watched in the region: subscriptions first, then free, with
    ads, to rent and to buy. A service appears once, under the first way it offers the
    show, in TMDB's own display order."""
    results = block.get('results') if isinstance(block, dict) else None
    local = results.get(region) if isinstance(results, dict) else None
    if not isinstance(local, dict):
        return []
    providers, seen = [], set()
    for kind in KINDS:
        entries = [p for p in local.get(kind) or [] if isinstance(p, dict)] if isinstance(local.get(kind), list) else []
        priority = lambda p: p['display_priority'] if isinstance(p.get('display_priority'), (int, float)) \
            and not isinstance(p.get('display_priority'), bool) else math.inf
        for p in sorted(entries, key=priority):
            name = p.get('provider_name')
            name = name.strip()[:100] if isinstance(name, str) else ''
            if not name or name in seen:
                continue
            seen.add(name)
            providers.append({'name': name, 'logo': image(p.get('logo_path')), 'kind': kind})
    return providers


def trim_trailers(block, season=None):
    """YouTube trailers, then teasers; official ones first, then the newest. At most six.
    A season's carry its number, since a trailer named only "Official Trailer" does not
    say which season it is for."""
    return rank_trailers(trailers_in(block, season))


def trailers_in(block, season=None):
    """The YouTube trailers and teasers in a videos block, each once."""
    results = block.get('results') if isinstance(block, dict) else None
    found, seen = [], set()
    for video in results if isinstance(results, list) else []:
        if not isinstance(video, dict) or video.get('site') != 'YouTube' or video.get('type') not in TRAILER_TYPES:
            continue
        key = video.get('key')
        if not isinstance(key, str) or not YOUTUBE.fullmatch(key) or key in seen:
            continue
        seen.add(key)
        published = video.get('published_at')
        day = published[:10] if isinstance(published, str) and DAY.fullmatch(published[:10]) else None
        found.append({'key': key, 'name': video['name'][:200] if isinstance(video.get('name'), str) else '',
                      'type': video['type'], 'official': video.get('official') is True, 'published': day,
                      **({'season': season} if season is not None else {})})
    return found


def rank_trailers(found):
    """Trailers before teasers, official ones first, then the newest; each video once, and
    six at most."""
    unique, seen = [], set()
    for trailer in found:
        if trailer['key'] not in seen:
            seen.add(trailer['key'])
            unique.append(trailer)
    unique.sort(key=lambda t: t['published'] or '', reverse=True)
    unique.sort(key=lambda t: (TRAILER_TYPES.index(t['type']), not t['official']))
    return unique[:6]


def trailer_seasons(raw):
    """The seasons to ask for trailers when a show has none of its own: its first and its
    latest, specials aside, from the seasons its details list (or, without them, from how
    many it has). One when they are the same season, none when it lists none."""
    listed = sorted({s['season_number'] for s in raw.get('seasons') or [] if isinstance(s, dict)
                     and type(s.get('season_number')) is int and s['season_number'] > 0}) \
        if isinstance(raw, dict) and isinstance(raw.get('seasons'), list) else []
    if not listed and isinstance(raw, dict):
        count = raw.get('number_of_seasons')
        listed = [1, count] if type(count) is int and count > 0 else []
    return list(dict.fromkeys([listed[0], listed[-1]])) if listed else []


def trim_details(raw, tmdb_id, region, fetched_at):
    """One show's record, in the shape tmdb.json.gz promises the apps."""
    if not isinstance(raw, dict):
        raise TmdbError('TMDB sent a show that is not an object')
    providers = trim_providers(raw.get('watch/providers'), region)
    count = raw.get('vote_count')
    return {'tmdb_id': tmdb_id, 'fetched_at': fetched_at,
            'rating': trim_rating(raw.get('content_ratings'), region),
            'watch_link': f'https://www.themoviedb.org/tv/{tmdb_id}/watch?locale={region}' if providers else None,
            'providers': providers,
            'trailers': trim_trailers(raw.get('videos')),
            'backdrop': image(raw.get('backdrop_path')),
            'vote_average': number(raw.get('vote_average')),
            'vote_count': count if type(count) is int and count >= 0 else None,
            'episodes': raw.get('number_of_episodes') if type(raw.get('number_of_episodes')) is int else None,
            'seasons': raw.get('number_of_seasons') if type(raw.get('number_of_seasons')) is int else None}


# Choosing what to fetch --------------------------------------------------------------

def load_index(raw_dir):
    """Each show's TVmaze weight and its IMDb and TheTVDB ids, from the raw pages."""
    index = {}
    for page in sorted(Path(raw_dir).glob('page-*.json')):
        for show in json.loads(page.read_bytes()):
            if not isinstance(show, dict) or type(show.get('id')) is not int:
                continue
            ext = show.get('externals') if isinstance(show.get('externals'), dict) else {}
            imdb = ext.get('imdb') if isinstance(ext.get('imdb'), str) and IMDB.fullmatch(ext['imdb']) else None
            tvdb = ext.get('thetvdb') if type(ext.get('thetvdb')) is int and ext['thetvdb'] > 0 else None
            weight = show.get('weight') if type(show.get('weight')) is int else 0
            index[show['id']] = (max(0, min(100, weight)), imdb, tvdb)
    return index


def catalog_ids(folder):
    """The show ids in a version's catalog, without keeping every show in memory."""
    def keep_id(pairs):
        keys = {k for k, _v in pairs}
        if {'id', 'name', 'genres'} <= keys:
            return next(v for k, v in pairs if k == 'id')
        return dict(pairs)
    with gzip.open(Path(folder) / 'catalog.json.gz', 'rt', encoding='utf-8') as f:
        data = json.load(f, object_pairs_hook=keep_id)
    return {i for i in data['shows'] if type(i) is int}


def same_ids(mapping, imdb, tvdb):
    return mapping.get('imdb') == imdb and mapping.get('tvdb') == tvdb


def plan(index, in_catalog, shows, ids, now, min_popularity=MIN_POPULARITY, limit=DAILY_LIMIT, top=TOP):
    """Tonight's shows, in order: those with no data yet, then those among the 3,000
    most popular, then the stalest. Popular shows need an IMDb or TheTVDB id to be
    found at all; a recent miss waits out its 30 days. Each show takes one request of
    the night's limit at least, so no more than the limit are planned; the step stops
    sooner when season requests have spent the rest. Returns (shows, eligible)."""
    eligible = sorted((sid for sid, (weight, imdb, tvdb) in index.items()
                       if weight >= min_popularity and (imdb or tvdb) and sid in in_catalog),
                      key=lambda sid: (-index[sid][0], sid))

    def waiting(sid):
        mapping = ids.get(str(sid))
        if not isinstance(mapping, dict) or mapping.get('tmdb_id') is not None:
            return False
        checked = parse_time(mapping.get('checked_at'))
        return same_ids(mapping, *index[sid][1:]) and checked is not None and now - checked < MISS_RETRY

    candidates = [sid for sid in eligible if not waiting(sid)]
    popular = set(eligible[:top])
    missing = [sid for sid in candidates if str(sid) not in shows]
    due = [sid for sid in candidates if str(sid) in shows and (
        not young(shows[str(sid)], now, FRESH) or 'episodes' not in shows[str(sid)] or 'seasons' not in shows[str(sid)])]
    first = [sid for sid in due if sid in popular]
    stalest = sorted((sid for sid in due if sid not in popular),
                     key=lambda sid: (shows[str(sid)].get('fetched_at') or '', -index[sid][0], sid))
    return (missing + first + stalest)[:max(0, limit)], len(eligible)


# Files ---------------------------------------------------------------------------------

def write_atomic(path, body):
    """Whole or not at all, and readable by the apps, which run as other users."""
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        with open(tmp, 'wb') as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def gzip_json(value):
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    return gzip.compress(body, compresslevel=9, mtime=0)


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


class Store:
    """The id mapping and the master cache, under MODEL_ROOT/tmdb."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.ids_path = self.folder / 'ids.json'
        self.cache_path = self.folder / 'cache.json.gz'

    def load(self, region, now, log=print):
        ids = read_json(self.ids_path, {})
        cache = read_json(self.cache_path, {})
        shows = cache.get('shows') if isinstance(cache.get('shows'), dict) else {}
        if shows and cache.get('region') != region:
            log(f'TMDB region changed from {cache.get("region")} to {region}; starting the cache again.')
            shows = {}
        kept = {k: v for k, v in shows.items() if young(v, now)}
        if len(kept) < len(shows):
            log(f'Dropped {len(shows) - len(kept):,} TMDB records older than 180 days.')
        return (ids if isinstance(ids, dict) else {}), kept

    def save(self, ids, shows, region):
        self.folder.mkdir(parents=True, exist_ok=True)
        write_atomic(self.ids_path, json.dumps(ids, separators=(',', ':'), sort_keys=True).encode())
        write_atomic(self.cache_path, gzip_json({'region': region, 'shows': dict(sorted(shows.items(), key=lambda kv: int(kv[0])))}))


def write_version(folder, shows, in_catalog, region, now):
    """tmdb.json.gz for one version: its own shows, none older than 180 days. Returns the
    count and the newest fetch; writes nothing when there is nothing to say."""
    keep = {k: v for k, v in sorted(shows.items(), key=lambda kv: int(kv[0]))
            if k.isdigit() and int(k) in in_catalog and young(v, now)}
    target = Path(folder) / 'tmdb.json.gz'
    if not keep:
        target.unlink(missing_ok=True)
        return {'shows': 0, 'fetched_at': None}
    fetched = max(v['fetched_at'] for v in keep.values())
    write_atomic(target, gzip_json({'fetched_at': fetched, 'region': region, 'shows': keep}))
    return {'shows': len(keep), 'fetched_at': fetched}


# The step ------------------------------------------------------------------------------

def refresh(root, version, raw=None, key=None, region=REGION, min_popularity=MIN_POPULARITY,
            limit=DAILY_LIMIT, now=None, connect=connect_https, limiter=None, workers=WORKERS, log=print):
    """Fetch tonight's shows, update the master cache and write the version's
    tmdb.json.gz. Returns counts, and 'error' when the step had to stop early."""
    now = now or datetime.now(timezone.utc)
    stamp = iso(now)
    root, version = Path(root), Path(version)
    auth = Auth(key)
    say = lambda message: log(auth.redact(message))
    client = Client(auth, limiter=limiter, connect=connect, log=say)
    store = Store(root / 'tmdb')
    ids, shows = store.load(region, now, say)
    index = load_index(raw or root / 'raw')
    in_catalog = catalog_ids(version)
    todo, eligible = plan(index, in_catalog, shows, ids, now, min_popularity, limit)
    say(f'TMDB: {eligible:,} popular shows with an IMDb or TheTVDB id, {len(todo):,} to fetch, '
        f'{len(shows):,} cached.')
    lock = threading.Lock()
    stop = threading.Event()
    # seasons: requests for a season's videos; deferred: planned shows the night's limit
    # did not reach, which stay due and come first another night.
    counts = {'fetched': 0, 'missing': 0, 'failed': 0, 'seasons': 0, 'deferred': 0}
    trouble = {'streak': 0, 'error': None}
    budget = {'left': max(0, limit)}

    def spend():
        """One of the night's requests for details or a season's videos, if any are left."""
        with lock:
            if budget['left'] <= 0:
                return False
            budget['left'] -= 1
            return True

    def defer():
        with lock:
            counts['deferred'] += 1

    def season_trailers(tmdb_id, raw_show):
        """For a show with no trailer or teaser of its own, those of its first and latest
        seasons, as far as the night's requests allow. A season TMDB cannot answer costs
        only its own trailers."""
        found = []
        for season in trailer_seasons(raw_show):
            if not spend():
                break
            with lock:
                counts['seasons'] += 1
            try:
                found += trailers_in(client.get(SEASON_VIDEOS.format(id=tmdb_id, season=season)), season)
            except TmdbError:
                continue
        return rank_trailers(found)

    def one(sid):
        if stop.is_set():
            return
        if budget['left'] <= 0:
            defer()
            return
        key_ = str(sid)
        _weight, imdb, tvdb = index[sid]
        try:
            with lock:
                mapping = ids.get(key_)
            if not isinstance(mapping, dict) or not same_ids(mapping, imdb, tvdb) or mapping.get('tmdb_id') is None:
                tmdb_id, source = find_tmdb_id(client, imdb, tvdb)
                with lock:
                    ids[key_] = {'tmdb_id': tmdb_id, 'source': source, 'imdb': imdb, 'tvdb': tvdb, 'checked_at': stamp}
                    if tmdb_id is None:
                        shows.pop(key_, None)
                        counts['missing'] += 1
                        trouble['streak'] = 0
                        return
            else:
                tmdb_id = mapping['tmdb_id']
            if not spend():
                defer()
                return
            raw_show = client.get(DETAILS.format(id=tmdb_id))
            record = trim_details(raw_show, tmdb_id, region, stamp) if raw_show is not None else None
            if record is not None and not record['trailers']:
                record['trailers'] = season_trailers(tmdb_id, raw_show)
            with lock:
                if raw_show is None:
                    # TMDB no longer has it: forget the match and look again in 30 days.
                    ids[key_] = {'tmdb_id': None, 'source': None, 'imdb': imdb, 'tvdb': tvdb, 'checked_at': stamp}
                    shows.pop(key_, None)
                    counts['missing'] += 1
                else:
                    shows[key_] = record
                    counts['fetched'] += 1
                trouble['streak'] = 0
        except KeyRejected:
            with lock:
                trouble['error'] = REJECTED
            stop.set()
        except Exception as exc:
            # One odd answer costs that show, not the night's work.
            with lock:
                counts['failed'] += 1
                trouble['streak'] += 1
                if trouble['streak'] == 1 or counts['failed'] % 100 == 0:
                    say(f'TMDB: show {sid}: {exc if isinstance(exc, TmdbError) else type(exc).__name__}')
                if trouble['streak'] >= GIVE_UP and not trouble['error']:
                    trouble['error'] = 'TMDB is not answering'
                    stop.set()

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, WORKERS))) as pool:
        for n, _ in enumerate(pool.map(one, todo), 1):
            if n % 500 == 0:
                say(f'TMDB: {n:,}/{len(todo):,} shows, {client.calls:,} requests, {time.monotonic() - started:.0f}s')
    if trouble['error']:
        say(f"TMDB: stopped early: {trouble['error']}.")
    if counts['deferred']:
        say(f"TMDB: the night's {limit:,} requests are spent; {counts['deferred']:,} shows wait for another night.")
    store.save(ids, shows, region)
    written = write_version(version, shows, in_catalog, region, now)
    say(f"TMDB: fetched {counts['fetched']:,}, not on TMDB {counts['missing']:,}, failed {counts['failed']:,}, "
        f"{counts['seasons']:,} seasons asked for trailers, {client.calls:,} requests; "
        f"{written['shows']:,} shows in this version.")
    return {'eligible': eligible, 'planned': len(todo), **counts, 'requests': client.calls, **written,
            'error': trouble['error']}


def carry(old, version, now=None, log=print):
    """Carry an older version's tmdb.json.gz into a new one, when no key is set: only the
    new catalog's shows, and only while the data is under 180 days old."""
    now = now or datetime.now(timezone.utc)
    data = read_json(old, {})
    fetched = parse_time(data.get('fetched_at')) if isinstance(data, dict) else None
    if fetched is None or now - fetched >= MAX_AGE:
        log('TMDB: the previous data is missing or older than 180 days; not carried forward.')
        Path(version, 'tmdb.json.gz').unlink(missing_ok=True)
        return {'shows': 0, 'fetched_at': None, 'carried': True}
    shows = data.get('shows') if isinstance(data.get('shows'), dict) else {}
    written = write_version(version, shows, catalog_ids(version), data.get('region') or REGION, now)
    log(f"TMDB: carried {written['shows']:,} shows forward from {old}.")
    return {**written, 'carried': True}


def settings(env=os.environ):
    region = (env.get('TMDB_REGION') or REGION).strip().upper()
    if not REGION_CODE.fullmatch(region):
        raise ValueError('TMDB_REGION must be a two-letter country code such as US.')
    return {'region': region,
            'min_popularity': int(env.get('TMDB_MIN_POPULARITY') or MIN_POPULARITY),
            'limit': int(env.get('TMDB_DAILY_LIMIT') or DAILY_LIMIT)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', required=True, type=Path, help='version folder that gets tmdb.json.gz')
    parser.add_argument('--root', type=Path, help='MODEL_ROOT, which holds tmdb/ and raw/')
    parser.add_argument('--raw', type=Path, help='TVmaze pages to choose shows from (default ROOT/raw)')
    parser.add_argument('--carry', type=Path, help='carry this older tmdb.json.gz forward instead of fetching')
    args = parser.parse_args(argv)
    key = os.environ.get('TMDB_API_KEY', '')
    try:
        if args.carry:
            result = carry(args.carry, args.version)
        else:
            if not args.root:
                parser.error('--root is needed to fetch')
            if not key.strip():
                print('TMDB_API_KEY is not set.', file=sys.stderr)
                return 2
            result = refresh(args.root, args.version, args.raw, key, **settings())
    except Exception:
        # A traceback can quote a request, so it is scrubbed like every other line.
        text = traceback.format_exc()
        print(text.replace(key.strip(), '[key]').replace(quote(key.strip(), safe=''), '[key]') if key.strip() else text,
              file=sys.stderr)
        return 1
    print('RESULT ' + json.dumps(result), flush=True)
    return 3 if result.get('error') == REJECTED else 4 if result.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
