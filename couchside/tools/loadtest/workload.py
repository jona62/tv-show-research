"""Deterministic traffic choices; browser-only actions belong to the browser cohort."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import hashlib
import ipaddress
import json
from pathlib import Path
import random
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
    accounts_path: str = ''
    metrics_directory: str = ''

    def validate(self, host, isolated=False):
        if self.think_min < 0 or self.think_max < self.think_min:
            raise ValueError('Think times must satisfy 0 <= minimum <= maximum.')
        if not 0 <= self.warm_probability <= 1 or not 0 <= self.auth_fraction <= 1 or self.max_inflight < 1:
            raise ValueError('Choose valid warm/auth fractions and a positive in-flight cap.')
        if not 0 <= self.retry_attempts <= 2:
            raise ValueError('Choose between zero and two safe-read retries.')
        if self.worker_count < 1 or not 0 <= self.worker_index < self.worker_count:
            raise ValueError('Each worker requires a unique index below the worker count.')
        if self.connection_model not in ('persistent', 'pooled'):
            raise ValueError('Choose persistent or pooled connections.')
        if self.synthetic_identities or self.connection_model == 'pooled':
            hostname = urlsplit(host or '').hostname
            try:
                local = hostname == 'localhost' or ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                local = False
            if not isolated or not local:
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
