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
    'year_min': 1990, 'runtime_min': 0, 'rating_min': 6.5,
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
        self.theme_counts = [s['theme_bits'].bit_count() for s in self.shows]
        self.genre_counts = [s['genre_bits'].bit_count() for s in self.shows]
        self.quick_picks = [self.card(self.by_id[i]) for i in QUICK_PICKS if i in self.by_id]

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
        return {k: s[k] for k in ('id', 'name', 'year', 'channel', 'rating', 'language', 'type')}

    def full(self, i):
        s = self.shows[i]
        return {k: s[k] for k in ('id', 'name', 'year', 'runtime', 'rating', 'genres', 'url',
                                  'channel', 'language', 'type', 'country', 'status', 'summary')}

    # ---------------------------------------------------------------- search

    def search(self, q):
        query = folded(q.strip())
        if len(query) < 2:
            return []
        tokens = query.split()
        matches = [i for i, name in enumerate(self.names) if all(t in name for t in tokens)]
        # Best-known first: exact title, then prefix, then public rating. Year only breaks ties.
        matches.sort(key=lambda i: (
            self.names[i].removeprefix('the ') != query,
            self.names[i] != query,
            not self.names[i].startswith(query),
            -(self.shows[i]['rating'] or 0),
            -(self.shows[i]['year'] or 0),
            len(self.names[i]),
            self.shows[i]['id'],
        ))
        return [self.card(i) for i in matches[:12]]

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
        settings = body.get('settings', {})
        if not isinstance(settings, dict):
            raise ValueError('Settings must be an object.')
        result = dict(DEFAULT_SETTINGS)
        ranges = {'text': (0, 100), 'themes': (0, 100), 'genres': (0, 100), 'closest': (0, 1),
                  'dislike': (0, 1), 'year_min': (1900, 2100), 'runtime_min': (0, 240), 'rating_min': (0, 10)}
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
        return parsed, result

    # ------------------------------------------------------------- scoring

    def text_items(self, index):
        return ((self.terms[k], self.values[k]) for k in range(self.row_ptr[index], self.row_ptr[index + 1]))

    def eligible(self, show, settings, formats=None):
        if not show['recommendable'] or show['year'] < settings['year_min']:
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

    def signals(self, i):
        """Theme and genre names a show actually records."""
        s = self.shows[i]
        return ([name for j, name in enumerate(self.themes) if s['theme_bits'] & (1 << j)],
                list(s['genres']))

    def calculate(self, body):
        profile, settings = self.validate(body)
        positives = [p for p in profile if p['weight'] > 0]
        negatives = [p for p in profile if p['weight'] < 0]
        watched_ids = {p['id'] for p in profile}
        base = {
            'date': self.date, 'catalog_count': self.n, 'candidate_count': 0,
            'settings': settings, 'positive_count': len(positives), 'negative_count': len(negatives),
            'picks': [], 'liked': [], 'features': [], 'context': [], 'message': '', 'warning': '',
            'breadth': {'themes': [0, len(self.themes)], 'genres': [0, len(self.genres)]},
        }
        if not positives:
            base['message'] = 'Rate one show as liked or loved to get recommendations.'
            return base

        kind = settings['type']
        formats = None if kind == 'all' else set(FORMAT_GROUPS.get(kind, (kind,)))
        candidates = [i for i, s in enumerate(self.shows)
                      if s['id'] not in watched_ids and self.eligible(s, settings, formats)]
        base['candidate_count'] = len(candidates)
        if any(self.shows[self.by_id[p['id']]]['summary_words'] < 15 for p in positives):
            base['warning'] = 'Some of your shows have very little plot text, so their matches lean on genres alone.'

        total = settings['text'] + settings['themes'] + settings['genres']
        a, b, c = (settings[k] / total for k in ('text', 'themes', 'genres'))
        affinities = {}
        for p in positives + negatives:
            t, h, g = self.components(self.by_id[p['id']])
            affinities[p['id']] = array('f', (min(1.0, a * x + b * y + c * z) for x, y, z in zip(t, h, g)))

        norm = sum(p['weight'] for p in positives)
        top_weight = max(p['weight'] for p in positives)
        closest, dislike = settings['closest'], settings['dislike']
        scores = array('f', [0]) * self.n
        for i in candidates:
            mean = sum(p['weight'] * affinities[p['id']][i] for p in positives) / norm
            best = max(p['weight'] / top_weight * affinities[p['id']][i] for p in positives)
            hit = (1 - closest) * mean + closest * best
            if negatives:
                hit -= dislike * sum(affinities[p['id']][i] for p in negatives) / len(negatives)
            scores[i] = max(0.0, hit)
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
            source = max(positives, key=lambda p: affinities[p['id']][i])
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
            base['message'] = ('Nothing matches these filters yet. Widen the year, language or format.'
                               if not candidates else 'No positive matches under these settings. Add another show you liked.')
        return base
