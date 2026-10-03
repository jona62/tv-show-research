"""Opt-in, bounded load-test counters; no query, account, credential or URL logging.

Snapshots are cumulative per process. Cache counters describe individual layers,
not a combined hit ratio. Latency percentiles use histogram upper bounds; browser
and load generators retain their own exact request timings.
"""
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
import atexit
import json
import math
import os
import threading
import time

BOUNDS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000)
LAYERS = frozenset(('shared_http_disk', 'shared_http_inflight', 'shared_http_lease', 'live_memory',
                    'live_detail_disk', 'live_inflight', 'live_stale', 'search_memory',
                    'episodes_memory', 'episodes_disk', 'episodes_inflight', 'episodes_full_memory',
                    'public_json', 'public_json_inflight',
                    'artwork_source_memory', 'artwork_source_inflight', 'artwork_inflight', 'icons_memory',
                    'static_memory', 'page_gzip', 'home_pages', 'catalogue_pool', 'recommendation_answers'))
OUTCOMES = frozenset(('hit', 'miss', 'stale', 'coalesced', 'expired', 'corrupt', 'negative', 'blocked'))
PROVIDERS = {'api.tvmaze.com': 'tvmaze', 'api.themoviedb.org': 'tmdb',
             'static.tvmaze.com': 'tvmaze_image', 'image.tmdb.org': 'tmdb_image',
             'api.kinocheck.com': 'kinocheck', 'itunes.apple.com': 'itunes',
             'query.wikidata.org': 'wikidata', 'en.wikipedia.org': 'wikipedia',
             'icons.duckduckgo.com': 'icons'}
ROUTES = frozenset(('home', 'browse', 'new', 'search', 'related', 'show', 'title', 'live',
                    'episodes', 'episode', 'episode-ratings', 'episode-ratings-batch', 'show-cards', 'episode-matrices', 'matrices', 'matrix', 'backdrop', 'rating', 'extra', 'shows',
                    'trailer', 'watch', 'person', 'biography', 'icon', 'starters', 'taste',
                    'register', 'login', 'logout', 'session', 'state', 'password', 'forgot',
                    'reset', 'verify', 'compare', 'list', 'welcome', 'robots.txt', 'sitemap.xml'))


class Recorder:
    def __init__(self, path, interval=5, clock=time.monotonic):
        self.path, self.interval, self.clock = Path(path), max(.2, interval), clock
        self.started = clock()
        self.lock, self.write_lock, self.stopped = threading.Lock(), threading.Lock(), threading.Event()
        self.counters, self.latencies = Counter(), {}
        self.worker = None

    def add(self, key, amount=1):
        with self.lock:
            self.counters[key] += amount

    def observe(self, key, milliseconds):
        if not math.isfinite(milliseconds) or milliseconds < 0:
            return
        with self.lock:
            held = self.latencies.setdefault(key, {'count': 0, 'sum': 0., 'max': 0., 'buckets': [0] * (len(BOUNDS) + 1)})
            held['count'] += 1
            held['sum'] += milliseconds
            held['max'] = max(held['max'], milliseconds)
            held['buckets'][next((n for n, upper in enumerate(BOUNDS) if milliseconds <= upper), len(BOUNDS))] += 1

    def snapshot(self, final=False):
        with self.lock:
            latencies = {key: {**value, 'buckets': list(value['buckets'])} for key, value in self.latencies.items()}
            counters = dict(self.counters)
        return {'version': 1, 'kind': 'server_metrics', 'pid': os.getpid(), 'final': final,
                'elapsed_s': round(self.clock() - self.started, 3), 'at_unix_s': time.time(),
                'counters': counters, 'latency_ms': latencies, 'latency_bucket_upper_ms': [*BOUNDS, None]}

    def flush(self, final=False):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.write_lock:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(descriptor, 'a') as output:
                    output.write(json.dumps(self.snapshot(final), separators=(',', ':'), allow_nan=False) + '\n')
            return True
        except (OSError, ValueError):
            self.add('metrics.export_errors')
            return False

    def start(self):
        self.worker = threading.Thread(target=self._run, name='load-metrics', daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stopped.wait(self.interval):
            self.flush()

    def stop(self):
        self.stopped.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=1)
        self.flush(final=True)


_recorder = None
_configuration_lock = threading.Lock()


def configure(path=None, interval=5, background=True):
    """Explicit setup for test processes; disabled by default in normal apps."""
    global _recorder
    with _configuration_lock:
        if _recorder:
            _recorder.stop()
        _recorder = Recorder(path, interval) if path else None
        if _recorder and background:
            _recorder.start()
        return _recorder


def configure_from_env():
    path = os.environ.get('COUCHSIDE_METRICS_FILE')
    if not path:
        return None
    try:
        interval = float(os.environ.get('COUCHSIDE_METRICS_INTERVAL', '5'))
        if not math.isfinite(interval):
            interval = 5
    except ValueError:
        interval = 5
    return configure(path, interval)


def enabled():
    return _recorder is not None


def cache(layer, outcome, kind='api'):
    recorder = _recorder
    if recorder and layer in LAYERS and outcome in OUTCOMES:
        recorder.add(f'cache.{layer}.{"image" if kind == "image" else "api"}.{outcome}')


def provider(host):
    return PROVIDERS.get(host.lower(), 'other')


def upstream_attempt(host):
    recorder = _recorder
    if recorder:
        recorder.add(f'upstream.{provider(host)}.attempts')


def upstream_result(host, outcome, milliseconds=0, size=0, status=None):
    recorder = _recorder
    if not recorder:
        return
    name = provider(host)
    outcome = outcome if outcome in {'success', 'http_error', 'transport_error', 'blocked'} else 'error'
    recorder.add(f'upstream.{name}.{outcome}')
    recorder.add(f'upstream.{name}.decoded_bytes', max(0, size))
    if status is not None:
        group = f'{status // 100}xx' if isinstance(status, int) and 100 <= status < 600 else 'other'
        recorder.add(f'upstream.{name}.status.{group}')
    recorder.observe(f'upstream.{name}', milliseconds)


def request_route(path):
    try:
        parts = urlsplit(path).path.strip('/').split('/')
    except ValueError:
        return 'other'
    if parts[0] == 'api':
        route = parts[-1] if parts[-1] in ROUTES else 'other'
        return 'api.' + route
    if parts[0] == 'assets':
        return 'static'
    if parts[0].startswith('sitemap'):
        return 'sitemap'
    return parts[0] if parts[0] in ROUTES else 'page'


def record_request(method, path, status, duration_ms, bytes=0, cache=None):
    recorder = _recorder
    if not recorder:
        return
    route = request_route(path)
    method = method if method in {'GET', 'POST', 'HEAD', 'OPTIONS'} else 'other'
    prefix = f'http.{method}.{route}'
    group = f'{status // 100}xx' if isinstance(status, int) and 100 <= status < 600 else 'other'
    recorder.add(prefix + '.requests')
    recorder.add(prefix + '.status.' + group)
    if status == 499:
        recorder.add(prefix + '.cancelled')
    recorder.add(prefix + '.bytes', max(0, bytes))
    if cache in {'hit', 'miss', 'not_modified'}:
        recorder.add(prefix + '.cache.' + cache)
    recorder.observe(prefix, duration_ms)


def flush(final=False):
    recorder = _recorder
    return recorder.flush(final) if recorder else False


def stop():
    global _recorder
    if _recorder:
        _recorder.stop()
        _recorder = None


atexit.register(stop)
