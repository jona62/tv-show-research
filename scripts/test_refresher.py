"""Check the model refresher and its TMDB step, with the network and the builds faked.

Run from the repository root:  .venv/bin/python scripts/test_refresher.py

Nothing here reaches TVmaze or TMDB. The build steps are stand-ins that write small but
well-formed model files, and TMDB is a pretend server. Validation and carrying TMDB
data forward really run, as child processes, the way the service runs them.

TV_FULL_TEST=1 adds an end-to-end check: the real build steps, driven by the refresher,
against the TVmaze pages in data/raw (or TV_FULL_RAW) into a temporary MODEL_ROOT, and a
rebuild with the scripts' default paths, which must reproduce the committed model.
"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
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
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import refresher                                                # noqa: E402
import tmdb                                                     # noqa: E402

NOW = datetime.now(timezone.utc).replace(microsecond=0)
KEY_V3 = '0123456789abcdef0123456789abcdef'
KEY_V4 = 'eyJhbGciOiJIUzI1NiJ9.a-read-access-token.signature'
BUILD_KEYS = ['version', 'built_at', 'snapshot_date', 'shows', 'pipeline', 'seeded_from', 'tmdb']
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


class FakeRunner:
    """Stands in for the build subprocesses; validation and the TMDB carry really run."""

    def __init__(self, shows=100, fail=None, hold=None):
        self.shows, self.fail, self.hold = shows, fail, hold
        self.calls = []
        self.real = refresher.Processes()
        self.popularity_shows = None
        self.tmdb_code, self.tmdb_error = 0, None

    def names(self):
        return [call['name'] for call in self.calls]

    def env_for(self, name):
        return next(call['env'] for call in reversed(self.calls) if call['name'] == name)

    def run(self, name, argv, env, cwd, timeout, log):
        self.calls.append({'name': name, 'argv': list(argv), 'env': dict(env)})
        if name in ('validate', 'tmdb carry'):
            return self.real.run(name, argv, env, cwd, timeout, log)
        if self.hold is not None and name == 'build_model':
            self.hold.wait(30)
        if name == self.fail:
            return result(1, [f'{name} fell over'])
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
                                                    'build_art', 'validate'], runner.names())
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
check('a version holds the four model files and build.json',
      sorted(p.name for p in (r.versions / done['version']).iterdir())
      == sorted(['build.json', *refresher.MODEL_FILES]))
build = r.current()['build']
check('build.json describes the build', list(build) == BUILD_KEYS and build['version'] == done['version']
      and build['shows'] == 100 and build['seeded_from'] is None and build['pipeline'] == r.pipeline
      and build['tmdb'] == {'fetched_at': None, 'shows': 0}, build)
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
    'pipeline', 'model_root'} <= set(status), sorted(status))
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
check('the model files are the live version\'s, shared not rebuilt',
      all(os.stat(after['path'] / n).st_ino == os.stat(before['path'] / n).st_ino for n in refresher.MODEL_FILES))
check('build.json carries the model\'s facts forward', all(after['build'][k] == before['build'][k]
      for k in ('snapshot_date', 'shows', 'pipeline', 'seeded_from')) and list(after['build']) == BUILD_KEYS)

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
    """A pretend api.themoviedb.org answering find and details from dicts. Every request
    is recorded, and scripted answers or errors are served first."""

    def __init__(self, finds=None, details=None, script=None, always=None):
        self.finds, self.details = finds or {}, details or {}
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

# 11. download.py --out --------------------------------------------------------------------------------------------

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

# 12. End to end with the real build steps (opt in) -------------------------------------------------------------------


def full_test(raw_dir, manifest):
    seed = TMP / 'full-seed'
    seed.mkdir()
    for name in ('catalog.json.gz', 'vectors.bin.gz', 'popularity.bin.gz'):
        shutil.copyfile(ROOT / 'model' / name, seed / name)
    config = refresher.Config({'MODEL_ROOT': str(TMP / 'full-root'), 'SEED_MODEL_DIR': str(seed),
                               'RAW_SOURCE_DIR': str(raw_dir), 'AUTO_DELAY_SECONDS': '0'})
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
