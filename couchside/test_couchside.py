"""Check Couchside's shelves, title pages, live details, TMDB data and server.

Run from the repository root:  .venv/bin/python couchside/test_couchside.py
Nothing here reaches TVmaze, TMDB or anything else: live clients are driven by fakes,
and the server reads a temporary model laid out the way the refresher leaves one.
"""
from collections import Counter
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
import math
import os
import re
import shutil
import statistics
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
# Other titles, the way the model carries Wikidata's labels and aliases.
with gzip.open(VERSION / 'search.json.gz', 'wt', encoding='utf-8') as f:
    json.dump({'version': 1, 'aliases': {'27436': ['Money Heist'], '919': ['Shingeki no Kyojin', '進撃の巨人']}}, f,
              ensure_ascii=False)
(VERSION / 'build.json').write_text(json.dumps({
    'version': VERSION.name, 'built_at': '2026-09-08T04:20:00Z', 'snapshot_date': MODEL_DATE, 'shows': len(position),
    'pipeline': 'test', 'seeded_from': None, 'tmdb': {'fetched_at': TMDB_FILE['fetched_at'], 'shows': 3}}))
os.symlink(VERSION.relative_to(TMP), TMP / 'current')
os.environ['MODEL_DIR'] = str(TMP / 'current')

import server                                                    # noqa: E402
import follow                                                    # noqa: E402
import tmdb                                                      # noqa: E402
from build import MODULES                                        # noqa: E402
from engine import DEFAULT_SETTINGS, QUICK_PICKS, Engine         # noqa: E402
from fallback import Remote                                      # noqa: E402
from library import ROW, MORE, GLANCE, SHORTEST, GENRE_ROWS, NEW_DAYS, FALLBACK, UNRELATED, Library, lower_first  # noqa: E402
from library import (Page, Deeper, FIRST_PAGE, NEXT_PAGE, MOST_ROWS, CREATOR_SHORTEST, NOT_FOR_ME,  # noqa: E402
                     INTEREST_CAP, HIDDEN, PINNED, LONGEST, TIERS)
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


# 1. One engine for both apps, with its taste model, its search and the search's
# TVmaze fallback, the model follower and the facet reader, each copied unchanged.
check('the build copies every one of them',
      {'engine.py', 'taste.py', 'titles.py', 'fallback.py', 'follow.py', 'facets.py', 'fresh.py', 'starters.py'}
      <= set(MODULES))
for name in MODULES:
    check(f'{name} is Next Watch\'s, unchanged',
          (ROOT / 'app' / name).read_bytes() == (ROOT / 'couchside' / name).read_bytes())

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
check('coming soon is dated after the snapshot', cold['soon'] and all(c['premiered'] > engine.date for c in cold['soon']))
check('the page carries a few fallback starters with posters, led by a quick pick',
      len(lib.starters) == FALLBACK and all(c['poster'] for c in lib.starters) and lib.starters[0]['id'] in QUICK_PICKS
      and len({c['id'] for c in lib.starters}) == FALLBACK)
check('every starter has a poster, whatever the seed', all(
    lib.images[slot.index] for seed in ('0123456789abcdef', 'fedcba9876543210', None)
    for slot in lib.starting.choose(seed, 0, (), 'ko')))

# 3b. A first visit's page: the Top 10, what is popular now, all-time favourites, new this
# year and the best-known genres and formats, no show twice, eight rows first.
def shown_of(rows):
    """What the browser says it shows: each row's key, first six ids and, past today's rows, its tier."""
    return [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:GLANCE]], **({'tier': r['tier']} if 'tier' in r else {})}
            for r in rows]


def whole(body):
    """Every row of a home page, asked for the way the browser asks, with each answer."""
    answers = [lib.home(body)]
    rows = list(answers[0]['rows'])
    while answers[-1]['more'] and len(rows) < LONGEST:
        answers.append(lib.home({**body, 'shown': shown_of(rows)}))
        rows += answers[-1]['rows']
    return rows, answers


def seeded(day):
    return {'day': day, 'seed': hashlib.sha256(f'test|{day}'.encode()).hexdigest()[:16]}


def page_of(body):
    """The Page for a request, laid out as the first request lays it out."""
    profile, settings, positives, negatives, rated, candidates, today_ = lib.prepare(body)
    page = Page(lib, profile, settings, positives, negatives, rated, candidates, lib.read_list(body), today_)
    return page, page.layout([])[1]


def listed(*keys, most=60):
    """A list gathered from bench personas, loves, likes and dislikes as rated there."""
    found, seen = [], set()
    by_key = {p['key']: p for p in PERSONAS}
    for key in keys:
        for role, weight in (('loves', 1), ('likes', .7), ('dislikes', -1)):
            for s in by_key[key][role]:
                if s['id'] in engine.by_id and s['id'] not in seen and len(found) < most:
                    seen.add(s['id'])
                    found.append({'id': s['id'], 'weight': weight})
    return found


PERSONAS = json.loads((ROOT / 'scripts' / 'bench' / 'personas.json').read_text())['personas']


cold_rows, cold_answers = whole({'profile': [], 'settings': {}})
cold_keys = [r['key'] for r in cold_rows]
cold_by = {r['key']: r for r in cold_rows}
check('a first visit gets eight rows first and the rest when asked',
      len(cold_answers[0]['rows']) == FIRST_PAGE and cold_answers[0]['more'] and len(cold_answers) == 2
      and 0 < len(cold_answers[1]['rows']) <= NEXT_PAGE and not cold_answers[1]['more'], [len(a['rows']) for a in cold_answers])
check('a first visit leads with the Top 10 and what is popular now', cold_keys[:2] == ['top10', 'popular'], cold_keys)
check('it has all-time favourites and new this year', {'classics', 'this-year'} <= set(cold_keys), cold_keys)
cold_genres = [k for k in cold_keys if k.startswith(('genre-', 'format-'))]
check('and six to eight rows of the best-known genres and formats', 6 <= len(cold_genres) <= 8, cold_genres)
cold_ids = [c['id'] for r in cold_rows for c in r['items']]
check('no show appears twice on a first visit', len(cold_ids) == len(set(cold_ids)))
check('all-time favourites premiered before 2010 and are well rated',
      all(c['year'] < 2010 and engine.shows[engine.by_id[c['id']]]['rating'] >= 8 for c in cold_by['classics']['items']))
check("new this year is this year's", all(c['year'] == lib.year for c in cold_by['this-year']['items']))
spanish = lib.home({'profile': [], 'settings': {}, 'lang': ['es-MX', 'en']})
spanish_rows = {r['key']: r for r in spanish['rows']}
check('a browser in Spanish also gets what is popular in Spanish', 'popular-spanish' in spanish_rows
      and spanish_rows['popular-spanish']['title'] == 'Popular in Spanish'
      and all(engine.shows[engine.by_id[c['id']]]['language'] == 'Spanish' for c in spanish_rows['popular-spanish']['items']))
check('a browser in English gets no language row',
      not any(r['key'].startswith('popular-') for r in lib.home({'profile': [], 'lang': 'en-GB'})['rows']))
top10_ids = [c['id'] for c in cold['top10']]
check('without a day the hero leads the Top 10', cold['hero']['id'] == top10_ids[0])
heroes = [lib.home({'profile': [], **seeded(f'2026-10-{d:02d}')})['hero']['id'] for d in range(1, 15)]
check('with a day the hero is drawn from the Top 10, and changes', set(heroes) <= set(top10_ids) and len(set(heroes)) >= 3,
      heroes)
rest = lib.home({'profile': [], **seeded('2026-10-01'), 'resting': top10_ids[:9]})['hero']['id']
check('a hero of the last week rests', rest == top10_ids[9], rest)

# 4. A rated list gets rows built from it.
home = lib.home({'profile': PROFILE, 'settings': {}, 'list': [526, 999_999_999, 431]})
rows = {r['key']: r for r in home['rows']}
reference = engine.calculate({'profile': PROFILE, 'settings': {}})
check('a rated list is personal', home['personal'] is True)
page4, _laid4 = page_of({'profile': PROFILE, 'settings': {}, 'list': [526, 999_999_999, 431]})
top_ids = [c['id'] for c in rows['top']['items']]
check('top picks come from the best hundred the plain ranking gives',
      set(top_ids) <= {engine.shows[i]['id'] for i in page4.usable[:100]})


def divergence(ids):
    """How far a set of picks' mix of interests is from the list's (Kullback-Leibler)."""
    groups = Counter(page4.ranking.group.get(engine.by_id[i]) for i in ids)
    return sum(p * math.log(p / (0.99 * groups[k] / len(ids) + 0.01 * p)) for k, p in enumerate(page4.share) if p > 0)


check("top picks are calibrated to the list's mix of interests at least as closely as the plain ranking",
      divergence(top_ids) <= divergence([p['id'] for p in reference['picks'][:ROW]]) + 1e-9,
      (round(divergence(top_ids), 3), round(divergence([p['id'] for p in reference['picks'][:ROW]]), 3)))
best10 = [engine.shows[i]['id'] for i in page4.usable if engine.shows[i]['id'] not in (526, 431)][:10]
check('the hero is one of the ten best picks not on My List', home['hero']['id'] in best10 and home['hero']['match'])
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
liked_only = [r['title'] for r in lib.home({'profile': [{'id': 82, 'weight': .7}], 'settings': {}})['rows']
              if r['key'].startswith('seed-')]
check('a liked seed says liked', liked_only == ['Because you liked Game of Thrones'], liked_only)
for r in home['rows']:
    if r['key'].startswith('genre-'):
        genre = next(g for g, title in GENRE_ROWS.items() if title == r['title'])
        check(f'{r["title"]} holds only {genre}', all(genre in engine.shows[engine.by_id[c["id"]]]['genres'] for c in r['items']))
check('new for you is new', all(c['year'] >= lib.year - 1 for c in rows.get('new', {'items': []})['items']))
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

# 4c. The whole page for lists of several shapes: its fixed places, its size, and the rules
# that keep rows from repeating one another. Today's rows (tier 0) come first and keep the
# rules of a page of 20 to 30 rows; the page goes on past them into the tiers below (4i
# pages whole pages with stand-in rows in every tier).
SHAPES = {
    'five shows': {'profile': PROFILE, 'list': [526, 431]},
    'one taste': {'profile': listed('prestige_crime')},
    'twenty-five mixed': {'profile': listed('prestige_crime', 'british_panel', 'cozy_mystery', most=25), 'list': [2993]},
    'sixty mixed': {'profile': listed('prestige_crime', 'british_panel', 'cozy_mystery', 'shonen_anime',
                                      'adult_animation'), 'list': [169, 526, 919]},
}
for shape, body in SHAPES.items():
    body = {'settings': {}, 'list': [], **body}
    page_rows, answers = whole(body)
    keys = [r['key'] for r in page_rows]
    rated_ids = {p['id'] for p in body['profile']}
    saved = [i for i in body['list'] if i in engine.by_id]
    check(f'{shape}: eight rows come first, then six at a time', len(answers[0]['rows']) == FIRST_PAGE
          and all(len(a['rows']) <= NEXT_PAGE for a in answers[1:]) and not answers[-1]['more'])
    today = [r for r in page_rows if 'tier' not in r]
    today_keys = [r['key'] for r in today]
    check(f'{shape}: today\'s rows come first, at least the first page and at most {MOST_ROWS}',
          page_rows[:len(today)] == today and FIRST_PAGE <= len(today) <= MOST_ROWS, len(today))
    check(f'{shape}: the page ends within {LONGEST} rows, each past today\'s saying its tier',
          len(keys) <= LONGEST and all(1 <= r['tier'] <= TIERS for r in page_rows[len(today):]))
    check(f'{shape}: top picks lead', keys[0] == 'top', keys)
    unrated_saved = [i for i in saved if i not in rated_ids]
    check(f'{shape}: My List is row 2 exactly when it holds an unrated show',
          (keys[1] == 'list') == bool(unrated_saved) and keys.count('list') <= 1, keys[:3])
    check(f'{shape}: the Top 10 sits between rows 3 and 10', 'top10' in keys and 2 <= keys.index('top10') <= 9, keys)
    check(f'{shape}: Popular sits below row 10', 'popular' not in keys or keys.index('popular') >= 10, keys)
    check(f'{shape}: Something different is never among the first eight', 'different' not in keys[:FIRST_PAGE])
    check(f'{shape}: no row twice', len(keys) == len(set(keys)))
    # The Top 10 is a chart, shown whole: a show trending today may also open a personal row.
    personal_rows = [r for r in page_rows if r['key'] != 'top10']
    heads = [c['id'] for r in personal_rows for c in r['items'][:GLANCE]]
    check(f'{shape}: no two rows open with the same show', len(heads) == len(set(heads)))
    times = Counter(c['id'] for r in personal_rows for c in r['items'])
    check(f'{shape}: no show appears more than twice', max(times.values()) <= 2, times.most_common(2))
    sizes = {r['key']: len(r['items']) for r in page_rows}
    check(f'{shape}: the Top 10 holds ten', sizes['top10'] == 10)
    check(f'{shape}: every other row holds {SHORTEST} to {ROW} cards, a creator\'s at least {CREATOR_SHORTEST}',
          all(SHORTEST <= n <= ROW or (k.startswith('creator-') and CREATOR_SHORTEST <= n <= ROW)
              for k, n in sizes.items() if k not in ('top10', 'list')), sizes)
    chosen = [r for r in page_rows if r['kind'] == 'row']
    check(f'{shape}: no row chosen for you holds a rated show', not rated_ids & {c['id'] for r in chosen for c in r['items']})
    disliked = [engine.blend(engine.by_id[p['id']], DEFAULT_SETTINGS) for p in body['profile'] if p['weight'] < 0]
    check(f'{shape}: nothing very close to a show marked Not for me', all(
        a[engine.by_id[c['id']]] < NOT_FOR_ME for a in disliked for r in chosen for c in r['items']))
    fine = True
    for r in chosen:
        head = [engine.by_id[c['id']] for c in r['items'][:GLANCE]]
        franchises = Counter(t for i in head for t in lib.facet_sets(i)[0])
        creators = Counter(t for i in head for t in lib.facet_sets(i)[1])
        if (franchises and max(franchises.values()) > 1) or (creators and max(creators.values()) > 2):
            fine = False
    check(f'{shape}: a row opens with one show at most from a franchise and two from a creator', fine)
    neighbours = []
    net = lambda i: engine.shows[i]['channel']
    # Top picks and Because you loved keep the ranking's order past networks (PRECISE_KINDS).
    for r in [r for r in chosen if r['key'] != 'top' and not r['key'].startswith('seed-')]:
        cards = [engine.by_id[c['id']] for c in r['items']]
        others = {engine.by_id[c['id']] for o in page_rows if o is not r for c in o['items'][:GLANCE]}
        for n in range(PINNED, min(GLANCE, len(cards))):
            if not net(cards[n]) or net(cards[n]) != net(cards[n - 1]):
                continue
            # Only a card that could open the row counts as another that could stand there.
            head = cards[:n]
            franchises = set().union(*(lib.facet_sets(i)[0] for i in head))
            creators = Counter(t for i in head for t in lib.facet_sets(i)[1])
            if any(net(j) != net(cards[n]) and j not in others and not lib.facet_sets(j)[0] & franchises
                   and all(creators[t] < 2 for t in lib.facet_sets(j)[1]) for j in cards[n + 1:]):
                neighbours.append((r['key'], n))
    check(f'{shape}: past the pinned cards, rows other than Top picks and Because you loved keep a network\'s shows apart',
          not neighbours, neighbours)
    niches = [r['title'] for r in page_rows if r['key'].startswith('niche-')]
    check(f'{shape}: micro-genre names run to five words at most', all(len(t.split()) <= 5 for t in niches), niches)
    seeds_ = [k for k in today_keys if k.startswith('seed-')]
    check(f'{shape}: two to six Because you loved rows among today\'s', 2 <= len(seeds_) <= 6, seeds_)
    page, laid = page_of(body)
    check(f'{shape}: the pages asked for one at a time are the page laid out at once',
          keys == [shelf.key for shelf, _items in laid])
    laid_today = [(shelf, items) for shelf, items in laid if not page.tier_of.get(shelf.key)]
    served = Counter(shelf.interest for shelf, _items in laid_today if shelf.interest is not None)
    check(f'{shape}: every interest with 8% or more of the list has a row',
          all(served[k] for k in page.significant), (page.significant, served))
    quota = page.quota
    check(f'{shape}: no interest holds more rows than its share allows', all(served[k] <= quota[k] for k in served),
          (served, quota))
    if len(page.significant) >= 3:
        planned = sum(quota.values())
        check(f'{shape}: with three or more interests, none is planned more than 40% of their rows',
              all(q <= INTEREST_CAP * planned + 1e-9 for q in quota.values()), quota)
    if sum(p['weight'] > 0 for p in body['profile']) < 10:
        check(f'{shape}: with fewer than ten liked shows, personal rows are at most half of today\'s',
              2 * sum(shelf.personal for shelf, _items in laid_today) <= len(laid_today))
    seed_interests = Counter(shelf.interest for shelf, _items in laid_today if shelf.kind_of == 'seed')
    check(f'{shape}: at most three Because you loved rows for an interest among today\'s', max(seed_interests.values()) <= 3)
    for shelf, items in laid:
        cards = [engine.shows[i] for i in items]
        if shelf.key == 'gems':
            floor = page.stats['rating_q75']
            check(f'{shape}: hidden gems are little known and well rated',
                  all(page.pop(i) <= HIDDEN[0] and (engine.shows[i]['rating'] or 0) >= floor for i in items))
        if shelf.key == 'limited':
            check(f'{shape}: limited series are limited series', all(i in lib.limited for i in items))
        if shelf.key == 'new':
            check(f'{shape}: new for you is new', all(s['year'] >= lib.year - 1 for s in cards))
        if shelf.key.startswith('acclaimed-'):
            check(f'{shape}: {shelf.title} is rated 8 or more', all(s['rating'] >= 8 for s in cards))
        if shelf.key.startswith('cast-'):
            column = next(c for c in lib.facet_sets(items[0])[3] if shelf.title == f'Starring {engine.facets.labels[c]}')
            liked_with = [p for p in body['profile'] if p['weight'] > 0 and column in lib.facet_sets(engine.by_id[p['id']])[3]]
            check(f'{shape}: {shelf.title} stars in two or more liked shows and every card', len(liked_with) >= 2
                  and all(column in lib.facet_sets(i)[3] for i in items))
        if shelf.key.startswith('seed-'):
            seed = next(p for p in body['profile'] if p['id'] == int(shelf.key[5:]))
            verb = 'loved' if seed['weight'] == 1 else 'liked'
            check(f'{shape}: {shelf.title} says {verb}', shelf.title.startswith(f'Because you {verb} '))
    callouts = [c['callout'] for r in page_rows for c in r['items'] if c.get('callout')]
    check(f'{shape}: call-outs name a concrete tie', all(t.startswith(('Same world as ', 'Same creator as ', 'Stars '))
                                                        for t in callouts), callouts[:3])
    subtitles = [r['subtitle'] for r in page_rows if r.get('subtitle')]
    check(f'{shape}: subtitles never explain a row by popularity', not any('popular' in t.lower() for t in subtitles))

# 4d. Paging: the same request gives the same page, and one sent after the list changed
# keeps the rows shown and builds only the rest.
body = {'profile': SHAPES['twenty-five mixed']['profile'], 'settings': {}, 'list': [2993], **seeded('2026-10-05')}
first = lib.home(body)
check('the same first request gives the same answer', lib.home(body) == first)
shown = [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:GLANCE]]} for r in first['rows']]
second = lib.home({**body, 'shown': shown})
check('asking again for the next rows gives the same rows', lib.home({**body, 'shown': shown}) == second)
check('the next rows carry no hero, and the list\'s taste', 'hero' not in second and second['taste'] and second['rows'])
check('asking for no rows gives the taste alone', lib.home({**body, 'shown': shown, 'count': 0})['rows'] == []
      and lib.home({**body, 'shown': shown, 'count': 0})['taste'] == second['taste'])
liked_now = next(c['id'] for c in first['rows'][0]['items'] if c['id'] not in {p['id'] for p in body['profile']})
after = lib.home({**body, 'profile': body['profile'] + [{'id': liked_now, 'weight': 1}], 'shown': shown})
after_keys = [r['key'] for r in after['rows']]
check('after a rating, the rows shown stay out of the next answer', not {s['key'] for s in shown} & set(after_keys)
      and after['rows'], after_keys)
opened = {i for s in shown for i in s['ids']}
check('and the rows built after them open with none of their shows',
      not opened & {c['id'] for r in after['rows'] for c in r['items'][:GLANCE]})
check('and hold nothing just rated', liked_now not in {c['id'] for r in after['rows'] for c in r['items']
                                                       if r['kind'] == 'row'})

# 4e. Freshness: a day's page is fixed by the day and seed, and the next day's differs.
monday = whole({**body, **seeded('2026-10-05')})[0]
check('the same day and seed give the same page', whole({**body, **seeded('2026-10-05')})[0] == monday)
tuesday = whole({**body, **seeded('2026-10-06')})[0]
check('the next day gives another page', tuesday != monday)
check('but top picks lead and keep their first two cards', monday[0]['key'] == tuesday[0]['key'] == 'top'
      and [c['id'] for c in monday[0]['items'][:PINNED]] == [c['id'] for c in tuesday[0]['items'][:PINNED]])
kept = [len({c['id'] for c in r['items']} & {c['id'] for c in t['items']}) / len(r['items'])
        for r in monday for t in tuesday if r['key'] == t['key'] and r['kind'] == 'row' and r['key'] != 'different']
check('most of a row carries over to the next day', statistics.mean(kept) >= 0.6, round(statistics.mean(kept), 2))
check('and rows further down change', [r['key'] for r in monday] != [r['key'] for r in tuesday]
      or any(r['items'] != t['items'] for r, t in zip(monday, tuesday)))
plain = whole({**body})[0]
worn = [c['id'] for c in plain[0]['items'][2:6]]
tired_page = whole({**body, 'seen': {str(i): 20 for i in worn}})[0]
check('titles shown on many recent days give way to others', not set(worn) <= {c['id'] for c in tired_page[0]['items'][:GLANCE]})
check('unless they were engaged with', whole({**body, 'seen': {str(i): 20 for i in worn}, 'engaged': worn})[0] == plain)

# 4f. The hero: drawn from the ten best picks, never rated, on My List or a recent hero,
# and not one the first rows already open with.
profile_ids = {p['id'] for p in body['profile']}
page, laid = page_of({**body, **seeded('2026-10-05')})
best = [engine.shows[i]['id'] for i in page.usable if engine.shows[i]['id'] not in body['list']][:10]
drawn = []
for d in range(1, 15):
    answer = lib.home({**body, **seeded(f'2026-10-{d:02d}')})
    drawn.append(answer['hero']['id'])
    opening = {c['id'] for r in answer['rows'][:3] for c in r['items'][:GLANCE]}
    if answer['hero']['id'] in opening and not set(best) - opening:
        opening = set()
    check(f'the hero on 2026-10-{d:02d} is one of the ten best, not rated, not listed, not opening a top row',
          answer['hero']['id'] in best and answer['hero']['id'] not in profile_ids and answer['hero']['id'] not in body['list']
          and answer['hero']['id'] not in opening)
check('the hero changes from day to day', len(set(drawn)) >= 3, drawn)
resting = lib.home({**body, **seeded('2026-10-05'), 'resting': drawn})['hero']['id']
check('a hero shown in the last week is not drawn again', resting not in drawn)

# 4g. Rows passed over on five days in a fortnight rest at the foot of today's rows.
tired_key = next(r['key'] for r in monday[4:] if r['kind'] == 'row' and r['key'] not in ('popular', 'different')
                 and 'tier' not in r)
rested = whole({**body, **seeded('2026-10-05'), 'tired': [tired_key]})[0]
rested_keys = [r['key'] for r in rested if 'tier' not in r]
check('a tired row rests below the first page', tired_key not in rested_keys[:FIRST_PAGE] and
      (tired_key not in rested_keys or rested_keys.index(tired_key) >= len(rested_keys) - 2), (tired_key, rested_keys))

# 4h. The new fields are checked like the rest.
rejects('a language that is not a tag', lambda: lib.home({'profile': [], 'lang': ['english!']}), 'language tags')
rejects('too many languages', lambda: lib.home({'profile': [], 'lang': ['en'] * 9}), 'language tags')
rejects('a language that is a number', lambda: lib.home({'profile': [], 'lang': 5}), 'language tags')
rejects('shown rows that are not a list', lambda: lib.home({'profile': [], 'shown': 'top'}), 'shown')
rejects('too many shown rows', lambda: lib.home({'profile': [], 'shown': [{'key': f'r{n}', 'ids': []} for n in range(LONGEST + 1)]}),
        f'up to {LONGEST}')
rejects('a shown row in a tier past the last', lambda: lib.home({'profile': [], 'shown': [{'key': 'top', 'tier': TIERS + 1}]}),
        'tier')
rejects('a shown row whose tier is not a number', lambda: lib.home({'profile': [], 'shown': [{'key': 'top', 'tier': '1'}]}),
        'tier')
rejects('a shown row with a bad key', lambda: lib.home({'profile': [], 'shown': [{'key': 'Top Picks!', 'ids': []}]}), 'key')
rejects('a shown row with too many ids', lambda: lib.home({'profile': [], 'shown': [{'key': 'top', 'ids': list(range(7))}]}),
        'up to 6')
rejects('a shown row with ids that are not numbers', lambda: lib.home({'profile': [], 'shown': [{'key': 'top', 'ids': ['1']}]}),
        'up to 6')
rejects('a row shown twice', lambda: lib.home({'profile': [], 'shown': [{'key': 'top'}, {'key': 'top'}]}), 'only once')
rejects('a count that is too big', lambda: lib.home({'profile': [], 'count': 9}), '0 to 8')
rejects('a count that is not a number', lambda: lib.home({'profile': [], 'count': '6'}), '0 to 8')
rejects('a day without its seed', lambda: lib.home({'profile': [], 'day': '2026-10-05'}), 'together')
rejects('a malformed seed', lambda: lib.home({'profile': [], 'day': '2026-10-05', 'seed': 'zz'}), 'hexadecimal')
rejects('seen counts that are not numbers', lambda: lib.home({'profile': [], 'seen': {'169': 'x'}}), '0 to 50')
rejects('tired rows that are not keys', lambda: lib.home({'profile': [], 'tired': ['Top!']}), 'row keys')
browsed = lib.browse({'profile': PROFILE, 'settings': {}, 'genre': 'Crime', **seeded('2026-10-05')})
check('browsing takes a day too, and keeps each row\'s first two', browsed['rows'][0]['items'][:PINNED] ==
      lib.browse({'profile': PROFILE, 'settings': {}, 'genre': 'Crime', **seeded('2026-10-06')})['rows'][0]['items'][:PINNED])
more_today = [c['id'] for c in lib.title({'profile': PROFILE, 'id': 169, **seeded('2026-10-05')})['more']]
more_plain = [c['id'] for c in lib.title({'profile': PROFILE, 'id': 169})['more']]
check('more like this is the same every day, with no day drawn into it',
      more_today == more_plain == [c['id'] for c in lib.title({'profile': PROFILE, 'id': 169, **seeded('2026-10-06')})['more']])

# 4i. Past today's rows, with rows of their own in every tier (stand-ins cut with the page's
# own helpers, scripts/bench/stub_tiers.py): the page goes on tier by tier until the last is
# spent, a tier is built only once the page reaches it, and a request can take the page up
# anywhere, the same each time.
sys.path.insert(0, str(ROOT / 'scripts' / 'bench'))
import stub_tiers  # noqa: E402

built = Counter()
building = Page.tier_rows
choosing = Deeper.best
picks = []


def counted(page_, tier):
    built[tier] += 1
    return building(page_, tier)


def watched(deeper, options, p):
    """Deeper.best, noting whether the row it takes was held back and whether any was not."""
    shelf, rel = choosing(deeper, options, p)
    held = {row.key: back for row, _rel, back in options}
    picks.append((held[shelf.key], not all(held.values())))
    return shelf, rel


Deeper.best = watched
with stub_tiers.installed(Page, tier_rows=counted):
    for shape, day in (('five shows', {}), ('twenty-five mixed', seeded('2026-10-05'))):
        body = {'settings': {}, 'list': [], **SHAPES[shape], **day}
        page_rows, answers = whole(body)
        keys = [r['key'] for r in page_rows]
        today = [r for r in page_rows if 'tier' not in r]
        tiers = [r.get('tier', 0) for r in page_rows]
        check(f'{shape}, every tier: the page goes on past today\'s rows into each tier in turn, to the last, and ends',
              len(page_rows) >= len(today) + 20 and tiers == sorted(tiers) and max(tiers) == TIERS
              and len(page_rows) < LONGEST, (len(today), Counter(tiers)))
        check(f'{shape}, every tier: each answer brings a full page but the last, and more is false only at the end',
              len(answers[0]['rows']) == FIRST_PAGE and all(len(a['rows']) == NEXT_PAGE for a in answers[1:-1])
              and all(a['more'] for a in answers[:-1]) and not answers[-1]['more'] and answers[-1]['rows'])
        check(f'{shape}, every tier: no row twice, and no two rows share a title',
              len(keys) == len(set(keys)) and len({r['title'].casefold() for r in page_rows}) == len(page_rows))
        heads = [c['id'] for r in page_rows if r['key'] != 'top10' for c in r['items'][:GLANCE]]
        times = Counter(c['id'] for r in page_rows if r['key'] != 'top10' for c in r['items'])
        check(f'{shape}, every tier: no two rows open with the same show, and no show is on the page more than twice',
              len(heads) == len(set(heads)) and max(times.values()) <= 2, times.most_common(2))
        check(f'{shape}, every tier: every row past today\'s holds {SHORTEST} to {ROW} cards',
              all(SHORTEST <= len(r['items']) <= ROW for r in page_rows[len(today):]))
        page, laid = page_of(body)
        check(f'{shape}, every tier: the pages asked for one at a time are the page laid out at once, cards and all',
              [page.row(shelf, items) for shelf, items in laid] == page_rows)
        origin = {shelf.key: shelf.tier for shelf, _items in laid}
        opened_at = {t: next((n for n, tier in enumerate(tiers) if tier >= t), len(tiers)) for t in range(1, TIERS + 1)}
        check(f'{shape}, every tier: no row comes before its tier opens, so no tier-2 row before tier 1',
              all(origin[r['key']] <= r.get('tier', 0) for r in page_rows)
              and all(origin[k] < t for t, n in opened_at.items() for k in keys[:n]))
        check(f'{shape}, every tier: a row resting, or whose interest holds its share of the page so far (a share that '
              f'grows with the page), comes only once nothing else open holds up',
              picks and not any(held and others for held, others in picks)
              and sum(page.quotas(4 * page.cap).values()) > sum(page.quotas(page.cap).values()), picks[-5:])
        picks.clear()

    # body, page_rows and today are the seeded page of twenty-five mixed shows from here.
    built.clear()
    lib.home(body)
    check('the first rows build no tier past today\'s', not built and len(today) > FIRST_PAGE, dict(built))
    built.clear()
    lib.home({**body, 'shown': shown_of(today)})
    check('the rows just past today\'s build tier 1, once', built[1] == 1 and max(built.values()) == 1, dict(built))
    deep = next(n for n, r in enumerate(page_rows) if r.get('tier', 0) >= 3)
    built.clear()
    lib.home({**body, 'shown': shown_of(page_rows[:deep + 1])})
    check('rows further down build the tiers they reach, each once', {1, 2, 3} <= set(built) and max(built.values()) == 1,
          dict(built))
    upto = len(today) + 20
    ask = {**body, 'shown': shown_of(page_rows[:upto])}
    again = lib.home(ask)
    check('a request past today\'s rows gives the same rows each time, the page\'s next ones',
          lib.home(ask) == again and again['rows'] == page_rows[upto:upto + NEXT_PAGE])
    shown = shown_of(page_rows[:upto])
    rated_ids = {p['id'] for p in body['profile']}
    liked_now = next(c['id'] for c in page_rows[upto - 3]['items'] if c['id'] not in rated_ids)
    after = lib.home({**body, 'profile': body['profile'] + [{'id': liked_now, 'weight': 1}], 'shown': shown})
    opened = {i for s in shown for i in s['ids']}
    check('after a rating deep in the page, the rows shown stay as they are and the next open with none of their shows',
          after['rows'] and not {s['key'] for s in shown} & {r['key'] for r in after['rows']}
          and not opened & {c['id'] for r in after['rows'] if r['kind'] == 'row' for c in r['items'][:GLANCE]}
          and liked_now not in {c['id'] for r in after['rows'] if r['kind'] == 'row' for c in r['items']})
    kept_before = lib.home({**body, 'shown': [{'key': s['key'], 'ids': s['ids']} for s in shown]})
    check('a page kept from before rows carried tiers still gets its next rows',
          kept_before['rows'] and kept_before['more'] and not {s['key'] for s in shown} & {r['key'] for r in kept_before['rows']})
    tuesday = whole({**body, **seeded('2026-10-06')})[0]
    deep_monday, deep_tuesday = [r['key'] for r in page_rows if 'tier' in r], [r['key'] for r in tuesday if 'tier' in r]
    check('rows past today\'s reorder a little from day to day, all below today\'s rows', deep_monday != deep_tuesday
          and len(set(deep_monday) & set(deep_tuesday)) >= 0.8 * min(len(deep_monday), len(deep_tuesday))
          and all('tier' not in r for r in tuesday[:len(tuesday) - len(deep_tuesday)]))
    tired_deep = page_rows[len(today) + 3]['key']
    rested = whole({**body, 'tired': [tired_deep]})[0]
    rested_keys = [r['key'] for r in rested]
    check('a tired row past today\'s rests further down, and no sooner than its tier',
          tired_deep not in rested_keys or (rested_keys.index(tired_deep) > len(today) + 3
                                            and rested[rested_keys.index(tired_deep)]['tier'] >= page_rows[len(today) + 3]['tier']),
          tired_deep)
Deeper.best = choosing

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

# More like this is about the title, not the viewer: closeness to it, its own world first,
# no padding, and no match. Franchises and what readers look up next come with the
# repository's model, which the temporary one leaves out, so it is read here as well.
check('no card under more like this carries a match, though the title has one',
      page['show']['match'] and all('match' not in c for c in page['more']))
check('more like this is stories for a story, with or without facets',
      all(c['type'] in ('Scripted', 'Animation') for c in page['more'] + bare['more']))
full_engine = Engine(ROOT / 'model')
full = Library(full_engine, ROOT / 'couchside' / 'art.bin.gz')


def more_of(show_id, profile=()):
    return full.title({'profile': list(profile), 'settings': {}, 'id': show_id})['more']


def ids_of(cards):
    return [c['id'] for c in cards]


thrones = more_of(82)
check('Game of Thrones brings House of the Dragon, among the first, as its own world',
      44778 in ids_of(thrones)[:2] and thrones[ids_of(thrones).index(44778)]['why'] == 'Same world', ids_of(thrones))
bad = more_of(169)
check('Breaking Bad brings Better Call Saul first, as its own world',
      bad[0]['id'] == 618 and bad[0]['why'] == 'Same world', ids_of(bad))
check('a card says why when it can: the same creator',
      any(c['id'] == 86175 and c['why'] == 'Same creator' for c in bad), [(c['name'], c.get('why')) for c in bad])
office = more_of(526)
check('a sitcom brings half-hour comedies', office and all(
    'Comedy' in c['genres'] and c['runtime'] and c['runtime'] <= 40 for c in office), [c['name'] for c in office])
check('a story brings stories', all(c['type'] in ('Scripted', 'Animation') for c in thrones + bad + office))
check('a factual show brings factual shows', all(c['type'] not in ('Scripted', 'Animation') for c in more_of(2950)))
trek = more_of(491)
worlds = [c for c in trek if c.get('why') == 'Same world']
check('a show\'s own world leads, six at most', 1 <= len(worlds) <= 6 and trek[:len(worlds)] == worlds
      and len(trek) == MORE, [(c['name'], c.get('why')) for c in trek])
check('a drama after another in its time slot is not its world',
      57705 not in full.kin(full_engine.by_id[56464])[0] and all(c.get('why') != 'Same world' for c in more_of(56464)))
settled = thrones
check('whoever looks, the same shows, the viewer\'s taste only breaking near ties',
      len(set(ids_of(more_of(82, [{'id': 431, 'weight': 1}]))) & set(ids_of(settled))) >= len(settled) - 2
      and len(set(ids_of(more_of(82, [{'id': 169, 'weight': 1}]))) & set(ids_of(settled))) >= len(settled) - 2)
wheel, rings = 35083, 33352
disliked = ids_of(more_of(82, [{'id': rings, 'weight': -1}])) + [wheel]
check('a show marked Not for me pushes what is like it down',
      rings not in disliked and ids_of(settled).index(wheel) < disliked.index(wheel), disliked)
close = full_engine.blend(full_engine.by_id[82], DEFAULT_SETTINGS)
check('every show there has something in common with the title',
      all(close[full_engine.by_id[c['id']]] >= UNRELATED for c in thrones))
check('a title with few shows much like it gets a short list rather than a padded one',
      0 < len(more_of(67633)) < MORE, len(more_of(67633)))
del full, full_engine
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


tvmaze_asked = []
NEW_SHOW = {'id': 900000001, 'name': 'Kimetsu Academy', 'premiered': '2026-09-26',
            'url': 'https://www.tvmaze.com/shows/900000001/kimetsu-academy'}


def tvmaze(path):
    """TVmaze's search: Demon Slayer by its Japanese name, and a show too new for the catalogue."""
    tvmaze_asked.append(path)
    if 'kimetsu' not in path:
        raise HTTPError(path, 500, 'boom', {}, None)
    return [{'show': {'id': 41469, 'name': 'Demon Slayer', 'premiered': '2019-04-06',
                      'url': 'https://www.tvmaze.com/shows/41469/demon-slayer'}}, {'show': NEW_SHOW}]


server.LIVE = Live(fetch=fake)
server.KINO = Live(fetch=kinocheck)
server.STORE = Live(fetch=itunes)
server.ICONS = Icons(fetch=lambda host: ('image/png', b'\x89PNG fake'))
server.TVMAZE = Remote(fetch=tvmaze)
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
check('iOS never zooms into a field, and the page runs under the notch',
      b'initial-scale=1, maximum-scale=1, viewport-fit=cover' in page_root and b'user-scalable' not in page_root)
check('everywhere but iOS the scale limit comes off, so pinch zoom stays on',
      b"if (!IOS) {" in fetch('/main.js')[2] and b"replace(/,\\s*maximum-scale=1/, '')" in fetch('/main.js')[2])
check('no field is under 16px on a touch screen, so iOS never zooms in',
      b'@media(any-pointer:coarse){\n  input,select,textarea{font-size:16px!important}\n}' in fetch('/style.css')[2])
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
check('the manifest offers its shortcuts, Search first', [sc['url'] for sc in manifest['shortcuts']] == ['/search', '/list', '/browse', '/new']
      and all(0 < len(sc['short_name']) <= 12 for sc in manifest['shortcuts']))
for path, kind in [('/favicon.ico', 'image/x-icon'), ('/favicon.svg', 'image/svg+xml'), ('/apple-touch-icon.png', 'image/png'),
                   ('/og.jpg', 'image/jpeg'), ('/sw.js', 'text/javascript'), ('/robots.txt', 'text/plain; charset=utf-8'),
                   ('/offline.html', 'text/html; charset=utf-8')]:
    status, headers, _body = fetch(path)
    check(f'{path} is served as {kind}', status == 200 and headers.get('Content-Type') == kind, headers.get('Content-Type'))
check('the service worker carries this build', b'__BUILD__' not in fetch('/sw.js')[2])
imported = sorted(set(re.findall(r"from '\./([\w.-]+\.js)'", (ROOT / 'couchside' / 'main.js').read_text())))
check('every module the page imports is built and served as JavaScript', 'gestures.js' in imported
      and all(status == 200 and headers.get('Content-Type') == 'text/javascript'
              for status, headers, _body in map(fetch, (f'/{name}' for name in imported))), imported)

# The service worker keeps the page and files of one build, each checked against the hash
# build.py wrote into it, and fetches the images it keeps under a policy of its own.
from build import OWN, SHARED  # noqa: E402
status, headers, worker = fetch('/sw.js')
stamp = re.search(rb"^const VERSION = '([0-9a-f]{12})';", worker, re.M)
kept = json.loads(re.search(rb'^const FILES = (\{.*\});$', worker, re.M)[1])
check('every page says it is the build the service worker keeps', stamp and server.BUILD == stamp[1].decode()
      and all(fetch(path)[1].get('X-Build') == server.BUILD for path in ('/', '/browse', '/?show=169')))
check('the service worker keeps every app and shared file, each with the hash of what is served',
      {f'/{name}' for name in (*OWN, *SHARED)} <= set(kept) and all(
          hashlib.sha256(fetch(path)[2]).hexdigest()[:16] == digest for path, digest in kept.items()))
check('it keeps what the offline page needs', {'/offline.html', '/style.css', '/favicon.svg'} <= set(kept))
pages = json.loads(re.search(rb'^const PAGES = (\[.*\]);$', worker, re.M)[1].replace(b"'", b'"'))
check('it serves the app\'s own pages and no others', sorted(pages) == sorted(server.PAGES))
check('it may fetch the images it keeps', headers.get('Content-Security-Policy') == server.WORKER_CSP
      and all(host in server.WORKER_CSP for host in ('https://static.tvmaze.com', 'https://i.ytimg.com', 'https://image.tmdb.org')))
check("the page's own policy still connects only to this site",
      "connect-src 'self';" in fetch('/')[1].get('Content-Security-Policy', ''))

# A page or a search the browser already holds comes back as a bodiless 304.
status, headers, _body = fetch('/')
tag = headers.get('ETag')
status, again, body = fetch('/', headers={'If-None-Match': tag})
check('a page the browser holds is a bodiless 304 that names its tag and build', tag and status == 304 and body == b''
      and again.get('ETag') == tag and again.get('X-Build') == server.BUILD)
check('a page is still checked every time', headers.get('Cache-Control') == 'no-cache')
check('a weak tag, or one of several, counts too', fetch('/', headers={'If-None-Match': f'"other", W/{tag}'})[0] == 304)
check('another tag, or another page, is sent whole', fetch('/', headers={'If-None-Match': '"other"'})[0] == 200
      and fetch('/?show=169', headers={'If-None-Match': tag})[0] == 200)
status, _headers, body = fetch('/', method='HEAD', headers={'If-None-Match': tag})
check('a HEAD honours the tag too', status == 304 and body == b'')
status, headers, body = fetch('/api/search?q=stranger%20things')
check('browsers keep a search five minutes, with a tag', status == 200 and json.loads(body)['shows']
      and headers.get('Cache-Control') == 'public, max-age=300' and headers.get('ETag'))
status, again, body = fetch('/api/search?q=stranger%20things', headers={'If-None-Match': headers['ETag']})
check('a search asked again with its tag is a bodiless 304', status == 304 and body == b''
      and again.get('Cache-Control') == 'public, max-age=300')
check('another search has another tag', fetch('/api/search?q=the%20office')[1].get('ETag') not in (None, headers['ETag']))
check('a refused search is not kept', fetch('/api/search?q=' + 'x' * 101)[1].get('Cache-Control') == 'no-store')
check('robots stay out of the api', b'Disallow: /api/' in fetch('/robots.txt')[2])
check('powerful features are switched off', 'camera=()' in fetch('/')[1].get('Permissions-Policy', ''))
check('the engine sources are not served', fetch('/engine.py')[0] == 404 and fetch('/art.bin.gz')[0] == 404)
status, _headers, body = fetch('/api/search?q=breaking%20bad')
found = json.loads(body)['shows']
check('search returns cards with posters', status == 200 and found[0]['id'] == 169 and found[0]['poster'])
status, _headers, body = fetch('/api/search?q=money%20heist')
found = json.loads(body)
check('search finds a show by another of its titles, as a card that says which',
      status == 200 and found['shows'][0]['id'] == 27436 and found['shows'][0]['aka'] == 'Money Heist'
      and found['shows'][0]['poster'] and found['missing'] == [] and tvmaze_asked == [])
check('typos, spacing and longer titles all find their show', [
    json.loads(fetch('/api/search?q=' + q)[2])['shows'][0]['id']
    for q in ('stranger%20thigns', 'sponge%20bob', 'Demon%20Slayer%3A%20Kimetsu%20no%20Yaiba', 'shogun%201980')]
    == [2993, 713, 41469, 10460])
tvmaze_asked.clear()
status, _headers, body = fetch('/api/search?q=kimetsu%20no%20yaiba')
found = json.loads(body)
check("a search the catalogue cannot place asks TVmaze, whose match leads as a card",
      status == 200 and len(tvmaze_asked) == 1 and found['shows'][0]['id'] == 41469 and found['shows'][0]['poster'])
check('a show too new for the catalogue comes back as missing, with its TVmaze page', found['missing'] == [
    {'id': 900000001, 'name': 'Kimetsu Academy', 'year': 2026, 'url': NEW_SHOW['url']}])
status, _headers, body = fetch('/api/search?q=xyzzyq')
check('TVmaze failing is an empty answer, not an error', status == 200
      and json.loads(body) == {'shows': [], 'missing': [], 'missing_first': False})
status, _headers, body = fetch('/api/home', {'profile': PROFILE, 'settings': DEFAULT_SETTINGS})
check('home answers over HTTP', status == 200 and json.loads(body)['personal'] is True)
answer = json.loads(body)
shown_rows = [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:6]]} for r in answer['rows']]
status, _headers, body = fetch('/api/home', {'profile': PROFILE, 'settings': DEFAULT_SETTINGS, 'shown': shown_rows,
                                             'day': '2026-10-05', 'seed': '0123456789abcdef', 'lang': ['fr-CA'],
                                             'seen': {'169': 2.5}, 'engaged': [82], 'resting': [44933], 'tired': ['gems']})
check('the next rows come over HTTP, with no hero', status == 200 and json.loads(body)['rows']
      and 'hero' not in json.loads(body))
check('a malformed shown list is a 400 that says why',
      fetch('/api/home', {'profile': [], 'shown': [{'key': 'no spaces'}]}) [:3:2] == (400, b'{"error":"Each shown row needs a key of lower-case letters, digits and hyphens."}'))
check('a malformed day is a 400', fetch('/api/home', {'profile': [], 'day': 'Monday', 'seed': '0123456789abcdef'})[0] == 400)
check('a body over 64KB is refused', fetch('/api/home', b'{"profile": [], "x": "' + b'y' * 66000 + b'"}')[0] == 413)
# The most a browser at the foot of a page can send: every row with the longest key, and the
# longest lists of what it has seen, engaged with and passed over.
longest_ids = sorted((s['id'] for s in engine.shows), reverse=True)
largest = {'profile': [{'id': i, 'weight': .35} for i in longest_ids[:60]], 'settings': DEFAULT_SETTINGS,
           'list': longest_ids[60:260], 'day': '2026-10-05', 'seed': '0123456789abcdef', 'lang': ['en-GB'] * 8,
           'count': NEXT_PAGE, 'seen': {str(i): 49.99 for i in longest_ids[:300]}, 'engaged': longest_ids[:300],
           'resting': longest_ids[:60], 'tired': [f'{n:02d}' + 'x' * 58 for n in range(40)],
           'shown': [{'key': f'{n:03d}' + 'x' * 57, 'ids': longest_ids[:GLANCE], 'tier': TIERS} for n in range(LONGEST)]}
status, _headers, body = fetch('/api/home', largest)
check('the largest request a page can send fits under the limit', len(json.dumps(largest)) < server.MOST_BODY
      and status == 200 and json.loads(body)['more'] is False, (len(json.dumps(largest)), status, body[:80]))
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

# 7a. First-visit starters: poster cards, drawn per visitor, adapting to picks.
def starters(query, headers=None):
    status, headers, body = fetch('/api/starters?' + query, headers=headers)
    return status, headers, json.loads(body)


SEED = '0123456789abcdef'
status, headers, first = starters(f'seed={SEED}&lang=en-US')
cards = first['shows']
check('starters answer 24 poster cards, each saying why it is there', status == 200 and len(cards) == 24
      and all(c['poster'] and c['name'] and c['why'] in ('anchor', 'facet', 'explore') for c in cards)
      and len({c['id'] for c in cards}) == 24)
check('starters are never cached', headers.get('Cache-Control') == 'no-store')
check('the same seed gives the same starters', starters(f'seed={SEED}&lang=en-US')[2] == first)
check('another visitor gets others', len({c['id'] for c in cards} & {c['id'] for c in starters(
    'seed=fedcba9876543210&lang=en-US')[2]['shows']}) < 12)
picked = cards[4]['id']
after = starters(f'seed={SEED}&lang=en-US&picked={picked}')[2]['shows']
check('a pick stays in its place, and three others swap for a contrast, a neighbour and an unexplored kind',
      after[4]['id'] == picked and after[4]['why'] == 'picked' and sorted(
          a['why'] for a, b in zip(after, cards) if a['id'] != b['id'] and a['id'] != picked)
      == ['contrast', 'nearest', 'unexplored'])
check('the next round shows different shows', len({c['id'] for c in cards} & {
    c['id'] for c in starters(f'seed={SEED}&lang=en-US&round=1')[2]['shows']}) <= 3)
korean = starters(f'seed={SEED}', headers={'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'})[2]['shows']
check('without lang the Accept-Language header speaks: seven Korean starters', sum(
    engine.shows[engine.by_id[c['id']]]['language'] == 'Korean' for c in korean) >= 7
      and sum(c['why'] == 'locale' for c in korean) == 7)
check('a seedless request gets the plain screen, the Stranger Things poster from this model\'s art in round 1',
      any(str(MOVED_POSTER) in (c['poster'] or '') for c in starters('round=1')[2]['shows']))
for query, what in [('seed=xyz', 'a bad seed'), ('round=51', 'a round past 50'), ('picked=1,x', 'a bad pick'),
                    ('picked=' + ','.join(map(str, range(1, 22))), 'too many picks'), ('lang=en_GB', 'a bad language'),
                    ('lang=' + 'a' * 36, 'a long language tag'), ('count=100', 'too many starters')]:
    status, _headers, body = starters(query)
    check(f'starters refuse {what}', status == 400 and body['error'])

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
check('and its fallback starters, with the posters of the model it loaded',
      [c['id'] for c in boot['starters']] == [c['id'] for c in lib.starters]
      and all(c['poster'] == lib.poster(engine.by_id[c['id']]) for c in boot['starters']))
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
      all(fetch(path)[0] == 404 for path in ('/tmdb.py', '/follow.py', '/facets.py', '/titles.py', '/fallback.py',
                                             '/tmdb.json.gz', '/build.json', '/facets.bin.gz', '/facets.json.gz',
                                             '/search.json.gz', '/starters.py')))
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
