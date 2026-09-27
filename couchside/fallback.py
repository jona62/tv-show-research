"""What GET /api/search answers, widened by TVmaze's own search when the catalogue's
comes up short. Couchside's build.py copies this file, like engine.py.

The model is rebuilt from TVmaze every night, so a show added since is missing until
the next build, and some phrasings still miss. When the catalogue finds nothing, or
only guesses (typos, initials, part of a title), the server asks TVmaze's search,
which is fuzzy and knows other names. Its matches that are in the catalogue lead the
results, since it knew what the guesses did not; those that are not come back as
missing, with their TVmaze page, so the page can say they arrive with the nightly
refresh. The browser never talks to TVmaze for this.

TVmaze allows about 20 calls every 10 seconds from one address, and every app on this
host shares it. So answers are cached, each app keeps to a small window of its own, a
429 pauses the calls, and a slow or failed call is simply no extra answer.
"""
from collections import OrderedDict, deque
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re
import threading
import time

from titles import LIMIT

API = 'https://api.tvmaze.com'
AGENT = 'TV Taste/1.0 (+https://github.com/jona62/tv-show-research)'
PAGE = re.compile(r'https://www\.tvmaze\.com/shows/\d+(?:/[a-z0-9-]*)?')
SHORTEST = 3            # characters a search needs before TVmaze is asked
MISSING = 3             # shows outside the catalogue worth naming


def trim(raw):
    """TVmaze's matches, best first, as id, name, premiere year and TVmaze page."""
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
        if name:
            out.append({'id': show['id'], 'name': name, 'year': int(premiered[:4]) if premiered[:4].isdigit() else None,
                        'url': url if isinstance(url, str) and PAGE.fullmatch(url) else f'https://www.tvmaze.com/shows/{show["id"]}'})
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
        request = Request(self.base + path, headers={'User-Agent': AGENT, 'Accept': 'application/json'})
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def search(self, q):
        """TVmaze's matches for q, or None when TVmaze could not be asked just now."""
        key = ' '.join(q.casefold().split())
        now = self.clock()
        with self.lock:
            held = self.cache.get(key)
            if held and held[0] > now:
                self.cache.move_to_end(key)
                return held[1]
            while self.sent and now - self.sent[0] > self.period:
                self.sent.popleft()
            if now < self.pause or len(self.sent) >= self.calls:
                return held[1] if held else None
            self.sent.append(now)
        try:
            value = trim(self.fetch('/search/shows?' + urlencode({'q': key})))
        except HTTPError as exc:
            if exc.code == 429:
                with self.lock:
                    self.pause = self.clock() + 10
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
    does not yet}. card turns a catalog index into the app's own card."""
    card = card or engine.card
    found = engine.titles.find(q)
    hits, missing = found.hits, []
    if not found.strong and remote and len(''.join(q.split())) >= SHORTEST:
        wider = remote.search(q) or []
        aka = dict(hits)
        merged = {}
        for i, also in [(engine.by_id[s['id']], None) for s in wider if s['id'] in engine.by_id] + hits:
            merged.setdefault(i, also or aka.get(i))
        hits = list(merged.items())[:LIMIT]
        missing = [s for s in wider if s['id'] not in engine.by_id][:MISSING]
    return {'shows': [{**card(i), 'aka': also} if also else card(i) for i, also in hits], 'missing': missing}
