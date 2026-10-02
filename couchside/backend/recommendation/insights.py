"""Small, descriptive taste views from the recommender's existing attributes.

Charts count all known liked shows, weighted by their rating. Their catalogue
comparison uses the same reference population as taste.py, with exact counts
rather than its smoothing floor. Themes describe plot text; they are not a new
recommendation score. Interest groups use the home's existing ranking model.
"""
import hashlib
import json

from .engine import Closeness
from .taste import REFERENCE_MIN, bits

DIMENSIONS = {'genre': 8, 'theme': 6}
MAX_INTERESTS = 8
MAX_NAMES = 6


class Insights:
    """Catalogue counts are shared; a person's profile lasts only for the request."""

    def __init__(self, engine):
        self.e = engine
        self.reference = [i for i, show in enumerate(engine.shows)
                          if show['recommendable'] and engine.popularity[i] >= REFERENCE_MIN]
        self.catalog = {}
        attributes = engine.attributes
        for family in DIMENSIONS:
            counts = [0] * len(attributes.labels[family])
            known = [i for i in self.reference if attributes.known[family][i]]
            for i in known:
                for bit in bits(attributes.masks[family][i]):
                    counts[bit] += 1
            self.catalog[family] = (counts, len(known))

    def chart(self, family, profile, taste):
        """Weighted own shares and unweighted reference shares, on the same 0–1 scale.

        Missing plot text or genres is excluded from both denominators. A known
        plot with no detected theme remains in the theme denominator. Null means
        there is no denominator; zero means known shows lack that dimension.
        """
        e, a = self.e, self.e.attributes
        masses, total, bad, _bad_total, support = taste.stats.get(family, ({}, 0, {}, 0, {}))
        counts, catalog_total = self.catalog[family]
        dimensions = []
        for bit, label in enumerate(a.labels[family]):
            mass = masses.get(bit, 0)
            dimensions.append({
                'key': f'{family}:{label}', 'label': label,
                'liked': round(mass / total, 6) if total else None,
                'catalog': round(counts[bit] / catalog_total, 6) if catalog_total else None,
                'liked_count': support.get(bit, 0), 'liked_weight': round(mass, 3),
                'disliked_count': bad.get(bit, 0), 'catalog_count': counts[bit],
            })
        dimensions.sort(key=lambda d: (-(d['liked'] or 0), -(d['catalog'] or 0), d['label']))
        known = a.known[family]
        return {
            'coverage': {
                'liked_count': sum(p['weight'] > 0 and bool(known[e.by_id[p['id']]]) for p in profile),
                'liked_weight': round(total, 3),
                'disliked_count': sum(p['weight'] < 0 and bool(known[e.by_id[p['id']]]) for p in profile),
                'catalog_count': catalog_total,
            },
            'available': len(dimensions), 'dimensions': dimensions[:DIMENSIONS[family]],
        }

    def interests(self, profile, settings):
        """Reuse home interest groups without scoring every catalogue candidate."""
        e = self.e
        focused = e.focus(profile)
        liked = [p for p in focused if p['weight'] > 0]
        disliked = [p for p in focused if p['weight'] < 0]
        groups = e.ranking(liked, disliked, Closeness(e, settings), settings, liked).describe() if liked else []
        out = []
        for group in groups[:MAX_INTERESTS]:
            ids = group['shows'][:MAX_NAMES]
            out.append({**group, 'shows': ids, 'names': [e.shows[e.by_id[i]]['name'] for i in ids],
                        'size': group.get('size', len(group['shows']))})
        rated = len(liked) + len(disliked)
        return out, {'rated': rated, 'liked': len(liked), 'disliked': len(disliked),
                     'omitted': sum(p['weight'] != 0 for p in profile) - rated,
                     'interest_count': len(groups), 'interests_omitted': max(0, len(groups) - MAX_INTERESTS)}

    def describe(self, body):
        """Accept home's compact profile/settings contract and return bounded views."""
        try:
            profile, settings, _chosen, _fresh = self.e.read(body)
        except OverflowError as exc:
            # JSON allows very large integers; the shared numeric settings validator
            # must not turn one into a failed request instead of a validation error.
            raise ValueError('Choose valid numeric settings.') from exc
        taste = self.e.taste(profile)
        # A model without neighbour data ranks only its most recent ratings.
        # Recommendation leanings follow that same focus; descriptive charts do not.
        focused = self.e.focus(profile)
        model_taste = taste if focused is profile else self.e.taste(focused)
        counts = {
            'rated': len(profile), 'liked': sum(p['weight'] > 0 for p in profile),
            'disliked': sum(p['weight'] < 0 for p in profile),
            'neutral': sum(p['weight'] == 0 for p in profile),
            'loved': sum(p['weight'] == 1 for p in profile),
            'good': sum(p['weight'] == .7 for p in profile),
            'okay': sum(p['weight'] == .35 for p in profile),
            'liked_weight': round(sum(p['weight'] for p in profile if p['weight'] > 0), 3),
        }
        interests, model = self.interests(profile, settings)
        context = json.dumps([self.e.version, self.e.date, profile, settings], sort_keys=True, separators=(',', ':'))
        return {
            'version': 1, 'context': hashlib.sha256(context.encode()).hexdigest()[:24], 'date': self.e.date,
            'counts': counts,
            'reference': {'shows': len(self.reference), 'minimum_known': REFERENCE_MIN,
                          'description': 'Recommendable catalogue shows with a knownness score of at least 40; '
                                         'each comparison excludes shows missing that kind of data.'},
            'genres': self.chart('genre', profile, taste), 'themes': self.chart('theme', profile, taste),
            'taste': model_taste.summary(), 'interests': interests, 'model': model,
        }
