"""Freshness between visits: what changes from one day to the next, and what stays.

Nothing here draws random numbers at request time or reads the server's clock. The
browser sends the day (its local date, rolling over at 04:00) and a seed it derives
from that day and a salt it never sends, so the same inputs always give the same page,
a new day gives a different one, and two people's pages differ. The browser also sends
how often it has shown each title lately, as a count that halves every seven days, and
which titles it engaged with (opened, rated, listed, hid) in the last fourteen days.

- ``dither`` shows a ranking by the key ln(rank) + LAMBDA ln(1 + seen) + EPSILON z,
  with z a normal deviate keyed by the seed, the surface and the title. The first
  PINNED places take no noise, so the strongest picks stay put while fatigue still
  applies, and nothing ranked below DEPTH times the list length can surface. This is
  Dunning's dithering with YouTube's top-M limit; LinkedIn and Yahoo found fatigue
  bites over the first few impressions and a week is the useful memory.
- ``explore`` fills a couple of labelled places from a little further down.
- ``pick_one`` draws a hero from the top few with weight 1/rank (a seeded Gumbel draw),
  leaving out titles that were the hero lately.
- ``spread`` discounts a repeated network or franchise within a row by
  0.75 x 0.5^k + 0.25 for its k-th repeat, as X does for repeated authors.
- ``shuffle_rows`` keeps the first rows in place and reorders the rest by
  ln(rank) + ROW_EPSILON z, sending rows the person keeps passing over to the end.

A request without a day and seed gets no noise at all, so tests and the benchmark see
the plain ranking. Engaged titles take no fatigue.
"""
from datetime import date
from statistics import NormalDist
import hashlib
import math
import re

PINNED = 5          # places at the top that take no noise
LAMBDA = 0.35       # how hard fatigue pushes a title down, per ln(1 + seen)
EPSILON = 0.35      # how far a day's noise moves a title, in ln(rank)
DEPTH = 3           # nothing ranked below DEPTH x the list length is shown
ROW_EPSILON = 0.3   # the same for whole rows
FIXED_ROWS = 2      # rows that keep their places
HERO_TOP = 10       # a hero is drawn from the best this many
MAX_SEEN = 300      # titles a request may report as seen
MAX_ENGAGED = 300
MAX_RESTING = 60
MAX_TIRED = 40
MOST_SEEN = 50.0    # a decayed count cannot honestly exceed this

DAY = re.compile(r'\d{4}-\d{2}-\d{2}$')
SEED = re.compile(r'[0-9a-f]{16}$')
ROW_KEY = re.compile(r'[a-z0-9-]{1,60}$')
NORMAL = NormalDist()


class Fresh:
    """One request's freshness: its day and seed, and what the browser has shown."""

    def __init__(self, day=None, seed=None, seen=None, engaged=(), resting=(), tired=()):
        self.day, self.seed = day, seed
        self.seen = dict(seen or {})
        self.engaged = frozenset(engaged)
        self.resting = frozenset(resting)
        self.tired = frozenset(tired)

    def __bool__(self):
        return bool(self.seed or self.seen)

    def fatigue(self, show_id):
        """The decayed count of recent days a title was shown, or zero once engaged."""
        return 0.0 if show_id in self.engaged else self.seen.get(show_id, 0.0)

    def z(self, surface, key):
        """A normal deviate fixed by the seed, the surface and the key; zero without a seed."""
        if not self.seed:
            return 0.0
        return NORMAL.inv_cdf(uniform(self.seed, surface, key))

    def gumbel(self, surface, key):
        if not self.seed:
            return 0.0
        return -math.log(-math.log(uniform(self.seed, surface, key)))

    def echo(self):
        return {'day': self.day, 'seed': self.seed}


def uniform(seed, surface, key):
    """A number strictly between 0 and 1 from blake2b of seed, surface and key."""
    digest = hashlib.blake2b(f'{seed}|{surface}|{key}'.encode(), digest_size=8).digest()
    return (int.from_bytes(digest, 'big') + 0.5) / 2 ** 64


def parse(body):
    """A Fresh from a request body. Everything is optional; anything malformed raises
    ValueError with a message fit to show."""
    if not isinstance(body, dict):
        return Fresh()
    day, seed = body.get('day'), body.get('seed')
    if day is not None:
        if not isinstance(day, str) or not DAY.match(day):
            raise ValueError('Send the day as YYYY-MM-DD.')
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError('Send the day as YYYY-MM-DD.') from None
    if seed is not None and (not isinstance(seed, str) or not SEED.match(seed)):
        raise ValueError('Send the seed as 16 hexadecimal digits.')
    if (day is None) != (seed is None):
        raise ValueError('Send the day and the seed together.')
    seen = body.get('seen', {})
    if not isinstance(seen, dict) or len(seen) > MAX_SEEN:
        raise ValueError(f'Report up to {MAX_SEEN} seen shows.')
    counts = {}
    for key, value in seen.items():
        if not isinstance(key, str) or not key.isdigit() or len(key) > 9:
            raise ValueError('Seen shows must be keyed by their id.')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MOST_SEEN \
                or value != value:
            raise ValueError('A seen count must be a number from 0 to 50.')
        if value > 0:
            counts[int(key)] = float(value)
    return Fresh(day, seed, counts, ids(body, 'engaged', MAX_ENGAGED), ids(body, 'resting', MAX_RESTING),
                 keys(body, 'tired', MAX_TIRED))


def ids(body, name, most):
    values = body.get(name, [])
    if not isinstance(values, list) or len(values) > most or any(type(v) is not int or v < 0 for v in values):
        raise ValueError(f'Send {name} as a list of up to {most} show ids.')
    return values


def keys(body, name, most):
    values = body.get(name, [])
    if not isinstance(values, list) or len(values) > most or \
            any(not isinstance(v, str) or not ROW_KEY.match(v) for v in values):
        raise ValueError(f'Send {name} as a list of up to {most} row keys.')
    return values


def dither(ranked, fresh, surface, length, pinned=PINNED):
    """The first ``length`` of ``ranked`` (show ids, best first) to show today, in order.
    The best ``pinned`` by rank and fatigue alone come first; the rest are drawn from the
    top DEPTH x length by rank, fatigue and the day's noise."""
    if not fresh:
        return list(ranked[:length])
    pool = list(ranked[:DEPTH * length])
    steady = {i: math.log(n + 1) + LAMBDA * math.log1p(fresh.fatigue(i)) for n, i in enumerate(pool)}
    by_steady = sorted(pool, key=lambda i: (steady[i], pool.index(i)))
    head = by_steady[:pinned]
    taken = set(head)
    rest = sorted((i for i in pool if i not in taken),
                  key=lambda i: (steady[i] + EPSILON * fresh.z(surface, i), i))
    return head + rest[:length - len(head)]


def explore(shown, ranked, fresh, surface, places=(12, 20), window=(25, 72), allowed=None):
    """Put a title from ranks ``window`` (1-based, inclusive) at each 1-based place in
    ``places``, chosen by the day's noise and fatigue, keeping the list's length.
    Returns the new list and the set of ids placed this way."""
    if not fresh or not fresh.seed:
        return list(shown), set()
    lo, hi = window
    have = set(shown)
    options = [i for i in ranked[lo - 1:hi] if i not in have and (allowed is None or allowed(i))]
    options.sort(key=lambda i: (LAMBDA * math.log1p(fresh.fatigue(i)) + EPSILON * fresh.z(surface + '-explore', i), i))
    out, placed = list(shown), set()
    for place, choice in zip(places, options):
        if place <= len(out):
            out.insert(place - 1, choice)
            out.pop()
            placed.add(choice)
    return out, placed


def pick_one(ranked, fresh, surface, top=HERO_TOP, avoid=()):
    """One id from the best ``top`` of ``ranked``, drawn with weight 1/rank by the day's
    seed, never one resting as a recent hero or in ``avoid``. Without a seed, the best."""
    avoid = set(avoid) | set(fresh.resting)
    pool = [i for i in ranked if i not in avoid][:top] or list(ranked[:1])
    if not pool:
        return None
    if not fresh.seed:
        return pool[0]
    return max(enumerate(pool), key=lambda ni: (-math.log(ni[0] + 1) + fresh.gumbel(surface, ni[1]), -ni[0]))[1]


def spread(items, group_of, fresh=None, keep=0):
    """Reorder ``items`` so a network or franchise that repeats is spread out: the k-th
    repeat of a group (from 0) has its rank weight multiplied by 0.75 x 0.5^k + 0.25.
    The first ``keep`` items stay where they are."""
    head, tail = list(items[:keep]), list(items[keep:])
    counts = {}
    for i in head:
        for group in group_of(i) or ():
            counts[group] = counts.get(group, 0) + 1
    keyed = []
    for n, i in enumerate(tail):
        groups = group_of(i) or ()
        weight = min((0.75 * 0.5 ** counts.get(g, 0) + 0.25 for g in groups), default=1.0)
        for g in groups:
            counts[g] = counts.get(g, 0) + 1
        keyed.append((math.log(n + keep + 1) - math.log(weight), n, i))
    keyed.sort()
    return head + [i for _k, _n, i in keyed]


def shuffle_rows(rows, fresh, key_of, fixed=FIXED_ROWS):
    """Rows in today's order: the first ``fixed`` stay; the rest reorder by
    ln(rank) + ROW_EPSILON z, and rows the person keeps passing over go last."""
    if not fresh:
        return list(rows)
    head, tail = list(rows[:fixed]), list(rows[fixed:])
    keyed = sorted(((key_of(r) in fresh.tired, math.log(n + fixed + 1) + ROW_EPSILON * fresh.z('rows', key_of(r)), n)
                    for n, r in enumerate(tail)))
    return head + [tail[n] for _tired, _k, n in keyed]
