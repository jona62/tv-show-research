"""Live details for a title page, fetched by this server and cached.

TVmaze gives cast, seasons, episodes, a widescreen backdrop and where a show airs.
KinoCheck gives official trailers, found by the IMDb id TVmaze supplies. iTunes
gives the US age rating and an Apple TV link for shows sold there. DuckDuckGo's
icon service gives each streaming service's small icon.

The snapshot holds everything the ranking needs, so none of this is required: a
title page renders without it and fills in as each answer arrives. Answers are
trimmed, cached, and kept inside each service's rate limit; after a 429 a source
backs off, and a stale answer is served rather than none.
"""
from collections import OrderedDict, deque
import html
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = 'https://api.tvmaze.com'
KINOCHECK = 'https://api.kinocheck.com'
ITUNES = 'https://itunes.apple.com'
ICON = 'https://icons.duckduckgo.com/ip3/{host}.ico'
YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')
HOST = re.compile(r'(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')
AGES = ('TV-Y', 'TV-Y7', 'TV-G', 'TV-PG', 'TV-14', 'TV-MA')
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
            # The TVmaze id opens the person's own page (people.py); without one the name is text.
            cast.append({'id': person['id'] if (whole(person.get('id')) or 0) > 0 else None, 'name': person['name'],
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
    channels = [c for c in (channel(raw.get('webChannel'), 'stream'), channel(raw.get('network'), 'network')) if c]
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
        'channels': channels,
    }


def link(value):
    return value if isinstance(value, str) and re.match(r'https?://[^\s"<>]+$', value) else None


def channel(value, kind):
    """Where a show streams (a web channel such as Netflix) or airs (a network)."""
    if not isinstance(value, dict) or not isinstance(value.get('name'), str):
        return None
    return {'name': value['name'], 'kind': kind, 'site': link(value.get('officialSite'))}


def trim_videos(raw):
    """KinoCheck's official trailers, teasers and clips, trailer first, as YouTube ids."""
    if not isinstance(raw, dict):
        raise ValueError('not a KinoCheck answer')
    found = [raw['trailer']] if isinstance(raw.get('trailer'), dict) else []
    found += [v for v in raw.get('videos') or [] if isinstance(v, dict)]
    videos, seen = [], set()
    for v in found:
        youtube = v.get('youtube_video_id')
        if not isinstance(youtube, str) or not YOUTUBE_ID.fullmatch(youtube) or youtube in seen:
            continue
        seen.add(youtube)
        kinds = [c for c in v.get('categories') or [] if isinstance(c, str)]
        published = v.get('published') if isinstance(v.get('published'), str) else ''
        videos.append({'youtube': youtube, 'title': v['title'] if isinstance(v.get('title'), str) else '',
                       'kind': kinds[0] if kinds else 'Video', 'published': published[:10]})
    return videos[:12]


def trim_seasons(raw):
    """iTunes season listings: who made them, their age rating, year and store link."""
    if not isinstance(raw, dict) or not isinstance(raw.get('results'), list):
        raise ValueError('not an iTunes answer')
    out = []
    for r in raw['results']:
        if not isinstance(r, dict) or not isinstance(r.get('artistName'), str):
            continue
        date = r.get('releaseDate') if isinstance(r.get('releaseDate'), str) else ''
        store = link(r.get('collectionViewUrl'))
        out.append({'artist': r['artistName'], 'rating': r.get('contentAdvisoryRating'),
                    'title': r['collectionName'] if isinstance(r.get('collectionName'), str) else '',
                    'year': int(date[:4]) if date[:4].isdigit() else None,
                    'link': store if store and store.startswith(('https://itunes.apple.com/', 'https://tv.apple.com/')) else None})
    return out


def fold(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.casefold()).strip()


def match_rating(seasons, name, start, end):
    """The age rating for one show out of a name search. The name must match exactly and
    the seasons must fall within the show's run, which keeps a remake or a namesake from
    another country from lending its rating."""
    last = (end or 9999) + 1
    hits = [s for s in seasons if fold(s['artist']) == fold(name) and s['rating'] in AGES
            and s['year'] and (start or 0) - 1 <= s['year'] <= last]
    if not hits:
        return {'rating': None, 'apple': None}
    counts = {}
    for s in hits:
        counts[s['rating']] = counts.get(s['rating'], 0) + 1
    # The store link opens the earliest regular season, not a compilation or a box set.
    regular = re.compile(re.escape(fold(name)) + r' season (\d+)')
    numbered = [(int(m[1]), s['year'], s['link']) for s in hits if s['link']
                for m in [regular.fullmatch(fold(s.get('title', '')))] if m]
    links = [link for _n, _y, link in sorted(numbered)] or [s['link'] for s in sorted(hits, key=lambda s: -s['year']) if s['link']]
    return {'rating': max(counts, key=lambda r: (counts[r], AGES.index(r))), 'apple': links[0] if links else None}


def itunes_search(name):
    return '/search?' + urlencode({'term': name, 'media': 'tvShow', 'entity': 'tvSeason', 'limit': 50, 'country': 'US'})


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
    def __init__(self, fetch=None, base=API, ttl=6 * 3600, size=500, calls=15, period=10.0, clock=time.monotonic):
        self.fetch = fetch or self._http
        self.base, self.ttl, self.size, self.calls, self.period, self.clock = base, ttl, size, calls, period, clock
        self.cache = OrderedDict()
        self.sent = deque()
        self.pause = 0.0
        self.lock = threading.Lock()

    def _http(self, path):
        request = Request(self.base + path, headers={'User-Agent': AGENT, 'Accept': 'application/json'})
        with urlopen(request, timeout=6) as response:
            return json.load(response)

    def get(self, path, trim, missing=None):
        """A trimmed answer for path. With missing set, a 404 is an answer too, cached like
        any other, so a show with no trailer is not asked about again and again."""
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
                raise LiveError('That service is busy. Details will be back in a moment.', 503)
            self.sent.append(now)
        try:
            value = trim(self.fetch(path))
        except HTTPError as exc:
            if exc.code == 404 and missing is not None:
                value = missing
                with self.lock:
                    self.cache[path] = (self.clock() + self.ttl, value)
                return value
            if exc.code in (403, 429):
                with self.lock:
                    self.pause = self.clock() + (60 if exc.code == 403 else 10)
            if held:
                return held[1]
            if exc.code == 404:
                raise LiveError('TVmaze has no details for this show.', 404) from None
            if exc.code in (403, 429):
                raise LiveError('That service is busy. Details will be back in a moment.', 503) from None
            raise LiveError('That service could not be reached.') from None
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
            if held:
                return held[1]
            raise LiveError('That service could not be reached.') from None
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


class Icons:
    """Small service icons, fetched through DuckDuckGo's icon service and cached. The
    server only ever calls that one host, whatever host is asked about, so this
    cannot be pointed at anything else."""

    def __init__(self, fetch=None, size=300):
        self.fetch = fetch or self._http
        self.cache = OrderedDict()
        self.size = size
        self.lock = threading.Lock()

    @staticmethod
    def _http(host):
        request = Request(ICON.format(host=host), headers={'User-Agent': AGENT})
        with urlopen(request, timeout=5) as response:
            kind = response.headers.get_content_type()
            body = response.read(65537)
        if not kind.startswith('image/') or len(body) > 65536:
            raise ValueError('not a small image')
        return kind, body

    def get(self, host):
        host = host.lower().removeprefix('www.')
        if not HOST.fullmatch(host):
            raise ValueError('Send a host name such as netflix.com.')
        with self.lock:
            if host in self.cache:
                self.cache.move_to_end(host)
                return self.cache[host]
        try:
            value = self.fetch(host)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise LiveError('No icon for that host.', 404) from None
        with self.lock:
            self.cache[host] = value
            while len(self.cache) > self.size:
                self.cache.popitem(last=False)
        return value
