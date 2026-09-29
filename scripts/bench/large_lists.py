"""Long synthetic lists of ratings, built from the bench personas, for measuring the
recommender with hundreds or thousands of rated shows.

Nobody has published a real list of 3,000 television ratings to test with, so each
viewer here is several personas (personas.json or holdout.json) united, and each is
extended with what someone with that taste plausibly also rated:

  related     shows tied to one of its liked shows: the same franchise or creator
              (Wikidata), what the show's Wikipedia readers also look up, the same
              network and genre, or a rare Wikidata genre in the same language
  broad       well-known shows in its languages and formats that share a genre with it
  mainstream  the best-known shows of all, whatever they are
  contrast    shows tied the same ways to one of its dislikes

each drawn with a pull toward well-known shows, and rated from a spread that fits
where it came from: related shows are mostly liked, mainstream ones much more mixed,
contrasting ones mostly disliked, with lukewarm (0.35) and indifferent (0) ratings
throughout. Plot text, the recommender's strongest signal of its own, plays no part in
choosing them, so the lists are not built from the ranking they are used to judge.

A third of each persona's loves (at least one, among shows the default settings can
recommend) are held out before anything is drawn and are never rated, which makes
them the targets: rank them with the whole list, or with only its 60 most recent
ratings. The order of the list is its history, oldest first, and is shuffled, so the
most recent 60 are a sample of the whole rather than one persona.

    from large_lists import viewers
    for v in viewers(engine, 'personas.json', size=1000, count=12):
        v.profile, v.held, v.recent(60)

Everything is seeded by the persona file, the size and the viewer's number, so the same
engine and model give the same lists.
"""
from pathlib import Path
import json
import random

HERE = Path(__file__).resolve().parent
WEIGHTS = {'loves': 1, 'likes': .7, 'dislikes': -1}
# Personas united into one viewer, by list size.
PERSONAS_PER_VIEWER = {60: 2, 300: 3, 1000: 4, 3000: 6}
HELD_SHARE = 1 / 3
# Where extra ratings are drawn from, in order of preference, and what share of them.
MIX = (('related', 0.45), ('broad', 0.3), ('mainstream', 0.15), ('contrast', 0.1))
# How each source's shows are rated: (weight, chance).
RATED = {
    'related': ((1, .22), (.7, .5), (.35, .16), (0, .06), (-1, .06)),
    'broad': ((1, .08), (.7, .4), (.35, .26), (0, .13), (-1, .13)),
    'mainstream': ((1, .03), (.7, .2), (.35, .27), (0, .2), (-1, .3)),
    'contrast': ((1, .02), (.7, .05), (.35, .13), (0, .2), (-1, .6)),
}
RARE_GENRE = 0.01       # a Wikidata genre this share of shows or fewer carries is a tie
BROAD_KNOWN = 60        # broad and related-by-network shows are at least this well known
MAINSTREAM_KNOWN = 85


class Viewer:
    def __init__(self, key, personas, profile, held, sources):
        self.key, self.personas, self.profile, self.held = key, personas, profile, held
        self.sources = sources      # show id: where it came from ('core' for a persona's own)

    def recent(self, count=60):
        """The list cut to its most recent ratings."""
        return self.profile[-count:]

    def __repr__(self):
        return f'Viewer({self.key}, {len(self.profile)} rated, {len(self.held)} held out)'


def load(name):
    return json.loads((HERE / name).read_text())['personas']


class Relations:
    """What ties shows together in the catalogue's own data, apart from plot text."""

    def __init__(self, engine):
        self.e = e = engine
        f = e.facets
        self.family = {}
        if f:
            for name, (start, end) in zip(f.families, f.family_ranges):
                self.family[name] = (start, end)
        self.by_network = {}
        for i, s in enumerate(e.shows):
            if s['recommendable'] and s['channel'] and e.popularity[i] >= BROAD_KNOWN:
                self.by_network.setdefault(s['channel'], []).append(i)
        self.known = sorted((i for i, s in enumerate(e.shows) if s['recommendable'] and e.popularity[i] >= BROAD_KNOWN),
                            key=lambda i: (-e.popularity[i], e.shows[i]['id']))
        self.mainstream = [i for i in self.known if e.popularity[i] >= MAINSTREAM_KNOWN]

    def tokens(self, i, family):
        f = self.e.facets
        if not f or family not in self.family:
            return []
        start, end = self.family[family]
        return [c for c, _v in f.row(i) if start <= c < end]

    def holders(self, c):
        f = self.e.facets
        return [f.post_rows[p] for p in range(f.col_ptr[c], f.col_ptr[c + 1])]

    def related(self, i):
        """Shows tied to show i, each with how strongly: franchise and creator ties count
        most, then Wikipedia's readers, then a network and genre, then a rare genre."""
        e, out = self.e, {}
        s = e.shows[i]

        def tie(j, strength):
            if j != i and e.shows[j]['recommendable']:
                out[j] = max(out.get(j, 0.0), strength)
        for c in self.tokens(i, 'franchise'):
            for j in self.holders(c):
                tie(j, 1.0)
        for c in self.tokens(i, 'maker'):
            for j in self.holders(c):
                tie(j, 0.8)
        if e.co:
            indptr, indices, values = e.co
            for k in range(indptr[i], indptr[i + 1]):
                tie(indices[k], 0.5 + 0.4 * values[k])
        genres = set(s['genres'])
        for j in self.by_network.get(s['channel'], ()):
            if genres & set(e.shows[j]['genres']):
                tie(j, 0.4)
        common = RARE_GENRE * e.n
        f = e.facets
        for c in self.tokens(i, 'genre'):
            if f.df[c] <= common:
                for j in self.holders(c):
                    if e.shows[j]['language'] == s['language']:
                        tie(j, 0.3)
        return out


class Pool:
    """Shows to draw from ({index: strength}), each drawn by its strength and how well known
    it is, never one already taken."""

    def __init__(self, strengths, known):
        self.known = known
        self.items = sorted(strengths)
        self.weights = [strengths[i] * (0.2 + (known[i] / 100) ** 2) for i in self.items]

    def draw(self, rng, taken):
        for _try in range(24):
            if not self.items:
                return None
            i = rng.choices(self.items, self.weights)[0]
            if i not in taken:
                return i
        # Mostly taken by now: keep what is left and draw again.
        kept = [(i, w) for i, w in zip(self.items, self.weights) if i not in taken]
        self.items, self.weights = [i for i, _w in kept], [w for _i, w in kept]
        return self.draw(rng, taken) if self.items else None


def rating(rng, source):
    weights, chances = zip(*RATED[source])
    return rng.choices(weights, chances)[0]


def viewer(engine, relations, personas, size, rng, key):
    """One viewer of about size ratings from the personas given, with its held-out loves."""
    e = engine
    eligible = lambda i: e.shows[i]['recommendable'] and e.popularity[i] >= 60
    held, core, seen = [], [], set()
    for p in personas:
        loves = [s['id'] for s in p['loves'] if s['id'] in e.by_id]
        candidates = [i for i in loves if eligible(e.by_id[i])]
        count = max(1, round(HELD_SHARE * len(loves))) if candidates else 0
        held += rng.sample(candidates, min(count, len(candidates)))
    held_set = set(held)
    for p in personas:
        for role, weight in WEIGHTS.items():
            for s in p.get(role, []):
                if s['id'] in e.by_id and s['id'] not in held_set and s['id'] not in seen:
                    seen.add(s['id'])
                    core.append((s['id'], weight))
    sources = {show_id: 'core' for show_id, _w in core}
    taken = {e.by_id[i] for i in seen | held_set}
    # Every held-out love stays off the list, and so does anything counted as the same show.
    pools = {'related': {}, 'broad': {}, 'mainstream': {}, 'contrast': {}}
    liked = [e.by_id[i] for i, w in core if w > 0]
    disliked = [e.by_id[i] for i, w in core if w < 0]
    for i in liked:
        for j, strength in relations.related(i).items():
            pools['related'][j] = pools['related'].get(j, 0.0) + strength
    for i in disliked:
        for j, strength in relations.related(i).items():
            pools['contrast'][j] = pools['contrast'].get(j, 0.0) + strength
    languages = {e.shows[i]['language'] for i in liked}
    types = {e.shows[i]['type'] for i in liked}
    genres = {g for i in liked for g in e.shows[i]['genres']}
    for i in relations.known:
        s = e.shows[i]
        if s['language'] in languages and s['type'] in types and genres & set(s['genres']):
            pools['broad'][i] = 1.0
    pools['mainstream'] = {i: 1.0 for i in relations.mainstream}
    pools = {name: Pool(pool, e.popularity) for name, pool in pools.items()}
    extra = []
    want = max(0, size - len(core))
    plan = [source for source, share in MIX for _n in range(round(share * want))]
    plan += ['broad'] * (want - len(plan))
    rng.shuffle(plan)
    for source in plan:
        chosen = None
        for option in (source, 'related', 'broad', 'mainstream'):
            chosen = pools[option].draw(rng, taken)
            if chosen is not None:
                source = option
                break
        if chosen is None:
            break
        taken.add(chosen)
        show_id = e.shows[chosen]['id']
        extra.append((show_id, rating(rng, source)))
        sources[show_id] = source
    ratings = core + extra
    rng.shuffle(ratings)
    profile = [{'id': i, 'weight': w} for i, w in ratings[:size]]
    kept = {p['id'] for p in profile}
    return Viewer(key, [p['key'] for p in personas], profile, [i for i in held if i not in kept],
                  {i: sources[i] for i in kept})


def viewers(engine, name='personas.json', size=1000, count=12, seed=20260929, relations=None):
    """count viewers of about size ratings each, from the personas in the file name."""
    personas = load(name)
    relations = relations or Relations(engine)
    per = min(len(personas), PERSONAS_PER_VIEWER.get(size, max(2, min(8, size // 400 + 2))))
    out = []
    for n in range(count):
        rng = random.Random(f'{seed}:{name}:{size}:{n}')
        chosen = rng.sample(personas, per)
        out.append(viewer(engine, relations, chosen, size, rng, f'{Path(name).stem}-{size}-{n}'))
    return out
