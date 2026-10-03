"""Supplement Locust's latency/RPS metrics without claiming browser cache measurements."""
from collections import Counter, deque
from dataclasses import asdict
import json
from pathlib import Path
import time

import gevent
from gevent.lock import BoundedSemaphore
from workload import PUBLIC_CACHE_LIMITS


class ProtocolMetrics:
    def __init__(self, config):
        self.config = config
        self.gate = BoundedSemaphore(config.max_inflight)
        self.started = time.monotonic()
        self.active = self.peak_active = self.waiting = self.peak_waiting = 0
        self.peak_virtual_users = 0
        self.gate_wait = deque(maxlen=20000)
        self.statuses, self.journeys, self.users, self.cache_headers = (Counter() for _ in range(4))
        self.application = Counter()
        self.simulated_public_cache = Counter()
        self.latencies = {name: Counter() for name in ('successful', 'api_successful', 'api_user_successful', 'failed', 'expected_non_2xx')}
        self.endpoints = {}
        self.journey_latencies = {}
        self.decoded_bytes = self.requests = self.retries = self.gate_blocked = 0
        self.generator_cpu_warnings = 0
        self.samples = []
        self.stopped = False
        self.pool_closed = None if config.connection_model == 'persistent' else False

    def enter(self):
        began = time.monotonic()
        blocked = self.gate.locked()
        if blocked:
            self.waiting += 1
            self.peak_waiting = max(self.peak_waiting, self.waiting)
            self.gate_blocked += 1
        try:
            self.gate.acquire()
        finally:
            if blocked:
                self.waiting -= 1
        waited = (time.monotonic() - began) * 1000
        self.gate_wait.append(waited)
        self.active += 1
        self.peak_active = max(self.active, self.peak_active)
        return waited

    def leave(self):
        self.active -= 1
        self.gate.release()

    def response(self, response, expected=False):
        self.requests += 1
        self.statuses[str(response.status_code) + ('_expected' if expected else '')] += 1
        self.decoded_bytes += len(response.content or b'')
        # Only explicit instrumentation is a server-cache hit. max-age is policy, not a hit.
        for name in ('X-Couchside-Cache', 'X-Cache'):
            if value := (response.headers or {}).get(name):
                self.cache_headers[name + ':' + value] += 1

    def latency(self, response_time, response, exception, context):
        status = getattr(response, 'status_code', 0)
        bucket = 'failed' if exception else 'successful' if 200 <= status < 300 else 'expected_non_2xx'
        milliseconds = min(120000, max(0, round(response_time)))
        self.latencies[bucket][milliseconds] += 1
        if bucket == 'successful' and context.get('api'):
            self.latencies['api_successful'][milliseconds] += 1
            user_ms = min(120000, max(0, round(response_time + context.get('gate_ms', 0))))
            self.latencies['api_user_successful'][user_ms] += 1
            endpoint = self.endpoints.setdefault(context.get('name', 'api'), Counter())
            endpoint[user_ms] += 1

    def completed_journey(self, name, elapsed_ms):
        histogram = self.journey_latencies.setdefault(name, Counter())
        histogram[min(120000, max(0, round(elapsed_ms)))] += 1

    def record_public_cache(self, kind, outcome, count=1):
        self.simulated_public_cache[f'{kind}.{outcome}'] += count

    @staticmethod
    def latency_summary(histogram):
        count = sum(histogram.values())
        cumulative, quantiles = 0, {}
        for milliseconds, samples in sorted(histogram.items()):
            cumulative += samples
            for percentile in (50, 95, 99):
                if percentile not in quantiles and cumulative >= count * percentile / 100:
                    quantiles[percentile] = milliseconds
        return {'count': count, 'p50_ms': quantiles.get(50), 'p95_ms': quantiles.get(95),
                'p99_ms': quantiles.get(99), 'max_ms': max(histogram, default=None),
                'under_100_ms': sum(count for ms, count in histogram.items() if ms < 100),
                'resolution_ms': 1, 'upper_bucket_ms': 120000}

    def summary(self):
        waits = sorted(self.gate_wait)
        percentile = lambda fraction: waits[min(len(waits) - 1, int(len(waits) * fraction))] if waits else 0
        public_config = {k: v for k, v in asdict(self.config).items()
                         if k not in ('accounts_path', 'metrics_directory', 'gateway_key_path')}
        counts = {name: sum(histogram.values()) for name, histogram in self.latencies.items()}
        definitive = {'total': counts['successful'] + counts['failed'] + counts['expected_non_2xx'],
                      'successful_2xx': counts['successful'], 'failed': counts['failed'],
                      'expected_non_2xx': counts['expected_non_2xx'],
                      'api_successful_2xx': counts['api_successful']}
        return {'schema': 1, 'kind': 'locust-http-protocol', 'configuration': public_config,
                'finished': self.stopped, 'definitive_request_counts': definitive,
                'elapsed_seconds': time.monotonic() - self.started,
                'requests': self.requests, 'decoded_response_bytes': self.decoded_bytes,
                'statuses': dict(self.statuses), 'journey_counts': dict(self.journeys),
                'application_events': dict(self.application),
                'request_latency': {name: self.latency_summary(histogram) for name, histogram in self.latencies.items()},
                'endpoint_user_latency': {name: self.latency_summary(histogram) for name, histogram in self.endpoints.items()},
                'completed_journey_latency': {name: self.latency_summary(histogram)
                                              for name, histogram in self.journey_latencies.items()},
                'user_counts': dict(self.users), 'retries': self.retries,
                'started_virtual_users': self.users['guest'] + self.users['authenticated'],
                'peak_virtual_users': self.peak_virtual_users,
                'max_active_wire_requests': self.peak_active, 'max_gate_waiting_users': self.peak_waiting,
                'gate_blocked_requests': self.gate_blocked, 'gate_wait_sample_size': len(waits),
                'gate_wait_ms': {'p50': percentile(.5), 'p95': percentile(.95), 'p99': percentile(.99)},
                'explicit_server_cache_headers': dict(self.cache_headers),
                'simulated_public_cache': {'enabled': self.config.simulate_public_cache,
                                           'counters': dict(self.simulated_public_cache),
                                           'limits_per_user': PUBLIC_CACHE_LIMITS,
                                           'retains_response_bodies': False},
                'generator_cpu_warnings': self.generator_cpu_warnings,
                'shared_pool_closed': self.pool_closed,
                'browser_cache_hits': None, 'samples': self.samples,
                'limitations': ['HTTP users do not execute JavaScript, scroll, use clipboard, download snapshots, '
                                'or read a browser HTTP/service-worker cache. The real-browser cohort measures these.',
                                'Virtual users include thinking and semaphore-waiting sessions. '
                                'The in-flight limit applies per load-generator worker.',
                                'Persistent mode keeps an independent connection pool per virtual user. '
                                'Pooled mode shares a bounded backend pool, approximating a reverse proxy; '
                                'it does not test the target holding 10,000 direct TCP connections.',
                                'api_user_successful and endpoint_user_latency include time queued at the generator gate; Locust response latency excludes it.',
                                'Completed journey latency includes generator queueing, request retries/backoff '
                                'and pauses within the journey; it excludes think time between journeys.',
                                'Random choices repeat for the same seed, worker layout and user ordinal; '
                                'concurrent timing, calendar date and provider cache state do not.',
                                'warm_probability controls repeated show/query choices; it is not a measured '
                                'cache-hit rate. Cache-hit measurements require actual instrumentation.',
                                'simulated_public_cache is an opt-in metadata model of comparison public-data '
                                'eligibility, not measured browser/IndexedDB/service-worker hits. Avoided '
                                'requests never enter HTTP latency, RPS or success counts. It does not model '
                                'browser pending-record polling, persistent storage or personal/private caching.']}

    def capture(self, environment):
        runner = environment.runner
        self.peak_virtual_users = max(self.peak_virtual_users, runner.user_count)
        self.samples.append({'seconds': round(time.monotonic() - self.started, 3),
                             'virtual_users': runner.user_count, 'active_requests': self.active,
                             'waiting_for_gate': self.waiting, 'requests': self.requests,
                             'rps': environment.stats.total.current_rps,
                             'failures': environment.stats.total.num_failures})
        self.write()

    def write(self):
        if not self.config.metrics_directory:
            return
        directory = Path(self.config.metrics_directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'protocol-worker-{self.config.worker_index}.json'
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(self.summary(), indent=2))
        temporary.replace(path)

    def sample_loop(self, environment):
        while not self.stopped:
            self.capture(environment)
            gevent.sleep(5)
