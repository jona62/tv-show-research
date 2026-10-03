"""Persistent development identity for the loopback-only design preview."""
import json

from backend.accounts import AccountError, DUMMY_HASH
from backend.account_validation import compact_state
from backend.account_merge import merge_guest

ACCOUNT_ID = 'local-development'
EMAIL = 'local-development@couchside.test'
PATH = '/api/account/local-development'


def bootstrap(handler, routes):
    """Keep valid sessions; otherwise attach a separate local development account."""
    if not routes.features.local_development:
        handler.close_connection = True
        routes.reply(handler, {'error': 'Not found.'}, 404, private=True)
        return
    try:
        origin, cookie, secure = routes.context(handler)
        if secure:
            raise AccountError(404, 'Not found.')
        payload = routes.payload(handler, 'state', origin)
        guest = compact_state(payload.get('state'))
        service = routes.service()
        token = routes.token(handler, cookie)
        if token:
            try:
                response = service.session(token)
                routes.reply(handler, response, private=True)
                return
            except AccountError as exc:
                if exc.status != 401:
                    raise
        with service.store.connection(write=True) as connection:
            connection.execute('INSERT OR IGNORE INTO accounts VALUES (?, ?, ?, ?, ?, 0, ?)',
                (ACCOUNT_ID, EMAIL, EMAIL, DUMMY_HASH, json.dumps(guest), service.clock()))
            row = connection.execute('SELECT * FROM accounts WHERE id=?', (ACCOUNT_ID,)).fetchone()
            removals = {(item['kind'], item['show_id']) for item in connection.execute(
                'SELECT kind, show_id FROM account_removals WHERE account_id=?', (ACCOUNT_ID,))}
            merged = merge_guest(json.loads(row['state_json']), guest, removals)
            if merged != json.loads(row['state_json']):
                connection.execute('UPDATE accounts SET state_json=?, revision=revision+1 WHERE id=?',
                    (json.dumps(merged, separators=(',', ':')), ACCOUNT_ID))
            token, response = service._new_session(connection, ACCOUNT_ID)
        routes.reply(handler, response, headers=(('Set-Cookie', routes.cookie(cookie, token, False)),), private=True)
    except AccountError as exc:
        handler.close_connection = True
        routes.reply(handler, {'error': exc.message}, exc.status, private=True)
