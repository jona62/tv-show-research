"""Check the model refresher, its TMDB step, its Wikidata and film steps and its
clickstream step, with the network and the builds faked.

Run from the repository root:  .venv/bin/python scripts/test_refresher.py

Nothing here reaches TVmaze, TMDB, Wikidata or Wikimedia's dumps. The build steps are
stand-ins that write small but well-formed model files, and TMDB, the Wikidata query
service and the clickstream dumps are pretend servers. Validation, the facet and
co-interest builds and carrying TMDB data forward really run, as child processes, the
way the service runs them, and so do the Wikidata, film and clickstream fetches and the
film build where a test asks for them.

TV_FULL_TEST=1 adds an end-to-end check: the real build steps, driven by the refresher,
against the TVmaze pages in data/raw (or TV_FULL_RAW) into a temporary MODEL_ROOT, and a
rebuild with the scripts' default paths, which must reproduce the committed model.
"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import ProxyHandler, Request, build_opener
import filecmp
import gzip
import http.client
import io
import json
import os
import re
import runpy
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import clickstream                                              # noqa: E402
import facets                                                   # noqa: E402
import refresher                                                # noqa: E402
import tmdb                                                     # noqa: E402
import wikidata                                                 # noqa: E402

NOW = datetime.now(timezone.utc).replace(microsecond=0)
KEY_V3 = '0123456789abcdef0123456789abcdef'
KEY_V4 = 'eyJhbGciOiJIUzI1NiJ9.a-read-access-token.signature'
BUILD_KEYS = ['version', 'built_at', 'snapshot_date', 'shows', 'pipeline', 'seeded_from', 'tmdb', 'facets',
              'cointerest', 'films', 'neighbours']
# The clickstream months the pretend listing names, and a month's counts between three shows.
PUBLISHED = ['2026-06', '2026-07', '2026-08']
COUNTS = {'1-2': 120, '1-3': 30, '2-3': 60}
RECORD_KEYS = ['tmdb_id', 'fetched_at', 'rating', 'watch_link', 'providers', 'trailers', 'backdrop',
               'vote_average', 'vote_count']
TMP = Path(tempfile.mkdtemp(prefix='refresher-test-'))
OPENER = build_opener(ProxyHandler({}))
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def rejects(label, fn, error, said):
    try:
        fn()
        check(label, False, 'accepted')
    except error as exc:
        check(label, said in str(exc), str(exc))


def wait_for(condition, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(.02)
    return False


# Small model files -------------------------------------------------------------------

def gz(path, body):
    Path(path).write_bytes(gzip.compress(body, mtime=0))


def gunzip(path):
    return gzip.decompress(Path(path).read_bytes())


def write_catalog(folder, ids, date=None):
    shows = [{'id': i, 'name': f'Show {i}', 'genres': []} for i in ids]
    date = date or NOW.strftime('%Y-%m-%d')
    gz(Path(folder) / 'catalog.json.gz', json.dumps({
        'version': f'tvmaze-v2-{date}', 'date': date, 'shows': shows, 'genres': [], 'themes': [],
        'text_features': 5, 'metadata': {}}).encode())


def write_vectors(folder, rows, features=5, nnz=0):
    gz(Path(folder) / 'vectors.bin.gz',
       struct.pack('<III', rows, features, nnz) + bytes(4 * ((rows + 1) + 2 * nnz + (features + 1) + 2 * nnz)))


def write_popularity(folder, rows):
    gz(Path(folder) / 'popularity.bin.gz', bytes([50]) * rows)


def write_art(path, rows):
    gz(path, b'ART1' + struct.pack('<I', rows) + bytes(6 * rows))


def write_neighbours(folder, rows, width=4):
    """A neighbour index as build_neighbours.py writes one: each show's next few shows."""
    index = [(i + k) % rows for i in range(rows) for k in range(1, width + 1)]
    degree = [0] * rows
    for j in index:
        degree[j] += 1
    count = rows * width
    gz(Path(folder) / 'neighbours.bin.gz', struct.pack('<4sII', b'NBR1', rows, width)
       + struct.pack(f'<{count}I', *index) + bytes([60]) * count + bytes([40]) * count + bytes(count)
       + struct.pack(f'<{rows}H', *degree))


def write_model(folder, count, art=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    write_catalog(folder, range(1, count + 1))
    write_vectors(folder, count)
    write_popularity(folder, count)
    if art:
        write_art(folder / 'art.bin.gz', count)
    return folder


def catalog_count(folder):
    return len(json.loads(gunzip(Path(folder) / 'catalog.json.gz'))['shows'])


def write_raw(folder, count=None, shows=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    shows = shows or [{'id': i, 'name': f'Show {i}', 'weight': 70, 'externals': {'imdb': f'tt{1000000 + i}'}}
                      for i in range(1, count + 1)]
    (folder / 'page-000.json').write_text(json.dumps(shows))
    (folder / 'manifest.json').write_text(json.dumps({
        'source': 'test', 'retrieved_utc': NOW.isoformat(), 'pages': 1, 'records': len(shows),
        'files': {'page-000.json': 'test'}}))
    return folder


def tmdb_record(show_id, fetched=NOW):
    return {'tmdb_id': 1000 + show_id, 'fetched_at': tmdb.iso(fetched), 'rating': 'TV-14', 'watch_link': None,
            'providers': [], 'trailers': [], 'backdrop': None, 'vote_average': 7.5, 'vote_count': 12}


def write_tmdb(folder, records, fetched=NOW):
    gz(Path(folder) / 'tmdb.json.gz', json.dumps({'fetched_at': tmdb.iso(fetched), 'region': 'US',
                                                   'shows': records}).encode())


# The refresher, with its build steps faked --------------------------------------------

def result(code=0, tail=('ok',), peak=12.5):
    return {'returncode': code, 'seconds': 0.01, 'peak_mb': peak, 'tail': list(tail), 'timed_out': False}


def small_cache(ids, fetched=NOW):
    """A Wikidata cache as wikidata.py writes one: every show a drama, three actors
    shared around, and a German name each."""
    labels = {'Q900001': 'drama television series', 'Q900100': 'Actor A', 'Q900101': 'Actor B', 'Q900102': 'Actor C'}
    shows = {str(i): {'qid': f'Q{i}', 'via': 'p8600', 'genre': ['Q900001'], 'cast': [f'Q{900100 + i % 3}'],
                      'names': [['de', f'Sendung {i}'], ['en', f'Show {i}']]} for i in ids}
    return {'version': 1, 'fetched_at': refresher.iso(fetched), 'source': 'https://www.wikidata.org',
            'license': 'CC0-1.0', 'mapped': {'p8600': len(shows), 'imdb': 0}, 'labels': labels, 'parents': {},
            'belongs': {}, 'shows': shows}


def small_films(count=3, fetched=NOW):
    """A film cache as films.py writes one: count crime films, the first two a series's."""
    films_found = {f'Q{800000 + n}': {'kind': 'film', 'links': 40 - n, 'year': 1990 + n, 'genre': ['Q900002'],
                                      'names': [['label', 'en', f'Film {n}']], **({'part_of': ['Q800100']} if n < 3 else {})}
                   for n in range(1, count + 1)}
    films_found['Q800100'] = {'kind': 'series', 'links': 9, 'names': [['label', 'en', 'Film Series']]}
    return {'version': 1, 'fetched_at': refresher.iso(fetched), 'source': 'https://www.wikidata.org',
            'license': 'CC0-1.0', 'labels': {'Q900002': 'crime film'}, 'parents': {}, 'films': films_found}


def write_films(folder, count=3, fetched=NOW):
    """A films.json.gz as build_films.py writes one."""
    found = [{'qid': f'Q{800000 + n}', 'title': f'Film {n}', 'titles': [], 'aliases': [], 'kind': 'film',
              'links': 40 - n, 'animated': False, 'genre': {'crime': 1.0}, 'subject': {}, 'topics': [], 'year': 1990 + n}
             for n in range(1, count + 1)]
    gz(Path(folder) / 'films.json.gz', json.dumps({'version': 1, 'date': NOW.strftime('%Y-%m-%d'),
                                                    'wikidata_fetched_at': refresher.iso(fetched), 'films': found}).encode())


class FakeRunner:
    """Stands in for the build subprocesses. Validation, the facet and co-interest builds
    and the TMDB carry really run; so do the Wikidata, film and clickstream fetches and the
    film build when real_wikidata, real_films and real_clickstream are set, and otherwise
    small caches and a small film index stand in for them, the clickstream one holding the
    months in self.published."""

    def __init__(self, shows=100, fail=None, hold=None, real_wikidata=False, real_clickstream=False, real_films=False):
        self.shows, self.fail, self.hold = shows, fail, hold
        self.calls = []
        self.real = refresher.Processes()
        self.real_steps = (('validate', 'tmdb carry', 'build_facets', 'build_cointerest')
                           + (('wikidata',) if real_wikidata else ())
                           + (('films', 'build_films') if real_films else ())
                           + (('clickstream check', 'clickstream') if real_clickstream else ()))
        self.popularity_shows = None
        self.tmdb_code, self.tmdb_error = 0, None
        self.cache_shows = None
        self.film_count = 3
        self.published = list(PUBLISHED)

    def names(self):
        return [call['name'] for call in self.calls]

    def env_for(self, name):
        return next(call['env'] for call in reversed(self.calls) if call['name'] == name)

    def run(self, name, argv, env, cwd, timeout, log):
        self.calls.append({'name': name, 'argv': list(argv), 'env': dict(env)})
        if name == self.fail:
            return result(1, [f'{name} fell over'])
        if name in self.real_steps:
            return self.real.run(name, argv, env, cwd, timeout, log)
        if self.hold is not None and name == 'build_model':
            self.hold.wait(30)
        if name == 'download':
            write_raw(argv[argv.index('--out') + 1], self.shows)
        elif name == 'build_model':
            out = Path(env['TV_MODEL_OUT'])
            write_catalog(out, range(1, self.shows + 1))
            write_vectors(out, self.shows)
            (Path(env['TV_AUDIT_DIR']) / 'catalog-audit.json').write_text(
                json.dumps({'searchable_shows': self.shows, 'recommendable_shows': self.shows - 3}))
        elif name == 'build_popularity':
            write_popularity(env['TV_MODEL_OUT'], self.popularity_shows or catalog_count(env['TV_MODEL_OUT']))
        elif name == 'build_art':
            write_art(Path(env['TV_ART_OUT']), catalog_count(env['TV_MODEL_OUT']))
        elif name == 'build_neighbours':
            write_neighbours(env['TV_MODEL_OUT'], catalog_count(env['TV_MODEL_OUT']))
        elif name == 'wikidata':
            cache = small_cache(range(1, (self.cache_shows or self.shows) + 1))
            Path(argv[argv.index('--out') + 1]).write_bytes(wikidata.encode(cache))
            return result(0, ['RESULT ' + json.dumps({'fetched_at': cache['fetched_at'], 'shows': len(cache['shows']),
                                                      'mapped': cache['mapped']})])
        elif name == 'films':
            cache = small_films(self.film_count)
            Path(argv[argv.index('--out') + 1]).write_bytes(wikidata.encode(cache))
            return result(0, ['RESULT ' + json.dumps({'fetched_at': cache['fetched_at'], 'films': len(cache['films']),
                                                      'series': 1})])
        elif name == 'build_films':
            # As many films as the cache it is given holds, less its series.
            held = json.loads(gunzip(env['TV_FILMS']))['films']
            write_films(env['TV_MODEL_OUT'], len(held) - 1)
        elif name == 'clickstream check':
            return result(0, ['RESULT ' + json.dumps({'published': self.published[-3:]})])
        elif name == 'clickstream':
            path = Path(argv[argv.index('--cache') + 1])
            held = clickstream.read(path) or {'version': 1, 'titles': {}, 'months': {}}
            wanted = self.published[-int(argv[argv.index('--months') + 1]):]
            fetched = [month for month in wanted if month not in held['months']]
            held['titles'] = {str(i): f'Show_{i}' for i in range(1, self.shows + 1)}
            held['months'].update({month: dict(COUNTS) for month in fetched})
            clickstream.write(path, held)
            return result(0, ['RESULT ' + json.dumps({'months': sorted(held['months']), 'wanted': wanted,
                                                      'fetched': fetched, 'skipped': {}, 'titles': self.shows})])
        elif name == 'tmdb':
            folder = Path(argv[argv.index('--version') + 1])
            log(f"calling TMDB with {env.get('TMDB_API_KEY')}")
            write_tmdb(folder, {str(i): tmdb_record(i) for i in (1, 2)})
            return result(self.tmdb_code, ['RESULT ' + json.dumps(
                {'fetched': 2, 'shows': 2, 'fetched_at': tmdb.iso(NOW), 'error': self.tmdb_error})])
        return result()

    def stop(self):
        if self.hold is not None:
            self.hold.set()


def make(name, runner=None, seed=None, **env):
    settings = {'MODEL_ROOT': str(TMP / name), 'SEED_MODEL_DIR': str(seed or TMP / f'{name}-no-seed'),
                'AUTO_DELAY_SECONDS': '0', **{k: str(v) for k, v in env.items()}}
    r = refresher.Refresher(refresher.Config(settings), runner or FakeRunner(), lambda: NOW, quiet=True)
    r.start(schedule=False)
    return r


def run(r, kind='full', trigger='manual', timeout=120):
    started = r.start_run(kind, trigger)
    if started is None:
        raise AssertionError('a run should have started')
    r.thread.join(timeout)
    return r.state['runs'][0]


def live(r):
    return os.readlink(r.root / 'current') if (r.root / 'current').is_symlink() else None


def add_version(r, stamp, shows=100, pipeline=None, seeded=None, built_at=NOW, records=None, fetched=NOW):
    folder = write_model(r.versions / stamp, shows)
    if records:
        write_tmdb(folder, records, fetched)
    (folder / 'build.json').write_text(json.dumps({
        'version': stamp, 'built_at': refresher.iso(built_at), 'snapshot_date': NOW.strftime('%Y-%m-%d'),
        'shows': shows, 'pipeline': pipeline or r.pipeline, 'seeded_from': seeded,
        'tmdb': {'fetched_at': None, 'shows': 0}}))
    return folder


def readable(root):
    """Every file and folder under root can be read by other users."""
    for path in [Path(root), *Path(root).rglob('*')]:
        if path.is_symlink() or path.name == '.lock':
            continue
        mode = path.stat().st_mode
        if not mode & stat.S_IROTH or (path.is_dir() and not mode & stat.S_IXOTH):
            return path
    return None


# 1. The study copies --------------------------------------------------------------------

for name in ('theme_rules.json', 'audit.json'):
    original, copy = ROOT / 'output' / name, SCRIPTS / 'study' / name
    if original.exists() and copy.exists():
        check(f'scripts/study/{name} matches output/{name}', original.read_bytes() == copy.read_bytes())
    else:
        check(f'scripts/study/{name} is present', copy.exists())
check('scripts/facets.py is app/facets.py, the reader the apps load the model with',
      (SCRIPTS / 'facets.py').read_bytes() == (ROOT / 'app' / 'facets.py').read_bytes())
check('scripts/neighbours.py is app/neighbours.py, the reader the apps load the neighbour index with',
      (SCRIPTS / 'neighbours.py').read_bytes() == (ROOT / 'app' / 'neighbours.py').read_bytes())
check('the neighbour index is part of the pipeline', 'build_neighbours.py' in refresher.PIPELINE
      and 'build_neighbours' in refresher.TIMEOUTS)
check('the clickstream scripts are part of the pipeline, with time limits',
      {'clickstream.py', 'build_cointerest.py'} <= set(refresher.PIPELINE)
      and {'clickstream check', 'clickstream', 'build_cointerest'} <= set(refresher.TIMEOUTS))

# 2. Schedule and catch-up decisions ---------------------------------------------------------

utc = timezone.utc
at = refresher.parse_clock('04:30')
check('the daily slot later today comes first',
      refresher.next_daily(datetime(2026, 9, 28, 3, 0, tzinfo=utc), at) == datetime(2026, 9, 28, 4, 30, tzinfo=utc))
check('after the slot, the next one is tomorrow',
      refresher.next_daily(datetime(2026, 9, 28, 5, 0, tzinfo=utc), at) == datetime(2026, 9, 29, 4, 30, tzinfo=utc))
check('a moment exactly on the slot waits a day',
      refresher.next_daily(datetime(2026, 9, 28, 4, 30, tzinfo=utc), at) == datetime(2026, 9, 29, 4, 30, tzinfo=utc))
check('a one-digit hour is read', refresher.parse_clock('4:05') == (4, 5))
for bad in ('24:00', '04:60', 'half four', ''):
    rejects(f'REFRESH_AT_UTC {bad!r} is refused', lambda bad=bad: refresher.parse_clock(bad), ValueError, 'REFRESH_AT_UTC')

r = make('schedule')
check('no live version calls for a catch-up', r.needs_catch_up() == 'there is no live version')
add_version(r, '20260101T000000Z', built_at=NOW - timedelta(hours=2))
r.swap_current('20260101T000000Z')
check('a fresh build calls for nothing', r.needs_catch_up() is None)
r.state['last_success'] = {'at': refresher.iso(NOW - timedelta(hours=27))}
check('a build over 26 hours old calls for a catch-up', 'more than 26 hours' in (r.needs_catch_up() or ''))
r.state['last_success'] = {'at': refresher.iso(NOW - timedelta(hours=25))}
check('25 hours is still fresh', r.needs_catch_up() is None)
add_version(r, '20260101T010000Z', pipeline='000000000000')
r.swap_current('20260101T010000Z')
check('new pipeline code calls for a catch-up', 'pipeline changed' in (r.needs_catch_up() or ''))
add_version(r, '20260101T020000Z', seeded='/home/developer/model')
r.swap_current('20260101T020000Z')
r.state['last_success'] = None
check('a seeded version calls for a real build', 'seeded' in (r.needs_catch_up() or ''))
r.next_daily_at, r.catch_up_at, r.retry_at = NOW + timedelta(hours=9), NOW + timedelta(minutes=2), None
check('the earliest reason wins', r.next_run() == (NOW + timedelta(minutes=2), 'catch-up'))
r.retry_at = NOW + timedelta(minutes=1)
check('a retry can come first', r.next_run()[1] == 'retry')
r.catch_up_at = r.retry_at = None
check('otherwise the daily slot is next', r.next_run() == (NOW + timedelta(hours=9), 'daily'))
r.boot()
check('boot schedules the catch-up AUTO_DELAY_SECONDS after start', r.catch_up_at == r.started_at)
check('status names the next run', r.status()['next_run'] == {'at': refresher.iso(r.started_at), 'reason': 'catch-up'})

# TMDB switched on after the live version was built: fetch it without waiting for the night.
r = make('tmdb-on', TMDB_API_KEY='v3-key-for-tests-0000000000000000')
add_version(r, '20260101T000000Z', built_at=NOW - timedelta(hours=2))
r.swap_current('20260101T000000Z')
r.state['last_success'] = {'at': refresher.iso(NOW - timedelta(hours=2))}
check('TMDB on with no TMDB data calls for a TMDB run', 'no TMDB data' in (r.needs_tmdb() or ''))
r.boot()
check('boot schedules the TMDB run, not a full one', r.tmdb_at == r.started_at and r.catch_up_at is None)
check('the TMDB run is next', r.next_run() == (r.started_at, 'tmdb'))
check('status explains it', r.status()['next_run']['reason'] == 'tmdb')
off = make('tmdb-off')
add_version(off, '20260101T000000Z', built_at=NOW - timedelta(hours=2))
off.swap_current('20260101T000000Z')
off.state['last_success'] = {'at': refresher.iso(NOW - timedelta(hours=2))}
off.boot()
check('without a key there is no TMDB run', off.needs_tmdb() is None and off.tmdb_at is None)
has = make('tmdb-has', TMDB_API_KEY='v3-key-for-tests-0000000000000000')
folder = add_version(has, '20260101T000000Z', built_at=NOW - timedelta(hours=2))
build = json.loads((folder / 'build.json').read_text())
build['tmdb'] = {'fetched_at': refresher.iso(NOW), 'shows': 40}
(folder / 'build.json').write_text(json.dumps(build))
has.swap_current('20260101T000000Z')
check('a version that already has TMDB data needs none', has.needs_tmdb() is None)
stale = make('tmdb-stale', TMDB_API_KEY='v3-key-for-tests-0000000000000000')
add_version(stale, '20260101T000000Z', pipeline='000000000000')
stale.swap_current('20260101T000000Z')
stale.boot()
check('a due full build carries TMDB, so no separate run', stale.catch_up_at is not None and stale.tmdb_at is None)

# The scheduler itself: seeds at start, then catches up at once with AUTO_DELAY_SECONDS=0.
runner = FakeRunner()
r = make('scheduler', runner, seed=write_model(TMP / 'seed-scheduler', 100))
r.scheduler = threading.Thread(target=r.schedule, daemon=True)
r.scheduler.start()
wait_for(lambda: len(r.state['runs']) >= 2 and not r.busy())
r.stop()
check('the scheduler seeds, then catches up with a full build',
      [(x['kind'], x['trigger'], x['outcome']) for x in r.state['runs']]
      == [('full', 'catch-up', 'success'), ('seed', 'startup', 'success')], r.state['runs'])
check('after catching up, current is the built version', live(r) == f"versions/{r.state['runs'][0]['version']}")

# 3. Seeding -------------------------------------------------------------------------------------

seed = write_model(TMP / 'seed-a', 100, art=False)
runner = FakeRunner()
r = make('seed', runner, seed=seed)
r.boot()
cur = r.current()
check('seeding makes a live version', cur is not None and (cur['path'] / 'build.json').exists())
check('build.json has the contract keys, in order', cur is not None and list(cur['build']) == BUILD_KEYS, cur and cur['build'])
check('the seed version says where it came from', cur['build']['seeded_from'] == str(seed))
check('the pipeline hash is 12 hex digits', re.fullmatch(r'[0-9a-f]{12}', cur['build']['pipeline']) is not None)
check('a seed without art downloads pages first, then builds art', runner.names() == ['download', 'build_art', 'validate'],
      runner.names())
check('seed art is built from MODEL_ROOT/raw into the new version',
      runner.env_for('build_art')['TV_RAW_DIR'] == str(r.raw)
      and runner.env_for('build_art')['TV_ART_OUT'].endswith('.tmp/art.bin.gz'))
check('the seed keeps its model files as they were',
      filecmp.cmp(seed / 'catalog.json.gz', cur['path'] / 'catalog.json.gz', shallow=False))
check('a seeded version still wants a real build', r.catch_up_at is not None)
check('the seed run is recorded', r.state['runs'][0]['kind'] == 'seed' and r.state['runs'][0]['outcome'] == 'success')

runner = FakeRunner()
r = make('seed-art', runner, seed=write_model(TMP / 'seed-b', 100))
r.boot()
check('a seed with art needs no download', runner.names() == ['validate'] and r.current() is not None, runner.names())

r = make('no-seed')
r.boot()
check('with nothing to seed from, nothing goes live and a build is due',
      r.current() is None and r.catch_up_at is not None and not r.state['runs'])

r = make('restore')
add_version(r, '20260101T000000Z')
add_version(r, '20260102T000000Z')
r.boot()
check('a missing current is pointed at the newest complete version', live(r) == 'versions/20260102T000000Z'
      and not r.state['runs'])

# 4. A full run, the swap and pruning ---------------------------------------------------------------

runner = FakeRunner()
r = make('full', runner, seed=write_model(TMP / 'seed-full', 100))
r.boot()
seeded = live(r)
done = run(r)
check('a full run succeeds', done['outcome'] == 'success', done.get('error'))
check('current is a relative link to the new version', live(r) == f"versions/{done['version']}")
check('the swap leaves no temporary link behind', not os.path.lexists(r.root / 'current.tmp'))
check('the steps run in order', runner.names() == ['validate', 'download', 'build_model', 'build_popularity',
                                                    'build_art', 'wikidata', 'build_facets', 'films', 'build_films',
                                                    'clickstream', 'build_cointerest', 'build_neighbours', 'validate'],
      runner.names())
env = runner.env_for('build_model')
check('build steps write into the temporary version', env['TV_MODEL_OUT'].endswith(f"versions/{done['version']}.tmp")
      and env['TV_ART_OUT'] == env['TV_MODEL_OUT'] + '/art.bin.gz')
check('build steps read raw/ and scripts/study', env['TV_RAW_DIR'] == str(r.raw)
      and env['TV_MANIFEST'] == str(r.raw / 'manifest.json') and env['TV_STUDY_DIR'] == str(SCRIPTS / 'study'))
check('audit files go to a scratch folder inside the temporary version',
      env['TV_AUDIT_DIR'] == env['TV_MODEL_OUT'] + '/audit'
      and not (r.versions / done['version'] / 'audit').exists())
check('build steps run single-threaded', all(call['env'].get(v) == '1' for call in runner.calls
                                             for v in refresher.THREAD_VARS))
check('the download goes to raw.new and is swapped into raw',
      runner.calls[1]['argv'][-2:] == ['--out', str(r.root / 'raw.new')] and (r.raw / 'manifest.json').exists()
      and not os.path.lexists(r.root / 'raw.new') and not os.path.lexists(r.root / 'raw.old'))
check('a version holds the four model files, the three facet files, the two co-interest files, the film index, '
      'the neighbour index and build.json', sorted(p.name for p in (r.versions / done['version']).iterdir())
      == sorted(['build.json', *refresher.MODEL_FILES, *refresher.FACET_FILES, *refresher.COINTEREST_FILES,
                 *refresher.FILM_FILES, *refresher.NEIGHBOUR_FILES]))
build = r.current()['build']
check('build.json describes the build', list(build) == BUILD_KEYS and build['version'] == done['version']
      and build['shows'] == 100 and build['seeded_from'] is None and build['pipeline'] == r.pipeline
      and build['tmdb'] == {'fetched_at': None, 'shows': 0}
      and build['facets'] == {'tokens': 3, 'nonzeros': 100, 'linked': 100, 'aliases': 100,
                              'wikidata_fetched_at': refresher.iso(NOW)}
      and build['cointerest'] == {'months': PUBLISHED, 'shows': 3, 'links': 6}
      and build['films'] == {'films': 3, 'series': 0, 'wikidata_fetched_at': refresher.iso(NOW)}
      and build['neighbours'] == {'width': 4}, build)
check('the neighbour index is built into the temporary version, after the co-interest',
      runner.env_for('build_neighbours')['TV_MODEL_OUT'] == env['TV_MODEL_OUT'])
coi_env = runner.env_for('build_cointerest')
check('the co-interest is built into the temporary version from the clickstream cache',
      coi_env['TV_MODEL_OUT'] == env['TV_MODEL_OUT']
      and coi_env['TV_COINTEREST'] == str(r.root / 'clickstream' / 'cache.json.gz'))
check('the clickstream is fetched into its cache in place, three months of it',
      runner.calls[9]['argv'][-4:] == ['--cache', str(r.root / 'clickstream' / 'cache.json.gz'), '--months', '3'])
check('and meta.json describes the cache', json.loads((r.root / 'clickstream' / 'meta.json').read_text()) == {
    'fetched_at': refresher.iso(NOW), 'months': PUBLISHED, 'titles': 100, 'script': r.clickstream_script,
    'checked_at': refresher.iso(NOW), 'published': PUBLISHED})
check('no other build step is told where the clickstream cache is',
      all('TV_COINTEREST' not in runner.env_for(name) for name in ('build_model', 'build_popularity', 'build_art',
                                                                     'build_facets', 'build_films')))
film_env = runner.env_for('build_films')
check('the film index is built into the temporary version from the film cache, once the facets are there',
      film_env['TV_MODEL_OUT'] == env['TV_MODEL_OUT'] and film_env['TV_FILMS'] == str(r.root / 'films' / 'cache.json.gz')
      and runner.names().index('build_films') > runner.names().index('build_facets'))
check('the film fetch writes beside its cache, which then replaces the old one and is described in meta.json',
      runner.calls[7]['argv'][-2:] == ['--out', str(r.root / 'films' / 'cache.new.json.gz')]
      and (r.root / 'films' / 'cache.json.gz').is_file() and not (r.root / 'films' / 'cache.new.json.gz').exists()
      and json.loads((r.root / 'films' / 'meta.json').read_text()) == {
          'fetched_at': refresher.iso(NOW), 'films': 4, 'series': 1, 'script': r.films_script})
check('no other build step is told where the film cache is', all('TV_FILMS' not in runner.env_for(name)
      for name in ('build_model', 'build_popularity', 'build_art', 'build_facets', 'build_cointerest')))
facet_env = runner.env_for('build_facets')
check('the facets are built into the temporary version from the Wikidata cache',
      facet_env['TV_MODEL_OUT'] == env['TV_MODEL_OUT'] and facet_env['TV_RAW_DIR'] == str(r.raw)
      and facet_env['TV_WIKIDATA'] == str(r.root / 'wikidata' / 'cache.json.gz'))
check('the fetch reads MODEL_ROOT/raw and writes beside the cache',
      runner.env_for('wikidata')['TV_RAW_DIR'] == str(r.raw)
      and runner.calls[5]['argv'][-2:] == ['--out', str(r.root / 'wikidata' / 'cache.new.json.gz')])
check('a fetched cache replaces the old one and is described in meta.json',
      (r.root / 'wikidata' / 'cache.json.gz').is_file() and not (r.root / 'wikidata' / 'cache.new.json.gz').exists()
      and json.loads((r.root / 'wikidata' / 'meta.json').read_text()) == {
          'fetched_at': refresher.iso(NOW), 'shows': 100, 'mapped': {'p8600': 100, 'imdb': 0},
          'script': r.wikidata_script})
check('each step records its time', all(s['seconds'] is not None and s['outcome'] == 'ok' for s in done['steps']))
check('child steps record their peak memory', all(s['peak_mb'] for s in done['steps']), done['steps'])
log_text = (r.logs / f"{done['id']}.log").read_text()
check('the run has its own log with step timings', 'build_model: ok in' in log_text and 'peak' in log_text)
check('the log names the new version', f"current -> versions/{done['version']}" in log_text)
check('state.json keeps the run', json.loads((r.root / 'state.json').read_text())['runs'][0]['id'] == done['id'])
check('the last success is remembered', r.state['last_success']['version'] == done['version'])
check('a fresh build calls for no catch-up', r.needs_catch_up() is None)
check('everything the service writes is readable by other users', readable(r.root) is None, readable(r.root))
check('the previous version stays for rollback', (r.root / seeded).is_dir())

# A neighbour index that will not build (out of time or memory): the version goes without
# one, and the apps rank long lists from their most recent ratings; the run still succeeds.
nb_runner = FakeRunner(fail='build_neighbours')
nb = make('neighbours-fail', nb_runner, seed=write_model(TMP / 'seed-neighbours-fail', 100))
nb.boot()
nb_done = run(nb)
check('a neighbour index that will not build never fails the run', nb_done['outcome'] == 'success'
      and any('The neighbour index would not build' in w for w in nb_done['warnings']), nb_done)
check('and the version goes without one', not (nb.current()['path'] / 'neighbours.bin.gz').exists()
      and nb.current()['build']['neighbours'] is None and nb.current()['version'] == nb_done['version'])

misses = []
stop = threading.Event()


def reader():
    # Missing means ENOENT, what an unlink-then-symlink swap produces. On Linux a reader
    # sees no error at all; APFS can hand a reader racing the rename a passing EINVAL.
    while not stop.is_set():
        try:
            os.stat(r.root / 'current' / 'build.json')
        except FileNotFoundError as exc:
            misses.append(exc)
        except OSError as exc:
            if sys.platform.startswith('linux'):
                misses.append(exc)


watcher = threading.Thread(target=reader)
watcher.start()
for _ in range(300):
    r.swap_current(seeded.split('/')[1])
    r.swap_current(done['version'])
stop.set()
watcher.join()
check('a reader never finds current missing while it is swapped', not misses, misses[:1])

r = make('prune')
stamps = [f'2026010{i}T000000Z' for i in range(1, 6)]
for stamp in stamps:
    add_version(r, stamp)
r.swap_current(stamps[0])
(r.versions / '20260109T000000Z').mkdir()
r.prune()
check('pruning keeps the newest three and the live one',
      sorted(p.name for p in r.versions.iterdir()) == sorted([stamps[0], *stamps[2:]]))
check('pruning never touches what current points at', (r.root / 'current' / 'build.json').exists())

# 5. Failures leave the live version alone -------------------------------------------------------------

runner = FakeRunner(fail='build_model')
r = make('fail', runner, seed=write_model(TMP / 'seed-fail', 100))
r.boot()
before = live(r)
done = run(r)
check('a failed step fails the run', done['outcome'] == 'failed'
      and 'build_model failed with exit code 1: build_model fell over' in (done['error'] or ''), done['error'])
check('a failed run leaves current untouched', live(r) == before)
check('a failed run leaves no temporary version', not list(r.versions.glob('*.tmp')))
check('the failed step is marked', [s['outcome'] for s in done['steps']][-1] == 'failed')
check('a manual failure is not retried', r.retry_at is None)
check('the error is in the run log', 'build_model fell over' in (r.logs / f"{done['id']}.log").read_text())

runner.fail = 'download'
manifest_before = (r.raw / 'manifest.json').read_text() if (r.raw / 'manifest.json').exists() else None
done = run(r, trigger='daily')
check('a failed download keeps the previous pages', done['outcome'] == 'failed'
      and ((r.raw / 'manifest.json').read_text() if (r.raw / 'manifest.json').exists() else None) == manifest_before
      and not os.path.lexists(r.root / 'raw.new'))
check('a failed nightly run is retried two hours later', r.retry_at == NOW + refresher.RETRY)
r.retry_at = None

runner.fail, runner.popularity_shows = None, 99
done = run(r)
check('mismatched counts fail validation', done['outcome'] == 'failed' and 'Show counts disagree' in (done['error'] or ''),
      done['error'])
check('a version that fails validation never goes live', live(r) == before and not list(r.versions.glob('*.tmp')))

runner.popularity_shows, runner.shows = None, 85
done = run(r)
check('a 15% drop in shows fails validation', done['outcome'] == 'failed' and '10%' in (done['error'] or ''), done['error'])
check('and the live version stays', live(r) == before)
runner.shows = 95
check('a 5% change is accepted', run(r)['outcome'] == 'success' and live(r) != before)

# The service stopping mid-run: the child is stopped and the run marked interrupted.
hold = threading.Event()
runner = FakeRunner(hold=hold)
r = make('interrupt', runner, seed=write_model(TMP / 'seed-interrupt', 100))
r.boot()
before = live(r)
r.start_run('full', 'manual')
wait_for(lambda: 'build_model' in runner.names())
r.stop()
check('stopping mid-run marks it interrupted', r.state['runs'][0]['outcome'] == 'interrupted', r.state['runs'][0])
check('an interrupted run leaves current and no temporary version', live(r) == before and not list(r.versions.glob('*.tmp')))

# A restart keeps the history and closes a run it never finished.
saved = json.loads((r.root / 'state.json').read_text())
saved['runs'][0]['outcome'] = 'running'
(r.root / 'state.json').write_text(json.dumps(saved))
again = refresher.Refresher(r.config, FakeRunner(), lambda: NOW, quiet=True)
again.start(schedule=False)
check('a restart keeps earlier runs', [x['id'] for x in again.state['runs']] == [x['id'] for x in saved['runs']])
check('a run left running is marked interrupted on start', again.state['runs'][0]['outcome'] == 'interrupted')
again.state['last_success'] = {'at': refresher.iso(NOW - timedelta(hours=1))}
check('an interrupted build is caught up after a restart', again.needs_catch_up() == 'the last build was interrupted')
again.boot()
check('so boot schedules it', again.catch_up_at == again.started_at)

# 6. Validation -----------------------------------------------------------------------------------------

good = write_model(TMP / 'valid', 100)
found = refresher.validate_version(good)
check('a well-formed version passes', found['shows'] == 100 and found['snapshot_date'] == NOW.strftime('%Y-%m-%d'), found)
bad = write_model(TMP / 'bad-popularity', 100)
write_popularity(bad, 99)
rejects('popularity of the wrong length is refused', lambda: refresher.validate_version(bad), refresher.Invalid, 'popularity 99')
bad_art = write_model(TMP / 'bad-art', 100)
write_art(bad_art / 'art.bin.gz', 101)
rejects('art of the wrong length is refused', lambda: refresher.validate_version(bad_art), refresher.Invalid, 'art 101')
bad_vectors = write_model(TMP / 'bad-vectors', 100)
write_vectors(bad_vectors, 90)
rejects('vectors with the wrong row count are refused', lambda: refresher.validate_version(bad_vectors),
        refresher.Invalid, 'vectors 90')
short = write_model(TMP / 'short-vectors', 100)
gz(short / 'vectors.bin.gz', struct.pack('<III', 100, 5, 0) + bytes(40))
rejects('truncated vectors are refused', lambda: refresher.validate_version(short), refresher.Invalid, 'header promises')
missing = write_model(TMP / 'no-art', 100, art=False)
rejects('a missing model file is refused', lambda: refresher.validate_version(missing), refresher.Invalid, 'art.bin.gz is missing')
broken = write_model(TMP / 'broken', 100)
(broken / 'catalog.json.gz').write_bytes(b'not gzip at all')
rejects('a file that does not decompress is refused', lambda: refresher.validate_version(broken), refresher.Invalid,
        'does not decompress')
rejects('a 10.7% drop is refused', lambda: refresher.validate_version(good, 112), refresher.Invalid, 'more than 10%')
check('a 9.9% drop is accepted', refresher.validate_version(good, 111)['shows'] == 100)
rejects('growth of more than 10% is refused too', lambda: refresher.validate_version(good, 90), refresher.Invalid, '11.1%')
(TMP / 'bad-manifest.json').write_text(json.dumps({'retrieved_utc': 'yesterday'}))
rejects('a manifest date that does not parse is refused',
        lambda: refresher.validate_version(good, manifest=TMP / 'bad-manifest.json'), refresher.Invalid, 'does not parse')
(TMP / 'old-manifest.json').write_text(json.dumps({'retrieved_utc': '2020-01-01T00:00:00+00:00'}))
rejects('a manifest from another day is refused',
        lambda: refresher.validate_version(good, manifest=TMP / 'old-manifest.json'), refresher.Invalid, 'does not match')
stray = write_model(TMP / 'stray-tmdb', 100)
write_tmdb(stray, {'1': tmdb_record(1), '500': tmdb_record(500)})
rejects('TMDB data for shows outside the catalog is refused', lambda: refresher.validate_version(stray),
        refresher.Invalid, 'not in this catalog')
write_tmdb(stray, {'1': tmdb_record(1)})
check('TMDB data is counted', refresher.validate_version(stray)['tmdb'] == {'fetched_at': tmdb.iso(NOW), 'shows': 1})
check('a version without a neighbour index passes, with none', refresher.validate_version(good)['neighbours'] is None)
near = write_model(TMP / 'neighbours', 100)
write_neighbours(near, 100, width=6)
check('a neighbour index is read as the apps read it', refresher.validate_version(near)['neighbours'] == {'width': 6})
write_neighbours(near, 90)
rejects('a neighbour index for another catalog is refused', lambda: refresher.validate_version(near), refresher.Invalid,
        '90 rows')
gz(near / 'neighbours.bin.gz', struct.pack('<4sII', b'NBR1', 100, 4) + bytes(100))
rejects('a truncated neighbour index is refused', lambda: refresher.validate_version(near), refresher.Invalid,
        'rows x width')

# 7. One run at a time, and the child processes ------------------------------------------------------------

hold = threading.Event()
runner = FakeRunner(hold=hold)
r = make('busy', runner, seed=write_model(TMP / 'seed-busy', 100))
r.boot()
first = r.start_run('full', 'manual')
wait_for(lambda: 'build_model' in runner.names())
check('a second run is refused while one is going', first is not None and r.start_run('full', 'manual') is None)
other = refresher.Refresher(r.config, FakeRunner(), lambda: NOW, quiet=True)
check('a second refresher on the same MODEL_ROOT waits its turn', other.start_run('full', 'manual') is None)
status = r.status()
check('status shows the step in progress', status['status'] == 'running' and status['running']['step'] == 'build_model'
      and status['running']['kind'] == 'full', status['running'])
server = ThreadingHTTPServer(('127.0.0.1', 0), refresher.make_handler(r))
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]


def call(path, method='GET', headers=None):
    request = Request(f'http://127.0.0.1:{PORT}{path}', method=method, headers=headers or {},
                      data=b'' if method == 'POST' else None)
    try:
        with OPENER.open(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


GOOD = {'X-Requested-With': 'refresher'}
code, _headers, body = call('/api/run', 'POST', GOOD)
check('a run requested over HTTP while busy is a 409', code == 409 and b'already in progress' in body)
hold.set()
r.thread.join(30)
check('the held run then finishes', r.state['runs'][0]['outcome'] == 'success')
check('and the next may start', run(r)['outcome'] == 'success')
server.shutdown()
server.server_close()

procs = refresher.Processes()
lines = []
probe = procs.run('probe', [sys.executable, '-c', 'import os; b = bytearray(80 << 20); print(os.nice(0))'],
                  dict(os.environ), str(TMP), 60, lines.append)
check('children run niced by 10', probe['returncode'] == 0 and lines and lines[-1].endswith(str(min(19, os.nice(0) + 10))),
      lines)
check('a child\'s peak memory is measured', probe['peak_mb'] >= 80, probe['peak_mb'])
slow = procs.run('slow', [sys.executable, '-c', 'import time; time.sleep(30)'], dict(os.environ), str(TMP), 0.5,
                 lambda _line: None)
check('a step past its timeout is stopped', slow['timed_out'] and slow['returncode'] != 0 and slow['seconds'] < 20)

# 8. HTTP: the page, the status JSON and the cross-site guard ------------------------------------------------

runner = FakeRunner()
r = make('http', runner, seed=write_model(TMP / 'seed-http', 100), TMDB_API_KEY=KEY_V3)
r.boot()
server = ThreadingHTTPServer(('127.0.0.1', 0), refresher.make_handler(r))
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]

code, _headers, body = call('/healthz')
check('health answers ok', code == 200 and json.loads(body) == {'status': 'ok'})
check('a POST without X-Requested-With is refused', call('/api/run', 'POST')[0] == 403)
check('a wrong X-Requested-With is refused', call('/api/run', 'POST', {'X-Requested-With': 'XMLHttpRequest'})[0] == 403)
check('a mismatched Origin is refused', call('/api/run', 'POST', {**GOOD, 'Origin': 'https://evil.example'})[0] == 403)
check('a null Origin is refused', call('/api/run', 'POST', {**GOOD, 'Origin': 'null'})[0] == 403)
check('a cross-site fetch is refused', call('/api/run', 'POST', {**GOOD, 'Sec-Fetch-Site': 'cross-site'})[0] == 403)
check('a sibling subdomain is refused', call('/api/run', 'POST', {**GOOD, 'Sec-Fetch-Site': 'same-site'})[0] == 403)
check('an unknown step is a 400', call('/api/run?step=everything', 'POST', GOOD)[0] == 400)
check('a GET to /api/run is a 404', call('/api/run')[0] == 404)
check('nothing ran on refused requests', len(r.state['runs']) == 1)
code, _headers, body = call('/api/run', 'POST', {**GOOD, 'Origin': f'http://127.0.0.1:{PORT}',
                                                  'Sec-Fetch-Site': 'same-origin'})
check('a same-origin request starts a run with 202', code == 202 and json.loads(body)['started'] is True, body)
wait_for(lambda: not r.busy())
check('the run over HTTP succeeds', r.state['runs'][0]['outcome'] == 'success', r.state['runs'][0].get('error'))

code, _headers, body = call('/api/status')
status = json.loads(body)
check('status JSON has every part', code == 200 and {
    'status', 'now', 'current', 'versions', 'running', 'next_run', 'schedule', 'last_success', 'runs', 'tmdb',
    'wikidata', 'clickstream', 'pipeline', 'model_root'} <= set(status), sorted(status))
check('status shows the live version and its build.json', status['current']['version'] == r.current()['version']
      and status['current']['build'] == r.current()['build'])
check('status lists runs with outcome, duration and steps', status['runs'][0]['outcome'] == 'success'
      and status['runs'][0]['seconds'] is not None and status['runs'][0]['steps'])
check('status says whether TMDB is configured', status['tmdb']['configured'] is True and status['tmdb']['region'] == 'US')
check('status is idle between runs', status['status'] == 'idle' and status['running'] is None)
check('the key is never in the status JSON', KEY_V3 not in body.decode())

code, headers, body = call('/')
page = body.decode()
check('the page renders', code == 200 and headers.get('Content-Type', '').startswith('text/html'))
check('the page has the rebuild buttons', 'Rebuild now' in page and 'Refresh TMDB only' in page)
check('the page shows the live version and the next run', r.current()['version'] in page and 'Next run' in page)
check('the page runs no inline script or style', not re.search(r'<script(?![^>]*\bsrc=)', page)
      and '<style' not in page and ' style=' not in page and ' on' + 'click=' not in page)
check('the page is served with a strict CSP', "script-src 'self'" in headers.get('Content-Security-Policy', '')
      and "default-src 'none'" in headers.get('Content-Security-Policy', ''))
check('the key is never on the page', KEY_V3 not in page)
code, headers, _body = call('/refresher.js')
check('the page script is served', code == 200 and 'javascript' in headers.get('Content-Type', ''))
code, headers, _body = call('/refresher.css')
check('the page styles are served', code == 200 and 'text/css' in headers.get('Content-Type', ''))
code, _headers, body = call('/', 'HEAD')
check('HEAD answers without a body', code == 200 and body == b'')
check('an unknown API path is a JSON 404', call('/api/nope')[0] == 404)
check('an unknown page is a 404', call('/nope')[0] == 404)

# 9. TMDB, from the refresher's side ---------------------------------------------------------------------------

version = r.current()
check('with a key, the TMDB step runs and its data lands in the version',
      'tmdb' in runner.names() and (version['path'] / 'tmdb.json.gz').exists()
      and version['build']['tmdb'] == {'fetched_at': tmdb.iso(NOW), 'shows': 2}, version['build']['tmdb'])
check('only the TMDB step is given the key', runner.env_for('tmdb').get('TMDB_API_KEY') == KEY_V3
      and all('TMDB_API_KEY' not in call['env'] for call in runner.calls if call['name'] != 'tmdb'))
check('TMDB settings reach the step', runner.env_for('tmdb')['TMDB_DAILY_LIMIT'] == '6000'
      and runner.env_for('tmdb')['TMDB_MIN_POPULARITY'] == '60' and runner.env_for('tmdb')['TMDB_REGION'] == 'US')
log_text = (r.logs / f"{r.state['runs'][0]['id']}.log").read_text()
check('the key never reaches a run log', KEY_V3 not in log_text and 'calling TMDB with [key]' in log_text)

before = r.current()
code, _headers, body = call('/api/run?step=tmdb', 'POST', GOOD)
check('a TMDB-only run starts over HTTP', code == 202, body)
wait_for(lambda: not r.busy())
after = r.current()
check('the TMDB-only run makes a new live version', r.state['runs'][0]['kind'] == 'tmdb'
      and r.state['runs'][0]['outcome'] == 'success' and after['version'] != before['version'], r.state['runs'][0])
check('it runs only the TMDB step and validation', runner.names()[-2:] == ['tmdb', 'validate'])
check('the model, facet, co-interest, film and neighbour files are the live version\'s, shared not rebuilt',
      all((after['path'] / n).is_file() and os.stat(after['path'] / n).st_ino == os.stat(before['path'] / n).st_ino
          for n in refresher.MODEL_FILES + refresher.FACET_FILES + refresher.COINTEREST_FILES + refresher.FILM_FILES
          + refresher.NEIGHBOUR_FILES))
check('build.json carries the model\'s facts forward', all(after['build'][k] == before['build'][k]
      for k in ('snapshot_date', 'shows', 'pipeline', 'seeded_from', 'facets', 'cointerest', 'films', 'neighbours'))
      and list(after['build']) == BUILD_KEYS and after['build']['facets']['linked'] == 100
      and after['build']['cointerest']['links'] == 6 and after['build']['films']['films'] == 3)

runner.tmdb_code, runner.tmdb_error = 3, tmdb.REJECTED
done = run(r)
check('a rejected key does not fail a full run', done['outcome'] == 'success' and tmdb.REJECTED in done['warnings'],
      done)
check('a rejected key is recorded', r.status()['tmdb']['last']['error'] == tmdb.REJECTED)
check('and shown on the page', tmdb.REJECTED in call('/')[2].decode())
before = live(r)
done = run(r, 'tmdb')
check('a rejected key fails a TMDB-only run', done['outcome'] == 'failed' and done['error'] == tmdb.REJECTED, done)
check('and leaves current alone', live(r) == before and not list(r.versions.glob('*.tmp')))
server.shutdown()

server.server_close()

r = make('no-key', FakeRunner())
r.boot()
server = ThreadingHTTPServer(('127.0.0.1', 0), refresher.make_handler(r))
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]
check('without a key a TMDB-only request is a 400', call('/api/run?step=tmdb', 'POST', GOOD)[0] == 400)
check('without a key there is no TMDB button', 'Refresh TMDB only' not in call('/')[2].decode())
check('with nothing live the page says so', 'No live version yet' in call('/')[2].decode())
server.shutdown()
server.server_close()

runner = FakeRunner()
r = make('carry', runner)
add_version(r, '20260101T000000Z', records={'1': tmdb_record(1, NOW - timedelta(days=10)),
                                            '2': tmdb_record(2, NOW - timedelta(days=10)),
                                            '999': tmdb_record(999, NOW - timedelta(days=10))},
            fetched=NOW - timedelta(days=10))
r.swap_current('20260101T000000Z')
done = run(r)
carried = json.loads(gunzip(r.current()['path'] / 'tmdb.json.gz'))
check('without a key, recent TMDB data is carried forward', done['outcome'] == 'success'
      and 'tmdb carry' in runner.names() and sorted(carried['shows']) == ['1', '2'], done.get('error'))
check('carried data keeps its own date', carried['fetched_at'] == tmdb.iso(NOW - timedelta(days=10))
      and r.current()['build']['tmdb'] == {'fetched_at': tmdb.iso(NOW - timedelta(days=10)), 'shows': 2})

r = make('carry-old', FakeRunner())
add_version(r, '20260101T000000Z', records={'1': tmdb_record(1, NOW - timedelta(days=181))},
            fetched=NOW - timedelta(days=181))
r.swap_current('20260101T000000Z')
done = run(r)
check('TMDB data older than 180 days is not carried', done['outcome'] == 'success'
      and not (r.current()['path'] / 'tmdb.json.gz').exists() and r.current()['build']['tmdb']['shows'] == 0)

# 10. The TMDB step itself ---------------------------------------------------------------------------------------

v4, v3 = tmdb.Auth(KEY_V4), tmdb.Auth(KEY_V3)
check('a read access token is sent as a bearer token', v4.bearer and v4.headers() == {'Authorization': f'Bearer {KEY_V4}'}
      and v4.sign('/3/tv/1?language=en-US') == '/3/tv/1?language=en-US')
check('a v3 key is sent as the api_key parameter', not v3.bearer and v3.headers() == {}
      and v3.sign('/3/tv/1?language=en-US') == f'/3/tv/1?language=en-US&api_key={KEY_V3}'
      and v3.sign('/3/tv/1') == f'/3/tv/1?api_key={KEY_V3}')
check('neither key shows in a repr', KEY_V3 not in repr(v3) and KEY_V4 not in repr(v4))
rejects('an empty key is refused', lambda: tmdb.Auth('  '), ValueError, 'empty')


class FakeTime:
    def __init__(self):
        self.now, self.slept = 1000.0, 0.0
        self.lock = threading.Lock()

    def clock(self):
        with self.lock:
            return self.now

    def sleep(self, seconds):
        with self.lock:
            self.now += seconds
            self.slept += seconds


class Answer:
    def __init__(self, status, body=b'', headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def read(self, _limit=-1):
        return self.body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


class FakeTMDB:
    """A pretend api.themoviedb.org answering find, details and a season's videos from
    dicts. Every request is recorded, and scripted answers or errors are served first;
    the seasons in `failing` always answer 500."""

    def __init__(self, finds=None, details=None, script=None, always=None, seasons=None, failing=()):
        self.finds, self.details = finds or {}, details or {}
        self.seasons, self.failing = seasons or {}, set(failing)
        self.script, self.always = list(script or []), always
        self.requests = []
        self.lock = threading.Lock()

    def connect(self):
        return FakeConnection(self)

    def answer(self, path):
        route, _, query = path.partition('?')
        if route.startswith('/3/find/'):
            source = re.search(r'external_source=(\w+)', query)[1]
            found = self.finds.get((source, route.rsplit('/', 1)[1]))
            return Answer(200, json.dumps({'tv_results': [{'id': found}] if found else [], 'movie_results': []}).encode())
        season = re.fullmatch(r'/3/tv/(\d+)/season/(\d+)/videos', route)
        if season:
            asked = (int(season[1]), int(season[2]))
            if asked in self.failing:
                return Answer(500)
            block = self.seasons.get(asked)
            return Answer(200, json.dumps(block).encode()) if block is not None else Answer(404, b'{"status_code":34}')
        show = self.details.get(int(route.rsplit('/', 1)[1]))
        return Answer(200, json.dumps(show).encode()) if show else Answer(404, b'{"status_code":34}')


class FakeConnection:
    def __init__(self, server):
        self.server, self.pending = server, None

    def request(self, method, path, headers=None):
        with self.server.lock:
            self.server.requests.append({'method': method, 'path': path, 'headers': dict(headers or {})})
            scripted = self.server.script.pop(0) if self.server.script else self.server.always
        if isinstance(scripted, Exception):
            raise scripted
        self.pending = scripted or self.server.answer(path)

    def getresponse(self):
        return self.pending

    def close(self):
        pass


def details(tmdb_id, providers=True):
    return {
        'id': tmdb_id, 'name': 'Breaking Bad', 'backdrop_path': '/tsRy63Mu5cu8etL1X7ZLyf7UP1M.jpg',
        'vote_average': 8.921, 'vote_count': 15000,
        'content_ratings': {'results': [{'iso_3166_1': 'GB', 'rating': '18'}, {'iso_3166_1': 'US', 'rating': 'TV-MA'}]},
        'watch/providers': {'results': {
            'GB': {'flatrate': [{'provider_name': 'Netflix UK', 'logo_path': '/gb.jpg', 'display_priority': 0}]},
            **({'US': {
                'link': 'https://www.themoviedb.org/tv/1396-breaking-bad/watch?locale=US',
                'buy': [{'provider_name': 'Apple TV', 'logo_path': '/apple.jpg', 'display_priority': 2},
                        {'provider_name': 'Amazon Video', 'logo_path': '/amazon.jpg', 'display_priority': 1}],
                'rent': [{'provider_name': 'Apple TV', 'logo_path': '/apple.jpg', 'display_priority': 4}],
                'flatrate': [{'provider_name': 'Netflix', 'logo_path': '/t2yyOv40HZeVlLjYsCsPHnWLk4W.jpg',
                              'display_priority': 5},
                             {'provider_name': 'AMC+', 'logo_path': 'javascript:alert(1)', 'display_priority': 3}],
                'ads': [{'provider_name': 'Netflix', 'logo_path': '/netflix.jpg', 'display_priority': 1},
                        {'provider_name': 'Pluto TV', 'logo_path': '/pluto.jpg', 'display_priority': 9}],
                'free': [{'provider_name': 'Tubi', 'logo_path': '/tubi.jpg', 'display_priority': 7}]}} if providers else {})}},
        'videos': {'results': [
            {'site': 'YouTube', 'type': 'Teaser', 'official': True, 'key': 'TEASER00001', 'name': 'Teaser',
             'published_at': '2013-06-01T00:00:00.000Z'},
            {'site': 'YouTube', 'type': 'Trailer', 'official': False, 'key': 'FANMADE0001', 'name': 'Fan cut',
             'published_at': '2020-01-01T00:00:00.000Z'},
            {'site': 'YouTube', 'type': 'Trailer', 'official': True, 'key': 'OLDTRAILER1', 'name': 'Season 1 Trailer',
             'published_at': '2008-01-01T00:00:00.000Z'},
            {'site': 'YouTube', 'type': 'Trailer', 'official': True, 'key': 'HhesaQXLuRY', 'name': 'Official Trailer',
             'published_at': '2013-08-11T00:00:00.000Z'},
            {'site': 'Vimeo', 'type': 'Trailer', 'official': True, 'key': 'VIMEO000001', 'name': 'Elsewhere',
             'published_at': '2019-01-01T00:00:00.000Z'},
            {'site': 'YouTube', 'type': 'Clip', 'official': True, 'key': 'CLIP0000001', 'name': 'A clip',
             'published_at': '2019-01-01T00:00:00.000Z'},
            {'site': 'YouTube', 'type': 'Trailer', 'official': True, 'key': 'not a key!!', 'name': 'Broken',
             'published_at': '2019-01-01T00:00:00.000Z'},
            {'site': 'YouTube', 'type': 'Trailer', 'official': True, 'key': 'HhesaQXLuRY', 'name': 'Again',
             'published_at': '2013-08-11T00:00:00.000Z'}]},
    }


record = tmdb.trim_details(details(1396), 1396, 'US', '2026-09-28T05:00:00Z')
check('a record has exactly the schema keys', list(record) == RECORD_KEYS, list(record))
check('the rating is the region\'s', record['rating'] == 'TV-MA')
check('providers run subscription, free, ads, rent, buy, each in TMDB\'s order',
      [(p['name'], p['kind']) for p in record['providers']] == [
          ('AMC+', 'flatrate'), ('Netflix', 'flatrate'), ('Tubi', 'free'), ('Pluto TV', 'ads'),
          ('Apple TV', 'rent'), ('Amazon Video', 'buy')], record['providers'])
check('a service appears once, under its first kind', [p['name'] for p in record['providers']].count('Netflix') == 1
      and [p['name'] for p in record['providers']].count('Apple TV') == 1)
check('provider entries are name, logo and kind', record['providers'][1] == {
    'name': 'Netflix', 'logo': '/t2yyOv40HZeVlLjYsCsPHnWLk4W.jpg', 'kind': 'flatrate'})
check('a logo that is not a TMDB image path is dropped', record['providers'][0]['logo'] is None)
check('other regions are ignored', 'Netflix UK' not in [p['name'] for p in record['providers']])
check('the watch link is TMDB\'s page for the region',
      record['watch_link'] == 'https://www.themoviedb.org/tv/1396/watch?locale=US')
check('trailers: YouTube trailers then teasers, official first, then newest',
      [t['key'] for t in record['trailers']] == ['HhesaQXLuRY', 'OLDTRAILER1', 'FANMADE0001', 'TEASER00001'],
      [t['key'] for t in record['trailers']])
check('a trailer entry is key, name, type, official and day', record['trailers'][0] == {
    'key': 'HhesaQXLuRY', 'name': 'Official Trailer', 'type': 'Trailer', 'official': True, 'published': '2013-08-11'})
many = {'videos': {'results': [{'site': 'YouTube', 'type': 'Trailer', 'official': True, 'key': f'TRAILER{i:04d}',
                                'published_at': f'20{10 + i}-01-01T00:00:00.000Z'} for i in range(9)]}}
check('at most six trailers', [t['key'] for t in tmdb.trim_details(many, 1, 'US', 'x')['trailers']]
      == [f'TRAILER{i:04d}' for i in (8, 7, 6, 5, 4, 3)])
check('backdrop and votes are kept', record['backdrop'] == '/tsRy63Mu5cu8etL1X7ZLyf7UP1M.jpg'
      and record['vote_average'] == 8.921 and record['vote_count'] == 15000)
bare = tmdb.trim_details(details(1396, providers=False), 1396, 'US', 'x')
check('no providers in the region means no watch link', bare['providers'] == [] and bare['watch_link'] is None)
odd = tmdb.trim_details({'watch/providers': 'nope', 'videos': [1], 'content_ratings': None, 'vote_average': 'high',
                         'backdrop_path': 'http://evil.example/x.jpg'}, 7, 'US', 'x')
check('malformed answers trim to empty values', odd['providers'] == [] and odd['trailers'] == []
      and odd['rating'] is None and odd['vote_average'] is None and odd['backdrop'] is None)

server = FakeTMDB(finds={('imdb_id', 'tt0903747'): 1396}, details={1396: details(1396)})
clock = FakeTime()
limiter = tmdb.Limiter(rate=20, clock=clock.clock, sleep=clock.sleep)
answer = tmdb.Client(v4, limiter=limiter, connect=server.connect).get(tmdb.DETAILS.format(id=1396))
sent = server.requests[-1]
check('a bearer request carries the header and no api_key', answer['id'] == 1396
      and sent['headers'].get('Authorization') == f'Bearer {KEY_V4}' and 'api_key' not in sent['path'])
check('details ask for ratings, providers and videos with the slash unencoded',
      'append_to_response=content_ratings,watch/providers,videos' in sent['path'] and '%2F' not in sent['path']
      and 'include_video_language=en,null' in sent['path'] and 'language=en-US' in sent['path'])
tmdb.Client(v3, limiter=limiter, connect=server.connect).get(tmdb.DETAILS.format(id=1396))
sent = server.requests[-1]
check('a v3 request carries api_key and no Authorization header',
      sent['path'].endswith(f'&api_key={KEY_V3}') and 'Authorization' not in sent['headers'])

clock = FakeTime()
limiter = tmdb.Limiter(rate=20, clock=clock.clock, sleep=clock.sleep)
client = tmdb.Client(v4, limiter=limiter, connect=server.connect)
for _ in range(21):
    client.get(tmdb.DETAILS.format(id=1396))
check('requests are spaced to 20 a second', abs(clock.now - 1001.0) < 0.01, clock.now - 1000)

server = FakeTMDB(finds={('tvdb_id', '81189'): 1396})
client = tmdb.Client(v3, limiter=tmdb.Limiter(rate=1e6), connect=server.connect)
check('find falls back from IMDb to TheTVDB', tmdb.find_tmdb_id(client, 'tt0903747', 81189) == (1396, 'tvdb_id'))
check('IMDb is asked first', [re.search(r'external_source=(\w+)', q['path'])[1] for q in server.requests]
      == ['imdb_id', 'tvdb_id'])
check('find reads tv_results only', tmdb.find_tmdb_id(client, 'tt0000001', None) == (None, None))

server = FakeTMDB(details={1: details(1)}, script=[Answer(429, headers={'Retry-After': '7'})])
clock = FakeTime()
client = tmdb.Client(v4, limiter=tmdb.Limiter(rate=20, clock=clock.clock, sleep=clock.sleep), connect=server.connect)
check('a 429 is retried after Retry-After', client.get('/3/tv/1')['id'] == 1 and clock.slept >= 7
      and len(server.requests) == 2, clock.slept)
server = FakeTMDB(details={1: details(1)}, script=[Answer(429)])
clock = FakeTime()
client = tmdb.Client(v4, limiter=tmdb.Limiter(rate=20, clock=clock.clock, sleep=clock.sleep), connect=server.connect)
check('a 429 without Retry-After waits 10 seconds', client.get('/3/tv/1')['id'] == 1 and 10 <= clock.slept < 10.2,
      clock.slept)
check('Retry-After is read as seconds or a date, within bounds',
      tmdb.retry_after('3') == 3 and tmdb.retry_after(None) == 10 and tmdb.retry_after('9999') == 120
      and tmdb.retry_after('Wed, 21 Oct 2015 07:28:00 GMT') == 1)
def fake_limiter():
    clock = FakeTime()
    return tmdb.Limiter(rate=20, clock=clock.clock, sleep=clock.sleep)


server = FakeTMDB(details={1: details(1)}, script=[Answer(502), OSError('reset'), Answer(503)])
client = tmdb.Client(v4, limiter=fake_limiter(), connect=server.connect)
check('server errors and dropped connections are retried', client.get('/3/tv/1')['id'] == 1 and len(server.requests) == 4)
server = FakeTMDB(always=Answer(500))
client = tmdb.Client(v3, limiter=fake_limiter(), connect=server.connect)
rejects('a TMDB that keeps failing gives up', lambda: client.get('/3/tv/1'), tmdb.TmdbError, 'gave up on /3/tv/1')
server = FakeTMDB(always=Answer(401))
client = tmdb.Client(v3, limiter=tmdb.Limiter(rate=1e6), connect=server.connect)
rejects('a 401 is a rejected key', lambda: client.get('/3/tv/1'), tmdb.KeyRejected, tmdb.REJECTED)
rejects('after a 401 nothing more is sent', lambda: client.get('/3/tv/2'), tmdb.KeyRejected, tmdb.REJECTED)
check('only the one request went out', len(server.requests) == 1)

# The whole step against the pretend server.
root = TMP / 'tmdb-root'
version = write_model(root / 'versions' / 'v1', 6)
raw = write_raw(root / 'raw', shows=[
    {'id': 1, 'weight': 95, 'externals': {'imdb': 'tt0000001', 'thetvdb': 1001}},
    {'id': 2, 'weight': 90, 'externals': {'imdb': 'tt0000002', 'thetvdb': 1002}},
    {'id': 3, 'weight': 85, 'externals': {'imdb': None, 'thetvdb': None}},
    {'id': 4, 'weight': 50, 'externals': {'imdb': 'tt0000004'}},
    {'id': 5, 'weight': 80, 'externals': {'imdb': 'tt0000005'}},
    {'id': 6, 'weight': 75, 'externals': {'imdb': 'tt0000006'}}])
server = FakeTMDB(finds={('imdb_id', 'tt0000001'): 101, ('tvdb_id', '1002'): 102, ('imdb_id', 'tt0000006'): 106},
                  details={101: details(101), 102: details(102)})
logs = []


def step(now, **kw):
    return tmdb.refresh(root, version, raw, KEY_V3, now=now, connect=server.connect, workers=3,
                        limiter=fake_limiter(), log=logs.append, **kw)


outcome = step(NOW)
ids = json.loads((root / 'tmdb' / 'ids.json').read_text())
check('the step fetches popular shows with an external id', outcome['eligible'] == 4 and outcome['fetched'] == 2
      and outcome['missing'] == 2 and outcome['failed'] == 0 and outcome['error'] is None, outcome)
check('matches are cached with their source', ids['1']['tmdb_id'] == 101 and ids['1']['source'] == 'imdb_id'
      and ids['2']['tmdb_id'] == 102 and ids['2']['source'] == 'tvdb_id')
check('misses are cached too', ids['5']['tmdb_id'] is None and ids['5']['checked_at'] == tmdb.iso(NOW))
check('a match TMDB no longer has becomes a miss', ids['6']['tmdb_id'] is None)
check('unpopular shows and shows without ids are left alone', '3' not in ids and '4' not in ids)
written = json.loads(gunzip(version / 'tmdb.json.gz'))
check('the version file follows the schema', written['region'] == 'US' and written['fetched_at'] == tmdb.iso(NOW)
      and sorted(written['shows']) == ['1', '2'] and list(written['shows']['1']) == RECORD_KEYS
      and written['shows']['1']['tmdb_id'] == 101)
cache = json.loads(gunzip(root / 'tmdb' / 'cache.json.gz'))
check('the master cache holds the records', sorted(cache['shows']) == ['1', '2'] and cache['region'] == 'US')

server.requests.clear()
outcome = step(NOW + timedelta(days=10))
finds = [q for q in server.requests if '/find/' in q['path']]
check('ten days on, known matches are not looked up again and misses wait',
      not finds and outcome['fetched'] == 2 and outcome['planned'] == 2, outcome)
server.requests.clear()
step(NOW + timedelta(days=31))
asked = sorted(re.search(r'/find/(\w+)', q['path'])[1] for q in server.requests if '/find/' in q['path'])
check('after 30 days a miss is asked about again', asked == ['tt0000005', 'tt0000006'], asked)
server.requests.clear()
outcome = step(NOW + timedelta(days=31, hours=2))
check('a record fetched within the day is not fetched again', outcome['planned'] == 0 and not server.requests, outcome)

store = tmdb.Store(root / 'tmdb')
old_ids, old_shows = store.load('US', NOW)
old_shows['1'] = tmdb_record(1, NOW - timedelta(days=181))
store.save(old_ids, old_shows, 'US')
_ids, kept = store.load('US', NOW, log=logs.append)
check('records older than 180 days are dropped from the cache', '1' not in kept and '2' in kept)
expiry = write_model(TMP / 'expiry', 2)
count = tmdb.write_version(expiry, {'1': tmdb_record(1, NOW - timedelta(days=181)), '2': tmdb_record(2)},
                           {1, 2}, 'US', NOW)
check('and never written into a version', count['shows'] == 1
      and sorted(json.loads(gunzip(expiry / 'tmdb.json.gz'))['shows']) == ['2'])
_ids, kept = store.load('GB', NOW, log=logs.append)
check('a region change starts the cache again', kept == {})

index = {sid: (100 - sid, f'tt{sid:07d}', None) for sid in range(10, 18)}
cached = {'10': tmdb_record(10, NOW - timedelta(days=2)), '11': tmdb_record(11, NOW - timedelta(hours=1)),
          '13': tmdb_record(13, NOW - timedelta(days=5)), '14': tmdb_record(14, NOW - timedelta(days=3)),
          '15': tmdb_record(15, NOW - timedelta(days=9))}
misses = {'17': {'tmdb_id': None, 'imdb': 'tt0000017', 'tvdb': None, 'checked_at': tmdb.iso(NOW - timedelta(days=5))}}
order, eligible = tmdb.plan(index, set(index), cached, misses, NOW, min_popularity=60, limit=5, top=2)
check('tonight: no data first, then the most popular, then the stalest', order == [12, 16, 10, 15, 13] and eligible == 8,
      order)
order, _eligible = tmdb.plan(index, set(index) - {12}, cached, misses, NOW, min_popularity=60, limit=100, top=2)
check('only shows in the catalog are chosen', 12 not in order)
order, _eligible = tmdb.plan(index, set(index), cached, misses, NOW, min_popularity=88, limit=100, top=2)
check('the popularity floor applies', all(100 - sid >= 88 for sid in order) and order)

# A rejected key stops the step, keeps what is cached, and says so.
server = FakeTMDB(always=Answer(401))
outcome = step(NOW + timedelta(days=60))
check('a 401 stops the step with "TMDB key rejected"', outcome['error'] == tmdb.REJECTED and outcome['fetched'] == 0
      and len(server.requests) <= tmdb.WORKERS, (outcome, len(server.requests)))
check('cached records still reach the version', json.loads(gunzip(version / 'tmdb.json.gz'))['shows'])

# The key never appears in anything the step prints.
server = FakeTMDB(script=[http.client.HTTPException(f'bad request to /3/find/x?api_key={KEY_V3}'),
                          OSError(f'reset while sending api_key={KEY_V3}')], always=Answer(500))
step(NOW + timedelta(days=120))
check('the key never appears in the step\'s log', logs and not any(KEY_V3 in line for line in logs), logs[-3:])
leaky = TMP / KEY_V3
(leaky / 'page-000.json').mkdir(parents=True)
os.environ['TMDB_API_KEY'] = KEY_V3
errors = io.StringIO()
with redirect_stderr(errors), redirect_stdout(io.StringIO()):
    code = tmdb.main(['--root', str(root), '--version', str(version), '--raw', str(leaky)])
del os.environ['TMDB_API_KEY']
check('a crash exits 1 with the key scrubbed from its traceback', code == 1 and 'Traceback' in errors.getvalue()
      and KEY_V3 not in errors.getvalue() and '[key]' in errors.getvalue())

# 10b. Trailers from seasons. TMDB keeps many shows' trailers on their seasons: Breaking Bad
# has none of its own, but a trailer on season 1 and a teaser on its last.
check('a show with seasons asks its first and its latest, specials aside',
      tmdb.trailer_seasons({'seasons': [{'season_number': 0}, {'season_number': 1}, {'season_number': 2},
                                        {'season_number': 5}, {'season_number': '6'}, 'junk']}) == [1, 5])
check('a show of one season asks it once', tmdb.trailer_seasons({'seasons': [{'season_number': 1}]}) == [1])
check('without a season list, how many seasons it has', tmdb.trailer_seasons({'number_of_seasons': 3}) == [1, 3]
      and tmdb.trailer_seasons({'number_of_seasons': 1}) == [1])
check('a show with no seasons asks none', tmdb.trailer_seasons({}) == [] and tmdb.trailer_seasons(None) == []
      and tmdb.trailer_seasons({'seasons': [{'season_number': 0}], 'number_of_seasons': 'x'}) == [])


def season_videos(key, kind, day, official=True):
    return {'results': [
        {'site': 'YouTube', 'type': kind, 'official': official, 'key': key, 'name': 'Official Trailer',
         'published_at': f'{day}T00:00:00.000Z'},
        {'site': 'YouTube', 'type': 'Featurette', 'official': True, 'key': f'{key[:10]}F', 'name': 'Inside',
         'published_at': f'{day}T00:00:00.000Z'},
        {'site': 'Vimeo', 'type': 'Trailer', 'official': True, 'key': f'{key[:10]}V', 'name': 'Elsewhere'}]}


check('a season\'s videos are filtered as a show\'s are, and carry the season',
      tmdb.trim_trailers(season_videos('SEASON1TRLR', 'Trailer', '2008-01-10'), season=1) == [
          {'key': 'SEASON1TRLR', 'name': 'Official Trailer', 'type': 'Trailer', 'official': True,
           'published': '2008-01-10', 'season': 1}])
check('a show\'s own trailers carry no season', all('season' not in t for t in record['trailers']))


def bare_details(tmdb_id, seasons):
    """A show's details with no trailer or teaser of its own, only a clip."""
    return {**details(tmdb_id), 'seasons': [{'season_number': n, 'episode_count': 8} for n in seasons],
            'videos': {'results': [{'site': 'YouTube', 'type': 'Clip', 'official': True, 'key': 'CLIPONLY001',
                                    'name': 'A clip', 'published_at': '2012-01-01T00:00:00.000Z'}]}}


def seasons_step(folder, server, limit=tmdb.DAILY_LIMIT, now=NOW, clock=None):
    """The TMDB step over four shows, one worker at a time so the order is fixed."""
    folder = Path(folder)
    model = folder / 'versions' / 'v1'
    if not model.exists():
        write_model(model, 4)
        write_raw(folder / 'raw', shows=[{'id': i, 'weight': 100 - i, 'externals': {'imdb': f'tt000000{i}'}}
                                         for i in range(1, 5)])
    clock = clock or FakeTime()
    outcome = tmdb.refresh(folder, model, folder / 'raw', KEY_V3, now=now, connect=server.connect, workers=1,
                           limiter=tmdb.Limiter(rate=20, clock=clock.clock, sleep=clock.sleep), log=logs.append,
                           limit=limit)
    return outcome, json.loads(gunzip(model / 'tmdb.json.gz'))['shows']


FINDS = {('imdb_id', f'tt000000{i}'): 200 + i for i in range(1, 5)}
server = FakeTMDB(finds=FINDS, details={
    201: bare_details(201, [0, 1, 2, 3, 4, 5]),    # Breaking Bad's shape: trailers on seasons 1 and 5
    202: details(202),                              # trailers of its own
    203: bare_details(203, [1]),                    # one season, which TMDB keeps failing on
    204: bare_details(204, [])},                    # no seasons listed
    seasons={(201, 1): season_videos('SEASON1TRLR', 'Trailer', '2008-01-10'),
             (201, 5): season_videos('SEASON5TEAS', 'Teaser', '2013-06-01')},
    failing={(203, 1)})
outcome, cached = seasons_step(TMP / 'tmdb-seasons', server)
asked = [q['path'] for q in server.requests if '/season/' in q['path']]
check('a show with no trailer of its own asks its first and latest seasons, and only such a show does',
      sorted({path.split('?')[0] for path in asked}) == ['/3/tv/201/season/1/videos', '/3/tv/201/season/5/videos',
                                                         '/3/tv/203/season/1/videos'], asked)
check('a season is asked in the languages a show\'s own videos are',
      all('language=en-US' in path and 'include_video_language=en,null' in path and '%2C' not in path for path in asked))
check('its trailers come from those seasons, trailer before teaser, each with its season',
      [(t['key'], t['type'], t.get('season')) for t in cached['1']['trailers']]
      == [('SEASON1TRLR', 'Trailer', 1), ('SEASON5TEAS', 'Teaser', 5)], cached['1']['trailers'])
check('a show with trailers of its own keeps them', cached['2']['trailers']
      and all('season' not in t for t in cached['2']['trailers']))
check('a season TMDB cannot answer costs only its trailers, not the show',
      '3' in cached and cached['3']['trailers'] == [] and cached['3']['rating'] == 'TV-MA' and outcome['failed'] == 0)
check('a show with no seasons listed asks for none', cached['4']['trailers'] == []
      and not any('/tv/204/season' in path for path in asked))
check('season requests are counted among the step\'s requests', outcome['seasons'] == 3
      and outcome['requests'] == len(server.requests) and outcome['fetched'] == 4 and outcome['deferred'] == 0, outcome)
check('the log says how many seasons were asked for trailers', any('3 seasons asked for trailers' in line for line in logs))

server = FakeTMDB(finds=FINDS, details={201: bare_details(201, [1, 5]), 202: details(202), 203: details(203),
                                        204: details(204)},
                  seasons={(201, 1): season_videos('SEASON1TRLR', 'Trailer', '2008-01-10'),
                           (201, 5): season_videos('SEASON5TEAS', 'Teaser', '2013-06-01')})
clock = FakeTime()
seasons_step(TMP / 'tmdb-season-rate', server, clock=clock)
check('season requests wait their turn at 20 a second like any other',
      abs(clock.now - 1000 - (len(server.requests) - 1) / 20) < 0.01 and len(server.requests) == 10,
      (clock.now, len(server.requests)))

# The night's limit counts a season's request as it counts a show's details: with room
# for three, three shows are planned, and the first one's details and two seasons spend
# it, so the other two wait.
server = FakeTMDB(finds=FINDS, details={201: bare_details(201, [1, 5]), 202: details(202), 203: details(203),
                                        204: details(204)},
                  seasons={(201, 1): season_videos('SEASON1TRLR', 'Trailer', '2008-01-10'),
                           (201, 5): season_videos('SEASON5TEAS', 'Teaser', '2013-06-01')})
outcome, cached = seasons_step(TMP / 'tmdb-season-limit', server, limit=3)
spent = [q['path'] for q in server.requests if '/find/' not in q['path']]
check('the night\'s limit counts season requests with details', len(spent) == 3 and outcome['seasons'] == 2
      and outcome['planned'] == 3 and outcome['fetched'] == 1 and outcome['deferred'] == 2 and sorted(cached) == ['1'],
      (spent, outcome))
check('shows the limit did not reach are not even looked up',
      not any(f'tt000000{i}' in q['path'] for q in server.requests for i in (2, 3, 4)))
check('the log says the rest wait for another night', any('2 shows wait for another night' in line for line in logs))
server.requests.clear()
outcome, cached = seasons_step(TMP / 'tmdb-season-limit', server, limit=3, now=NOW + timedelta(hours=1))
check('the next night they come first, and a show fetched within the day is not asked again',
      sorted(cached) == ['1', '2', '3', '4'] and outcome['fetched'] == 3
      and not any('/tv/201' in q['path'] for q in server.requests), outcome)
server = FakeTMDB(finds=FINDS, details={201: bare_details(201, [1, 5])},
                  seasons={(201, 1): season_videos('SEASON1TRLR', 'Trailer', '2008-01-10'),
                           (201, 5): season_videos('SEASON5TEAS', 'Teaser', '2013-06-01')})
outcome, cached = seasons_step(TMP / 'tmdb-season-short', server, limit=2)
check('a season past the limit is not asked, and the show keeps what it found',
      [t['key'] for t in cached['1']['trailers']] == ['SEASON1TRLR']
      and not any('/season/5/' in q['path'] for q in server.requests) and outcome['seasons'] == 1, outcome)

# 11. Wikidata, the fetch itself -------------------------------------------------------------------------------------

class FakeWikidata:
    """A pretend query.wikidata.org answering the fetcher's queries from a dict of items. It
    can be down, run out of time on batches above a size, and serve scripted answers
    first. Every query is recorded with the headers it came with."""

    def __init__(self, items, fail=False):
        self.items, self.fail = items, fail
        self.script = []
        self.split_above = None
        self.queries = []
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
                status, headers, answer = fake.answer(parse_qs(body).get('query', [''])[0], self.headers)
                if status == 200 and 'gzip' in (self.headers.get('Accept-Encoding') or ''):
                    answer, headers = gzip.compress(answer), {**headers, 'Content-Encoding': 'gzip'}
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header('Content-Length', str(len(answer)))
                self.end_headers()
                self.wfile.write(answer)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/sparql'

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def tags(self):
        with self.lock:
            return [q['query'].split('\n', 1)[0].lstrip('#') for q in self.queries]

    def answer(self, query, headers):
        with self.lock:
            self.queries.append({'query': query, 'agent': headers.get('User-Agent'), 'accept': headers.get('Accept')})
            scripted = self.script.pop(0) if self.script else None
        if scripted:
            return scripted
        if self.fail:
            return 503, {}, b'The service is down.'
        tag = query.split('\n', 1)[0].lstrip('#')
        block = re.search(r'VALUES \?item \{([^}]*)\}', query)
        items = re.findall(r'wd:(Q\d+)', block[1]) if block else []
        if self.split_above and len(items) > self.split_above:
            return 500, {}, b'java.util.concurrent.TimeoutException: query took too long'
        uri = lambda q: {'type': 'uri', 'value': wikidata.ENTITY + q}
        lit = lambda text, lang=None: {'type': 'literal', 'value': text, **({'xml:lang': lang} if lang else {})}
        known = lambda q: self.items.get(q, {})
        if tag == 'tvmaze':
            rows = [{'item': uri(q), 'id': lit(v)} for q, d in self.items.items() for v in d.get('P8600', [])]
        elif tag == 'imdb':
            wanted = set(re.findall(r'"(tt\d+)"', query))
            rows = [{'item': uri(q), 'imdb': lit(v)} for q, d in self.items.items() for v in d.get('P345', []) if v in wanted]
        elif tag == 'claims':
            props = re.findall(r'wdt:(P\d+)', re.search(r'VALUES \?p \{([^}]*)\}', query)[1])
            rows = [{'item': uri(q), 'p': {'type': 'uri', 'value': wikidata.DIRECT + p}, 'v': uri(v)}
                    for q in items for p in props for v in known(q).get(p, [])]
        elif tag in ('cast', 'parents'):
            rows = [{'item': uri(q), 'v': uri(v)} for q in items for v in known(q).get('P161' if tag == 'cast' else 'P279', [])]
        elif tag in ('labels', 'any-labels'):
            rows = [{'item': uri(q), 'label': lit(text, lang)} for q in items for lang, text in known(q).get('labels', [])
                    if tag == 'any-labels' or lang in ('en', 'mul')]
        elif tag == 'names':
            rows = [{'item': uri(q), 'name': lit(text, lang)} for q in items
                    for lang, text in known(q).get('labels', []) + known(q).get('aliases', [])]
        elif tag == 'films':
            # films.py's queries: films and series of some classes, well enough known.
            classes = re.findall(r'wd:(Q\d+)', re.search(r'VALUES \?class \{([^}]*)\}', query)[1])
            least = int(re.search(r'FILTER\(\?links >= (\d+)\)', query)[1])
            rows = [{'item': uri(q), 'class': uri(c), 'links': lit(str(d['links']))} for q, d in self.items.items()
                    for c in d.get('P31', []) if c in classes and d.get('links', 0) >= least]
        elif tag == 'dates':
            rows = [{'item': uri(q), 'date': lit(v)} for q in items for v in known(q).get('P577', [])]
        elif tag == 'titles':
            rows = [{'item': uri(q), 'title': lit(text, lang)} for q in items for lang, text in known(q).get('P1476', [])]
        elif tag == 'film-names':
            rows = [{'item': uri(q), 'name': lit(text, lang), 'alias': lit(kind)} for q in items
                    for kind, field in (('label', 'labels'), ('alias', 'aliases'))
                    for lang, text in known(q).get(field, []) if lang in ('en', 'mul')]
        elif 'schema:about' in query:
            # clickstream.py's one query: the English article of every item with a TVmaze id.
            rows = [{'tvmaze': lit(v), 'title': lit(d['enwiki'])} for d in self.items.values() if d.get('enwiki')
                    for v in d.get('P8600', [])]
        else:
            return 400, {}, b'Unknown query'
        body = json.dumps({'head': {'vars': []}, 'results': {'bindings': rows}}).encode()
        return 200, {'Content-Type': 'application/sparql-results+json'}, body


ITEMS = {
    'Q1': {'P8600': ['1'], 'P345': ['tt1000001'], 'P136': ['Q500'], 'P161': ['Q600', 'Q601'], 'P170': ['Q700'],
           'P4969': ['Q3'], 'labels': [('en', 'Show 1'), ('fr', 'Le Show')], 'aliases': [('en', 'S1')]},
    'Q2': {'P8600': ['2'], 'P136': ['Q500'], 'P161': ['Q600'], 'P58': ['Q700'], 'labels': [('en', 'Show 2')]},
    'Q3': {'P8600': ['3'], 'P144': ['Q1', 'Q800'], 'labels': [('en', 'Show 3')]},
    'Q4': {'P8600': ['3', 'x'], 'labels': [('en', 'Show 3 again')]},
    'Q6': {'P345': ['tt1000006'], 'P161': ['Q601'], 'labels': [('en', 'Show 6')]},
    'Q7': {'P8600': ['7'], 'P345': ['tt1000008'], 'labels': [('en', 'Show 7')]},
    'Q500': {'P279': ['Q501'], 'labels': [('en', 'crime television series')]},
    'Q501': {'P279': ['Q502'], 'labels': [('en', 'crime fiction')]},
    'Q502': {'P279': ['Q503'], 'labels': [('en', 'fiction')]},
    'Q503': {'labels': [('en', 'work')]},
    'Q600': {'labels': [('mul', 'Actor Mul'), ('de', 'Schauspieler')]},
    'Q601': {'labels': [('ja', '俳優'), ('zh', '俳優'), ('ko', '배우')]},
    'Q700': {'labels': [('en', 'Maker'), ('mul', 'Maker Mul')]},
    'Q800': {'P179': ['Q801'], 'labels': [('en', 'A Book')]},
    'Q801': {'labels': [('en', 'A Book Series')]},
    # Two crime films well enough known for films.py, and one not.
    'Q950': {'P31': ['Q11424'], 'links': 60, 'P136': ['Q952'], 'P577': ['1972-03-15T00:00:00Z'],
             'labels': [('en', 'The Crime Film')], 'aliases': [('en', 'Crime Film')]},
    'Q951': {'P31': ['Q11424'], 'links': 30, 'P136': ['Q952'], 'labels': [('en', 'Crime Film II')]},
    'Q953': {'P31': ['Q11424'], 'links': 3, 'P136': ['Q952'], 'labels': [('en', 'Obscure Film')]},
    'Q952': {'labels': [('en', 'crime film')]},
}


class Naps:
    """Records the waits the client would sleep."""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


fake = FakeWikidata(ITEMS)
naps = Naps()
client = wikidata.Sparql(fake.url, sleep=naps, log=lambda _line: None, backoff=2)
rows = client.select(wikidata.Q_TVMAZE)
check('a query is POSTed with the agent and the Accept the service asks for', len(rows) == 6
      and fake.queries[-1]['agent'] == 'tv-taste-research/1.0 (https://github.com/jona62/tv-show-research)'
      and fake.queries[-1]['accept'] == 'application/sparql-results+json')
check('answers are read gzipped', client.bytes > 0 and not naps.waits)
fake.script = [(429, {'Retry-After': '7'}, b'Too many requests')]
client.select(wikidata.Q_TVMAZE)
check('a 429 waits out its Retry-After and asks again', naps.waits == [7.0] and fake.tags()[-2:] == ['tvmaze', 'tvmaze'])
naps.waits.clear()
fake.script = [(503, {}, b'busy'), (502, {}, b'bad gateway')]
check('server errors are retried with a growing wait', len(client.select(wikidata.Q_TVMAZE)) == 6 and naps.waits == [2, 4])
naps.waits.clear()
fake.script = [(500, {}, b'java.util.concurrent.TimeoutException')]
check('a query that cannot be split is retried when the service runs out of time',
      len(client.select(wikidata.Q_TVMAZE)) == 6 and naps.waits == [2])
fake.script = [(400, {}, b'Parse error')]
before = len(fake.queries)
rejects('a query the service refuses is not retried', lambda: client.select(wikidata.Q_TVMAZE), wikidata.WikidataError,
        'answered 400')
check('only the one request went out', len(fake.queries) == before + 1)
fake.split_above = 2
batch = ['Q1', 'Q2', 'Q3', 'Q6', 'Q7']
before = len(fake.queries)
answered = [b for b, _rows in wikidata.batched(client, batch, 5, lambda b: wikidata.Q_NAMES.format(items=wikidata.entities(b)))]
check('a batch the service runs out of time on is split in half until it fits',
      answered == [['Q1', 'Q2'], ['Q3'], ['Q6', 'Q7']] and len(fake.queries) - before == 5, answered)
fake.split_above = None
fake.script = [(200, {}, b'{"head": {"vars": []}, "results": {"bindings": [{"item": ')]
answered = [b for b, _rows in wikidata.batched(client, ['Q1', 'Q2'], 5, lambda b: wikidata.Q_NAMES.format(items=wikidata.entities(b)))]
check('an answer cut off part way is treated as out of time', answered == [['Q1'], ['Q2']], answered)
down = FakeWikidata({}, fail=True)
naps.waits.clear()
rejects('a service that stays down is given up on',
        lambda: wikidata.Sparql(down.url, sleep=naps, log=lambda _line: None, backoff=1).select(wikidata.Q_TVMAZE),
        wikidata.WikidataError, 'gave up after 6 attempts')
check('with waits that double', naps.waits == [1, 2, 4, 8, 16], naps.waits)
check('Retry-After is read as seconds or a date', wikidata.retry_after('3', 9) == 3.0 and wikidata.retry_after(None, 9) == 9
      and wikidata.retry_after('Wed, 21 Oct 2015 07:28:00 GMT', 9) == 0.0 and wikidata.retry_after('99999', 9) == 600.0)

by_show = {1: ['Q1'], 3: ['Q3', 'Q4'], 7: ['Q7']}
by_item = {'Q1': {1}, 'Q3': {3}, 'Q4': {3}, 'Q7': {7}}
chosen, skipped = wikidata.match(by_show, by_item, {8: 'tt8', 9: 'tt9', 10: 'tt10', 11: 'tt11', 12: 'tt12'},
                                 {'tt8': {'Q7'}, 'tt9': {'Q90'}, 'tt10': {'Q90'}, 'tt11': {'Q111', 'Q110'}})
check('a show named by several items takes the oldest', chosen[3] == ('Q3', 'p8600'))
check('an IMDb match is taken only for an item with no TVmaze id of its own', 8 not in chosen
      and skipped['item has a TVmaze id'] == 1)
check('an item two shows reach by IMDb goes to neither', 9 not in chosen and 10 not in chosen
      and skipped['item reached twice'] == 2)
check('several items for one IMDb id: the oldest', chosen[11] == ('Q110', 'imdb') and 12 not in chosen)

raw_dir = TMP / 'wikidata-raw'
write_raw(raw_dir, shows=[{'id': i, 'name': f'Show {i}', 'externals': {'imdb': f'tt{1000000 + i}'}} for i in range(1, 9)]
          + [{'id': 9, 'name': 'No IMDb', 'externals': {'imdb': 'nm0000001'}}])
cache = wikidata.fetch(raw_dir, wikidata.Sparql(fake.url, sleep=naps, log=lambda _line: None), log=lambda _line: None,
                       now=NOW)
shows = cache['shows']
check('the fetch maps shows by TVmaze id, then by IMDb id', sorted(shows, key=int) == ['1', '2', '3', '6', '7']
      and cache['mapped'] == {'p8600': 4, 'imdb': 1} and shows['6'] == {'qid': 'Q6', 'via': 'imdb', 'cast': ['Q601'],
                                                                         'names': [['en', 'Show 6']]}, shows)
check('a TVmaze id that is not a number is ignored', 'x' not in shows)
check('each field holds the property values, sorted', shows['1']['genre'] == ['Q500'] and shows['1']['cast'] == ['Q600', 'Q601']
      and shows['1']['maker'] == {'P170': ['Q700']} and shows['2']['maker'] == {'P58': ['Q700']}
      and shows['1']['franchise'] == {'P4969': ['Q3']} and shows['3']['franchise'] == {'P144': ['Q1', 'Q800']})
check('empty fields are left out', 'award' not in shows['1'] and 'subject' not in shows['3'])
check('names are every label and alias', shows['1']['names'] == [['en', 'S1'], ['en', 'Show 1'], ['fr', 'Le Show']])
check('superclasses go two levels up from each genre', cache['parents'] == {'Q500': ['Q501'], 'Q501': ['Q502']})
check('franchise targets carry what they belong to', cache['belongs'] == {'Q800': ['Q801']})
check('labels: English, else the default label, else the one most languages share',
      cache['labels']['Q700'] == 'Maker' and cache['labels']['Q600'] == 'Actor Mul' and cache['labels']['Q601'] == '俳優'
      and cache['labels']['Q801'] == 'A Book Series' and cache['labels']['Q501'] == 'crime fiction')
check('the fetch time and the licence are recorded', cache['fetched_at'] == refresher.iso(NOW)
      and cache['license'] == 'CC0-1.0' and cache['version'] == 1)
body = wikidata.encode(cache)
check('the cache encodes to the same bytes every time, with no gzip timestamp', body == wikidata.encode(json.loads(
    json.dumps(cache))) and body[4:8] == bytes(4))
(TMP / 'cache-v2.json.gz').write_bytes(gzip.compress(json.dumps({**cache, 'version': 2}).encode()))
rejects('a cache of another version is refused', lambda: wikidata.read(TMP / 'cache-v2.json.gz'), ValueError, 'version 1')
check('no cache file reads as None', wikidata.read(TMP / 'no-cache.json.gz') is None)

cli_out = TMP / 'cli-cache.json.gz'
env = {**{k: v for k, v in os.environ.items() if not k.startswith(('TV_', 'WIKIDATA_'))},
       'TV_RAW_DIR': str(raw_dir), 'WIKIDATA_SPARQL_URL': fake.url}
done = subprocess.run([sys.executable, str(SCRIPTS / 'wikidata.py'), '--out', str(cli_out)], env=env,
                      capture_output=True, text=True, timeout=120)
result_line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith('RESULT ')), '')
check('wikidata.py --out writes the cache and ends with RESULT', done.returncode == 0 and cli_out.is_file()
      and json.loads(result_line[len('RESULT '):])['shows'] == 5 and wikidata.read(cli_out)['mapped']['imdb'] == 1,
      done.stdout[-500:] + done.stderr[-500:])
done = subprocess.run([sys.executable, str(SCRIPTS / 'wikidata.py'), '--out', str(TMP / 'never.json.gz')],
                      env={**env, 'WIKIDATA_SPARQL_URL': down.url, 'WIKIDATA_BACKOFF_SECONDS': '0.01'},
                      capture_output=True, text=True, timeout=120)
check('a fetch that fails exits 1 and writes nothing', done.returncode == 1 and 'wikidata: failed' in done.stdout
      and not (TMP / 'never.json.gz').exists(), done.stdout[-300:])
down.close()

# 12. Facets in a version, and the Wikidata step in a run --------------------------------------------------------------


def with_facets(folder, count=100, cache_shows=None):
    """A model folder with real facets built from a small cache."""
    folder = write_model(folder, count)
    raw = write_raw(Path(str(folder) + '-raw'), count)
    (Path(str(folder) + '-cache.json.gz')).write_bytes(wikidata.encode(small_cache(range(1, (cache_shows or count) + 1))))
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('TV_')}, 'TV_MODEL_OUT': str(folder),
           'TV_RAW_DIR': str(raw), 'TV_WIKIDATA': str(folder) + '-cache.json.gz'}
    done = subprocess.run([sys.executable, str(SCRIPTS / 'build_facets.py')], env=env, capture_output=True, text=True)
    if done.returncode:
        raise AssertionError(done.stderr)
    return folder


good = with_facets(TMP / 'facets-good')
check('a version\'s facets are validated and summed up', refresher.validate_version(good)['facets'] == {
    'tokens': 3, 'nonzeros': 100, 'linked': 100, 'aliases': 100, 'wikidata_fetched_at': refresher.iso(NOW)})
check('a version without facets passes, with none', refresher.validate_version(write_model(TMP / 'facets-none', 100))['facets']
      is None)
partial = with_facets(TMP / 'facets-partial')
(partial / 'search.json.gz').unlink()
rejects('facets without their search file are refused', lambda: refresher.validate_version(partial), refresher.Invalid,
        'search.json.gz missing beside')
other = with_facets(TMP / 'facets-other', 99)
mixed = with_facets(TMP / 'facets-mixed')
for name in refresher.FACET_FILES:
    shutil.copyfile(other / name, mixed / name)
rejects('facets built for another catalog are refused', lambda: refresher.validate_version(mixed), refresher.Invalid,
        'facets.bin.gz has 99 rows where the catalog has 100 shows')
columns = with_facets(TMP / 'facets-columns')
meta = json.loads(gunzip(columns / 'facets.json.gz'))
gz(columns / 'facets.json.gz', json.dumps({**meta, 'tokens': meta['tokens'][1:]}).encode())
rejects('a token list that does not match the columns is refused', lambda: refresher.validate_version(columns),
        refresher.Invalid, 'names 2 tokens where facets.bin.gz has 3 columns')
gz(columns / 'facets.json.gz', json.dumps({**meta, 'date': '2020-01-01'}).encode())
rejects('facets from another day are refused', lambda: refresher.validate_version(columns), refresher.Invalid,
        'built for the catalog of 2020-01-01')
gz(columns / 'facets.json.gz', json.dumps(meta).encode())
(columns / 'search.json.gz').write_bytes(b'not gzip')
rejects('a search file that does not decompress is refused', lambda: refresher.validate_version(columns),
        refresher.Invalid, 'does not decompress')
gz(columns / 'search.json.gz', json.dumps({'version': 1, 'aliases': {'500': ['Elsewhere']}}).encode())
rejects('aliases for shows outside the catalog are refused', lambda: refresher.validate_version(columns),
        refresher.Invalid, 'search.json.gz names shows that are not in this catalog')
shutil.copyfile(good / 'search.json.gz', columns / 'search.json.gz')
gz(columns / 'facets.bin.gz', gunzip(good / 'facets.bin.gz')[:-4])
rejects('a truncated facet matrix is refused', lambda: refresher.validate_version(columns), refresher.Invalid,
        'header promises')

runner = FakeRunner()
r = make('seed-facets', runner, seed=with_facets(TMP / 'seed-with-facets'))
r.boot()
check('a seed with facets carries them into the first version', all((r.current()['path'] / n).is_file()
      for n in refresher.FACET_FILES) and r.current()['build']['facets']['linked'] == 100)
half_seed = with_facets(TMP / 'seed-half-facets')
(half_seed / 'facets.json.gz').unlink()
r = make('seed-half', FakeRunner(), seed=half_seed)
r.boot()
check('a seed with only some facet files leaves them behind', r.current() is not None
      and not any((r.current()['path'] / n).exists() for n in refresher.FACET_FILES)
      and r.current()['build']['facets'] is None)

rejects('WIKIDATA_MAX_AGE_DAYS must be a number', lambda: refresher.Config({'WIKIDATA_MAX_AGE_DAYS': 'soon'}),
        ValueError, 'WIKIDATA_MAX_AGE_DAYS')
rejects('WIKIDATA_MAX_AGE_DAYS cannot be negative', lambda: refresher.Config({'WIKIDATA_MAX_AGE_DAYS': '-1'}),
        ValueError, 'WIKIDATA_MAX_AGE_DAYS')
check('WIKIDATA_MAX_AGE_DAYS defaults to a week', refresher.Config({}).wikidata_max_age == timedelta(days=7)
      and refresher.Config({'WIKIDATA_MAX_AGE_DAYS': '0.5'}).wikidata_max_age == timedelta(hours=12))


def wikidata_run(name, server, **env):
    runner = FakeRunner(real_wikidata=True)
    r = make(name, runner, seed=write_model(TMP / f'seed-{name}', 100), WIKIDATA_SPARQL_URL=server.url,
             WIKIDATA_BACKOFF_SECONDS='0.01', **env)
    r.boot()
    return r, runner


def version_facets(r):
    return json.loads(gunzip(r.current()['path'] / 'facets.json.gz'))


# Success: the fetch runs as a child against the pretend service, and the facets use it.
r, runner = wikidata_run('wikidata-ok', fake)
done = run(r)
cache_file, meta_file = r.root / 'wikidata' / 'cache.json.gz', r.root / 'wikidata' / 'meta.json'
check('a run fetches Wikidata when there is no cache', done['outcome'] == 'success' and 'wikidata' in runner.names()
      and not done['warnings'], done)
check('the cache lands in MODEL_ROOT/wikidata', wikidata.read(cache_file)['mapped'] == {'p8600': 4, 'imdb': 1}
      and json.loads(meta_file.read_text())['shows'] == 5 and not (r.root / 'wikidata' / 'cache.new.json.gz').exists())
facets_meta = version_facets(r)
check('the version\'s facets come from it', facets_meta['linked'] == 5
      and facets_meta['wikidata_fetched_at'] == wikidata.read(cache_file)['fetched_at']
      and r.current()['build']['facets']['linked'] == 5)
check('the run records what the fetch found', r.state['wikidata']['shows'] == 5
      and r.state['wikidata']['mapped'] == {'p8600': 4, 'imdb': 1})
status = r.status()
check('status carries the Wikidata cache', status['wikidata']['cache']['shows'] == 5
      and status['wikidata']['max_age_days'] == 7 and status['wikidata']['last']['shows'] == 5)
page = refresher.render_page(status)
check('the page shows the cache and the live facets', '5 shows cached' in page and 'Wikidata fetched' in page
      and 'and Wikidata, CC0' in page)

calls = len(runner.calls)
before = cache_file.read_bytes()
done = run(r)
check('a fresh cache is not fetched again', done['outcome'] == 'success' and 'wikidata' not in runner.names()[calls:]
      and 'build_facets' in runner.names()[calls:] and cache_file.read_bytes() == before)
check('and the log says why', 'is fresh; not fetching it again' in (r.logs / f"{done['id']}.log").read_text())
check('a cache is due again once it is a week old, or fetched by another wikidata.py', r.wikidata_due() is None)
saved = json.loads(meta_file.read_text())
meta_file.write_text(json.dumps({**saved, 'script': '000000000000'}))
check('another wikidata.py makes it due', 'wikidata.py changed' in (r.wikidata_due() or ''))
meta_file.write_text(json.dumps({**saved, 'fetched_at': refresher.iso(NOW - timedelta(days=8))}))
check('eight days makes it due', r.wikidata_due() == 'the cache is 8 days old')

# Failure with a cache: the old one carries on and the run still succeeds.
fake.fail = True
old_bytes = cache_file.read_bytes()
done = run(r)
check('a failed fetch never fails the run', done['outcome'] == 'success' and runner.names()[-6:] == [
    'wikidata', 'build_facets', 'build_films', 'build_cointerest', 'build_neighbours', 'validate'], done)
check('it leaves a warning naming the cache kept', any('Wikidata step failed, keeping the cache fetched' in w
                                                       for w in done['warnings']), done['warnings'])
check('the old cache stays and the facets are built from it', cache_file.read_bytes() == old_bytes
      and version_facets(r)['linked'] == 5 and runner.env_for('build_facets')['TV_WIKIDATA'] == str(cache_file))
check('the failure is recorded', 'gave up' in r.state['wikidata']['error']
      and r.status()['wikidata']['cache']['shows'] == 5)
check('and shown on the page', 'the last try' in refresher.render_page(r.status()))
fake.fail = False

# A fetch that finds far fewer shows than the cache holds is not trusted.
meta_file.write_text(json.dumps({**saved, 'shows': 1000, 'fetched_at': refresher.iso(NOW - timedelta(days=8))}))
done = run(r)
check('a much smaller fetch is refused and the cache kept', done['outcome'] == 'success'
      and any('found 5 shows where the cache has 1,000' in w for w in done['warnings'])
      and cache_file.read_bytes() == old_bytes, done['warnings'])

# A cache that will not build is set aside for the run.
cache_file.write_bytes(b'not a cache')
meta_file.write_text(json.dumps({**saved, 'fetched_at': refresher.iso(NOW)}))
done = run(r)
check('a broken cache is set aside and the facets built from TVmaze alone', done['outcome'] == 'success'
      and any('would not build from the Wikidata cache' in w for w in done['warnings'])
      and runner.names()[-6:] == ['build_facets', 'build_facets', 'build_films', 'build_cointerest',
                                  'build_neighbours', 'validate']
      and version_facets(r)['linked'] == 0, done['warnings'])

# No cache and no Wikidata: TVmaze facets, and a warning.
down = FakeWikidata({}, fail=True)
r, runner = wikidata_run('wikidata-none', down)
done = run(r)
check('with no cache and no Wikidata the run still succeeds', done['outcome'] == 'success'
      and any('building the facets from TVmaze alone' in w for w in done['warnings']), done)
check('its facets say they have no Wikidata', version_facets(r)['linked'] == 0
      and version_facets(r)['wikidata_fetched_at'] is None and not (r.root / 'wikidata' / 'cache.json.gz').exists()
      and 'TV_WIKIDATA' not in runner.env_for('build_facets'))
check('the page says a cache is still to come', 'No cache yet' in refresher.render_page(r.status()))
down.close()

r, runner = wikidata_run('wikidata-always', fake, WIKIDATA_MAX_AGE_DAYS='0')
run(r)
calls = len(runner.calls)
run(r)
check('WIKIDATA_MAX_AGE_DAYS=0 fetches every run', runner.names()[calls:].count('wikidata') == 1)

runner = FakeRunner(fail='build_facets')
r = make('facets-fail', runner, seed=write_model(TMP / 'seed-facets-fail', 100))
r.boot()
before = live(r)
done = run(r)
check('facets that will not build even without the cache fail the run', done['outcome'] == 'failed'
      and 'build_facets failed' in (done['error'] or '') and live(r) == before
      and runner.names()[-2:] == ['build_facets', 'build_facets'], done)

r = make('wikidata-tidy')
(r.root / 'wikidata' / 'cache.new.json.gz').write_bytes(b'half')
(r.root / 'wikidata' / '.cache.new.json.gz.123.456.tmp').write_bytes(b'half')
(r.root / 'wikidata' / 'cache.json.gz').write_bytes(b'kept')
r.take_file_lock()
r.tidy()
r.release_file_lock()
check('an interrupted fetch\'s leftovers are cleared, and the cache kept',
      sorted(p.name for p in (r.root / 'wikidata').iterdir()) == ['cache.json.gz'])

# 13. Films: the film cache, and each version's film index -------------------------------------------------------------

films_ok = write_model(TMP / 'films-valid', 100)
write_films(films_ok, 4)
check('a version\'s film index is validated and summed up', refresher.validate_version(films_ok)['films'] == {
    'films': 4, 'series': 0, 'wikidata_fetched_at': refresher.iso(NOW)})
check('a version without a film index passes, with none',
      refresher.validate_version(write_model(TMP / 'films-none', 100))['films'] is None)
committed = refresher.check_films(ROOT / 'model')
check('the committed film index, which a seed carries, passes too', committed is not None
      and committed['films'] > 5000 and committed['series'] > 100, committed)
index = json.loads(gunzip(films_ok / 'films.json.gz'))
bad = write_model(TMP / 'films-bad', 100)
(bad / 'films.json.gz').write_bytes(b'not gzip')
rejects('a film index that does not decompress is refused', lambda: refresher.validate_version(bad), refresher.Invalid,
        'films.json.gz does not decompress')
for label, value in (('of another version', {**index, 'version': 2}), ('with no films', {**index, 'films': []}),
                     ('that is a list', index['films'])):
    gz(bad / 'films.json.gz', json.dumps(value).encode())
    rejects(f'a film index {label} is refused', lambda: refresher.validate_version(bad), refresher.Invalid,
            'holds no version 1 film list')
for label, change in (('with no title', {'title': ' '}), ('with an IMDb id for a Q-id', {'qid': 'tt0068646'}),
                      ('with a genre weighed above 1', {'genre': {'crime': 1.5}}),
                      ('with a genre weighed 0', {'genre': {'crime': 0}}),
                      ('with a subject that is no Q-id', {'subject': {'crime': 1.0}}),
                      ('with names that are not text', {'aliases': [3]})):
    gz(bad / 'films.json.gz', json.dumps({**index, 'films': [{**index['films'][0], **change}]}).encode())
    rejects(f'a film {label} is refused', lambda: refresher.validate_version(bad), refresher.Invalid,
            'holds a malformed film')

# A run: the cache is fetched when due and the index built from it each time.
runner = FakeRunner()
r = make('films-run', runner, seed=write_model(TMP / 'seed-films-run', 100))
r.boot()
done = run(r)
film_cache, film_meta = r.root / 'films' / 'cache.json.gz', r.root / 'films' / 'meta.json'
check('a run fetches the film cache when there is none and builds the index from it', done['outcome'] == 'success'
      and runner.names().count('films') == 1 and not done['warnings']
      and r.current()['build']['films'] == {'films': 3, 'series': 0, 'wikidata_fetched_at': refresher.iso(NOW)}, done)
check('the run records what the fetch found', r.state['films']['films'] == 4 and r.state['films']['series'] == 1)
status = r.status()
check('status carries the film cache', status['films']['cache'] == {'fetched_at': refresher.iso(NOW), 'films': 4,
                                                                    'series': 1} and status['films']['last']['films'] == 4)
page = refresher.render_page(status)
check('the page shows the film cache and the live index', '<h2>Films</h2><p>4 films and series cached' in page
      and '3 films and series, 0 of them series; from Wikidata fetched' in page)
calls, before = len(runner.calls), film_cache.read_bytes()
done = run(r)
check('a fresh film cache is not fetched again, but each build maps it again', done['outcome'] == 'success'
      and 'films' not in runner.names()[calls:] and 'build_films' in runner.names()[calls:]
      and film_cache.read_bytes() == before)
check('and the log says why', 'films: the cache fetched' in (r.logs / f"{done['id']}.log").read_text())
check('the film cache is due on the Wikidata cache\'s terms', r.films_due() is None)
saved = json.loads(film_meta.read_text())
film_meta.write_text(json.dumps({**saved, 'script': '000000000000'}))
check('another films.py makes it due', r.films_due() == 'films.py changed since the cache was fetched')
film_meta.write_text(json.dumps({**saved, 'fetched_at': None}))
check('a cache with no fetch date is due', r.films_due() == 'the cache carries no fetch date')
film_meta.write_text(json.dumps({**saved, 'fetched_at': refresher.iso(NOW - timedelta(days=8))}))
check('eight days makes it due', r.films_due() == 'the cache is 8 days old')

# A failed fetch keeps the cache there is, and the run goes on.
runner.fail = 'films'
calls = len(runner.calls)
done = run(r)
check('a failed film fetch never fails the run', done['outcome'] == 'success'
      and runner.names()[calls:].count('films') == 1 and 'build_films' in runner.names()[calls:], done)
check('it leaves a warning naming the cache kept', any('Film step failed, keeping the cache fetched' in w
                                                       for w in done['warnings']), done['warnings'])
check('the old cache stays and the index is built from it', film_cache.read_bytes() == before
      and runner.env_for('build_films')['TV_FILMS'] == str(film_cache) and r.current()['build']['films']['films'] == 3)
check('the failure is recorded and shown', 'films fell over' in r.state['films']['error']
      and r.status()['films']['cache']['films'] == 4 and 'failed: films failed with exit code 1: films fell over'
      in refresher.render_page(r.status()))
runner.fail = None

# A fetch that finds far fewer films than the cache holds is not trusted.
film_meta.write_text(json.dumps({**saved, 'films': 1000, 'fetched_at': refresher.iso(NOW - timedelta(days=8))}))
done = run(r)
check('a much smaller film fetch is refused and the cache kept', done['outcome'] == 'success'
      and any('found 4 films where the cache has 1,000' in w for w in done['warnings'])
      and film_cache.read_bytes() == before and not (r.root / 'films' / 'cache.new.json.gz').exists(), done['warnings'])

# An index that will not build: the live version's is carried forward.
film_meta.write_text(json.dumps(saved))
old_index = gunzip(r.current()['path'] / 'films.json.gz')
runner.fail = 'build_films'
done = run(r)
check('a film index that will not build never fails the run', done['outcome'] == 'success'
      and any('The film index would not build: build_films failed' in w for w in done['warnings']), done)
check('the live version\'s index is carried forward', gunzip(r.current()['path'] / 'films.json.gz') == old_index
      and r.current()['build']['films']['films'] == 3
      and "carried the live version's film index forward" in (r.logs / f"{done['id']}.log").read_text())
runner.fail = None

# No cache and no live index: no index, and a warning.
runner = FakeRunner(fail='films')
r = make('films-never', runner, seed=write_model(TMP / 'seed-films-never', 100))
r.boot()
done = run(r)
check('with no film cache and no fetch the run still succeeds, with no index', done['outcome'] == 'success'
      and any('Film step failed, and there is no film cache yet' in w for w in done['warnings'])
      and 'build_films' not in runner.names() and not (r.current()['path'] / 'films.json.gz').exists()
      and r.current()['build']['films'] is None and not (r.root / 'films' / 'cache.json.gz').exists(), done)
check('the page says a film cache is still to come',
      '<h2>Films</h2><p>No cache yet; the next build fetches one</p>' in refresher.render_page(r.status()))

# A seed's index goes live, and is carried forward while there is no cache to build from.
seed = write_model(TMP / 'seed-films', 100)
write_films(seed, 2)
runner = FakeRunner(fail='films')
r = make('seed-films', runner, seed=seed)
r.boot()
check('a seed with a film index carries it into the first version', r.current() is not None
      and r.current()['build']['films'] == {'films': 2, 'series': 0, 'wikidata_fetched_at': refresher.iso(NOW)})
done = run(r)
check('a version with no film cache to build from carries the live index forward', done['outcome'] == 'success'
      and r.current()['build']['films']['films'] == 2
      and filecmp.cmp(seed / 'films.json.gz', r.current()['path'] / 'films.json.gz', shallow=False), done)

runner = FakeRunner()
r = make('films-always', runner, seed=write_model(TMP / 'seed-films-always', 100), WIKIDATA_MAX_AGE_DAYS='0')
r.boot()
run(r)
calls = len(runner.calls)
run(r)
check('WIKIDATA_MAX_AGE_DAYS=0 fetches the films every run too', runner.names()[calls:].count('films') == 1
      and r.films_due() == 'WIKIDATA_MAX_AGE_DAYS is 0')

r = make('films-tidy')
(r.root / 'films' / 'cache.new.json.gz').write_bytes(b'half')
(r.root / 'films' / '.cache.new.json.gz.123.456.tmp').write_bytes(b'half')
(r.root / 'films' / 'cache.json.gz').write_bytes(b'kept')
r.take_file_lock()
r.tidy()
r.release_file_lock()
check('an interrupted film fetch\'s leftovers are cleared, and the cache kept',
      sorted(p.name for p in (r.root / 'films').iterdir()) == ['cache.json.gz'])

# The real fetch and build, as child processes, against the pretend service.
runner = FakeRunner(real_wikidata=True, real_films=True)
r = make('films-real', runner, seed=write_model(TMP / 'seed-films-real', 100), WIKIDATA_SPARQL_URL=fake.url,
         WIKIDATA_BACKOFF_SECONDS='0.01')
r.boot()
asked = len(fake.queries)
done = run(r)
cache = json.loads(gunzip(r.root / 'films' / 'cache.json.gz'))
built = json.loads(gunzip(r.current()['path'] / 'films.json.gz'))
check('films.py fetches the films well enough known', done['outcome'] == 'success' and not done['warnings']
      and sorted(cache['films']) == ['Q950', 'Q951'] and cache['films']['Q950']['year'] == 1972
      and cache['labels'] == {'Q952': 'crime film'}, done)
check('build_films.py maps them to the version\'s facets, best known first',
      [(f['title'], f['aliases'], f['genre']) for f in built['films']]
      == [('The Crime Film', ['Crime Film'], {'crime': 1.0}), ('Crime Film II', [], {'crime': 1.0})]
      and built['date'] == version_facets(r)['date'] and r.current()['build']['films']['films'] == 2, built)
film_asks = [q for q in fake.queries[asked:] if q['query'].split('\n', 1)[0] in ('#films', '#film-names')]
check('its requests carry the project\'s User-Agent and no email address', film_asks
      and all(q['agent'] == wikidata.AGENT and '@' not in q['agent'] for q in fake.queries[asked:]))
fake.close()

# 14. The clickstream and the co-interest -----------------------------------------------------------------------------


class FakeClickstream:
    """A pretend dumps.wikimedia.org/other/clickstream: an index of month folders and, in
    each, a small gzipped TSV of prev, curr, type and n, as the dumps hold them. A month
    can answer 500, send a gzip stream cut off part way, or hang until released, and the
    index can be down. Every request is recorded."""

    def __init__(self, months):
        self.months = dict(months)
        self.fail, self.cut, self.hold = set(), set(), set()
        self.release = threading.Event()
        self.down = False
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fake.requests.append(self.path)
                status, body = fake.answer(self.path)
                try:
                    self.send_response(status)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/clickstream'

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()

    def files(self, since=0):
        """The months whose files were asked for, in order."""
        return [re.search(r'/(\d{4}-\d{2})/', path)[1] for path in self.requests[since:] if path.endswith('.tsv.gz')]

    def answer(self, path):
        if path == '/clickstream/':
            if self.down:
                return 503, b'Service Unavailable'
            rows = ''.join(f'<a href="{m}/">{m}/</a>{" " * 43}07-Dec-2026 22:47    -\n' for m in sorted(self.months))
            return 200, f'<html><body><pre><a href="../">../</a>\n{rows}</pre></body></html>'.encode()
        found = re.fullmatch(r'/clickstream/(\d{4}-\d{2})/clickstream-enwiki-(\d{4}-\d{2})\.tsv\.gz', path)
        if not found or found[1] != found[2] or found[1] not in self.months:
            return 404, b'Not Found'
        month = found[1]
        if month in self.hold:
            self.release.wait(30)
        if month in self.fail:
            return 500, b'Internal Server Error'
        body = gzip.compress(self.months[month].encode(), mtime=0)
        return 200, body[:len(body) // 2] if month in self.cut else body


def tsv(*links):
    """A month of clickstream: the links given, among many from articles that are not shows."""
    return ''.join([f'{a}\t{b}\t{kind}\t{n}\n' for a, b, kind, n in links]
                   + [f'Main_Page\tArticle_{i}\tlink\t{10 + i}\n' for i in range(2000)])


# Six shows with English articles, and the months the pretend dumps can publish.
TITLED = {f'Q{i}': {'P8600': [str(i)], 'enwiki': f'Show {i}'} for i in range(1, 7)}
DUMPS = {
    '2026-05': tsv(('Show_5', 'Show_6', 'link', 900)),
    '2026-06': tsv(('Show_1', 'Show_2', 'link', 120), ('Show_2', 'Show_1', 'link', 30), ('Show_1', 'Show_3', 'link', 50)),
    '2026-07': tsv(('Show_1', 'Show_2', 'link', 100), ('Show_3', 'Show_4', 'link', 40)),
    '2026-08': tsv(('Show_1', 'Show_2', 'link', 80), ('Show_1', 'Show_1', 'link', 999),
                   ('Show_2', 'Show_4', 'external', 70)),
    '2026-09': tsv(('Show_2', 'Show_6', 'link', 500)),
    '2026-10': tsv(('Show_4', 'Show_5', 'link', 70)),
    '2026-11': tsv(('Show_1', 'Show_6', 'link', 60)),
}
titles = FakeWikidata(TITLED)


def clickstream_run(name, dumps):
    runner = FakeRunner(real_clickstream=True)
    r = make(name, runner, seed=write_model(TMP / f'seed-{name}', 100), CLICKSTREAM_BASE=dumps.url,
             WIKIDATA_SPARQL_URL=titles.url)
    r.boot()
    return r, runner


def links(r):
    """The live version's co-interest as the pairs of show ids it links, or None."""
    matrix = facets.cointerest(r.current()['path'], r.current()['build']['shows'])
    if matrix is None:
        return None
    indptr, indices, _values = matrix
    return {(i + 1, indices[k] + 1) for i in range(len(indptr) - 1) for k in range(indptr[i], indptr[i + 1])}


def on_day(r, n):
    r.clock = lambda: NOW + timedelta(days=n)


def coi_months(r):
    return (r.current()['build'].get('cointerest') or {}).get('months')


# The first fetch: no cache, so clickstream.py reads the listing itself and streams the
# latest three months into the cache, and the co-interest is built from them.
dumps = FakeClickstream({m: DUMPS[m] for m in ('2026-05', *PUBLISHED)})
r, runner = clickstream_run('clickstream', dumps)
done = run(r)
cache_file, meta_file = r.root / 'clickstream' / 'cache.json.gz', r.root / 'clickstream' / 'meta.json'
held = clickstream.read(cache_file)
check('a first run fetches the latest three published months', done['outcome'] == 'success' and not done['warnings']
      and held is not None and sorted(held['months']) == PUBLISHED, (done['warnings'], held and sorted(held['months'])))
check('each is streamed once, and the older month not at all', sorted(dumps.files()) == PUBLISHED, dumps.requests)
check('with no cache there is no separate look at the listing', 'clickstream check' not in runner.names()
      and dumps.requests.count('/clickstream/') == 1)
check('the cache counts links between shows\' articles, both ways added', held['months']['2026-06'] == {'1-2': 150, '1-3': 50}
      and held['months']['2026-08'] == {'1-2': 80} and held['titles']['6'] == 'Show_6', held['months'])
check('meta.json records the months, the listing and the script', json.loads(meta_file.read_text()) == {
    'fetched_at': refresher.iso(NOW), 'months': PUBLISHED, 'titles': 6, 'script': r.clickstream_script,
    'checked_at': refresher.iso(NOW), 'published': PUBLISHED}, meta_file.read_text())
check('the co-interest lands in the version', all((r.current()['path'] / n).is_file() for n in refresher.COINTEREST_FILES)
      and links(r) == {(1, 2), (2, 1), (1, 3), (3, 1), (3, 4), (4, 3)}, links(r))
check('build.json says what it was built from', r.current()['build']['cointerest'] == {
    'months': PUBLISHED, 'shows': 4, 'links': 6}, r.current()['build']['cointerest'])
check('the fetch is told where the dumps and the title service are',
      runner.env_for('clickstream')['CLICKSTREAM_BASE'] == dumps.url
      and runner.env_for('clickstream')['WIKIDATA_SPARQL_URL'] == titles.url)
check('the cache is readable by other users, like all the service writes', readable(r.root) is None, readable(r.root))
status = r.status()
check('status carries the months held', status['clickstream']['months'] == 3
      and status['clickstream']['cache']['months'] == PUBLISHED and status['clickstream']['last']['fetched'] == PUBLISHED,
      status['clickstream'])
page = refresher.render_page(status)
check('the page shows them, and the live co-interest', '3 months held: 2026-06, 2026-07, 2026-08' in page
      and '6 links among 4 shows' in page and 'clickstream, CC0' in page)

since, calls = len(dumps.requests), len(runner.calls)
done = run(r)
check('later the same day the dumps are not asked again', done['outcome'] == 'success' and len(dumps.requests) == since
      and not {'clickstream check', 'clickstream'} & set(runner.names()[calls:])
      and 'build_cointerest' in runner.names()[calls:] and coi_months(r) == PUBLISHED)
check('and the log says why', 'names nothing it lacks; not fetching' in (r.logs / f"{done['id']}.log").read_text())

on_day(r, 1)
since, calls = len(dumps.requests), len(runner.calls)
done = run(r)
check('the next day the listing is read, once, and nothing fetched', done['outcome'] == 'success'
      and runner.names()[calls:].count('clickstream check') == 1 and 'clickstream' not in runner.names()[calls:]
      and dumps.requests[since:] == ['/clickstream/']
      and json.loads(meta_file.read_text())['checked_at'] == refresher.iso(NOW + timedelta(days=1)))

# A later month appears: it is found by the next day's look and fetched alone.
dumps.months['2026-09'] = DUMPS['2026-09']
calls = len(runner.calls)
run(r)
check('a month out later that day waits for the next day\'s look', 'clickstream' not in runner.names()[calls:])
on_day(r, 2)
since, calls = len(dumps.requests), len(runner.calls)
done = run(r)
check('the next day it is found and fetched alone', done['outcome'] == 'success' and not done['warnings']
      and runner.names()[calls:].count('clickstream check') == 1 and dumps.files(since) == ['2026-09'],
      (done['warnings'], dumps.requests[since:]))
check('the cache keeps the months it had beside it', sorted(clickstream.read(cache_file)['months']) == PUBLISHED + ['2026-09']
      and json.loads(meta_file.read_text())['months'] == PUBLISHED + ['2026-09'])
check('and the version is built from the latest three', coi_months(r) == ['2026-07', '2026-08', '2026-09']
      and (2, 6) in links(r) and (1, 3) not in links(r), links(r))

# A month that breaks off part way, then fails outright: the cache carries on without it.
dumps.months['2026-10'] = DUMPS['2026-10']
dumps.cut.add('2026-10')
on_day(r, 3)
kept = clickstream.read(cache_file)['months']
done = run(r)
check('a month cut off part way never fails the run', done['outcome'] == 'success'
      and any(w.startswith('The clickstream for 2026-10 did not download') for w in done['warnings']), done['warnings'])
check('the cache keeps its months, and the version is built from them', clickstream.read(cache_file)['months'] == kept
      and coi_months(r) == ['2026-07', '2026-08', '2026-09'])
check('the page says which month is missing', '2026-10 did not download' in refresher.render_page(r.status()))
dumps.cut.clear()
dumps.fail.add('2026-10')
since, calls = len(dumps.requests), len(runner.calls)
done = run(r)
check('a missing month is tried again next run, not waiting for the next day\'s look',
      'clickstream check' not in runner.names()[calls:] and dumps.files(since) == ['2026-10']
      and any('2026-10 did not download' in w and '500' in w for w in done['warnings']), done['warnings'])
dumps.fail.clear()
done = run(r)
check('once it downloads it is used', done['outcome'] == 'success' and not done['warnings']
      and coi_months(r) == ['2026-08', '2026-09', '2026-10'] and (4, 5) in links(r), done['warnings'])

# The title query failing fails the whole fetch: the cache stays, and so does the run.
dumps.months['2026-11'] = DUMPS['2026-11']
on_day(r, 4)
titles.fail = True
before = cache_file.read_bytes()
done = run(r)
check('a fetch that fails outright keeps the cache, and the run succeeds', done['outcome'] == 'success'
      and any(w.startswith('Clickstream step failed, keeping the cache of 2026-06, 2026-07, 2026-08, 2026-09, 2026-10')
              for w in done['warnings'])
      and cache_file.read_bytes() == before and coi_months(r) == ['2026-08', '2026-09', '2026-10'], done['warnings'])
check('the failure is recorded, and shown', 'HTTP Error 503' in (r.state['clickstream'].get('error') or '')
      and 'the last try' in refresher.render_page(r.status()), r.state['clickstream'])
titles.fail = False

# Another clickstream.py counts every month again beside the cache, which it replaces
# only when the count has every month the cache had.
saved = json.loads(meta_file.read_text())
meta_file.write_text(json.dumps({**saved, 'script': '000000000000'}))
since = len(dumps.requests)
done = run(r)
recount = next(call for call in reversed(runner.calls) if call['name'] == 'clickstream')
check('a changed clickstream.py counts every month again, beside the cache', done['outcome'] == 'success'
      and not done['warnings'] and recount['argv'][-4:] == ['--cache', str(r.root / 'clickstream' / 'cache.new.json.gz'),
                                                           '--months', '3']
      and sorted(dumps.files(since)) == ['2026-09', '2026-10', '2026-11'], (done['warnings'], dumps.files(since)))
check('and the count takes the cache\'s place', sorted(clickstream.read(cache_file)['months']) == ['2026-09', '2026-10', '2026-11']
      and json.loads(meta_file.read_text())['script'] == r.clickstream_script
      and not (r.root / 'clickstream' / 'cache.new.json.gz').exists() and coi_months(r) == ['2026-09', '2026-10', '2026-11'])
meta_file.write_text(json.dumps({**json.loads(meta_file.read_text()), 'script': '000000000000'}))
dumps.fail.add('2026-10')
before = cache_file.read_bytes()
done = run(r)
check('a count that comes up short leaves the cache as it was', done['outcome'] == 'success'
      and any('counting again came up without 2026-10' in w for w in done['warnings']) and cache_file.read_bytes() == before
      and not (r.root / 'clickstream' / 'cache.new.json.gz').exists(), done['warnings'])
dumps.fail.clear()
done = run(r)
check('and the next run counts again', done['outcome'] == 'success' and not done['warnings']
      and json.loads(meta_file.read_text())['script'] == r.clickstream_script)

# A cache that will not build is set aside for the run, and counted again the next.
cache_file.write_bytes(b'not a cache')
calls = len(runner.calls)
done = run(r)
check('a cache that will not build is set aside, and the version has no co-interest', done['outcome'] == 'success'
      and any('would not build from the clickstream cache' in w for w in done['warnings'])
      and runner.names()[calls:][-4:] == ['build_cointerest', 'build_cointerest', 'build_neighbours', 'validate']
      and r.current()['build']['cointerest'] is None and links(r) is None, done['warnings'])
check('its meta.json goes, so the next run looks the cache over', not meta_file.exists())
done = run(r)
check('which counts it again from nothing', done['outcome'] == 'success' and not done['warnings']
      and sorted(clickstream.read(cache_file)['months']) == ['2026-09', '2026-10', '2026-11']
      and coi_months(r) == ['2026-09', '2026-10', '2026-11']
      and 'counting it again from nothing' in (r.logs / f"{done['id']}.log").read_text(), done['warnings'])
dumps.close()

# A listing that will not load: a warning, the cache serves, and it is read next run.
quiet = FakeClickstream({m: DUMPS[m] for m in PUBLISHED})
r, runner = clickstream_run('clickstream-listing', quiet)
run(r)
on_day(r, 1)
quiet.down = True
done = run(r)
check('a listing that will not load is a warning, and the cache serves', done['outcome'] == 'success'
      and any(w.startswith('Could not read which clickstream months are out, keeping the cache of 2026-06, 2026-07, 2026-08')
              for w in done['warnings']) and coi_months(r) == PUBLISHED, done['warnings'])
check('the day\'s look is still to come', json.loads((r.root / 'clickstream' / 'meta.json').read_text())['checked_at']
      == refresher.iso(NOW))
quiet.down = False
calls = len(runner.calls)
done = run(r)
check('so the next run reads it', runner.names()[calls:].count('clickstream check') == 1 and not done['warnings'])
quiet.close()

# No cache and no clickstream: the version simply has no co-interest.
gone = FakeClickstream({})
gone.down = True
r, runner = clickstream_run('clickstream-none', gone)
done = run(r)
check('with no cache and no clickstream the run succeeds, without co-interest', done['outcome'] == 'success'
      and any(w.startswith('Clickstream step failed, so this version has no co-interest') for w in done['warnings'])
      and not any((r.current()['path'] / n).exists() for n in refresher.COINTEREST_FILES)
      and r.current()['build']['cointerest'] is None, done['warnings'])
check('build_cointerest is told there is none', runner.env_for('build_cointerest')['TV_COINTEREST'] == ''
      and not (r.root / 'clickstream' / 'cache.json.gz').exists())
check('the page says the months are still to come', 'No months held yet' in refresher.render_page(r.status()))
gone.close()

# A cache put in place by hand, say a copy of data/cointerest.json.gz, is taken as it is.
handed = FakeClickstream({m: DUMPS[m] for m in PUBLISHED})
r, runner = clickstream_run('clickstream-by-hand', handed)
clickstream.write(r.root / 'clickstream' / 'cache.json.gz', {
    'version': 1, 'titles': {}, 'months': {'2026-06': {'1-2': 5}, '2026-07': {'1-2': 5}}})
done = run(r)
check('a cache put there by hand is taken as it is, and only what it lacks is fetched', done['outcome'] == 'success'
      and not done['warnings'] and handed.files() == ['2026-08']
      and sorted(clickstream.read(r.root / 'clickstream' / 'cache.json.gz')['months']) == PUBLISHED
      and json.loads((r.root / 'clickstream' / 'meta.json').read_text())['script'] == r.clickstream_script,
      (done['warnings'], handed.files()))
handed.close()

# A fetch stopped part way keeps the months it finished.
slow = FakeClickstream({m: DUMPS[m] for m in PUBLISHED})
slow.hold.add('2026-08')
stopped = TMP / 'stopped' / 'cache.json.gz'
proc = subprocess.Popen([sys.executable, str(SCRIPTS / 'clickstream.py'), '--cache', str(stopped), '--months', '3'],
                        env={**os.environ, 'CLICKSTREAM_BASE': slow.url, 'WIKIDATA_SPARQL_URL': titles.url},
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
wait_for(lambda: '2026-08' in slow.files())
proc.kill()
proc.wait()
check('a fetch stopped part way keeps the months it finished', stopped.is_file()
      and sorted(clickstream.read(stopped)['months']) == ['2026-06', '2026-07'])
slow.close()
titles.close()

r = make('clickstream-tidy')
(r.root / 'clickstream' / 'cache.new.json.gz').write_bytes(b'half')
(r.root / 'clickstream' / 'cache.json.gz.k2j3h4.tmp').write_bytes(b'half')
(r.root / 'clickstream' / 'cache.json.gz').write_bytes(b'kept')
r.take_file_lock()
r.tidy()
r.release_file_lock()
check('an interrupted count\'s leftovers are cleared, and the cache kept',
      sorted(p.name for p in (r.root / 'clickstream').iterdir()) == ['cache.json.gz'])


def cointerest_files(folder, rows, linked, months=('2026-08',), magic=b'COI1'):
    """Co-interest files by hand: linked maps a row to [(column, similarity), ...]."""
    indptr, indices, values = [0], [], []
    for i in range(rows):
        for j, s in linked.get(i, ()):
            indices.append(j)
            values.append(s)
        indptr.append(len(indices))
    gz(folder / 'cointerest.bin.gz', struct.pack('<4sII', magic, rows, len(indices))
       + struct.pack(f'<{rows + 1}I', *indptr) + struct.pack(f'<{len(indices)}I', *indices)
       + struct.pack(f'<{len(values)}f', *values))
    gz(folder / 'cointerest.json.gz', json.dumps({'version': 1, 'months': list(months), 'pairs': len(indices) // 2,
                                                  'shows': len(linked), 'license': 'CC0-1.0'}).encode())
    return folder


pair = {0: [(1, 0.5)], 1: [(0, 0.5)]}
good = cointerest_files(write_model(TMP / 'coi-good', 100), 100, pair)
check('a version\'s co-interest is validated and summed up', refresher.validate_version(good)['cointerest'] == {
    'months': ['2026-08'], 'shows': 2, 'links': 2})
check('a version without co-interest passes, with none',
      refresher.validate_version(write_model(TMP / 'coi-none', 100))['cointerest'] is None)
lone = cointerest_files(write_model(TMP / 'coi-lone', 100), 100, pair)
(lone / 'cointerest.json.gz').unlink()
rejects('a co-interest matrix without its metadata is refused', lambda: refresher.validate_version(lone),
        refresher.Invalid, 'cointerest.json.gz missing beside cointerest.bin.gz')
bad = write_model(TMP / 'coi-bad', 100)
for label, make_files, said in (
        ('built for another catalog', lambda: cointerest_files(bad, 99, pair), 'has 99 rows where the catalog has 100'),
        ('of another kind', lambda: cointerest_files(bad, 100, pair, magic=b'FAC1'), 'is not co-interest data'),
        ('linking outside the catalog', lambda: cointerest_files(bad, 100, {0: [(100, 0.5)]}), 'not in this catalog'),
        ('with a similarity of zero', lambda: cointerest_files(bad, 100, {0: [(1, 0.0)]}), 'not above zero'),
        ('with a similarity that is not a number', lambda: cointerest_files(bad, 100, {0: [(1, float('nan'))]}),
         'not above zero'),
        ('naming no months', lambda: cointerest_files(bad, 100, pair, months=()), 'names no clickstream months')):
    make_files()
    rejects(f'co-interest {label} is refused', lambda: refresher.validate_version(bad), refresher.Invalid, said)
cointerest_files(bad, 100, pair)
gz(bad / 'cointerest.bin.gz', gunzip(bad / 'cointerest.bin.gz')[:-4])
rejects('a truncated co-interest matrix is refused', lambda: refresher.validate_version(bad), refresher.Invalid,
        'truncated')
cointerest_files(bad, 100, pair)
(bad / 'cointerest.json.gz').write_bytes(b'not gzip')
rejects('co-interest metadata that does not decompress is refused', lambda: refresher.validate_version(bad),
        refresher.Invalid, 'cointerest.json.gz does not decompress')

seed = cointerest_files(write_model(TMP / 'seed-coi', 100), 100, pair)
r = make('seed-coi', FakeRunner(), seed=seed)
r.boot()
check('a seed with co-interest carries it into the first version', all((r.current()['path'] / n).is_file()
      for n in refresher.COINTEREST_FILES) and r.current()['build']['cointerest'] == {
    'months': ['2026-08'], 'shows': 2, 'links': 2})
half_seed = cointerest_files(write_model(TMP / 'seed-coi-half', 100), 100, pair)
(half_seed / 'cointerest.json.gz').unlink()
r = make('seed-coi-half', FakeRunner(), seed=half_seed)
r.boot()
check('a seed with only the matrix leaves it behind', r.current() is not None
      and not (r.current()['path'] / 'cointerest.bin.gz').exists() and r.current()['build']['cointerest'] is None)

# 15. download.py --out --------------------------------------------------------------------------------------------

pages = {0: [{'id': 1}, {'id': 2}], 1: [{'id': 250}]}


def fake_urlopen(url, timeout=None):
    if url.endswith('/updates/shows'):
        return io.BytesIO(json.dumps({'1': 1, '2': 2, '250': 3}).encode())
    return io.BytesIO(json.dumps(pages[int(url.rsplit('=', 1)[1])]).encode())


out = TMP / 'download-out'
sentinel = TMP / 'must-stay-empty'
saved_env = {k: os.environ.get(k) for k in ('TV_RAW_DIR', 'TV_MANIFEST')}
saved_argv, real_urlopen = sys.argv, urllib.request.urlopen
os.environ.update(TV_RAW_DIR=str(sentinel / 'raw'), TV_MANIFEST=str(sentinel / 'manifest.json'))
urllib.request.urlopen = fake_urlopen
try:
    sys.argv = ['download.py', '--out', str(out)]
    with redirect_stdout(io.StringIO()):
        runpy.run_path(str(SCRIPTS / 'download.py'), run_name='__main__')
    sys.argv = ['download.py', '--refresh', '--out', str(out)]
    with redirect_stderr(io.StringIO()):
        try:
            runpy.run_path(str(SCRIPTS / 'download.py'), run_name='__main__')
            combined = 0
        except SystemExit as exc:
            combined = exc.code
finally:
    sys.argv, urllib.request.urlopen = saved_argv, real_urlopen
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
manifest = json.loads((out / 'manifest.json').read_text())
check('download --out writes every page, the updates and a manifest into DIR',
      sorted(p.name for p in out.iterdir()) == ['manifest.json', 'page-000.json', 'page-001.json', 'updates.json'])
check('the --out manifest lists the pages', manifest['pages'] == 2 and manifest['records'] == 3
      and sorted(manifest['files']) == ['page-000.json', 'page-001.json'])
check('download --out leaves the default paths alone', not sentinel.exists())
check('--refresh and --out together are refused', combined == 2)

# 16. End to end with the real build steps (opt in) -------------------------------------------------------------------


def full_test(raw_dir, manifest):
    seed = TMP / 'full-seed'
    seed.mkdir()
    for name in ('catalog.json.gz', 'vectors.bin.gz', 'popularity.bin.gz'):
        shutil.copyfile(ROOT / 'model' / name, seed / name)
    # Wikidata is the pretend service: a few real TVmaze ids, so the facets have links, and
    # English articles for them, which a month of pretend clickstream links.
    service = FakeWikidata({q: {**d, 'enwiki': f"Show {d['P8600'][0]}"} if d.get('P8600') else d
                            for q, d in ITEMS.items()})
    dumps = FakeClickstream({'2026-08': tsv(('Show_1', 'Show_2', 'link', 90), ('Show_2', 'Show_7', 'link', 30))})
    config = refresher.Config({'MODEL_ROOT': str(TMP / 'full-root'), 'SEED_MODEL_DIR': str(seed),
                               'RAW_SOURCE_DIR': str(raw_dir), 'AUTO_DELAY_SECONDS': '0',
                               'WIKIDATA_SPARQL_URL': service.url, 'CLICKSTREAM_BASE': dumps.url})
    r = refresher.Refresher(config, quiet=True)
    r.start(schedule=False)
    r.boot()
    seeded = r.current()
    check('the real seed goes live with art built from the pages', seeded is not None
          and seeded['build']['seeded_from'] == str(seed) and (seeded['path'] / 'art.bin.gz').exists())
    check('the seed\'s art matches the committed art', seeded is not None
          and gunzip(seeded['path'] / 'art.bin.gz') == gunzip(ROOT / 'couchside' / 'art.bin.gz'))
    done = run(r, timeout=7200)
    check('a real full run succeeds', done['outcome'] == 'success', done.get('error'))
    cur = r.current()
    check('current points at the new, complete version', cur is not None and cur['version'] == done['version']
          and live(r) == f"versions/{done['version']}" and (cur['path'] / 'build.json').exists())
    check('the new version passes validation', cur is not None
          and refresher.validate_version(cur['path'])['shows'] == cur['build']['shows'])
    for name in ('catalog.json.gz', 'vectors.bin.gz'):
        check(f'the refresher rebuilds {name} byte for byte', cur is not None
              and filecmp.cmp(cur['path'] / name, ROOT / 'model' / name, shallow=False))
    check('the refresher rebuilds popularity with the committed content', cur is not None
          and gunzip(cur['path'] / 'popularity.bin.gz') == gunzip(ROOT / 'model' / 'popularity.bin.gz'))
    check('the refresher rebuilds art with the committed content', cur is not None
          and gunzip(cur['path'] / 'art.bin.gz') == gunzip(ROOT / 'couchside' / 'art.bin.gz'))
    check('the real build makes facets from the Wikidata cache', cur is not None and cur['build']['facets']
          and cur['build']['facets']['linked'] >= 4 and cur['build']['facets']['tokens'] > 1000, cur and cur['build'])
    check('and co-interest from the clickstream cache', cur is not None
          and cur['build']['cointerest'] == {'months': ['2026-08'], 'shows': 3, 'links': 4}, cur and cur['build'])
    check('and a film index from the film cache', cur is not None and (cur['build']['films'] or {}).get('films') == 2,
          cur and cur['build'])
    service.close()
    dumps.close()
    print('\n  step timings, driven by the refresher:')
    for run_record in reversed(r.state['runs']):
        for s in run_record['steps']:
            peak = f"{s['peak_mb']:>7,.0f} MB" if s.get('peak_mb') else '       n/a'
            print(f"    {run_record['kind']:<5} {s['name']:<17} {s['seconds']:>7.1f} s  peak {peak}")
    print()

    tree = TMP / 'tree'
    for sub in ('scripts', 'output', 'data/raw', 'couchside'):
        (tree / sub).mkdir(parents=True)
    for name in ('build_model.py', 'build_popularity.py', 'build_art.py'):
        shutil.copyfile(SCRIPTS / name, tree / 'scripts' / name)
    for name in ('theme_rules.json', 'audit.json'):
        shutil.copyfile(ROOT / 'output' / name, tree / 'output' / name)
    for page in raw_dir.glob('page-*.json'):
        shutil.copyfile(page, tree / 'data' / 'raw' / page.name)
    shutil.copyfile(manifest, tree / 'data' / 'manifest.json')
    env = {k: v for k, v in os.environ.items() if not k.startswith('TV_')}
    for script in ('build_model', 'build_popularity', 'build_art'):
        ran = refresher.Processes().run(script, [sys.executable, str(tree / 'scripts' / f'{script}.py')], env,
                                        str(tree), 7200, lambda _line: None)
        check(f'{script}.py runs with its default paths', ran['returncode'] == 0, ran['tail'][-3:])
    for name in ('catalog.json.gz', 'vectors.bin.gz'):
        check(f'default paths reproduce model/{name} byte for byte',
              filecmp.cmp(tree / 'model' / name, ROOT / 'model' / name, shallow=False))
    check('default paths reproduce the popularity content',
          gunzip(tree / 'model' / 'popularity.bin.gz') == gunzip(ROOT / 'model' / 'popularity.bin.gz'))
    check('default paths reproduce the art content',
          gunzip(tree / 'couchside' / 'art.bin.gz') == gunzip(ROOT / 'couchside' / 'art.bin.gz'))
    check('default paths reproduce output/catalog-audit.json',
          filecmp.cmp(tree / 'output' / 'catalog-audit.json', ROOT / 'output' / 'catalog-audit.json', shallow=False))
    check('popularity and art carry no timestamp now', (tree / 'model' / 'popularity.bin.gz').read_bytes()[4:8] == bytes(4)
          and (tree / 'couchside' / 'art.bin.gz').read_bytes()[4:8] == bytes(4))


if os.environ.get('TV_FULL_TEST') == '1':
    raw_dir = Path(os.environ.get('TV_FULL_RAW') or ROOT / 'data' / 'raw')
    manifest = raw_dir / 'manifest.json' if (raw_dir / 'manifest.json').exists() else raw_dir.parent / 'manifest.json'
    if not any(raw_dir.glob('page-*.json')) or not manifest.exists():
        check('the full test finds TVmaze pages and a manifest', False, f'nothing usable in {raw_dir}; set TV_FULL_RAW')
    else:
        full_test(raw_dir, manifest)

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
