"""The recommender: closeness over TVmaze plot text, themes and genres, and taste.

It answers what to watch next, what a taste profile looks like, and how a pick
connects to it. A pick has to sit close to shows you liked (plot wording, themes,
genres) and fit what your whole list leans toward (taste.py); a list that holds
several interests has each scored on its own and given its share (Ranking). The
research-only outputs (scatter axes, pairwise matrices, catalog correlations) live
in site/.
"""
from array import array
from functools import lru_cache
from operator import itemgetter
from pathlib import Path
import gzip
import json
import math
import re
import struct
import sys

import facets
import fresh
from taste import Attributes, Taste
from titles import Titles

RATINGS = (-1, 0, .35, .7, 1)
MAX_LIST = 60
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
# Tuned on scripts/bench: franchises (spin-offs, sequels, shared universes) and makers
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

DEFAULT_SETTINGS = {
    'text': 40, 'themes': 35, 'genres': 25, 'facets': 30,
    'closest': .3, 'dislike': .35,
    'language': 'all', 'type': 'all', 'status': 'all',
    'year_min': 1900, 'runtime_min': 0, 'rating_min': 0, 'known_min': 60,
}

# Recognisable starting points so a first visit is two taps from a result.
QUICK_PICKS = [169, 82, 526, 2993, 44933, 23470, 431, 44458, 54198, 919,
               43687, 46562, 269, 16149, 305, 216]


class Engine:
    def __init__(self, path=None):
        model = Path(path) if path else Path(__file__).resolve().parent / 'model'
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
        # Wikidata's genres, makers, cast, franchises and subjects and TVmaze's networks,
        # when the model carries them (facets.py); a model without them ranks as before.
        self.facets = facets.load(model, self.n)
        if self.facets:
            known = [f for f in FACET_WEIGHTS if f in self.facets.families]
            total = sum(FACET_WEIGHTS[f] for f in known) or 1
            self.facet_weights = {f: FACET_WEIGHTS[f] / total for f in known}
        self.attributes = Attributes(self, self.subgenres())
        self.quick_picks = [self.card(self.by_id[i]) for i in QUICK_PICKS if i in self.by_id]
        self.titles = Titles(self.shows, self.popularity, model / 'search.json.gz')

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
        if not isinstance(profile, list) or len(profile) > MAX_LIST:
            raise ValueError(f'Your list can hold up to {MAX_LIST} shows.')
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
            raise ValueError(f'Choose up to {MAX_LIST} shows to match.')
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

    def ties(self, i, j):
        """What two shows concretely share beyond plot words: a franchise, a maker, cast,
        a Wikidata genre, a subject or a network, strongest first within each kind."""
        f = self.facets
        if not f:
            return []
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
        return out[:4]

    @lru_cache(maxsize=32)
    def components(self, index):
        """Cached catalog-to-show similarities: plot text, themes, genres and, when the
        model has them, facets. No user profile is ever cached."""
        source = self.shows[index]
        text = array('f', [0]) * self.n
        for term, value in self.text_items(index):
            for k in range(self.col_ptr[term], self.col_ptr[term + 1]):
                text[self.post_rows[k]] += value * self.post_values[k]

        def bits(field):
            masks, counts, where = self.combos[field]
            mine = source[field]
            n = mine.bit_count()
            if not n:
                return array('f', bytes(4 * self.n))
            table = [(mine & m).bit_count() / math.sqrt(n * c) if c else 0.0 for m, c in zip(masks, counts)]
            return array('f', map(table.__getitem__, where))
        near = self.facets.similarity(index, self.facet_weights) if self.facets else None
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
        if not extra or f is None:
            return array('f', [a * x + b * y + c * z for x, y, z in zip(t, h, g)])
        d = extra / 100
        return array('f', [a * x + b * y + c * z + d * w for x, y, z, w in zip(t, h, g, f)])

    def taste(self, profile):
        """The leanings of a whole list, liked and disliked shows alike."""
        return Taste(self.attributes,
                     [(self.by_id[p['id']], p['weight']) for p in profile if p['weight'] > 0],
                     [self.by_id[p['id']] for p in profile if p['weight'] < 0])

    def ranking(self, scoring, negatives, affinities, settings, liked=None):
        """How one request scores candidates: see Ranking."""
        return Ranking(self, scoring, negatives, affinities, settings, liked)

    def rank(self, candidates, scoring, negatives, affinities, settings, liked=None):
        """Scores for the candidates, in an array over the whole catalog. Affinities are
        keyed by show id. See Ranking for how they are made."""
        return self.ranking(scoring, negatives, affinities, settings, liked).score(candidates)

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
        positives = [p for p in profile if p['weight'] > 0]
        negatives = [p for p in profile if p['weight'] < 0]
        # Choosing shows narrows what the picks are matched to, not what your taste
        # is made of: only the scoring set shrinks. Every rated show still stays out
        # of the pool, dislikes still count, and the liked list, its signals and the
        # per-show links keep covering everything you liked. Ranking against a chosen
        # set is the same as ranking a list where every other liked show is re-rated
        # neutral, since neutral shows leave the pool but are never scored.
        scoring = [p for p in positives if p['id'] in set(chosen)] if chosen else positives
        watched_ids = {p['id'] for p in profile}
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

        affinities = {p['id']: self.blend(self.by_id[p['id']], settings) for p in positives + negatives}
        ranking = self.ranking(scoring, negatives, affinities, settings, positives)
        scores = ranking.score(candidates)
        base['taste'] = self.taste(profile).summary()
        base['interests'] = ranking.describe()
        dislike = settings['dislike']
        ordered = sorted((i for i in candidates if scores[i] > 0), key=lambda i: (-scores[i], self.shows[i]['id']))

        liked_indices = [self.by_id[p['id']] for p in positives]
        liked_order = [p['id'] for p in positives]
        liked_signals = {}
        for p in positives:
            index = self.by_id[p['id']]
            themes, genres = self.signals(index)
            liked_signals[p['id']] = (themes, genres)
            base['liked'].append({
                **self.card(index), 'weight': p['weight'], 'themes': themes, 'genres': genres,
                'has_plot': self.shows[index]['summary_words'] >= 15,
            })

        def pick(i, rank):
            s = self.shows[i]
            themes, genres = self.signals(i)
            source = max(scoring, key=lambda p: affinities[p['id']][i])
            source_index = self.by_id[source['id']]
            source_themes, source_genres = liked_signals[source['id']]
            penalty = dislike * sum(affinities[p['id']][i] for p in negatives) / len(negatives) if negatives else 0.0
            return {
                **self.full(i), 'rank': rank, 'score': round(scores[i] * 100, 1),
                'themes': themes, 'genres': genres,
                'because': self.shows[source_index]['name'],
                'because_id': self.shows[source_index]['id'],
                'shared_themes': [t for t in themes if t in source_themes],
                'shared_genres': [g for g in genres if g in source_genres],
                'keywords': self.plot_words(s),
                'penalised': round(penalty * 100, 1) if penalty > 0 else 0,
                'links': [round(affinities[pid][i] * 100, 1) for pid in liked_order],
                'known': self.popularity[i],
                'fits': ranking.fits(i),
                'ties': self.ties(i, source_index),
                'interest': ranking.interest_of(i),
            }
        base['picks'] = [{**pick(i, rank), 'place': place} if place else pick(i, rank)
                         for i, rank, place in self.arrange(ordered, scores, today)]

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
            'themes': [len({t for s in base['liked'] for t in s['themes']}), len(self.themes)],
            'genres': [len({g for s in base['liked'] for g in s['genres']}), len(self.genres)],
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
