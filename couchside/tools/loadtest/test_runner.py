"""Local-worker orchestration and final-event aggregation; no HTTP traffic."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import signal
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import configargparse
import psutil
from locust.runners import WorkerRunner

import locustfile
from protocol_metrics import MasterMetrics, ProtocolMetrics
import run
from workload import Configuration


class WorkerConfiguration(unittest.TestCase):
    def arguments(self):
        return SimpleNamespace(locust_python='/isolated/python', origin='http://127.0.0.1:18120',
                               seed=123, max_inflight=7, workers=1, think_min=3, think_max=12,
                               auth_fraction=0, accounts=None, gateway_key_path=None,
                               media=False, simulate_public_cache=False)

    def test_one_worker_keeps_existing_command_and_multiple_workers_are_explicit(self):
        arguments = self.arguments()
        stage = {'target_users': 12, 'spawn_per_second': 6, 'run_seconds': 5, 'connection_model': 'pooled'}
        ordinary = run.locust_command(arguments, stage, 1, Path('/isolated/results'))
        for flag in ('--processes', '--workload-worker-count', '--master-bind-host', '--workload-run-id'):
            self.assertNotIn(flag, ordinary)
        arguments.workers = 3
        command = run.locust_command(arguments, stage, 1, Path('/isolated/results'), 'fresh-run', 19557)
        for flag, value in (('--processes', '3'), ('--workload-worker-count', '3'),
                            ('--workload-max-inflight', '7'), ('--master-bind-host', '127.0.0.1'),
                            ('--master-bind-port', '19557'), ('--master-port', '19557'),
                            ('--expect-workers-max-wait', '15'), ('--workload-run-id', 'fresh-run')):
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_uneven_caps_and_unique_worker_ordinals_share_one_bounded_budget(self):
        caps = run.inflight_caps(7, 3)
        self.assertEqual(caps, [3, 2, 2])
        self.assertEqual(sum(caps), 7)
        configs = [Configuration(worker_index=index, worker_count=3, max_inflight=7) for index in range(3)]
        self.assertEqual([config.worker_inflight() for config in configs], caps)
        ordinals = [ordinal * 3 + config.worker_index for config in configs for ordinal in range(5)]
        self.assertEqual(len(set(ordinals)), 15)
        for total, workers in ((1, 2), (7, 0), (0, 1)):
            with self.assertRaises(ValueError):
                run.inflight_caps(total, workers)
        with self.assertRaises(ValueError):
            Configuration(worker_count=3, max_inflight=2).validate('http://127.0.0.1')

    def test_worker_uses_locust_assigned_index_and_partitioned_cap(self):
        parser = configargparse.ArgumentParser()
        locustfile.add_options(parser)
        with patch.dict('os.environ', {}, clear=True):
            parsed = parser.parse_args(['--workload-worker-count', '3', '--workload-max-inflight', '7',
                                        '--workload-worker-index', '0', '--workload-run-id', 'fresh-run'])
            runner = WorkerRunner.__new__(WorkerRunner)
            runner.greenlet = None
            runner.worker_index = 2
            environment = SimpleNamespace(parsed_options=parsed, runner=runner, host='http://127.0.0.1')
            config = locustfile.configuration(environment)
        self.assertEqual((config.worker_index, config.worker_count, config.max_inflight, config.run_id),
                         (2, 3, 2, 'fresh-run'))

    def test_global_spawn_event_does_not_become_each_workers_peak(self):
        metrics = ProtocolMetrics(Configuration())
        with patch.object(locustfile, 'RUNTIME', metrics), patch.object(locustfile, 'MASTER', None), \
                patch.object(locustfile, 'ENVIRONMENT', SimpleNamespace(runner=SimpleNamespace(user_count=4))), \
                patch.object(locustfile, 'WorkerRunner', SimpleNamespace):
            locustfile.spawned_users(12)
        self.assertEqual(metrics.peak_virtual_users, 4)


class FinalAggregation(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.config = Configuration(worker_count=2, max_inflight=7, run_id='fresh-run',
                                    connection_model='pooled', metrics_directory=str(self.directory))
        self.metrics = []
        for index, histogram in enumerate(({1: 99, 1000: 1}, {800: 900})):
            metrics = ProtocolMetrics(replace(self.config, worker_index=index, max_inflight=(4, 3)[index]))
            metrics.latencies['successful'] = Counter(histogram)
            metrics.latencies['api_successful'] = Counter(histogram)
            metrics.latencies['api_user_successful'] = Counter(histogram)
            metrics.endpoints['home/feed'] = Counter(histogram)
            metrics.journey_latencies['home'] = Counter({900: index + 1})
            metrics.journeys['home'] = index + 2
            metrics.gate_wait_histogram = Counter({index: sum(histogram.values())})
            metrics.requests = sum(histogram.values())
            metrics.statuses['200'] = metrics.requests
            metrics.users['guest'] = index + 3
            metrics.peak_virtual_users = index + 3
            metrics.peak_active = (4, 3)[index]
            metrics.peak_waiting = index + 10
            metrics.stopped, metrics.pool_closed = True, True
            metrics.write()
            self.metrics.append(metrics)
        self.master = MasterMetrics(self.config)
        for index in range(2):
            self.master.report(f'client-{index}', {'run_id': 'fresh-run', 'worker_count': 2,
                                                  'worker_index': index, 'user_count': 0,
                                                  'max_inflight': (4, 3)[index],
                                                  'finished': True, 'shared_pool_closed': True})
        self.master.stopped, self.master.peak_virtual_users = True, 7
        self.master.write()

    def aggregate(self):
        return run.final_protocol(self.directory, 'fresh-run', 2, 7)

    def mutate(self, name, change):
        path = self.directory / name
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_skewed_histograms_are_merged_before_quantiles_and_peaks_are_bounds(self):
        result = self.aggregate()
        self.assertTrue(result['aggregation_complete'], result['aggregation_errors'])
        self.assertEqual(result['request_latency']['api_user_successful']['p95_ms'], 800)
        self.assertEqual(result['endpoint_user_latency']['home/feed']['count'], 1000)
        self.assertEqual(result['completed_journey_latency']['home']['count'], 3)
        self.assertEqual(result['gate_wait_sample_size'], 1000)
        self.assertEqual(result['gate_wait_ms']['p95'], 1)
        self.assertEqual(result['definitive_request_counts']['total'], 1000)
        self.assertEqual(result['started_virtual_users'], 7)
        self.assertEqual(result['peak_virtual_users'], 7)
        self.assertEqual(result['max_active_wire_requests_upper_bound'], 7)
        self.assertEqual(result['max_gate_waiting_users_upper_bound'], 21)
        self.assertNotIn('max_active_wire_requests', result)
        self.assertNotIn('elapsed_seconds', result)

    def test_retry_transport_and_expected_401_events_keep_separate_counts(self):
        metrics = self.metrics[1]
        metrics.latencies['failed'][20000] = 2
        metrics.latencies['expected_non_2xx'][11] = 3
        metrics.statuses.update({'0': 2, '401_expected': 3})
        metrics.requests += 5
        metrics.retries = 2
        metrics.generator_cpu_warnings = 1
        metrics.write()
        result = self.aggregate()
        self.assertTrue(result['aggregation_complete'], result['aggregation_errors'])
        self.assertEqual(result['definitive_request_counts'], {'total': 1005, 'successful_2xx': 1000,
                         'failed': 2, 'expected_non_2xx': 3, 'api_successful_2xx': 1000})
        self.assertEqual(result['retries'], 2)
        self.assertEqual(result['generator_cpu_warnings'], 1)

    def test_missing_multiworker_authenticated_fixtures_make_the_requested_mix_incomplete(self):
        for metrics, count in zip(self.metrics, (1, 2)):
            metrics.users['auth_fixture_unavailable'] = count
            metrics.write()
        result = self.aggregate()
        self.assertFalse(result['aggregation_complete'])
        self.assertEqual(result['user_counts']['auth_fixture_unavailable'], 3)
        self.assertTrue(any('1 requested users' in reason for reason in result['aggregation_errors']))
        self.assertTrue(any('2 requested users' in reason for reason in result['aggregation_errors']))
        acceptance = run.stage_acceptance(result, 7, .01, 1000, None, 0)
        self.assertFalse(acceptance['passed'])
        self.assertEqual(acceptance['auth_fixture_unavailable_users'], 3)
        self.assertTrue(any('3 requested users in total' in reason for reason in acceptance['incomplete_reasons']))
        # Acceptance also guards independently if a caller supplies a legacy or
        # incorrectly marked-complete summary rather than final_protocol's output.
        result.update(aggregation_complete=True, finished=True, aggregation_errors=[])
        self.assertFalse(run.stage_acceptance(result, 7, .01, 1000, None, 0)['passed'])

    def test_missing_single_worker_authenticated_fixture_cannot_certify_guest_substitution(self):
        directory = self.directory / 'single-missing-auth'
        config = Configuration(metrics_directory=str(directory), run_id='single-auth', auth_fraction=.2)
        metrics = ProtocolMetrics(config)
        for name in ('successful', 'api_successful', 'api_user_successful'):
            metrics.latencies[name][1] = 1
        metrics.endpoints['home/feed'] = Counter({1: 1})
        metrics.statuses['200'] = metrics.requests = 1
        metrics.users.update(guest=1, auth_fixture_unavailable=1)
        metrics.peak_virtual_users = 1
        metrics.stopped = True
        metrics.write()
        result = run.final_protocol(directory, 'single-auth', 1, 64)
        self.assertEqual(result['definitive_request_counts']['total'], 1)
        self.assertFalse(result['aggregation_complete'])
        self.assertTrue(any('1 requested users' in reason for reason in result['aggregation_errors']))
        acceptance = run.stage_acceptance(result, 1, .01, 100, None, 0)
        self.assertFalse(acceptance['passed'])
        self.assertEqual(acceptance['auth_fixture_unavailable_users'], 1)

    def test_missing_worker_is_incomplete_and_keeps_partial_events_explicit(self):
        (self.directory / 'protocol-worker-1.json').unlink()
        result = self.aggregate()
        self.assertFalse(result['finished'])
        self.assertFalse(result['aggregation_complete'])
        self.assertEqual(result['observed_worker_count'], 1)
        self.assertEqual(result['definitive_request_counts']['total'], 100)

    def test_stale_unfinished_malformed_and_inconsistent_workers_cannot_pass(self):
        changes = [lambda value: value['configuration'].update(run_id='stale'),
                   lambda value: value.update(finished=False),
                   lambda value: value.update(shared_pool_closed=False),
                   lambda value: value['configuration'].update(seed=4),
                   lambda value: value['configuration'].update(worker_index=0),
                   lambda value: value['configuration'].update(max_inflight=7),
                   lambda value: value['histograms']['request_latency']['successful'].update({'800': -1}),
                   lambda value: value['request_latency']['successful'].update(count=1)]
        for change in changes:
            with self.subTest(change=change):
                self.metrics[1].write()
                self.mutate('protocol-worker-1.json', change)
                result = self.aggregate()
                self.assertFalse(result['aggregation_complete'])
                self.assertTrue(result['aggregation_errors'])

    def test_missing_stale_malformed_or_duplicate_master_roster_cannot_pass(self):
        changes = [lambda value: value.update(run_id='stale'),
                   lambda value: value.update(finished=False),
                   lambda value: value.update(current_users=1),
                   lambda value: value.update(worker_clients={'a': 0, 'b': 0}),
                   lambda value: value.update(worker_clients={'a': 0, 'b': 'bad'}),
                   lambda value: value['worker_reports'].pop('client-1'),
                   lambda value: value.pop('peak_virtual_users'),
                   lambda value: value.pop('generator_cpu_warnings'),
                   lambda value: value.update(peak_virtual_users=999),
                   lambda value: value['configuration'].update(seed=4)]
        for change in changes:
            with self.subTest(change=change):
                self.master.write()
                self.mutate('protocol-master.json', change)
                self.assertFalse(self.aggregate()['aggregation_complete'])
        (self.directory / 'protocol-master.json').unlink()
        self.assertFalse(self.aggregate()['aggregation_complete'])

    def test_master_event_uses_actual_reported_users_instead_of_spawn_target(self):
        runner = SimpleNamespace(user_count=5, clients=SimpleNamespace(all=[]))
        with patch.object(locustfile, 'RUNTIME', None), patch.object(locustfile, 'MASTER', self.master), \
                patch.object(locustfile, 'ENVIRONMENT', SimpleNamespace(runner=runner)):
            self.master.stopped = False
            self.master.peak_virtual_users = 0
            locustfile.spawned_users(12)
        self.master.stopped, self.master.current_users = True, 0
        self.master.write()
        result = self.aggregate()
        self.assertTrue(result['aggregation_complete'], result['aggregation_errors'])
        self.assertEqual(result['peak_virtual_users'], 5)
        self.assertFalse(run.stage_acceptance(result, 12, .01, 1000, None, 0)['passed'])

    def test_one_worker_preserves_existing_gate_percentiles_and_peak_fields(self):
        temporary = Path(self.temporary.name) / 'single'
        config = Configuration(metrics_directory=str(temporary), run_id='single')
        metrics = ProtocolMetrics(config)
        metrics.stopped = True
        metrics.gate_wait.extend([.123, .456])
        metrics.peak_active = 1
        metrics.write()
        result = run.final_protocol(temporary, 'single', 1, 64)
        self.assertTrue(result['aggregation_complete'], result['aggregation_errors'])
        self.assertEqual(result['gate_wait_ms'], metrics.summary()['gate_wait_ms'])
        self.assertEqual(result['max_active_wire_requests'], 1)

    def test_process_tree_resources_and_owned_group_signals_include_children(self):
        child = SimpleNamespace(pid=2)
        master = SimpleNamespace(pid=1, children=lambda recursive: [child])
        def sample(process):
            return {'pid': process.pid, 'rss_bytes': 100, 'cpu_percent': 12, 'threads': 2, 'fds': 3}
        with patch.object(run, 'process_metrics', side_effect=sample):
            result = run.process_tree_metrics(master, {})
        self.assertEqual((result['rss_bytes'], result['cpu_percent'], result['threads'], result['fds']), (200, 24, 4, 6))
        with patch.object(run.os, 'killpg') as kill:
            run.signal_generator(master, signal.SIGINT)
        kill.assert_called_once_with(1, signal.SIGINT)

    def test_process_exit_race_is_safe_and_unresolved_cleanup_is_recorded(self):
        vanished = SimpleNamespace(pid=2, is_running=lambda: True,
                                   status=lambda: (_ for _ in ()).throw(psutil.NoSuchProcess(2)))
        alive = SimpleNamespace(pid=3, is_running=lambda: True, status=lambda: psutil.STATUS_RUNNING)
        self.assertEqual(run.live_processes([vanished, alive]), [alive])
        with patch.object(run, 'signal_generator') as sent, \
                patch.object(run.psutil, 'wait_procs', return_value=([], [alive])):
            remaining = run.cleanup_workers(SimpleNamespace(pid=1), {2: vanished, 3: alive})
        self.assertEqual(remaining, [3])
        sent.assert_called_once()

    def test_abnormal_master_exit_cannot_pass_complete_partial_metrics(self):
        result = self.aggregate()
        self.assertTrue(run.stage_acceptance(result, 7, .01, 1000, None, 0)['passed'])
        self.assertFalse(run.stage_acceptance(result, 7, .01, 1000, None, 1)['passed'])

    def test_owned_workers_remaining_after_cleanup_prevent_the_next_stage(self):
        outcome = {'cleanup_remaining_worker_pids': [3], 'acceptance': {'passed': False}}
        arguments = ['run.py', '--origin', 'http://127.0.0.1:18120', '--output-dir', str(self.directory / 'blocked'),
                     '--workers', '2', '--stages', '2:2:3:pooled,4:4:3:pooled']
        with patch.object(run.sys, 'argv', arguments), patch.object(run, 'run_stage', return_value=outcome) as stage:
            self.assertEqual(run.main(), 1)
        self.assertEqual(stage.call_count, 1)

    def test_final_report_barrier_timeout_is_incomplete_and_stops_replacement_spawning(self):
        master = SimpleNamespace(stopping=False, reports={}, config=SimpleNamespace(worker_count=2),
                                 errors=[], capture=lambda environment: None, write=lambda: None)
        runner = SimpleNamespace(update_state=lambda state: None, send_message=lambda name: None)
        environment = SimpleNamespace(runner=runner, stop_timeout=0)
        with patch.object(locustfile, 'MASTER', master), \
                patch.object(locustfile.time, 'monotonic', side_effect=[0, 6]):
            locustfile.drain_worker_reports(environment)
        self.assertTrue(master.stopping)
        self.assertTrue(master.errors)


if __name__ == '__main__':
    unittest.main()
