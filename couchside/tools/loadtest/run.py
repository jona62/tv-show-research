"""Run staged Locust traffic and save raw metrics, resources, and server-cache deltas."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
import csv
import ipaddress
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
import uuid

import psutil
from protocol_metrics import ProtocolMetrics

HERE = Path(__file__).resolve().parent


def inflight_caps(total, workers):
    if workers < 1 or total < workers:
        raise ValueError('Choose positive workers and at least one aggregate in-flight slot per worker.')
    slots, remainder = divmod(total, workers)
    return [slots + (index < remainder) for index in range(workers)]


def final_protocol(directory, run_id, worker_count, max_inflight):
    """Merge final events, rejecting incomplete, stale or inconsistent snapshots."""
    errors, workers = [], []
    caps = inflight_caps(max_inflight, worker_count)
    expected = {f'protocol-worker-{index}.json' for index in range(worker_count)}
    unexpected = {path.name for path in directory.glob('protocol-worker-*.json')} - expected
    if unexpected:
        errors.append('Unexpected worker metric files: ' + ', '.join(sorted(unexpected)))

    def read(path):
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError('Expected a JSON object.')
            return value
        except (OSError, ValueError) as error:
            errors.append(f'{path.name}: unavailable or invalid metrics ({error}).')
            return {}

    families = ('request_latency', 'endpoint_user_latency', 'completed_journey_latency')
    histograms = {family: {} for family in families}
    gate_histogram = Counter()
    scalar_fields = ('requests', 'decoded_response_bytes', 'retries', 'gate_blocked_requests', 'generator_cpu_warnings')
    counter_fields = ('statuses', 'journey_counts', 'application_events', 'user_counts', 'explicit_server_cache_headers')
    sums = {key: 0 for key in scalar_fields}
    counters = {key: Counter() for key in counter_fields}
    simulation = Counter()
    common = None

    def histogram(raw):
        if not isinstance(raw, dict):
            raise ValueError('Missing raw histogram.')
        result = Counter()
        for key, count in raw.items():
            bucket = int(key)
            if str(bucket) != str(key) or not 0 <= bucket <= 120000 or type(count) is not int or count <= 0:
                raise ValueError('Invalid histogram bucket or count.')
            result[bucket] += count
        return result

    def checked_counter(raw):
        if not isinstance(raw, dict) or any(type(count) is not int or count < 0 for count in raw.values()):
            raise ValueError('Invalid counter map.')
        return Counter(raw)

    for index in range(worker_count):
        path = directory / f'protocol-worker-{index}.json'
        worker = read(path)
        if not worker:
            continue
        try:
            config = worker['configuration']
            if (config.get('run_id'), config.get('worker_count'), config.get('worker_index'), config.get('max_inflight')) != (
                    run_id, worker_count, index, caps[index]):
                raise ValueError('Run identity, worker layout or in-flight cap does not match this stage.')
            shared = {key: value for key, value in config.items() if key not in ('worker_index', 'max_inflight')}
            if common is not None and shared != common:
                raise ValueError('Workers have inconsistent workload configurations.')
            parsed = {family: {name: histogram(values) for name, values in worker['histograms'][family].items()}
                      for family in families}
            if set(parsed['request_latency']) != {'successful', 'failed', 'expected_non_2xx', 'api_successful', 'api_user_successful'}:
                raise ValueError('Missing request-event histogram categories.')
            for family, values in parsed.items():
                if {name: ProtocolMetrics.latency_summary(value) for name, value in values.items()} != worker[family]:
                    raise ValueError('Raw histograms do not reconcile with final latency summaries.')
            definitive = {name: sum(values.values()) for name, values in parsed['request_latency'].items()}
            expected_counts = {'total': sum(definitive[name] for name in ('successful', 'failed', 'expected_non_2xx')),
                               'successful_2xx': definitive['successful'], 'failed': definitive['failed'],
                               'expected_non_2xx': definitive['expected_non_2xx'],
                               'api_successful_2xx': definitive['api_successful']}
            if worker['definitive_request_counts'] != expected_counts:
                raise ValueError('Final request counters do not reconcile with raw histograms.')
            if (sum(worker['statuses'].values()) != worker['requests'] or worker['requests'] != expected_counts['total'] or
                    definitive['api_successful'] != definitive['api_user_successful'] or
                    definitive['api_successful'] > definitive['successful'] or
                    sum(sum(value.values()) for value in parsed['endpoint_user_latency'].values()) != definitive['api_user_successful']):
                raise ValueError('Final status, request or API endpoint counts do not reconcile.')
            worker_sums = {key: worker[key] for key in scalar_fields}
            if any(type(value) is not int or value < 0 for value in worker_sums.values()):
                raise ValueError('Invalid scalar counter.')
            worker_counters = {key: checked_counter(worker[key]) for key in counter_fields}
            for key in ('started_virtual_users', 'peak_virtual_users', 'max_active_wire_requests', 'max_gate_waiting_users'):
                if type(worker[key]) is not int or worker[key] < 0:
                    raise ValueError('Invalid user or concurrency count.')
            if worker['started_virtual_users'] != worker_counters['user_counts']['guest'] + worker_counters['user_counts']['authenticated']:
                raise ValueError('Started user counters do not reconcile.')
            unavailable = worker_counters['user_counts']['auth_fixture_unavailable']
            if unavailable:
                errors.append(f'{path.name}: authenticated fixtures unavailable for {unavailable} requested users.')
            worker_simulation = checked_counter(worker['simulated_public_cache']['counters'])
            gate = histogram(worker['histograms']['gate_wait'])
            if worker['finished'] is not True:
                errors.append(f'{path.name}: worker did not finish.')
            if config['connection_model'] == 'pooled' and worker.get('shared_pool_closed') is not True:
                errors.append(f'{path.name}: shared pool did not close.')
            if worker['max_active_wire_requests'] > caps[index]:
                raise ValueError('Observed active requests exceeded the assigned cap.')
            common = shared
            workers.append(worker)
            for family, values in parsed.items():
                for name, value in values.items():
                    histograms[family].setdefault(name, Counter()).update(value)
            gate_histogram.update(gate)
            for key, value in worker_sums.items():
                sums[key] += value
            for key, value in worker_counters.items():
                counters[key].update(value)
            simulation.update(worker_simulation)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            errors.append(f'{path.name}: inconsistent final metrics ({error}).')

    master = {}
    if worker_count > 1:
        master = read(directory / 'protocol-master.json')
        required = {'configuration', 'run_id', 'worker_count', 'aggregate_max_inflight', 'finished', 'current_users',
                    'peak_virtual_users', 'peak_user_count_source', 'worker_clients', 'worker_reports',
                    'generator_cpu_warnings', 'errors', 'samples'}
        if required - master.keys():
            errors.append('Master is missing required final observation fields.')
        roster = master.get('worker_clients', {})
        if (master.get('run_id'), master.get('worker_count'), master.get('aggregate_max_inflight')) != (
                run_id, worker_count, max_inflight):
            errors.append('Master run identity, worker count or aggregate cap does not match this stage.')
        master_config = master.get('configuration', {})
        if (not isinstance(master_config, dict) or
                {key: value for key, value in master_config.items() if key not in ('worker_index', 'max_inflight')} != common):
            errors.append('Master and workers have inconsistent workload configurations.')
        roster_valid = (isinstance(roster, dict) and len(roster) == worker_count and
                        all(type(index) is int for index in roster.values()) and
                        sorted(roster.values()) == list(range(worker_count)))
        if not roster_valid:
            errors.append('Master did not observe exactly the expected unique worker roster.')
        reports = master.get('worker_reports', {})
        if not roster_valid or not isinstance(reports, dict) or set(reports) != set(roster):
            errors.append('Master is missing final reports from its worker roster.')
        else:
            for client_id, report in reports.items():
                index = roster[client_id]
                if (not isinstance(report, dict) or report.get('run_id') != run_id or
                        report.get('worker_count') != worker_count or report.get('worker_index') != index or
                        index not in range(worker_count) or report.get('max_inflight') != caps[index] or
                        report.get('user_count') != 0 or report.get('finished') is not True or
                        (common and common.get('connection_model') == 'pooled' and report.get('shared_pool_closed') is not True)):
                    errors.append('Master worker reports are incomplete or inconsistent.')
        if (master.get('finished') is not True or type(master.get('current_users')) is not int or
                master.get('current_users') != 0 or not isinstance(master.get('errors'), list) or master.get('errors')):
            errors.append('Master did not finish cleanly or reported inconsistent workers.')
        if type(master.get('peak_virtual_users')) is not int or master.get('peak_virtual_users', -1) < 0:
            errors.append('Master observed user peak is missing or invalid.')

    if worker_count == 1 and workers:
        result = dict(workers[0])
    else:
        latency = {family: {name: ProtocolMetrics.latency_summary(values) for name, values in members.items()}
                   for family, members in histograms.items()}
        counts = {name: value['count'] for name, value in latency['request_latency'].items()}
        gate = ProtocolMetrics.latency_summary(gate_histogram)
        result = {'schema': 2, 'kind': 'locust-http-protocol-aggregate',
                  'configuration': {**(common or {}), 'max_inflight': max_inflight},
                  **sums, **{key: dict(value) for key, value in counters.items()}, **latency,
                  'histograms': {**{family: {name: dict(value) for name, value in values.items()}
                                      for family, values in histograms.items()}, 'gate_wait': dict(gate_histogram)},
                  'definitive_request_counts': {'total': sum(counts.get(name, 0) for name in ('successful', 'failed', 'expected_non_2xx')),
                                               'successful_2xx': counts.get('successful', 0),
                                               'failed': counts.get('failed', 0),
                                               'expected_non_2xx': counts.get('expected_non_2xx', 0),
                                               'api_successful_2xx': counts.get('api_successful', 0)},
                  'started_virtual_users': sum(worker['started_virtual_users'] for worker in workers),
                  'peak_virtual_users': master.get('peak_virtual_users', 0) if type(master.get('peak_virtual_users')) is int else 0,
                  'peak_user_count_source': master.get('peak_user_count_source'),
                  'max_active_wire_requests_upper_bound': sum(worker['max_active_wire_requests'] for worker in workers),
                  'max_gate_waiting_users_upper_bound': sum(worker['max_gate_waiting_users'] for worker in workers),
                  'gate_wait_sample_size': gate['count'],
                  'gate_wait_ms': {'p50': gate['p50_ms'], 'p95': gate['p95_ms'], 'p99': gate['p99_ms'],
                                   'resolution_ms': 1, 'upper_bucket_ms': 120000},
                  'simulated_public_cache': {**workers[0]['simulated_public_cache'], 'counters': dict(simulation)} if workers else {},
                  'shared_pool_closed': all(worker['shared_pool_closed'] is True for worker in workers) if common and common.get('connection_model') == 'pooled' else None,
                  'browser_cache_hits': None, 'master': master,
                  'workers': [{'index': worker['configuration']['worker_index'], 'configuration': worker['configuration'],
                               'finished': worker['finished'], 'peak_virtual_users': worker['peak_virtual_users']}
                              for worker in workers],
                  'limitations': ['Worker active/waiting peaks are summed bounds, not synchronized observed peaks.',
                                  'Request, endpoint and journey percentiles are recomputed from merged raw integer-ms histograms.',
                                  'Gate wait percentiles use every completed gate acquisition, rounded/clamped to 1ms/120s; cancelled waits are excluded.',
                                  'Master user totals come from asynchronous actual worker reports, not the requested spawn target.',
                                  'Elapsed worker durations are not summed; the runner supplies the stage wall interval.']}
        master_warnings = master.get('generator_cpu_warnings') if worker_count > 1 else 0
        if type(master_warnings) is not int or master_warnings < 0:
            errors.append('Master CPU warning count is invalid.')
        else:
            result['generator_cpu_warnings'] += master_warnings
        if result['peak_virtual_users'] > result['started_virtual_users']:
            errors.append('Master user peak exceeds the workers\' definitive started user count.')
    result.update({'finished': not errors and len(workers) == worker_count,
                   'aggregation_complete': not errors and len(workers) == worker_count,
                   'aggregation_errors': errors, 'expected_worker_count': worker_count,
                   'observed_worker_count': len(workers), 'aggregate_max_inflight': max_inflight,
                   'worker_inflight_caps': caps})
    return result


def latest_metrics(path):
    if not path or not path.exists():
        return {}
    with path.open() as source:
        lines = source.readlines()
    workers = {}
    for line in reversed(lines):
        try:
            snapshot = json.loads(line)
            workers.setdefault(snapshot.get('pid', 0), snapshot)
        except ValueError:
            pass
    counters = {}
    for snapshot in workers.values():
        for key, count in snapshot.get('counters', {}).items():
            counters[key] = counters.get(key, 0) + count
    return {'workers': list(workers.values()), 'counters': counters}


def server_delta(before, after):
    old, new = before.get('counters', {}), after.get('counters', {})
    return {key: value - old.get(key, 0) for key, value in new.items() if value - old.get(key, 0)}


def process_metrics(process):
    if process is None:
        return None
    try:
        return {'pid': process.pid, 'rss_bytes': process.memory_info().rss,
                'cpu_percent': process.cpu_percent(), 'threads': process.num_threads(),
                'fds': process.num_fds() if hasattr(process, 'num_fds') else None}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {'pid': process.pid, 'unavailable': True}


def process_tree_metrics(process, tracked):
    """Sample the master and its children; summed RSS can count shared pages twice."""
    try:
        found = [process, *process.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        found = [process]
    samples = []
    for candidate in found:
        held = tracked.setdefault(candidate.pid, candidate)
        samples.append(process_metrics(held))
    return {'processes': samples, 'rss_bytes': sum(item.get('rss_bytes', 0) for item in samples),
            'cpu_percent': sum(item.get('cpu_percent', 0) for item in samples),
            'threads': sum(item.get('threads', 0) for item in samples),
            'fds': sum(item.get('fds') or 0 for item in samples)}


def signal_generator(generator, signum):
    try:
        os.killpg(generator.pid, signum)
    except ProcessLookupError:
        pass


def live_processes(tracked):
    living = []
    for held in tracked:
        try:
            if held.is_running() and held.status() != psutil.STATUS_ZOMBIE:
                living.append(held)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            # An unverified owned process cannot be treated as stopped.
            living.append(held)
    return living


def cleanup_workers(generator, tracked):
    remaining = live_processes(tracked.values())
    if remaining:
        signal_generator(generator, signal.SIGKILL)
        _gone, alive = psutil.wait_procs(remaining, timeout=3)
        return [held.pid for held in live_processes(alive)]
    return []


def stage_acceptance(protocol, target_users, max_failure_rate, max_api_p95_ms, aborted, exit_code):
    latency = protocol.get('request_latency', {})
    total = sum(latency.get(name, {}).get('count', 0) for name in ('successful', 'failed', 'expected_non_2xx'))
    failures = latency.get('failed', {}).get('count', 0)
    api = latency.get('api_user_successful', {})
    p95 = api.get('p95_ms')
    unavailable = protocol.get('user_counts', {}).get('auth_fixture_unavailable', 0)
    reasons = list(protocol.get('aggregation_errors', []))
    if unavailable:
        reasons.append(f'Authenticated account fixtures unavailable for {unavailable} requested users in total.')
    return {'max_failure_rate': max_failure_rate, 'max_api_success_p95_ms': max_api_p95_ms,
            'metrics_complete': protocol.get('aggregation_complete') is True and not unavailable,
            'incomplete_reasons': reasons, 'auth_fixture_unavailable_users': unavailable,
            'failure_rate': failures / total if total else None,
            'successful_api_under_100_ms_fraction': api.get('under_100_ms', 0) / api['count'] if api.get('count') else None,
            'includes_generator_queue': True,
            'passed': not aborted and not unavailable and exit_code == 0 and protocol.get('finished') is True
            and protocol.get('aggregation_complete') is True and total > 0 and failures / total <= max_failure_rate
            and p95 is not None and p95 <= max_api_p95_ms and protocol.get('peak_virtual_users', 0) >= target_users
            and protocol.get('generator_cpu_warnings', 0) == 0}


def stage_plan(raw):
    plan = []
    for item in raw.split(','):
        users, rate, seconds, model = item.split(':')
        stage = {'target_users': int(users), 'spawn_per_second': float(rate),
                 'run_seconds': float(seconds), 'connection_model': model}
        if min(stage['target_users'], stage['spawn_per_second'], stage['run_seconds']) <= 0 or model not in ('persistent', 'pooled'):
            raise ValueError('Stages must have positive users/rate/duration and persistent or pooled connections.')
        if stage['run_seconds'] <= stage['target_users'] / stage['spawn_per_second']:
            raise ValueError('Stage duration must include time at the target user count after ramp-up.')
        plan.append(stage)
    return plan


def locust_command(args, stage, number, directory, run_id=None, master_port=None):
    command = [args.locust_python, '-m', 'locust', '-f', str(HERE / 'locustfile.py'),
               '--host', args.origin, '--headless', '--users', str(stage['target_users']),
               '--spawn-rate', str(stage['spawn_per_second']), '--run-time', f"{math.ceil(stage['run_seconds'])}s",
               '--stop-timeout', '3', '--csv', str(directory / 'locust'), '--csv-full-history',
               '--html', str(directory / 'locust.html'), '--workload-seed', str(args.seed + number),
               '--workload-metrics-directory', str(directory), '--workload-max-inflight', str(args.max_inflight),
               '--workload-connection-model', stage['connection_model'], '--workload-think-min', str(args.think_min),
               '--workload-think-max', str(args.think_max), '--workload-auth-fraction', str(args.auth_fraction)]
    workers = getattr(args, 'workers', 1)
    if workers > 1:
        command.extend(('--processes', str(workers), '--expect-workers-max-wait', '15',
                        '--master-bind-host', '127.0.0.1', '--master-host', '127.0.0.1',
                        '--master-bind-port', str(master_port or 5557), '--master-port', str(master_port or 5557),
                        '--workload-worker-count', str(workers)))
    if run_id:
        command.extend(('--workload-run-id', run_id))
    if args.accounts:
        command.extend(('--workload-accounts-path', str(args.accounts)))
    if args.gateway_key_path:
        command.extend(('--workload-gateway-key-path', str(args.gateway_key_path)))
    if args.media:
        command.append('--workload-media')
    if args.simulate_public_cache:
        command.append('--workload-simulate-public-cache')
    return command


def run_stage(args, stage, number, server):
    directory = args.output_dir / f"stage-{number}-{stage['target_users']}-{stage['connection_model']}"
    directory.mkdir(parents=True, exist_ok=True)
    before = latest_metrics(args.server_metrics)
    run_id = uuid.uuid4().hex
    master_port = None
    if args.workers > 1:
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            master_port = reservation.getsockname()[1]
    command = locust_command(args, stage, number, directory, run_id, master_port)
    env = {**os.environ, 'COUCHSIDE_LOAD_ISOLATED': '1' if args.synthetic_identities else '0',
           'COUCHSIDE_LOAD_PROXY': '1' if args.synthetic_identities else '0',
           'COUCHSIDE_LOAD_SIMULATE_PUBLIC_CACHE': '1' if args.simulate_public_cache else '0'}
    samples, aborted, tracked, cleanup_remaining = [], None, {}, []
    with (directory / 'generator.log').open('w') as log:
        generator = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        process = psutil.Process(generator.pid)
        began = time.monotonic()
        began_utc = time.time()
        try:
            while generator.poll() is None:
                tree = process_tree_metrics(process, tracked) if args.workers > 1 else None
                generator_sample = next((item for item in tree['processes'] if item['pid'] == process.pid), None) if tree else process_metrics(process)
                sample = {'seconds': round(time.monotonic() - began, 3),
                          'server': process_metrics(server), 'generator': generator_sample,
                          'host_memory_percent': psutil.virtual_memory().percent}
                if tree:
                    sample['generator_tree'] = tree
                samples.append(sample)
                if sample['host_memory_percent'] >= args.abort_memory_percent:
                    aborted = 'Host memory reached the configured test limit.'
                if sample['server'] and sample['server'].get('threads', 0) >= args.abort_server_threads:
                    aborted = 'Server threads reached the configured test limit.'
                if sample['server'] and sample['server'].get('unavailable'):
                    aborted = 'The target server process stopped.'
                if aborted:
                    signal_generator(generator, signal.SIGINT)
                    break
                if time.monotonic() - began > stage['run_seconds'] + 30:
                    aborted = 'Generator exceeded the bounded test duration.'
                    signal_generator(generator, signal.SIGINT)
                    break
                time.sleep(1)
            try:
                generator.wait(timeout=15)
            except subprocess.TimeoutExpired:
                signal_generator(generator, signal.SIGKILL)
                generator.wait()
        finally:
            if generator.poll() is None:
                signal_generator(generator, signal.SIGKILL)
                generator.wait()
            had_remaining = bool(live_processes(tracked.values()))
            cleanup_remaining = cleanup_workers(generator, tracked)
            if had_remaining:
                aborted = aborted or 'Generator left live worker processes after shutdown.'
            if cleanup_remaining:
                aborted = 'Owned generator workers remain alive after bounded cleanup; no further stages may start.'
    time.sleep(1.1)
    after = latest_metrics(args.server_metrics)
    protocol = final_protocol(directory, run_id, args.workers, args.max_inflight)
    stats = directory / 'locust_stats.csv'
    rows = list(csv.DictReader(stats.open())) if stats.exists() else []
    aggregate = next((row for row in rows if row.get('Name') == 'Aggregated'), {})
    latency = protocol.get('request_latency', {})
    # The CSV is a periodic snapshot and can omit requests completed during shutdown.
    total = sum(latency.get(name, {}).get('count', 0)
                for name in ('successful', 'failed', 'expected_non_2xx'))
    failures = latency.get('failed', {}).get('count', 0)
    peak_users = protocol.get('peak_virtual_users',
                             max((s['virtual_users'] for s in protocol.get('samples', [])), default=0))
    if not total and not aborted:
        aborted = 'The load generator did not initialize or produce requests; see generator.log.'
    acceptance = stage_acceptance(protocol, stage['target_users'], args.max_failure_rate,
                                  args.max_api_p95_ms, aborted, generator.returncode)
    result = {**stage, 'actual_peak_users': peak_users, 'run_id': run_id,
              'generator_workers': args.workers, 'aggregate_max_inflight': args.max_inflight,
              'started_at': began_utc, 'ended_at': time.time(),
              'elapsed_seconds': time.monotonic() - began, 'aborted': aborted, 'exit_code': generator.returncode,
              'cleanup_remaining_worker_pids': cleanup_remaining,
              'request_totals': {'completed': total, 'failed': failures, 'source': 'final request events'},
              'locust_aggregate_periodic_snapshot': aggregate, 'protocol': protocol, 'resources': samples,
              'acceptance': acceptance,
              'server_counters': server_delta(before, after),
              'notes': ['Server counters are per-layer lookups, not one combined cache-hit ratio.',
                        'Server HTTP bytes are declared response body bytes; browser and generator bytes are measured separately.',
                        'Virtual users include idle and queued sessions. A pooled run does not test 10,000 physical browser connections.',
                        'Public cache simulation is explicitly labeled in protocol.configuration and '
                        'protocol.simulated_public_cache; it does not synthesize completed HTTP events.']}
    (directory / 'stage-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('target_users', 'actual_peak_users', 'connection_model', 'aborted', 'exit_code')}), flush=True)
    return result


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--locust-python', default=sys.executable)
    parser.add_argument('--server-pid', type=int)
    parser.add_argument('--server-metrics', type=Path)
    parser.add_argument('--accounts', type=Path)
    parser.add_argument('--stages', default='100:25:35:persistent,1000:100:35:persistent,10000:1000:45:pooled')
    parser.add_argument('--seed', type=int, default=20261002)
    parser.add_argument('--max-inflight', type=int, default=64)
    parser.add_argument('--workers', type=int, default=1,
                        help='Opt-in local Locust worker processes; --max-inflight remains one aggregate wire cap.')
    parser.add_argument('--think-min', type=float, default=3)
    parser.add_argument('--think-max', type=float, default=12)
    parser.add_argument('--auth-fraction', type=float, default=.2)
    parser.add_argument('--abort-server-threads', type=int, default=512)
    parser.add_argument('--abort-memory-percent', type=float, default=85)
    parser.add_argument('--synthetic-identities', action='store_true')
    parser.add_argument('--gateway-key-path', type=Path)
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--media', action='store_true')
    parser.add_argument('--simulate-public-cache', action='store_true',
                        help='Simulate per-user public comparison cache eligibility with metadata only; not browser cache measurements.')
    parser.add_argument('--max-failure-rate', type=float, default=.01)
    parser.add_argument('--max-api-p95-ms', type=float, default=100)
    args = parser.parse_args()
    try:
        inflight_caps(args.max_inflight, args.workers)
    except ValueError as error:
        parser.error(str(error))
    if args.workers > 1 and os.name == 'nt':
        parser.error('Local Locust worker processes require a platform with fork support.')
    try:
        local = urlsplit(args.origin).hostname == 'localhost' or ipaddress.ip_address(urlsplit(args.origin).hostname).is_loopback
    except ValueError:
        local = False
    if not local and not args.allow_remote:
        parser.error('Use --allow-remote only with an explicitly chosen isolated target.')
    if args.synthetic_identities and not local and not args.gateway_key_path:
        parser.error('Synthetic client identities are supported only on the isolated loopback server.')
    if args.gateway_key_path:
        from gateway import key_from
        key_from(args.gateway_key_path, args.origin)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    server = psutil.Process(args.server_pid) if args.server_pid else None
    metadata = {'schema': 1, 'origin': args.origin, 'seed': args.seed,
                'host_cpu_count': psutil.cpu_count(), 'host_memory_bytes': psutil.virtual_memory().total,
                'local_test': local, 'max_wire_requests_aggregate': args.max_inflight,
                'generator_workers': args.workers,
                'worker_inflight_caps': inflight_caps(args.max_inflight, args.workers),
                'simulate_public_cache': args.simulate_public_cache,
                'production_manifest': {'shared_vcpus': 1, 'shared_ram_mb': 3072},
                'outbound_mode': 'Read the isolated-server startup record; blocked attempts are distinct from real requests.',
                'stages': []}
    if args.workers == 1:
        metadata['max_wire_requests_per_worker'] = args.max_inflight
    for number, stage in enumerate(stage_plan(args.stages), 1):
        result = run_stage(args, stage, number, server)
        metadata['stages'].append(result)
        (args.output_dir / 'load-results.json').write_text(json.dumps(metadata, indent=2) + '\n')
        if result['cleanup_remaining_worker_pids']:
            break
        # Close aborted users' sockets before starting the next independently labeled stage.
        time.sleep(3)
    return 0 if all(stage['acceptance']['passed'] for stage in metadata['stages']) else 1


if __name__ == '__main__':
    sys.exit(main())
