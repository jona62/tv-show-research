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
                                  art.bin.gz, the facets (facets.bin.gz,
                                  facets.json.gz, search.json.gz), films.json.gz
                                  when there are films, the co-interest
                                  (cointerest.bin.gz, cointerest.json.gz) when there
                                  are clickstream counts, neighbours.bin.gz, each
                                  show's closest shows, which the apps rank long lists
                                  from, tmdb.json.gz when there is TMDB data, and
                                  build.json, written last to mark it complete
    raw/                          the latest TVmaze pages and manifest.json
    wikidata/                     cache.json.gz, the Wikidata facts the facets are
                                  built from (see wikidata.py), and meta.json
    films/                        cache.json.gz, well-known films from Wikidata, which
                                  each version's films.json.gz is built from (see
                                  films.py and build_films.py), and meta.json
    clickstream/                  cache.json.gz, Wikipedia's clickstream counts
                                  between shows, which the co-interest is built from
                                  (see clickstream.py), and meta.json
    tmdb/                         TMDB id mapping and cache (see tmdb.py)
    state.json                    past runs, so a restart keeps its history
    logs/                         one log per run, the last 14 kept

The Wikidata cache is fetched again when it is WIKIDATA_MAX_AGE_DAYS (7) old or was
fetched by another wikidata.py. A failed fetch is only a warning: the facets are
built from the cache there is, or from TVmaze alone when there is none. The film cache
is fetched on the same terms, by films.py, and each version's films.json.gz is built
from it once the facets are (build_films.py). A failed fetch keeps the cache there is,
and a version whose film index will not build, or that has no cache to build it from,
carries the live version's forward; none of it ever fails a run.

The clickstream comes out monthly. At most once a UTC day, a run with nothing else to
fetch reads which months are published, and the cache fetches whichever of the latest
three it lacks, about 500 MB each, streamed and never stored: three on the first fetch,
then one a month, and a month that failed is tried again on the next run. A changed
clickstream.py counts every month again, beside the cache, which it replaces only when
the count has every month the cache had. A failed fetch is only a warning: the
co-interest is built from the cache there is, and a version has none without one.

Settings, all optional: PORT (8083), MODEL_ROOT, SEED_MODEL_DIR (/home/developer/model),
REFRESH_AT_UTC (04:30), AUTO_DELAY_SECONDS (120), TMDB_API_KEY, TMDB_REGION (US),
TMDB_MIN_POPULARITY (60), TMDB_DAILY_LIMIT (6000), WIKIDATA_MAX_AGE_DAYS (7, and 0
fetches every run, the film cache too), WIKIDATA_SPARQL_URL and WIKIDATA_BACKOFF_SECONDS,
which wikidata.py and films.py are given, CLICKSTREAM_BASE, which clickstream.py is
given with WIKIDATA_SPARQL_URL, and
RAW_SOURCE_DIR, which copies TVmaze pages from a local folder instead of downloading
them, for local runs.
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
import math
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

# The apps' own readers of the model's extras, app/facets.py and app/neighbours.py, copied
# beside this file because the refresher deploys scripts/ alone; test_refresher.py fails
# if either copy drifts.
import facets
import neighbours

HERE = Path(__file__).resolve().parent
STAMP = re.compile(r'\d{8}T\d{6}Z')
MODEL_FILES = ('catalog.json.gz', 'vectors.bin.gz', 'popularity.bin.gz', 'art.bin.gz')
# Built beside the model files from Wikidata and TVmaze. A version may lack them, as the
# frozen seed does, but it has all three or none.
FACET_FILES = ('facets.bin.gz', 'facets.json.gz', 'search.json.gz')
# Which shows the same readers look up, from Wikipedia's clickstream; both or neither.
COINTEREST_FILES = ('cointerest.bin.gz', 'cointerest.json.gz')
# Well-known films in the shows' genre and subject keys, for Couchside's search.
FILM_FILES = ('films.json.gz',)
# Each show's closest shows, from everything above (build_neighbours.py). A seed may lack
# it; the apps then rank a long list from its most recent ratings.
NEIGHBOUR_FILES = ('neighbours.bin.gz',)
# The sources whose change means the model must be built again. tmdb.py and this file
# only shape display data and the service, so a change to them rebuilds nothing.
PIPELINE = ('download.py', 'build_model.py', 'build_popularity.py', 'build_art.py', 'build_facets.py',
            'wikidata.py', 'clickstream.py', 'build_cointerest.py', 'films.py', 'build_films.py',
            'build_neighbours.py', 'study/theme_rules.json', 'study/audit.json', 'requirements-refresher.txt')
KEEP_VERSIONS = 3
KEEP_LOGS = 14
KEEP_RUNS = 60
STALE = timedelta(hours=26)
RETRY = timedelta(hours=2)
MAX_SHIFT = 0.10
TMDB_MAX_AGE = timedelta(days=180)
WIKIDATA_MAX_AGE_DAYS = 7
# A fetch that finds fewer than half the shows the last one did looks broken, not new.
WIKIDATA_MIN_SHARE = 0.5
# The latest published clickstream months the cache holds; build_cointerest.py uses as many.
CLICKSTREAM_MONTHS = 3
MONTH = re.compile(r'\d{4}-\d{2}')
THREAD_VARS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS')
SECRETS = ('TMDB_API_KEY',)
# A first clickstream fetch streams three months, about 1.5 GB: some 5 to 15 minutes on
# the workspace's one vCPU, bound by the download. It keeps each month as soon as it is
# counted, so even a first fetch that runs out of time keeps the months it finished.
# The neighbour index takes two minutes and 820 MB on one thread of a laptop, so perhaps
# ten to twenty minutes here; one that fails leaves the version without it.
TIMEOUTS = {'download': 3 * 3600, 'build_model': 2 * 3600, 'build_popularity': 1800, 'build_art': 1800,
            'wikidata': 3600, 'build_facets': 1800, 'films': 3600, 'build_films': 600, 'clickstream check': 300,
            'clickstream': 2 * 3600, 'build_cointerest': 1800, 'build_neighbours': 2 * 3600, 'tmdb': 3 * 3600,
            'tmdb carry': 1800, 'validate': 1800}
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


def pipeline_hash(folder=HERE, names=PIPELINE):
    digest = hashlib.sha256()
    for name in names:
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


def result_of(done):
    """What a step printed last on a line beginning RESULT, as JSON, or None."""
    line = next((line for line in reversed(done.get('tail') or []) if line.startswith('RESULT ')), None)
    try:
        return json.loads(line[len('RESULT '):]) if line else None
    except ValueError:
        return None


def months_text(months):
    return ', '.join(sorted(months or [])) or 'no months'


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


def matrix_shape(path):
    """(rows, cols, nnz) of a sparse matrix in the vectors.bin.gz layout, once its size
    is checked against its header."""
    path = Path(path)
    with gzip.open(path, 'rb') as f:
        head = f.read(12)
        if len(head) < 12:
            raise Invalid(f'{path.name} is truncated.')
        rows, cols, nnz = struct.unpack('<III', head)
        size = 12
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
    expected = 12 + 4 * ((rows + 1) + 2 * nnz + (cols + 1) + 2 * nnz)
    if size != expected:
        raise Invalid(f'{path.name} holds {size:,} bytes where its header promises {expected:,}.')
    return rows, cols, nnz


def check_facets(folder, ids, date):
    """What a version's facet files hold, or None when it has none. Raises Invalid when
    they are partial, broken, or built for another catalog."""
    present = [name for name in FACET_FILES if (folder / name).exists()]
    if not present:
        return None
    if len(present) < len(FACET_FILES):
        missing = [name for name in FACET_FILES if name not in present]
        raise Invalid(f"{', '.join(missing)} missing beside {', '.join(present)}.")
    try:
        rows, cols, nnz = matrix_shape(folder / 'facets.bin.gz')
        meta = json.loads(gzip.decompress((folder / 'facets.json.gz').read_bytes()))
        search = json.loads(gzip.decompress((folder / 'search.json.gz').read_bytes()))
    except Invalid:
        raise
    except (OSError, EOFError, ValueError, zlib.error, struct.error) as exc:
        raise Invalid(f'A facet file does not decompress: {exc}') from None
    if rows != len(ids):
        raise Invalid(f'facets.bin.gz has {rows:,} rows where the catalog has {len(ids):,} shows.')
    families = meta.get('families') if isinstance(meta, dict) else None
    tokens = meta.get('tokens') if isinstance(meta, dict) else None
    if not isinstance(families, list) or not families or not isinstance(tokens, list):
        raise Invalid('facets.json.gz holds no families and tokens.')
    if len(tokens) != cols:
        raise Invalid(f'facets.json.gz names {len(tokens):,} tokens where facets.bin.gz has {cols:,} columns.')
    if any(not isinstance(t, list) or len(t) != 4 or type(t[0]) is not int or not 0 <= t[0] < len(families)
           for t in tokens):
        raise Invalid('facets.json.gz holds a malformed token.')
    if meta.get('date') != date:
        raise Invalid(f"facets.json.gz was built for the catalog of {meta.get('date')}, not {date}.")
    aliases = search.get('aliases') if isinstance(search, dict) else None
    known = set(ids)
    if not isinstance(aliases, dict) or not all(k.isdigit() and int(k) in known and isinstance(v, list)
                                                for k, v in aliases.items()):
        raise Invalid('search.json.gz names shows that are not in this catalog.')
    return {'tokens': cols, 'nonzeros': nnz, 'linked': meta.get('linked'), 'aliases': len(aliases),
            'wikidata_fetched_at': meta.get('wikidata_fetched_at')}


def check_cointerest(folder, shows):
    """What a version's co-interest holds, or None when it has none. Raises Invalid when
    one file is there without the other, or when the apps could not use them: the matrix
    must read with the apps' own facets.cointerest for this catalog, link only to its
    shows, with similarities above zero, and its metadata must name its months."""
    present = [name for name in COINTEREST_FILES if (folder / name).exists()]
    if not present:
        return None
    if len(present) < len(COINTEREST_FILES):
        missing = [name for name in COINTEREST_FILES if name not in present]
        raise Invalid(f"{', '.join(missing)} missing beside {', '.join(present)}.")
    try:
        indptr, indices, values = facets.cointerest(folder, shows)
    except ValueError as exc:
        raise Invalid(str(exc)) from None
    try:
        meta = json.loads(gzip.decompress((folder / 'cointerest.json.gz').read_bytes()))
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        raise Invalid(f'cointerest.json.gz does not decompress: {exc}') from None
    months = meta.get('months') if isinstance(meta, dict) else None
    if not isinstance(months, list) or not months or not all(isinstance(m, str) and MONTH.fullmatch(m) for m in months):
        raise Invalid('cointerest.json.gz names no clickstream months.')
    if indices and max(indices) >= shows:
        raise Invalid('cointerest.bin.gz links to shows that are not in this catalog.')
    if not all(value > 0 and math.isfinite(value) for value in values):
        raise Invalid('cointerest.bin.gz holds a similarity that is not above zero.')
    return {'months': months, 'shows': meta.get('shows'), 'links': len(indices)}


def check_neighbours(folder, shows):
    """What a version's neighbour index holds, or None when it has none. Raises Invalid when
    the apps could not read it for this catalog with their own neighbours.load."""
    if not (folder / 'neighbours.bin.gz').exists():
        return None
    try:
        found = neighbours.load(folder, shows)
    except ValueError as exc:
        raise Invalid(str(exc)) from None
    return {'width': found.width}


QID = re.compile(r'Q[1-9]\d{0,11}')


def check_films(folder):
    """What a version's film index holds, or None when it has none. Raises Invalid when it
    is there but a search could not use it: every film needs a Q-id, a title, names as
    lists of text, and genres and subjects as keys weighed above 0 and at most 1. Keys
    are not checked against the version's facets: an index carried forward from the
    last version may name one the new facets lack, and the search passes over it."""
    path = folder / 'films.json.gz'
    if not path.exists():
        return None
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        raise Invalid(f'films.json.gz does not decompress: {exc}') from None
    films = data.get('films') if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(films, list) or not films:
        raise Invalid('films.json.gz holds no version 1 film list.')
    weighed = lambda value: (isinstance(value, dict) and all(
        isinstance(k, str) and k and type(v) in (int, float) and 0 < v <= 1 for k, v in value.items()))
    for film in films:
        if not (isinstance(film, dict) and isinstance(film.get('qid'), str) and QID.fullmatch(film['qid'])
                and isinstance(film.get('title'), str) and film['title'].strip()
                and all(isinstance(film.get(k, []), list) and all(isinstance(n, str) for n in film.get(k, []))
                        for k in ('titles', 'aliases'))
                and weighed(film.get('genre')) and weighed(film.get('subject'))
                and all(QID.fullmatch(k) for k in film['subject'])):
            raise Invalid('films.json.gz holds a malformed film.')
    return {'films': len(films), 'series': sum(1 for f in films if f.get('kind') == 'series'),
            'wikidata_fetched_at': data.get('wikidata_fetched_at')}


def validate_version(folder, previous_shows=None, manifest=None):
    """Everything a version must pass before `current` points at it. Returns a summary,
    or raises Invalid with the reason."""
    folder = Path(folder)
    for name in MODEL_FILES:
        if not (folder / name).is_file():
            raise Invalid(f'{name} is missing.')
    try:
        catalog = read_catalog(folder / 'catalog.json.gz')
        rows, cols, nnz = matrix_shape(folder / 'vectors.bin.gz')
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
            'text_features': cols, 'nonzeros': nnz, 'tmdb': tmdb, 'facets': check_facets(folder, ids, date),
            'cointerest': check_cointerest(folder, shows), 'films': check_films(folder),
            'neighbours': check_neighbours(folder, shows)}


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
        try:
            days = float(env.get('WIKIDATA_MAX_AGE_DAYS') or WIKIDATA_MAX_AGE_DAYS)
        except ValueError:
            days = -1.0
        if not 0 <= days < float('inf'):
            raise ValueError('WIKIDATA_MAX_AGE_DAYS must be a number of days, 0 or more.')
        self.wikidata_max_age = timedelta(days=days)
        # Passed to wikidata.py: another endpoint, and the first wait after a failed query.
        self.wikidata_env = {k: env[k] for k in ('WIKIDATA_SPARQL_URL', 'WIKIDATA_BACKOFF_SECONDS') if env.get(k)}
        # Passed to clickstream.py: another dumps server, and the endpoint its title query goes to.
        self.clickstream_env = {k: env[k] for k in ('CLICKSTREAM_BASE', 'WIKIDATA_SPARQL_URL') if env.get(k)}
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
        self.wikidata = self.root / 'wikidata'
        self.films = self.root / 'films'
        self.clickstream = self.root / 'clickstream'
        self.logs = self.root / 'logs'
        self.runner = runner or Processes()
        self.clock = clock
        self.pipeline = pipeline_hash(config.scripts)
        # A cache fetched by another wikidata.py or films.py may lack what this one fetches,
        # and months counted by another clickstream.py may not match what this one counts.
        self.wikidata_script = pipeline_hash(config.scripts, ('wikidata.py',))
        self.films_script = pipeline_hash(config.scripts, ('films.py',))
        self.clickstream_script = pipeline_hash(config.scripts, ('clickstream.py',))
        self.lock = threading.Lock()       # one run at a time in this process
        self.guard = threading.RLock()     # the state and the run in progress
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.state = {'runs': [], 'last_success': None, 'tmdb': None, 'wikidata': None, 'films': None,
                      'clickstream': None}
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
        return {'runs': state.get('runs', []), 'last_success': state.get('last_success'), 'tmdb': state.get('tmdb'),
                'wikidata': state.get('wikidata'), 'films': state.get('films'), 'clickstream': state.get('clickstream')}

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
        # A fetch stopped part way leaves its unfinished cache, and perhaps wikidata.py's or
        # films.py's own temporary file beside it.
        for folder in (self.wikidata, self.films):
            if folder.is_dir():
                for leftover in [folder / 'cache.new.json.gz', *folder.glob('.*.tmp')]:
                    remove(leftover)
        # Likewise a clickstream count made beside the cache, and clickstream.py's temporary
        # files. A cache it wrote in place is whole, and kept.
        if self.clickstream.is_dir():
            for leftover in [self.clickstream / 'cache.new.json.gz', *self.clickstream.glob('*.tmp')]:
                remove(leftover)

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
        for folder in (self.root, self.versions, self.logs, self.root / 'tmdb', self.wikidata, self.films,
                       self.clickstream):
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

    def child_env(self, tmdb=False, wikidata=False, clickstream=False):
        env = {k: v for k, v in os.environ.items() if k not in SECRETS}
        env.update({name: '1' for name in THREAD_VARS})
        env.update(PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        if tmdb:
            env.update(TMDB_API_KEY=self.config.tmdb_key, TMDB_REGION=self.config.tmdb_region,
                       TMDB_MIN_POPULARITY=str(self.config.tmdb_min_popularity),
                       TMDB_DAILY_LIMIT=str(self.config.tmdb_daily_limit))
        if wikidata:
            env.update(self.config.wikidata_env, TV_RAW_DIR=str(self.raw))
        if clickstream:
            env.update(self.config.clickstream_env)
        return env

    def build_env(self, folder, audit):
        env = self.child_env()
        env.update(TV_RAW_DIR=str(self.raw), TV_MANIFEST=str(self.raw / 'manifest.json'),
                   TV_STUDY_DIR=str(self.config.scripts / 'study'), TV_MODEL_OUT=str(folder),
                   TV_ART_OUT=str(folder / 'art.bin.gz'), TV_AUDIT_DIR=str(audit))
        # Only the facets, film and co-interest steps are told where their caches are, by
        # facets_step, films_step and cointerest_step.
        env.pop('TV_WIKIDATA', None)
        env.pop('TV_FILMS', None)
        env.pop('TV_COINTEREST', None)
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

    def wikidata_meta(self):
        """What meta.json says about the Wikidata cache: its fetch date, its show count
        and the wikidata.py that fetched it. {} when there is no cache."""
        meta = read_json(self.wikidata / 'meta.json', {})
        return meta if isinstance(meta, dict) and (self.wikidata / 'cache.json.gz').is_file() else {}

    def wikidata_due(self):
        """Why the Wikidata cache should be fetched again, or None."""
        if not (self.wikidata / 'cache.json.gz').is_file():
            return 'there is no Wikidata cache'
        if not self.config.wikidata_max_age:
            return 'WIKIDATA_MAX_AGE_DAYS is 0'
        meta = self.wikidata_meta()
        if meta.get('script') != self.wikidata_script:
            return 'wikidata.py changed since the cache was fetched'
        fetched = parse_time(meta.get('fetched_at'))
        if fetched is None:
            return 'the cache carries no fetch date'
        if self.clock() - fetched >= self.config.wikidata_max_age:
            return f'the cache is {(self.clock() - fetched).days} days old'
        return None

    def wikidata_step(self, ctx):
        """The Wikidata cache the facets are built from, fetched again when it is due. The
        fetch goes to cache.new.json.gz and replaces the cache only once it is whole and
        about as large as the last one. A failed fetch is a warning, never a failed run:
        the cache there is stays in use. Returns the cache's path, or None."""
        cache, new = self.wikidata / 'cache.json.gz', self.wikidata / 'cache.new.json.gz'
        reason = self.wikidata_due()
        if reason is None:
            ctx.log(f"wikidata: the cache fetched {self.wikidata_meta().get('fetched_at')} is fresh; "
                    'not fetching it again')
            return cache
        ctx.log(f'wikidata: fetching, as {reason}')
        self.wikidata.mkdir(parents=True, exist_ok=True)
        remove(new)
        try:
            done = ctx.run_step('wikidata', self.script('wikidata.py') + ['--out', new], self.child_env(wikidata=True))
            line = next((l for l in reversed(done['tail']) if l.startswith('RESULT ')), None)
            result = json.loads(line[len('RESULT '):]) if line else None
            if not isinstance(result, dict) or not new.is_file() or not isinstance(result.get('shows'), int):
                raise StepFailed('wikidata.py wrote no cache.')
            before = self.wikidata_meta().get('shows')
            if isinstance(before, int) and result['shows'] < before * WIKIDATA_MIN_SHARE:
                raise StepFailed(f"the fetch found {result['shows']:,} shows where the cache has {before:,}")
            os.replace(new, cache)
            write_json(self.wikidata / 'meta.json', {
                'fetched_at': result.get('fetched_at'), 'shows': result['shows'], 'mapped': result.get('mapped'),
                'script': self.wikidata_script})
            ctx.log(f"wikidata: cached {result['shows']:,} shows, fetched {result.get('fetched_at')}")
        except StepFailed as exc:
            if cache.is_file():
                ctx.warn(f"Wikidata step failed, keeping the cache fetched {self.wikidata_meta().get('fetched_at')}: {exc}")
            else:
                ctx.warn(f'Wikidata step failed, building the facets from TVmaze alone: {exc}')
            result = {'error': str(exc)}
        finally:
            remove(new)
        with self.guard:
            self.state['wikidata'] = {'at': iso(self.clock()), **result}
        return cache if cache.is_file() else None

    def facets_step(self, ctx, env, cache):
        """The facets, from the Wikidata cache when there is one. A cache that will not
        build is set aside for this run with a warning, and the facets built from TVmaze
        alone; a build that fails even so fails the run, like any other model step."""
        env = dict(env)
        if cache is not None:
            env['TV_WIKIDATA'] = str(cache)
        try:
            ctx.run_step('build_facets', self.script('build_facets.py'), env)
        except StepFailed as exc:
            if cache is None:
                raise
            ctx.warn(f'The facets would not build from the Wikidata cache, so they were built without it: {exc}')
            env.pop('TV_WIKIDATA')
            ctx.run_step('build_facets', self.script('build_facets.py'), env)

    def films_meta(self):
        """What meta.json says about the film cache: its fetch date, its film count and the
        films.py that fetched it. {} when there is no cache."""
        meta = read_json(self.films / 'meta.json', {})
        return meta if isinstance(meta, dict) and (self.films / 'cache.json.gz').is_file() else {}

    def films_due(self):
        """Why the film cache should be fetched again, or None: on the Wikidata cache's terms."""
        if not (self.films / 'cache.json.gz').is_file():
            return 'there is no film cache'
        if not self.config.wikidata_max_age:
            return 'WIKIDATA_MAX_AGE_DAYS is 0'
        meta = self.films_meta()
        if meta.get('script') != self.films_script:
            return 'films.py changed since the cache was fetched'
        fetched = parse_time(meta.get('fetched_at'))
        if fetched is None:
            return 'the cache carries no fetch date'
        if self.clock() - fetched >= self.config.wikidata_max_age:
            return f'the cache is {(self.clock() - fetched).days} days old'
        return None

    def films_fetch(self, ctx):
        """The film cache, fetched again when it is due. The fetch goes to cache.new.json.gz
        and replaces the cache only once it is whole and about as large as the last one. A
        failed fetch is a warning, never a failed run: the cache there is stays in use.
        Returns the cache's path, or None."""
        cache, new = self.films / 'cache.json.gz', self.films / 'cache.new.json.gz'
        reason = self.films_due()
        if reason is None:
            ctx.log(f"films: the cache fetched {self.films_meta().get('fetched_at')} is fresh; not fetching it again")
            return cache
        ctx.log(f'films: fetching, as {reason}')
        self.films.mkdir(parents=True, exist_ok=True)
        remove(new)
        try:
            done = ctx.run_step('films', self.script('films.py') + ['--out', new], self.child_env(wikidata=True))
            line = next((l for l in reversed(done['tail']) if l.startswith('RESULT ')), None)
            result = json.loads(line[len('RESULT '):]) if line else None
            if not isinstance(result, dict) or not new.is_file() or not isinstance(result.get('films'), int):
                raise StepFailed('films.py wrote no cache.')
            before = self.films_meta().get('films')
            if isinstance(before, int) and result['films'] < before * WIKIDATA_MIN_SHARE:
                raise StepFailed(f"the fetch found {result['films']:,} films where the cache has {before:,}")
            os.replace(new, cache)
            write_json(self.films / 'meta.json', {'fetched_at': result.get('fetched_at'), 'films': result['films'],
                                                  'series': result.get('series'), 'script': self.films_script})
            ctx.log(f"films: cached {result['films']:,} films and series, fetched {result.get('fetched_at')}")
        except StepFailed as exc:
            if cache.is_file():
                ctx.warn(f"Film step failed, keeping the cache fetched {self.films_meta().get('fetched_at')}: {exc}")
            else:
                ctx.warn(f'Film step failed, and there is no film cache yet: {exc}')
            result = {'error': str(exc)}
        finally:
            remove(new)
        with self.guard:
            self.state['films'] = {'at': iso(self.clock()), **result}
        return cache if cache.is_file() else None

    def films_step(self, ctx, env, folder, previous):
        """A version's film index, built from the film cache once the facets are there to
        map it to (build_films.py). With no cache, or a build that fails, the live
        version's index is carried forward, so a failure keeps the last good file; none of
        it ever fails the run."""
        cache = self.films_fetch(ctx)
        target = folder / 'films.json.gz'
        if cache is not None:
            try:
                ctx.run_step('build_films', self.script('build_films.py'), dict(env, TV_FILMS=str(cache)))
            except StepFailed as exc:
                remove(target)
                ctx.warn(f'The film index would not build: {exc}')
        old = previous['path'] / 'films.json.gz' if previous else None
        if not target.is_file() and old is not None and old.is_file():
            link_or_copy(old, target)
            ctx.log("films: carried the live version's film index forward")

    def clickstream_meta(self):
        """What meta.json says about the clickstream cache: the months it holds, when they
        were fetched and by which clickstream.py, and when the listing of published months
        was last read and what it named. {} when there is no cache."""
        meta = read_json(self.clickstream / 'meta.json', {})
        return meta if isinstance(meta, dict) and (self.clickstream / 'cache.json.gz').is_file() else {}

    def clickstream_due(self, meta):
        """Why the clickstream cache should be fetched, and whether every month must be
        counted again; (None, False) when it holds the latest published months, as far as
        the last reading of the listing knows."""
        if not (self.clickstream / 'cache.json.gz').is_file():
            return 'there is no clickstream cache', False
        if not meta:
            return 'nothing records what the cache holds', False
        if meta.get('script') != self.clickstream_script:
            return 'clickstream.py changed since the cache was fetched', True
        held = set(meta.get('months') or [])
        missing = [m for m in (meta.get('published') or [])[-CLICKSTREAM_MONTHS:] if m not in held]
        if missing:
            return f"the cache lacks {', '.join(missing)}", False
        return None, False

    def clickstream_listing_due(self, meta):
        """The listing of published months is read at most once a UTC day."""
        checked = parse_time(meta.get('checked_at'))
        return checked is None or checked.astimezone(timezone.utc).date() < self.clock().astimezone(timezone.utc).date()

    def clickstream_listing(self, ctx, meta):
        """Which months have been published, read by clickstream.py in a step of its own,
        a single small page, and noted in meta.json. A failure is a warning, and the cache
        there is stays."""
        try:
            done = ctx.run_step('clickstream check', self.script('clickstream.py') + [
                '--published', '--months', CLICKSTREAM_MONTHS], self.child_env(clickstream=True))
            found = result_of(done)
            published = found.get('published') if isinstance(found, dict) else None
            if not isinstance(published, list) or not published or \
                    not all(isinstance(m, str) and MONTH.fullmatch(m) for m in published):
                raise StepFailed('clickstream.py named no published months.')
            write_json(self.clickstream / 'meta.json', {**meta, 'checked_at': iso(self.clock()),
                                                        'published': sorted(published)})
        except (StepFailed, OSError) as exc:
            ctx.warn(f"Could not read which clickstream months are out, keeping the cache of "
                     f"{months_text(meta.get('months'))}: {exc}")
            with self.guard:
                self.state['clickstream'] = {'at': iso(self.clock()), 'error': str(exc)}
            return None
        return published

    def clickstream_step(self, ctx):
        """The clickstream cache the co-interest is built from, brought up to date when it
        is due. clickstream.py adds the months the cache lacks in place, writing each one
        as soon as it is counted; after it has changed, it counts every month again into
        cache.new.json.gz, which replaces the cache only when it has every month the cache
        had. A failed fetch is a warning, never a failed run: the cache there is stays in
        use. Returns the cache's path, or None."""
        cache, new = self.clickstream / 'cache.json.gz', self.clickstream / 'cache.new.json.gz'
        self.clickstream.mkdir(parents=True, exist_ok=True)
        meta = self.clickstream_meta()
        reason, recount = self.clickstream_due(meta)
        if reason is None and self.clickstream_listing_due(meta) and self.clickstream_listing(ctx, meta):
            meta = self.clickstream_meta()
            reason, recount = self.clickstream_due(meta)
        if reason is None:
            ctx.log(f"clickstream: the cache holds {months_text(meta.get('months'))}; the listing, last read "
                    f"{meta.get('checked_at') or 'never'}, names nothing it lacks; not fetching")
            return cache
        ctx.log(f'clickstream: fetching, as {reason}')
        target = new if recount else cache
        remove(new)
        try:
            done = ctx.run_step('clickstream', self.script('clickstream.py') + [
                '--cache', target, '--months', CLICKSTREAM_MONTHS], self.child_env(clickstream=True))
            result = result_of(done)
            months_only = lambda v: isinstance(v, list) and all(isinstance(m, str) and MONTH.fullmatch(m) for m in v)
            if not isinstance(result, dict) or not months_only(result.get('months')) \
                    or not months_only(result.get('wanted')) or not isinstance(result.get('skipped'), dict) \
                    or not target.is_file():
                raise StepFailed('clickstream.py wrote no cache.')
            if recount:
                lost = (set(result['wanted']) & set(meta.get('months') or [])) - set(result['months'])
                if lost or not result['months']:
                    raise StepFailed(f"counting again came up without {months_text(lost) if lost else 'any month'}")
                os.replace(new, cache)
            now = iso(self.clock())
            write_json(self.clickstream / 'meta.json', {
                'fetched_at': now, 'months': result['months'], 'titles': result.get('titles'),
                'script': self.clickstream_script, 'checked_at': now, 'published': result['wanted']})
            for month, why in sorted(result['skipped'].items()):
                ctx.warn(f'The clickstream for {month} did not download and is tried again next run: {why}')
            ctx.log(f"clickstream: the cache holds {months_text(result['months'])}")
        except (StepFailed, OSError) as exc:
            if cache.is_file():
                ctx.warn(f"Clickstream step failed, keeping the cache of {months_text(meta.get('months'))}: {exc}")
            else:
                ctx.warn(f'Clickstream step failed, so this version has no co-interest: {exc}')
            result = {'error': str(exc)}
        finally:
            remove(new)
        with self.guard:
            self.state['clickstream'] = {'at': iso(self.clock()), **result}
        return cache if cache.is_file() else None

    def neighbours_step(self, ctx, env, folder):
        """Each show's closest shows, from the text, facets and co-interest just built
        (build_neighbours.py). The apps rank a list of more than 60 ratings from it, and
        without it from the list's 60 most recent likes and dislikes, so a build that fails
        or runs out of time or memory leaves this version without one and a warning; it
        never fails the run. The live version's cannot be carried forward, since an index
        holds one catalogue's shows in that catalogue's order."""
        try:
            ctx.run_step('build_neighbours', self.script('build_neighbours.py'), env)
        except StepFailed as exc:
            for name in NEIGHBOUR_FILES:
                remove(folder / name)
                remove(folder / f'.{name}.tmp')
            ctx.warn(f'The neighbour index would not build, so this version ranks long lists from their '
                     f'most recent ratings: {exc}')

    def cointerest_step(self, ctx, env, cache):
        """The co-interest, from the clickstream cache when there is one; without one,
        build_cointerest.py writes none. A cache that will not build is set aside for this
        run with a warning, and its meta.json dropped, so the next run has clickstream.py
        look it over and count it again if it does not read. A build that fails even
        without it fails the run, like any other model step."""
        env = dict(env, TV_COINTEREST=str(cache) if cache is not None else '')
        try:
            ctx.run_step('build_cointerest', self.script('build_cointerest.py'), env)
        except StepFailed as exc:
            if cache is None:
                raise
            ctx.warn(f'The co-interest would not build from the clickstream cache, so this version has none: {exc}')
            remove(self.clickstream / 'meta.json')
            env['TV_COINTEREST'] = ''
            ctx.run_step('build_cointerest', self.script('build_cointerest.py'), env)

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
        self.facets_step(ctx, env, self.wikidata_step(ctx))
        self.films_step(ctx, env, folder, previous)
        self.cointerest_step(ctx, env, self.clickstream_step(ctx))
        self.neighbours_step(ctx, env, folder)
        self.tmdb_step(ctx, folder, previous, required=False)
        checked = ctx.validate(folder, previous and previous['build'].get('shows'), self.raw / 'manifest.json')
        self.finish(ctx, folder, {
            'version': ctx.stamp, 'built_at': iso(self.clock()), 'snapshot_date': checked['snapshot_date'],
            'shows': checked['shows'], 'pipeline': self.pipeline, 'seeded_from': None, 'tmdb': checked['tmdb'],
            'facets': checked['facets'], 'cointerest': checked['cointerest'], 'films': checked['films'],
            'neighbours': checked['neighbours']})

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
            for name in MODEL_FILES + FACET_FILES + COINTEREST_FILES + FILM_FILES + NEIGHBOUR_FILES:
                if name in MODEL_FILES or (live['path'] / name).is_file():
                    link_or_copy(live['path'] / name, folder / name)
        self.tmdb_step(ctx, folder, live, required=True)
        checked = ctx.validate(folder, live['build'].get('shows'))
        old = live['build']
        self.finish(ctx, folder, {
            'version': ctx.stamp, 'built_at': iso(self.clock()), 'snapshot_date': old.get('snapshot_date'),
            'shows': checked['shows'], 'pipeline': old.get('pipeline'), 'seeded_from': old.get('seeded_from'),
            'tmdb': checked['tmdb'], 'facets': checked['facets'], 'cointerest': checked['cointerest'],
            'films': checked['films'], 'neighbours': checked['neighbours']})

    def seed_run(self, ctx):
        """The first version, copied from the model the apps were deployed with. Art comes
        from the raw pages when the seed has none. The facets come along when the seed has
        all three files, the co-interest when it has both, and the film index and the
        neighbour index when it has them; the first full build makes them otherwise."""
        seed = Path(self.config.seed)
        missing = [name for name in MODEL_FILES[:3] if not (seed / name).is_file()]
        if missing:
            raise StepFailed(f"Nothing to seed from: {seed} lacks {', '.join(missing)}.")
        folder = ctx.new_version()
        extras = tuple(name for group in (FACET_FILES, COINTEREST_FILES, FILM_FILES, NEIGHBOUR_FILES)
                       if all((seed / name).is_file() for name in group) for name in group)
        with ctx.step('copy seed'):
            for name in MODEL_FILES + extras + ('tmdb.json.gz',):
                if (seed / name).is_file():
                    shutil.copyfile(seed / name, folder / name)
        if not (folder / 'art.bin.gz').exists():
            if not has_index(self.raw):
                self.fetch_index(ctx)
            ctx.run_step('build_art', self.script('build_art.py'), self.build_env(folder, folder / 'audit'))
        checked = ctx.validate(folder)
        self.finish(ctx, folder, {
            'version': ctx.stamp, 'built_at': iso(self.clock()), 'snapshot_date': checked['snapshot_date'],
            'shows': checked['shows'], 'pipeline': self.pipeline, 'seeded_from': str(seed), 'tmdb': checked['tmdb'],
            'facets': checked['facets'], 'cointerest': checked['cointerest'], 'films': checked['films'],
            'neighbours': checked['neighbours']})

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
            wikidata_last = self.state.get('wikidata')
            films_last = self.state.get('films')
            clickstream_last = self.state.get('clickstream')
        live = self.current()
        due, reason = self.next_run()
        meta = self.wikidata_meta()
        films = self.films_meta()
        clicks = self.clickstream_meta()
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
            'wikidata': {'max_age_days': self.config.wikidata_max_age.total_seconds() / 86400,
                         'cache': {'fetched_at': meta.get('fetched_at'), 'shows': meta.get('shows'),
                                   'mapped': meta.get('mapped')} if meta else None,
                         'last': wikidata_last},
            'films': {'cache': {'fetched_at': films.get('fetched_at'), 'films': films.get('films'),
                                'series': films.get('series')} if films else None,
                      'last': films_last},
            'clickstream': {'months': CLICKSTREAM_MONTHS,
                            'cache': {k: clicks.get(k) for k in ('months', 'fetched_at', 'titles', 'checked_at',
                                                                 'published')} if clicks else None,
                            'last': clickstream_last},
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


def facts_line(facets):
    """The live build's facets in a line, or None when it has none."""
    if not facets:
        return None
    source = (f"Wikidata fetched {when(facets['wikidata_fetched_at'])}" if facets.get('wikidata_fetched_at')
              else 'TVmaze alone')
    return (f"{facets.get('tokens') or 0:,} tokens, {facets.get('linked') or 0:,} shows linked, "
            f"{facets.get('aliases') or 0:,} with other names; from {source}")


def films_line(films):
    """The live build's film index in a line, or None when it has none."""
    if not films:
        return None
    return (f"{films.get('films') or 0:,} films and series, {films.get('series') or 0:,} of them series; "
            f"from Wikidata fetched {when(films.get('wikidata_fetched_at'))}")


def cointerest_line(cointerest):
    """The live build's co-interest in a line, or None when it has none."""
    if not cointerest:
        return None
    return (f"{cointerest.get('links') or 0:,} links among {cointerest.get('shows') or 0:,} shows, from the "
            f"clickstream of {months_text(cointerest.get('months'))}")


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
         if (build.get('tmdb') or {}).get('shows') else None),
        ('facets', facts_line(build.get('facets'))), ('co-interest', cointerest_line(build.get('cointerest'))),
        ('films', films_line(build.get('films'))),
        ('neighbours', f"the {build['neighbours']['width']} closest shows to each show, for ranking long lists"
         if build.get('neighbours') else None))
    ) if live else ''
    wikidata = status['wikidata']
    cache, tried = wikidata.get('cache') or {}, wikidata.get('last') or {}
    wikidata_line = (f"{cache['shows']:,} shows cached, fetched {when(cache.get('fetched_at'))}" if cache.get('shows')
                     else 'No cache yet; the next build fetches one')
    wikidata_note = f"Fetched again when {wikidata['max_age_days']:g} days old" + (
        f"; the last try, {when(tried.get('at'))}, failed: {tried['error']}" if tried.get('error') else '')
    films = status['films']
    film_cache, film_try = films.get('cache') or {}, films.get('last') or {}
    films_card = (f"{film_cache['films']:,} films and series cached, fetched {when(film_cache.get('fetched_at'))}"
                  if film_cache.get('films') else 'No cache yet; the next build fetches one')
    films_note = 'Fetched again with the Wikidata cache; each build maps it to its facets' + (
        f"; the last try, {when(film_try.get('at'))}, failed: {film_try['error']}" if film_try.get('error') else '')
    clickstream = status['clickstream']
    clicks, clicked = clickstream.get('cache') or {}, clickstream.get('last') or {}
    held = clicks.get('months') or []
    clickstream_line = (f"{len(held)} month{'' if len(held) == 1 else 's'} held: {months_text(held)}" if held
                        else 'No months held yet; the next build fetches them')
    trouble = clicked.get('error') or '; '.join(f'{month} did not download' for month in sorted(clicked.get('skipped') or {}))
    clickstream_note = (f"New months looked for once a day, last {when(clicks.get('checked_at'))}; builds use the "
                        f"latest {clickstream['months']}") + (
        f"; the last try, {when(clicked.get('at'))}: {trouble}" if trouble else '')
    last = tmdb.get('last') or {}
    tmdb_line = (f"On, region {e(tmdb['region'])}, up to {tmdb['daily_limit']:,} requests a night, "
                 "one for each show and one for each season whose trailers it asks for"
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
<div class="card"><h2>Wikidata</h2><p>{e(wikidata_line)}</p><p class="dim">{e(wikidata_note)}</p></div>
<div class="card"><h2>Films</h2><p>{e(films_card)}</p><p class="dim">{e(films_note)}</p></div>
<div class="card"><h2>Clickstream</h2><p>{e(clickstream_line)}</p><p class="dim">{e(clickstream_note)}</p></div>
<div class="card"><h2>Pipeline</h2><p><code>{e(status['pipeline'])}</code></p><p class="dim">{e(kept)}</p></div>
</section>
<section><h2>Live build</h2>{f'<dl>{facts}</dl>' if live else '<p class="dim">Nothing is live yet.</p>'}</section>
<section><h2>Recent runs</h2>{table}</section>
</main>
<footer class="dim">Show data from TVmaze, CC BY-SA 4.0, and Wikidata, CC0; which shows the same readers look up, from Wikipedia's clickstream, CC0.{' This product uses the TMDB API but is not endorsed or certified by TMDB.' if tmdb['configured'] else ''}</footer>
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
