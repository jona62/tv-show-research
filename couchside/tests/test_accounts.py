"""Account invariants without catalogue loading, networking, or an HTTP server."""

from pathlib import Path
import sys

# Direct script runs and unittest discovery share the app package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import os
import sqlite3
import tempfile
import threading
from unittest import TestCase, main
from unittest.mock import patch

from argon2 import extract_parameters
from argon2.low_level import Type
from email_validator import EmailUndeliverableError

from backend.accounts import AccountError, AccountService, AUTH_WORK, MAX_SESSIONS, SESSION_SECONDS
from backend.account_validation import MAX_RATED, MAX_SAVED, compact_state


PASSWORD = 'a correct horse battery staple'
OTHER_PASSWORD = 'another long password phrase'
STATE = {'version': 3, 'profile': [{'id': 10, 'weight': .7}], 'saved': [{'id': 20}],
         'settings': {'known_min': 85}, 'onboarded': True}


class AccountTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'private' / 'accounts.sqlite3'
        self.now = 1000.0
        self.service = self.reopen()

    def reopen(self):
        return AccountService(self.path, clock=lambda: self.now, validate_domain=False)

    def signup(self, email='person@gmail.com', state=None, value=PASSWORD):
        return self.service.signup(email, value, deepcopy(STATE if state is None else state))

    def error(self, status, operation):
        with self.assertRaises(AccountError) as caught:
            operation()
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def test_passwords_are_argon2id_and_tokens_are_hashed_with_private_storage(self):
        token, response = self.signup()
        with self.service.store.connection() as connection:
            row = connection.execute('SELECT * FROM accounts').fetchone()
            session = connection.execute('SELECT * FROM account_sessions').fetchone()
            params = extract_parameters(row['password_hash'])
            self.assertEqual(params.type, Type.ID)
            self.assertGreaterEqual(params.memory_cost, 19456)
            self.assertGreaterEqual(params.time_cost, 2)
            self.assertNotIn(PASSWORD, row['password_hash'])
            self.assertEqual(session['token_hash'], hashlib.sha256(token.encode()).hexdigest())
            self.assertNotEqual(session['token_hash'], token)
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            for path in self.path.parent.glob('accounts.sqlite3*'):
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.path.parent).st_mode & 0o777, 0o700)
        self.assertEqual(response['state'], STATE)
        self.assertEqual(response['revision'], 0)
        self.assertEqual(set(response), {'user', 'csrf', 'state', 'revision', 'removals'})
        self.assertEqual(response['removals'], {'profile': [], 'saved': []})

    def test_email_syntax_normalization_and_case_insensitive_uniqueness(self):
        _, response = self.signup(' Person@GMAIL.COM ')
        self.assertEqual(response['user']['email'], 'Person@gmail.com')
        duplicate = self.error(400, lambda: self.signup('person@gmail.com'))
        self.assertIn('Unable to create this account', duplicate.message)
        token, signed_in = self.service.login('PERSON@gmail.com', PASSWORD)
        self.assertEqual(signed_in['user'], response['user'])
        self.assertEqual(self.service.session(token)['state'], STATE)
        for email in ('A at B dot com', 'a@b', 'a..b@gmail.com', 'a b@gmail.com',
                      'a@gmail..com', 'Name <a@gmail.com>', None, 'x' * 321):
            with self.subTest(email=email):
                self.error(400, lambda: self.signup(email))

    def test_any_mail_domain_is_supported_and_uncertain_dns_fails_closed(self):
        self.service.validate_domain = True
        accepted = {'mx': [(10, 'mail.independent-domain.tld')], 'mx_fallback_type': None}
        with patch('backend.account_validation.validate_email_deliverability', return_value=accepted) as lookup:
            self.signup('person@independent-domain.tld')
            lookup.assert_called_once_with('independent-domain.tld', 'independent-domain.tld', timeout=3)
        with patch('backend.account_validation.validate_email_deliverability',
                   side_effect=EmailUndeliverableError('The domain does not accept mail.')):
            self.error(400, lambda: self.signup('person@unreachable-domain.tld'))
        for outcome in ('timeout', 'no_nameservers'):
            with self.subTest(outcome=outcome), patch('backend.account_validation.validate_email_deliverability',
                                                    return_value={'unknown-deliverability': outcome}):
                failure = self.error(503, lambda: self.signup(f'{outcome}@mail-domain.tld'))
                self.assertEqual(failure.retry_after, 30)
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM accounts').fetchone()[0], 1)
        # DNS availability is irrelevant when signing into an existing account.
        with patch('backend.account_validation.validate_email_deliverability', side_effect=AssertionError('DNS on login')):
            self.service.login('person@independent-domain.tld', PASSWORD)

    def test_password_length_and_spaces_unicode_are_preserved(self):
        for value in ('x' * 14, 'x' * 129, None, '\ud800' * 15):
            self.error(400, lambda: self.signup(value=value))
        value = '  café 密碼 long phrase  '
        self.signup(value=value)
        self.service.login('person@gmail.com', value)
        self.error(401, lambda: self.service.login('person@gmail.com', value.strip()))
        self.signup('min@gmail.com', value='x' * 15)
        self.signup('max@gmail.com', value='x' * 128)

    def test_unknown_account_and_wrong_password_share_generic_error(self):
        self.signup()
        errors = [self.error(401, lambda: self.service.login(email, OTHER_PASSWORD)).message
                  for email in ('person@gmail.com', 'missing@gmail.com', 'not-an-email')]
        self.assertEqual(len(set(errors)), 1)
        self.error(401, lambda: self.service.login('person@gmail.com', '\ud800' * 15))

    def test_mutations_require_csrf_and_sessions_expire_or_logout(self):
        token, response = self.signup()
        for csrf in ('wrong', None, 42, 'é', '\ud800'):
            self.error(403, lambda: self.service.save(token, csrf, STATE, 0))
            self.error(403, lambda: self.service.logout(token, csrf))
            self.error(403, lambda: self.service.change_password(token, csrf, PASSWORD, OTHER_PASSWORD))
        self.service.logout(token, response['csrf'])
        self.error(401, lambda: self.service.session(token))
        token, _ = self.service.login('person@gmail.com', PASSWORD)
        self.now += SESSION_SECONDS
        self.error(401, lambda: self.service.session(token))
        for token in ('', 'missing' * 8, None, 'é' * 43, '\ud800' * 43):
            self.error(401, lambda: self.service.session(token))

    def test_accounts_are_isolated_and_stale_revision_returns_authoritative_state(self):
        token, response = self.signup()
        second, second_response = self.signup('second@gmail.com')
        new = deepcopy(STATE)
        new['saved'] = [{'id': 99, 'name': 'Untrusted title', 'poster': 'https://example.com'}]
        new['profile'][0]['name'] = 'Untrusted name'
        saved = self.service.save(token, response['csrf'], new, 0)
        self.assertEqual(saved, {'state': {**STATE, 'saved': [{'id': 99}]}, 'revision': 1,
                                 'removals': {'profile': [], 'saved': [{'id': 20, 'revision': 1}]}})
        self.assertEqual(self.service.session(second)['state'], STATE)
        self.assertEqual(self.service.session(second)['revision'], 0)
        self.error(403, lambda: self.service.save(second, response['csrf'], new, 0))
        self.error(403, lambda: self.service.save(token, second_response['csrf'], new, 1))
        conflict = self.error(409, lambda: self.service.save(token, response['csrf'], STATE, 0))
        self.assertEqual(conflict.data, saved)
        self.assertEqual(self.service.session(token)['state'], saved['state'])

    def test_login_imports_guest_additions_once_and_keeps_account_choices(self):
        token, account = self.signup()
        guest = {'version': 3, 'profile': [{'id': 10, 'weight': -1}, {'id': 11, 'weight': 1}],
                 'saved': [{'id': 20}, {'id': 21}], 'settings': {'known_min': 0}, 'onboarded': False}
        _, imported = self.service.login('person@gmail.com', PASSWORD, guest)
        expected = {**STATE, 'profile': [{'id': 10, 'weight': .7}, {'id': 11, 'weight': 1}],
                    'saved': [{'id': 20}, {'id': 21}]}
        self.assertEqual(imported['state'], expected)
        self.assertEqual(imported['revision'], 1)
        self.assertEqual(imported['user'], account['user'])
        self.assertEqual(self.service.session(token)['state'], expected)
        _, replayed = self.service.login('person@gmail.com', PASSWORD, guest)
        self.assertEqual(replayed['state'], expected)
        self.assertEqual(replayed['revision'], 1, 'a repeated import must not create another revision')

    def test_recorded_account_removals_block_guest_replay_and_survive_restart(self):
        token, account = self.signup()
        empty = {**STATE, 'profile': [], 'saved': []}
        self.service.save(token, account['csrf'], empty, 0)
        self.service = self.reopen()
        guest = {**STATE, 'profile': STATE['profile'] + [{'id': 11, 'weight': 1}],
                 'saved': STATE['saved'] + [{'id': 21}]}
        _, imported = self.service.login('person@gmail.com', PASSWORD, guest)
        self.assertEqual(imported['state'], {**STATE, 'profile': [{'id': 11, 'weight': 1}], 'saved': [{'id': 21}]})
        self.assertEqual(imported['revision'], 2)
        # An explicit signed-in re-add remains possible; history still protects
        # the account after the item is subsequently removed again.
        self.service.save(token, account['csrf'], STATE, 2)
        self.service.save(token, account['csrf'], empty, 3)
        _, replayed = self.service.login('person@gmail.com', PASSWORD, STATE)
        self.assertEqual(replayed['state'], empty)
        self.assertEqual(replayed['revision'], 4)

    def test_removal_history_is_scoped_to_the_account_and_collection(self):
        token, account = self.signup()
        self.service.save(token, account['csrf'], {**STATE, 'profile': []}, 0)
        # A removed rating does not prevent saving that same show to My List.
        guest = {**STATE, 'saved': [{'id': 10}]}
        _, imported = self.service.login('person@gmail.com', PASSWORD, guest)
        self.assertEqual(imported['state']['profile'], [])
        self.assertEqual(imported['state']['saved'], [{'id': 20}, {'id': 10}])
        self.signup('second@gmail.com', state={**STATE, 'profile': [], 'saved': []})
        _, second = self.service.login('second@gmail.com', PASSWORD, STATE)
        self.assertEqual(second['state'], STATE)
        with self.service.store.connection(write=True) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_removals').fetchone()[0], 1)
            connection.execute('DELETE FROM accounts WHERE id=?', (account['user']['id'],))
            self.assertEqual(connection.execute('SELECT count(*) FROM account_removals').fetchone()[0], 0)

    def test_invalid_guest_import_does_not_consume_an_email_attempt(self):
        self.signup()
        with self.service.store.connection() as connection:
            before = dict(connection.execute('SELECT * FROM account_attempts').fetchone())
        invalid = {**STATE, 'saved': [{'id': 20}, {'id': 20}]}
        with patch('backend.accounts.verifies', side_effect=AssertionError('password work on invalid guest state')):
            self.error(400, lambda: self.service.login('person@gmail.com', PASSWORD, invalid))
        with self.service.store.connection() as connection:
            self.assertEqual(dict(connection.execute('SELECT * FROM account_attempts').fetchone()), before)
            self.assertEqual(connection.execute('SELECT count(*) FROM account_sessions').fetchone()[0], 1)

    def test_guest_union_overflow_does_not_truncate_or_create_a_session(self):
        for kind, maximum in (('profile', MAX_RATED), ('saved', MAX_SAVED)):
            with self.subTest(kind=kind):
                full = {**STATE, 'profile': [], 'saved': []}
                full[kind] = [{'id': i + 1, **({'weight': .7} if kind == 'profile' else {})} for i in range(maximum)]
                email = f'{kind}@gmail.com'
                token, _ = self.signup(email, state=full)
                guest = {**full, kind: [{'id': maximum + 1, **({'weight': 1} if kind == 'profile' else {})}]}
                with self.service.store.connection() as connection:
                    session_count = connection.execute('SELECT count(*) FROM account_sessions').fetchone()[0]
                self.error(409, lambda: self.service.login(email, PASSWORD, guest))
                unchanged = self.service.session(token)
                self.assertEqual((unchanged['state'], unchanged['revision']), (full, 0))
                with self.service.store.connection() as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM account_sessions').fetchone()[0], session_count)
                # A duplicate at capacity does not count as another show.
                _, duplicate = self.service.login(email, PASSWORD, {**full, kind: full[kind][:1]})
                self.assertEqual((duplicate['state'], duplicate['revision']), (full, 0))

    def test_guest_import_rolls_back_if_session_creation_fails(self):
        token, _ = self.signup()
        guest = {**STATE, 'saved': [{'id': 21}]}
        with patch.object(self.service, '_new_session', side_effect=sqlite3.OperationalError('simulated storage failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.service.login('person@gmail.com', PASSWORD, guest)
        unchanged = self.service.session(token)
        self.assertEqual((unchanged['state'], unchanged['revision']), (STATE, 0))
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_sessions').fetchone()[0], 1)

    def test_concurrent_guest_imports_keep_both_devices_additions(self):
        token, _ = self.signup()
        barrier = threading.Barrier(2)

        def sign_in(show_id):
            guest = {**STATE, 'profile': [{'id': show_id, 'weight': 1}], 'saved': [{'id': show_id}]}
            barrier.wait(timeout=5)
            return self.service.login('person@gmail.com', PASSWORD, guest)[1]

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(sign_in, show_id) for show_id in (30, 40)]
            imported = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted(item['revision'] for item in imported), [1, 2])
        current = self.service.session(token)
        self.assertEqual(sorted(item['id'] for item in current['state']['profile']), [10, 30, 40])
        self.assertEqual(sorted(item['id'] for item in current['state']['saved']), [20, 30, 40])

    def test_stale_save_does_not_record_a_removal(self):
        token, response = self.signup()
        self.service.save(token, response['csrf'], STATE, 0)
        self.error(409, lambda: self.service.save(token, response['csrf'], {**STATE, 'profile': [], 'saved': []}, 0))
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_removals').fetchone()[0], 0)

    def test_cancelled_unsaved_additions_record_removals_and_block_guest_replay(self):
        token, response = self.signup()
        removed = {'profile': [99], 'saved': [98]}
        saved = self.service.save(token, response['csrf'], STATE, 0, removed)
        self.assertEqual(saved['state'], STATE)
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['removals'], {'profile': [{'id': 99, 'revision': 1}], 'saved': [{'id': 98, 'revision': 1}]})
        guest = {**STATE, 'profile': [{'id': 99, 'weight': 1}], 'saved': [{'id': 98}]}
        _, replayed = self.service.login('person@gmail.com', PASSWORD, guest)
        self.assertEqual((replayed['state'], replayed['revision']), (STATE, 1))
        self.signup('second@gmail.com')
        _, second = self.service.login('second@gmail.com', PASSWORD, guest)
        self.assertEqual(second['state']['profile'], STATE['profile'] + guest['profile'])
        self.assertEqual(second['state']['saved'], STATE['saved'] + guest['saved'])

    def test_inferred_and_explicit_removals_are_recorded_once(self):
        token, response = self.signup()
        empty = {**STATE, 'profile': [], 'saved': []}
        saved = self.service.save(token, response['csrf'], empty, 0, {'profile': [10, 11], 'saved': [20, 21]})
        self.assertEqual(saved['removals'], {'profile': [{'id': 10, 'revision': 1}, {'id': 11, 'revision': 1}],
                                           'saved': [{'id': 20, 'revision': 1}, {'id': 21, 'revision': 1}]})
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_removals').fetchone()[0], 4)

    def test_invalid_explicit_removals_leave_state_revision_and_history_unchanged(self):
        token, response = self.signup()
        invalid = [[], {}, {'profile': []}, {'profile': [], 'saved': [], 'other': []},
                   {'profile': None, 'saved': []}, {'profile': [], 'saved': '99'},
                   {'profile': [99, 99], 'saved': []}, {'profile': [10], 'saved': []},
                   {'profile': [], 'saved': [20]},
                   {'profile': list(range(100, 100 + MAX_RATED + 1)), 'saved': []},
                   {'profile': [], 'saved': list(range(100, 100 + MAX_SAVED + 1))}]
        invalid += [{'profile': [show_id], 'saved': []} for show_id in (None, True, 0, -1, .5, '99', 2**53, [], {})]
        for removed in invalid:
            with self.subTest(removed=str(removed)[:80]):
                self.error(400, lambda: self.service.save(token, response['csrf'], STATE, 0, removed))
        self.assertEqual(self.service.session(token), response)
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_removals').fetchone()[0], 0)

    def test_stale_explicit_cancellation_does_not_write_history(self):
        token, response = self.signup()
        self.service.save(token, response['csrf'], STATE, 0)
        failure = self.error(409, lambda: self.service.save(token, response['csrf'], STATE, 0,
                                                         {'profile': [99], 'saved': [98]}))
        self.assertEqual(failure.data['removals'], {'profile': [], 'saved': []})
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_removals').fetchone()[0], 0)

    def test_removal_revisions_follow_repeated_deletions_and_filter_by_owner(self):
        token, response = self.signup()
        owner = response['user']['id']
        empty = {**STATE, 'profile': [], 'saved': []}
        removed = self.service.save(token, response['csrf'], empty, 0)
        first = {'profile': [{'id': 10, 'revision': 1}], 'saved': [{'id': 20, 'revision': 1}]}
        self.assertEqual(removed['removals'], first)
        readded = self.service.save(token, response['csrf'], STATE, 1)
        self.assertEqual(readded['removals'], {'profile': [], 'saved': []})
        self.assertEqual(self.service.session(token)['removals'], first, 're-adds must retain removal history')
        self.service.save(token, response['csrf'], empty, 2)
        latest = {'profile': [{'id': 10, 'revision': 3}], 'saved': [{'id': 20, 'revision': 3}]}
        self.assertEqual(self.service.session(token, 2, owner)['removals'], latest)
        self.assertEqual(self.service.session(token, 3, owner)['removals'], {'profile': [], 'saved': []})
        self.assertEqual(self.service.session(token, 3, 'different-account')['removals'], latest)
        self.assertEqual(self.service.session(token, 3)['removals'], latest)
        conflict = self.error(409, lambda: self.service.save(token, response['csrf'], STATE, 2))
        self.assertEqual(conflict.data['removals'], latest)
        with self.service.store.connection() as connection:
            self.assertEqual([row[0] for row in connection.execute('SELECT revision FROM account_removals')], [3, 3])

    def test_session_removal_query_rejects_invalid_revisions_and_owners(self):
        token, _ = self.signup()
        for since in (None, True, -1, 2**53, .0, '0'):
            self.error(400, lambda: self.service.session(token, since))
        for owner in (42, '', 'é', '\ud800', 'x' * 129):
            self.error(400, lambda: self.service.session(token, owner=owner))

    def test_session_state_and_removals_share_one_read_snapshot(self):
        token, response = self.signup()
        read, changed = threading.Event(), threading.Event()
        original = self.service._session_row

        def pause_session(connection, *args):
            row = original(connection, *args)
            if len(args) == 1:
                read.set()
                self.assertTrue(changed.wait(5))
            return row

        with patch.object(self.service, '_session_row', side_effect=pause_session):
            with ThreadPoolExecutor(max_workers=1) as executor:
                reading = executor.submit(self.service.session, token)
                self.assertTrue(read.wait(5))
                self.service.save(token, response['csrf'], {**STATE, 'saved': []}, 0)
                changed.set()
                session = reading.result(timeout=5)
        self.assertEqual(session, response, 'an old state must not include a newer removal')
        self.assertEqual(self.service.session(token)['removals']['saved'], [{'id': 20, 'revision': 1}])

    def test_existing_database_adds_removal_history_without_changing_accounts(self):
        token, response = self.signup()
        # This is the old schema: account/session data exists without the new table.
        with self.service.store.connection(write=True) as connection:
            connection.execute('DROP TABLE account_removals')
        self.service = self.reopen()
        self.assertEqual(self.service.session(token), response)
        self.service.save(token, response['csrf'], {**STATE, 'saved': []}, 0)
        _, replayed = self.service.login('person@gmail.com', PASSWORD, STATE)
        self.assertEqual(replayed['state']['saved'], [])

    def test_concurrent_device_updates_have_one_winner(self):
        first, response = self.signup()
        second, second_response = self.service.login('person@gmail.com', PASSWORD)
        barrier = threading.Barrier(2)

        def save(token, csrf, show_id):
            state = {**STATE, 'saved': [{'id': show_id}]}
            barrier.wait(timeout=5)
            try:
                return self.service.save(token, csrf, state, 0)
            except AccountError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(save, first, response['csrf'], 30),
                       executor.submit(save, second, second_response['csrf'], 40)]
            outcomes = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(isinstance(result, dict) for result in outcomes), 1)
        conflict = next(result for result in outcomes if isinstance(result, AccountError))
        self.assertEqual(conflict.status, 409)
        final = self.service.session(first)
        self.assertEqual(final['revision'], 1)
        self.assertEqual(conflict.data, {'state': final['state'], 'revision': 1, 'removals': final['removals']})

    def test_password_change_rotates_session_and_revokes_other_devices(self):
        first, response = self.signup()
        second, _ = self.service.login('person@gmail.com', PASSWORD)
        new, changed = self.service.change_password(first, response['csrf'], PASSWORD, OTHER_PASSWORD)
        self.assertNotEqual(new, first)
        self.assertNotEqual(changed['csrf'], response['csrf'])
        self.error(401, lambda: self.service.session(first))
        self.error(401, lambda: self.service.session(second))
        self.assertEqual(self.service.session(new)['state'], STATE)
        self.error(401, lambda: self.service.login('person@gmail.com', PASSWORD))
        self.service.login('person@gmail.com', OTHER_PASSWORD)

    def test_incorrect_current_password_keeps_session_connected(self):
        token, response = self.signup()
        for value in (OTHER_PASSWORD, None, 'short', '\ud800' * 15):
            failure = self.error(400, lambda: self.service.change_password(
                token, response['csrf'], value, OTHER_PASSWORD))
            self.assertEqual(failure.message, 'Current password is incorrect.')
            self.assertEqual(self.service.session(token), response)

    def test_state_and_sessions_survive_restart(self):
        token, response = self.signup()
        changed = {**STATE, 'saved': [{'id': 777}]}
        self.service.save(token, response['csrf'], changed, 0)
        reopened = self.reopen()
        self.assertEqual(reopened.session(token)['state'], changed)
        self.assertEqual(reopened.session(token)['revision'], 1)
        _, signed_in = reopened.login('person@gmail.com', PASSWORD)
        self.assertEqual(signed_in['state'], changed)

    def test_session_creation_caps_devices_and_removes_expired_tokens(self):
        token, response = self.signup()
        tokens = [token]
        for _ in range(MAX_SESSIONS + 1):
            with self.service.store.connection(write=True) as connection:
                new, _ = self.service._new_session(connection, response['user']['id'])
                tokens.append(new)
        for token in tokens[:-MAX_SESSIONS]:
            self.error(401, lambda: self.service.session(token))
        for token in tokens[-MAX_SESSIONS:]:
            self.assertEqual(self.service.session(token)['user'], response['user'])
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_sessions').fetchone()[0], MAX_SESSIONS)
        self.now += SESSION_SECONDS
        self.service.login('person@gmail.com', PASSWORD)
        with self.service.store.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_sessions').fetchone()[0], 1)

    def test_attempt_budget_is_durable_shared_by_email_case_and_refills(self):
        self.signup()
        for _ in range(4):
            self.error(401, lambda: self.service.login('PERSON@gmail.com', OTHER_PASSWORD))
        throttled = self.error(429, lambda: self.service.login('person@gmail.com', PASSWORD))
        self.assertEqual(throttled.retry_after, 60)
        self.service = self.reopen()
        self.assertEqual(self.error(429, lambda: self.service.login('Person@gmail.com', PASSWORD)).retry_after, 60)
        self.signup('independent@gmail.com')
        self.now += 60
        self.service.login('person@gmail.com', PASSWORD)
        self.error(429, lambda: self.service.login('person@gmail.com', PASSWORD))

    def test_expensive_work_fails_fast_when_capacity_is_exhausted(self):
        token, response = self.signup()
        self.assertTrue(AUTH_WORK.acquire(blocking=False))
        self.assertTrue(AUTH_WORK.acquire(blocking=False))
        try:
            self.error(429, lambda: self.service.login('person@gmail.com', PASSWORD))
            self.error(429, lambda: self.signup('other@gmail.com'))
            self.error(429, lambda: self.service.change_password(token, response['csrf'], PASSWORD, OTHER_PASSWORD))
        finally:
            AUTH_WORK.release()
            AUTH_WORK.release()

    def test_attempt_storage_is_bounded_and_prunes_stale_keys(self):
        with patch('backend.account_store.MAX_ATTEMPT_KEYS', 3):
            for email_hash in ('a', 'b', 'c', 'd'):
                self.service.store.consume_attempt(email_hash, self.now)
                self.now += 1
            with self.service.store.connection() as connection:
                self.assertEqual([row[0] for row in connection.execute(
                    'SELECT email_hash FROM account_attempts ORDER BY email_hash')], ['b', 'c', 'd'])
            self.now += 86400
            self.service.store.consume_attempt('e', self.now)
            with self.service.store.connection() as connection:
                self.assertEqual([row[0] for row in connection.execute('SELECT email_hash FROM account_attempts')], ['e'])

    def test_state_validation_rejects_malformed_duplicates_nonfinite_and_limits(self):
        self.assertEqual(compact_state(STATE), STATE)
        mutations = [
            ('version', 2), ('version', True), ('onboarded', 1),
            ('profile', None), ('profile', [{'id': 10, 'weight': .7}] * 2),
            ('profile', [{'id': True, 'weight': .7}]), ('profile', [{'id': 0, 'weight': 1}]),
            ('profile', [{'id': 2**53, 'weight': 1}]), ('profile', [{'id': 1, 'weight': float('nan')}]),
            ('profile', [{'id': 1, 'weight': float('inf')}]), ('profile', [{'id': 1, 'weight': True}]),
            ('profile', [{'id': 1, 'weight': 10**1000}]),
            ('profile', [{'id': 1, 'weight': .9}]), ('profile', [{'id': 1}]),
            ('profile', [{'id': n + 1, 'weight': 1} for n in range(MAX_RATED + 1)]),
            ('saved', [1]), ('saved', [{'id': 1.5}]), ('saved', [{'id': 1}] * 2),
            ('saved', [{'id': n + 1} for n in range(MAX_SAVED + 1)]),
            ('settings', {}), ('settings', {'known_min': True}), ('settings', {'known_min': 95}),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=str(value)[:80]):
                self.error(400, lambda: compact_state({**STATE, key: value}))
        self.error(400, lambda: compact_state(None))
        for weight in (1, .7, .35, 0, -1):
            self.assertEqual(compact_state({**STATE, 'profile': [{'id': 1, 'weight': weight}]})['profile'][0]['weight'], weight)
        token, response = self.signup()
        for value in (None, True, -1, 0.0, '0'):
            self.error(400, lambda: self.service.save(token, response['csrf'], STATE, value))


if __name__ == '__main__':
    main()
