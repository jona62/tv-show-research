"""Shared, persistent episode data. Readers use saved answers; one worker refreshes them.

The worker shares TVmaze's existing rate budget. TMDB is fetched by season, matched
by external show ID and episode position/date, never by a fuzzy show-name search.
"""
from collections import OrderedDict
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import gzip
import json
import math
import sqlite3
import threading
import time

from live import AGENT, LiveError

DAY = 86400
MAX_AGE = 180 * DAY
MIN_VOTES = 20


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
    def __init__(self, path, clock=time.time, most=5000):
        self.clock, self.most = clock, most
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.lock = threading.Lock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, fetched REAL, touched REAL, data BLOB, matrix BLOB)')
        if 'matrix' not in {r[1] for r in self.db.execute('PRAGMA table_info(episodes)')}:
            self.db.execute('ALTER TABLE episodes ADD COLUMN matrix BLOB')
        self.db.commit()

    def get(self, show_id, compact=False):
        with self.lock:
            column = 'matrix' if compact else 'data'
            row = self.db.execute(f'SELECT fetched, {column} FROM episodes WHERE id=?', (show_id,)).fetchone()
            if not row:
                return None
            if self.clock() - row[0] > MAX_AGE:
                self.db.execute('DELETE FROM episodes WHERE id=?', (show_id,))
                self.db.commit()
                return None
            try:
                if row[1] is None:
                    return None
                value = json.loads(gzip.decompress(row[1]))
            except (OSError, ValueError, EOFError):
                self.db.execute('DELETE FROM episodes WHERE id=?', (show_id,))
                self.db.commit()
                return None
            return row[0], value

    def put(self, show_id, value):
        now = self.clock()
        data = gzip.compress(json.dumps(value, separators=(',', ':'), allow_nan=False).encode(), mtime=0)
        fields = ('season', 'number', 'name', 'rating', 'rating_source', 'rating_votes')
        compact = {**{k: value[k] for k in ('id', 'tmdb_at')},
                   'episodes': [{k: e.get(k) for k in fields} for e in value['episodes']],
                   'tvmaze': [{k: e.get(k) for k in fields} for e in value['tvmaze']]}
        matrix = gzip.compress(json.dumps(compact, separators=(',', ':'), allow_nan=False).encode(), mtime=0)
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO episodes VALUES (?, ?, ?, ?, ?)', (show_id, now, now, data, matrix))
            self.db.execute('DELETE FROM episodes WHERE fetched<?', (now - MAX_AGE,))
            self.db.execute('DELETE FROM episodes WHERE id IN (SELECT id FROM episodes ORDER BY touched DESC LIMIT -1 OFFSET ?)', (self.most,))
            self.db.commit()

    def touch(self, show_id):
        with self.lock:
            self.db.execute('UPDATE episodes SET touched=? WHERE id=? AND touched<?',
                            (self.clock(), show_id, self.clock() - 3600))
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
        with urlopen(Request('https://api.themoviedb.org/3' + path, headers=headers), timeout=6) as response:
            return json.load(response)

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
                    try:
                        wait = float(exc.headers.get('Retry-After', '30'))
                    except (ValueError, AttributeError):
                        wait = 30
                    self.next = max(self.next, time.monotonic() + max(10, min(300, wait)))
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
    def __init__(self, store, live, tmdb=None, clock=time.time, interval=2, ended=()):
        self.store, self.live, self.tmdb, self.clock, self.interval = store, live, tmdb, clock, interval
        self.lock, self.ready = threading.Lock(), threading.Event()
        self.pending, self.active, self.rest = OrderedDict(), {}, {}
        self.ended, self.popular = set(ended), ()
        self.started = False

    def stale(self, show_id, at):
        return self.clock() - at >= (7 * DAY if show_id in self.ended else DAY)

    def enriching(self, show_id, value):
        checked = value.get('tmdb_at', 0)
        return bool(self.tmdb and (not checked or self.stale(show_id, checked)))

    def saved(self, show_id, compact=False):
        held = self.store.get(show_id, compact=compact)
        if held:
            if self.stale(show_id, held[0]):
                self.queue(show_id)
            value = held[1]
            if self.clock() - value.get('tmdb_at', 0) > MAX_AGE and any(e.get('rating_source') == 'TMDB' for e in value['episodes']):
                value = {**value, 'tmdb': {}, 'episodes': merge(value['tvmaze'], {})}
            return value

    def queue(self, show_id, urgent=False):
        with self.lock:
            if show_id in self.active or self.rest.get(show_id, 0) > self.clock():
                return
            if show_id not in self.pending and len(self.pending) >= 500:
                if not urgent:
                    return
                self.pending.popitem()
            self.pending[show_id] = None
            if urgent:
                self.pending.move_to_end(show_id, last=False)
            self.ready.set()

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
            self.store.put(show_id, value)
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
            self.store.put(show_id, value)
            return value
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
        value = self.saved(show_id)
        if value is None:
            # Foreground requests keep the existing TVmaze response time. Enrichment is
            # queued separately so a long-running show's seasons never block its page.
            value = self.refresh(show_id, enrich=False)
            if self.tmdb:
                self.queue(show_id, urgent=True)
        self.store.touch(show_id)
        return {'id': show_id, 'episodes': value['episodes'], 'sources': source_names(value['episodes']),
                'refreshing': self.enriching(show_id, value)}

    def matrices(self, ids):
        found, pending = [], []
        for show_id in ids:
            value = self.saved(show_id, compact=True)
            if value is None:
                self.queue(show_id, urgent=True)
                pending.append(show_id)
                continue
            self.store.touch(show_id)
            eps = value['episodes']
            found.append({'id': show_id, 'sources': source_names(eps), 'refreshing': self.enriching(show_id, value), 'episodes': [
                {k: e.get(k) for k in ('season', 'number', 'name', 'rating', 'rating_source', 'rating_votes')} for e in eps]})
        return {'shows': found, 'pending': pending}

    def start(self, popular=()):
        if self.started:
            return
        self.started = True
        self.popular = tuple(popular)
        self.plan()
        threading.Thread(target=self.run, name='episode-ratings', daemon=True).start()

    def plan(self):
        for show_id in dict.fromkeys((*self.popular, *self.store.recent())):
            held = self.store.get(show_id)
            if not held or self.stale(show_id, held[0]) or self.enriching(show_id, held[1]):
                self.queue(show_id)

    def run(self):
        planned = self.clock()
        while True:
            self.ready.wait(60)
            if self.clock() - planned >= 3600:
                self.plan()
                planned = self.clock()
            with self.lock:
                if self.pending:
                    show_id, _ = self.pending.popitem(last=False)
                else:
                    self.ready.clear()
                    continue
            try:
                self.refresh(show_id)
            except (LiveError, OSError, ValueError, sqlite3.Error):
                # Readers keep stale data. A later request retries after the cooldown.
                pass
            time.sleep(self.interval)
