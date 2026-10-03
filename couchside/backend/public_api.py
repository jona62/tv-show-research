"""Public catalog/episode batches shared by the native and production HTTP adapters."""
import hashlib
import json
import math
import re

from .public_data import CacheBusy, PreparedCache, prepare
from .episode_store import MAX_AGE as SUMMARY_MAX_AGE

CARDS = '/api/show-cards'
RATINGS = '/api/episode-ratings-batch'
ROUTES = frozenset((CARDS, RATINGS))
MAX_IDS = 40
MAX_AGE = 300
CARD_FIELDS = frozenset(('id', 'name', 'year', 'poster', 'genres', 'runtime', 'type', 'summary',
                         'badge', 'rank', 'rating', 'rating_source', 'popularity', 'status',
                         'language', 'seasons', 'episodes', 'total_minutes', 'minutes_estimated',
                         'newer', 'ended', 'premiered', 'url'))


def read_ids(query):
    if set(query) - {'ids', 'v'} or len(query.get('ids', [])) != 1:
        raise ValueError('Choose between 1 and 40 shows.')
    raw = query['ids'][0].split(',')
    if not 1 <= len(raw) <= MAX_IDS or any(not re.fullmatch(r'[1-9][0-9]{0,8}', value) for value in raw):
        raise ValueError('Choose between 1 and 40 valid show ids.')
    return tuple(dict.fromkeys(map(int, raw)))


class PublicAPI:
    def __init__(self, library, ratings, catalogue_version, known=None, cache=None, cards_for_missing=None):
        self.library, self.ratings = library, ratings
        self.catalogue_version = str(catalogue_version)
        self.known = known or (lambda show_id: show_id in library.e.by_id)
        self.cache = cache or PreparedCache()
        self.cards_for_missing = cards_for_missing

    def newer_cards(self, ids):
        """Read already cached public metadata; the callback must never fetch providers."""
        if not ids or self.cards_for_missing is None:
            return ()
        allowed, found = set(ids), {}
        for value in self.cards_for_missing(ids):
            if (isinstance(value, dict) and type(value.get('id')) is int
                    and value['id'] in allowed and isinstance(value.get('name'), str)):
                found[value['id']] = {**{key: value[key] for key in CARD_FIELDS if key in value},
                                      'match': None}
        return tuple(found[show_id] for show_id in ids if show_id in found)

    def get(self, path, query):
        if path not in ROUTES:
            return None
        # Cards are catalog entries; newer live shows can have cached episode
        # data but cannot be represented by Library.cards until the next model.
        ids = read_ids(query)
        extra = self.newer_cards(tuple(show_id for show_id in ids if show_id not in self.library.e.by_id)) if path == CARDS else ()
        extra_ids = {show['id'] for show in extra}
        known = (lambda show_id: show_id in self.library.e.by_id or show_id in extra_ids) if path == CARDS else self.known
        missing = tuple(show_id for show_id in ids if not known(show_id))
        available = tuple(show_id for show_id in ids if show_id not in missing)
        revision = (self.ratings.store.sync_metadata() if path == CARDS
                    else self.ratings.store.record_revisions(ids))
        extra_version = hashlib.sha256(json.dumps(extra, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24] if extra else ''
        key = (path, self.catalogue_version, revision, ids, extra_version)
        try:
            return self.cache.get(key, lambda: self.cards(available, missing, extra) if path == CARDS else self.episodes(available, missing))
        except (CacheBusy, TimeoutError):
            return prepare({'error': 'Public show data is loading. Try again in a moment.'}, status=503)

    def cards(self, ids, missing=(), extra=()):
        cards = {show['id']: show for show in (*self.library.cards(ids), *extra)}
        shows = [cards[show_id] for show_id in ids if show_id in cards]
        # No profile, saved list, match score or cookie enters this method.
        now = self.ratings.clock()
        deadlines = [row['at'] + SUMMARY_MAX_AGE - now for show_id in ids
                     if (row := self.ratings.store.summaries.get(show_id))
                     and row['at'] + SUMMARY_MAX_AGE > now]
        ttl = min([MAX_AGE, *(math.floor(seconds) for seconds in deadlines)])
        return prepare({'shows': shows, 'catalogueVersion': self.catalogue_version, 'missing': list(missing)},
                       ttl if not missing else 0)

    def episodes(self, ids, missing=()):
        result = self.ratings.batch(ids)
        identity = '|'.join(f"{show['id']}:{show['revision']}" for show in result['shows'])
        version = hashlib.sha256((self.catalogue_version + '|' + identity).encode()).hexdigest()[:24]
        result.update({'catalogueVersion': self.catalogue_version, 'version': version, 'missing': list(missing)})
        complete = not missing and not result['pending'] and not any(show['refreshing'] for show in result['shows'])
        ttl = min([MAX_AGE, *(math.floor(show['expiresAt'] - self.ratings.clock()) for show in result['shows'])])
        return prepare(result, max(0, ttl) if complete else 0)
