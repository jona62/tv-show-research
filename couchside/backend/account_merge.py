"""Guest imports add preferences without undoing choices already made in an account."""
from .account_validation import AccountError, MAX_RATED, MAX_SAVED


def merge_guest(account, guest, removals):
    """The account wins duplicates; recorded removals block old guest replays.

    Guest lists have no reliable edit dates. A signed-in edit may explicitly
    restore a removed item, but importing an old guest copy must not restore it.
    Keep removal history even when an item is added back to the account.
    """
    merged = {
        'version': 3,
        'profile': [dict(item) for item in account['profile']],
        'saved': [dict(item) for item in account['saved']],
        'settings': dict(account['settings']),
        'onboarded': account['onboarded'] or guest['onboarded'],
    }
    for kind, limit, label in (('profile', MAX_RATED, 'rated shows'), ('saved', MAX_SAVED, 'shows in My List')):
        existing = {item['id'] for item in merged[kind]}
        for item in guest[kind]:
            if item['id'] in existing or (kind, item['id']) in removals:
                continue
            if len(merged[kind]) >= limit:
                raise AccountError(409, f'Your combined list exceeds {limit:,} {label}. '
                                   'Your device list is still saved here. Remove some shows before signing in again.')
            merged[kind].append(dict(item))
            existing.add(item['id'])
    return merged


def record_removals(connection, account_id, before, after, revision, explicit):
    """Record only committed account removals, scoped to each collection and owner."""
    removed = []
    for kind in ('profile', 'saved'):
        present = {item['id'] for item in after[kind]}
        ids = {item['id'] for item in before[kind] if item['id'] not in present} | set(explicit[kind])
        removed.extend((account_id, kind, show_id, revision) for show_id in sorted(ids))
    connection.executemany('INSERT INTO account_removals VALUES (?, ?, ?, ?) '
                           'ON CONFLICT(account_id, kind, show_id) DO UPDATE SET revision=excluded.revision', removed)
