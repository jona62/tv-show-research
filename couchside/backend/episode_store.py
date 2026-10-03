"""Shared, persistent episode data. Readers use saved answers; one worker refreshes them.

The worker shares TVmaze's existing rate budget. TMDB is fetched by season, matched
by external show ID and episode position/date, never by a fuzzy show-name search.
"""
from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from .http_client import client, retry_after
from . import telemetry
import gzip
import hashlib
import json
import math
import sqlite3
import sys
import threading
import time
import weakref
from datetime import date

from .live import AGENT, LiveError

DAY = 86400
MAX_AGE = 180 * DAY
MIN_VOTES = 20
DECODED_BYTES = 64 * 1024 * 1024
MAX_DEMANDS = 2400


def decoded_size(value):
    """Account for decoded Python objects, counting shared references only once."""
    seen, todo, total = set(), [value], 0
    while todo:
        item = todo.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            todo.extend(item.keys())
            todo.extend(item.values())
        elif isinstance(item, (list, tuple)):
            todo.extend(item)
    return total


def choose_rating(tvmaze, tmdb=None):
    """Prefer a TMDB score with 20 votes; then TVmaze; then a smaller TMDB sample.
    Scores are source averages, never blended or filled with a show's overall score.
    """
    tmdb = tmdb or {}
    rating, votes = tmdb.get('rating'), tmdb.get('votes', 0)
    if rating is not None and votes >= MIN_VOTES:
        return rating, 'TMDB', votes
    if tvmaze is not None:
        return tvmaze, 'TVmaze', None
    return (rating, 'TMDB', votes) if rating is not None else (None, None, None)


def merge(episodes, scores):
    out = []
    for e in episodes:
        other = scores.get(f"{e['season']}:{e['number']}")
        # Alternate episode orders must not silently borrow a different episode's score.
        if other and e.get('airdate') and other.get('airdate') and e['airdate'] != other['airdate']:
            other = None
        rating, source, votes = choose_rating(e.get('rating'), other)
        out.append({**e, 'rating': rating, 'rating_source': source, 'rating_votes': votes})
    return out


def source_names(episodes):
    return ' / '.join(s for s in ('TMDB', 'TVmaze') if any(e.get('rating_source') == s for e in episodes))


class Store:
    """Compressed SQLite records outside the app checkout survive builds and restarts."""
    def __init__(self, path, clock=time.time, most=5000, memory_bytes=DECODED_BYTES, memory_most=512):
        self.clock, self.most = clock, most
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.lock = threading.Lock()
        # Both full and compact records are decoded once. Consumers treat them as
        # immutable; updates enter through put, which invalidates both variants.
        self.memory, self.decoding, self.memory_revisions = OrderedDict(), {}, {}
        self.memory_bytes, self.memory_most, self.decoded_bytes = memory_bytes, memory_most, 0
        self.content_revision = 0
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, fetched REAL, touched REAL, data BLOB, matrix BLOB)')
        if 'matrix' not in {r[1] for r in self.db.execute('PRAGMA table_info(episodes)')}:
            self.db.execute('ALTER TABLE episodes ADD COLUMN matrix BLOB')
        self.db.commit()
        # Demand traffic has its own WAL: inserting a refresh request must not
        # invalidate the decoded episode cache in every HTTP worker.
        self.demand_lock = threading.Lock()
        self.demands = sqlite3.connect(str(path) + '.demands.sqlite3', check_same_thread=False, timeout=10)
        self._close_demands = weakref.finalize(self, self.demands.close)
        self.demands.execute('PRAGMA journal_mode=WAL')
        self.demands.execute('CREATE TABLE IF NOT EXISTS demands '
                             '(id INTEGER, source TEXT, urgent INTEGER, requested REAL, available REAL, '
                             'PRIMARY KEY (id, source))')
        self.demands.execute('CREATE INDEX IF NOT EXISTS demands_order ON demands(source, urgent DESC, requested)')
        self.demands.commit()
        self.db.execute('CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY, data TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS live_details (path TEXT PRIMARY KEY, fetched REAL, data BLOB)')
        self._initialize_content_revisions()
        self.content_revision = self._content_version()
        self.data_version = self.db.execute('PRAGMA data_version').fetchone()[0]
        self.summaries = {}
        for show_id, data in self.db.execute('SELECT id, data FROM summaries'):
            try:
                summary = json.loads(data)
                if isinstance(summary, dict) and 'at' in summary:
                    self.summaries[show_id] = summary
            except (ValueError, TypeError):
                pass
        self.revision = 0
        # Backfill once from the existing persistent cache; no upstream requests.
        for show_id in self.recent(self.most):
            if show_id not in self.summaries:
                held = self.get(show_id)
                if held:
                    self.summarize(show_id, held[1], at=held[0])
        self.db.commit()

    def _initialize_content_revisions(self):
        """Observe episode writes from every worker, including older readers.

        Recency and live-detail writes share this WAL but do not change episodes.
        SQLite triggers keep the revision valid even for direct/legacy writers.
        Deleted rows remove their revision, so this index stays bounded with data.
        """
        self.db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS episode_cache_generation
                (singleton INTEGER PRIMARY KEY CHECK(singleton=1), generation INTEGER NOT NULL);
            INSERT OR IGNORE INTO episode_cache_generation VALUES (1, 1);
            CREATE TABLE IF NOT EXISTS episode_cache_revisions
                (id INTEGER PRIMARY KEY, generation INTEGER NOT NULL);
            INSERT OR IGNORE INTO episode_cache_revisions
                SELECT id, (SELECT generation FROM episode_cache_generation WHERE singleton=1) FROM episodes;
            CREATE TRIGGER IF NOT EXISTS episode_cache_insert AFTER INSERT ON episodes BEGIN
                UPDATE episode_cache_generation SET generation=generation+1 WHERE singleton=1;
                INSERT OR REPLACE INTO episode_cache_revisions
                    VALUES (NEW.id, (SELECT generation FROM episode_cache_generation WHERE singleton=1));
            END;
            CREATE TRIGGER IF NOT EXISTS episode_cache_update AFTER UPDATE OF id, fetched, data, matrix ON episodes
                WHEN NEW.id IS NOT OLD.id OR NEW.fetched IS NOT OLD.fetched OR NEW.data IS NOT OLD.data OR NEW.matrix IS NOT OLD.matrix BEGIN
                UPDATE episode_cache_generation SET generation=generation+1 WHERE singleton=1;
                DELETE FROM episode_cache_revisions WHERE id=OLD.id;
                INSERT OR REPLACE INTO episode_cache_revisions
                    VALUES (NEW.id, (SELECT generation FROM episode_cache_generation WHERE singleton=1));
            END;
            CREATE TRIGGER IF NOT EXISTS episode_cache_delete AFTER DELETE ON episodes BEGIN
                UPDATE episode_cache_generation SET generation=generation+1 WHERE singleton=1;
                DELETE FROM episode_cache_revisions WHERE id=OLD.id;
            END;
            COMMIT;
        ''')

    def _content_version(self):
        return self.db.execute('SELECT generation FROM episode_cache_generation WHERE singleton=1').fetchone()[0]

    def _record_versions(self, ids):
        if not ids:
            return ()
        placeholders = ','.join('?' for _ in ids)
        found = dict(self.db.execute(f'SELECT id, generation FROM episode_cache_revisions WHERE id IN ({placeholders})', ids))
        return tuple(found.get(show_id, 0) for show_id in ids)

    def record_revisions(self, ids):
        """Ordered content identities for just the public records being requested."""
        with self.lock:
            self._check_changes()
            return self._record_versions(ids)

    def demand(self, show_id, source, urgent=False):
        """Coalesce bounded refresh requests across all spawned HTTP workers."""
        if source not in ('tvmaze', 'tmdb'):
            raise ValueError('Unknown episode source.')
        now = self.clock()
        with self.demand_lock:
            row = self.demands.execute('SELECT urgent FROM demands WHERE id=? AND source=?',
                                       (show_id, source)).fetchone()
            if row is not None and (row[0] or not urgent):
                return True
            self.demands.execute('BEGIN IMMEDIATE')
            try:
                row = self.demands.execute('SELECT urgent FROM demands WHERE id=? AND source=?',
                                           (show_id, source)).fetchone()
                if row is None and self.demands.execute('SELECT count(*) FROM demands').fetchone()[0] >= MAX_DEMANDS:
                    if not urgent:
                        self.demands.rollback()
                        return False
                    # A direct visitor may replace the oldest low-priority warm
                    # request, while the database remains bounded under abuse.
                    self.demands.execute('DELETE FROM demands WHERE rowid IN '
                                         '(SELECT rowid FROM demands ORDER BY urgent, requested LIMIT 1)')
                self.demands.execute('INSERT INTO demands VALUES (?, ?, ?, ?, ?) '
                                     'ON CONFLICT(id, source) DO UPDATE SET urgent=max(urgent, excluded.urgent)',
                                     (show_id, source, int(urgent), now, now))
                self.demands.commit()
                return True
            except BaseException:
                self.demands.rollback()
                raise

    def next_demand(self, source):
        """The elected owner retains a row until success, so death loses no work."""
        with self.demand_lock:
            row = self.demands.execute('SELECT id FROM demands WHERE source=? AND available<=? '
                                       'ORDER BY urgent DESC, requested LIMIT 1', (source, self.clock())).fetchone()
            return row[0] if row else None

    def finish_demand(self, show_id, source, retry=None):
        with self.demand_lock:
            if retry is None:
                self.demands.execute('DELETE FROM demands WHERE id=? AND source=?', (show_id, source))
            else:
                self.demands.execute('UPDATE demands SET available=? WHERE id=? AND source=?',
                                     (self.clock() + retry, show_id, source))
            self.demands.commit()

    def close(self):
        self.db.close()
        self._close_demands()

    def _check_changes(self):
        """Refresh only changed episodes when another process commits to this WAL."""
        current = self.db.execute('PRAGMA data_version').fetchone()[0]
        if current != self.data_version:
            self.data_version = current
            revision = self._content_version()
            if revision != self.content_revision:
                ids = tuple(dict.fromkeys(key[0] for key in self.memory))
                versions = dict(zip(ids, self._record_versions(ids)))
                for key in list(self.memory):
                    if versions[key[0]] != self.memory_revisions[key]:
                        self._drop_decoded(key)
                self.content_revision = revision
            self._reload_summaries()

    def _reload_summaries(self):
        latest = {}
        for show_id, data in self.db.execute('SELECT id, data FROM summaries'):
            try:
                value = json.loads(data)
                if isinstance(value, dict) and 'at' in value:
                    latest[show_id] = value
            except (ValueError, TypeError):
                continue
        # Dates propagate to every worker, but a rating-only refresh with the
        # same counts must not force all filtered catalog views to be rebuilt.
        metadata = lambda values: {show_id: {key: value for key, value in row.items() if key != 'at'}
                                   for show_id, row in values.items()}
        fresh = lambda values: {show_id for show_id, row in values.items()
                                if self.clock() - row['at'] <= MAX_AGE}
        if metadata(latest) != metadata(self.summaries) or fresh(latest) != fresh(self.summaries):
            self.revision += 1
        self.summaries = latest

    def sync_metadata(self):
        """Refresh Discovery's summaries before requests that need no episode reads."""
        with self.lock:
            self._check_changes()
            return self.revision

    def current_revision(self):
        with self.lock:
            self._check_changes()
            return self.content_revision

    def _drop_decoded(self, key):
        held = self.memory.pop(key, None)
        self.memory_revisions.pop(key, None)
        if held:
            self.decoded_bytes -= held[3]

    def _remember(self, key, record, size, revision):
        if size > self.memory_bytes or self.memory_most <= 0:
            return
        self._drop_decoded(key)
        self.memory[key] = (*record, size)
        self.memory_revisions[key] = revision
        self.decoded_bytes += size
        while self.memory and (self.decoded_bytes > self.memory_bytes or len(self.memory) > self.memory_most):
            self._drop_decoded(next(iter(self.memory)))

    def get_live(self, path):
        """TVmaze show details share this durable store, with a bounded stale fallback."""
        with self.lock:
            row = self.db.execute('SELECT fetched, data FROM live_details WHERE path=?', (path,)).fetchone()
            if not row or self.clock() - row[0] > 30 * DAY:
                return None
            try:
                return row[0], json.loads(gzip.decompress(row[1]))
            except (OSError, ValueError, EOFError):
                return None

    def put_live(self, path, value):
        data = gzip.compress(json.dumps(value, separators=(',', ':'), allow_nan=False).encode(), mtime=0)
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO live_details VALUES (?, ?, ?)', (path, self.clock(), data))
            self.db.execute('DELETE FROM live_details WHERE fetched<?', (self.clock() - 30 * DAY,))
            self.db.execute('DELETE FROM live_details WHERE path IN (SELECT path FROM live_details ORDER BY fetched DESC LIMIT -1 OFFSET ?)', (self.most,))
            self.db.commit()

    def summarize(self, show_id, value, at=None):
        episodes = [e for e in value['episodes'] if not e.get('airdate') or e['airdate'] <= date.today().isoformat()]
        if not episodes:
            return
        runtimes = [e.get('runtime') for e in episodes]
        complete = all(type(n) in (int, float) and n > 0 for n in runtimes)
        summary = {'episodes': len(episodes), 'seasons': len({e['season'] for e in episodes}),
                   'total_minutes': sum(runtimes) if complete else None, 'minutes_estimated': not complete}
        previous = self.summaries.get(show_id, {})
        if {k: v for k, v in previous.items() if k != 'at'} != summary or self.clock() - previous.get('at', 0) > MAX_AGE:
            self.revision += 1
        summary['at'] = self.clock() if at is None else at
        self.summaries = {**self.summaries, show_id: summary}
        self.db.execute('INSERT OR REPLACE INTO summaries VALUES (?, ?)', (show_id, json.dumps(summary)))

    def get(self, show_id, compact=False, *, with_revision=False):
        """Read a decoded record without holding SQLite's lock during gzip/JSON work.

        Concurrent misses share one decode. Its generation is checked afterward,
        so a refresh completing during decoding cannot publish the old record.
        with_revision includes a stable durable-record identity for public caches.
        """
        key = (show_id, compact)
        layer = 'episodes_memory' if compact else 'episodes_full_memory'
        with self.lock:
            self._check_changes()
            held = self.memory.get(key)
            if held:
                if self.clock() - held[0] <= MAX_AGE:
                    self.memory.move_to_end(key)
                    telemetry.cache(layer, 'hit')
                    return held[:3] if with_revision else held[:2]
                self._drop_decoded(key)
            telemetry.cache(layer, 'miss')
            pending = self.decoding.get(key)
            owner = pending is None
            if owner:
                pending = self.decoding[key] = Future()
        if not owner:
            telemetry.cache('episodes_inflight', 'coalesced')
            record = pending.result(timeout=10)
            return record if record is None or with_revision else record[:2]
        try:
            record = self._decode(show_id, compact, key)
            pending.set_result(record)
            return record if record is None or with_revision else record[:2]
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.decoding.pop(key, None)

    def _decode(self, show_id, compact, key):
        # Retry if a put or an external writer overtook this record's decoding.
        while True:
            with self.lock:
                self._check_changes()
                row = self._read_row(show_id, compact)
            if row is None:
                return None
            revision = row[2]
            try:
                value = json.loads(gzip.decompress(row[1]))
            except (OSError, ValueError, EOFError, TypeError):
                with self.lock:
                    self._check_changes()
                    if revision != self._record_versions((show_id,))[0]:
                        continue
                    telemetry.cache('episodes_disk', 'corrupt')
                    self.db.execute('DELETE FROM episodes WHERE id=?', (show_id,))
                    self.db.commit()
                    self.content_revision = self._content_version()
                    self._drop_decoded((show_id, True))
                    self._drop_decoded((show_id, False))
                return None
            fingerprint = hashlib.sha256(str(row[0]).encode() + b':' + row[1]).hexdigest()[:24]
            record = (row[0], value, fingerprint)
            size = decoded_size(record)
            with self.lock:
                self._check_changes()
                if revision != self._record_versions((show_id,))[0]:
                    continue
                self._remember(key, record, size, revision)
            telemetry.cache('episodes_disk', 'hit')
            return record

    def _read_row(self, show_id, compact):
        """Read or expire one compressed record while holding the database lock."""
        column = 'matrix' if compact else 'data'
        row = self.db.execute(f'SELECT e.fetched, e.{column}, r.generation FROM episodes e '
                              'JOIN episode_cache_revisions r ON r.id=e.id WHERE e.id=?', (show_id,)).fetchone()
        if not row or row[1] is None:
            telemetry.cache('episodes_disk', 'miss')
            return None
        if self.clock() - row[0] > MAX_AGE:
            telemetry.cache('episodes_disk', 'expired')
            self.db.execute('DELETE FROM episodes WHERE id=?', (show_id,))
            self.db.commit()
            self.content_revision = self._content_version()
            self._drop_decoded((show_id, True))
            self._drop_decoded((show_id, False))
            return None
        return row

    def put(self, show_id, value, fetched_at=None):
        now = self.clock()
        fetched_at = now if fetched_at is None else fetched_at
        with self.lock:
            # A process-local lock cannot serialize different HTTP workers.
            # Reserve the writer before reading/merging the latest provider data.
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self._check_changes()
                value = self._put(show_id, value, fetched_at, now)
                self.db.commit()
            except BaseException:
                self.db.rollback()
                self._reload_summaries()
                raise
            # Expired and disk-evicted records must not survive in decoded memory.
            remembered = tuple({key[0] for key in self.memory})
            placeholders = ','.join('?' for _ in remembered)
            remaining = {row[0] for row in self.db.execute(
                f'SELECT id FROM episodes WHERE id IN ({placeholders})', remembered)} if remembered else set()
            for key in list(self.memory):
                if key[0] not in remaining:
                    self._drop_decoded(key)
            self.content_revision = self._content_version()
            return value

    def _put(self, show_id, value, fetched_at, now):
        # The two refresh lanes can finish together. A TVmaze update keeps a
        # newer provider answer that finished after its initial cache read.
        row = self.db.execute('SELECT fetched, data FROM episodes WHERE id=?', (show_id,)).fetchone()
        if row:
            try:
                latest = json.loads(gzip.decompress(row[1]))
                if row[0] > fetched_at:
                    fetched_at = row[0]
                    value = {**value, 'tvmaze': latest['tvmaze'],
                             'episodes': merge(latest['tvmaze'], value.get('tmdb', {}))}
                checked = latest.get('tmdb_at', 0)
                if checked > value.get('tmdb_at', 0) and now - checked <= MAX_AGE:
                    value = {**value, 'tmdb_at': checked, 'tmdb': latest.get('tmdb', {}),
                             'episodes': merge(value['tvmaze'], latest.get('tmdb', {}))}
            except (OSError, ValueError, EOFError):
                pass
        data = gzip.compress(json.dumps(value, separators=(',', ':'), allow_nan=False).encode(), mtime=0)
        fields = ('season', 'number', 'name', 'rating', 'rating_source', 'rating_votes')
        compact = {**{k: value[k] for k in ('id', 'tmdb_at')},
                   'episodes': [{k: e.get(k) for k in fields} for e in value['episodes']],
                   'tvmaze': [{k: e.get(k) for k in fields} for e in value['tvmaze']]}
        matrix = gzip.compress(json.dumps(compact, separators=(',', ':'), allow_nan=False).encode(), mtime=0)
        self.summarize(show_id, value, at=fetched_at)
        self._drop_decoded((show_id, True))
        self._drop_decoded((show_id, False))
        self.db.execute('INSERT OR REPLACE INTO episodes VALUES (?, ?, ?, ?, ?)', (show_id, fetched_at, now, data, matrix))
        self.db.execute('DELETE FROM episodes WHERE fetched<?', (now - MAX_AGE,))
        self.db.execute('DELETE FROM episodes WHERE id IN (SELECT id FROM episodes ORDER BY touched DESC LIMIT -1 OFFSET ?)', (self.most,))
        return value

    def touch(self, show_id):
        with self.lock:
            now = self.clock()
            row = self.db.execute('SELECT touched FROM episodes WHERE id=?', (show_id,)).fetchone()
            if row is None or row[0] >= now - 3600:
                return
            self.db.execute('UPDATE episodes SET touched=? WHERE id=? AND touched<?',
                            (now, show_id, now - 3600))
            self.db.commit()

    def recent(self, most=200):
        with self.lock:
            return [r[0] for r in self.db.execute('SELECT id FROM episodes ORDER BY touched DESC LIMIT ?', (most,))]


class Tmdb:
    """An optional authenticated reader, paced at three calls/second with 429 backoff."""
    def __init__(self, key, ids=None, fetch=None):
        self.key, self.ids, self.fetch = key, ids or {}, fetch or self._http
        self.lock, self.next = threading.Lock(), 0
        self.disabled = False

    def _http(self, path):
        headers = {'Accept': 'application/json', 'User-Agent': AGENT}
        if len(self.key) > 40:
            headers['Authorization'] = 'Bearer ' + self.key
        else:
            path += ('&' if '?' in path else '?') + urlencode({'api_key': self.key})
        return client().json('https://api.themoviedb.org/3' + path, headers=headers,
                             ttl=DAY, budget=12)

    def get(self, path):
        if self.disabled:
            raise LiveError('Episode ratings could not be refreshed.')
        with self.lock:
            delay = self.next - time.monotonic()
            if delay > 1:
                raise LiveError('Episode ratings will refresh after the service rests.', 503)
            self.next = max(self.next, time.monotonic()) + 1 / 3
        if delay > 0:
            time.sleep(delay)
        try:
            value = self.fetch(path)
            if value is not None and not isinstance(value, dict):
                raise LiveError('Episode ratings could not be refreshed.')
            return value
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code == 429:
                with self.lock:
                    self.next = max(self.next, time.monotonic() + retry_after(exc.headers.get('Retry-After'), 30))
            if exc.code in (401, 403):
                self.disabled = True
            raise LiveError('Episode ratings could not be refreshed.') from None

    def ratings(self, show_id, live):
        tmdb_id = self.ids.get(show_id)
        if not tmdb_id:
            imdb = live.show(show_id).get('imdb')
            if not imdb:
                return {}
            found = self.get(f'/find/{imdb}?external_source=imdb_id') or {}
            matches = [m for m in found.get('tv_results') or [] if isinstance(m, dict)]
            tmdb_id = matches[0].get('id') if len(matches) == 1 else None
            if type(tmdb_id) is not int or tmdb_id <= 0:
                return {}
            self.ids[show_id] = tmdb_id
        show = self.get(f'/tv/{tmdb_id}') or {}
        scores = {}
        for season in show.get('seasons') or []:
            if not isinstance(season, dict):
                continue
            number = season.get('season_number')
            if type(number) is not int or number <= 0:
                continue
            raw = self.get(f'/tv/{tmdb_id}/season/{number}') or {}
            for e in raw.get('episodes') or []:
                if not isinstance(e, dict):
                    continue
                s, n, score, votes = e.get('season_number'), e.get('episode_number'), e.get('vote_average'), e.get('vote_count')
                if (type(s) is int and s == number and type(n) is int and n > 0
                        and type(score) in (int, float) and math.isfinite(score) and 0 < score <= 10
                        and type(votes) is int and votes > 0):
                    scores[f'{s}:{n}'] = {'rating': round(score, 1), 'votes': votes, 'airdate': e.get('air_date')}
        return scores


class Episodes:
    def __init__(self, store, live, tmdb=None, clock=time.time, interval=1, ended=()):
        self.store, self.live, self.tmdb, self.clock, self.interval = store, live, tmdb, clock, interval
        self.lock, self.ready = threading.Lock(), threading.Event()
        self.pending, self.active, self.rest = OrderedDict(), {}, {}
        self.enrichment = OrderedDict()
        self.enrichment_active, self.enrichment_rest = set(), {}
        self.stop = threading.Event()
        self.ended, self.popular = set(ended), ()
        self.started = False
        self.workers = []

    def stale(self, show_id, at):
        return self.clock() - at >= (7 * DAY if show_id in self.ended else DAY)

    def enriching(self, show_id, value):
        checked = value.get('tmdb_at', 0)
        return bool(self.tmdb and not getattr(self.tmdb, 'disabled', False) and (not checked or self.stale(show_id, checked)))

    def saved(self, show_id, compact=False):
        held = self.saved_record(show_id, compact=compact)
        return held[1] if held else None

    def saved_record(self, show_id, compact=False):
        """Full cached data and its durable identity; queue refreshes without fetching."""
        held = self.store.get(show_id, compact=compact, with_revision=True)
        if held:
            if self.stale(show_id, held[0]):
                # A visitor looking at stale data must take priority over the
                # broader automatic warm queue, including when it is full.
                self.queue(show_id, urgent=True)
            value = held[1]
            revision = held[2]
            if self.clock() - value.get('tmdb_at', 0) > MAX_AGE and any(e.get('rating_source') == 'TMDB' for e in value['episodes']):
                value = {**value, 'tmdb': {}, 'episodes': merge(value['tvmaze'], {})}
                revision += '-tvmaze'
            if self.enriching(show_id, value):
                self.queue_enrichment(show_id, urgent=True)
            return held[0], value, revision

    def queue_enrichment(self, show_id, urgent=False):
        with self.lock:
            if show_id in self.enrichment_active or self.enrichment_rest.get(show_id, 0) > self.clock():
                return
            if len(self.enrichment) < 2400 or show_id in self.enrichment:
                self.enrichment[show_id] = urgent or self.enrichment.get(show_id, False)
        self.store.demand(show_id, 'tmdb', urgent=urgent)

    def queue(self, show_id, urgent=False):
        with self.lock:
            if show_id in self.active or self.rest.get(show_id, 0) > self.clock():
                return
            if show_id not in self.pending and len(self.pending) >= 2400:
                if not urgent:
                    return
                self.pending.popitem()
            self.pending[show_id] = urgent or self.pending.get(show_id, False)
            self.ready.set()
        self.store.demand(show_id, 'tvmaze', urgent=urgent)

    def refresh(self, show_id, enrich=True):
        with self.lock:
            event = self.active.get(show_id)
            own = event is None
            if own:
                if self.rest.get(show_id, 0) > self.clock():
                    raise LiveError('Ratings are loading. Try again in a moment.', 503)
                event = self.active[show_id] = threading.Event()
                self.pending.pop(show_id, None)
        if not own:
            telemetry.cache('episodes_inflight', 'coalesced')
            event.wait(8)
            held = self.store.get(show_id)
            if held:
                return held[1]
            raise LiveError('Ratings are loading. Try again in a moment.', 503)
        try:
            held = self.store.get(show_id)
            episodes = self.live.episode_ratings(show_id)
            scores, checked = (held[1].get('tmdb', {}) if held else {}), (held[1].get('tmdb_at', 0) if held else 0)
            if self.clock() - checked > MAX_AGE:
                scores = {}
            value = {'id': show_id, 'tvmaze': episodes, 'episodes': merge(episodes, scores), 'tmdb': scores, 'tmdb_at': checked}
            value = self.store.put(show_id, value)
            event.set()  # First visitors can use TVmaze while TMDB's seasons arrive.
            if enrich and self.tmdb:
                try:
                    scores = self.tmdb.ratings(show_id, self.live)
                    checked = self.clock()
                except (LiveError, OSError, ValueError, KeyError, TypeError):
                    pass  # Keep the last good fallback; never sacrifice TVmaze's answer.
            if self.clock() - checked > MAX_AGE:
                scores = {}
            value = {'id': show_id, 'tvmaze': episodes, 'episodes': merge(episodes, scores), 'tmdb': scores, 'tmdb_at': checked}
            return self.store.put(show_id, value)
        except LiveError:
            with self.lock:
                self.rest = {k: v for k, v in self.rest.items() if v > self.clock()}
                self.rest[show_id] = self.clock() + 60
            raise
        finally:
            with self.lock:
                self.active.pop(show_id, None)
                event.set()

    def get(self, show_id):
        held = self.saved_record(show_id)
        if held is None:
            # Foreground requests keep the existing TVmaze response time. Enrichment is
            # queued separately so a long-running show's seasons never block its page.
            value = self.refresh(show_id, enrich=False)
            if self.tmdb:
                self.queue_enrichment(show_id, urgent=True)
            held = self.saved_record(show_id)
            if held is None:
                # An immediate disk eviction must not discard the valid provider
                # answer just returned to this visitor.
                revision = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]
                held = (self.clock(), value, revision)
        return self.public_record(show_id, held)

    def public_record(self, show_id, held):
        fetched, value, revision = held
        self.store.touch(show_id)
        expires = fetched + (7 * DAY if show_id in self.ended else DAY)
        checked = value.get('tmdb_at', 0)
        if checked and checked + MAX_AGE > self.clock():
            expires = min(expires, checked + MAX_AGE)
        return {'id': show_id, 'episodes': value['episodes'],
                'sources': source_names(value['episodes']),
                'refreshing': self.stale(show_id, fetched) or self.enriching(show_id, value),
                'fetchedAt': fetched, 'revision': revision, 'expiresAt': expires}

    def matrices(self, ids):
        found, pending = [], []
        for show_id in ids:
            held = self.saved_record(show_id, compact=True)
            if held is None:
                self.queue(show_id, urgent=True)
                pending.append(show_id)
                continue
            self.store.touch(show_id)
            fetched, value, _revision = held
            eps = value['episodes']
            found.append({'id': show_id, 'sources': source_names(eps),
                          'refreshing': self.stale(show_id, fetched) or self.enriching(show_id, value), 'episodes': [
                {k: e.get(k) for k in ('season', 'number', 'name', 'rating', 'rating_source', 'rating_votes')} for e in eps]})
        return {'shows': found, 'pending': pending}

    def batch(self, ids):
        """Read complete public episodes for comparisons; missing data warms separately.

        Unlike matrices, every original episode ID, image and description remains.
        No request in this path contacts a provider or invents a missing score.
        """
        found, pending = [], []
        for show_id in ids:
            held = self.saved_record(show_id)
            if held is None:
                self.queue(show_id, urgent=True)
                pending.append(show_id)
                continue
            found.append(self.public_record(show_id, held))
        return {'shows': found, 'pending': pending}

    def start(self, popular=()):
        if self.started:
            return
        self.started = True
        self.popular = tuple(popular)
        self.workers = [threading.Thread(target=self.run, name='episode-ratings', daemon=True)]
        if self.tmdb:
            self.workers.append(threading.Thread(target=self.enrich, name='episode-enrichment', daemon=True))
        for worker in self.workers:
            worker.start()

    def enrich(self):
        # Season lookups have their own paced lane; a long show cannot hold up
        # other shows' first TVmaze matrices. All writes still use the shared store.
        while not self.stop.is_set():
            show_id = self.store.next_demand('tmdb')
            with self.lock:
                if show_id is not None:
                    self.enrichment.pop(show_id, None)
                    self.enrichment_active.add(show_id)
            if show_id is None:
                self.stop.wait(.25)
                continue
            held = self.store.get(show_id)
            if not held:
                self.store.finish_demand(show_id, 'tmdb', retry=.5)
                with self.lock:
                    self.enrichment_active.discard(show_id)
                continue
            try:
                if self.enriching(show_id, held[1]):
                    scores = self.tmdb.ratings(show_id, self.live)
                    held = self.store.get(show_id)
                    if not held:
                        self.store.finish_demand(show_id, 'tmdb', retry=.5)
                        continue
                    value = held[1]
                    value = {**value, 'tmdb': scores, 'tmdb_at': self.clock(), 'episodes': merge(value['tvmaze'], scores)}
                    self.store.put(show_id, value, fetched_at=held[0])
                self.store.finish_demand(show_id, 'tmdb')
            except (LiveError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                self.store.finish_demand(show_id, 'tmdb', retry=60)
                with self.lock:
                    self.enrichment_rest[show_id] = self.clock() + 60
            finally:
                with self.lock:
                    self.enrichment_active.discard(show_id)

    def plan(self):
        for show_id in dict.fromkeys((*self.popular, *self.store.recent())):
            if self.stop.is_set():
                break
            held = self.store.get(show_id)
            if not held or self.stale(show_id, held[0]):
                self.queue(show_id)
            elif self.enriching(show_id, held[1]):
                self.queue_enrichment(show_id)

    def run(self):
        # Planning can decode thousands of saved records. Keep it on this worker
        # rather than blocking the ASGI election/startup event loop.
        self.plan()
        planned = self.clock()
        while not self.stop.is_set():
            # Followers cannot signal this process's Event. Poll the durable
            # demand queue frequently so a sticky connection does not strand a
            # cold title in a follower's private memory.
            self.ready.wait(.25)
            self.ready.clear()
            if self.stop.is_set():
                break
            if hasattr(self.live, 'spare') and not self.live.spare():
                self.stop.wait(.5)
                continue
            if self.clock() - planned >= 3600:
                self.plan()
                planned = self.clock()
            show_id = self.store.next_demand('tvmaze')
            if show_id is None:
                continue
            with self.lock:
                self.pending.pop(show_id, None)
            try:
                held = self.store.get(show_id)
                if not held or self.stale(show_id, held[0]):
                    self.refresh(show_id, enrich=False)
                if self.tmdb and (not held or self.enriching(show_id, held[1])):
                    self.queue_enrichment(show_id)
                self.store.finish_demand(show_id, 'tvmaze')
            except (LiveError, OSError, ValueError, sqlite3.Error):
                # Readers keep stale data. A later request retries after the cooldown.
                self.store.finish_demand(show_id, 'tvmaze', retry=60)
            self.stop.wait(self.interval)
