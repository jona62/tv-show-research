"""Durable account-owned viewing history, separate from replaceable preferences."""
import json


SCHEMA = '''
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS account_tracking_revisions (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS account_show_tracking (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    show_id INTEGER NOT NULL CHECK(show_id > 0 AND show_id <= 9007199254740991),
    intent TEXT CHECK(intent IN ('watching', 'paused', 'completed', 'dropped')),
    progress_known INTEGER NOT NULL CHECK(progress_known IN (0, 1)),
    deleted INTEGER NOT NULL CHECK(deleted IN (0, 1)),
    revision INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    intent_revision INTEGER NOT NULL,
    progress_known_revision INTEGER NOT NULL,
    deleted_revision INTEGER NOT NULL,
    PRIMARY KEY(account_id, show_id),
    CHECK(deleted = 1 OR intent IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS account_episode_progress (
    account_id TEXT NOT NULL,
    show_id INTEGER NOT NULL,
    episode_id INTEGER NOT NULL CHECK(episode_id > 0 AND episode_id <= 9007199254740991),
    watched INTEGER NOT NULL CHECK(watched IN (0, 1)),
    revision INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(account_id, show_id, episode_id),
    FOREIGN KEY(account_id, show_id) REFERENCES account_show_tracking(account_id, show_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS account_tracking_operations (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    show_id INTEGER NOT NULL,
    request_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    undo_json TEXT NOT NULL,
    PRIMARY KEY(account_id, operation_id)
);
CREATE INDEX IF NOT EXISTS account_tracking_changes ON account_show_tracking(account_id, revision);
CREATE INDEX IF NOT EXISTS account_episode_changes ON account_episode_progress(account_id, revision);
COMMIT;
'''
FIELDS = ('intent', 'progress_known', 'deleted')


def revision(connection, account_id):
    row = connection.execute('SELECT revision FROM account_tracking_revisions WHERE account_id=?', (account_id,)).fetchone()
    return row['revision'] if row else 0


def response(connection, account_id):
    episodes = {}
    for row in connection.execute(
            'SELECT show_id, episode_id, watched, revision FROM account_episode_progress WHERE account_id=? '
            'ORDER BY show_id, episode_id', (account_id,)):
        episodes.setdefault(row['show_id'], []).append({
            'episode_id': row['episode_id'], 'watched': bool(row['watched']), 'revision': row['revision']})
    tracking = []
    for row in connection.execute(
            'SELECT * FROM account_show_tracking WHERE account_id=? ORDER BY updated_at DESC, show_id', (account_id,)):
        tracking.append({
            'show_id': row['show_id'], 'intent': row['intent'], 'progress_known': bool(row['progress_known']),
            'deleted': bool(row['deleted']), 'revision': row['revision'], 'updated_at': row['updated_at'],
            'episode_states': episodes.get(row['show_id'], []),
        })
    return {'schema_version': 1, 'user_id': account_id, 'tracking_revision': revision(connection, account_id),
            'tracking': tracking}


def show(connection, account_id, show_id):
    row = connection.execute('SELECT * FROM account_show_tracking WHERE account_id=? AND show_id=?',
                             (account_id, show_id)).fetchone()
    values = dict(row) if row else {
        'intent': None, 'progress_known': 0, 'deleted': 1, 'revision': 0,
        'intent_revision': 0, 'progress_known_revision': 0, 'deleted_revision': 0,
    }
    states = {item['episode_id']: dict(item) for item in connection.execute(
        'SELECT episode_id, watched, revision FROM account_episode_progress WHERE account_id=? AND show_id=?',
        (account_id, show_id))}
    return values, states


def commit(connection, account_id, show_id, current, states, fields, marks, next_revision, now):
    """Return only changed cells, allowing Undo to preserve unrelated later edits."""
    changed_fields = {key: value for key, value in fields.items() if current[key] != value}
    changed_marks = {episode_id: value for episode_id, value in marks.items()
                     if episode_id not in states or states[episode_id]['watched'] != value}
    undo = {'fields': {key: current[key] for key in changed_fields},
            'episodes': {str(episode_id): states.get(episode_id, {}).get('watched', 0) for episode_id in changed_marks}}
    if not changed_fields and not changed_marks:
        return None
    values = {**current, **changed_fields}
    field_revisions = {key: next_revision if key in changed_fields else current[key + '_revision'] for key in FIELDS}
    connection.execute(
        'INSERT INTO account_show_tracking VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(account_id, show_id) DO UPDATE SET intent=excluded.intent, progress_known=excluded.progress_known, '
        'deleted=excluded.deleted, revision=excluded.revision, updated_at=excluded.updated_at, '
        'intent_revision=excluded.intent_revision, progress_known_revision=excluded.progress_known_revision, '
        'deleted_revision=excluded.deleted_revision',
        (account_id, show_id, values['intent'], values['progress_known'], values['deleted'], next_revision, now,
         *(field_revisions[key] for key in FIELDS)))
    for episode_id, watched in changed_marks.items():
        connection.execute(
            'INSERT INTO account_episode_progress VALUES (?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(account_id, show_id, episode_id) DO UPDATE SET watched=excluded.watched, '
            'revision=excluded.revision, updated_at=excluded.updated_at',
            (account_id, show_id, episode_id, watched, next_revision, now))
    connection.execute('INSERT INTO account_tracking_revisions VALUES (?, ?) '
                       'ON CONFLICT(account_id) DO UPDATE SET revision=excluded.revision', (account_id, next_revision))
    return undo


def operation(connection, account_id, operation_id):
    return connection.execute('SELECT * FROM account_tracking_operations WHERE account_id=? AND operation_id=?',
                              (account_id, operation_id)).fetchone()


def remember(connection, account_id, payload, request_hash, accepted_revision, undo):
    connection.execute('INSERT INTO account_tracking_operations VALUES (?, ?, ?, ?, ?, ?)',
                       (account_id, payload['operation_id'], payload['show_id'], request_hash, accepted_revision,
                        json.dumps(undo, separators=(',', ':'))))
