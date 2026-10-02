"""Freshness between visits: what changes from one visit to the next, and what stays.

Nothing here draws random numbers at request time or reads the server's clock. The
browser sends the day (its local date, rolling over at 04:00) and a seed it derives
from that day and a salt it never sends, so the same inputs always give the same page,
a new day gives a different one, and two people's pages differ. Couchside also sends a
visit: a second seed, from the salt, the day and how many times the app was opened that
day, so each time it is opened the page is its own, while every request of one visit
still gives the same page. The browser also sends how often it has shown each title
lately, as a count that halves every seven days, and which titles it engaged with
(opened, rated, listed, hid) in the last fourteen days. With a visit, each earlier visit
the same day that showed a title, among its cards or as its hero, adds half a day's
showing to its count, a whole day's at most, and the heroes of those visits rest with
those of the last week. All of it is fixed when the visit begins, so nothing a visit
shows changes its own page.

- ``dither`` shows a ranking by the key ln(rank) + LAMBDA ln(1 + seen) + EPSILON z,
  with z a normal deviate keyed by the seed, the surface and the title. With a visit,
  VISIT of z's variance is the visit's own and the rest the day's, so the visits of one
  day share most of their order and each moves it a little, however many there are.
  The first PINNED places take no noise, so the strongest picks stay put while fatigue
  still applies, and nothing ranked below DEPTH times the list length can surface.
  This is Dunning's dithering with YouTube's top-M limit; LinkedIn and Yahoo found
  fatigue bites over the first few impressions and a week is the useful memory.
- ``rotate`` draws the first places of a list that greets each visit afresh
  (Couchside's Top picks) from its best LEAD_TOP, by rank and fatigue with weight
  1/rank^LEAD_STEEP: the best still leads most visits, and the strongest after it take
  turns beside it rather than the same few standing there all day.
- ``explore`` fills a couple of labelled places from a little further down.
- ``pick_one`` draws a hero from the top few with weight 1/rank (a seeded Gumbel draw,
  the visit's own when there is one), leaving out titles that were the hero lately.
- ``spread`` discounts a repeated network or franchise within a row by
  0.75 x 0.5^k + 0.25 for its k-th repeat, as X does for repeated authors.
- ``shuffle_rows`` keeps the first rows in place and reorders the rest by
  ln(rank) + ROW_EPSILON z, sending rows the person keeps passing over to the end.

A request without a day and seed gets no noise at all, so tests and the benchmark see
the plain ranking, and one without a visit gets the day's page, as Next Watch asks for
it. Engaged titles take no fatigue.
"""
from datetime import date
from statistics import NormalDist
import hashlib
import math
import re

PINNED = 5          # places at the top that take no noise
LAMBDA = 0.35       # how hard fatigue pushes a title down, per ln(1 + seen)
EPSILON = 0.35      # how far a day's noise moves a title, in ln(rank)
VISIT = 0.35        # the share of that noise's variance that is a visit's own, the rest the day's
DEPTH = 3           # nothing ranked below DEPTH x the list length is shown
ROW_EPSILON = 0.3   # the same for whole rows
FIXED_ROWS = 2      # rows that keep their places
HERO_TOP = 10       # a hero is drawn from the best this many
LEAD_TOP = 10       # a list that rotates its first places draws them from the best this many
LEAD_STEEP = 2.5    # with weight 1/rank to this power, so the best leads about three visits in four
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
    """One request's freshness: its day and seed, its visit, and what the browser has shown."""

    def __init__(self, day=None, seed=None, seen=None, engaged=(), resting=(), tired=(), visit=None):
        self.day, self.seed, self.visit = day, seed, visit
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
        """A normal deviate fixed by the seed, the surface and the key; zero without a seed.
        With a visit it blends the day's deviate and the visit's, VISIT of the variance the
        visit's. It is still a standard normal, so a visit's page lies as far from the plain
        ranking as a day's did, while the visits of one day lie nearer each other than two
        days do."""
        if not self.seed:
            return 0.0
        day = NORMAL.inv_cdf(uniform(self.seed, surface, key))
        if not self.visit:
            return day
        return math.sqrt(1 - VISIT) * day + math.sqrt(VISIT) * NORMAL.inv_cdf(uniform(self.visit, surface, key))

    def gumbel(self, surface, key):
        """A Gumbel deviate for a draw, fixed by the surface, the key and the visit's seed,
        or the day's without a visit, so each visit draws its hero afresh."""
        seed = self.visit or self.seed
        if not seed:
            return 0.0
        return -math.log(-math.log(uniform(seed, surface, key)))

    def echo(self):
        return {'day': self.day, 'seed': self.seed, **({'visit': self.visit} if self.visit else {})}


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
    visit = body.get('visit')
    if visit is not None and (not isinstance(visit, str) or not SEED.match(visit)):
        raise ValueError('Send the visit as 16 hexadecimal digits.')
    if visit is not None and seed is None:
        raise ValueError('Send the visit with its day and seed.')
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
                 keys(body, 'tired', MAX_TIRED), visit)


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


def dither(ranked, fresh, surface, length, pinned=PINNED, rotating=0):
    """The first ``length`` of ``ranked`` (show ids, best first) to show today, in order.
    The best ``pinned`` by rank and fatigue alone come first; the rest are drawn from the
    top DEPTH x length by rank, fatigue and the day's noise. With a visit, a list that
    rotates its first ``rotating`` places draws them for the visit instead (rotate)."""
    if not fresh:
        return list(ranked[:length])
    pool = list(ranked[:DEPTH * length])
    steady = steadiness(pool, fresh)
    if rotating and fresh.visit:
        head = rotate(pool, fresh, surface, min(rotating, length))
    else:
        head = sorted(pool, key=lambda i: (steady[i], pool.index(i)))[:pinned]
    taken = set(head)
    rest = sorted((i for i in pool if i not in taken),
                  key=lambda i: (steady[i] + EPSILON * fresh.z(surface, i), i))
    return head + rest[:length - len(head)]


def steadiness(ranked, fresh):
    """Each title's key by rank and fatigue alone, ln(rank) + LAMBDA ln(1 + seen): lower first."""
    return {i: math.log(n + 1) + LAMBDA * math.log1p(fresh.fatigue(i)) for n, i in enumerate(ranked)}


def rotate(ranked, fresh, surface, places):
    """The first ``places`` of ``ranked`` for this visit, in order, drawn from its best
    LEAD_TOP by rank and fatigue: each next place goes to one of those left with weight
    1/rank^LEAD_STEEP, less for a title shown lately (a seeded Gumbel draw, as pick_one's
    for the hero). Over the bench personas' visits the best leads three in four, the best
    three are all among the first six more than nine times in ten, and one or two of the
    six are new each visit. Without a seed, the best by rank and fatigue."""
    steady = steadiness(ranked, fresh)
    best = sorted(ranked, key=lambda i: (steady[i], ranked.index(i)))[:max(LEAD_TOP, places)]
    if not fresh.seed:
        return best[:places]
    return sorted(best, key=lambda i: (LEAD_STEEP * steady[i] - fresh.gumbel(surface + '-lead', i), i))[:places]


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
    """One id from the best ``top`` of ``ranked``, drawn with weight 1/rank by the visit's
    seed (the day's without a visit), never one resting as a recent hero or in ``avoid``.
    Without a seed, the best."""
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
