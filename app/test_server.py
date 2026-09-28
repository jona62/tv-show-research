"""Check Next Watch's server: the page it fills in from the model it loads, the paths
that serve it, search with its TVmaze fallback, and how it follows a model replaced
while it runs.

Run from the repository root:  .venv/bin/python app/test_server.py
The server reads a temporary model laid out the way the refresher leaves one, and a
fake stands in for TVmaze: nothing here reaches the network.
"""
from datetime import date, timedelta
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import atexit
import gzip
import json
import os
import re
import shutil
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

# A model the way the refresher leaves one: a version directory with build.json written
# last, and a current link to it. It is the repository's model dated a day later, so a
# date on the page can only have come from the model the server loaded.
TMP = Path(tempfile.mkdtemp(prefix='next-watch-test-'))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
VERSION = TMP / 'versions' / '2026-09-08T040000Z'
VERSION.mkdir(parents=True)
with gzip.open(ROOT / 'model' / 'catalog.json.gz', 'rt') as f:
    catalog = json.load(f)
FROZEN_DATE = catalog['date']
MODEL_DATE = catalog['date'] = (date.fromisoformat(FROZEN_DATE) + timedelta(days=1)).isoformat()
with gzip.open(VERSION / 'catalog.json.gz', 'wt', compresslevel=1) as f:
    json.dump(catalog, f, separators=(',', ':'))
del catalog
for name in ('vectors.bin.gz', 'popularity.bin.gz'):
    try:
        os.link(ROOT / 'model' / name, VERSION / name)
    except OSError:
        shutil.copyfile(ROOT / 'model' / name, VERSION / name)
# Other titles, the way the model carries Wikidata's labels and aliases.
ALIASES = {'27436': ['Money Heist', 'Haus des Geldes'], '919': ['Shingeki no Kyojin', '進撃の巨人'],
           '103': ['Law & Order: SVU']}
with gzip.open(VERSION / 'search.json.gz', 'wt', encoding='utf-8') as f:
    json.dump({'version': 1, 'aliases': ALIASES}, f, ensure_ascii=False)
(VERSION / 'build.json').write_text(json.dumps({'version': VERSION.name, 'snapshot_date': MODEL_DATE}))
os.symlink(VERSION.relative_to(TMP), TMP / 'current')
os.environ['MODEL_DIR'] = str(TMP / 'current')

import server                                                    # noqa: E402
import follow                                                    # noqa: E402
from fallback import Remote                                      # noqa: E402
from page import boot, fill                                      # noqa: E402

# TVmaze's search, faked: Demon Slayer by its Japanese name, and a show too new for
# the catalogue.
NEW_SHOW = {'id': 900000001, 'name': 'Kimetsu Academy', 'premiered': '2026-09-26',
            'url': 'https://www.tvmaze.com/shows/900000001/kimetsu-academy'}
tvmaze_asked = []


def tvmaze(path):
    tvmaze_asked.append(path)
    if 'xyzzyq' in path:
        raise URLError('TVmaze is down')
    if 'kimetsu' not in path:
        return []
    return [{'score': 9, 'show': {'id': 41469, 'name': 'Demon Slayer', 'premiered': '2019-04-06',
                                  'url': 'https://www.tvmaze.com/shows/41469/demon-slayer'}},
            {'score': 5, 'show': NEW_SHOW}]


server.TVMAZE = Remote(fetch=tvmaze)

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


engine = server.ENGINE
PUBLIC = ROOT / 'app' / 'public'
ASSETS = ('style.css', 'main.js', 'fit.js', 'similar.js', 'transfer.js', 'qr.js', 'fresh.js', 'visits.js', 'favicon.svg')

# 1. The model is the one MODEL_DIR leads to, read from where the link led at startup.
check('the server reads the version the link leads to', server.MODEL == Path(os.path.realpath(VERSION)))
check('the catalog is that model\'s', engine.date == MODEL_DATE != FROZEN_DATE)

# 2. The built page leaves the model's figures to the server, but carries its size badge.
built = (PUBLIC / 'index.html').read_text()
check('the built page leaves the model to the server',
      {'__BOOTSTRAP__', '__CATALOG_COUNT__', '__DATASET_DATE__'} <= set(re.findall(r'__[A-Z_]+__', built)))
check('the size badge is settled at build time', '__PAGE_SIZE__' not in built and re.search(r'loads \d+\.\d KB', built))

# 3. The server end to end.
httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.PUBLIC)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{httpd.server_address[1]}'


def fetch(path, method=None):
    try:
        with urlopen(Request(base + path, method=method), timeout=30) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


status, headers, page = fetch('/')
check('the page is served as HTML', status == 200 and headers.get('Content-Type') == 'text/html; charset=utf-8'
      and page == server.PAGE)
check('no placeholder survives', not re.search(rb'__[A-Z_]+__', page))
data = json.loads(re.search(rb'<script type="application/json" id="boot">(.*?)</script>', page, re.S)[1])
check('the boot data is the loaded model\'s', data == json.loads(json.dumps(boot(engine)))
      and data['date'] == MODEL_DATE and data['catalog_count'] == engine.n and data['picks'])
check('the footer and How this works state the loaded model\'s date and count',
      f'snapshot {MODEL_DATE}'.encode() in page and f'{engine.n:,} television series'.encode() in page)
for path in ('/saved', '/taste', '/shows', '/index.html'):
    status, headers, body = fetch(path)
    check(f'{path} is the page too', status == 200 and body == page
          and headers.get('Content-Type') == 'text/html; charset=utf-8')
for path in ('/', '/taste'):
    status, headers, body = fetch(path, method='HEAD')
    check(f'a HEAD for {path} answers without a body', status == 200 and body == b''
          and int(headers['Content-Length']) == len(page))
check('pages are revalidated, not cached', fetch('/')[1].get('Cache-Control') == 'no-cache')
check('the policy is unchanged', fetch('/')[1].get('Content-Security-Policy') ==
      "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
      "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
for name in ASSETS:
    status, _headers, body = fetch(f'/{name}')
    check(f'/{name} is served as built', status == 200 and body == (PUBLIC / name).read_bytes())
check('a tab path with a trailing slash leads nowhere', fetch('/saved/')[0] == 404)
check('an unknown path is a 404', fetch('/nope')[0] == 404)
check('sources and the model are not served', all(fetch(path)[0] == 404 for path in (
    '/server.py', '/page.py', '/follow.py', '/engine.py', '/titles.py', '/fallback.py', '/model/catalog.json.gz',
    '/model/search.json.gz', '/build.json')))
check('the health check answers', json.loads(fetch('/healthz')[2]) == {'status': 'ok'})
check('search answers from the loaded model', json.loads(fetch('/api/search?q=breaking%20bad')[2])['shows'][0]['id'] == 169)


def search(q):
    status, headers, body = fetch('/api/search?q=' + quote(q))
    return status, headers, json.loads(body)


status, headers, found = search('money heist')
check('search finds a show by another of its titles, and says which',
      status == 200 and found['shows'][0]['id'] == 27436 and found['shows'][0]['aka'] == 'Money Heist'
      and found['missing'] == [])
check('search answers are never cached', headers.get('Cache-Control') == 'no-store')
check('a show found by its own name carries no aka', 'aka' not in search('la casa de papel')[2]['shows'][0])
check('other titles in any script', search('進撃の巨人')[2]['shows'][0]['id'] == 919
      and search('law and order svu')[2]['shows'][0]['aka'] == 'Law & Order: SVU')
for q, want in [('greys anatomy', 67), ('sucession', 23470), ('brooklyn 99', 49), ('the last of', 46562),
                ('Demon Slayer: Kimetsu no Yaiba', 41469), ('doctor who 1963', 766)]:
    check(f'search finds {q!r}', search(q)[2]['shows'][0]['id'] == want)
tvmaze_asked.clear()
search('the office')
search('breaking b')
check('a search the catalogue answers well never asks TVmaze', tvmaze_asked == [])
status, _headers, found = search('kimetsu no yaiba')
check('a search it cannot place asks TVmaze once', len(tvmaze_asked) == 1 and 'kimetsu' in tvmaze_asked[0])
check("TVmaze's match in the catalogue leads, as an ordinary card", status == 200 and found['shows'][0]['id'] == 41469
      and set(found['shows'][0]) >= {'id', 'name', 'year', 'channel', 'known'})
check('a show TVmaze has and the catalogue does not yet comes back as missing, with its page', found['missing'] == [
    {'id': 900000001, 'name': 'Kimetsu Academy', 'year': 2026, 'url': NEW_SHOW['url']}]
    and found['missing_first'] is False)
search('kimetsu no yaiba')
check('the same search again is answered from the cache', len(tvmaze_asked) == 1)
status, _headers, found = search('xyzzyq')
NOTHING = {'shows': [], 'missing': [], 'missing_first': False}
check('TVmaze down is an empty answer, not an error', status == 200 and found == NOTHING)
check('an overlong search is refused', fetch('/api/search?q=' + 'x' * 101)[0] == 400)
check('an empty search finds nothing', search('')[2] == NOTHING)
first_load = len(page) + sum((PUBLIC / name).stat().st_size for name in ASSETS)
badge = float(re.search(rb'loads (\d+\.\d) KB', page)[1])
check('the size badge states the page as served, under the budget',
      abs(badge * 1000 - first_load) < 200 and first_load < 512_000, (badge, first_load))


def recommend(payload):
    request = Request(base + '/api/recommend', data=json.dumps(payload).encode(), method='POST',
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, response.headers, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, exc.headers, json.loads(exc.read())


# Freshness rides in the request: the day, its seed, what was shown and engaged with.
LIST = [{'id': 169, 'weight': 1}, {'id': 82, 'weight': .7}, {'id': 80, 'weight': -1}]
TODAY = {'day': '2026-10-05', 'seed': '0123456789abcdef', 'seen': {'1871': 2.5, '179': .4}, 'engaged': [179],
         'resting': [], 'tired': []}
status, headers, plain = recommend({'profile': LIST, 'settings': {}})
check('picks come back as ranked when a request says nothing of freshness',
      status == 200 and len(plain['picks']) == 24 and 'fresh' not in plain and headers.get('Cache-Control') == 'no-store')
status, _headers, today = recommend({'profile': LIST, 'settings': {}, **TODAY})
check('the endpoint takes the fresh fields and echoes the day and seed',
      status == 200 and today['fresh'] == {'day': TODAY['day'], 'seed': TODAY['seed']}
      and [p['id'] for p in today['picks'][:5]] == [p['id'] for p in plain['picks'][:5]]
      and [n + 1 for n, p in enumerate(today['picks']) if p['place'] == 'different'] == [12, 20])
check('and answers the same fields the same way', recommend({'profile': LIST, 'settings': {}, **TODAY})[2] == today)
for label, extra, said in [
    ('a malformed day', {'day': '5 October'}, 'YYYY-MM-DD'),
    ('a malformed seed', {'seed': 'ABC'}, 'hexadecimal'),
    ('a seed without its day', {'day': None}, 'together'),
    ('a seen count that is not a number', {'seen': {'1871': 'often'}}, '0 to 50'),
    ('engaged titles by name', {'engaged': ['Lost']}, 'show ids'),
    ('row keys that are not keys', {'tired': ['Top Picks!']}, 'row keys'),
]:
    status, _headers, answer = recommend({'profile': LIST, 'settings': {}, **TODAY, **extra})
    check(f'the endpoint refuses {label} with the reason', status == 400 and said in answer.get('error', ''), answer)
httpd.shutdown()

# 4. Whatever model is loaded fills the page, and nothing in it can end the boot block.
stand_in = type('Model', (), {
    'n': 12345, 'date': '2031-02-03', 'metadata': {'language': [], 'type': [], 'status': []},
    'themes': [], 'genres': [], 'quick_picks': [{'id': 1, 'name': '</script><!--<script>'}]})()
filled = fill(built, stand_in)
check('the page takes any model\'s date and count', 'snapshot 2031-02-03' in filled and '12,345 television series' in filled)
check('a show name cannot close the boot block',
      json.loads(re.search(r'id="boot">(.*?)</script>', filled, re.S)[1])['picks'][0]['name'] == '</script><!--<script>')

# 5. Following the model: leave for a complete new one, and for nothing else.
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
