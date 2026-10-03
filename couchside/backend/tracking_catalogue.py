"""A released-episode snapshot for explicit, finite watch-progress commands."""
from datetime import date, datetime, timezone
import math

from .account_validation import AccountError, MAX_ID


MAX_EPISODES = 20000


def identifier(value, label='show'):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise AccountError(400, f'The {label} ID is invalid.')
    return value


def released(episode, now):
    """Today without a precise time is uncertain, rather than already watched."""
    stamp = episode.get('airstamp')
    if isinstance(stamp, str) and stamp:
        try:
            value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if value.tzinfo is not None:
                return value.timestamp() <= now
        except (ValueError, OverflowError, OSError):
            pass
    airdate = episode.get('airdate')
    try:
        day = date.fromisoformat(airdate)
    except (TypeError, ValueError):
        return None
    today = datetime.fromtimestamp(now, timezone.utc).date()
    return True if day < today else False if day > today else None


def snapshot(raw, show_id, now):
    """Provider output is validated before it can establish episode ownership."""
    if (not isinstance(raw, dict) or type(raw.get('id')) is not int or raw['id'] != show_id
            or not isinstance(raw.get('episodes'), list)
            or len(raw['episodes']) > MAX_EPISODES
            or not isinstance(raw.get('revision'), str) or not raw['revision']
            or len(raw['revision']) > 128):
        raise AccountError(503, 'Episode details are unavailable. Please try again shortly.', retry_after=5)
    seen, episodes = set(), []
    for episode in raw['episodes']:
        if not isinstance(episode, dict):
            raise AccountError(503, 'Episode details are unavailable. Please try again shortly.', retry_after=5)
        try:
            episode_id = identifier(episode.get('id'), 'episode')
        except AccountError:
            raise AccountError(503, 'Episode details are unavailable. Please try again shortly.', retry_after=5) from None
        if (episode_id in seen or type(episode.get('season')) is not int or episode['season'] <= 0
                or type(episode.get('number')) is not int or episode['number'] <= 0):
            raise AccountError(503, 'Episode details are unavailable. Please try again shortly.', retry_after=5)
        seen.add(episode_id)
        episodes.append({**episode, 'released': released(episode, now)})
    expires = raw.get('expiresAt')
    expires = expires if type(expires) in (int, float) and math.isfinite(expires) and expires >= 0 else None
    fresh = expires is not None and expires > now
    return {
        'show_id': show_id, 'catalogue_revision': raw['revision'],
        'episodes': sorted(episodes, key=lambda e: (e['season'], e['number'], e['id'])),
        'fresh': fresh, 'expires_at': expires, 'complete': raw.get('complete', True) is True,
        'ended': raw.get('ended') is True,
    }


def bulk_episodes(catalogue, revision):
    if (revision != catalogue['catalogue_revision'] or not catalogue['fresh']
            or not catalogue['complete']):
        raise AccountError(409, 'Episode details changed or need refreshing. Review the latest episodes and try again.',
                           data={'catalogue_changed': True, 'catalogue': catalogue})
    return [episode for episode in catalogue['episodes'] if episode['released'] is True]
