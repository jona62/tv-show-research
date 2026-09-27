"""Check Couchside's shelves, title pages, live details, TMDB data and server.

Run from the repository root:  .venv/bin/python couchside/test_couchside.py
Nothing here reaches TVmaze, TMDB or anything else: live clients are driven by fakes,
and the server reads a temporary model laid out the way the refresher leaves one.
"""
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from functools import partial
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import atexit
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'couchside'))

# A model the way the refresher leaves one: a version directory with build.json written
# last, and a current link to it. It is the repository's model dated a day later, with
# one poster moved and TMDB data for a few shows, so whatever the server shows from it
# can only have come from MODEL_DIR.
TMP = Path(tempfile.mkdtemp(prefix='couchside-test-'))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
VERSION = TMP / 'versions' / '2026-09-08T040000Z'
VERSION.mkdir(parents=True)
with gzip.open(ROOT / 'model' / 'catalog.json.gz', 'rt') as f:
    catalog = json.load(f)
FROZEN_DATE = catalog['date']
MODEL_DATE = catalog['date'] = (date.fromisoformat(FROZEN_DATE) + timedelta(days=1)).isoformat()
with gzip.open(VERSION / 'catalog.json.gz', 'wt', compresslevel=1) as f:
    json.dump(catalog, f, separators=(',', ':'))
position = {s['id']: n for n, s in enumerate(catalog['shows'])}
del catalog
for name in ('vectors.bin.gz', 'popularity.bin.gz'):
    try:
        os.link(ROOT / 'model' / name, VERSION / name)
    except OSError:
        shutil.copyfile(ROOT / 'model' / name, VERSION / name)
MOVED_POSTER = 987654
with gzip.open(ROOT / 'couchside' / 'art.bin.gz', 'rb') as f:
    art_track = bytearray(f.read())
struct.pack_into('<I', art_track, 8 + 4 * position[2993], MOVED_POSTER)
with gzip.open(VERSION / 'art.bin.gz', 'wb') as f:
    f.write(art_track)
TMDB_FILE = {'fetched_at': '2026-09-08T04:10:00Z', 'region': 'US', 'shows': {
    # Stranger Things: everything, with junk to drop and one service twice.
    '2993': {'tmdb_id': 66732, 'fetched_at': '2026-09-08T04:10:00Z', 'rating': 'TV-14',
             'watch_link': 'https://www.themoviedb.org/tv/66732/watch?locale=US',
             'providers': [{'name': 'Apple TV', 'logo': '/apple.jpg', 'kind': 'buy'},
                           {'name': 'Netflix', 'logo': '/netflix.jpg', 'kind': 'flatrate'},
                           {'name': 'Apple TV', 'logo': '/apple.jpg', 'kind': 'rent'},
                           {'name': 'Tubi', 'logo': '/tubi.jpg', 'kind': 'ads'},
                           {'name': 'Odd One', 'logo': 'javascript:alert(1)', 'kind': 'flatrate'},
                           {'name': 'Cinema', 'logo': '/c.jpg', 'kind': 'theatre'}, {'kind': 'buy'}, 'junk'],
             'trailers': [{'key': 'TEASER00001', 'name': 'Teaser', 'type': 'Teaser', 'official': True, 'published': '2016-07-01'},
                          {'key': 'TRAILER0001', 'name': 'Season 1 Trailer', 'type': 'Trailer', 'official': True,
                           'published': '2016-07-07T12:00:00.000Z'},
                          {'key': 'FANMADE0001', 'name': 'Fan trailer', 'type': 'Trailer', 'official': False, 'published': '2025-01-01'},
                          {'key': 'TRAILER0005', 'name': 'Season 5 Trailer', 'type': 'Trailer', 'official': True, 'published': '2025-10-30'},
                          {'key': 'not a key!', 'name': 'Broken', 'type': 'Trailer', 'official': True},
                          {'key': 'TRAILER0001', 'name': 'Again', 'type': 'Trailer', 'official': True}],
             'backdrop': '/stranger.jpg', 'vote_average': 8.6, 'vote_count': 19000},
    # Game of Thrones: a rating, and nowhere to watch.
    '82': {'tmdb_id': 1399, 'rating': 'TV-MA', 'watch_link': None, 'providers': [], 'trailers': [], 'backdrop': None},
    # Severance: a backdrop, a rating TV does not use and a link that is not TMDB's.
    '44933': {'tmdb_id': 95396, 'rating': 'NR', 'watch_link': 'javascript:alert(1)', 'providers': [], 'trailers': [],
              'backdrop': '/severance.jpg'},
    # The Office: a service, but no TMDB page to link it to, so nothing at all.
    '526': {'rating': None, 'watch_link': None, 'providers': [{'name': 'Peacock', 'logo': '/p.jpg', 'kind': 'flatrate'}]},
    '999999999': {'tmdb_id': 1, 'rating': 'TV-G'},
    'Breaking Bad': {'tmdb_id': 1396, 'rating': 'TV-MA'},
}}
with gzip.open(VERSION / 'tmdb.json.gz', 'wt') as f:
    json.dump(TMDB_FILE, f)
(VERSION / 'build.json').write_text(json.dumps({
    'version': VERSION.name, 'built_at': '2026-09-08T04:20:00Z', 'snapshot_date': MODEL_DATE, 'shows': len(position),
    'pipeline': 'test', 'seeded_from': None, 'tmdb': {'fetched_at': TMDB_FILE['fetched_at'], 'shows': 3}}))
os.symlink(VERSION.relative_to(TMP), TMP / 'current')
os.environ['MODEL_DIR'] = str(TMP / 'current')

import server                                                    # noqa: E402
import follow                                                    # noqa: E402
import tmdb                                                      # noqa: E402
from engine import DEFAULT_SETTINGS                              # noqa: E402
from library import ROW, MORE, GLANCE, SHORTEST, GENRE_ROWS, NEW_DAYS, lower_first  # noqa: E402
from live import (Live, LiveError, Icons, trim_show, trim_episodes, trim_videos,        # noqa: E402
                  trim_seasons, match_rating, IMAGES)

engine, lib = server.ENGINE, server.LIBRARY
PROFILE = [{'id': 169, 'weight': 1}, {'id': 82, 'weight': .7}, {'id': 44933, 'weight': 1},
           {'id': 269, 'weight': .7}, {'id': 80, 'weight': -1}]
RATED = {p['id'] for p in PROFILE}
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def rejects(label, fn, said):
    try:
        fn()
        check(f'rejects {label}', False)
    except ValueError as exc:
        check(f'rejects {label}', said in str(exc), str(exc))


# 1. One engine for both apps.
check('the engine is Next Watch\'s, unchanged',
      (ROOT / 'app' / 'engine.py').read_bytes() == (ROOT / 'couchside' / 'engine.py').read_bytes())
check('so is the model follower',
      (ROOT / 'app' / 'follow.py').read_bytes() == (ROOT / 'couchside' / 'follow.py').read_bytes())
check('and the taste model',
      (ROOT / 'app' / 'taste.py').read_bytes() == (ROOT / 'couchside' / 'taste.py').read_bytes())
check('and the facet reader',
      (ROOT / 'app' / 'facets.py').read_bytes() == (ROOT / 'couchside' / 'facets.py').read_bytes())

# 1b. Icons at the sizes each platform asks for.
def png_size(path):
    head = (ROOT / 'couchside' / 'public' / path).read_bytes()[:24]
    return (int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')) if head[:8] == b'\x89PNG\r\n\x1a\n' else None


check('icons are the sizes they claim', png_size('apple-touch-icon.png') == (180, 180) and png_size('icon-192.png') == (192, 192)
      and png_size('icon-512.png') == (512, 512) and png_size('icon-maskable-512.png') == (512, 512))
ico = (ROOT / 'couchside' / 'public' / 'favicon.ico').read_bytes()
check('favicon.ico holds 16, 32 and 48 pixel images', ico[:4] == b'\x00\x00\x01\x00' and int.from_bytes(ico[4:6], 'little') == 3
      and sorted(ico[6 + 16 * n] for n in range(3)) == [16, 32, 48])
check('the Apple icon has no transparent corners', (lambda b: b[25] in (2, 6))((ROOT / 'couchside' / 'public' / 'apple-touch-icon.png').read_bytes()))

# 2. The art track lines up with the catalog.
poster = lib.poster(engine.by_id[169])
check('posters rebuild to TVmaze image URLs',
      bool(re.fullmatch(r'https://static\.tvmaze\.com/uploads/images/medium_portrait/\d+/\d+\.jpg', poster or '')), poster)
check('originals share the id and bucket', lib.poster(engine.by_id[169], 'original_untouched') == poster.replace('medium_portrait', 'original_untouched'))
check('most shows have a poster', sum(1 for i in lib.images if i) / engine.n > .85)
check('an ended show knows when it ended', lib.ended[engine.by_id[169]] >= 2013)

# 2b. Everything comes from the model MODEL_DIR leads to: its catalog, its posters and its
# TMDB data. The frozen layout, a plain directory, carries no posters and uses ours.
IMAGE_URL = 'https://image.tmdb.org/t/p/'
check('the server reads the version the link leads to', server.MODEL == Path(os.path.realpath(VERSION)))
check('the catalog is that model\'s', engine.date == MODEL_DATE != FROZEN_DATE)
check('posters come from that model\'s art',
      lib.poster(engine.by_id[2993]).endswith(f'/{MOVED_POSTER // 2500}/{MOVED_POSTER}.jpg'))
check('a model without art uses the copy kept here', server.art_file(ROOT / 'model') == ROOT / 'couchside' / 'art.bin.gz'
      and server.art_file(server.MODEL) == server.MODEL / 'art.bin.gz')

# 2c. TMDB's data, trimmed to what a title page shows and never a reason to fail.
known = server.TMDB
check('TMDB data loads for the catalog\'s shows that have some', sorted(known) == [82, 2993, 44933], sorted(known))
things = known[2993]
check('services are merged, streaming first, with TMDB\'s logos', things['providers'] == [
    {'name': 'Netflix', 'logo': IMAGE_URL + 'w92/netflix.jpg', 'kinds': ['flatrate']},
    {'name': 'Odd One', 'logo': None, 'kinds': ['flatrate']},
    {'name': 'Tubi', 'logo': IMAGE_URL + 'w92/tubi.jpg', 'kinds': ['ads']},
    {'name': 'Apple TV', 'logo': IMAGE_URL + 'w92/apple.jpg', 'kinds': ['rent', 'buy']}], things['providers'])
check('official trailers lead, trailers before teasers, newest first',
      [v['youtube'] for v in things['videos']] == ['TRAILER0005', 'TRAILER0001', 'TEASER00001', 'FANMADE0001'])
check('trailers take the shape the page plays', things['videos'][1] == {
    'youtube': 'TRAILER0001', 'title': 'Season 1 Trailer', 'kind': 'Trailer', 'published': '2016-07-07'})
check('the rating, watch page and backdrop come through', things['rating'] == 'TV-14'
      and things['link'] == 'https://www.themoviedb.org/tv/66732/watch?locale=US'
      and things['backdrop'] == IMAGE_URL + 'w1280/stranger.jpg')
check('a show without a usable watch link gets TMDB\'s own',
      known[82]['link'] == 'https://www.themoviedb.org/tv/1399/watch?locale=US'
      and known[44933]['link'] == 'https://www.themoviedb.org/tv/95396/watch?locale=US')
check('a rating TV does not use counts as none', known[44933]['rating'] is None and known[82]['rating'] == 'TV-MA')
check('every TMDB image comes from TMDB\'s image server', all(
    url.startswith(IMAGE_URL) for block in known.values()
    for url in [block['backdrop'], *(p['logo'] for p in block['providers'])] if url))
bad = TMP / 'bad'
bad.mkdir()
(bad / 'plain.json.gz').write_bytes(b'not gzip at all')
(bad / 'cut.json.gz').write_bytes(gzip.compress(json.dumps(TMDB_FILE).encode())[:200])
for name, text in (('text', '{"shows": '), ('list', '[1, 2]'), ('shows', '{"shows": [1, 2]}'),
                   ('deep', '[' * 100_000 + ']' * 100_000)):
    (bad / f'{name}.json.gz').write_bytes(gzip.compress(text.encode()))
said = io.StringIO()
with contextlib.redirect_stderr(said):
    for name, what in (('missing', 'no TMDB file'), ('plain', 'a TMDB file that is not gzip'), ('cut', 'a cut-off TMDB file'),
                       ('text', 'a TMDB file of broken JSON'), ('list', 'a TMDB file holding a list'),
                       ('shows', 'a TMDB file whose shows are a list'), ('deep', 'a TMDB file nested too deep')):
        check(f'{what} means no TMDB data, not a failure', tmdb.load(bad / f'{name}.json.gz', engine.by_id) == {})
check('each unreadable one says so, and a missing one does not', said.getvalue().count('Ignoring') == 6, said.getvalue())

# 3. A first visit gets rows without any ratings.
cold = lib.home({'profile': [], 'settings': {}})
check('a first visit is not personal', cold['personal'] is False and cold['hero']['because'] is None)
check('a first visit still gets full rows', len(cold['rows']) >= 8 and all(len(r['items']) >= SHORTEST for r in cold['rows']))
check('top 10 holds ten current shows', len(cold['top10']) == 10 and all(c['year'] >= lib.year - 5 for c in cold['top10']))
check('every card on a first visit has a poster', all(c['poster'] for r in cold['rows'] for c in r['items']))
check('no match is claimed without ratings', all(c['match'] is None for r in cold['rows'] for c in r['items']))
check('the hero leads the top 10', cold['hero']['id'] == cold['top10'][0]['id'])
check('coming soon is dated after the snapshot', cold['soon'] and all(c['premiered'] > engine.date for c in cold['soon']))
check('starters are recognisable and many', len(lib.starters) >= 30 and lib.starters[0]['id'] == 169)

# 4. A rated list gets rows built from it.
home = lib.home({'profile': PROFILE, 'settings': {}, 'list': [526, 999_999_999, 431]})
rows = {r['key']: r for r in home['rows']}
reference = engine.calculate({'profile': PROFILE, 'settings': {}})
check('a rated list is personal', home['personal'] is True)
check('top picks rank exactly as Next Watch does',
      [c['id'] for c in rows['top']['items']] == [p['id'] for p in reference['picks'][:ROW]])
check('the hero is the best pick at 99', home['hero']['id'] == reference['picks'][0]['id'] and home['hero']['match'] == 99)
check('the hero says which show it came from', home['hero']['because']['id'] in RATED and home['hero']['because']['name'])
personal = [r for r in home['rows'] if r['key'] != 'top10']
check('nothing rated comes back in a row', not RATED & {c['id'] for r in personal for c in r['items']})
check('matches sit between 1 and 99', all(c['match'] is None or 1 <= c['match'] <= 99 for r in home['rows'] for c in r['items']))
seeds = [r['title'] for r in home['rows'] if r['key'].startswith('seed-')]
positives = [p for p in PROFILE if p['weight'] > 0]
negatives = [p for p in PROFILE if p['weight'] < 0]
closeness = {p['id']: engine.blend(engine.by_id[p['id']], engine.validate({'profile': PROFILE})[1]) for p in PROFILE}
interests = engine.ranking(positives, negatives, closeness, engine.validate({'profile': PROFILE})[1]).interests
owner = {p['id']: n for n, group in enumerate(interests) for p in group}
seed_owners = [owner[int(r['key'][5:])] for r in home['rows'] if r['key'].startswith('seed-')]
check('seed rows take one show from each interest, heaviest first',
      seed_owners[:len(interests)] == list(range(min(len(interests), len(seed_owners)))), seeds)
check('a loved show fronts the heaviest interest', seeds[0] == 'Because you loved Breaking Bad', seeds)
check('a liked seed says liked', any(t == 'Because you liked Peaky Blinders' for t in seeds), seeds)
for r in home['rows']:
    if r['key'].startswith('genre-'):
        genre = next(g for g, title in GENRE_ROWS.items() if title == r['title'])
        check(f'{r["title"]} holds only {genre}', all(genre in engine.shows[engine.by_id[c["id"]]]['genres'] for c in r['items']))
check('new for you is new', all(c['year'] >= lib.year - 1 for c in rows['new']['items']))
fresh_rows = [r for r in home['rows'] if r['key'] not in ('top10', 'popular')]
openers = [c['id'] for r in fresh_rows for c in r['items'][:GLANCE]]
check('rows open with shows no earlier row opened with', len(openers) == len(set(openers)))
check('rows hold no repeats inside themselves', all(len({c['id'] for c in r['items']}) == len(r['items']) for r in home['rows']))
check('My List comes back in order, unknown ids dropped', [c['id'] for c in home['list']] == [526, 431])
check('My List carries matches', all(c['match'] is None or 1 <= c['match'] <= 99 for c in home['list']))
check('an empty pool says so', lib.home({'profile': PROFILE, 'settings': {'year_min': 2100}})['message'] != '')
rejects('a list that is not a list', lambda: lib.home({'profile': [], 'list': 5}), 'My List')
rejects('an oversized list', lambda: lib.home({'profile': [], 'list': list(range(1, 202))}), 'up to 200')
rejects('a list of strings', lambda: lib.home({'profile': [], 'list': ['169']}), 'whole numbers')
rejects('a bad rating', lambda: lib.home({'profile': [{'id': 169, 'weight': 2}]}), 'rating')

# 4b. Badges, and browsing by genre or format.
genres_of = lambda c: engine.shows[engine.by_id[c['id']]]['genres']
check('top 10 cards wear their badge', all(c['badge'] == 'top10' for c in cold['top10']))
news = [c for r in cold['rows'] for c in r['items'] if c['badge'] == 'new']
snapshot = date.fromisoformat(engine.date)
check('new badges go only to recent premieres', news and all(
    0 <= (snapshot - date.fromisoformat(engine.shows[engine.by_id[c['id']]]['premiered'])).days <= NEW_DAYS for c in news))
crime = lib.browse({'profile': PROFILE, 'settings': {}, 'genre': 'Crime'})
check('browsing a genre keeps to it', crime['rows'] and all('Crime' in genres_of(c) for r in crime['rows'] for c in r['items']))
check('browsing is personal once rated', crime['personal'] and crime['rows'][0]['title'] == 'Top crime TV shows for you')
check('browsing leaves rated shows out', not RATED & {c['id'] for r in crime['rows'] for c in r['items']})
check('browse rows open without repeating each other',
      len([c['id'] for r in crime['rows'] for c in r['items'][:GLANCE]]) == len({c['id'] for r in crime['rows'] for c in r['items'][:GLANCE]}))
cartoons = lib.browse({'profile': [], 'settings': {}, 'genre': 'animation'})
check('formats browse too', not cartoons['personal'] and cartoons['rows']
      and all(engine.shows[engine.by_id[c['id']]]['type'] == 'Animation' for r in cartoons['rows'] for c in r['items']))
rejects('an unknown genre', lambda: lib.browse({'profile': [], 'genre': 'Klingon'}), 'Choose a genre')
rejects('a missing genre', lambda: lib.browse({'profile': []}), 'Choose a genre')
check('every browsable genre has a poster for its tile', len(lib.genres) >= 20 and all(g['poster'] for g in lib.genres))
check('no two genre tiles share a poster', len({g['poster'] for g in lib.genres}) == len(lib.genres))
check('labels lower-case without breaking acronyms',
      lower_first('Crime TV shows') == 'crime TV shows' and lower_first('DIY and makeovers') == 'DIY and makeovers')

# 5. A title page explains itself and finds what is like it.
page = lib.title({'profile': PROFILE, 'settings': {}, 'id': reference['picks'][0]['id']})
check('a title page carries its details', {'summary', 'genres', 'themes', 'art', 'poster', 'channel'} <= set(page['show']))
check('the best pick is a 99 match', page['show']['match'] == 99)
check('a title names the liked show it sits closest to',
      page['show']['because']['id'] in RATED and page['show']['because']['name'])
more_ids = [c['id'] for c in page['more']]
check('more like this holds up to twelve', 0 < len(more_ids) <= MORE)
check('more like this leaves out the show itself and anything rated',
      page['show']['id'] not in more_ids and not RATED & set(more_ids))
check('more like this carries summaries', all('summary' in c for c in page['more']))
check('a rated title does not explain itself', lib.title({'profile': PROFILE, 'settings': {}, 'id': 169})['show']['because'] is None)
bare = lib.title({'profile': [], 'settings': {}, 'id': 169})
check('a title works with nothing rated', bare['show']['match'] is None and bare['more'])
soon_id = cold['soon'][0]['id']
check('an upcoming show opens too', lib.title({'profile': PROFILE, 'settings': {}, 'id': soon_id})['show']['id'] == soon_id)
rejects('an unknown title', lambda: lib.title({'profile': [], 'id': 999_999_999}), 'not in this catalog')
rejects('a title id that is a string', lambda: lib.title({'profile': [], 'id': '169'}), 'not in this catalog')

# 6. Live details: trimmed, cached, and polite to TVmaze.
RAW = {
    'status': 'Ended', 'ended': '2013-09-29', 'officialSite': 'http://www.amc.com/x', 'externals': {'imdb': 'tt0903747'},
    'schedule': {'days': ['Sunday'], 'time': '22:00'},
    '_embedded': {
        'seasons': [{'id': 753, 'number': 1, 'episodeOrder': 7, 'premiereDate': '2008-01-20'},
                    {'id': 754, 'number': 2, 'episodeOrder': 13, 'premiereDate': '2009-03-08'}, {'id': 'x'}],
        'cast': [{'person': {'name': 'Bryan Cranston', 'image': {'medium': IMAGES + 'medium_portrait/1/2.jpg'}},
                  'character': {'name': 'Walter White'}},
                 {'person': {'name': 'Aaron Paul', 'image': {'medium': 'https://evil.example/x.jpg'}}, 'character': {}}],
        'images': [{'type': 'background', 'main': False, 'resolutions': {'original': {'url': IMAGES + 'o/1/9.jpg'}}},
                   {'type': 'background', 'main': True, 'resolutions': {'original': {'url': IMAGES + 'o/1/8.jpg'}}},
                   {'type': 'poster', 'main': True, 'resolutions': {'original': {'url': IMAGES + 'o/1/7.jpg'}}}],
    },
}
shape = trim_show(RAW)
check('live seasons keep what is valid', [(s['number'], s['episodes'], s['year']) for s in shape['seasons']] == [(1, 7, 2008), (2, 13, 2009)])
check('live cast keeps names and characters', [(c['name'], c['character']) for c in shape['cast']] == [('Bryan Cranston', 'Walter White'), ('Aaron Paul', '')])
check('images from anywhere but TVmaze are dropped', shape['cast'][1]['photo'] is None and shape['cast'][0]['photo'])
check('the main backdrop wins', shape['backdrop'] == IMAGES + 'o/1/8.jpg')
check('the IMDb id and site survive', shape['imdb'] == 'tt0903747' and shape['site'] == 'http://www.amc.com/x')
check('a bad IMDb id is dropped', trim_show({**RAW, 'externals': {'imdb': 'javascript:x'}})['imdb'] is None)
episodes = trim_episodes([{'number': 1, 'name': 'Pilot', 'runtime': 58, 'airdate': '2008-01-20',
                           'image': {'medium': IMAGES + 'medium_landscape/1/3.jpg'}, 'summary': '<p>A &amp; B <b>go</b>.</p>'},
                          {'number': None, 'name': 'Special', 'runtime': None, 'summary': None}, 'junk'])
check('episode summaries lose their HTML', episodes[0]['summary'] == 'A & B go.')
check('specials are kept and junk dropped', len(episodes) == 2 and episodes[1]['number'] is None)

check('where it streams and where it airs are both kept',
      trim_show({**RAW, 'webChannel': {'name': 'Netflix', 'officialSite': 'https://www.netflix.com/'},
                 'network': {'name': 'AMC', 'officialSite': 'javascript:alert(1)'}})['channels']
      == [{'name': 'Netflix', 'kind': 'stream', 'site': 'https://www.netflix.com/'},
          {'name': 'AMC', 'kind': 'network', 'site': None}])
videos = trim_videos({'trailer': {'youtube_video_id': 'AAAAAAAAAAA', 'title': 'Trailer', 'categories': ['Trailer'],
                                  'published': '2025-01-02T10:00:00+01:00'},
                      'videos': [{'youtube_video_id': 'AAAAAAAAAAA'}, {'youtube_video_id': 'bad id!'},
                                 {'youtube_video_id': 'BBBBBBBBBBB', 'categories': ['Clip']}, 'junk']})
check('the chosen trailer leads and repeats go', [v['youtube'] for v in videos] == ['AAAAAAAAAAA', 'BBBBBBBBBBB'])
check('videos carry kind and date', videos[0]['kind'] == 'Trailer' and videos[0]['published'] == '2025-01-02'
      and videos[1]['kind'] == 'Clip')
seasons = trim_seasons({'results': [
    {'artistName': 'The Office', 'contentAdvisoryRating': 'TV-14', 'releaseDate': '2009-09-17T07:00:00Z',
     'collectionViewUrl': 'https://itunes.apple.com/us/tv-season/a/id1'},
    {'artistName': 'The Office', 'contentAdvisoryRating': 'TV-14', 'releaseDate': '2012-09-20T07:00:00Z',
     'collectionViewUrl': 'https://itunes.apple.com/us/tv-season/b/id2'},
    {'artistName': 'The Office', 'contentAdvisoryRating': 'TV-PG', 'releaseDate': '2006-01-01T00:00:00Z',
     'collectionViewUrl': 'https://evil.example/x'},
    {'artistName': 'Not The Office', 'contentAdvisoryRating': 'TV-G', 'releaseDate': '2010-01-01T00:00:00Z'}, 'junk']})
check('the commonest rating in the run wins, with the newest store link when no season is numbered',
      match_rating(seasons, 'The Office', 2005, 2013) == {'rating': 'TV-14', 'apple': 'https://itunes.apple.com/us/tv-season/b/id2'})
check('store links elsewhere are dropped', [x['link'] for x in seasons][2] is None)
boxed = trim_seasons({'results': [
    {'artistName': 'Breaking Bad', 'collectionName': 'Breaking Bad, Deluxe Edition: Seasons 1-2', 'contentAdvisoryRating': 'TV-MA',
     'releaseDate': '2013-01-01T00:00:00Z', 'collectionViewUrl': 'https://itunes.apple.com/us/tv-season/deluxe/id9'},
    {'artistName': 'Breaking Bad', 'collectionName': 'Breaking Bad, Season 2', 'contentAdvisoryRating': 'TV-MA',
     'releaseDate': '2009-03-08T00:00:00Z', 'collectionViewUrl': 'https://itunes.apple.com/us/tv-season/s2/id2'},
    {'artistName': 'Breaking Bad', 'collectionName': 'Breaking Bad, Season 1', 'contentAdvisoryRating': 'TV-MA',
     'releaseDate': '2008-01-20T00:00:00Z', 'collectionViewUrl': 'https://itunes.apple.com/us/tv-season/s1/id1'}]})
check('the store link opens season one, not a box set',
      match_rating(boxed, 'Breaking Bad', 2008, 2013)['apple'] == 'https://itunes.apple.com/us/tv-season/s1/id1')
check('a namesake outside the run lends nothing', match_rating(seasons, 'The Office', 1990, 1995)['rating'] is None)
check('a running show matches up to now', match_rating(seasons, 'The Office', 2005, None)['rating'] == 'TV-14')
check('unknown rating codes are ignored',
      match_rating([{'artist': 'X', 'rating': 'NR', 'year': 2010, 'link': None}], 'X', 2010, None)['rating'] is None)

now = [0.0]
calls = []


def fake(path):
    calls.append(path)
    if path.startswith('/seasons/'):
        return [{'number': 1, 'name': 'Pilot'}]
    return RAW


live = Live(fetch=fake, ttl=60, calls=3, period=10, clock=lambda: now[0])
live.show(169)
live.show(169)
check('a second look is served from cache', len(calls) == 1)
check('episodes find their season', live.episodes(169, 2)[0]['name'] == 'Pilot' and calls[-1] == '/seasons/754/episodes')
try:
    live.episodes(169, 9)
    check('an unknown season is refused', False)
except LiveError as exc:
    check('an unknown season is refused', exc.status == 404)
now[0] = 100.0


def failing(path):
    raise HTTPError(path, 500, 'boom', {}, None)


live.fetch = failing
check('a stale answer beats none when TVmaze fails', live.show(169)['backdrop'] == IMAGES + 'o/1/8.jpg')
limited = Live(fetch=lambda p: (_ for _ in ()).throw(HTTPError(p, 429, 'slow down', {}, None)), clock=lambda: now[0])
try:
    limited.show(1)
    check('a 429 is reported as busy', False)
except LiveError as exc:
    check('a 429 is reported as busy', exc.status == 503)
check('a 429 pauses further calls', limited.pause > now[0])
missing = Live(fetch=lambda p: (_ for _ in ()).throw(HTTPError(p, 404, 'gone', {}, None)), clock=lambda: now[0])
try:
    missing.show(1)
    check('a show TVmaze lacks is a 404', False)
except LiveError as exc:
    check('a show TVmaze lacks is a 404', exc.status == 404)
window = Live(fetch=lambda p: RAW, calls=2, period=10, clock=lambda: now[0])
window.show(1)
window.show(2)
try:
    window.show(3)
    check('calls stay inside the rate window', False)
except LiveError as exc:
    check('calls stay inside the rate window', exc.status == 503)

misses = []


def nothing(path):
    misses.append(path)
    raise HTTPError(path, 404, 'none', {}, None)


kino = Live(fetch=nothing, clock=lambda: now[0])
check('a 404 can be an answer', kino.get('/shows?imdb_id=tt1', trim_videos, missing=[]) == [])
kino.get('/shows?imdb_id=tt1', trim_videos, missing=[])
check('and is not asked about again', len(misses) == 1)
icon_calls = []
icons = Icons(fetch=lambda host: icon_calls.append(host) or ('image/png', b'png'))
check('icons are fetched once per host', icons.get('www.Netflix.com') == icons.get('netflix.com') and icon_calls == ['netflix.com'])
for bad in ('localhost', '127.0.0.1', 'netflix.com/x', 'a b.com', '', 'x' * 300 + '.com'):
    try:
        icons.get(bad)
        check(f'icon host {bad[:20]!r} is refused', False)
    except ValueError:
        check(f'icon host {bad[:20]!r} is refused', True)

# 7. The server end to end, with every outside service faked.
asked = {'kino': [], 'store': []}
# iTunes seasons by a word of the name searched for. Game of Thrones's rating here differs
# from TMDB's on purpose, so an answer shows which source it came from.
SEASONS = {
    'Breaking': ('Breaking Bad', 'TV-MA', '2012-07-15T07:00:00Z',
                 'https://itunes.apple.com/us/tv-season/breaking-bad-season-5/id533936970'),
    'Thrones': ('Game of Thrones', 'TV-14', '2011-04-17T07:00:00Z',
                'https://itunes.apple.com/us/tv-season/game-of-thrones-season-1/id1'),
    'Severance': ('Severance', 'TV-MA', '2022-02-18T07:00:00Z', 'https://itunes.apple.com/us/tv-season/severance-season-1/id2'),
}


def kinocheck(path):
    asked['kino'].append(path)
    return ({'trailer': {'youtube_video_id': 'CCCCCCCCCCC', 'categories': ['Trailer']}}
            if 'tt0903747' in path else {'trailer': None, 'videos': []})


def itunes(path):
    asked['store'].append(path)
    return {'results': [{'artistName': name, 'contentAdvisoryRating': rating, 'releaseDate': day, 'collectionViewUrl': link}
                        for word, (name, rating, day, link) in SEASONS.items() if word in path]}


server.LIVE = Live(fetch=fake)
server.KINO = Live(fetch=kinocheck)
server.STORE = Live(fetch=itunes)
server.ICONS = Icons(fetch=lambda host: ('image/png', b'\x89PNG fake'))
httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.PUBLIC)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{httpd.server_address[1]}'


def fetch(path, body=None, kind='application/json', headers=None, method=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    request = Request(base + path, data=data, method=method,
                      headers={**({'Content-Type': kind} if data is not None else {}), **(headers or {})})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


status, headers, page_root = fetch('/')
check('the page is served', status == 200 and b'id="boot"' in page_root)
policy = headers.get('Content-Security-Policy', '')
check('images come only from TVmaze, YouTube thumbnails and TMDB',
      "img-src 'self' data: https://static.tvmaze.com https://i.ytimg.com https://image.tmdb.org;" in policy)
check('trailers play only in the no-cookie player', "frame-src https://www.youtube-nocookie.com;" in policy)
check('no referrer goes to the image server', headers.get('Referrer-Policy') == 'no-referrer')
for path in ('/new', '/list', '/search', '/browse', '/welcome'):
    status, _headers, body = fetch(path)
    check(f'{path} is the page too', status == 200 and body == page_root)
status, headers, body = fetch('/nope')
check('an unknown path is a 404 with the app\'s own page', status == 404 and b'Lost your way?' in body
      and headers.get('Content-Type', '').startswith('text/html'))
check('a trailing slash leads nowhere too', fetch('/list/')[0] == 404)
check('an unknown api path stays JSON', fetch('/api/nope')[2].startswith(b'{'))
status, headers, body = fetch('/nope', method='HEAD')
check('a HEAD for nothing is a bodiless 404', status == 404 and body == b'')
status, headers, body = fetch('/', method='HEAD')
check('a HEAD for the page answers without a body', status == 200 and body == b'' and int(headers['Content-Length']) > 1000)
check('the page links its icons and manifest', all(tag in page_root for tag in (
    b'rel="manifest" href="/manifest.webmanifest"', b'rel="apple-touch-icon" href="/apple-touch-icon.png"',
    b'href="/favicon.ico"', b'name="apple-mobile-web-app-capable" content="yes"')))
check('no build placeholder survives', not re.search(rb'__[A-Z_]+__', page_root))
check('the home preview uses the share image at this address',
      f'content="{base}/og.jpg"'.encode() in page_root and b'content="summary_large_image"' in page_root)
status, _headers, titled = fetch('/?show=169')
art = lib.poster(engine.by_id[169], 'original_untouched')
check('a shared title previews itself', status == 200 and b'content="Breaking Bad (2008) on Couchside"' in titled
      and f'content="{art}"'.encode() in titled and b'<title>Breaking Bad \xc2\xb7 Couchside</title>' in titled
      and f'content="{base}/?show=169"'.encode() in titled)
tricky = next(i for i, show in enumerate(engine.shows) if '&' in show['name'] and '"' not in show['name'] and show['recommendable'])
tricky_id, tricky_name = engine.shows[tricky]['id'], engine.shows[tricky]['name']
body = fetch(f'/?show={tricky_id}')[2].decode()
check('titles are escaped in previews', f'content="{tricky_name.replace("&", "&amp;")}' in body and f'content="{tricky_name} (' not in body)
check('an unknown title previews the app', b'content="Couchside"' in fetch('/?show=999999999')[2])
check('https is kept behind a proxy', f'content="https://127.0.0.1:{httpd.server_address[1]}/og.jpg"'.encode()
      in fetch('/', headers={'X-Forwarded-Proto': 'https'})[2])
check('a public host is https even when the proxy says http', b'content="https://couchside.example/og.jpg"'
      in fetch('/', headers={'Host': 'couchside.example', 'X-Forwarded-Proto': 'http'})[2])
body = fetch('/', headers={'Host': 'evil.example"><script>x</script>'})[2]
check('a hostile Host header is not echoed', b'<script>x' not in body and b'evil.example' not in body)
status, headers, body = fetch('/manifest.webmanifest')
manifest = json.loads(body)
check('the manifest is served as one', status == 200 and headers.get('Content-Type') == 'application/manifest+json')
check('the manifest can be installed', manifest['display'] == 'standalone' and manifest['start_url'] == '/'
      and {'192x192', '512x512'} <= {i['sizes'] for i in manifest['icons']}
      and any(i.get('purpose') == 'maskable' for i in manifest['icons']))
check('every manifest icon and shortcut resolves', all(fetch(i['src'])[0] == 200 for i in manifest['icons'])
      and all(fetch(sc['url'])[0] == 200 for sc in manifest['shortcuts']))
for path, kind in [('/favicon.ico', 'image/x-icon'), ('/favicon.svg', 'image/svg+xml'), ('/apple-touch-icon.png', 'image/png'),
                   ('/og.jpg', 'image/jpeg'), ('/sw.js', 'text/javascript'), ('/robots.txt', 'text/plain; charset=utf-8'),
                   ('/offline.html', 'text/html; charset=utf-8')]:
    status, headers, _body = fetch(path)
    check(f'{path} is served as {kind}', status == 200 and headers.get('Content-Type') == kind, headers.get('Content-Type'))
check('the service worker carries this build', b'__BUILD__' not in fetch('/sw.js')[2])
check('robots stay out of the api', b'Disallow: /api/' in fetch('/robots.txt')[2])
check('powerful features are switched off', 'camera=()' in fetch('/')[1].get('Permissions-Policy', ''))
check('the engine sources are not served', fetch('/engine.py')[0] == 404 and fetch('/art.bin.gz')[0] == 404)
status, _headers, body = fetch('/api/search?q=breaking%20bad')
found = json.loads(body)['shows']
check('search returns cards with posters', status == 200 and found[0]['id'] == 169 and found[0]['poster'])
status, _headers, body = fetch('/api/home', {'profile': PROFILE, 'settings': DEFAULT_SETTINGS})
check('home answers over HTTP', status == 200 and json.loads(body)['personal'] is True)
check('a bad title id is a 400', fetch('/api/title', {'profile': [], 'id': -1})[0] == 400)
check('a body that is not an object is a 400', fetch('/api/home', [1, 2])[0] == 400)
check('the wrong content type is refused', fetch('/api/home', b'{}', 'text/plain')[0] == 415)
check('broken JSON is a 400', fetch('/api/home', b'{"profile":')[0] == 400)
check('deep nesting is a 400, not a dropped line', fetch('/api/home', b'[' * 5000 + b']' * 5000)[0] == 400)
status, _headers, body = fetch('/api/shows', {'ids': [169, 999_999_999]})
check('ids resolve to cards with posters', status == 200 and [c['id'] for c in json.loads(body)['shows']] == [169])
status, _headers, body = fetch('/api/extra?id=169')
check('live details come through', status == 200 and json.loads(body)['details']['cast'][0]['name'] == 'Bryan Cranston')
check('a non-numeric show id is a 400', fetch('/api/extra?id=abc')[0] == 400)
check('a show outside the catalog is a 400', fetch('/api/extra?id=999999999')[0] == 400)
check('episodes need a season', fetch('/api/episodes?id=169')[0] == 400)
status, _headers, body = fetch('/api/episodes?id=169&season=1')
check('episodes come through', status == 200 and json.loads(body)['episodes'][0]['name'] == 'Pilot')
status, _headers, body = fetch('/api/trailer?id=169')
check('trailers come through', status == 200 and json.loads(body)['videos'][0]['youtube'] == 'CCCCCCCCCCC')
status, _headers, body = fetch('/api/rating?id=169')
check('age ratings come through', status == 200 and json.loads(body) == {
    'rating': 'TV-MA', 'apple': 'https://itunes.apple.com/us/tv-season/breaking-bad-season-5/id533936970'})
check('a trailer needs a show id', fetch('/api/trailer?id=')[0] == 400)
status, headers, body = fetch('/api/icon?host=www.netflix.com')
check('icons are served as images and cached a week', status == 200 and headers.get('Content-Type') == 'image/png'
      and headers.get('Cache-Control') == 'public, max-age=604800' and body.startswith(b'\x89PNG'))
check('an icon for a non-host is a 400', fetch('/api/icon?host=127.0.0.1')[0] == 400)
check('api answers after an icon are not cached', fetch('/api/extra?id=169')[1].get('Cache-Control') == 'no-store')
status, _headers, body = fetch('/api/browse', {'profile': PROFILE, 'settings': {}, 'genre': 'Crime'})
check('browse answers over HTTP', status == 200 and json.loads(body)['rows'])
check('browsing nowhere is a 400', fetch('/api/browse', {'profile': [], 'genre': 'Nowhere'})[0] == 400)
check('an unknown api path is a 404', fetch('/api/nope')[0] == 404)

# 7b. TMDB first, and the live sources asked only for what it lacks.
before = len(asked['kino'])
status, _headers, body = fetch('/api/trailer?id=2993')
check('TMDB\'s trailers come first, without asking KinoCheck',
      status == 200 and json.loads(body)['videos'] == known[2993]['videos'] and len(asked['kino']) == before)
status, _headers, body = fetch('/api/trailer?id=44933')
check('without TMDB trailers, KinoCheck\'s', status == 200 and json.loads(body)['videos'][0]['youtube'] == 'CCCCCCCCCCC')
before = len(asked['store'])
status, _headers, body = fetch('/api/rating?id=2993')
check('TMDB\'s rating comes first, and iTunes is not asked while TMDB lists where to watch',
      status == 200 and json.loads(body) == {'rating': 'TV-14', 'apple': None} and len(asked['store']) == before)
status, _headers, body = fetch('/api/rating?id=82')
check('with nowhere to watch on TMDB, iTunes gives the Apple TV link but not the rating',
      status == 200 and json.loads(body) == {'rating': 'TV-MA', 'apple': SEASONS['Thrones'][3]})
status, _headers, body = fetch('/api/rating?id=44933')
check('without a TMDB rating, iTunes gives both', status == 200
      and json.loads(body) == {'rating': 'TV-MA', 'apple': SEASONS['Severance'][3]})
store = server.STORE
server.STORE = Live(fetch=lambda path: (_ for _ in ()).throw(HTTPError(path, 500, 'boom', {}, None)))
check('a TMDB rating survives iTunes being down', server.age(82) == {'rating': 'TV-MA', 'apple': None})
check('without one, iTunes being down is still an error', fetch('/api/rating?id=526')[0] == 502)
server.STORE = store
status, _headers, body = fetch('/api/title', {'profile': PROFILE, 'settings': {}, 'id': 2993})
check('a title carries TMDB\'s data with it', status == 200 and json.loads(body)['tmdb'] == known[2993])
status, _headers, body = fetch('/api/title', {'profile': [], 'settings': {}, 'id': 169})
check('a title TMDB lacks carries none', status == 200 and json.loads(body)['tmdb'] is None)
status, _headers, body = fetch('/api/home', {'profile': PROFILE, 'settings': {}})
hero = json.loads(body)['hero']
check('the hero carries TMDB\'s data too', status == 200 and 'tmdb' in hero and hero['tmdb'] == known.get(hero['id']))

# 7c. The page states the model the server loaded, not the one it was built beside.
built = (ROOT / 'couchside' / 'public' / 'index.html').read_text()
check('the built page leaves the model to the server',
      {'__BOOTSTRAP__', '__CATALOG_COUNT__', '__DATASET_DATE__'} <= set(re.findall(r'__[A-Z_]+__', built)))
boot = json.loads(re.search(rb'<script type="application/json" id="boot">(.*?)</script>', page_root, re.S)[1])
check('the page carries the loaded model\'s date and count', boot['date'] == MODEL_DATE and boot['count'] == engine.n
      and f'Catalogue snapshot {MODEL_DATE}.'.encode() in page_root
      and f'{engine.n:,} series from {MODEL_DATE}.'.encode() in page_root)
check('and its first-visit posters', [c['id'] for c in boot['starters']] == [c['id'] for c in lib.starters]
      and any(str(MOVED_POSTER) in (c['poster'] or '') for c in boot['starters']))
NOTICE = b'This website uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.'
check('TMDB is credited in the footer and in How Couchside works', page_root.count(NOTICE) == 2
      and page_root.count(b'<a class="tmdb-logo" href="https://www.themoviedb.org"><img src="/tmdb.svg"') == 2)
check('How Couchside works says what TMDB supplies', b'that streaming data comes from JustWatch' in page_root)
check('no credit marker reaches the page', b'<!--tmdb' not in page_root and b'<!--/tmdb' not in page_root)
plain = server.fill(server.TEMPLATE.read_text(), engine, lib, False)
check('without TMDB data there is no TMDB credit', 'TMDB' not in plain and 'tmdb' not in plain)
stand_in = type('Model', (), {'date': '2031-02-03', 'n': 12345})()
odd = type('Shelves', (), {'starters': [{'id': 1, 'name': '</script><!--<script>'}], 'genres': []})()
filled = server.fill(server.TEMPLATE.read_text(), stand_in, odd, False)
check('whatever model is loaded fills the page', 'Catalogue snapshot 2031-02-03.' in filled and '12,345 series' in filled
      and json.loads(re.search(r'id="boot">(.*?)</script>', filled, re.S)[1])['starters'][0]['name'] == '</script><!--<script>')
logo = (ROOT / 'couchside' / 'brand' / 'tmdb.svg').read_bytes()
status, headers, body = fetch('/tmdb.svg')
check('TMDB\'s logo is served as TMDB publishes it', status == 200 and headers.get('Content-Type') == 'image/svg+xml'
      and body == logo and hashlib.sha256(logo).hexdigest()
      == '8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c')
check('the 404 and offline pages stay as built', fetch('/nope')[2] == (ROOT / 'couchside' / 'public' / '404.html').read_bytes()
      and fetch('/offline.html')[2] == (ROOT / 'couchside' / 'public' / 'offline.html').read_bytes())
check('the new sources and model files are not served',
      all(fetch(path)[0] == 404 for path in ('/tmdb.py', '/follow.py', '/facets.py', '/tmdb.json.gz', '/build.json',
                                             '/facets.bin.gz', '/facets.json.gz', '/search.json.gz')))
httpd.shutdown()

# 8. Following the model: leave for a complete new one, and for nothing else.
current, loaded = TMP / 'current', server.MODEL
NEXT = TMP / 'versions' / '2026-09-09T040000Z'
HALF = TMP / 'versions' / '2026-09-10T040000Z'
NEXT.mkdir()
HALF.mkdir()


def point(link, target):
    """Move a link the way the refresher does: a new one beside it, renamed over it."""
    spare = link.with_name(link.name + '.next')
    os.symlink(target, spare)
    os.replace(spare, link)


class Stop(Exception):
    pass


def follow_through(moves, delay=5):
    """Run the follower with a sleep that makes one of the refresher's moves per nap,
    and stops it once the moves run out."""
    naps, said, left = [], [], []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) > len(moves):
            raise Stop
        if moves[len(naps) - 1]:
            point(current, moves[len(naps) - 1])
    try:
        result = follow.watch(current, loaded, poll=60, delay=delay, sleep=nap, leave=left.append, say=said.append)
    except Stop:
        result = None
    point(current, VERSION)
    return naps, said, left, result


check('an unmoved model is no reason to leave', follow.moved(current, loaded) is None)
point(current, HALF)
check('a model still being written is no reason to leave', follow.moved(current, loaded) is None)
(NEXT / 'build.json').write_text('{}')
point(current, NEXT)
check('a complete new model is', follow.moved(current, loaded) == os.path.realpath(NEXT))
point(current, TMP / 'versions' / 'gone')
check('a link to nothing is no reason to leave', follow.moved(current, loaded) is None)
point(current, VERSION)
check('a plain directory never moves', follow.moved(VERSION, loaded) is None)
naps, said, left, result = follow_through([None, NEXT, None])
check('the follower polls, waits out the delay, then leaves once', naps == [60, 60, 5] and left == [0]
      and result == os.path.realpath(NEXT), naps)
check('and says so in one line', len(said) == 1 and '\n' not in said[0] and NEXT.name in said[0], said)
naps, said, left, result = follow_through([NEXT, VERSION, None])
check('a move undone during the delay is no reason to leave', left == [] and said == [] and naps == [60, 5, 60, 60], naps)
naps, said, left, result = follow_through([HALF, None, None])
check('a model that never completes is waited out, not left for', left == [] and naps == [60, 60, 60, 60], naps)
naps, said, left, result = follow_through([NEXT, None], delay=0)
check('with no delay it leaves at once', naps == [60, 0] and left == [0], naps)
check('durations come from the environment', follow.seconds('90', 60.0) == 90 and follow.seconds('2.5', 0.0) == 2.5
      and follow.seconds('0', 60.0) == 0)
check('a duration that is not one falls back to the default',
      all(follow.seconds(value, 60.0) == 60 for value in (None, '', 'soon', '-5', 'nan', 'inf')))
check('a poll of 0 turns following off', follow.start(current, loaded, {'MODEL_POLL_SECONDS': '0'}) is None)

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
