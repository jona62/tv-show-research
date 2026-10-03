"""Account operations independent of HTTP, catalogue loading, and browser UI."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from argon2.low_level import Type

from .account_store import AccountStore
from .account_merge import merge_guest, record_removals
from .account_validation import AccountError, compact_removed, compact_state, email_address, email_domain
from .account_validation import password as validate_password, revision as validate_revision


SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_SESSIONS = 20
# OWASP's Argon2id minimum: 19 MiB, two iterations, one lane. At most two
# requests perform expensive password/DNS work concurrently across services.
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID)
AUTH_WORK = threading.BoundedSemaphore(2)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
INVALID_LOGIN = 'Email or password is incorrect.'
NO_CSRF = object()
SESSION_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
SESSION_QUERY = '''
    SELECT a.*, s.csrf, s.expires_at FROM account_sessions s
    JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=?
'''


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@contextmanager
def expensive_work():
    if not AUTH_WORK.acquire(blocking=False):
        raise AccountError(429, 'Too many account requests. Please try again shortly.', retry_after=2)
    try:
        yield
    finally:
        AUTH_WORK.release()


def verifies(encoded, value):
    try:
        return HASHER.verify(encoded, value)
    except (VerificationError, UnicodeEncodeError):
        return False


class AccountService:
    def __init__(self, path, clock=time.time, validate_domain=True):
        self.store = AccountStore(path)
        self.clock = clock
        self.validate_domain = validate_domain

    def _attempt(self, email_key):
        wait = self.store.consume_attempt(digest(email_key), self.clock())
        if wait:
            raise AccountError(429, 'Too many attempts. Please try again shortly.', retry_after=wait)

    def _session_row(self, connection, token, csrf=NO_CSRF):
        if not isinstance(token, str) or not SESSION_TOKEN.fullmatch(token):
            raise AccountError(401, 'Please sign in to your account.')
        row = connection.execute(SESSION_QUERY, (digest(token),)).fetchone()
        if row is None or row['expires_at'] <= self.clock():
            raise AccountError(401, 'Please sign in to your account.')
        if csrf is not NO_CSRF:
            try:
                valid = isinstance(csrf, str) and hmac.compare_digest(row['csrf'].encode('utf-8'), csrf.encode('utf-8'))
            except UnicodeEncodeError:
                valid = False
            if not valid:
                raise AccountError(403, 'This account request could not be verified. Please reload and try again.')
        return row

    @staticmethod
    def _response(row, csrf, removals):
        return {
            'user': {'id': row['id'], 'email': row['email']},
            'csrf': csrf,
            'state': json.loads(row['state_json']),
            'revision': row['revision'],
            'removals': removals,
        }

    @staticmethod
    def _removals(connection, account_id, since=0):
        removed = {'profile': [], 'saved': []}
        for item in connection.execute(
                'SELECT kind, show_id, revision FROM account_removals WHERE account_id=? AND revision>? '
                'ORDER BY revision, kind, show_id', (account_id, since)):
            removed[item['kind']].append({'id': item['show_id'], 'revision': item['revision']})
        return removed

    def _new_session(self, connection, account_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        connection.execute('DELETE FROM account_sessions WHERE expires_at <= ?', (self.clock(),))
        connection.execute('INSERT INTO account_sessions VALUES (?, ?, ?, ?)',
                           (digest(token), account_id, csrf, self.clock() + SESSION_SECONDS))
        connection.execute(
            'DELETE FROM account_sessions WHERE account_id=? AND token_hash NOT IN '
            '(SELECT token_hash FROM account_sessions WHERE account_id=? '
            'ORDER BY expires_at DESC, rowid DESC LIMIT ?)',
            (account_id, account_id, MAX_SESSIONS),
        )
        row = connection.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        return token, self._response(row, csrf, self._removals(connection, account_id))

    def signup(self, email, password, initial_state):
        info, email_key = email_address(email)
        value, state = validate_password(password), compact_state(initial_state)
        self._attempt(email_key)
        with expensive_work():
            if self.validate_domain:
                email_domain(info)
            encoded = HASHER.hash(value)
        try:
            with self.store.connection(write=True) as connection:
                account_id = secrets.token_urlsafe(16)
                connection.execute('INSERT INTO accounts VALUES (?, ?, ?, ?, ?, 0, ?)',
                                   (account_id, info.normalized, email_key, encoded,
                                    json.dumps(state, separators=(',', ':'), allow_nan=False), self.clock()))
                return self._new_session(connection, account_id)
        except sqlite3.IntegrityError:
            raise AccountError(400, 'Unable to create this account. Try signing in or use a different email address.') from None

    def login(self, email, password, guest_state=None):
        guest = compact_state(guest_state) if guest_state is not None else None
        try:
            _, email_key = email_address(email)
        except AccountError:
            raise AccountError(401, INVALID_LOGIN) from None
        self._attempt(email_key)
        if not isinstance(password, str) or not 15 <= len(password) <= 128:
            raise AccountError(401, INVALID_LOGIN)
        with self.store.connection() as connection:
            row = connection.execute('SELECT * FROM accounts WHERE email_key=?', (email_key,)).fetchone()
        with expensive_work():
            valid = verifies(row['password_hash'] if row else DUMMY_HASH, password)
        if not valid or row is None:
            raise AccountError(401, INVALID_LOGIN)
        with self.store.connection(write=True) as connection:
            current = connection.execute('SELECT * FROM accounts WHERE id=?', (row['id'],)).fetchone()
            # A password change between verification and session creation revokes
            # the old credentials even when these requests run concurrently.
            if current is None or current['password_hash'] != row['password_hash']:
                raise AccountError(401, INVALID_LOGIN)
            if guest is not None:
                before = json.loads(current['state_json'])
                removals = {(item['kind'], item['show_id']) for item in connection.execute(
                    'SELECT kind, show_id FROM account_removals WHERE account_id=?', (row['id'],))}
                merged = merge_guest(before, guest, removals)
                if merged != before:
                    connection.execute('UPDATE accounts SET state_json=?, revision=revision+1 WHERE id=?',
                                       (json.dumps(merged, separators=(',', ':'), allow_nan=False), row['id']))
            return self._new_session(connection, row['id'])

    def session(self, token, since=0, owner=None, conditional=False):
        since = validate_revision(since)
        if owner is not None and (not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', owner)):
            raise AccountError(400, 'The account owner is invalid.')
        with self.store.connection() as connection:
            # State and its removal history must come from the same snapshot
            # while another device may be committing a save through WAL.
            connection.execute('BEGIN')
            row = self._session_row(connection, token)
            if conditional and owner == row['id'] and since == row['revision']:
                # Clients explicitly opt in so an older, cached app still gets
                # the complete session it expects. Authenticate every poll;
                # revisions are hints about state, never session credentials.
                return {'user': {'id': row['id'], 'email': row['email']},
                        'csrf': row['csrf'], 'revision': row['revision'], 'unchanged': True}
            return self._response(row, row['csrf'], self._removals(connection, row['id'], since if owner == row['id'] else 0))

    def identity(self, token):
        """Authenticate lightweight private reads without decoding preference state."""
        with self.store.connection() as connection:
            row = self._session_row(connection, token)
            return {'id': row['id'], 'email': row['email']}

    def save(self, token, csrf, state, revision, removed=None):
        state, expected_revision = compact_state(state), validate_revision(revision)
        removed = compact_removed(removed, state)
        with self.store.connection(write=True) as connection:
            row = self._session_row(connection, token, csrf)
            if row['revision'] != expected_revision:
                raise AccountError(409, 'Your list changed on another device. Review its latest version and try again.',
                                   data={'state': json.loads(row['state_json']), 'revision': row['revision'],
                                         'removals': self._removals(connection, row['id'], expected_revision)})
            record_removals(connection, row['id'], json.loads(row['state_json']), state, expected_revision + 1, removed)
            connection.execute('UPDATE accounts SET state_json=?, revision=revision+1 WHERE id=?',
                               (json.dumps(state, separators=(',', ':'), allow_nan=False), row['id']))
            return {'state': state, 'revision': expected_revision + 1,
                    'removals': self._removals(connection, row['id'], expected_revision)}

    def logout(self, token, csrf):
        with self.store.connection(write=True) as connection:
            self._session_row(connection, token, csrf)
            connection.execute('DELETE FROM account_sessions WHERE token_hash=?', (digest(token),))

    def change_password(self, token, csrf, current_password, password):
        value = validate_password(password)
        with self.store.connection() as connection:
            row = self._session_row(connection, token, csrf)
        self._attempt(row['email_key'])
        with expensive_work():
            if not isinstance(current_password, str) or not 15 <= len(current_password) <= 128:
                raise AccountError(400, 'Current password is incorrect.')
            if not verifies(row['password_hash'], current_password):
                raise AccountError(400, 'Current password is incorrect.')
            encoded = HASHER.hash(value)
        with self.store.connection(write=True) as connection:
            current = self._session_row(connection, token, csrf)
            if current['password_hash'] != row['password_hash']:
                raise AccountError(401, INVALID_LOGIN)
            connection.execute('UPDATE accounts SET password_hash=? WHERE id=?', (encoded, row['id']))
            connection.execute('DELETE FROM account_sessions WHERE account_id=?', (row['id'],))
            return self._new_session(connection, row['id'])
