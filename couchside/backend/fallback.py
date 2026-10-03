"""What GET /api/search answers, widened by TVmaze's own search when the catalogue's
comes up short. Couchside's build.py copies this file, like engine.py.

The model is rebuilt from TVmaze every night, so a show added since is missing until
the next build, and some phrasings still miss. When the catalogue finds nothing, or
only guesses (typos, initials, part of a title), the server asks TVmaze's search,
which is fuzzy and knows other names. Its matches that are in the catalogue lead the
results unless the local search corrects one slip in a complete title; that precise
match stays ahead of remote partial matches, while a remote exact title still wins.
Those that are not in the catalogue come back as
missing, with their TVmaze page and poster, so the page can say they arrive with the
nightly refresh (Couchside opens each as a title page from TVmaze meanwhile), and put
them first when TVmaze ranks one of them first. The browser never
talks to TVmaze for this.

TVmaze allows about 20 calls every 10 seconds from one address, and every app on this
host shares it. So answers are cached, each app keeps to a small window of its own,
searches wait for a finished last word, a 429 pauses the calls, and a slow or failed
call is simply no extra answer.
"""
from collections import OrderedDict, deque
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from .http_client import client, retry_after
from . import telemetry
import json
import re
import threading
import time

from .recommendation.titles import LIMIT, forms, normalize

API = 'https://api.tvmaze.com'
AGENT = 'TV Taste/1.0 (+https://github.com/jona62/tv-show-research)'
PAGE = re.compile(r'https://www\.tvmaze\.com/shows/\d+(?:/[a-z0-9-]*)?')
POSTER = re.compile(r'https://static\.tvmaze\.com/uploads/images/medium_portrait/\d+/\d+\.jpg')
SHORTEST = 3            # characters a search needs before TVmaze is asked
MISSING = 3             # shows outside the catalogue worth naming


def trim(raw):
    """TVmaze's matches, best first, as id, name, premiere year, TVmaze page and poster."""
    if not isinstance(raw, list):
        raise ValueError('not a TVmaze search answer')
    out = []
    for hit in raw:
        show = hit.get('show') if isinstance(hit, dict) else None
        if not isinstance(show, dict) or type(show.get('id')) is not int or not isinstance(show.get('name'), str):
            continue
        name = ' '.join(show['name'].split())[:200]
        premiered = show.get('premiered') if isinstance(show.get('premiered'), str) else ''
        url = show.get('url')
        poster = show['image'].get('medium') if isinstance(show.get('image'), dict) else None
        if name:
            out.append({'id': show['id'], 'name': name, 'year': int(premiered[:4]) if premiered[:4].isdigit() else None,
                        'url': url if isinstance(url, str) and PAGE.fullmatch(url) else f'https://www.tvmaze.com/shows/{show["id"]}',
                        'poster': poster if isinstance(poster, str) and POSTER.fullmatch(poster) else None})
    return out[:10]


class Remote:
    """TVmaze's search, cached, kept to calls per period, and never an error."""

    def __init__(self, fetch=None, base=API, ttl=3600, size=500, calls=4, period=10.0, timeout=3.0, clock=time.monotonic):
        self.fetch = fetch or self._http
        self.base, self.ttl, self.size, self.calls, self.period = base, ttl, size, calls, period
        self.timeout, self.clock = timeout, clock
        self.cache = OrderedDict()
        self.sent = deque()
        self.pause = 0.0
        self.lock = threading.Lock()

    def _http(self, path):
        return client().json(self.base + path, headers={'Accept': 'application/json'},
                             timeout=self.timeout, budget=min(5, self.timeout * 2), attempts=2, ttl=self.ttl, stale=86400)

    def search(self, q):
        """TVmaze's matches for q, or None when TVmaze could not be asked just now."""
        key = ' '.join(q.casefold().split())
        now = self.clock()
        with self.lock:
            held = self.cache.get(key)
            if held and held[0] > now:
                self.cache.move_to_end(key)
                telemetry.cache('search_memory', 'hit')
                return held[1]
            telemetry.cache('search_memory', 'miss')
            while self.sent and now - self.sent[0] > self.period:
                self.sent.popleft()
            if now < self.pause or len(self.sent) >= self.calls:
                telemetry.cache('search_memory', 'stale' if held else 'blocked')
                return held[1] if held else None
            self.sent.append(now)
        try:
            value = trim(self.fetch('/search/shows?' + urlencode({'q': key})))
        except HTTPError as exc:
            if exc.code == 429:
                with self.lock:
                    self.pause = self.clock() + retry_after(exc.headers.get('Retry-After'))
            return held[1] if held else None
        except (URLError, OSError, ValueError, TypeError, RecursionError):
            return held[1] if held else None
        with self.lock:
            self.cache[key] = (self.clock() + self.ttl, value)
            self.cache.move_to_end(key)
            while len(self.cache) > self.size:
                self.cache.popitem(last=False)
        return value


def answer(engine, q, remote=None, card=None):
    """{'shows': cards, best first, 'missing': shows TVmaze knows that the catalogue
    does not yet, 'missing_first': whether TVmaze's best match is one of those}. card
    turns a catalog index into the app's own card."""
    card = card or engine.card
    found = engine.titles.find(q)
    hits, missing, first = found.hits, [], False
    # Searches arrive as someone types, so TVmaze waits for a finished last word
    # rather than spend its few calls on half of one.
    if not found.strong and not found.typing and remote and len(''.join(q.split())) >= SHORTEST:
        wider = remote.search(q) or []
        aka = dict(hits)
        preferred = found.preferred
        shapes = forms([word.encode() for word in normalize([q.replace('\n', ' ')])[0].split()])
        exact = [show for show in wider if shapes.keys() & forms(
            [word.encode() for word in normalize([show['name']])[0].split()]).keys()] if preferred else []
        # A remote exact title still wins. Otherwise a local whole-title typo
        # correction must not fall behind a remote franchise or partial title.
        remote_hits = lambda shows: [(engine.by_id[s['id']], None) for s in shows if s['id'] in engine.by_id]
        merged = {}
        for i, also in remote_hits(exact) + list(preferred) + remote_hits(wider) + hits:
            merged.setdefault(i, also or aka.get(i))
        hits = list(merged.items())[:LIMIT]
        missing = {}
        for show in exact + wider:
            if show['id'] not in engine.by_id:
                missing.setdefault(show['id'], show)
        missing = list(missing.values())[:MISSING]
        leaders = exact if preferred else wider
        first = bool(leaders) and leaders[0]['id'] not in engine.by_id
    return {'shows': [{**card(i), 'aka': also} if also else card(i) for i, also in hits], 'missing': missing,
            'missing_first': first}
