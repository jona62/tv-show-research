"""Deterministic traffic choices; browser-only actions belong to the browser cohort."""
from copy import deepcopy
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import random
import time
from urllib.parse import urlencode, urlsplit


SHOWS = (
    (2, 'Person of Interest'), (82, 'Game of Thrones'), (123, 'Lost'),
    (169, 'Breaking Bad'), (182, 'Black Sails'), (216, 'Rick and Morty'),
    (318, 'Community'), (396, 'Gravity Falls'), (431, 'Friends'),
    (526, 'The Office'), (538, 'Futurama'), (541, 'Prison Break'),
    (563, 'Star Wars: The Clone Wars'), (919, 'Attack on Titan'),
    (1505, 'One Piece'), (2103, 'Dragon Ball Z'), (2993, 'Stranger Things'),
    (16149, 'Fleabag'), (30770, 'Chernobyl'), (37675, 'The Dragon Prince'),
    (42184, 'Primal'), (43031, 'Reacher'), (44458, 'Ted Lasso'),
    (55386, 'Krapopolis'),
)
GROUPS = ((82, 182, 123, 2, 541), (396, 216, 538, 37675, 55386),
          (431, 526, 318, 16149, 44458), (1505, 2103, 919, 42184, 563))
SEARCH_NAMES = ("Grey's Anatomy", "Bob's Burgers", 'Criminal Minds',
                'Law & Order: Special Victims Unit', 'NCIS')
GENRES = ('Medical', 'Comedy', 'Crime', 'Drama', 'Science-Fiction', 'Fantasy',
          'Mystery', 'Action', 'Adventure', 'History', 'Anime', 'Horror',
          'Romance', 'Thriller', 'Nature', 'animation', 'documentary', 'all')
JOURNEYS = {'home': 13, 'browse': 19, 'popular': 8, 'new': 7, 'search': 20,
            'detail': 13, 'compare': 12, 'lists': 6, 'account': 2}
WEIGHTS = (1, .7, .35, 0, -1)


@dataclass(frozen=True)
class Configuration:
    seed: int = 20261002
    worker_index: int = 0
    worker_count: int = 1
    think_min: float = 3
    think_max: float = 12
    warm_probability: float = .8
    auth_fraction: float = .2
    max_inflight: int = 64
    connection_model: str = 'persistent'
    retry_attempts: int = 1
    media: bool = False
    live_details: bool = False
    synthetic_identities: bool = False
    simulate_public_cache: bool = False
    accounts_path: str = ''
    metrics_directory: str = ''
    gateway_key_path: str = ''
    run_id: str = ''

    def worker_inflight(self):
        """Partition one aggregate wire budget without exceeding it."""
        if self.max_inflight < self.worker_count:
            raise ValueError('The aggregate in-flight cap must provide at least one slot per worker.')
        slots, remainder = divmod(self.max_inflight, self.worker_count)
        return slots + (self.worker_index < remainder)

    def validate(self, host, isolated=False):
        if self.think_min < 0 or self.think_max < self.think_min:
            raise ValueError('Think times must satisfy 0 <= minimum <= maximum.')
        if not 0 <= self.warm_probability <= 1 or not 0 <= self.auth_fraction <= 1 or self.max_inflight < 1:
            raise ValueError('Choose valid warm/auth fractions and a positive in-flight cap.')
        if not 0 <= self.retry_attempts <= 2:
            raise ValueError('Choose between zero and two safe-read retries.')
        if self.worker_count < 1 or not 0 <= self.worker_index < self.worker_count:
            raise ValueError('Each worker requires a unique index below the worker count.')
        self.worker_inflight()
        if self.connection_model not in ('persistent', 'pooled'):
            raise ValueError('Choose persistent or pooled connections.')
        if self.synthetic_identities or self.connection_model == 'pooled':
            hostname = urlsplit(host or '').hostname
            try:
                local = hostname == 'localhost' or ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                local = False
            signed_gateway = False
            if self.gateway_key_path:
                from gateway import key_from
                key_from(self.gateway_key_path, host)
                signed_gateway = True
            if not isolated or not (local or signed_gateway):
                raise ValueError('Synthetic identities and pooled connections require an explicitly isolated loopback target.')


def accounts_from(path):
    if not path:
        return '', []
    body = json.loads(Path(path).read_text())
    cookie, accounts = body.get('cookie_name'), body.get('accounts')
    if cookie not in ('couchside-dev-session', '__Host-couchside-session') or not isinstance(accounts, list):
        raise ValueError('Account fixtures must contain cookie_name and an accounts list.')
    for account in accounts:
        required = {'token', 'owner', 'csrf', 'state', 'revision'}
        if not isinstance(account, dict) or not required <= account.keys():
            raise ValueError('Each account needs token, owner, csrf, state and revision.')
    return cookie, accounts


def account_assignment(index, fraction):
    """Distribute unique accounts evenly: 20% selects users 4, 9, 14, ... ."""
    share = Fraction(str(fraction))
    before = index * share.numerator // share.denominator
    after = (index + 1) * share.numerator // share.denominator
    return after - 1 if after > before else None


def shown_rows(rows):
    # Library.GLANCE is six cards per row, matching the real browser pagination body.
    return [{'key': row['key'], 'ids': [show['id'] for show in row.get('items', [])[:6]],
             'tier': row.get('tier', 0)} for row in rows]


PUBLIC_CACHE_LIMITS = {'max_bytes': 20 * 1024 * 1024, 'max_records': 600, 'ttl_seconds': 300}
CARD_FIELDS = ('id', 'name', 'year', 'poster', 'art', 'genres', 'runtime', 'type',
               'summary', 'badge', 'rank', 'status', 'language')
RATINGS_FIELDS = ('id', 'sources', 'refreshing', 'dataVersion', 'revision', 'fetchedAt', 'expiresAt')
EPISODE_FIELDS = ('id', 'season', 'number', 'name', 'rating', 'rating_source', 'rating_votes',
                  'image', 'summary', 'airdate', 'airtime', 'runtime', 'url')


def finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def positive_integer(value):
    return finite_number(value) and value > 0 and int(value) == value


def valid_public_id(value):
    return positive_integer(value) and value <= 2147483647


def sorted_public_ids(values):
    """The browser batches missing public records by numeric ID, not display order."""
    return sorted({int(value) for value in values if valid_public_id(value)})


def public_fields(value, names):
    """Mirror public-data.js' scalar allowlist without retaining raw records."""
    result = {}
    for key in names:
        if key not in value:
            continue
        item = value[key]
        if item is None or isinstance(item, (str, bool, int, float)):
            result[key] = None if isinstance(item, float) and not math.isfinite(item) else item
        elif key == 'genres' and isinstance(item, list) and all(isinstance(part, str) for part in item):
            result[key] = item
    return result


def json_units(value):
    # JSON.stringify counts UTF-16 code units; Python len counts Unicode scalars.
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return len(encoded.encode('utf-16-le', errors='surrogatepass')) // 2


@dataclass(frozen=True, slots=True)
class PublicCacheEntry:
    at: float
    expires: float
    bytes: int
    version: str
    fetched_at: float | None


class SimulatedPublicCache:
    """Per-user public-cache eligibility, with metadata only and no fake HTTP events.

    Incoming card/episode records are validated using the browser's allowlist.
    Byte estimates describe the browser entry budget, not this Python map's RSS.
    No show, episode list, account state or personalized answer is retained.
    """
    def __init__(self, *, now=time.time, record=None, max_bytes=PUBLIC_CACHE_LIMITS['max_bytes'],
                 max_records=PUBLIC_CACHE_LIMITS['max_records'], ttl=PUBLIC_CACHE_LIMITS['ttl_seconds']):
        self.now, self.record = now, record
        self.max_bytes, self.max_records, self.ttl = max_bytes, max_records, ttl
        self.entries, self.used_bytes = OrderedDict(), 0

    def emit(self, kind, outcome, count=1):
        if self.record and count:
            self.record(kind, outcome, count)

    def remove(self, key, outcome):
        held = self.entries.pop(key)
        self.used_bytes -= held.bytes
        self.emit(key[0], outcome)

    def missing(self, kind, values):
        if kind not in ('card', 'ratings'):
            raise ValueError('Only public cards and complete ratings can be simulated.')
        now, missing = self.now(), []
        for sid in sorted_public_ids(values):
            key = kind, sid
            held = self.entries.get(key)
            if held and (held.at > now + 5 or now - held.at >= self.ttl or held.expires <= now):
                self.remove(key, 'expired')
                held = None
            if held:
                self.entries.move_to_end(key)
                self.emit(kind, 'hit')
            else:
                self.emit(kind, 'miss')
                missing.append(sid)
        return missing

    def entry(self, kind, value, version, now):
        try:
            return self._entry(kind, value, version, now)
        except (ValueError, TypeError, OverflowError):
            return None

    def _entry(self, kind, value, version, now):
        if not isinstance(value, dict) or not valid_public_id(value.get('id')) or value.get('refreshing') is True:
            return None
        if kind == 'card':
            if not isinstance(value.get('name'), str):
                return None
            clean = public_fields(value, CARD_FIELDS)
            units = json_units(clean)
        else:
            episodes = value.get('episodes')
            if not isinstance(episodes, list) or len(episodes) > 50000:
                return None
            # Size one episode at a time: do not copy or retain the complete array.
            units = 0
            for episode in episodes:
                if not isinstance(episode, dict) or not valid_public_id(episode.get('id')) \
                        or not positive_integer(episode.get('season')) or not positive_integer(episode.get('number')):
                    return None
                rating = episode.get('rating')
                if rating is not None and not (finite_number(rating) and 0 <= rating <= 10):
                    return None
                units += json_units(public_fields(episode, EPISODE_FIELDS))
            clean = public_fields(value, RATINGS_FIELDS)
            # Replace the closing brace with the episodes property and closing array.
            units += json_units(clean) - 1 + len(',"episodes":[]}') + max(0, len(episodes) - 1)
        source_expiry = clean.get('expiresAt')
        expires = min(now + self.ttl, source_expiry if finite_number(source_expiry) else math.inf)
        if expires <= now:
            return None
        fetched_at = clean.get('fetchedAt')
        envelope = {'key': f'{kind}:{int(value["id"])}', 'schema': 1, 'at': now * 1000,
                    'expires': expires * 1000, 'version': version, 'value': None}
        size = (json_units(envelope) - len('null') + units) * 2
        if size > self.max_bytes:
            return None
        return PublicCacheEntry(now, expires, size, version,
                                fetched_at if finite_number(fetched_at) else None)

    def put_batch(self, kind, requested, body):
        """Only a successful, valid batch can supply eligible record metadata."""
        if kind not in ('card', 'ratings'):
            raise ValueError('Only public cards and complete ratings can be simulated.')
        if not isinstance(body, dict) or not isinstance(body.get('shows'), list):
            self.emit(kind, 'invalid_batch' if body is not None else 'failed_batch')
            return
        version = body.get('catalogueVersion') or body.get('dataVersion') or ''
        if not isinstance(version, str) or len(version) > 256:
            self.emit(kind, 'invalid_batch')
            return
        if version:
            for key, held in list(self.entries.items()):
                if held.version != version:
                    self.remove(key, 'version_invalidated')
        requested = set(sorted_public_ids(requested))
        pending = set(sorted_public_ids(body.get('pending', []))) if isinstance(body.get('pending'), list) else set()
        unavailable = set(sorted_public_ids(body.get('missing', []))) if isinstance(body.get('missing'), list) else set()
        self.emit(kind, 'pending', len(requested & pending))
        self.emit(kind, 'missing_response', len(requested & unavailable))
        now, seen = self.now(), set()
        for value in body['shows']:
            sid = value.get('id') if isinstance(value, dict) else None
            if not valid_public_id(sid) or sid not in requested or sid in pending or sid in unavailable:
                self.emit(kind, 'invalid_record')
                continue
            seen.add(sid)
            entry = self.entry(kind, value, version, now)
            if entry is None:
                self.emit(kind, 'invalid_record')
                continue
            key, held = (kind, int(sid)), self.entries.get((kind, int(sid)))
            if held and entry.fetched_at is not None and held.fetched_at is not None and held.fetched_at > entry.fetched_at:
                self.emit(kind, 'older_record')
                continue
            if held:
                self.used_bytes -= held.bytes
            self.entries[key] = entry
            self.entries.move_to_end(key)
            self.used_bytes += entry.bytes
            self.emit(kind, 'stored')
        self.emit(kind, 'missing_response', len(requested - seen - pending - unavailable))
        while self.entries and (self.used_bytes > self.max_bytes or len(self.entries) > self.max_records):
            self.remove(next(iter(self.entries)), 'evicted')


class Persona:
    def __init__(self, config, index):
        self.config, self.index = config, index
        digest = hashlib.blake2b(f'{config.seed}:{index}'.encode(), digest_size=16).digest()
        self.random = random.Random(int.from_bytes(digest, 'big'))
        self.group = list(self.random.choice(GROUPS))
        self.visited, self.recent_query = [], None
        self.known_min = self.random.choice((85, 85, 60, 0))
        count = self.random.choice((0, 0, 2, 3, 5, 8))
        rated = self.random.sample(list(SHOWS), count)
        self.profile = [{'id': sid, 'weight': self.random.choice((1, .7, .35, 0, -1))}
                        for sid, _name in rated]
        self.saved = self.random.sample([sid for sid, _name in SHOWS], self.random.randrange(5))
        self.seed = digest.hex()[:16]
        self.visit = digest.hex()[16:]

    def journey(self):
        names, weights = zip(*JOURNEYS.items())
        return self.random.choices(names, weights=weights, k=1)[0]

    def show(self):
        if self.visited and self.random.random() < self.config.warm_probability:
            return self.random.choice(self.visited[-8:])
        sid = self.random.choice(self.group if self.random.random() < .65 else [s[0] for s in SHOWS])
        self.visited.append(sid)
        return sid

    def comparison(self):
        pool = self.group if self.random.random() < .6 else [s[0] for s in SHOWS]
        ids = self.random.sample(pool, self.random.randint(2, 5))
        self.random.shuffle(ids)
        mode = self.random.choice(('all', 'all', 'single'))
        view = self.random.choice(('grid', 'timeline'))
        params = {'compare': ','.join(map(str, ids)), 'mode': mode,
                  'compare-view': view, 'compare-inverted': self.random.choice((0, 1)),
                  'averages': self.random.choice((0, 1)),
                  'timeline-layout': self.random.choice(('row', 'side', 'compact')),
                  'point-style': self.random.choice(('show', 'rating', 'none')),
                  'seasons': ','.join(f'{sid}:1' for sid in ids)}
        return ids, '/compare?' + urlencode(params)

    def query(self):
        if self.recent_query and self.random.random() < self.config.warm_probability / 2:
            return self.recent_query
        sid = self.show()
        name = self.random.choice(SEARCH_NAMES) if self.random.random() < .2 else dict(SHOWS)[sid]
        style = self.random.choice(('exact', 'substring', 'reordered', 'punctuation', 'typo'))
        words = name.split()
        if style == 'substring':
            name = name[:max(3, len(name) // 2)]
        elif style == 'reordered' and len(words) > 1:
            name = ' '.join(reversed(words))
        elif style == 'punctuation':
            name = name.replace("'", '').replace(':', '').replace(',', '').replace('&', '').replace(' ', '  ')
        elif style == 'typo' and len(name) > 4:
            at = self.random.randrange(1, len(name) - 1)
            name = name[:at] + name[at + 1] + name[at] + name[at + 2:]
        self.recent_query = (style, name)
        return self.recent_query

    def body(self, **extra):
        codes = {1: '4', .7: '3', .35: '2', 0: '1', -1: '0'}
        packed = {'ids': [p['id'] for p in self.profile],
                  'weights': ''.join(codes[p['weight']] for p in self.profile)}
        return {'profile': packed, 'settings': {'known_min': self.known_min},
                'list': list(self.saved), 'day': date.today().isoformat(),
                'seed': self.seed, 'visit': self.visit, 'lang': ['en-US'], **extra}

    def state(self):
        return {'version': 3, 'profile': deepcopy(self.profile),
                'saved': [{'id': sid} for sid in self.saved],
                'settings': {'known_min': self.known_min}, 'onboarded': True}

    def absorb(self, state):
        self.profile = deepcopy(state['profile'])
        self.saved = [item['id'] for item in state['saved']]
        self.known_min = state['settings']['known_min']

    def edit_list(self):
        sid = self.show()
        if self.random.random() < .65:
            if sid in self.saved:
                self.saved.remove(sid)
            elif len(self.saved) < 200:
                self.saved.append(sid)
        else:
            self.profile = [p for p in self.profile if p['id'] != sid]
            self.profile.append({'id': sid, 'weight': self.random.choice(WEIGHTS)})
        return sid
