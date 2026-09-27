"""Keep the shared model fresh: fetch TVmaze each night, rebuild, and swap it in.

A service of its own beside the three apps, standard library only. The build steps run
one at a time as niced child processes of this same interpreter, whose virtual
environment carries numpy and scikit-learn (requirements-refresher.txt). A version is
built beside the live one and goes live only once it checks out, so a failed night
leaves the apps exactly where they were.

    .venv/bin/python refresher.py            # from scripts/

MODEL_ROOT (/home/developer/tv-model) holds everything:

    current -> versions/<stamp>   what the apps read, swapped with one rename
    versions/<stamp>/             catalog.json.gz vectors.bin.gz popularity.bin.gz
                                  art.bin.gz, tmdb.json.gz when there is TMDB data,
                                  and build.json, written last to mark it complete
    raw/                          the latest TVmaze pages and manifest.json
    tmdb/                         TMDB id mapping and cache (see tmdb.py)
    state.json                    past runs, so a restart keeps its history
    logs/                         one log per run, the last 14 kept

Settings, all optional: PORT (8083), MODEL_ROOT, SEED_MODEL_DIR (/home/developer/model),
REFRESH_AT_UTC (04:30), AUTO_DELAY_SECONDS (120), TMDB_API_KEY, TMDB_REGION (US),
TMDB_MIN_POPULARITY (60), TMDB_DAILY_LIMIT (6000), and RAW_SOURCE_DIR, which copies
TVmaze pages from a local folder instead of downloading them, for local runs.
"""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import argparse
import fcntl
import gzip
import hashlib
import html
import json
import os
import re
import resource
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import traceback
import zlib

HERE = Path(__file__).resolve().parent
STAMP = re.compile(r'\d{8}T\d{6}Z')
MODEL_FILES = ('catalog.json.gz', 'vectors.bin.gz', 'popularity.bin.gz', 'art.bin.gz')
# The sources whose change means the model must be built again. tmdb.py and this file
# only shape display data and the service, so a change to them rebuilds nothing.
PIPELINE = ('download.py', 'build_model.py', 'build_popularity.py', 'build_art.py',
            'study/theme_rules.json', 'study/audit.json', 'requirements-refresher.txt')
KEEP_VERSIONS = 3
KEEP_LOGS = 14
KEEP_RUNS = 60
STALE = timedelta(hours=26)
RETRY = timedelta(hours=2)
MAX_SHIFT = 0.10
TMDB_MAX_AGE = timedelta(days=180)
THREAD_VARS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS')
SECRETS = ('TMDB_API_KEY',)
TIMEOUTS = {'download': 3 * 3600, 'build_model': 2 * 3600, 'build_popularity': 1800, 'build_art': 1800,
            'tmdb': 3 * 3600, 'tmdb carry': 1800, 'validate': 1800}
AUTOMATIC = ('daily', 'catch-up', 'retry', 'tmdb')
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
ASSETS = {'/refresher.js': ('refresher.js', 'text/javascript; charset=utf-8'),
          '/refresher.css': ('refresher.css', 'text/css; charset=utf-8')}


class StepFailed(Exception):
    """A step did not do its job; the run stops and the live version stays."""


class Stopped(Exception):
    """The service is shutting down in the middle of a run."""


class Invalid(Exception):
    """A built version failed its checks."""


# Small helpers ---------------------------------------------------------------------

def utc_now():
    return datetime.now(timezone.utc)


def iso(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_time(value):
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def say(message):
    print(f'{iso(utc_now())} {message}', flush=True)


def parse_clock(value):
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', (value or '').strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f'REFRESH_AT_UTC must look like 04:30, not {value!r}.')
    return int(match[1]), int(match[2])


def next_daily(after, at):
    """The first daily slot strictly after a moment."""
    slot = after.astimezone(timezone.utc).replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    return slot if slot > after else slot + timedelta(days=1)


def pipeline_hash(folder=HERE):
    digest = hashlib.sha256()
    for name in PIPELINE:
        path = Path(folder) / name
        digest.update(name.encode() + b'\0' + (path.read_bytes() if path.exists() else b'(missing)') + b'\0')
    return digest.hexdigest()[:12]


def write_atomic(path, body):
    """Whole or not at all, and readable by the apps, which run as other users."""
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        with open(tmp, 'wb') as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(path, value):
    write_atomic(path, (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def remove(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def link_or_copy(src, dst):
    """Versions never change once written, so the TMDB-only step can share their files."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def swap_dir(new, target):
    """Put a finished folder in place of the old one, which is kept only until the swap
    has worked."""
    old = target.with_name(target.name + '.old')
    remove(old)
    if target.exists():
        os.rename(target, old)
    try:
        os.rename(new, target)
    except BaseException:
        if old.exists() and not target.exists():
            os.rename(old, target)
        raise
    remove(old)


def peak_mb(maxrss):
    """ru_maxrss is in kilobytes on Linux and in bytes on macOS."""
    return round(maxrss / (1 << 20 if sys.platform == 'darwin' else 1 << 10), 1)


def has_index(folder):
    return (folder / 'manifest.json').is_file() and any(folder.glob('page-*.json'))


def check_index(folder):
    """A downloaded index is complete when every page its manifest lists is on disk."""
    try:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise StepFailed(f'The download left no readable manifest: {exc}') from None
    if parse_time(manifest.get('retrieved_utc')) is None:
        raise StepFailed('The manifest has no readable retrieval date.')
    pages = sorted(p.name for p in folder.glob('page-*.json'))
    listed = sorted(manifest.get('files') or {})
    if not pages or pages != listed:
        raise StepFailed(f'The download is incomplete: {len(pages)} pages on disk, {len(listed)} in its manifest.')
    return manifest


def copy_index(source, target):
    """RAW_SOURCE_DIR: take the pages from a local folder, with the manifest.json inside
    it or beside it, as the repository keeps them."""
    source = Path(source)
    manifest = source / 'manifest.json'
    if not manifest.exists():
        manifest = source.parent / 'manifest.json'
    if not manifest.exists():
        raise StepFailed(f'No manifest.json in {source} or beside it.')
    target.mkdir(parents=True)
    for page in sorted(source.glob('page-*.json')):
        shutil.copyfile(page, target / page.name)
    if (source / 'updates.json').exists():
        shutil.copyfile(source / 'updates.json', target / 'updates.json')
    shutil.copyfile(manifest, target / 'manifest.json')


# Checking a version before it goes live ---------------------------------------------

def read_catalog(path):
    """The catalog's shape without holding 90,000 show objects: each show is read and
    reduced to its id as it is parsed."""
    def compact(pairs):
        keys = {k for k, _v in pairs}
        return next(v for k, v in pairs if k == 'id') if {'id', 'name'} <= keys else dict(pairs)
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        data = json.load(f, object_pairs_hook=compact)
    if not isinstance(data, dict) or not isinstance(data.get('shows'), list):
        raise Invalid('catalog.json.gz holds no show list.')
    return data


def vectors_shape(path):
    with gzip.open(path, 'rb') as f:
        head = f.read(12)
        if len(head) < 12:
            raise Invalid('vectors.bin.gz is truncated.')
        rows, cols, nnz = struct.unpack('<III', head)
        size = 12
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
    expected = 12 + 4 * ((rows + 1) + 2 * nnz + (cols + 1) + 2 * nnz)
    if size != expected:
        raise Invalid(f'vectors.bin.gz holds {size:,} bytes where its header promises {expected:,}.')
    return rows, cols, nnz


def validate_version(folder, previous_shows=None, manifest=None):
    """Everything a version must pass before `current` points at it. Returns a summary,
    or raises Invalid with the reason."""
    folder = Path(folder)
    for name in MODEL_FILES:
        if not (folder / name).is_file():
            raise Invalid(f'{name} is missing.')
    try:
        catalog = read_catalog(folder / 'catalog.json.gz')
        rows, cols, nnz = vectors_shape(folder / 'vectors.bin.gz')
        popularity = gzip.decompress((folder / 'popularity.bin.gz').read_bytes())
        art = gzip.decompress((folder / 'art.bin.gz').read_bytes())
    except Invalid:
        raise
    except (OSError, EOFError, ValueError, zlib.error, struct.error) as exc:
        raise Invalid(f'A model file does not decompress: {exc}') from None
    ids = catalog['shows']
    shows = len(ids)
    if not shows or any(type(i) is not int for i in ids) or len(set(ids)) != shows:
        raise Invalid('The catalog is empty or its show ids are not unique whole numbers.')
    art_count = struct.unpack('<I', art[4:8])[0] if art[:4] == b'ART1' and len(art) >= 8 else None
    if art_count is None or len(art) != 8 + 6 * art_count:
        raise Invalid('art.bin.gz is not an ART1 track.')
    counts = {'catalog': shows, 'vectors': rows, 'popularity': len(popularity), 'art': art_count}
    if len(set(counts.values())) != 1:
        raise Invalid('Show counts disagree: ' + ', '.join(f'{k} {v:,}' for k, v in counts.items()) + '.')
    if cols != catalog.get('text_features'):
        raise Invalid(f"vectors.bin.gz has {cols:,} text features where the catalog says {catalog.get('text_features')}.")
    date = catalog.get('date')
    if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise Invalid('The catalog carries no snapshot date.')
    if previous_shows:
        shift = abs(shows - previous_shows) / previous_shows
        if shift > MAX_SHIFT:
            raise Invalid(f'{shows:,} shows against {previous_shows:,} in the live version, a {shift:.1%} change; '
                          'more than 10% looks like a broken download, so the live version stays.')
    if manifest is not None:
        retrieved = (read_json(manifest, {}) or {}).get('retrieved_utc')
        if parse_time(retrieved) is None:
            raise Invalid(f'The manifest date in {manifest} does not parse.')
        if retrieved[:10] != date:
            raise Invalid(f'The catalog date {date} does not match the manifest date {retrieved[:10]}.')
    tmdb = {'fetched_at': None, 'shows': 0}
    if (folder / 'tmdb.json.gz').exists():
        try:
            data = json.loads(gzip.decompress((folder / 'tmdb.json.gz').read_bytes()))
        except (OSError, EOFError, ValueError, zlib.error) as exc:
            raise Invalid(f'tmdb.json.gz does not decompress: {exc}') from None
        entries = data.get('shows') if isinstance(data, dict) else None
        known = set(ids)
        if not isinstance(entries, dict) or not all(k.isdigit() and int(k) in known for k in entries):
            raise Invalid('tmdb.json.gz names shows that are not in this catalog.')
        if entries and parse_time(data.get('fetched_at')) is None:
            raise Invalid('tmdb.json.gz carries no fetch date.')
        tmdb = {'fetched_at': data.get('fetched_at') if entries else None, 'shows': len(entries)}
    return {'shows': shows, 'snapshot_date': date, 'catalog_version': catalog.get('version'),
            'text_features': cols, 'nonzeros': nnz, 'tmdb': tmdb}


# Running the steps --------------------------------------------------------------------

def lower_priority():
    os.nice(10)


class Processes:
    """Runs one build step at a time as a niced child in its own process group, and
    reports its wall time and peak memory (the rusage the kernel keeps per child)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.child = None

    def run(self, name, argv, env, cwd, timeout, log):
        started = time.monotonic()
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, preexec_fn=lower_priority, start_new_session=True)
        with self.lock:
            self.child = proc
        tail = deque(maxlen=40)

        def pump():
            for raw in proc.stdout:
                line = raw.decode('utf-8', 'replace').rstrip()
                tail.append(line)
                log(f'  {name} | {line}')
        reader = threading.Thread(target=pump, name=f'{name}-output', daemon=True)
        reader.start()
        expired = threading.Event()

        def expire():
            expired.set()
            self._kill(proc)
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            _pid, status, usage = os.wait4(proc.pid, 0)
        finally:
            timer.cancel()
        with self.lock:
            proc.returncode = os.waitstatus_to_exitcode(status)
            self.child = None
        reader.join(10)
        proc.stdout.close()
        return {'returncode': proc.returncode, 'seconds': round(time.monotonic() - started, 2),
                'peak_mb': peak_mb(usage.ru_maxrss), 'tail': list(tail), 'timed_out': expired.is_set()}

    def _kill(self, proc):
        with self.lock:
            if proc.returncode is not None:
                return
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                return

        def hard():
            with self.lock:
                if proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
        later = threading.Timer(10, hard)
        later.daemon = True
        later.start()

    def stop(self):
        with self.lock:
            child = self.child
        if child is not None:
            self._kill(child)


class RunLog:
    """Timestamped lines to stdout and the run's own log file, with the TMDB key scrubbed."""

    def __init__(self, path, secret='', echo=True):
        self.file = open(path, 'a', encoding='utf-8')
        self.secret, self.echo = secret, echo
        self.lock = threading.Lock()

    def __call__(self, message):
        text = str(message)
        if self.secret:
            text = text.replace(self.secret, '[key]')
        line = f'{iso(utc_now())} {text}'
        with self.lock:
            if self.echo:
                print(line, flush=True)
            if not self.file.closed:
                self.file.write(line + '\n')
                self.file.flush()

    def close(self):
        with self.lock:
            self.file.close()


class Context:
    """One run: its record, its log, its step timings and its temporary version."""

    def __init__(self, refresher, run, log):
        self.refresher, self.run, self.log = refresher, run, log
        self.stamp = run['id']
        self.tmp = None

    def check(self):
        if self.refresher.stopping.is_set():
            raise Stopped('The refresher is stopping.')

    @contextmanager
    def step(self, name):
        self.check()
        with self.refresher.guard:
            self.run['step'] = name
            self.run['step_started_at'] = iso(self.refresher.clock())
        record = {'name': name, 'seconds': None, 'outcome': 'running', 'peak_mb': None}
        self.run['steps'].append(record)
        self.log(f'{name}: starting')
        started = time.monotonic()
        try:
            yield record
        except BaseException:
            record['outcome'] = 'failed'
            raise
        else:
            record['outcome'] = 'ok'
        finally:
            record['seconds'] = round(time.monotonic() - started, 2)
            peak = f", peak {record['peak_mb']:,.0f} MB" if record.get('peak_mb') else ''
            self.log(f"{name}: {record['outcome']} in {record['seconds']:.1f}s{peak}")

    def run_step(self, name, argv, env, ok=(0,)):
        with self.step(name) as record:
            result = self.refresher.runner.run(name, [str(a) for a in argv], env, str(self.refresher.config.scripts),
                                               TIMEOUTS.get(name, 3600), self.log)
            record['peak_mb'] = result.get('peak_mb')
            self.check()
            if result.get('timed_out'):
                raise StepFailed(f'{name} timed out after {TIMEOUTS.get(name, 3600)}s.')
            if result['returncode'] not in ok:
                last = next((line for line in reversed(result.get('tail') or []) if line.strip()), '')
                raise StepFailed(f"{name} failed with exit code {result['returncode']}" + (f': {last.strip()}' if last else '.'))
            return result

    def validate(self, folder, previous_shows=None, manifest=None):
        argv = [self.refresher.config.python, self.refresher.config.scripts / 'refresher.py', '--validate', folder]
        if previous_shows:
            argv += ['--previous-shows', previous_shows]
        if manifest:
            argv += ['--manifest', manifest]
        try:
            result = self.run_step('validate', argv, self.refresher.child_env(), ok=(0,))
        except StepFailed as exc:
            raise StepFailed(str(exc).replace('validate failed with exit code 1: INVALID ', 'Validation failed: ')) from None
        line = next((line for line in reversed(result['tail']) if line.startswith('VALID ')), None)
        if line is None:
            raise StepFailed('Validation said nothing.')
        return json.loads(line[len('VALID '):])

    def warn(self, message):
        self.run.setdefault('warnings', []).append(message)
        self.log(f'warning: {message}')

    def new_version(self):
        self.tmp = self.refresher.versions / f'{self.stamp}.tmp'
        self.tmp.mkdir()
        return self.tmp


# The service ---------------------------------------------------------------------------

class Config:
    def __init__(self, env=os.environ):
        # Absolute from the start: the build steps run from scripts/, not from here.
        where = lambda value: Path(os.path.abspath(os.path.expanduser(value)))
        self.port = int(env.get('PORT') or 8083)
        self.root = where(env.get('MODEL_ROOT') or '/home/developer/tv-model')
        self.seed = where(env.get('SEED_MODEL_DIR') or '/home/developer/model')
        self.refresh_at = parse_clock(env.get('REFRESH_AT_UTC') or '04:30')
        self.auto_delay = float(env.get('AUTO_DELAY_SECONDS') or 120)
        self.tmdb_key = (env.get('TMDB_API_KEY') or '').strip()
        self.tmdb_region = (env.get('TMDB_REGION') or 'US').strip().upper()
        self.tmdb_min_popularity = int(env.get('TMDB_MIN_POPULARITY') or 60)
        self.tmdb_daily_limit = int(env.get('TMDB_DAILY_LIMIT') or 6000)
        self.raw_source = where(env['RAW_SOURCE_DIR']) if env.get('RAW_SOURCE_DIR') else None
        self.scripts = HERE
        self.python = sys.executable
        if not re.fullmatch(r'[A-Z]{2}', self.tmdb_region):
            raise ValueError('TMDB_REGION must be a two-letter country code such as US.')


class Refresher:
    def __init__(self, config, runner=None, clock=utc_now, quiet=False):
        self.config = config
        self.quiet = quiet
        self.say = (lambda _message: None) if quiet else say
        self.root = Path(config.root)
        self.versions = self.root / 'versions'
        self.raw = self.root / 'raw'
        self.logs = self.root / 'logs'
        self.runner = runner or Processes()
        self.clock = clock
        self.pipeline = pipeline_hash(config.scripts)
        self.lock = threading.Lock()       # one run at a time in this process
        self.guard = threading.RLock()     # the state and the run in progress
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.state = {'runs': [], 'last_success': None, 'tmdb': None}
        self.running = None
        self.thread = None
        self.scheduler = None
        self.started_at = clock()
        self.next_daily_at = next_daily(self.started_at, config.refresh_at)
        self.catch_up_at = None
        self.retry_at = None
        self.tmdb_at = None
        self.lock_file = None

    # State -------------------------------------------------------------------------

    def load_state(self):
        state = read_json(self.root / 'state.json')
        if not isinstance(state, dict) or not isinstance(state.get('runs'), list):
            if (self.root / 'state.json').exists():
                self.say('state.json did not parse; starting a fresh history.')
            state = {}
        return {'runs': state.get('runs', []), 'last_success': state.get('last_success'), 'tmdb': state.get('tmdb')}

    def save_state(self):
        with self.guard:
            self.state['runs'] = self.state['runs'][:KEEP_RUNS]
            body = json.dumps(self.state, indent=2, ensure_ascii=False) + '\n'
        write_atomic(self.root / 'state.json', body.encode())

    # Versions ----------------------------------------------------------------------

    def current(self):
        """The live version and its build.json, or None."""
        try:
            target = os.readlink(self.root / 'current')
        except OSError:
            return None
        folder = self.root / target
        build = read_json(folder / 'build.json')
        if not isinstance(build, dict):
            return None
        return {'version': folder.name, 'path': folder, 'build': build}

    def complete_versions(self):
        if not self.versions.is_dir():
            return []
        return sorted((p.name for p in self.versions.iterdir()
                       if STAMP.fullmatch(p.name) and p.is_dir() and (p / 'build.json').is_file()), reverse=True)

    def swap_current(self, stamp):
        """Point `current` at a version with a single rename, so a reader sees the old
        version or the new one and never neither."""
        tmp = self.root / 'current.tmp'
        remove(tmp)
        os.symlink(f'versions/{stamp}', tmp)
        os.replace(tmp, self.root / 'current')

    def prune(self, log=None):
        """Keep the newest three complete versions and, whatever its age, the live one."""
        log = log or self.say
        live = (self.current() or {}).get('version')
        complete = self.complete_versions()
        keep = set(complete[:KEEP_VERSIONS]) | {live}
        for entry in sorted(self.versions.iterdir()) if self.versions.is_dir() else []:
            if STAMP.fullmatch(entry.name) and entry.name not in keep and entry.is_dir():
                remove(entry)
                log(f'pruned versions/{entry.name}')

    def prune_logs(self):
        logs = sorted(self.logs.glob('*.log'), reverse=True) if self.logs.is_dir() else []
        for old in logs[KEEP_LOGS:]:
            old.unlink(missing_ok=True)

    def tidy(self):
        """Clear what an interrupted run left behind. Only called while holding the lock."""
        for leftover in list(self.versions.glob('*.tmp')) if self.versions.is_dir() else []:
            remove(leftover)
        remove(self.root / 'raw.new')
        old = self.root / 'raw.old'
        if old.exists():
            if self.raw.exists():
                remove(old)
            else:
                os.rename(old, self.raw)
        remove(self.root / 'current.tmp')

    def last_built(self):
        success = self.state.get('last_success') or {}
        moment = parse_time(success.get('at'))
        if moment is None:
            cur = self.current()
            if cur and cur['build'].get('seeded_from') is None:
                moment = parse_time(cur['build'].get('built_at'))
        return moment

    def needs_catch_up(self):
        """Why a run is due now rather than at the next daily slot, or None."""
        cur = self.current()
        if cur is None:
            return 'there is no live version'
        if cur['build'].get('pipeline') != self.pipeline:
            return 'the pipeline changed since the live version was built'
        if self.latest_full_outcome() == 'interrupted':
            # A deploy in the middle of the nightly build would otherwise wait a day.
            return 'the last build was interrupted'
        built = self.last_built()
        if built is None:
            return 'the live version was seeded, not built here'
        if self.clock() - built > STALE:
            return 'the last build is more than 26 hours old'
        return None

    def needs_tmdb(self):
        """Why the live version should get TMDB data before the next build, or None. It
        is due when TMDB was switched on, say by adding the key, after that version was
        built, so the data need not wait for the nightly run."""
        if not self.config.tmdb_key:
            return None
        cur = self.current()
        if cur is None or ((cur['build'].get('tmdb') or {}).get('shows') or 0):
            return None
        return 'TMDB is on but the live version has no TMDB data'

    def refreshed_since(self, moment):
        started = parse_time((self.state.get('last_success') or {}).get('started_at'))
        return started is not None and started >= moment

    def latest_full_outcome(self):
        with self.guard:
            return next((r.get('outcome') for r in self.state['runs']
                         if r.get('kind') == 'full' and r.get('outcome') != 'running'), None)

    def next_run(self):
        options = [(self.next_daily_at, 'daily')]
        if self.catch_up_at:
            options.append((self.catch_up_at, 'catch-up'))
        if self.retry_at:
            options.append((self.retry_at, 'retry'))
        if self.tmdb_at:
            options.append((self.tmdb_at, 'tmdb'))
        return min(options, key=lambda option: option[0])

    # Running -----------------------------------------------------------------------

    def start(self, schedule=True):
        os.umask(0o022)
        for folder in (self.root, self.versions, self.logs, self.root / 'tmdb'):
            folder.mkdir(parents=True, exist_ok=True)
        self.state = self.load_state()
        for run in self.state['runs']:
            if run.get('outcome') == 'running':
                run.update(outcome='interrupted', step=None, error='The refresher stopped before this run finished.')
        if self.take_file_lock():
            try:
                self.tidy()
            finally:
                self.release_file_lock()
        self.save_state()
        self.started_at = self.clock()
        self.next_daily_at = next_daily(self.started_at, self.config.refresh_at)
        if schedule:
            self.scheduler = threading.Thread(target=self.schedule, name='scheduler', daemon=True)
            self.scheduler.start()

    def take_file_lock(self):
        """A second refresher on the same MODEL_ROOT, say during a deploy, waits its turn."""
        handle = open(self.root / '.lock', 'a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.lock_file = handle
        return True

    def release_file_lock(self):
        if self.lock_file is not None:
            fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None

    def busy(self):
        with self.guard:
            return self.running is not None

    def new_stamp(self):
        moment = self.clock().replace(microsecond=0)
        taken = {r.get('id') for r in self.state['runs']}
        while True:
            stamp = moment.strftime('%Y%m%dT%H%M%SZ')
            if stamp not in taken and not any(p.exists() for p in (
                    self.versions / stamp, self.versions / f'{stamp}.tmp', self.logs / f'{stamp}.log')):
                return stamp
            moment += timedelta(seconds=1)

    def start_run(self, kind='full', trigger='manual'):
        """Start a run in the background. Returns its record, or None when one is going."""
        if self.stopping.is_set() or not self.lock.acquire(blocking=False):
            return None
        try:
            if not self.take_file_lock():
                self.lock.release()
                return None
            stamp = self.new_stamp()
            run = {'id': stamp, 'kind': kind, 'trigger': trigger, 'started_at': iso(self.clock()),
                   'finished_at': None, 'seconds': None, 'outcome': 'running', 'error': None, 'warnings': [],
                   'version': None, 'step': None, 'step_started_at': None, 'steps': [], 'log': f'logs/{stamp}.log'}
            with self.guard:
                self.running = run
                self.state['runs'].insert(0, run)
            self.save_state()
            self.thread = threading.Thread(target=self.execute, args=(run,), name=f'{kind}-run', daemon=True)
            self.thread.start()
            return summary(run)
        except BaseException:
            with self.guard:
                self.running = None
            self.release_file_lock()
            self.lock.release()
            raise

    def execute(self, run):
        log = RunLog(self.logs / f"{run['id']}.log", self.config.tmdb_key, echo=not self.quiet)
        ctx = Context(self, run, log)
        started = time.monotonic()
        outcome, error = 'failed', None
        try:
            log(f"{run['kind']} run {run['id']} started ({run['trigger']}); pipeline {self.pipeline}")
            self.tidy()
            {'full': self.full_run, 'tmdb': self.tmdb_run, 'seed': self.seed_run}[run['kind']](ctx)
            outcome = 'success'
        except Stopped:
            outcome, error = 'interrupted', 'The refresher was stopped during this run.'
        except Exception as exc:
            outcome, error = 'failed', str(exc) or type(exc).__name__
            if not isinstance(exc, (StepFailed, Invalid)):
                log(traceback.format_exc().rstrip())
        finally:
            if ctx.tmp is not None:
                remove(ctx.tmp)
            remove(self.root / 'raw.new')
        children = peak_mb(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
        finished = self.clock()
        with self.guard:
            run.update(outcome=outcome, error=error, finished_at=iso(finished), step=None, step_started_at=None,
                       seconds=round(time.monotonic() - started, 1))
            if outcome == 'success' and run['kind'] == 'full':
                self.state['last_success'] = {'at': iso(finished), 'started_at': run['started_at'], 'version': run['version']}
            if outcome == 'failed' and run['trigger'] in ('daily', 'catch-up'):
                self.retry_at = finished + RETRY
            self.running = None
        if error:
            log(f'error: {error}')
        log(f"{run['kind']} run {run['id']}: {outcome} in {run['seconds']:.0f}s; "
            f'largest child so far {children:,.0f} MB')
        log.close()
        try:
            self.save_state()
            self.prune_logs()
        finally:
            self.release_file_lock()
            self.lock.release()
            self.wake.set()

    def child_env(self, tmdb=False):
        env = {k: v for k, v in os.environ.items() if k not in SECRETS}
        env.update({name: '1' for name in THREAD_VARS})
        env.update(PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        if tmdb:
            env.update(TMDB_API_KEY=self.config.tmdb_key, TMDB_REGION=self.config.tmdb_region,
                       TMDB_MIN_POPULARITY=str(self.config.tmdb_min_popularity),
                       TMDB_DAILY_LIMIT=str(self.config.tmdb_daily_limit))
        return env

    def build_env(self, folder, audit):
        env = self.child_env()
        env.update(TV_RAW_DIR=str(self.raw), TV_MANIFEST=str(self.raw / 'manifest.json'),
                   TV_STUDY_DIR=str(self.config.scripts / 'study'), TV_MODEL_OUT=str(folder),
                   TV_ART_OUT=str(folder / 'art.bin.gz'), TV_AUDIT_DIR=str(audit))
        return env

    def script(self, name):
        return [self.config.python, self.config.scripts / name]

    def fetch_index(self, ctx):
        """A complete fresh TVmaze index into raw.new, then swapped in for raw/."""
        new = self.root / 'raw.new'
        remove(new)
        if self.config.raw_source:
            with ctx.step('download'):
                copy_index(self.config.raw_source, new)
                ctx.log(f'copied the index from {self.config.raw_source} (RAW_SOURCE_DIR) instead of downloading')
        else:
            ctx.run_step('download', self.script('download.py') + ['--out', new], self.child_env())
        manifest = check_index(new)
        swap_dir(new, self.raw)
        ctx.log(f"index: {manifest.get('records', 0):,} shows on {manifest.get('pages')} pages, "
                f"retrieved {manifest.get('retrieved_utc')}")
        return manifest

    def tmdb_step(self, ctx, folder, previous, required):
        """TMDB data for a version: fetched when a key is set, otherwise carried forward
        from the live version while it is under 180 days old. On a full run a TMDB problem
        is only a warning; the model matters more than where to watch it."""
        if self.config.tmdb_key:
            result = None
            try:
                done = ctx.run_step('tmdb', self.script('tmdb.py') + ['--root', self.root, '--version', folder,
                                                                      '--raw', self.raw],
                                    self.child_env(tmdb=True), ok=(0, 3, 4))
                line = next((l for l in reversed(done['tail']) if l.startswith('RESULT ')), None)
                result = json.loads(line[len('RESULT '):]) if line else None
            except StepFailed as exc:
                if required:
                    raise
                ctx.warn(f'TMDB step failed: {exc}')
            with self.guard:
                self.state['tmdb'] = {'at': iso(self.clock()), **(result or {'error': 'the TMDB step failed'})}
            if result is not None:
                if result.get('error'):
                    if required:
                        raise StepFailed(result['error'])
                    ctx.warn(result['error'])
                return
            if required:
                raise StepFailed('The TMDB step gave no result.')
        old = previous['path'] / 'tmdb.json.gz' if previous else None
        if old is not None and old.exists():
            ctx.run_step('tmdb carry', self.script('tmdb.py') + ['--version', folder, '--carry', old], self.child_env())

    def finish(self, ctx, folder, build):
        """build.json last, then the rename, then the swap."""
        ctx.check()
        write_json(folder / 'build.json', build)
        final = self.versions / ctx.stamp
        os.rename(folder, final)
        ctx.tmp = final
        self.swap_current(ctx.stamp)
        ctx.tmp = None
        with self.guard:
            ctx.run['version'] = ctx.stamp
        ctx.log(f'current -> versions/{ctx.stamp} ({build["shows"]:,} shows, snapshot {build["snapshot_date"]})')
        try:
            self.prune(ctx.log)
        except OSError as exc:
            ctx.warn(f'Could not prune old versions: {exc}')

    def full_run(self, ctx):
        previous = self.current()
        self.fetch_index(ctx)
        folder = ctx.new_version()
        audit = folder / 'audit'
        audit.mkdir()
        env = self.build_env(folder, audit)
        for step in ('build_model', 'build_popularity', 'build_art'):
            ctx.run_step(step, self.script(f'{step}.py'), env)
        report = read_json(audit / 'catalog-audit.json', {}) or {}
        if report:
            ctx.log(f"catalog: {report.get('searchable_shows', 0):,} shows, "
                    f"{report.get('recommendable_shows', 0):,} recommendable")
        remove(audit)
        self.tmdb_step(ctx, folder, previous, required=False)
        checked = ctx.validate(folder, previous and previous['build'].get('shows'), self.raw / 'manifest.json')
        self.finish(ctx, folder, {
            'version': ctx.stamp, 'built_at': iso(self.clock()), 'snapshot_date': checked['snapshot_date'],
            'shows': checked['shows'], 'pipeline': self.pipeline, 'seeded_from': None, 'tmdb': checked['tmdb']})

    def tmdb_run(self, ctx):
        """Only the TMDB step, on a copy of the live version."""
        if not self.config.tmdb_key:
            raise StepFailed('TMDB is not configured: set TMDB_API_KEY.')
        live = self.current()
        if live is None:
            raise StepFailed('There is no live version to add TMDB data to yet.')
        if not has_index(self.raw):
            raise StepFailed('There are no TVmaze pages yet; run a full refresh first.')
        folder = ctx.new_version()
        with ctx.step('copy'):
            for name in MODEL_FILES:
                link_or_copy(live['path'] / name, folder / name)
        self.tmdb_step(ctx, folder, live, required=True)
        checked = ctx.validate(folder, live['build'].get('shows'))
        old = live['build']
        self.finish(ctx, folder, {
            'version': ctx.stamp, 'built_at': iso(self.clock()), 'snapshot_date': old.get('snapshot_date'),
            'shows': checked['shows'], 'pipeline': old.get('pipeline'), 'seeded_from': old.get('seeded_from'),
            'tmdb': checked['tmdb']})

    def seed_run(self, ctx):
        """The first version, copied from the model the apps were deployed with. Art comes
        from the raw pages when the seed has none."""
        seed = Path(self.config.seed)
        missing = [name for name in MODEL_FILES[:3] if not (seed / name).is_file()]
        if missing:
            raise StepFailed(f"Nothing to seed from: {seed} lacks {', '.join(missing)}.")
        folder = ctx.new_version()
        with ctx.step('copy seed'):
            for name in MODEL_FILES + ('tmdb.json.gz',):
                if (seed / name).is_file():
                    shutil.copyfile(seed / name, folder / name)
        if not (folder / 'art.bin.gz').exists():
            if not has_index(self.raw):
                self.fetch_index(ctx)
            ctx.run_step('build_art', self.script('build_art.py'), self.build_env(folder, folder / 'audit'))
        checked = ctx.validate(folder)
        self.finish(ctx, folder, {
            'version': ctx.stamp, 'built_at': iso(self.clock()), 'snapshot_date': checked['snapshot_date'],
            'shows': checked['shows'], 'pipeline': self.pipeline, 'seeded_from': str(seed), 'tmdb': checked['tmdb']})

    # Scheduling ----------------------------------------------------------------------

    def boot(self):
        """At start: make sure there is a live version, then decide whether to catch up."""
        if self.current() is None:
            complete = self.complete_versions()
            if complete:
                self.swap_current(complete[0])
                self.say(f'current was missing; pointed it at versions/{complete[0]}')
            elif (Path(self.config.seed) / 'catalog.json.gz').is_file():
                if self.start_run('seed', 'startup') is not None and self.thread is not None:
                    self.thread.join()
            else:
                self.say(f'No live version and nothing to seed from in {self.config.seed}; the first build will make one.')
        reason = self.needs_catch_up()
        if reason:
            self.catch_up_at = self.started_at + timedelta(seconds=self.config.auto_delay)
            self.say(f'Catching up at {iso(self.catch_up_at)}: {reason}.')
            return
        # A full build fetches TMDB anyway; without one due, fetch it on its own.
        wanted = self.needs_tmdb()
        if wanted:
            self.tmdb_at = self.started_at + timedelta(seconds=self.config.auto_delay)
            self.say(f'Fetching TMDB data at {iso(self.tmdb_at)}: {wanted}.')

    def schedule(self):
        try:
            self.boot()
        except Exception:
            self.say('Start-up check failed:\n' + traceback.format_exc().rstrip())
        while not self.stopping.is_set():
            due, reason = self.next_run()
            wait = (due - self.clock()).total_seconds()
            if wait > 0:
                self.wake.wait(min(wait, 60))
                self.wake.clear()
                continue
            if self.busy():
                # Let the run in progress finish, then look again.
                self.wake.wait(30)
                self.wake.clear()
                continue
            if reason == 'daily':
                self.next_daily_at = next_daily(max(due, self.clock()), self.config.refresh_at)
                if self.refreshed_since(due - timedelta(hours=1)):
                    self.say('Skipped the daily run: a build finished within the hour before it.')
                    continue
            elif reason == 'catch-up':
                self.catch_up_at = None
                if not self.needs_catch_up():
                    continue
            elif reason == 'tmdb':
                self.tmdb_at = None
                if not self.needs_tmdb():
                    continue
            else:
                self.retry_at = None
                if self.latest_full_outcome() == 'success':
                    continue
            if self.start_run('tmdb' if reason == 'tmdb' else 'full', reason) is None:
                self.say(f'Skipped the {reason} run: another refresher holds the lock.')

    def stop(self, timeout=30):
        self.stopping.set()
        self.wake.set()
        self.runner.stop()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout)

    # Status --------------------------------------------------------------------------

    def status(self):
        now = self.clock()
        with self.guard:
            running = summary(self.running) if self.running else None
            if running and self.running.get('step_started_at'):
                started = parse_time(self.running['step_started_at'])
                running['step_seconds'] = round((now - started).total_seconds()) if started else None
            runs = [summary(run) for run in self.state['runs'][:15]]
            last_success = self.state.get('last_success')
            tmdb_last = self.state.get('tmdb')
        live = self.current()
        due, reason = self.next_run()
        return {
            'status': 'running' if running else 'idle',
            'now': iso(now),
            'current': {'version': live['version'], 'build': live['build']} if live else None,
            'versions': self.complete_versions(),
            'running': running,
            'next_run': {'at': iso(due), 'reason': reason},
            'schedule': {'daily_at_utc': '%02d:%02d' % self.config.refresh_at,
                         'auto_delay_seconds': self.config.auto_delay},
            'last_success': last_success,
            'runs': runs,
            'tmdb': {'configured': bool(self.config.tmdb_key), 'region': self.config.tmdb_region,
                     'min_popularity': self.config.tmdb_min_popularity,
                     'daily_limit': self.config.tmdb_daily_limit, 'last': tmdb_last},
            'pipeline': self.pipeline,
            'model_root': str(self.root),
        }


def summary(run):
    """A copy of a run record that is safe to serialise while the run goes on."""
    if not run:
        return None
    keys = ('id', 'kind', 'trigger', 'started_at', 'finished_at', 'seconds', 'outcome', 'error', 'warnings',
            'version', 'step', 'step_started_at', 'log')
    return {**{k: (list(run[k]) if isinstance(run.get(k), list) else run.get(k)) for k in keys},
            'steps': [dict(step) for step in list(run.get('steps') or [])]}


# The status page -------------------------------------------------------------------------

def when(value):
    moment = parse_time(value)
    return moment.strftime('%Y-%m-%d %H:%M UTC') if moment else 'never'


def took(seconds):
    if seconds is None:
        return ''
    seconds = int(round(seconds))
    if seconds < 90:
        return f'{seconds} s'
    if seconds < 5400:
        return f'{seconds // 60} min {seconds % 60} s'
    return f'{seconds // 3600} h {seconds % 3600 // 60:02d} min'


def render_page(status):
    e = lambda value: html.escape(str(value), quote=True)
    live, running, tmdb = status['current'], status['running'], status['tmdb']
    build = live['build'] if live else {}
    if running:
        state = f"Running a {e(running['kind'])} run: {e(running['step'] or 'starting')}"
        if running.get('step_seconds') is not None:
            state += f", {e(took(running['step_seconds']))} in"
    else:
        state = 'Idle'
    rows = []
    for run in status['runs']:
        steps = ', '.join(f"{s['name']} {took(s.get('seconds'))}" + (f" ({s['peak_mb']:,.0f} MB)" if s.get('peak_mb') else '')
                          for s in run.get('steps') or [])
        notes = run.get('error') or '; '.join(run.get('warnings') or []) or ''
        rows.append(
            f"<tr><td>{e(when(run['started_at']))}</td><td>{e(run['kind'])}<span class='dim'> {e(run['trigger'])}</span></td>"
            f"<td><span class='pill {e(run['outcome'])}'>{e(run['outcome'])}</span></td>"
            f"<td>{e(took(run.get('seconds')))}</td><td>{e(run.get('version') or '')}</td>"
            f"<td class='wide'>{e(notes)}<div class='dim'>{e(steps)}</div></td></tr>")
    table = ('<div class="scroll"><table><thead><tr><th>Started</th><th>Run</th><th>Outcome</th><th>Took</th>'
             '<th>Version</th><th>Notes and steps</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
             ) if rows else '<p class="dim">No runs yet.</p>'
    facts = ''.join(f'<dt>{e(k)}</dt><dd>{e(v if v is not None else "none")}</dd>' for k, v in (
        ('version', build.get('version')), ('built at', when(build.get('built_at')) if build else None),
        ('snapshot date', build.get('snapshot_date')), ('shows', f"{build['shows']:,}" if build.get('shows') else None),
        ('pipeline', build.get('pipeline')), ('seeded from', build.get('seeded_from')),
        ('TMDB data', f"{build['tmdb']['shows']:,} shows, fetched {when(build['tmdb']['fetched_at'])}"
         if (build.get('tmdb') or {}).get('shows') else None))) if live else ''
    last = tmdb.get('last') or {}
    tmdb_line = (f"On, region {e(tmdb['region'])}, up to {tmdb['daily_limit']:,} shows a night"
                 if tmdb['configured'] else 'Off: set TMDB_API_KEY to add where to watch, ratings and trailers')
    tmdb_note = (f"Last run {e(when(last.get('at')))}: " + e(last['error'] if last.get('error') else
                 f"{last.get('fetched', 0):,} fetched, {last.get('shows', 0):,} shows kept")) if last else ''
    buttons = '<button class="btn primary" type="button" data-run=""{d}>Rebuild now</button>'
    if tmdb['configured']:
        buttons += '<button class="btn ghost" type="button" data-run="tmdb"{d}>Refresh TMDB only</button>'
    buttons = buttons.replace('{d}', ' disabled' if running else '')
    daily = f"{status['schedule']['daily_at_utc']} UTC"
    why = {'daily': f'The daily run, at {daily}', 'catch-up': f'A catch-up run; the daily one is at {daily}',
           'retry': f'A retry of a failed run; the daily one is at {daily}',
           'tmdb': f'Fetching TMDB data now that it is on; the daily run is at {daily}'}.get(status['next_run']['reason'], daily)
    kept = len(status['versions'])
    kept = f"{kept} version{'' if kept == 1 else 's'} kept in {status['model_root']}"
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Model refresher</title>
<link rel="stylesheet" href="/refresher.css">
<script src="/refresher.js" defer></script>
</head>
<body data-running="{1 if running else 0}">
<header class="top"><span class="brand">Refresher</span><span class="dim">keeps the TV model fresh</span></header>
<main>
<section class="hero">
<p class="state{' on' if running else ''}" id="state" role="status">{state}</p>
<h1>{e(live['version']) if live else 'No live version yet'}</h1>
<p class="lede">{e(f"{build.get('shows') or 0:,} shows, snapshot {build.get('snapshot_date')}, built {when(build.get('built_at'))}") if live else 'The first build will make one.'}</p>
<div class="acts">{buttons}<span class="msg" id="msg" role="alert"></span></div>
</section>
<section class="cards">
<div class="card"><h2>Next run</h2><p>{e(when(status['next_run']['at']))}</p><p class="dim">{e(why)}</p></div>
<div class="card"><h2>TMDB</h2><p>{tmdb_line}</p><p class="dim">{tmdb_note}</p></div>
<div class="card"><h2>Pipeline</h2><p><code>{e(status['pipeline'])}</code></p><p class="dim">{e(kept)}</p></div>
</section>
<section><h2>Live build</h2>{f'<dl>{facts}</dl>' if live else '<p class="dim">Nothing is live yet.</p>'}</section>
<section><h2>Recent runs</h2>{table}</section>
</main>
<footer class="dim">Show data from TVmaze, CC BY-SA 4.0.{' This product uses the TMDB API but is not endorsed or certified by TMDB.' if tmdb['configured'] else ''}</footer>
</body>
</html>
'''


def make_handler(refresher):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'refresher'

        def end_headers(self):
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def send(self, status, kind, body, head=False):
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def send_json(self, value, status=200, head=False):
            self.send(status, 'application/json; charset=utf-8',
                      json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(), head)

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            path = urlsplit(self.path).path
            if path == '/healthz':
                self.send_json({'status': 'ok'}, head=head)
            elif path == '/api/status':
                self.send_json(refresher.status(), head=head)
            elif path in ('/', '/index.html'):
                self.send(200, 'text/html; charset=utf-8', render_page(refresher.status()).encode(), head)
            elif path in ASSETS:
                name, kind = ASSETS[path]
                self.send(200, kind, (HERE / name).read_bytes(), head)
            elif path.startswith('/api/'):
                self.send_json({'error': 'Not found.'}, 404, head)
            else:
                self.send(404, 'text/plain; charset=utf-8', b'Not found.\n', head)

        def cross_site(self):
            """Why a POST is refused, or None. The custom header cannot be sent cross-site
            without a CORS preflight, which this server never grants; a mismatched Origin
            or Sec-Fetch-Site is refused besides."""
            if self.headers.get('X-Requested-With') != 'refresher':
                return 'Send the header X-Requested-With: refresher.'
            origin = self.headers.get('Origin')
            if origin is not None:
                hosts = {h.strip().lower() for h in (self.headers.get('Host') or '',
                                                     (self.headers.get('X-Forwarded-Host') or '').split(',')[0]) if h.strip()}
                parts = urlsplit(origin)
                if parts.scheme not in ('http', 'https') or parts.netloc.lower() not in hosts:
                    return 'Cross-site requests are refused.'
            if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
                return 'Cross-site requests are refused.'
            return None

        def do_POST(self):
            parts = urlsplit(self.path)
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = -1
            if 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower():
                length = -1
            if not 0 <= length <= 4096:
                self.close_connection = True
                self.send_json({'error': 'Send an empty body.'}, 413)
                return
            if length:
                self.rfile.read(length)
            if parts.path != '/api/run':
                self.send_json({'error': 'Not found.'}, 404)
                return
            problem = self.cross_site()
            if problem:
                self.send_json({'error': problem}, 403)
                return
            step = parse_qs(parts.query).get('step', [''])[0]
            if step not in ('', 'tmdb'):
                self.send_json({'error': 'The only step that runs alone is tmdb.'}, 400)
                return
            if step == 'tmdb':
                if not refresher.config.tmdb_key:
                    self.send_json({'error': 'TMDB is not configured. Set TMDB_API_KEY.'}, 400)
                    return
                if refresher.current() is None:
                    self.send_json({'error': 'There is no live version to add TMDB data to yet.'}, 409)
                    return
            run = refresher.start_run('tmdb' if step else 'full', 'manual')
            if run is None:
                self.send_json({'error': 'A run is already in progress.', 'running': refresher.status()['running']}, 409)
                return
            self.send_json({'started': True, 'run': run}, 202)

        def log_message(self, fmt, *args):
            pass

    return Handler


# Entry points --------------------------------------------------------------------------

def validate_cli(args):
    try:
        found = validate_version(args.validate, args.previous_shows, args.manifest)
    except Invalid as exc:
        print(f'INVALID {exc}', flush=True)
        return 1
    print('VALID ' + json.dumps(found), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--validate', type=Path, metavar='DIR', help='check a version folder and exit')
    parser.add_argument('--previous-shows', type=int, help='with --validate: the live version\'s show count')
    parser.add_argument('--manifest', type=Path, help='with --validate: the manifest whose date must parse')
    args = parser.parse_args(argv)
    if args.validate:
        return validate_cli(args)
    try:
        config = Config()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    refresher = Refresher(config)
    # The port first: a service that cannot listen should fail before it starts any work.
    server = ThreadingHTTPServer(('0.0.0.0', config.port), make_handler(refresher))
    refresher.start()

    def terminate(_signum, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    due, reason = refresher.next_run()
    say(f"Refresher on port {config.port}; model root {config.root}; pipeline {refresher.pipeline}; "
        f"TMDB {'on' if config.tmdb_key else 'off'}; next run {iso(due)} ({reason}).")
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        say('Stopping.')
        refresher.stop()
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
