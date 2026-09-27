"""Check Couchside's shelves, title pages, live details and server.

Run from the repository root:  .venv/bin/python couchside/test_couchside.py
Nothing here reaches TVmaze: the live client is driven by a fake.
"""
from http.server import ThreadingHTTPServer
from functools import partial
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import re
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'couchside'))

import server                                                    # noqa: E402
from engine import DEFAULT_SETTINGS                              # noqa: E402
from library import ROW, MORE, GLANCE, SHORTEST, GENRE_ROWS, NEW_DAYS, lower_first  # noqa: E402
from live import (Live, LiveError, Icons, trim_show, trim_episodes, trim_videos,        # noqa: E402
                  trim_seasons, match_rating, IMAGES)
from datetime import date                                        # noqa: E402

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

# 2. The art track lines up with the catalog.
poster = lib.poster(engine.by_id[169])
check('posters rebuild to TVmaze image URLs',
      bool(re.fullmatch(r'https://static\.tvmaze\.com/uploads/images/medium_portrait/\d+/\d+\.jpg', poster or '')), poster)
check('originals share the id and bucket', lib.poster(engine.by_id[169], 'original_untouched') == poster.replace('medium_portrait', 'original_untouched'))
check('most shows have a poster', sum(1 for i in lib.images if i) / engine.n > .85)
check('an ended show knows when it ended', lib.ended[engine.by_id[169]] >= 2013)

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
check('rows follow the shows you loved first', seeds[:2] == ['Because you loved Severance', 'Because you loved Breaking Bad'], seeds)
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
server.LIVE = Live(fetch=fake)
server.KINO = Live(fetch=lambda path: {'trailer': {'youtube_video_id': 'CCCCCCCCCCC', 'categories': ['Trailer']}}
                   if 'tt0903747' in path else {'trailer': None, 'videos': []})
server.STORE = Live(fetch=lambda path: {'results': [
    {'artistName': 'Breaking Bad', 'contentAdvisoryRating': 'TV-MA', 'releaseDate': '2012-07-15T07:00:00Z',
     'collectionViewUrl': 'https://itunes.apple.com/us/tv-season/breaking-bad-season-5/id533936970'}]})
server.ICONS = Icons(fetch=lambda host: ('image/png', b'\x89PNG fake'))
httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.PUBLIC)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{httpd.server_address[1]}'


def fetch(path, body=None, kind='application/json'):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    request = Request(base + path, data=data, headers={'Content-Type': kind} if data is not None else {})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


status, headers, page_root = fetch('/')
check('the page is served', status == 200 and b'id="boot"' in page_root)
policy = headers.get('Content-Security-Policy', '')
check('images come only from TVmaze and YouTube thumbnails',
      "img-src 'self' data: https://static.tvmaze.com https://i.ytimg.com;" in policy)
check('trailers play only in the no-cookie player', "frame-src https://www.youtube-nocookie.com;" in policy)
check('no referrer goes to the image server', headers.get('Referrer-Policy') == 'no-referrer')
for path in ('/new', '/list', '/search', '/browse'):
    status, _headers, body = fetch(path)
    check(f'{path} is the page too', status == 200 and body == page_root)
check('an unknown path is a 404', fetch('/nope')[0] == 404 and fetch('/list/')[0] == 404)
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
httpd.shutdown()

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
