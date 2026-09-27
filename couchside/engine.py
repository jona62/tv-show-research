"""Similarity engine over the frozen TVmaze text, genre, and theme vectors.

Trimmed for the consumer app: it answers what to watch next, what a taste
profile looks like, and how a recommendation connects to it. The research-only
outputs (scatter axes, pairwise matrices, catalog correlations) are gone.
"""
from array import array
from functools import lru_cache
from pathlib import Path
import gzip
import json
import math
import re
import struct
import sys
import unicodedata

from titles import Titles

RATINGS = (-1, 0, .35, .7, 1)
MAX_LIST = 60
TOP_PICKS = 24

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

DEFAULT_SETTINGS = {
    'text': 40, 'themes': 35, 'genres': 25,
    'closest': .3, 'dislike': .35,
    'language': 'all', 'type': 'all', 'status': 'all',
    'year_min': 1990, 'runtime_min': 0, 'rating_min': 0, 'known_min': 85,
}

# Recognisable starting points so a first visit is two taps from a result.
QUICK_PICKS = [169, 82, 526, 2993, 44933, 23470, 431, 44458, 54198, 919,
               43687, 46562, 269, 16149, 305, 216]


def folded(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s.casefold()) if not unicodedata.combining(c))


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
        self.names = [folded(s['name']) for s in self.shows]
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
        ranges = {'text': (0, 100), 'themes': (0, 100), 'genres': (0, 100), 'closest': (0, 1),
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
        return parsed, result, chosen

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

    @lru_cache(maxsize=48)
    def components(self, index):
        """Cached catalog-to-show similarities. No user profile is ever cached."""
        source = self.shows[index]
        text = array('f', [0]) * self.n
        for term, value in self.text_items(index):
            for k in range(self.col_ptr[term], self.col_ptr[term + 1]):
                text[self.post_rows[k]] += value * self.post_values[k]

        def bits(field, counts):
            source_bits = source[field]
            n = source_bits.bit_count()
            return array('f', ((source_bits & s[field]).bit_count() / math.sqrt(n * counts[i]) if n and counts[i] else 0.0
                               for i, s in enumerate(self.shows)))
        return text, bits('theme_bits', self.theme_counts), bits('genre_bits', self.genre_counts)

    def blend(self, index, settings):
        """How close every show in the catalog sits to one show, with story, themes and
        genres weighted as the settings ask."""
        total = settings['text'] + settings['themes'] + settings['genres']
        a, b, c = (settings[k] / total for k in ('text', 'themes', 'genres'))
        t, h, g = self.components(index)
        return array('f', (min(1.0, a * x + b * y + c * z) for x, y, z in zip(t, h, g)))

    def rank(self, candidates, scoring, negatives, affinities, settings):
        """Scores for the candidates, in an array over the whole catalog: a weighted mean
        across the scoring shows blended with the closest of them, minus a penalty for
        looking like what you disliked. Affinities are keyed by show id."""
        norm = sum(p['weight'] for p in scoring)
        top_weight = max(p['weight'] for p in scoring)
        closest, dislike = settings['closest'], settings['dislike']
        scores = array('f', [0]) * self.n
        for i in candidates:
            mean = sum(p['weight'] * affinities[p['id']][i] for p in scoring) / norm
            best = max(p['weight'] / top_weight * affinities[p['id']][i] for p in scoring)
            hit = (1 - closest) * mean + closest * best
            if negatives:
                hit -= dislike * sum(affinities[p['id']][i] for p in negatives) / len(negatives)
            scores[i] = max(0.0, hit)
        return scores

    def signals(self, i):
        """Theme and genre names a show actually records."""
        s = self.shows[i]
        return ([name for j, name in enumerate(self.themes) if s['theme_bits'] & (1 << j)],
                list(s['genres']))

    def calculate(self, body):
        profile, settings, chosen = self.validate(body)
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
            'breadth': {'themes': [0, len(self.themes)], 'genres': [0, len(self.genres)]},
        }
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
        scores = self.rank(candidates, scoring, negatives, affinities, settings)
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
            }
        base['picks'] = [pick(i, rank + 1) for rank, i in enumerate(ordered[:TOP_PICKS])]

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
