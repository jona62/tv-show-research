"""SQLite persistence. Each transaction owns its connection, including on worker threads."""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import sqlite3
import stat


SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    email_key TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    state_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS account_sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS account_sessions_user ON account_sessions(account_id);
CREATE INDEX IF NOT EXISTS account_sessions_expiry ON account_sessions(expires_at);
CREATE TABLE IF NOT EXISTS account_removals (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('profile', 'saved')),
    show_id INTEGER NOT NULL CHECK (show_id > 0 AND show_id <= 9007199254740991),
    revision INTEGER NOT NULL CHECK (revision > 0 AND revision <= 9007199254740991),
    PRIMARY KEY (account_id, kind, show_id)
);
CREATE INDEX IF NOT EXISTS account_removals_revision ON account_removals(account_id, revision);
CREATE TABLE IF NOT EXISTS account_attempts (
    email_hash TEXT PRIMARY KEY,
    tokens REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS account_attempts_updated ON account_attempts(updated_at);
'''
ATTEMPT_BURST = 5
ATTEMPT_REFILL_SECONDS = 60
MAX_ATTEMPT_KEYS = 10000


class AccountStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().absolute()
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Pre-create with private permissions, and reject a database symlink.
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('The account database must be a regular file.')
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self.connection() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA synchronous=FULL')
        try:
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            if write:
                connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        finally:
            connection.close()

    def consume_attempt(self, email_hash, now):
        """Reserve an attempt before expensive work; survives restart and races."""
        with self.connection(write=True) as connection:
            row = connection.execute(
                'SELECT tokens, updated_at FROM account_attempts WHERE email_hash=?', (email_hash,)
            ).fetchone()
            tokens = ATTEMPT_BURST if row is None else min(
                ATTEMPT_BURST, row['tokens'] + max(0, now - row['updated_at']) / ATTEMPT_REFILL_SECONDS
            )
            wait = math.ceil((1 - tokens) * ATTEMPT_REFILL_SECONDS) if tokens < 1 else 0
            connection.execute(
                'INSERT INTO account_attempts VALUES (?, ?, ?) '
                'ON CONFLICT(email_hash) DO UPDATE SET tokens=excluded.tokens, updated_at=excluded.updated_at',
                (email_hash, tokens if wait else tokens - 1, now),
            )
            connection.execute('DELETE FROM account_attempts WHERE updated_at < ?', (now - 86400,))
            count = connection.execute('SELECT count(*) FROM account_attempts').fetchone()[0]
            if count > MAX_ATTEMPT_KEYS:
                connection.execute(
                    'DELETE FROM account_attempts WHERE rowid IN '
                    '(SELECT rowid FROM account_attempts ORDER BY updated_at, rowid LIMIT ?)',
                    (count - MAX_ATTEMPT_KEYS,),
                )
            connection.execute('DELETE FROM account_sessions WHERE expires_at <= ?', (now,))
            return wait
