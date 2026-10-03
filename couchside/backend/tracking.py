"""Authenticated, incremental watch tracking with conditional atomic Undo."""
import hashlib
import json
import re

from .accounts import NO_CSRF
from .account_validation import AccountError, revision as valid_revision
from .tracking_catalogue import bulk_episodes, identifier, snapshot
from . import tracking_store as store


INTENTS = ('watching', 'paused', 'completed', 'dropped')
OPERATION_ID = re.compile(r'[A-Za-z0-9_.:-]{8,128}')
COMMON = {'operation_id', 'base_revision', 'show_id', 'action'}
DETAILS = {
    'intent': {'intent', 'progress_known'}, 'episode': {'episode_id', 'watched', 'establish_progress'},
    'replace': {'through_episode_id', 'catalogue_revision'}, 'all': {'catalogue_revision'},
    'remove': set(), 'undo': {'target_operation_id'},
}
MAX_SHOWS = 5000


def validate(payload):
    invalid = AccountError(400, 'The viewing-progress request is invalid.')
    if not isinstance(payload, dict) or not isinstance(payload.get('action'), str) or payload['action'] not in DETAILS:
        raise invalid
    if set(payload) - COMMON - DETAILS[payload['action']] or not COMMON <= set(payload):
        raise invalid
    if not isinstance(payload['operation_id'], str) or not OPERATION_ID.fullmatch(payload['operation_id']):
        raise invalid
    valid_revision(payload['base_revision'])
    identifier(payload['show_id'])
    action = payload['action']
    if action == 'intent' and payload.get('intent') not in INTENTS:
        raise invalid
    for key in ('progress_known', 'watched', 'establish_progress'):
        if key in payload and type(payload[key]) is not bool:
            raise invalid
    if action == 'episode':
        identifier(payload.get('episode_id'), 'episode')
        if 'watched' not in payload:
            raise invalid
    if action in ('replace', 'all'):
        if not isinstance(payload.get('catalogue_revision'), str) or not 1 <= len(payload['catalogue_revision']) <= 128:
            raise invalid
    if action == 'replace':
        if 'through_episode_id' not in payload:
            raise invalid
        if payload['through_episode_id'] is not None:
            identifier(payload['through_episode_id'], 'episode')
    if action == 'undo' and (not isinstance(payload.get('target_operation_id'), str)
                             or not OPERATION_ID.fullmatch(payload['target_operation_id'])):
        raise invalid
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class TrackingService:
    def __init__(self, accounts, catalogue, authorize):
        self.accounts, self.provider, self.authorize = accounts, catalogue, authorize
        self.clock = accounts.clock
        with accounts.store.connection() as connection:
            connection.executescript(store.SCHEMA)

    def _owner(self, connection, token, csrf=NO_CSRF):
        row = self.accounts._session_row(connection, token, csrf)
        if not self.authorize(connection, row):
            raise AccountError(403, 'Watch tracking is unavailable for this account.')
        return row['id']

    def read(self, token):
        with self.accounts.store.connection() as connection:
            connection.execute('BEGIN')
            account_id = self._owner(connection, token)
            return store.response(connection, account_id)

    def catalogue(self, token, show_id):
        identifier(show_id)
        with self.accounts.store.connection() as connection:
            account_id = self._owner(connection, token)
        # Catalogue retrieval may contact a provider. It never holds the account
        # writer lock, and authorization is rechecked before returning anything.
        value = snapshot(self.provider(show_id), show_id, self.clock())
        with self.accounts.store.connection() as connection:
            self._owner(connection, token)
        return {'user_id': account_id, **value}

    @staticmethod
    def _receipt(connection, account_id, payload, accepted):
        return {**store.response(connection, account_id), 'operation_id': payload['operation_id'],
                'operation_revision': accepted['revision'],
                'undo': {'operation_id': payload['operation_id'], 'show_id': payload['show_id']}
                if json.loads(accepted['undo_json']) is not None and payload['action'] != 'undo' else None}

    def _replay(self, connection, account_id, payload, request_hash):
        accepted = store.operation(connection, account_id, payload['operation_id'])
        if accepted is None:
            return None
        if accepted['request_hash'] != request_hash:
            raise AccountError(409, 'That viewing-progress operation was already used for a different change.',
                               data=store.response(connection, account_id))
        return self._receipt(connection, account_id, payload, accepted)

    def mutate(self, token, csrf, payload):
        request_hash = validate(payload)
        with self.accounts.store.connection() as connection:
            connection.execute('BEGIN')
            account_id = self._owner(connection, token, csrf)
            replay = self._replay(connection, account_id, payload, request_hash)
            if replay is not None:
                return replay
        catalogue = None
        if payload['action'] not in ('remove', 'undo'):
            catalogue = snapshot(self.provider(payload['show_id']), payload['show_id'], self.clock())
        with self.accounts.store.connection(write=True) as connection:
            account_id = self._owner(connection, token, csrf)
            replay = self._replay(connection, account_id, payload, request_hash)
            if replay is not None:
                return replay
            current_revision = store.revision(connection, account_id)
            if payload['base_revision'] != current_revision:
                raise AccountError(409, 'Viewing progress changed on another device. Review its latest version and try again.',
                                   data=store.response(connection, account_id))
            current, states = store.show(connection, account_id, payload['show_id'])
            try:
                fields, marks = self._changes(connection, account_id, payload, current, states, catalogue)
            except AccountError as exc:
                if exc.status == 409:
                    exc.data = {**store.response(connection, account_id), **(exc.data or {})}
                raise
            if current['deleted'] and not fields.get('deleted', current['deleted']):
                count = connection.execute('SELECT count(*) FROM account_show_tracking WHERE account_id=? AND deleted=0',
                                           (account_id,)).fetchone()[0]
                if count >= MAX_SHOWS:
                    raise AccountError(400, 'Your viewing history has reached its show limit.')
            undo = store.commit(connection, account_id, payload['show_id'], current, states, fields, marks,
                                current_revision + 1, self.clock())
            accepted_revision = current_revision + 1 if undo is not None else current_revision
            store.remember(connection, account_id, payload, request_hash, accepted_revision, undo)
            accepted = store.operation(connection, account_id, payload['operation_id'])
            return self._receipt(connection, account_id, payload, accepted)

    def _changes(self, connection, account_id, payload, current, states, catalogue):
        action = payload['action']
        if action == 'undo':
            return self._undo(connection, account_id, payload, current, states)
        if action == 'remove':
            return {'deleted': 1}, {episode_id: 0 for episode_id in states}
        fields = {'deleted': 0, 'intent': current['intent'] or 'watching'}
        if action == 'intent':
            fields['intent'] = payload['intent']
            if 'progress_known' in payload:
                fields['progress_known'] = int(payload['progress_known'])
            if fields['intent'] == 'completed' and fields.get('progress_known', current['progress_known']):
                released_ids = [e['id'] for e in catalogue['episodes'] if e['released'] is True]
                if (not catalogue['fresh'] or not catalogue['complete'] or not released_ids
                        or any(e['released'] is None for e in catalogue['episodes'])
                        or any(not states.get(episode_id, {}).get('watched') for episode_id in released_ids)):
                    raise AccountError(400, 'Choose Finished with unknown progress, or mark all released episodes watched first.')
            return fields, {}
        if action == 'episode':
            episode = next((e for e in catalogue['episodes'] if e['id'] == payload['episode_id']), None)
            if episode is None:
                raise AccountError(400, 'That episode does not belong to this show.')
            if payload['watched'] and episode['released'] is not True:
                raise AccountError(400, 'This episode is not known to have been released yet.')
            if not current['progress_known']:
                if payload.get('establish_progress') is not True:
                    raise AccountError(400, 'Set exact episode progress before changing individual episodes.')
                fields['progress_known'] = 1
            if current['intent'] == 'completed' and (not payload['watched'] or not current['progress_known']):
                fields['intent'] = 'watching'
            return fields, {payload['episode_id']: int(payload['watched'])}
        released_episodes = bulk_episodes(catalogue, payload['catalogue_revision'])
        fields['progress_known'] = 1
        if action == 'all':
            exact_completion = (catalogue['ended'] and released_episodes
                                and all(e['released'] is True for e in catalogue['episodes']))
            fields['intent'] = 'completed' if exact_completion else 'watching'
            return fields, {e['id']: 1 for e in released_episodes}
        through = payload['through_episode_id']
        position = next((index for index, e in enumerate(released_episodes) if e['id'] == through), None)
        if through is not None and position is None:
            raise AccountError(400, 'Select a released episode from this show.')
        position = -1 if through is None else position
        if current['intent'] == 'completed' and position < len(released_episodes) - 1:
            fields['intent'] = 'watching'
        return fields, {e['id']: int(index <= position) for index, e in enumerate(released_episodes)}

    @staticmethod
    def _undo(connection, account_id, payload, current, states):
        target = store.operation(connection, account_id, payload['target_operation_id'])
        if target is None or target['show_id'] != payload['show_id']:
            raise AccountError(400, 'That viewing-progress change is unavailable to undo.')
        undo = json.loads(target['undo_json'])
        if undo is None:
            return {}, {}
        affected_fields = any(current[key + '_revision'] != target['revision'] for key in undo['fields'])
        affected_marks = any(states.get(int(episode_id), {}).get('revision') != target['revision']
                             for episode_id in undo['episodes'])
        if affected_fields or affected_marks:
            raise AccountError(409, 'A later change affected this progress. Review the latest version before editing it.',
                               data=store.response(connection, account_id))
        return undo['fields'], {int(episode_id): watched for episode_id, watched in undo['episodes'].items()}
