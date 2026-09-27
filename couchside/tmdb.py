"""TMDB's display data for shows, read once from the model's tmdb.json.gz.

The refresher fetches it from TMDB with each new model: the US age rating, where to
watch (JustWatch's data, which TMDB asks to be linked to its own watch page),
trailers and a widescreen backdrop, keyed by TVmaze show id. Title pages show it
ahead of the live sources; the ranking never sees it. A file that is missing or
cannot be read means no TMDB data, and the live sources carry on as before.
"""
import gzip
import json
import re
import sys
import zlib

IMAGE = 'https://image.tmdb.org/t/p/{size}{path}'
# Streaming first: a subscription, free, free with ads; then renting and buying.
KINDS = ('flatrate', 'free', 'ads', 'rent', 'buy')
RATINGS = ('TV-Y', 'TV-Y7', 'TV-Y7-FV', 'TV-G', 'TV-PG', 'TV-14', 'TV-MA')
IMAGE_PATH = re.compile(r'/[A-Za-z0-9_-]{1,100}\.(?:jpg|jpeg|png|svg|webp)')
YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')
WATCH_PAGE = re.compile(r'https://www\.themoviedb\.org/[^\s"<>\\]{1,200}')
SHOW_ID = re.compile(r'[1-9][0-9]{0,8}')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
VIDEO_ORDER = {'Trailer': 0, 'Teaser': 1}
MOST = 12           # pills, and videos


def image(size, path):
    """A TMDB image URL, only for a plain file path such as /abc.jpg."""
    return IMAGE.format(size=size, path=path) if isinstance(path, str) and IMAGE_PATH.fullmatch(path) else None


def providers(raw):
    """One entry per service with every way it offers the show, best first, and the
    services that stream it ahead of those that rent or sell it."""
    merged = {}
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict) or p.get('kind') not in KINDS or not isinstance(p.get('name'), str):
            continue
        name = ' '.join(p['name'].split())[:60]
        if not name:
            continue
        held = merged.setdefault(name, {'name': name, 'logo': None, 'kinds': []})
        held['logo'] = held['logo'] or image('w92', p.get('logo'))
        if p['kind'] not in held['kinds']:
            held['kinds'].append(p['kind'])
    for held in merged.values():
        held['kinds'].sort(key=KINDS.index)
    return sorted(merged.values(), key=lambda p: KINDS.index(p['kinds'][0]))[:MOST]


def videos(raw):
    """Trailers in the shape the page plays: official ones first, trailers before teasers
    before anything else, newest first within each."""
    found, seen = [], set()
    for v in raw if isinstance(raw, list) else []:
        key = v.get('key') if isinstance(v, dict) else None
        if not isinstance(key, str) or not YOUTUBE_ID.fullmatch(key) or key in seen:
            continue
        seen.add(key)
        kind = v['type'].strip()[:40] if isinstance(v.get('type'), str) and v['type'].strip() else 'Video'
        day = v.get('published') if isinstance(v.get('published'), str) else ''
        found.append(({'youtube': key, 'title': v['name'][:200] if isinstance(v.get('name'), str) else '',
                       'kind': kind, 'published': day[:10] if DAY.match(day) else ''}, v.get('official') is True))
    found.sort(key=lambda f: f[0]['published'], reverse=True)
    found.sort(key=lambda f: (not f[1], VIDEO_ORDER.get(f[0]['kind'], 2)))
    return [video for video, _official in found[:MOST]]


def trim(entry, region='US'):
    """What a title page shows from one show's entry, or None when it offers nothing."""
    if not isinstance(entry, dict):
        return None
    tmdb_id = entry['tmdb_id'] if type(entry.get('tmdb_id')) is int and entry['tmdb_id'] > 0 else None
    link = entry.get('watch_link')
    if not (isinstance(link, str) and WATCH_PAGE.fullmatch(link)):
        link = f'https://www.themoviedb.org/tv/{tmdb_id}/watch?locale={region}' if tmdb_id else None
    block = {
        'rating': entry.get('rating') if entry.get('rating') in RATINGS else None,
        'link': link,
        # JustWatch's data may only be shown linked to TMDB's watch page, so none without one.
        'providers': providers(entry.get('providers')) if link else [],
        'videos': videos(entry.get('trailers')),
        'backdrop': image('w1280', entry.get('backdrop')),
    }
    return block if block['rating'] or block['providers'] or block['videos'] or block['backdrop'] else None


def load(path, known=None):
    """Show id to what its title page shows, for the ids in known when given. Empty,
    never an error, when the file is missing or cannot be read."""
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, EOFError, ValueError, RecursionError, zlib.error) as exc:
        print(f'Ignoring {path}: {exc}', file=sys.stderr, flush=True)
        return {}
    shows = raw.get('shows') if isinstance(raw, dict) else None
    if not isinstance(shows, dict):
        print(f'Ignoring {path}: it lists no shows', file=sys.stderr, flush=True)
        return {}
    region = raw['region'] if isinstance(raw.get('region'), str) and re.fullmatch(r'[A-Z]{2}', raw['region']) else 'US'
    found = {}
    for key, entry in shows.items():
        if not (isinstance(key, str) and SHOW_ID.fullmatch(key)):
            continue
        show_id = int(key)
        if known is not None and show_id not in known:
            continue
        block = trim(entry, region)
        if block:
            found[show_id] = block
    return found
