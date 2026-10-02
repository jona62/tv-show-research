"""Pooled HTTP reads with fixed pacing, bounded retries and a shared durable cache.

Every physical attempt spends the same host budget, including nightly jobs and
other apps. Retry-After pauses that host without changing its configured rate.
urllib3 owns connection pooling, TLS and retry classification/backoff.
"""
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin
import gzip
import hashlib
import io
import json
import os
import sqlite3
import threading
import time

import urllib3
from urllib3.exceptions import HTTPError as TransportError, MaxRetryError, SSLError
from urllib3.util import Retry, Timeout

DAY = 86400
AGENT = 'Couchside/1.0 (+https://github.com/jona62/tv-show-research)'
# Shared by all processes on this workspace, rather than multiplied per worker.
GAPS = {'api.tvmaze.com': 10 / 18, 'api.themoviedb.org': 1 / 3,
        'api.kinocheck.com': 90, 'itunes.apple.com': 4,
        'query.wikidata.org': 2, 'en.wikipedia.org': 1,
        'icons.duckduckgo.com': .25}
RETRY = Retry(total=2, connect=2, read=2, status=2, other=0, redirect=0,
              allowed_methods={'GET', 'HEAD'}, status_forcelist={408, 429, 500, 502, 503, 504},
              backoff_factor=.5, backoff_max=4, backoff_jitter=.5,
              respect_retry_after_header=True, retry_after_max=2**63 - 1, raise_on_status=False)


def state_path():
    root = Path(os.environ.get('MODEL_ROOT') or Path(__file__).resolve().parents[2] / 'data')
    return Path(os.environ.get('OUTBOUND_CACHE') or root / 'cache/http.sqlite3')


def cache_key(url):
    parts = urlsplit(url)
    # These APIs return public data. Credentials never enter cache keys or logs.
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != 'api_key')
    normalized = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ''))
    return hashlib.sha256(normalized.encode()).hexdigest()


def retry_after(value, default=10):
    try:
        return max(0, RETRY.parse_retry_after(str(value))) if value else default
    except (ValueError, urllib3.exceptions.InvalidHeader):
        return default


@dataclass(frozen=True)
class Response:
    body: bytes
    headers: dict
    status: int = 200
    stale: bool = False


class State:
    """Small SQLite cache and atomic host admission shared across app releases."""
    def __init__(self, path, clock=time.time, max_bytes=64 * 1024 * 1024):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.max_bytes = clock, max_bytes
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=2)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS http_limits (host TEXT PRIMARY KEY, next REAL, pause REAL);
            CREATE TABLE IF NOT EXISTS http_cache (key TEXT PRIMARY KEY, fetched REAL, headers TEXT, body BLOB);
            CREATE INDEX IF NOT EXISTS http_cache_fetched ON http_cache(fetched);
        ''')

    def delay(self, host, gap):
        """Reserve only an immediately available turn, so cancelled readers leave no queue."""
        now = self.clock()
        with self.lock:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                row = self.db.execute('SELECT next, pause FROM http_limits WHERE host=?', (host,)).fetchone()
                delay = max(0, max(row) - now) if row else 0
                if not delay:
                    self.db.execute('INSERT OR REPLACE INTO http_limits VALUES (?, ?, ?)', (host, now + gap, row[1] if row else 0))
                self.db.commit()
                return delay
            except BaseException:
                self.db.rollback()
                raise

    def hold(self, host, seconds):
        with self.lock, self.db:
            self.db.execute('INSERT INTO http_limits VALUES (?, 0, ?) ON CONFLICT(host) DO UPDATE SET pause=MAX(pause, excluded.pause)',
                            (host, self.clock() + seconds))

    def get(self, key, age):
        with self.lock:
            try:
                row = self.db.execute('SELECT fetched, headers, body FROM http_cache WHERE key=?', (key,)).fetchone()
            except sqlite3.Error:
                return None
        if not row or self.clock() - row[0] > age:
            return None
        try:
            return Response(gzip.decompress(row[2]), json.loads(row[1]))
        except (ValueError, OSError, EOFError):
            return None

    def put(self, key, response):
        body = gzip.compress(response.body, mtime=0)
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?)',
                            (key, self.clock(), json.dumps(response.headers), body))
            self.db.execute('DELETE FROM http_cache WHERE fetched<?', (self.clock() - 30 * DAY,))
            # The oldest compressed records go first; a single large answer cannot grow this without bound.
            total = self.db.execute('SELECT COALESCE(SUM(LENGTH(body)), 0) FROM http_cache').fetchone()[0]
            if total > self.max_bytes:
                for old, size in self.db.execute('SELECT key, LENGTH(body) FROM http_cache ORDER BY fetched').fetchall():
                    self.db.execute('DELETE FROM http_cache WHERE key=?', (old,))
                    total -= size
                    if total <= self.max_bytes:
                        break


class Client:
    def __init__(self, state=None, pool=None, sleep=time.sleep, clock=time.monotonic, retries=RETRY):
        self.state = state or State(state_path())
        self.pool = pool or urllib3.PoolManager(num_pools=12, maxsize=4, block=True)
        self.sleep, self.clock, self.retries = sleep, clock, retries
        self.lock, self.inflight = threading.Lock(), {}

    def _admit(self, host, deadline):
        while True:
            try:
                delay = self.state.delay(host, GAPS.get(host, .25))
            except sqlite3.Error:
                raise URLError('Network admission is temporarily unavailable') from None
            if not delay:
                return
            if delay >= deadline - self.clock():
                raise HTTPError('', 429, 'Provider resting', {'Retry-After': str(max(1, int(delay + 1)))}, None)
            self.sleep(min(delay, .25))

    def _send(self, url, headers, timeout, deadline, max_bytes, attempts, on_attempt):
        retry = self.retries.new(total=attempts - 1)
        host = urlsplit(url).hostname or ''
        origin, redirects = urlsplit(url), 0
        while True:
            self._admit(host, deadline)
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise URLError('Request deadline exceeded')
            response = None
            try:
                if on_attempt:
                    on_attempt()
                response = self.pool.request('GET', url, headers={'User-Agent': AGENT, **headers},
                    timeout=Timeout(total=remaining, connect=min(2, remaining), read=min(timeout, remaining)),
                    pool_timeout=min(2, remaining), retries=False, redirect=False, preload_content=False)
                # Bound the decoded body too; urllib3 handles compressed responses.
                chunks, size = [], 0
                while True:
                    if self.clock() >= deadline:
                        raise URLError('Request deadline exceeded')
                    chunk = response.read1(min(16384, max_bytes + 1 - size), decode_content=True)
                    if not chunk:
                        break
                    chunks.append(chunk);size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('Upstream answer exceeds the size limit')
                body = b''.join(chunks)
                status = response.status
                saved_headers = {'Content-Type': response.headers.get('Content-Type', '')}
                if status == 200:
                    return Response(body, saved_headers)
                if status in (301, 302, 303, 307, 308):
                    target = urljoin(url, response.headers.get('Location', ''))
                    parts = urlsplit(target)
                    if redirects >= 2 or (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc):
                        raise HTTPError('', status, 'Redirect refused', {}, None)
                    redirects += 1;url = target
                    continue
                if status in (429, 503):
                    self._hold(host, retry_after(response.headers.get('Retry-After'), 10 if status == 429 else 1))
                if status in (401, 403):
                    self._hold(host, 60)
                if not retry.is_retry('GET', status):
                    raise HTTPError('', status, 'Upstream request failed', dict(response.headers), io.BytesIO(body))
                try:
                    retry = retry.increment('GET', url, response=response)
                except MaxRetryError:
                    raise HTTPError('', status, 'Upstream retries exhausted', dict(response.headers), io.BytesIO(body)) from None
            except SSLError:
                raise URLError('Upstream TLS verification failed') from None
            except TransportError as error:
                try:
                    retry = retry.increment('GET', url, error=error)
                except (MaxRetryError, TransportError):
                    raise URLError('Upstream connection unavailable') from None
            finally:
                if response is not None:
                    # Close truncated/unread streams before releasing their pool slot.
                    if not response.isclosed():
                        response.close()
                    response.release_conn()
            delay = retry.get_backoff_time()
            if delay >= deadline - self.clock():
                raise URLError('Request deadline exceeded')
            self.sleep(delay)

    def _hold(self, host, seconds):
        try:
            self.state.hold(host, seconds)
        except sqlite3.Error:
            raise URLError('Network admission is temporarily unavailable') from None

    def get(self, url, headers=None, timeout=6, budget=15, max_bytes=5 * 1024 * 1024,
            ttl=0, stale=0, force=False, attempts=3, on_attempt=None, validate=None):
        if urlsplit(url).scheme not in ('https', 'http'):
            raise ValueError('An HTTP URL is required')
        key = cache_key(url)
        held = self.state.get(key, ttl) if ttl and not force else None
        if held:
            return held
        with self.lock:
            pending = self.inflight.get(key)
            owner = pending is None
            if owner:
                pending = self.inflight[key] = Future()
        if not owner:
            try:
                return pending.result(timeout=budget)
            except TimeoutError:
                raise URLError('Upstream answer is still loading') from None
        try:
            try:
                value = self._send(url, headers or {}, timeout, self.clock() + budget, max_bytes, attempts, on_attempt)
                if validate:
                    validate(value.body)
            except (HTTPError, URLError) as error:
                # Missing records and rejected credentials are not temporary outages.
                held = self.state.get(key, stale) if stale and (not isinstance(error, HTTPError) or error.code in RETRY.status_forcelist) else None
                if held is None:
                    raise
                value = Response(held.body, held.headers, held.status, stale=True)
            else:
                if ttl:
                    try:
                        self.state.put(key, value)
                    except sqlite3.Error:
                        pass  # A cache write must not discard a successfully fetched answer.
            pending.set_result(value)
            return value
        except Exception as error:
            pending.set_exception(error)
            raise
        finally:
            with self.lock:
                self.inflight.pop(key, None)

    def json(self, url, **options):
        return json.loads(self.get(url, validate=json.loads, **options).body)


_client, _lock = None, threading.Lock()


def client():
    global _client
    with _lock:
        if _client is None:
            _client = Client()
    return _client
