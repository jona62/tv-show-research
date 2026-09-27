"""Live details from the TVmaze API: cast, seasons, episodes and a widescreen backdrop.

The snapshot holds everything the ranking needs, so none of this is required: a
title page renders without it and fills in when it arrives. Calls go out from
this server, so a browser only ever talks to Couchside and to TVmaze's image
server. Answers are trimmed, cached for six hours, and kept well inside TVmaze's
rate limit of at least 20 calls every 10 seconds; after a 429 the client backs
off, and a stale answer is served rather than none.
"""
from collections import OrderedDict, deque
import html
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = 'https://api.tvmaze.com'
IMAGES = 'https://static.tvmaze.com/uploads/images/'
AGENT = 'Couchside/1.0 (+https://github.com/jona62/tv-show-research)'
SHOW = '/shows/{id}?embed%5B%5D=cast&embed%5B%5D=seasons&embed%5B%5D=images'
EPISODES = '/seasons/{id}/episodes'


class LiveError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def plain(value, limit=700):
    """Plain text from TVmaze's HTML summaries, cut at a word boundary."""
    if not isinstance(value, str):
        return ''
    # Paragraph and line breaks become spaces; inline tags such as <b> simply go.
    spaced = re.sub(r'<(?:br|/?p|/?div|/?li|/?ul|/?ol)\b[^>]*>', ' ', value, flags=re.I)
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', spaced))).strip()
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0] + '…'


def picture(value, size='medium'):
    """An image URL, only if it points at TVmaze's image server."""
    url = value.get(size) if isinstance(value, dict) else None
    return url if isinstance(url, str) and url.startswith(IMAGES) else None


def whole(value):
    return value if type(value) is int else None


def trim_show(raw):
    if not isinstance(raw, dict):
        raise ValueError('not a show')
    embedded = raw.get('_embedded') if isinstance(raw.get('_embedded'), dict) else {}
    seasons = []
    for s in embedded.get('seasons') or []:
        if isinstance(s, dict) and whole(s.get('id')) and whole(s.get('number')) is not None:
            premiere = s.get('premiereDate') if isinstance(s.get('premiereDate'), str) else ''
            seasons.append({'id': s['id'], 'number': s['number'], 'episodes': whole(s.get('episodeOrder')),
                            'year': int(premiere[:4]) if premiere[:4].isdigit() else None})
    cast = []
    for c in embedded.get('cast') or []:
        person = c.get('person') if isinstance(c, dict) and isinstance(c.get('person'), dict) else {}
        character = c.get('character') if isinstance(c, dict) and isinstance(c.get('character'), dict) else {}
        if isinstance(person.get('name'), str):
            cast.append({'name': person['name'],
                         'character': character['name'] if isinstance(character.get('name'), str) else '',
                         'photo': picture(person.get('image')) or picture(character.get('image'))})
    backdrop = None
    backgrounds = [im for im in embedded.get('images') or [] if isinstance(im, dict) and im.get('type') == 'background']
    for im in sorted(backgrounds, key=lambda im: not im.get('main')):
        backdrop = picture((im.get('resolutions') or {}).get('original') or {}, 'url')
        if backdrop:
            break
    externals = raw.get('externals') if isinstance(raw.get('externals'), dict) else {}
    imdb = externals.get('imdb')
    schedule = raw.get('schedule') if isinstance(raw.get('schedule'), dict) else {}
    site = raw.get('officialSite')
    return {
        'seasons': seasons, 'cast': cast[:15], 'backdrop': backdrop,
        'imdb': imdb if isinstance(imdb, str) and re.fullmatch(r'tt\d{5,10}', imdb) else None,
        'site': site if isinstance(site, str) and re.match(r'https?://', site) else None,
        'status': raw.get('status') if isinstance(raw.get('status'), str) else None,
        'ended': raw.get('ended') if isinstance(raw.get('ended'), str) else None,
        'days': [d for d in schedule.get('days') or [] if isinstance(d, str)],
        'time': schedule.get('time') if isinstance(schedule.get('time'), str) else '',
    }


def trim_episodes(raw):
    if not isinstance(raw, list):
        raise ValueError('not an episode list')
    out = []
    for e in raw[:150]:
        if not isinstance(e, dict) or not isinstance(e.get('name'), str):
            continue
        out.append({'number': whole(e.get('number')), 'name': e['name'], 'runtime': whole(e.get('runtime')),
                    'airdate': e.get('airdate') if isinstance(e.get('airdate'), str) else '',
                    'still': picture(e.get('image')), 'summary': plain(e.get('summary'), 360)})
    return out


class Live:
    def __init__(self, fetch=None, ttl=6 * 3600, size=500, calls=15, period=10.0, clock=time.monotonic):
        self.fetch = fetch or self._http
        self.ttl, self.size, self.calls, self.period, self.clock = ttl, size, calls, period, clock
        self.cache = OrderedDict()
        self.sent = deque()
        self.pause = 0.0
        self.lock = threading.Lock()

    @staticmethod
    def _http(path):
        request = Request(API + path, headers={'User-Agent': AGENT, 'Accept': 'application/json'})
        with urlopen(request, timeout=6) as response:
            return json.load(response)

    def get(self, path, trim):
        now = self.clock()
        with self.lock:
            held = self.cache.get(path)
            if held and held[0] > now:
                self.cache.move_to_end(path)
                return held[1]
            while self.sent and now - self.sent[0] > self.period:
                self.sent.popleft()
            if now < self.pause or len(self.sent) >= self.calls:
                if held:
                    return held[1]
                raise LiveError('TVmaze is busy. Details will be back in a moment.', 503)
            self.sent.append(now)
        try:
            value = trim(self.fetch(path))
        except HTTPError as exc:
            if exc.code == 429:
                with self.lock:
                    self.pause = self.clock() + 10
            if held:
                return held[1]
            if exc.code == 404:
                raise LiveError('TVmaze has no details for this show.', 404) from None
            if exc.code == 429:
                raise LiveError('TVmaze is busy. Details will be back in a moment.', 503) from None
            raise LiveError('TVmaze could not be reached.') from None
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
            if held:
                return held[1]
            raise LiveError('TVmaze could not be reached.') from None
        with self.lock:
            self.cache[path] = (self.clock() + self.ttl, value)
            self.cache.move_to_end(path)
            while len(self.cache) > self.size:
                self.cache.popitem(last=False)
        return value

    def show(self, show_id):
        return self.get(SHOW.format(id=show_id), trim_show)

    def episodes(self, show_id, number):
        season = next((s for s in self.show(show_id)['seasons'] if s['number'] == number), None)
        if not season:
            raise LiveError('That season is not listed for this show.', 404)
        return self.get(EPISODES.format(id=season['id']), trim_episodes)
