"""Private viewing state survives restarts, conflicts, Undo, and catalogue churn."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import tempfile
import threading
from unittest import TestCase, main

from backend.accounts import AccountError, AccountService, SESSION_SECONDS
from backend.tracking import TrackingService
from backend.tracking_catalogue import released
from backend.live import trim_episode_ratings


STATE = {'version': 3, 'profile': [{'id': 10, 'weight': .7}], 'saved': [{'id': 20}],
         'settings': {'known_min': 85}, 'onboarded': True}
PASSWORD = 'a correct horse battery staple'


class TrackingTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'private' / 'accounts.sqlite3'
        self.now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc).timestamp()
        self.accounts = AccountService(self.path, clock=lambda: self.now, validate_domain=False)
        self.token, self.account = self.accounts.signup('jonathanjamesm66@gmail.com', PASSWORD, deepcopy(STATE))
        self.allowed = {self.account['user']['id']}
        self.calls = 0
        self.serial = 0
        self.catalogues = {
            10: {'id': 10, 'revision': 'catalogue-10-v1', 'expiresAt': self.now + 1000, 'ended': True, 'episodes': [
                {'id': 101, 'season': 1, 'number': 1, 'airdate': '2026-10-01'},
                {'id': 102, 'season': 1, 'number': 2, 'airdate': '2026-10-02'},
                {'id': 103, 'season': 1, 'number': 3, 'airdate': '2026-10-03', 'airstamp': '2026-10-03T17:00:00+00:00'},
                {'id': 104, 'season': 1, 'number': 4, 'airdate': '2026-10-04'},
                {'id': 105, 'season': 1, 'number': 5, 'airdate': '2026-10-03'},
                {'id': 106, 'season': 1, 'number': 6, 'airdate': ''},
            ]},
            20: {'id': 20, 'revision': 'catalogue-20-v1', 'expiresAt': self.now + 1000, 'ended': True, 'episodes': [
                {'id': 201, 'season': 1, 'number': 1, 'airdate': '2026-10-01'},
                {'id': 202, 'season': 1, 'number': 2, 'airdate': '2026-10-02'},
            ]},
        }
        self.service = self.reopen()

    def provider(self, show_id):
        self.calls += 1
        if show_id not in self.catalogues:
            raise AccountError(404, 'That show is not in this catalog.')
        return deepcopy(self.catalogues[show_id])

    def reopen(self):
        return TrackingService(self.accounts, self.provider, lambda connection, row: row['id'] in self.allowed)

    def payload(self, action, show_id=10, **details):
        self.serial += 1
        return {'operation_id': f'operation-{self.serial:04}', 'base_revision': self.service.read(self.token)['tracking_revision'],
                'show_id': show_id, 'action': action, **details}

    def apply(self, action, show_id=10, **details):
        return self.service.mutate(self.token, self.account['csrf'], self.payload(action, show_id, **details))

    def error(self, status, operation):
        with self.assertRaises(AccountError) as caught:
            operation()
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def record(self, result, show_id=10):
        return next(item for item in result['tracking'] if item['show_id'] == show_id)

    def marks(self, result, show_id=10):
        return {item['episode_id']: item['watched'] for item in self.record(result, show_id)['episode_states']}

    def test_empty_and_durable_tracking_are_independent_of_account_preferences(self):
        empty = self.service.read(self.token)
        self.assertEqual(empty, {'schema_version': 1, 'user_id': self.account['user']['id'], 'tracking_revision': 0, 'tracking': []})
        started = self.apply('intent', intent='watching')
        self.assertEqual(started['tracking_revision'], 1)
        self.assertFalse(self.record(started)['progress_known'])
        self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        self.accounts = AccountService(self.path, clock=lambda: self.now, validate_domain=False)
        self.service = self.reopen()
        self.assertEqual(self.marks(self.service.read(self.token)), {101: True})
        self.assertEqual(self.accounts.session(self.token)['state'], STATE)
        self.assertEqual(self.accounts.session(self.token)['revision'], 0)

    def test_authentication_csrf_eligibility_and_expiry_fail_before_catalogue_work(self):
        body = self.payload('intent', intent='watching')
        self.error(401, lambda: self.service.read(''))
        self.error(401, lambda: self.service.mutate('', self.account['csrf'], body))
        self.error(403, lambda: self.service.mutate(self.token, 'wrong', body))
        self.allowed.clear()
        self.error(403, lambda: self.service.read(self.token))
        self.error(403, lambda: self.service.catalogue(self.token, 10))
        self.error(403, lambda: self.service.mutate(self.token, self.account['csrf'], body))
        self.allowed.add(self.account['user']['id'])
        self.now += SESSION_SECONDS
        self.error(401, lambda: self.service.read(self.token))
        self.assertEqual(self.calls, 0)

    def test_account_isolation_is_derived_from_session_not_payload(self):
        self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        second_token, second = self.accounts.signup('second@gmail.com', PASSWORD, deepcopy(STATE))
        self.allowed.add(second['user']['id'])
        self.assertEqual(self.service.read(second_token)['tracking'], [])
        body = {**self.payload('intent', intent='paused'), 'user_id': self.account['user']['id']}
        self.error(400, lambda: self.service.mutate(second_token, second['csrf'], body))
        body.pop('user_id')
        body['base_revision'] = 0
        changed = self.service.mutate(second_token, second['csrf'], body)
        self.assertEqual(changed['user_id'], second['user']['id'])
        self.assertEqual(self.record(self.service.read(self.token))['intent'], 'watching')
        self.error(403, lambda: self.service.mutate(second_token, self.account['csrf'], body))

    def test_known_show_and_stable_episode_ownership_are_validated(self):
        self.error(404, lambda: self.apply('intent', show_id=999, intent='watching'))
        for episode_id in (201, 999):
            self.error(400, lambda: self.apply('episode', episode_id=episode_id, watched=True, establish_progress=True))
        for show_id in (True, 0, -1, 2 ** 53, '10'):
            body = {**self.payload('intent', intent='watching'), 'show_id': show_id}
            self.error(400, lambda: self.service.mutate(self.token, self.account['csrf'], body))
        self.assertEqual(self.service.read(self.token)['tracking'], [])

    def test_individual_marks_preserve_gaps_and_false_corrections(self):
        self.error(400, lambda: self.apply('episode', episode_id=103, watched=True))
        self.apply('episode', episode_id=103, watched=True, establish_progress=True)
        self.apply('episode', episode_id=101, watched=True)
        corrected = self.apply('episode', episode_id=101, watched=False)
        self.assertEqual(self.marks(corrected), {101: False, 103: True})
        self.assertTrue(self.record(corrected)['progress_known'])
        for episode_id in (104, 105, 106):
            self.error(400, lambda: self.apply('episode', episode_id=episode_id, watched=True))

    def test_explicit_unwatched_state_is_durable_even_without_an_earlier_true_mark(self):
        known = self.apply('intent', intent='watching', progress_known=True)
        stale = self.payload('episode', episode_id=101, watched=True)
        corrected = self.apply('episode', episode_id=101, watched=False)
        self.assertEqual(self.marks(corrected), {101: False})
        self.assertEqual(corrected['tracking_revision'], known['tracking_revision'] + 1)
        self.error(409, lambda: self.service.mutate(self.token, self.account['csrf'], stale))
        self.service = self.reopen()
        self.assertEqual(self.marks(self.service.read(self.token)), {101: False})

    def test_all_and_exact_replace_use_the_finite_released_snapshot(self):
        watched = self.apply('all', catalogue_revision='catalogue-10-v1')
        self.assertEqual(self.marks(watched), {101: True, 102: True, 103: True})
        self.assertEqual(self.record(watched)['intent'], 'watching', 'uncertain releases must not establish exact Finished')
        earlier = self.apply('replace', through_episode_id=101, catalogue_revision='catalogue-10-v1')
        self.assertEqual(self.marks(earlier), {101: True, 102: False, 103: False})
        empty = self.apply('replace', through_episode_id=None, catalogue_revision='catalogue-10-v1')
        self.assertEqual(self.marks(empty), {101: False, 102: False, 103: False})
        self.assertTrue(self.record(empty)['progress_known'])
        self.error(400, lambda: self.apply('replace', through_episode_id=201, catalogue_revision='catalogue-10-v1'))
        self.error(400, lambda: self.apply('replace', through_episode_id=104, catalogue_revision='catalogue-10-v1'))

    def test_stale_or_changed_catalogue_refuses_bulk_without_a_partial_commit(self):
        for changes, requested in (({}, 'wrong-revision'), ({'expiresAt': self.now}, 'catalogue-10-v1'),
                                   ({'complete': False}, 'catalogue-10-v1')):
            with self.subTest(changes=changes, requested=requested):
                original = deepcopy(self.catalogues[10])
                self.catalogues[10].update(changes)
                exc = self.error(409, lambda: self.apply('all', catalogue_revision=requested))
                self.assertTrue(exc.data['catalogue_changed'])
                self.assertEqual(exc.data['tracking'], [])
                self.assertEqual(exc.data['tracking_revision'], 0)
                self.catalogues[10] = original

    def test_finished_unknown_does_not_invent_marks_and_exact_finished_requires_all(self):
        unknown = self.apply('intent', intent='completed', progress_known=False)
        self.assertFalse(self.record(unknown)['progress_known'])
        self.assertEqual(self.marks(unknown), {})
        exact = self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        self.assertEqual(self.record(exact)['intent'], 'watching')
        self.error(400, lambda: self.apply('intent', intent='completed', progress_known=True))
        finished = self.apply('all', show_id=20, catalogue_revision='catalogue-20-v1')
        self.assertEqual(self.record(finished, 20)['intent'], 'completed')
        self.apply('episode', show_id=20, episode_id=201, watched=False)
        self.assertEqual(self.record(self.service.read(self.token), 20)['intent'], 'watching')

    def test_pausing_dropping_and_bookmark_changes_do_not_erase_episode_history(self):
        self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        for intent in ('paused', 'dropped', 'watching'):
            result = self.apply('intent', intent=intent)
            self.assertEqual(self.marks(result), {101: True})
        self.accounts.save(self.token, self.account['csrf'], {**STATE, 'saved': []}, 0)
        self.assertEqual(self.marks(self.service.read(self.token)), {101: True})

    def test_stale_writes_receive_current_snapshot_and_cannot_resurrect_removed_marks(self):
        stale = self.payload('episode', episode_id=101, watched=True, establish_progress=True)
        changed = self.apply('episode', episode_id=103, watched=True, establish_progress=True)
        exc = self.error(409, lambda: self.service.mutate(self.token, self.account['csrf'], stale))
        self.assertEqual(exc.data['tracking'], changed['tracking'])
        self.assertEqual(exc.data['tracking_revision'], changed['tracking_revision'])
        old = self.payload('episode', episode_id=103, watched=True)
        removed = self.apply('remove')
        self.assertTrue(self.record(removed)['deleted'])
        self.assertEqual(self.marks(removed), {103: False})
        self.error(409, lambda: self.service.mutate(self.token, self.account['csrf'], old))

    def test_idempotent_retry_returns_current_state_and_reused_id_is_rejected(self):
        body = self.payload('episode', episode_id=101, watched=True, establish_progress=True)
        first = self.service.mutate(self.token, self.account['csrf'], body)
        self.apply('intent', intent='paused')
        before_calls = self.calls
        retry = self.service.mutate(self.token, self.account['csrf'], body)
        self.assertEqual(retry['operation_revision'], first['operation_revision'])
        self.assertEqual(retry['tracking_revision'], 2)
        self.assertEqual(self.record(retry)['intent'], 'paused')
        self.assertEqual(self.calls, before_calls, 'a response retry must not depend on a provider')
        self.error(409, lambda: self.service.mutate(self.token, self.account['csrf'], {**body, 'watched': False}))
        self.assertEqual(self.service.read(self.token)['tracking_revision'], 2)

    def test_atomic_bulk_undo_and_remove_undo_restore_only_affected_state(self):
        before = self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        all_result = self.apply('all', catalogue_revision='catalogue-10-v1')
        undone = self.apply('undo', target_operation_id=all_result['operation_id'])
        self.assertEqual(self.marks(undone), {101: True, 102: False, 103: False})
        self.assertEqual(self.record(undone)['intent'], self.record(before)['intent'])
        removed = self.apply('remove')
        restored = self.apply('undo', target_operation_id=removed['operation_id'])
        self.assertFalse(self.record(restored)['deleted'])
        self.assertEqual(self.marks(restored), {101: True, 102: False, 103: False})
        self.assertEqual(self.accounts.session(self.token)['state'], STATE)

    def test_undo_preserves_unrelated_later_edits_but_rejects_changed_cells(self):
        self.apply('replace', through_episode_id=None, catalogue_revision='catalogue-10-v1')
        first = self.apply('episode', episode_id=101, watched=True)
        self.apply('episode', episode_id=103, watched=True)
        undone = self.apply('undo', target_operation_id=first['operation_id'])
        self.assertEqual(self.marks(undone), {101: False, 102: False, 103: True})
        next_mark = self.apply('episode', episode_id=101, watched=True)
        self.apply('episode', episode_id=101, watched=False)
        self.apply('episode', episode_id=101, watched=True)
        failure = self.error(409, lambda: self.apply('undo', target_operation_id=next_mark['operation_id']))
        self.assertEqual(self.marks(failure.data), {101: True, 102: False, 103: True})
        self.error(400, lambda: self.apply('undo', show_id=20, target_operation_id=first['operation_id']))

    def test_catalogue_refresh_and_cache_removal_preserve_orphaned_personal_marks(self):
        self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        self.catalogues[10]['episodes'] = [e for e in self.catalogues[10]['episodes'] if e['id'] != 101]
        self.catalogues[10]['revision'] = 'catalogue-10-v2'
        self.apply('replace', through_episode_id=None, catalogue_revision='catalogue-10-v2')
        self.assertEqual(self.marks(self.service.read(self.token)), {101: True, 102: False, 103: False})
        self.catalogues.clear()
        self.assertEqual(self.marks(self.service.read(self.token)), {101: True, 102: False, 103: False})
        removed = self.apply('remove')
        self.assertEqual(self.marks(removed), {101: False, 102: False, 103: False})
        self.apply('undo', target_operation_id=removed['operation_id'])
        self.assertEqual(self.marks(self.service.read(self.token)), {101: True, 102: False, 103: False})

    def test_authenticated_catalogue_exposes_precise_server_release_projection(self):
        value = self.service.catalogue(self.token, 10)
        self.assertEqual(value['user_id'], self.account['user']['id'])
        self.assertEqual(value['catalogue_revision'], 'catalogue-10-v1')
        self.assertEqual([e['released'] for e in value['episodes']], [True, True, True, False, None, None])
        self.assertTrue(value['fresh'])
        self.assertEqual(value['expires_at'], self.now + 1000)
        self.assertTrue(value['complete'])

    def test_malformed_source_never_establishes_ownership_or_commits_partial_marks(self):
        original = deepcopy(self.catalogues[10])
        bad_values = [
            {'id': 20}, {'revision': None}, {'episodes': None},
            {'episodes': [original['episodes'][0], original['episodes'][0]]},
            {'episodes': [{**original['episodes'][0], 'id': True}]},
            {'episodes': [{**original['episodes'][0], 'season': None}]},
        ]
        for changes in bad_values:
            with self.subTest(changes=changes):
                self.catalogues[10] = {**original, **changes}
                self.error(503, lambda: self.apply('all', catalogue_revision='catalogue-10-v1'))
                self.assertEqual(self.service.read(self.token)['tracking'], [])
                self.assertEqual(self.service.read(self.token)['tracking_revision'], 0)
        self.catalogues[10] = original

    def test_noop_does_not_create_a_revision_and_delete_account_cascades_tracking(self):
        first = self.apply('intent', intent='watching')
        second = self.apply('intent', intent='watching')
        self.assertEqual(first['tracking_revision'], second['tracking_revision'])
        self.assertIsNone(second['undo'])
        self.apply('episode', episode_id=101, watched=True, establish_progress=True)
        with self.accounts.store.connection(write=True) as connection:
            connection.execute('DELETE FROM accounts WHERE id=?', (self.account['user']['id'],))
            for table in ('account_tracking_revisions', 'account_show_tracking', 'account_episode_progress', 'account_tracking_operations'):
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_concurrent_same_revision_writes_have_only_one_winner(self):
        barrier = threading.Barrier(2)
        first = self.payload('episode', episode_id=101, watched=True, establish_progress=True)
        second = self.payload('episode', episode_id=103, watched=True, establish_progress=True)

        def commit(body):
            barrier.wait(timeout=3)
            try:
                return self.service.mutate(self.token, self.account['csrf'], body)['tracking_revision']
            except AccountError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(commit, (first, second)))
        self.assertEqual(sorted(outcomes), [1, 409])
        self.assertEqual(len(self.marks(self.service.read(self.token))), 1)


class ReleaseTimeTests(TestCase):
    def test_regular_episode_feed_retains_precise_release_time(self):
        episodes = trim_episode_ratings([{'id': 1, 'season': 1, 'number': 1, 'name': 'Pilot',
                                         'airstamp': '2026-10-03T17:00:00+00:00'}])
        self.assertEqual(episodes[0]['airstamp'], '2026-10-03T17:00:00+00:00')

    def test_offsets_missing_time_and_invalid_stamps(self):
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc).timestamp()
        self.assertTrue(released({'airstamp': '2026-10-03T13:00:00-04:00'}, now))
        self.assertFalse(released({'airstamp': '2026-10-03T15:00:00-04:00'}, now))
        self.assertIsNone(released({'airstamp': '2026-10-03T01:00:00', 'airdate': '2026-10-03'}, now))
        self.assertTrue(released({'airstamp': 'invalid', 'airdate': '2026-10-02'}, now))
        self.assertIsNone(released({'airdate': 'invalid'}, now))


if __name__ == '__main__':
    main()
