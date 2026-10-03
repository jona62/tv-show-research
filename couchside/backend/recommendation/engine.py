"""The recommender: closeness over TVmaze plot text, themes and genres, and taste.

It answers what to watch next, what a taste profile looks like, and how a pick
connects to it. A pick has to sit close to shows you liked (plot wording, themes,
genres) and fit what your whole list leans toward (taste.py); a list that holds
several interests has each scored on its own and given its share (Ranking). A list
longer than DENSE_MAX, up to MAX_LIST, is ranked from each rated show's closest shows
instead (Wide), which scales to thousands of ratings. The research-only outputs
(scatter axes, pairwise matrices, catalog correlations) live in site/.
"""
from array import array
from functools import lru_cache
from operator import add, itemgetter, mul
from pathlib import Path
import gzip
import json
import math
import re
import struct
import sys
try:
    import numpy as np
except ImportError:
    np = None

from . import facets, fresh, neighbours
from .taste import Attributes, Taste, STRENGTH, QUALITY, bits as taste_bits, clamp
from .titles import Titles

RATINGS = (-1, 0, .35, .7, 1)
# People who watch a lot of television have seen three or four thousand shows.
MAX_LIST = 3000
# A list may also travel as {"ids": [...], "weights": "43..."}: its show ids, and one
# character a rating in the same order, about a quarter of the bytes of a list of
# objects (19 KB for 3,000 shows against 75 KB). transfer.js packs it (packList).
CODES = {'4': 1, '3': .7, '2': .35, '1': 0, '0': -1}
# A list rating at most this many shows, the old limit, is ranked exactly as it always
# was: from how close every show sits to each rated one. Past it that is out of reach
# (about 20 ms and 360 KB a rated show), so a longer list is ranked from each rated
# show's closest shows (Wide), which the bench's long lists also ranked better.
DENSE_MAX = 60
TOP_PICKS = 24
# Two places go to shows from a little further down the ranking (fresh.explore), but
# only to one scoring at least this share of the last pick the plain ranking shows: a
# step to the side, not a step down. Measured against the best pick instead, half its
# score shut ranks 25 to 72 out of most lists, since the best stands well clear of the
# rest (the 24th scores a median 0.43 of it over the bench personas).
DIFFERENT_FLOOR = 0.75

# TVmaze is a television catalogue: there are no films in it, so the only real
# distinction is the kind of programme. These group the 11 raw types into the
# four buckets worth filtering on.
FORMAT_GROUPS = {
    'scripted': ('Scripted',),
    'animation': ('Animation',),
    'documentary': ('Documentary',),
    'unscripted': ('Reality', 'Variety', 'Talk Show', 'Game Show', 'Panel Show',
                   'Award Show', 'Sports', 'News'),
}

# How much each Wikidata or network facet family counts toward the facet closeness of
# two shows; each family's part is a cosine, and the total is scaled back to 0 to 1.
# Tuned on pipeline/bench: franchises (spin-offs, sequels, shared universes) and makers
# lift the right shows; shared cast, subjects, networks and broad genres pulled in
# shows that merely look alike, so they only explain picks (TIE_ORDER), and Wikidata's
# genres reach the ranking through the taste model's subgenre family instead.
FACET_WEIGHTS = {'franchise': 2.0, 'maker': 0.5, 'cast': 0.0, 'genre': 0.0, 'subject': 0.0,
                 'network': 0.0, 'award': 0.0}
# The order ties between two shows are named in when a pick explains itself. A tie that
# more than TIE_COMMON of all shows share (drama, crime, a streaming service) explains
# nothing and is left out.
TIE_ORDER = ('franchise', 'maker', 'cast', 'genre', 'subject', 'network')
TIE_COMMON = 0.01
# Wikipedia's clickstream: readers of one show's article who go on to another's
# (pipeline/jobs/build_cointerest.py). A link of similarity s adds CO_WEIGHT x s^CO_POWER to
# closeness, on the same footing as the facet bonus; the low power lets a modest link
# count almost as much as a strong one, since the clickstream drops pairs under ten a
# month. Pairs that share a franchise are skipped: the franchise already links them,
# and readers comparing an original with its reboot say nothing about liking both.
# Tuned on pipeline/bench's personas and confirmed on its holdout.
CO_WEIGHT = 3.0
CO_POWER = 0.33
CO_TIE = 0.25       # a link this strong (after the power) is named when a pick explains itself

DEFAULT_SETTINGS = {
    'text': 40, 'themes': 35, 'genres': 25, 'facets': 30,
    'closest': .3, 'dislike': .35,
    'language': 'all', 'type': 'all', 'status': 'all',
    'year_min': 1900, 'runtime_min': 0, 'rating_min': 0, 'known_min': 60,
}

# How a long list is ranked (Wide), tuned on the bench's long lists (pipeline/bench/
# large_bench.py), where each of these ranked held-out loves higher. Each rated show adds
# its closeness to each of its closest shows, times how much the rating counts: a love 1,
# a like 0.7 and an OK only 0.1, since a list of thousands holds many lukewarm ratings.
WIDE_RATES = {1: 1.0, .7: 0.7, .35: 0.1}
# Older ratings fade toward WIDE_FADE[0] of their weight, halfway there WIDE_FADE[1]
# ratings back, so a list says most about what its owner watches now.
WIDE_FADE = (0.5, 300)
# Themes and genres count this share of their weight in what a rated show adds: over
# hundreds of rated shows the likeness every drama has with every other adds up to noise,
# where shared plot, franchises and makers do not.
WIDE_BROAD = 0.5
# A show that is among the closest of many shows (a hub) adds less each time: its count
# over the index's width, to this power, divides what it gets.
WIDE_HUB = 0.3
# A long list's interests are found among its most telling liked shows, loves first and
# then the newest, and every other liked show joins the interest it sits closest to. An
# interest needs this share of the liked shows (and at least three) to stand on its own,
# and each learns its taste against the dislikes that sit closest to it.
WIDE_ANCHORS = 150
WIDE_SUPPORT = 0.01
WIDE_FEWEST = 3
WIDE_OWN_DISLIKES = True
# A group of this few shows to match (a title page's, or shows chosen to match) is
# matched on its whole closeness, as a short list is.
WIDE_FEW = 3
# Shows named for each interest, and liked shows sent back with a long list's picks.
WIDE_NAMED = 12
WIDE_LIKED = 100
# Up to this many shows scored at once (a title, My List) are met from their own closest
# shows too, when none of the list's counts them among its closest.
WIDE_AROUND = 400

def unpack(packed):
    """A list sent as ids and rating codes (CODES), as the list of {id, weight} it stands
    for; the ids and weights are checked as any list's are (Engine.read)."""
    ids, codes = packed.get('ids'), packed.get('weights')
    if not isinstance(ids, list) or not isinstance(codes, str) or len(ids) != len(codes):
        raise ValueError('Send your list as its show ids and a rating for each.')
    if len(ids) > MAX_LIST:
        raise ValueError(f'Your list can hold up to {MAX_LIST:,} shows.')
    if any(code not in CODES for code in codes):
        raise ValueError('Choose a valid rating for each show.')
    return [{'id': show_id, 'weight': CODES[code]} for show_id, code in zip(ids, codes)]


def weights_of(settings):
    """Story, themes and genres shared out, and the facet bonus, as Engine.blended takes them."""
    total = settings['text'] + settings['themes'] + settings['genres']
    return (settings['text'] / total, settings['themes'] / total, settings['genres'] / total,
            settings.get('facets', DEFAULT_SETTINGS['facets']) / 100)


# The weights the neighbour index was built under (pipeline/jobs/build_neighbours.py).
STANDARD = weights_of(DEFAULT_SETTINGS)

# Recognisable starting points so a first visit is two taps from a result.
QUICK_PICKS = [169, 82, 526, 2993, 44933, 23470, 431, 44458, 54198, 919,
               43687, 46562, 269, 16149, 305, 216]


class Engine:
    def __init__(self, path=None):
        model = Path(path) if path else Path(__file__).resolve().parents[3] / 'data' / 'model'
        with gzip.open(model / 'catalog.json.gz', 'rt') as f:
            data = json.load(f)
        self.shows = data['shows']
        self.by_id = {s['id']: i for i, s in enumerate(self.shows)}
        self.genres = data['genres']
        self.themes = data['themes']
        self.version = data['version']
        self.date = data['date']
        self.metadata = data['metadata']
        self.n = len(self.shows)
        with gzip.open(model / 'vectors.bin.gz', 'rb') as f:
            rows, cols, nnz = struct.unpack('<III', f.read(12))
            if rows != self.n or cols != data['text_features']:
                raise ValueError('Model vector dimensions do not match catalog.')

            def read_array(code, count):
                values = array(code)
                values.frombytes(f.read(count * 4))
                if sys.byteorder != 'little':
                    values.byteswap()
                if len(values) != count:
                    raise ValueError('Incomplete model vectors.')
                return values
            self.row_ptr = read_array('I', rows + 1)
            self.terms = read_array('I', nnz)
            self.values = read_array('f', nnz)
            self.col_ptr = read_array('I', cols + 1)
            self.post_rows = read_array('I', nnz)
            self.post_values = read_array('f', nnz)
        self.text_features = cols
        self.feature_specs = [('themes', name, 'theme_bits', j) for j, name in enumerate(self.themes)]
        self.feature_specs += [('genres', name, 'genre_bits', j) for j, name in enumerate(self.genres)]
        self.feature_masks = []
        for _group, _label, field, value in self.feature_specs:
            mask = bytearray((self.n + 7) // 8)
            for i, show in enumerate(self.shows):
                if show[field] & (1 << value):
                    mask[i // 8] |= 1 << (i % 8)
            self.feature_masks.append(int.from_bytes(mask, 'little'))
        # TVmaze's 0-100 popularity, one byte per show in catalog order. It covers the
        # whole catalog, unlike the public rating, which only 13% of shows carry.
        with gzip.open(model / 'popularity.bin.gz', 'rb') as f:
            self.popularity = array('B', f.read())
        if len(self.popularity) != self.n:
            raise ValueError('Popularity track does not match the catalog.')
        self.theme_counts = [s['theme_bits'].bit_count() for s in self.shows]
        self.genre_counts = [s['genre_bits'].bit_count() for s in self.shows]
        # Shows share far fewer theme and genre combinations than there are shows (about
        # 17,000 and 1,300 across 90,000), so closeness is worked out once per combination.
        self.combos = {field: self.combinations(field) for field in ('theme_bits', 'genre_bits')}
        self.numpy_combos = {}
        if np is not None:
            for field, (masks, counts, where) in self.combos.items():
                if hasattr(np, 'bitwise_count') and max(masks, default=0).bit_length() <= 64:
                    self.numpy_combos[field] = (np.asarray(masks, dtype=np.uint64),
                                               np.asarray(counts, dtype=np.float64), np.asarray(where))
        # Wikidata's genres, makers, cast, franchises and subjects and TVmaze's networks,
        # when the model carries them (facets.py); a model without them ranks as before.
        self.facets = facets.load(model, self.n)
        if self.facets:
            known = [f for f in FACET_WEIGHTS if f in self.facets.families]
            total = sum(FACET_WEIGHTS[f] for f in known) or 1
            self.facet_weights = {f: FACET_WEIGHTS[f] / total for f in known}
        self.co = facets.cointerest(model, self.n)
        # Each show's closest shows, for ranking long lists (Wide); a model without them
        # ranks a long list from its most recent ratings (focus).
        self.neighbours = neighbours.load(model, self.n)
        if self.neighbours:
            width = self.neighbours.width
            self.damp = [1.0 if d <= width else (d / width) ** -WIDE_HUB for d in self.neighbours.degree]
        # Themes and genres as bit sets with one over the root of their count, for closeness
        # worked out a pair at a time.
        norm = lambda bits: 1 / math.sqrt(bits.bit_count()) if bits else 0.0
        self.theme_norm = [norm(s['theme_bits']) for s in self.shows]
        self.genre_norm = [norm(s['genre_bits']) for s in self.shows]
        self.attributes = Attributes(self, self.subgenres())
        if np is not None:
            self.numpy_columns = {id(column): np.asarray(column) for column in self.attributes.values.values()}
            self.numpy_quality = np.asarray([clamp((s['rating'] - 7.2) / 1.2, 1.5) if s['rating'] else 0.
                                             for s in self.shows])
            self.numpy_sets = self._set_columns()
        self.quick_picks = [self.card(self.by_id[i]) for i in QUICK_PICKS if i in self.by_id]
        self.titles = Titles(self.shows, self.popularity, model / 'search.json.gz')

    def _set_columns(self):
        """Public mask combinations, with unknown data distinct from a known empty set."""
        columns = {}
        for family in ('genre', 'subgenre'):
            if family not in self.attributes.masks:
                continue
            masks, known = self.attributes.masks[family], self.attributes.known[family]
            combinations, by_mask = [None], {}
            codes = np.zeros(len(masks), dtype=np.int32)
            for i, mask in enumerate(masks):
                if not known[i]:
                    continue
                code = by_mask.get(mask)
                if code is None:
                    code = len(combinations)
                    by_mask[mask] = code
                    combinations.append(mask)
                codes[i] = code
            codes.flags.writeable = False
            columns[id(masks), id(known)] = tuple(combinations), codes
        return columns

    # ---------------------------------------------------------------- shapes

    def plot_words(self, s):
        """Distinctive summary terms. Single words must appear lowercase in the visible
        summary, which drops the character names TF-IDF otherwise rates highly."""
        summary = s['summary'] or ''
        words = [term for term in s['keywords']
                 if ' ' in term or re.search(r'\b' + re.escape(term) + r'\b', summary)]
        return words[:4]

    def card(self, i):
        """The short form used in search results and the watched list."""
        s = self.shows[i]
        return {**{k: s[k] for k in ('id', 'name', 'year', 'channel', 'rating', 'language', 'type')},
                'known': self.popularity[i]}

    def full(self, i):
        s = self.shows[i]
        return {k: s[k] for k in ('id', 'name', 'year', 'runtime', 'rating', 'genres', 'url',
                                  'channel', 'language', 'type', 'country', 'status', 'summary')}

    # ---------------------------------------------------------------- search

    def search(self, q):
        """Cards for the shows q most likely means, best first; titles.py says how. A
        show found only through another of its titles carries that title as aka."""
        return [{**self.card(i), 'aka': aka} if aka else self.card(i) for i, aka in self.titles.find(q).hits]

    def cards(self, ids):
        """Short records for ids, in the order asked. Unknown ids are dropped, which
        is what an imported list needs: a show cut from a later snapshot should not
        make the whole transfer fail."""
        return [self.card(self.by_id[i]) for i in ids if i in self.by_id]

    # ------------------------------------------------------------ validation

    def validate(self, body):
        """The list, settings and liked shows to match; see read()."""
        return self.read(body)[:3]

    def read(self, body):
        """Everything a request carries, checked: the rated list, the settings, the liked
        shows to match and what the browser has shown lately (fresh.py). Anything
        malformed raises ValueError with a message fit to show."""
        if not isinstance(body, dict):
            raise ValueError('Send a watched list and settings.')
        profile = body.get('profile', [])
        if isinstance(profile, dict):
            profile = unpack(profile)
        if not isinstance(profile, list) or len(profile) > MAX_LIST:
            raise ValueError(f'Your list can hold up to {MAX_LIST:,} shows.')
        seen, parsed = set(), []
        for p in profile:
            if not isinstance(p, dict) or type(p.get('id')) is not int or p['id'] not in self.by_id:
                raise ValueError('A show in your list is not in this catalog. Remove it and try again.')
            if p['id'] in seen:
                raise ValueError('Each show should appear only once.')
            weight = p.get('weight', 1)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight not in RATINGS:
                raise ValueError('Choose a valid rating for each show.')
            seen.add(p['id'])
            parsed.append({'id': p['id'], 'weight': weight})
        chosen = self.validate_similar(body.get('similar_to', []), parsed)
        settings = body.get('settings', {})
        if not isinstance(settings, dict):
            raise ValueError('Settings must be an object.')
        result = dict(DEFAULT_SETTINGS)
        ranges = {'text': (0, 100), 'themes': (0, 100), 'genres': (0, 100), 'facets': (0, 100), 'closest': (0, 1),
                  'dislike': (0, 1), 'year_min': (1900, 2100), 'runtime_min': (0, 240),
                  'rating_min': (0, 10), 'known_min': (0, 100)}
        for k, (lo, hi) in ranges.items():
            value = settings.get(k, result[k])
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'Invalid value for {k.replace("_", " ")}.')
            result[k] = value
        if result['text'] + result['themes'] + result['genres'] == 0:
            raise ValueError('Give story, themes, or genres a weight above zero.')
        for key in ('language', 'type', 'status'):
            value = settings.get(key, result[key])
            allowed = ['all', 'unknown'] + self.metadata[key] + (list(FORMAT_GROUPS) if key == 'type' else [])
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f'Choose a valid {key} filter.')
            result[key] = value
        return parsed, result, chosen, fresh.parse(body)

    def validate_similar(self, wanted, profile):
        """The liked shows a request asks to match, in list order. Absent or empty
        means every liked show, which is the plain ranking."""
        if not isinstance(wanted, list):
            raise ValueError('Send the shows to match as a list of ids.')
        if len(wanted) > MAX_LIST:
            raise ValueError(f'Choose up to {MAX_LIST:,} shows to match.')
        if any(type(i) is not int for i in wanted):
            raise ValueError('Show ids must be whole numbers.')
        if len(set(wanted)) != len(wanted):
            raise ValueError('Each show to match should appear only once.')
        wanted = set(wanted)
        if not wanted <= {p['id'] for p in profile if p['weight'] > 0}:
            raise ValueError('Each show to match must be on your list and counted as liked.')
        return [p['id'] for p in profile if p['id'] in wanted]

    # ------------------------------------------------------------- scoring

    def text_items(self, index):
        return ((self.terms[k], self.values[k]) for k in range(self.row_ptr[index], self.row_ptr[index + 1]))

    def eligible(self, index, settings, formats=None):
        show = self.shows[index]
        if not show['recommendable'] or show['year'] < settings['year_min']:
            return False
        if self.popularity[index] < settings['known_min']:
            return False
        if formats is not None and (show['type'] or 'unknown') not in formats:
            return False
        for key in ('language', 'status'):
            value = settings[key]
            if value != 'all' and (show[key] or 'unknown') != value:
                return False
        return all(settings[key] == 0 or (show[field] is not None and show[field] >= settings[key])
                   for key, field in [('runtime_min', 'runtime'), ('rating_min', 'rating')])

    def combinations(self, field):
        seen, index = {}, array('I', bytes(4 * self.n))
        for i, show in enumerate(self.shows):
            index[i] = seen.setdefault(show[field], len(seen))
        masks = list(seen)
        return masks, [m.bit_count() for m in masks], index

    def subgenres(self):
        """Wikidata's genres as (labels, one bitmask per show), for the taste model."""
        f = self.facets
        if not f or 'genre' not in f.families:
            return None
        start, end = f.family_ranges[f.families.index('genre')]
        labels = [f.labels[c] for c in range(start, end)]
        masks = []
        for i in range(self.n):
            mask = 0
            for k in range(f.row_ptr[i], f.row_ptr[i + 1]):
                column = f.columns[k]
                if start <= column < end:
                    mask |= 1 << (column - start)
            masks.append(mask)
        return labels, masks

    def franchises(self, i):
        """Show i's franchise tokens in the facets, for telling linked shows apart."""
        f = self.facets
        if not f or 'franchise' not in f.families:
            return frozenset()
        start, end = f.family_ranges[f.families.index('franchise')]
        return frozenset(c for c, _v in f.row(i) if start <= c < end)

    def cointerest(self, i):
        """(show j, strength after the power) for the shows show i's readers also look up,
        leaving out any it shares a franchise with."""
        if not self.co:
            return []
        indptr, indices, values = self.co
        mine = self.franchises(i)
        out = []
        for k in range(indptr[i], indptr[i + 1]):
            j = indices[k]
            if mine and mine & self.franchises(j):
                continue
            out.append((j, values[k] ** CO_POWER))
        return out

    def ties(self, i, j):
        """What two shows concretely share beyond plot words: a franchise, a maker, cast,
        a Wikidata genre, a subject or a network, strongest first within each kind, and
        whether one's readers often look up the other."""
        f = self.facets
        if not f:
            return [{'family': 'fans', 'label': ''}] if any(k == i and s >= CO_TIE for k, s in self.cointerest(j)) else []
        mine = dict(f.row(i))
        common = TIE_COMMON * self.n
        shared = [(TIE_ORDER.index(f.families[f.token_family[c]]), -v * mine[c], c)
                  for c, v in f.row(j) if c in mine and f.families[f.token_family[c]] in TIE_ORDER
                  and f.df[c] <= common]
        shared.sort()
        out, seen = [], set()
        for _order, _strength, c in shared:
            family, label = f.families[f.token_family[c]], f.labels[c]
            # One Wikidata genre says enough: the next is usually its parent
            # (police procedural, then procedural).
            if (family, label) in seen or (family == 'genre' and any(t['family'] == 'genre' for t in out)):
                continue
            seen.add((family, label))
            out.append({'family': family, 'label': label})
        # Readers of the liked show often go on to this one: its fans look it up too.
        if not any(t['family'] == 'franchise' for t in out) and \
                any(k == i and s >= CO_TIE for k, s in self.cointerest(j)):
            out.insert(min(1, len(out)), {'family': 'fans', 'label': ''})
        return out[:4]

    @lru_cache(maxsize=32)
    def components(self, index):
        """Cached catalog-to-show similarities: plot text, themes, genres and, when the
        model has them, facets. No user profile is ever cached."""
        source = self.shows[index]
        text = array('f', [0]) * self.n
        if np is not None:
            vector = np.frombuffer(text, dtype=np.float32)
            rows = np.frombuffer(self.post_rows, dtype=np.uint32)
            values = np.frombuffer(self.post_values, dtype=np.float32)
            for term, value in self.text_items(index):
                lo, hi = self.col_ptr[term], self.col_ptr[term + 1]
                at = rows[lo:hi]
                vector[at] = vector[at].astype(np.float64) + value * values[lo:hi].astype(np.float64)
        else:
            for term, value in self.text_items(index):
                for k in range(self.col_ptr[term], self.col_ptr[term + 1]):
                    text[self.post_rows[k]] += value * self.post_values[k]

        def bits(field):
            masks, counts, where = self.combos[field]
            mine = source[field]
            n = mine.bit_count()
            if not n:
                return array('f', bytes(4 * self.n))
            if np is not None and field in self.numpy_combos:
                masks, counts, where = self.numpy_combos[field]
                denominator = np.sqrt(n * counts)
                table = np.divide(np.bitwise_count(masks & np.uint64(mine)), denominator,
                                  out=np.zeros(len(masks)), where=denominator != 0)
                found = array('f')
                found.frombytes(np.take(table.astype(np.float32), where).tobytes())
                return found
            table = [(mine & m).bit_count() / math.sqrt(n * c) if c else 0.0 for m, c in zip(masks, counts)]
            if np is not None:
                found = array('f')
                found.frombytes(np.take(np.asarray(table, dtype=np.float32), where).tobytes())
                return found
            return array('f', map(table.__getitem__, where))
        near = self.facets.similarity(index, self.facet_weights) if self.facets else None
        linked = self.cointerest(index)
        if linked:
            # Added where the facet bonus is, scaled so the default facet setting gives
            # CO_WEIGHT; a request that turns facets off turns this off with them.
            near = near if near is not None else array('f', bytes(4 * self.n))
            scale = CO_WEIGHT / (DEFAULT_SETTINGS['facets'] / 100)
            for j, strength in linked:
                near[j] += scale * strength
        return text, bits('theme_bits'), bits('genre_bits'), near

    def blend(self, index, settings):
        """How close every show in the catalog sits to one show, with story, themes,
        genres and facets weighted as the settings ask."""
        return self.blended(index, settings['text'], settings['themes'], settings['genres'],
                            settings.get('facets', DEFAULT_SETTINGS['facets']))

    @lru_cache(maxsize=96)
    def blended(self, index, text, themes, genres, extra=0):
        """Story, themes and genres share out their weights; facets come on top, as a
        bonus of extra / 100 times the facet closeness. So a show with no franchise or
        maker in common with anything ranks exactly as it would without facets, and one
        that shares them is lifted."""
        t, h, g, f = self.components(index)
        total = text + themes + genres
        a, b, c = text / total, themes / total, genres / total
        if np is not None:
            # Python's scalar implementation does each operation in double precision
            # before one float32 store. Keep that order and rounding here too.
            values = (a * np.frombuffer(t, dtype=np.float32).astype(np.float64)
                      + b * np.frombuffer(h, dtype=np.float32).astype(np.float64)
                      + c * np.frombuffer(g, dtype=np.float32).astype(np.float64))
            if extra and f is not None:
                values += extra / 100 * np.frombuffer(f, dtype=np.float32).astype(np.float64)
            result = array('f')
            result.frombytes(values.astype(np.float32).tobytes())
            return result
        if not extra or f is None:
            return array('f', [a * x + b * y + c * z for x, y, z in zip(t, h, g)])
        d = extra / 100
        return array('f', [a * x + b * y + c * z + d * w for x, y, z, w in zip(t, h, g, f)])

    def row(self, i, settings):
        """Show i's closest shows from the neighbour index, closest first under the default
        settings: (catalog indices, closeness under these settings, what the show adds to
        each as evidence in a long list, which counts themes and genres at WIDE_BROAD and
        damps a hub by WIDE_HUB)."""
        return self._row(i, *weights_of(settings))

    @lru_cache(maxsize=4096)
    def _row(self, i, a, b, c, d):
        if (a, b, c, d) == STANDARD:
            # Under the weights the index was built with, what a show adds is a fixed mix of
            # its three stored parts (the closeness, its plot text and its facet part), so
            # it is read through three tables, a long list's thousands of rows at C speed.
            found = self.neighbours
            lo = i * found.width
            hi = lo + found.width
            index = found.index[lo:hi]
            near, text, bonus = found.near[lo:hi], found.text[lo:hi], found.bonus[lo:hi]
            e_near, e_text, e_bonus = self.evidence_tables()
            evidence = list(map(mul, map(add, map(add, map(e_near.__getitem__, near), map(e_text.__getitem__, text)),
                                         map(e_bonus.__getitem__, bonus)), map(self.damp.__getitem__, index)))
            return index, list(map(neighbours.NEAR.__getitem__, near)), evidence
        # Other weights (Next Watch's other focuses) take themes and genres from the bits.
        index, _near, text, bonus = self.neighbours.row(i)
        shows, theme_norm, genre_norm = self.shows, self.theme_norm, self.genre_norm
        tb, gb, tn, gn = shows[i]['theme_bits'], shows[i]['genre_bits'], theme_norm[i], genre_norm[i]
        broad = [b * tn * theme_norm[j] * (tb & shows[j]['theme_bits']).bit_count()
                 + c * gn * genre_norm[j] * (gb & shows[j]['genre_bits']).bit_count() for j in index]
        close = [a * t + y + d * f for t, y, f in zip(text, broad, bonus)]
        z = a + WIDE_BROAD * (b + c)
        damp = self.damp
        evidence = [((a * t + WIDE_BROAD * y) / z + d * f) * damp[j] for j, t, y, f in zip(index, text, broad, bonus)]
        return index, close, evidence

    def evidence_tables(self):
        """What each packed byte of closeness, plot text and facet part adds as evidence under
        the index's own weights: evidence counts themes and genres at WIDE_BROAD, and since
        closeness is plot text, themes and genres and the facet part added up, evidence is
        (b/z) x closeness + a(1 - b)/z x text + d(1 - b/z) x facet part, b being WIDE_BROAD
        and z the weights left once themes and genres are cut to it."""
        key = WIDE_BROAD
        if getattr(self, '_tables', (None,))[0] != key:
            a, b, c, d = STANDARD
            z = a + key * (b + c)
            self._tables = (key, [key / z * v for v in neighbours.NEAR], [a * (1 - key) / z * v for v in neighbours.TEXT],
                            [d * (1 - key / z) * v for v in neighbours.BONUS])
        return self._tables[1:]

    def pairs(self, i, others, settings):
        """Show i's closeness to each of others under the settings, a pair at a time: what
        blend() gives, for a few pairs where a whole array would cost too much."""
        a, b, c, d = weights_of(settings)
        terms, values, row_ptr = self.terms, self.values, self.row_ptr
        mine = dict(zip(terms[row_ptr[i]:row_ptr[i + 1]], values[row_ptr[i]:row_ptr[i + 1]]))
        f, weighted, linked = self.facets, {}, {}
        if d:
            if f:
                family = [self.facet_weights.get(name, 0.0) for name in f.families]
                weighted = {col: family[f.token_family[col]] * v for col, v in f.row(i) if family[f.token_family[col]]}
            scale = CO_WEIGHT / (DEFAULT_SETTINGS['facets'] / 100)
            linked = {j: scale * s for j, s in self.cointerest(i)}
        shows = self.shows
        tb, gb, tn, gn = shows[i]['theme_bits'], shows[i]['genre_bits'], self.theme_norm[i], self.genre_norm[i]
        out = []
        for j in others:
            lo, hi = row_ptr[j], row_ptr[j + 1]
            text = sum(mine.get(t, 0.0) * v for t, v in zip(terms[lo:hi], values[lo:hi]))
            h = tn * self.theme_norm[j] * (tb & shows[j]['theme_bits']).bit_count()
            g = gn * self.genre_norm[j] * (gb & shows[j]['genre_bits']).bit_count()
            extra = linked.get(j, 0.0)
            if weighted:
                extra += sum(weighted.get(col, 0.0) * v for col, v in f.row(j))
            out.append(a * text + b * h + c * g + d * extra)
        return out

    def taste(self, profile):
        """The leanings of a whole list, liked and disliked shows alike."""
        return Taste(self.attributes,
                     [(self.by_id[p['id']], p['weight']) for p in profile if p['weight'] > 0],
                     [self.by_id[p['id']] for p in profile if p['weight'] < 0])

    def wide(self, rated):
        """Whether a list rating this many shows (liked and disliked) is ranked from each
        show's closest shows (Wide) rather than its closeness to every show (Ranking)."""
        return rated > DENSE_MAX and self.neighbours is not None

    def focus(self, profile):
        """The ratings that shape a ranking: all of them, unless the list is longer than
        DENSE_MAX and the model has no neighbour index, when only its DENSE_MAX most recent
        likes and dislikes count. Every rated show stays out of the picks either way."""
        rated = [p for p in profile if p['weight'] != 0]
        if len(rated) <= DENSE_MAX or self.neighbours is not None:
            return profile
        keep = {p['id'] for p in rated[-DENSE_MAX:]}
        return [p for p in profile if p['id'] in keep]

    def ranking(self, scoring, negatives, affinities, settings, liked=None, base=None):
        """How one request scores candidates: see Ranking, and Wide for a long list, which
        may take its interests from base, a Wide for the same list."""
        if self.wide(len(liked or scoring) + len(negatives)):
            return Wide(self, scoring, negatives, affinities, settings, liked, base if isinstance(base, Wide) else None)
        return Ranking(self, scoring, negatives, affinities, settings, liked)

    def rank(self, candidates, scoring, negatives, affinities, settings, liked=None, base=None):
        """Scores for the candidates, in an array over the whole catalog. Affinities are
        keyed by show id. See Ranking for how they are made."""
        return self.ranking(scoring, negatives, affinities, settings, liked, base).score(candidates)

    def signals(self, i):
        """Theme and genre names a show actually records."""
        s = self.shows[i]
        return ([name for j, name in enumerate(self.themes) if s['theme_bits'] & (1 << j)],
                list(s['genres']))

    def arrange(self, ordered, scores, today):
        """The ranked shows to show, in order, as (index, rank, place). Without freshness
        they are the first TOP_PICKS and carry no place, exactly as ranked. With it, the
        five strongest by rank and fatigue hold the top ('steady'), the rest rotate a
        little each day among the best DEPTH x TOP_PICKS ('fresh', fresh.dither), and
        places 12 and 20 go to shows from ranks 25 to 72 scoring at least
        DIFFERENT_FLOOR of the plain ranking's last pick ('different', fresh.explore)."""
        if not today:
            return [(i, n + 1, None) for n, i in enumerate(ordered[:TOP_PICKS])]
        ids = [self.shows[i]['id'] for i in ordered[:fresh.DEPTH * TOP_PICKS]]
        rank = {show_id: n + 1 for n, show_id in enumerate(ids)}
        floor = DIFFERENT_FLOOR * scores[ordered[TOP_PICKS - 1]] if len(ordered) >= TOP_PICKS else 0.0
        shown = fresh.dither(ids, today, 'next', TOP_PICKS)
        shown, different = fresh.explore(shown, ids, today, 'next',
                                         allowed=lambda show_id: scores[self.by_id[show_id]] >= floor)
        return [(self.by_id[show_id], rank[show_id],
                 'steady' if n < fresh.PINNED else 'different' if show_id in different else 'fresh')
                for n, show_id in enumerate(shown)]

    def calculate(self, body):
        profile, settings, chosen, today = self.read(body)
        watched_ids = {p['id'] for p in profile}
        profile = self.focus(profile)
        positives = [p for p in profile if p['weight'] > 0]
        negatives = [p for p in profile if p['weight'] < 0]
        # Choosing shows narrows what the picks are matched to, not what your taste
        # is made of: only the scoring set shrinks. Every rated show still stays out
        # of the pool, dislikes still count, and the liked list, its signals and the
        # per-show links keep covering everything you liked. Ranking against a chosen
        # set is the same as ranking a list where every other liked show is re-rated
        # neutral, since neutral shows leave the pool but are never scored.
        scoring = [p for p in positives if p['id'] in set(chosen)] if chosen else positives
        base = {
            'date': self.date, 'catalog_count': self.n, 'candidate_count': 0,
            'settings': settings, 'positive_count': len(positives), 'negative_count': len(negatives),
            'similar_to': chosen,
            'picks': [], 'liked': [], 'features': [], 'context': [], 'message': '', 'warning': '',
            'taste': {'leans': [], 'avoids': []}, 'interests': [],
            'breadth': {'themes': [0, len(self.themes)], 'genres': [0, len(self.genres)]},
        }
        if today:
            # The day and seed come back as they were sent, to tell one day's page from another's.
            base['fresh'] = today.echo()
        if not positives:
            base['message'] = 'Rate one show as liked or loved to get recommendations.'
            return base

        kind = settings['type']
        formats = None if kind == 'all' else set(FORMAT_GROUPS.get(kind, (kind,)))
        candidates = [i for i, s in enumerate(self.shows)
                      if s['id'] not in watched_ids and self.eligible(i, settings, formats)]
        base['candidate_count'] = len(candidates)
        thin = [self.shows[self.by_id[p['id']]]['name'] for p in scoring
                if self.shows[self.by_id[p['id']]]['summary_words'] < 15]
        if thin and not chosen:
            base['warning'] = 'Some of your shows have very little plot text, so their matches lean on genres alone.'
        elif len(thin) == 1:
            base['warning'] = f'{thin[0]} has very little plot text, so its matches lean on genres alone.'
        elif thin:
            base['warning'] = 'Some of the shows you chose have very little plot text, so their matches lean on genres alone.'

        affinities = Closeness(self, settings)
        ranking = self.ranking(scoring, negatives, affinities, settings, positives)
        scores = ranking.score(candidates)
        base['taste'] = self.taste(profile).summary()
        base['interests'] = ranking.describe()
        ordered = sorted((i for i in candidates if scores[i] > 0), key=lambda i: (-scores[i], self.shows[i]['id']))

        liked_indices = [self.by_id[p['id']] for p in positives]
        liked_signals = {p['id']: self.signals(self.by_id[p['id']]) for p in positives}
        chosen_picks = self.arrange(ordered, scores, today)
        sources = {i: ranking.source(i) for i, _rank, _place in chosen_picks}
        # Every liked show comes back with a short list's picks. A long list's would run to
        # megabytes, so it sends the shows its picks come from, the shows its interests are
        # named for and then its newest loves and likes, WIDE_LIKED in all.
        shown = positives
        if isinstance(ranking, Wide):
            wanted = dict.fromkeys(p['id'] for p in sources.values())
            wanted.update(dict.fromkeys(i for interest in base['interests'] for i in interest['shows']))
            for p in sorted(positives, key=lambda p: -p['weight']):
                if len(wanted) >= WIDE_LIKED:
                    break
                wanted.setdefault(p['id'])
            shown = [p for p in positives if p['id'] in wanted]
        base['liked_count'] = len(positives)
        liked_order = [p['id'] for p in shown]
        for p in shown:
            index = self.by_id[p['id']]
            themes, genres = liked_signals[p['id']]
            base['liked'].append({
                **self.card(index), 'weight': p['weight'], 'themes': themes, 'genres': genres,
                'has_plot': self.shows[index]['summary_words'] >= 15,
            })

        def pick(i, rank):
            s = self.shows[i]
            themes, genres = self.signals(i)
            source = sources[i]
            source_index = self.by_id[source['id']]
            source_themes, source_genres = liked_signals[source['id']]
            penalty = ranking.penalty(i)
            return {
                **self.full(i), 'rank': rank, 'score': round(scores[i] * 100, 1),
                'themes': themes, 'genres': genres,
                'because': self.shows[source_index]['name'],
                'because_id': self.shows[source_index]['id'],
                'shared_themes': [t for t in themes if t in source_themes],
                'shared_genres': [g for g in genres if g in source_genres],
                'keywords': self.plot_words(s),
                'penalised': round(penalty * 100, 1) if penalty > 0 else 0,
                'links': [round(v * 100, 1) for v in ranking.links(i, liked_order)],
                'known': self.popularity[i],
                'fits': ranking.fits(i),
                'ties': self.ties(i, source_index),
                'interest': ranking.interest_of(i),
            }
        base['picks'] = [{**pick(i, rank), 'place': place} if place else pick(i, rank)
                         for i, rank, place in chosen_picks]
        # How much of the liked list carries each theme and genre, weighted by rating, for
        # the taste chart: a theme counts among shows with plot text, a genre among shows
        # with genres.
        fit = {'themes': {}, 'genres': {}}
        for group, known in (('themes', lambda i: self.shows[i]['summary_words'] >= 15),
                             ('genres', lambda i: bool(self.shows[i]['genres']))):
            total, tally = 0.0, {}
            for p in positives:
                if known(self.by_id[p['id']]):
                    total += p['weight']
                    for name in liked_signals[p['id']][0 if group == 'themes' else 1]:
                        tally[name] = tally.get(name, 0.0) + p['weight']
            # Rounded half up, as the page rounds its own.
            shares = {name: int(value / total * 100 + 0.5) for name, value in sorted(tally.items())} if total else {}
            fit[group] = {name: share for name, share in shares.items() if share}
        base['fit'] = fit

        # Signal prevalence: how often a signal shows up in your likes vs the eligible pool.
        def mask_for(indices):
            data = bytearray((self.n + 7) // 8)
            for i in indices:
                data[i // 8] |= 1 << (i % 8)
            return int.from_bytes(data, 'little')
        pool_mask = mask_for(candidates)
        liked_mask = mask_for(liked_indices)
        for (group, name, _field, _value), mask in zip(self.feature_specs, self.feature_masks):
            count = (mask & liked_mask).bit_count()
            if not count:
                continue
            prevalence = (mask & pool_mask).bit_count() / len(candidates) if candidates else 0.0
            base['features'].append({
                'name': name, 'group': group, 'count': count,
                'share': round(count / len(positives) * 100),
                'baseline': round(prevalence * 100, 1),
                'lift': round(count / len(positives) / prevalence, 1) if prevalence else None,
            })
        base['features'].sort(key=lambda f: (-f['count'], -(f['lift'] or 0), f['name']))

        base['breadth'] = {
            'themes': [len({t for themes, _genres in liked_signals.values() for t in themes}), len(self.themes)],
            'genres': [len({g for _themes, genres in liked_signals.values() for g in genres}), len(self.genres)],
        }

        # One plain line of context: where your shows come from and what form they take.
        for key, label in [('language', 'language'), ('type', 'format'), ('country', 'country')]:
            tally = {}
            for i in liked_indices:
                value = self.shows[i][key]
                if value:
                    tally[value] = tally.get(value, 0) + 1
            if tally:
                top, count = max(tally.items(), key=lambda kv: (kv[1], kv[0]))
                base['context'].append({'label': label, 'value': top, 'count': count, 'of': len(positives)})

        if not ordered:
            base['message'] = ('Nothing matches these filters yet. Widen the year, language or format.' if not candidates
                               else 'No positive matches for the shows you chose. Choose others, or use all your shows.' if chosen
                               else 'No positive matches under these settings. Add another show you liked.')
        return base


INTEREST_JOIN = 0.12   # average closeness at which two groups of liked shows are one interest
INTEREST_SHARE = 0.5   # how much a bigger interest outranks a smaller one: its share of the list to this power


class Ranking:
    """One request's scoring. A list can hold several tastes (anime and British panel
    shows, say), and averaging across them favours whichever kind sits closest to
    itself. So the scoring shows are first grouped into interests by how close they
    sit to one another, and each candidate is scored against the interest it is
    closest to: a weighted mean across that interest's shows blended with the closest
    of them, less a penalty for looking like what you disliked, times how well it fits
    that interest's taste (taste.py). Scores are then measured against each interest's
    best candidate and scaled by the interest's share of the list, so every interest
    gets picks in proportion to it, and a list with one interest ranks exactly as
    closeness times taste would."""

    def __init__(self, engine, scoring, negatives, affinities, settings, liked=None):
        """liked is the whole list's liked shows when scoring is only some of them (a
        row about one show, or shows chosen to match): interests and their tastes come
        from the whole list, and scoring picks out its part of each."""
        self.e, self.negatives, self.affinities, self.settings = engine, negatives, affinities, settings
        liked = liked or scoring
        self.scoring = scoring
        disliked = [engine.by_id[p['id']] for p in negatives]
        taste = lambda shows: Taste(engine.attributes, [(engine.by_id[p['id']], p['weight']) for p in shows], disliked)
        # Heaviest interest first, so interest 0 is the one a list is mostly about.
        order = {p['id']: n for n, p in enumerate(liked)}
        self.interests = sorted(self.cluster(liked) if liked else [],
                                key=lambda g: (-sum(p['weight'] for p in g), order[g[0]['id']]))
        self.interest_tastes = [taste(interest) for interest in self.interests]
        self.groups, self.tastes, self.origin = [], [], []
        wanted = {p['id'] for p in scoring}
        for n, interest in enumerate(self.interests):
            group = [p for p in interest if p['id'] in wanted]
            if group:
                self.groups.append(group)
                self.tastes.append(self.interest_tastes[n])
                self.origin.append(n)
        known = {p['id'] for p in liked}
        for p in scoring:
            if p['id'] not in known:
                # A show outside the list (a title page's more like this) is its own interest.
                self.groups.append([p])
                self.tastes.append(taste([p]))
                self.origin.append(None)
        total = sum(p['weight'] for g in self.groups for p in g) or 1
        self.share = [(sum(p['weight'] for p in g) / total) ** INTEREST_SHARE for g in self.groups]
        self.best = None
        self.group = {}

    def describe(self):
        """The list's interests, heaviest first: their shows and what each leans toward."""
        out = []
        for interest, taste in zip(self.interests, self.interest_tastes):
            leans = [f['label'] for f in taste.summary(limit=3)['leans']]
            out.append({'shows': [p['id'] for p in interest],
                        'weight': round(sum(p['weight'] for p in interest), 2), 'leans': leans[:3]})
        return out

    def fits(self, i):
        """What about show i fits the taste of the interest it was scored for."""
        k = self.group.get(i)
        return self.tastes[k].reasons(i) if k is not None else []

    def interest_of(self, i):
        k = self.group.get(i)
        return self.origin[k] if k is not None else None

    def cluster(self, scoring):
        """Average-linkage clustering of liked shows on their mutual closeness."""
        e, aff = self.e, self.affinities
        index = [e.by_id[p['id']] for p in scoring]
        n = len(scoring)
        sim = [[(aff[scoring[a]['id']][index[b]] + aff[scoring[b]['id']][index[a]]) / 2 for b in range(n)] for a in range(n)]
        groups = [[a] for a in range(n)]
        while len(groups) > 1:
            best, pair = -1.0, None
            for x in range(len(groups)):
                for y in range(x + 1, len(groups)):
                    link = sum(sim[a][b] for a in groups[x] for b in groups[y]) / (len(groups[x]) * len(groups[y]))
                    if link > best:
                        best, pair = link, (x, y)
            if best < INTEREST_JOIN:
                break
            x, y = pair
            groups[x] = groups[x] + groups.pop(y)
        return [[scoring[a] for a in sorted(g)] for g in groups]

    def score(self, candidates):
        scores = array('f', [0]) * self.e.n
        m = len(candidates)
        if not self.groups or not m:
            return scores
        if np is not None:
            hits, penalty = self._hits_vector(candidates)
            return self._scores_vector(candidates, scores, hits, penalty)
        gather = itemgetter(*candidates) if m > 1 else (lambda values: (values[candidates[0]],))
        closest, aff = self.settings['closest'], self.affinities
        hits = []
        for group in self.groups:
            norm = sum(p['weight'] for p in group)
            top = max(p['weight'] for p in group)
            mean, near = [0.0] * m, [0.0] * m
            for p in group:
                values = gather(aff[p['id']])
                share, scale = p['weight'] / norm, p['weight'] / top
                mean = [a + share * x for a, x in zip(mean, values)]
                near = [b if b > scale * x else scale * x for b, x in zip(near, values)]
            hits.append([(1 - closest) * a + closest * b for a, b in zip(mean, near)])
        penalty = [0.0] * m
        if self.negatives:
            share = self.settings['dislike'] / len(self.negatives)
            for p in self.negatives:
                penalty = [a + share * x for a, x in zip(penalty, gather(aff[p['id']]))]
        raw = []
        single = len(self.groups) == 1
        for n, i in enumerate(candidates):
            if single:
                k, hit = 0, hits[0][n]
            else:
                k, hit = max(enumerate(h[n] for h in hits), key=lambda kv: kv[1])
            hit -= penalty[n]
            raw.append((i, k, hit * self.tastes[k].factor(i) if hit > 0 else 0.0))
        if self.best is None:
            # Each interest's best among the first candidates scored sets its scale for
            # the whole request, so shows scored later are measured the same way.
            self.best = [0.0] * len(self.groups)
            for _i, k, value in raw:
                if value > self.best[k]:
                    self.best[k] = value
        for i, k, value in raw:
            self.group[i] = k
            if value > 0 and self.best[k] > 0:
                scores[i] = value / self.best[k] * self.share[k]
        return scores

    def _hits_vector(self, candidates):
        index = np.asarray(candidates, dtype=np.intp)
        gather = lambda show_id: np.asarray(self.affinities[show_id])[index].astype(np.float64)
        closest, hits = self.settings['closest'], []
        for group in self.groups:
            norm = sum(p['weight'] for p in group)
            top = max(p['weight'] for p in group)
            mean, near = np.zeros(len(index), dtype=np.float64), np.zeros(len(index), dtype=np.float64)
            for p in group:
                values = gather(p['id'])
                share, scale = p['weight'] / norm, p['weight'] / top
                # Match Python's double-precision multiply then add, in member
                # order. No float32 intermediate or reordered group reduction.
                mean += share * values
                scaled = scale * values
                near = np.where(near > scaled, near, scaled)
            hits.append((1 - closest) * mean + closest * near)
        penalty = np.zeros(len(index), dtype=np.float64)
        if self.negatives:
            share = self.settings['dislike'] / len(self.negatives)
            for p in self.negatives:
                penalty += share * gather(p['id'])
        return hits, penalty

    def _factors_vector(self, taste, indices):
        fit = np.zeros(len(indices), dtype=np.float64)
        for column, contributions in taste.tables:
            fit += np.asarray(contributions)[self.e.numpy_columns[id(column)][indices]]
        for _family, masks, known, delta, offset, weight, limit, cache in taste.sets:
            if weight == 0:
                continue
            column = getattr(self.e, 'numpy_sets', {}).get((id(masks), id(known)))
            if column is not None and len(indices) >= 64:
                combinations, all_codes = column
                codes = all_codes[indices]
                contributions = np.zeros(len(combinations), dtype=np.float64)
                for code in np.unique(codes):
                    if code == 0:
                        continue
                    mask = combinations[code]
                    hit = cache.get(mask)
                    if hit is None:
                        hit = cache[mask] = weight * clamp(offset + sum(delta[bit] for bit in taste_bits(mask)), limit)
                    contributions[code] = hit
                # Only public combination identities are shared. Contributions
                # remain request-local and retain the scalar bit/addition order.
                fit += contributions[codes]
                continue
            values = []
            for i in indices:
                if not known[i]:
                    values.append(0.)
                    continue
                mask = masks[i]
                hit = cache.get(mask)
                if hit is None:
                    hit = cache[mask] = weight * clamp(offset + sum(delta[bit] for bit in taste_bits(mask)), limit)
                values.append(hit)
            fit += values
        return np.exp(STRENGTH * fit + QUALITY * self.e.numpy_quality[indices])

    def _scores_vector(self, candidates, scores, hits, penalty):
        index = np.asarray(candidates)
        matrix = np.asarray(hits)
        groups = np.argmax(matrix, axis=0)
        close = matrix[groups, np.arange(len(candidates))] - penalty
        raw = np.zeros(len(candidates), dtype=np.float64)
        for group, taste in enumerate(self.tastes):
            positions = np.flatnonzero((groups == group) & (close > 0))
            raw[positions] = close[positions] * self._factors_vector(taste, index[positions])
        if self.best is None:
            self.best = [float(np.max(raw[groups == group], initial=0)) for group in range(len(self.groups))]
        self.group.update(zip(candidates, groups.tolist()))
        best = np.asarray(self.best)[groups]
        result = np.divide(raw, best, out=np.zeros(len(candidates)), where=(raw > 0) & (best > 0))
        result *= np.asarray(self.share)[groups]
        np.frombuffer(scores, dtype=np.float32)[index] = result
        return scores

    def source(self, i, among=None):
        """The show to match (or of among) that show i sits closest to, to name as its reason."""
        aff = self.affinities
        return max(among or self.scoring, key=lambda p: aff[p['id']][i])

    def penalty(self, i):
        """What looking like the disliked shows took off show i."""
        if not self.negatives:
            return 0.0
        return self.settings['dislike'] * sum(self.affinities[p['id']][i] for p in self.negatives) / len(self.negatives)

    def links(self, i, ids):
        """How close show i sits to each of the shows ids."""
        return [self.affinities[show_id][i] for show_id in ids]


class Closeness(dict):
    """How close every show sits to each of some shows, by show id, each worked out when it
    is first asked for (Engine.blend), so a long list's ranking works out only the few it
    needs."""

    def __init__(self, engine, settings):
        super().__init__()
        self.engine, self.settings = engine, settings

    def __missing__(self, show_id):
        found = self[show_id] = self.engine.blend(self.engine.by_id[show_id], self.settings)
        return found


class Wide:
    """One request's scoring for a list rating more than DENSE_MAX shows, from each rated
    show's closest shows (neighbours.py), with the same interests, tastes and shares as
    Ranking and the same answers to what it is asked.

    The closeness of every show to each of thousands of rated ones is out of reach, and
    averaged over hundreds of shows it would favour whatever sits near the middle of them
    all. So each liked show adds, to each of its closest shows, its closeness times how
    much its rating counts (WIDE_RATES, fading with age, WIDE_FADE), with themes and genres
    counting less than plot and franchise (WIDE_BROAD) and a show that is everyone's
    neighbour damped (WIDE_HUB): a candidate close to many liked shows gathers the most.
    Disliked shows take theirs away, at the dislike setting's strength. The interests come
    from the list's most telling liked shows (WIDE_ANCHORS), clustered as Ranking clusters
    a short list, and every other liked show joins the interest it sits closest to. A
    candidate goes to the interest that gathered most for it, and its score is that times
    how well it fits the interest's taste, measured against the interest's best and scaled
    by its share, as in Ranking. A group of only a few shows to match (WIDE_FEW), such as a
    title page's more like this, is matched on its whole closeness instead, and a show to
    match from outside the list has a taste of its own without the dislikes: one liked
    show against a long list's hundreds of dislikes would be the dislikes' taste alone.

    base is a Wide for the same list and settings whose interests, tastes and closest shows
    this one takes rather than working them out again, as a title page's more like this
    takes the page's."""

    def __init__(self, engine, scoring, negatives, affinities, settings, liked=None, base=None):
        e = self.e = engine
        self.negatives, self.affinities, self.settings = negatives, affinities, settings
        self.weights = weights_of(settings)
        # No liked list given means the shows to match are the list; an empty one means the
        # list likes nothing (a title page for a list of dislikes alone).
        liked = scoring if liked is None else liked
        self.scoring = scoring
        if base is not None:
            self.rows, self.strength, self.against = base.rows, dict(base.strength), base.against
            self.interests, self.interest_tastes, self.nearness = base.interests, base.interest_tastes, base.nearness
        else:
            self.rows, self.nearness = {}, None
            self.strength = fading(liked, lambda p: WIDE_RATES.get(p['weight'], p['weight']))
            self.against = fading(negatives, lambda p: 1.0)
            self.interests = self.cluster(liked) if liked else []
            # Each interest's taste is learned from its own shows against the disliked shows
            # that sit closest to it: a long list's hundreds of dislikes of one kind would
            # otherwise teach every interest to shun that kind.
            disliked = [[] for _ in self.interests]
            for p in negatives if self.interests else ():
                i = e.by_id[p['id']]
                if WIDE_OWN_DISLIKES:
                    disliked[self.nearest(i)].append(i)
                else:
                    for own in disliked:
                        own.append(i)
            self.interest_tastes = [Taste(e.attributes, [(e.by_id[p['id']], p['weight']) for p in interest], own)
                                    for interest, own in zip(self.interests, disliked)]
        self.groups, self.tastes, self.origin = [], [], []
        wanted = {p['id'] for p in scoring}
        for n, interest in enumerate(self.interests):
            group = [p for p in interest if p['id'] in wanted]
            if group:
                self.groups.append(group)
                self.tastes.append(self.interest_tastes[n])
                self.origin.append(n)
        known = {p['id'] for p in liked}
        for p in scoring:
            if p['id'] not in known:
                # A show outside the list (a title page's more like this) is its own
                # interest, with a taste of its own: the dislikes it sits near take their
                # part through what they take away.
                self.groups.append([p])
                self.tastes.append(Taste(e.attributes, [(e.by_id[p['id']], p['weight'])], []))
                self.origin.append(None)
                self.strength[p['id']] = 1.0
        weight = [sum(self.strength[p['id']] for p in g) for g in self.groups]
        total = sum(weight) or 1
        self.share = [(w / total) ** INTEREST_SHARE for w in weight]
        self.best = None
        self.group = {}
        self.gathered = self.members = None

    def row(self, i):
        found = self.rows.get(i)
        if found is None:
            found = self.rows[i] = self.e.row(i, self.settings)
        return found

    # ------------------------------------------------------------ interests

    def broad(self, i, j):
        """The theme and genre part of two shows' closeness, from their bits alone."""
        e = self.e
        _a, b, c, _d = self.weights
        return (b * e.theme_norm[i] * e.theme_norm[j] * (e.shows[i]['theme_bits'] & e.shows[j]['theme_bits']).bit_count()
                + c * e.genre_norm[i] * e.genre_norm[j] * (e.shows[i]['genre_bits'] & e.shows[j]['genre_bits']).bit_count())

    def cluster(self, liked):
        """The list's interests, heaviest first, each in list order: the anchors clustered
        by average linkage on their closeness from the index (or themes and genres alone
        for two shows neither lists), and every other liked show in the interest whose
        anchors it sits closest to on average."""
        e = self.e
        order = {p['id']: n for n, p in enumerate(liked)}
        anchors = sorted(liked, key=lambda p: (-p['weight'], -order[p['id']]))[:WIDE_ANCHORS]
        index = [e.by_id[p['id']] for p in anchors]
        listed = [dict(zip(*self.row(i)[:2])) for i in index]
        m = len(anchors)
        sim = [[0.0] * m for _ in range(m)]
        for x in range(m):
            for y in range(x + 1, m):
                there, back = listed[x].get(index[y]), listed[y].get(index[x])
                if there is None and back is None:
                    value = self.broad(index[x], index[y])
                else:
                    value = ((there if there is not None else back) + (back if back is not None else there)) / 2
                sim[x][y] = sim[y][x] = value
        clusters = average_linkage(sim, INTEREST_JOIN)
        self.ready(index, clusters)
        groups = [[anchors[x] for x in members] for members in clusters]
        for p in liked:
            i = e.by_id[p['id']]
            if i not in self.nearness['home']:
                groups[self.nearest(i)].append(p)
        # An interest needs WIDE_SUPPORT of the liked shows behind it, and WIDE_FEWEST at
        # least: a handful of shows has no taste of its own worth scoring by, so its shows
        # join the interests left. A show that joined an interest kept would join it again.
        least = max(WIDE_FEWEST, round(WIDE_SUPPORT * len(liked)))
        kept = [k for k, group in enumerate(groups) if len(group) >= least]
        if kept and len(kept) < len(clusters):
            left = [p for k, group in enumerate(groups) if k not in kept for p in group]
            clusters, groups = [clusters[k] for k in kept], [groups[k] for k in kept]
            self.ready(index, clusters)
            for p in left:
                groups[self.nearest(e.by_id[p['id']])].append(p)
        weight = lambda g: sum(q['weight'] for q in g)
        groups = [sorted(g, key=lambda q: order[q['id']]) for g in groups]
        ranked = sorted(range(len(clusters)), key=lambda k: (-weight(groups[k]), order[groups[k][0]['id']]))
        # From here on nearest() names interests in the order they are returned.
        self.nearness['order'] = [ranked.index(k) for k in range(len(clusters))]
        return [groups[k] for k in ranked]

    def ready(self, index, clusters):
        """What nearest() weighs a show against: each cluster's anchors, their closest
        shows and their themes and genres."""
        e = self.e
        home = {}
        for k, members in enumerate(clusters):
            for x in members:
                home[index[x]] = k
        size = [len(members) for members in clusters]
        count = len(clusters)
        # Each interest's anchors as theme and genre bits over the roots of their counts,
        # so a show's average theme and genre closeness to them is a few additions.
        _a, b, c, _d = self.weights
        bits = {}
        for k, members in enumerate(clusters):
            for x in members:
                s, i = e.shows[index[x]], index[x]
                for family, mask, norm, weight in (('t', s['theme_bits'], e.theme_norm[i], b),
                                                   ('g', s['genre_bits'], e.genre_norm[i], c)):
                    while mask:
                        low = mask & -mask
                        vector = bits.setdefault((family, low.bit_length() - 1), [0.0] * count)
                        vector[k] += weight * norm / size[k]
                        mask ^= low
        back = {}
        for i in home:
            for j, value in zip(*self.row(i)[:2]):
                back.setdefault(j, []).append((i, value))
        self.nearness = {'home': home, 'size': size, 'bits': bits, 'back': back, 'order': list(range(count)),
                         'broad': {}}

    def nearest(self, i):
        """The interest show i sits closest to on average over its anchors: their closeness
        from the index where one lists the other, and their themes and genres otherwise."""
        e, found = self.e, self.nearness
        home, size, bits = found['home'], found['size'], found['bits']
        count = len(size)
        s = e.shows[i]
        # The theme and genre part is the same for every show with the same bits, and shows
        # share far fewer bits than there are shows.
        key = (s['theme_bits'], s['genre_bits'])
        base = found['broad'].get(key)
        if base is None:
            base = [0.0] * count
            for family, mask, norm in (('t', key[0], e.theme_norm[i]), ('g', key[1], e.genre_norm[i])):
                while mask:
                    low = mask & -mask
                    vector = bits.get((family, low.bit_length() - 1))
                    if vector:
                        base = [total + norm * v for total, v in zip(base, vector)]
                    mask ^= low
            found['broad'][key] = base
        score = list(base)
        near = {}
        for j, value in zip(*self.row(i)[:2]):
            if j in home:
                near[j] = value
        for j, value in found['back'].get(i, ()):
            near[j] = (near[j] + value) / 2 if j in near else value
        for j, value in near.items():
            k = home[j]
            score[k] += (value - self.broad(i, j)) / size[k]
        return found['order'][max(range(count), key=lambda k: (score[k], -k))]

    def describe(self):
        """The list's interests, heaviest first: the shows each is named for (loves, then
        the newest), how many it holds and what it leans toward."""
        out = []
        for interest, taste in zip(self.interests, self.interest_tastes):
            order = {p['id']: n for n, p in enumerate(interest)}
            named = sorted(interest, key=lambda p: (-p['weight'], -order[p['id']]))[:WIDE_NAMED]
            leans = [f['label'] for f in taste.summary(limit=3)['leans']]
            out.append({'shows': [p['id'] for p in named], 'size': len(interest),
                        'weight': round(sum(p['weight'] for p in interest), 2), 'leans': leans[:3]})
        return out

    def fits(self, i):
        k = self.group.get(i)
        return self.tastes[k].reasons(i) if k is not None else []

    def interest_of(self, i):
        k = self.group.get(i)
        return self.origin[k] if k is not None else None

    # ------------------------------------------------------------ scoring

    def gather(self):
        """What each group gathered for each show ({index: evidence} per group), what the
        disliked shows took away, and for each show the most any group gathered and which."""
        e = self.e
        groups = []
        few = len(self.scoring) <= WIDE_FEW
        for group in self.groups:
            found = {}
            get = found.get
            if few:
                # A handful of shows to match: their whole closeness, as Ranking has it.
                for p in group:
                    weight = self.strength[p['id']]
                    for j, value in enumerate(self.affinities[p['id']]):
                        if value > 0:
                            found[j] = get(j, 0.0) + weight * value
                groups.append(found)
                continue
            for p in group:
                weight = self.strength[p['id']]
                index, _close, evidence = self.row(e.by_id[p['id']])
                for j, value in zip(index, evidence):
                    found[j] = get(j, 0.0) + weight * value
            groups.append(found)
        taken = {}
        get = taken.get
        for p in self.negatives:
            weight = self.against[p['id']]
            index, _close, evidence = self.row(e.by_id[p['id']])
            for j, value in zip(index, evidence):
                taken[j] = get(j, 0.0) + weight * value
        lead = {}
        for k, found in enumerate(groups):
            best = lead.get
            for j, value in found.items():
                held = best(j)
                if held is None or value > held[0]:
                    lead[j] = (value, k)
        self.gathered = groups, taken, lead
        return self.gathered

    def around(self, j):
        """For a show no show to match counts among its closest: what those among its own
        closest add the other way round, as (the most one group gathers, that group), or
        None."""
        e = self.e
        if self.members is None:
            self.members = {e.by_id[p['id']]: (k, self.strength[p['id']]) for k, group in enumerate(self.groups)
                            for p in group}
        found = {}
        index, _close, evidence = self.row(j)
        for i, value in zip(index, evidence):
            member = self.members.get(i)
            if member:
                found[member[0]] = found.get(member[0], 0.0) + member[1] * value
        if not found:
            return None
        k = max(found, key=lambda k: (found[k], -k))
        return found[k], k

    def score(self, candidates):
        scores = array('f', [0]) * self.e.n
        if not self.groups or not candidates:
            return scores
        _groups, taken, lead = self.gathered or self.gather()
        dislike = self.settings['dislike']
        # A few shows scored on their own (a title, My List, the Top 10) are met from
        # their side too when no liked show counts them among its closest.
        few = len(candidates) <= WIDE_AROUND
        raw = []
        for j in candidates:
            found = lead.get(j)
            if found is None and few:
                found = self.around(j)
            if found is None:
                continue
            value, k = found
            hit = value - dislike * taken.get(j, 0.0)
            raw.append((j, k, hit * self.tastes[k].factor(j) if hit > 0 else 0.0))
        if self.best is None:
            self.best = [0.0] * len(self.groups)
            for _j, k, value in raw:
                if value > self.best[k]:
                    self.best[k] = value
        for j, k, value in raw:
            self.group[j] = k
            if value > 0 and self.best[k] > 0:
                scores[j] = value / self.best[k] * self.share[k]
        return scores

    def source(self, i, among=None):
        """The show to match (or of among) that show i sits closest to: from the index when
        one of them lists it or it lists one of them, else by themes and genres."""
        e = self.e
        among = among or self.scoring
        best, found = 0.0, None
        for p in among:
            index, close, _evidence = self.row(e.by_id[p['id']])
            if i in index:
                value = close[index.index(i)]
                if value > best:
                    best, found = value, p
        if found:
            return found
        ids = {p['id']: p for p in among}
        index, close, _evidence = self.row(i)
        best = max(((value, n) for n, (j, value) in enumerate(zip(index, close)) if e.shows[j]['id'] in ids),
                   default=None)
        if best:
            return ids[e.shows[index[best[1]]]['id']]
        return max(among, key=lambda p: self.broad(e.by_id[p['id']], i))

    def penalty(self, i):
        _groups, taken, _lead = self.gathered or self.gather()
        return self.settings['dislike'] * taken.get(i, 0.0)

    def links(self, i, ids):
        return self.e.pairs(i, [self.e.by_id[show_id] for show_id in ids], self.settings)


def fading(shows, weight):
    """{show id: weight} for shows in rating order, oldest first, each faded by its age."""
    floor, half = WIDE_FADE
    last = len(shows) - 1
    return {p['id']: weight(p) * (floor + (1 - floor) * 0.5 ** ((last - n) / half)) for n, p in enumerate(shows)}


def average_linkage(sim, join):
    """Groups of positions 0 to len(sim) - 1, merged two at a time while the best average
    closeness between two groups is at least join. Each group keeps the group it links to
    best, so a merge looks again only where that changed. sim is changed in place."""
    m = len(sim)
    members = {x: [x] for x in range(m)}

    def partner(x):
        return max(((sim[x][y], -y) for y in members if y != x), default=(-1.0, 0))
    best = {x: partner(x) for x in members}
    while len(members) > 1:
        x = max(members, key=lambda k: (best[k][0], -k))
        value, y = best[x][0], -best[x][1]
        if value < join:
            break
        nx, ny = len(members[x]), len(members[y])
        for k in members:
            if k != x and k != y:
                sim[x][k] = sim[k][x] = (nx * sim[x][k] + ny * sim[y][k]) / (nx + ny)
        members[x] += members.pop(y)
        del best[y]
        for k in members:
            if k == x or best[k][1] in (-x, -y):
                best[k] = partner(k)
            elif (sim[k][x], -x) > best[k]:
                best[k] = (sim[k][x], -x)
    return [sorted(group) for group in members.values()]
