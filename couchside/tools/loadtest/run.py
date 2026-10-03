"""Run staged Locust traffic and save raw metrics, resources, and server-cache deltas."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import urlsplit
import csv
import ipaddress
import json
import math
import os
import signal
import subprocess
import sys
import time

import psutil

HERE = Path(__file__).resolve().parent


def latest_metrics(path):
    if not path or not path.exists():
        return {}
    with path.open() as source:
        lines = source.readlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            pass
    return {}


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


def run_stage(args, stage, number, server):
    directory = args.output_dir / f"stage-{number}-{stage['target_users']}-{stage['connection_model']}"
    directory.mkdir(parents=True, exist_ok=True)
    before = latest_metrics(args.server_metrics)
    command = [args.locust_python, '-m', 'locust', '-f', str(HERE / 'locustfile.py'),
               '--host', args.origin, '--headless', '--users', str(stage['target_users']),
               '--spawn-rate', str(stage['spawn_per_second']), '--run-time', f"{math.ceil(stage['run_seconds'])}s",
               '--stop-timeout', '3', '--csv', str(directory / 'locust'), '--csv-full-history',
               '--html', str(directory / 'locust.html'), '--workload-seed', str(args.seed + number),
               '--workload-metrics-directory', str(directory), '--workload-max-inflight', str(args.max_inflight),
               '--workload-connection-model', stage['connection_model'], '--workload-think-min', str(args.think_min),
               '--workload-think-max', str(args.think_max), '--workload-auth-fraction', str(args.auth_fraction)]
    if args.accounts:
        command.extend(('--workload-accounts-path', str(args.accounts)))
    if args.media:
        command.append('--workload-media')
    env = {**os.environ, 'COUCHSIDE_LOAD_ISOLATED': '1' if args.synthetic_identities else '0',
           'COUCHSIDE_LOAD_PROXY': '1' if args.synthetic_identities else '0'}
    samples, aborted = [], None
    with (directory / 'generator.log').open('w') as log:
        generator = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        process = psutil.Process(generator.pid)
        began = time.monotonic()
        try:
            while generator.poll() is None:
                sample = {'seconds': round(time.monotonic() - began, 3),
                          'server': process_metrics(server), 'generator': process_metrics(process),
                          'host_memory_percent': psutil.virtual_memory().percent}
                samples.append(sample)
                if sample['host_memory_percent'] >= args.abort_memory_percent:
                    aborted = 'Host memory reached the configured test limit.'
                if sample['server'] and sample['server'].get('threads', 0) >= args.abort_server_threads:
                    aborted = 'Server threads reached the configured test limit.'
                if sample['server'] and sample['server'].get('unavailable'):
                    aborted = 'The target server process stopped.'
                if aborted:
                    generator.send_signal(signal.SIGINT)
                    break
                if time.monotonic() - began > stage['run_seconds'] + 30:
                    aborted = 'Generator exceeded the bounded test duration.'
                    generator.send_signal(signal.SIGINT)
                    break
                time.sleep(1)
            try:
                generator.wait(timeout=15)
            except subprocess.TimeoutExpired:
                generator.kill()
                generator.wait()
        finally:
            if generator.poll() is None:
                generator.kill()
                generator.wait()
    time.sleep(1.1)
    after = latest_metrics(args.server_metrics)
    supplemental = directory / 'protocol-worker-0.json'
    protocol = json.loads(supplemental.read_text()) if supplemental.exists() else {}
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
    api_p95 = protocol.get('request_latency', {}).get('api_successful', {}).get('p95_ms')
    acceptance = {'max_failure_rate': args.max_failure_rate, 'max_api_success_p95_ms': args.max_api_p95_ms,
                  'failure_rate': failures / total if total else None,
                  'passed': not aborted and protocol.get('finished') is True
                  and total > 0 and failures / total <= args.max_failure_rate
                  and api_p95 is not None and api_p95 <= args.max_api_p95_ms
                  and peak_users >= stage['target_users']
                  and protocol.get('generator_cpu_warnings', 0) == 0}
    result = {**stage, 'actual_peak_users': peak_users,
              'elapsed_seconds': time.monotonic() - began, 'aborted': aborted, 'exit_code': generator.returncode,
              'request_totals': {'completed': total, 'failed': failures, 'source': 'final request events'},
              'locust_aggregate_periodic_snapshot': aggregate, 'protocol': protocol, 'resources': samples,
              'acceptance': acceptance,
              'server_counters': server_delta(before, after),
              'notes': ['Server counters are per-layer lookups, not one combined cache-hit ratio.',
                        'Server HTTP bytes are declared response body bytes; browser and generator bytes are measured separately.',
                        'Virtual users include idle and queued sessions. A pooled run does not test 10,000 physical browser connections.']}
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
    parser.add_argument('--think-min', type=float, default=3)
    parser.add_argument('--think-max', type=float, default=12)
    parser.add_argument('--auth-fraction', type=float, default=.2)
    parser.add_argument('--abort-server-threads', type=int, default=512)
    parser.add_argument('--abort-memory-percent', type=float, default=85)
    parser.add_argument('--synthetic-identities', action='store_true')
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--media', action='store_true')
    parser.add_argument('--max-failure-rate', type=float, default=.01)
    parser.add_argument('--max-api-p95-ms', type=float, default=1000)
    args = parser.parse_args()
    try:
        local = urlsplit(args.origin).hostname == 'localhost' or ipaddress.ip_address(urlsplit(args.origin).hostname).is_loopback
    except ValueError:
        local = False
    if not local and not args.allow_remote:
        parser.error('Use --allow-remote only with an explicitly chosen isolated target.')
    if args.synthetic_identities and not local:
        parser.error('Synthetic client identities are supported only on the isolated loopback server.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    server = psutil.Process(args.server_pid) if args.server_pid else None
    metadata = {'schema': 1, 'origin': args.origin, 'seed': args.seed,
                'host_cpu_count': psutil.cpu_count(), 'host_memory_bytes': psutil.virtual_memory().total,
                'local_test': local, 'max_wire_requests_per_worker': args.max_inflight,
                'production_manifest': {'shared_vcpus': 1, 'shared_ram_mb': 3072},
                'outbound_mode': 'Read the isolated-server startup record; blocked attempts are distinct from real requests.',
                'stages': []}
    for number, stage in enumerate(stage_plan(args.stages), 1):
        result = run_stage(args, stage, number, server)
        metadata['stages'].append(result)
        (args.output_dir / 'load-results.json').write_text(json.dumps(metadata, indent=2) + '\n')
        # Close aborted users' sockets before starting the next independently labeled stage.
        time.sleep(3)
    return 0 if all(stage['acceptance']['passed'] for stage in metadata['stages']) else 1


if __name__ == '__main__':
    sys.exit(main())
