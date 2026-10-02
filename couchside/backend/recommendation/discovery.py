"""Page-local discovery constraints. They never change a person's saved taste."""
from collections import OrderedDict
from copy import copy
import gzip
import json
import threading

from .engine import FORMAT_GROUPS
from .library import Library, GENRE_ROWS, Taste
from ..episode_store import MAX_AGE

SORTS = ('relevance', 'popular', 'rating', 'newest', 'shortest', 'added', 'name')


def read_filters(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('Send filters as an object.')
    allowed = {'genres', 'rating', 'length', 'status', 'year', 'language', 'format',
               'episodes', 'seasons', 'hours', 'sort'}
    if set(raw) - allowed:
        raise ValueError('That filter is not available.')
    out = {}
    for key, value in raw.items():
        if value in (None, '', 0, 'all', 'relevance') or value == []:
            continue
        if key == 'genres':
            if not isinstance(value, list) or len(value) > len(GENRE_ROWS) or any(not isinstance(v, str) or v not in GENRE_ROWS for v in value):
                raise ValueError('Choose genres from the catalogue.')
            out[key] = sorted(set(value))
        elif key in ('rating', 'year', 'episodes', 'seasons', 'hours'):
            maximum = {'rating': 10, 'year': 2100, 'episodes': 10000, 'seasons': 200, 'hours': 10000}[key]
            if type(value) not in (int, float) or not 0 < value <= maximum or (key != 'hours' and int(value) != value):
                raise ValueError('Choose a valid filter limit.')
            out[key] = value
        elif key == 'language':
            if not isinstance(value, str) or len(value) > 60:
                raise ValueError('Choose a language.')
            out[key] = value
        else:
            choices = {'length': ('short', 'standard', 'long'), 'status': ('Running', 'Ended', 'In Development', 'To Be Determined'),
                       'format': tuple(FORMAT_GROUPS), 'sort': SORTS}
            if value not in choices[key]:
                raise ValueError('Choose a valid filter option.')
            out[key] = value
    return out


def fits(s, f):
    if f.get('genres') and not set(f['genres']).intersection(s.get('genres') or []):
        return False
    for key in ('rating', 'year'):
        if f.get(key) and (s.get(key) is None or s[key] < f[key]):
            return False
    for key in ('status', 'language'):
        if f.get(key) and s.get(key) != f[key]:
            return False
    if f.get('format') and s.get('type') not in FORMAT_GROUPS[f['format']]:
        return False
    runtime = s.get('runtime')
    if f.get('length') and (not runtime or not {'short': runtime < 30, 'standard': 30 <= runtime <= 60, 'long': runtime > 60}[f['length']]):
        return False
    for key in ('episodes', 'seasons'):
        if f.get(key) and (s.get(key) is None or s[key] <= 0 or s[key] > f[key]):
            return False
    if f.get('hours') and (not s.get('total_minutes') or s['total_minutes'] > 60 * f['hours']):
        return False
    return True


def sort_key(s, sort, popularity=0):
    if sort == 'rating':
        return (-(s.get('rating') or 0), s['id'])
    if sort == 'newest':
        return (-(s.get('year') or 0), s['id'])
    if sort == 'shortest':
        return (s.get('total_minutes') or float('inf'), s['id'])
    if sort == 'name':
        return (s['name'].casefold(), s['id'])
    return (-popularity, s['id'])


class Discovery:
    def __init__(self, library, store, path):
        self.library, self.store = library, store
        self.lock, self.views = threading.Lock(), OrderedDict()
        self.counts = {}
        try:
            with gzip.open(path, 'rt') as stream:
                entries = json.load(stream).get('shows', {})
            for key, value in entries.items():
                counts = {k: value.get(k) for k in ('episodes', 'seasons')}
                if any(type(v) is int and v > 0 for v in counts.values()):
                    self.counts[int(key)] = {k: v for k, v in counts.items() if type(v) is int and v > 0}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def metadata(self, show_id):
        s = self.library.e.shows[self.library.e.by_id[show_id]]
        held = self.store.summaries.get(show_id, {})
        if self.store.clock() - held.get('at', 0) > MAX_AGE:
            held = {}
        counts = {**(self.counts.get(show_id, {}) if s['status'] == 'Ended' else {}), **held}
        minutes = counts.get('total_minutes') or ((counts.get('episodes') or 0) * (s['runtime'] or 0)) or None
        return {'rating': s['rating'], 'rating_source': 'TVmaze' if s['rating'] else None,
                'popularity': self.library.e.popularity[self.library.e.by_id[show_id]],
                'status': s['status'], 'language': s['language'],
                'seasons': counts.get('seasons'), 'episodes': counts.get('episodes'),
                'total_minutes': minutes, 'minutes_estimated': counts.get('minutes_estimated', True)}

    def record(self, i):
        s = self.library.e.shows[i]
        return {**s, **self.metadata(s['id'])}

    def view(self, raw):
        filters = read_filters(raw)
        if not filters:
            return self.library
        changes = any(k in filters for k in ('hours', 'episodes', 'seasons')) or filters.get('sort') == 'shortest'
        key = (json.dumps(filters, sort_keys=True), self.store.revision if changes else 0)
        with self.lock:
            if key in self.views:
                self.views.move_to_end(key)
                return self.views[key]
            view = copy(self.library)
            view.__class__ = FilteredLibrary
            view.rules, view.base = filters, self.library
            view.allowed = {i for i in range(view.e.n) if fits(self.record(i), filters)}
            # Pagination is kept by the full request hash across metadata snapshots.
            # A new count must not discard rows already laid out for a scrolling visit.
            view._pools = {}
            take = lambda values: [i for i in values if i in view.allowed]
            for field in ('shelf', 'top10', 'popular', 'acclaimed', 'fresh', 'soon', 'classics', 'popular_pool'):
                setattr(view, field, take(getattr(view, field)))
            view.cold = [(k, t, take(items)) for k, t, items in view.cold]
            view.by_language = {k: take(v) for k, v in view.by_language.items()}
            view.shelf_by_key = {k: take(v) for k, v in view.shelf_by_key.items()}
            self.views[key] = view
            while len(self.views) > 8:
                self.views.popitem(last=False)
            return view

    def order(self, items, rules):
        sort = rules.get('sort', 'relevance')
        if sort in ('relevance', 'added'):
            return items
        return sorted(items, key=lambda i: sort_key(self.record(i), sort, self.library.e.popularity[i]))


class FilteredLibrary(Library):
    def daily(self, items, fresh, surface, length, pinned, rotating=0):
        if self.rules.get('sort', 'relevance') != 'relevance':
            return self.discovery.order(items, self.rules)[:length]
        return super().daily(items, fresh, surface, length, pinned, rotating)

    def browse(self, body):
        answer = super().browse(body)
        if not answer['rows']:
            profile, settings, positives, negatives, rated, candidates, _fresh = self.prepare(body)
            items = Taste(self, positives, negatives, settings, candidates).ranked() if positives else self.shelf
            items = [i for i in items if self.images[i] and self._fits(body['genre'], i) and self.e.shows[i]['id'] not in rated]
            if items:
                answer['rows'] = [{'key': 'matching', 'title': 'Shows that match', 'kind': 'row',
                                   'items': [self.card(i) for i in self.discovery.order(items, self.rules)[:20]]}]
        return answer

    def pool_stats(self, settings):
        stats = self.base.pool_stats(settings)
        return {**stats, 'pool': [i for i in stats['pool'] if i in self.allowed]}

    def read_list(self, body):
        return [i for i in super().read_list(body) if i in self.allowed]

    def _cold_featured(self, saved, rated, fresh):
        if not self.top10:
            return self.shelf[:6]
        return super()._cold_featured(saved, rated, fresh)

    def home(self, body):
        if not self.shelf:
            _profile, _settings, positives, _negatives, _rated, candidates, _fresh = self.prepare(body)
            fallback = [i for i in candidates if self.images[i]] if positives else []
            if fallback:
                view = copy(self)
                view.shelf = self.discovery.order(fallback, {'sort': 'popular'})
                return view.home(body)
            return {'personal': False, 'date': self.e.date, 'rows': [], 'more': False, 'list': [],
                    'top10': [], 'fresh': [], 'soon': [], 'popular': [], 'featured': [], 'hero': None,
                    'taste': {'leans': [], 'avoids': []}, 'interests': [],
                    'message': 'No shows match these filters. Try widening them or clear all.'}
        answer = super().home(body)
        answer['rows'] = [r for r in answer['rows'] if r['items']]
        if not answer['rows'] and 'shown' not in body:
            profile, settings, positives, negatives, rated, candidates, _fresh = self.prepare(body)
            items = Taste(self, positives, negatives, settings, candidates).ranked() if positives else self.shelf
            items = [i for i in items if self.images[i] and self.e.shows[i]['id'] not in rated]
            if items:
                answer['rows'] = [{'key': 'matching', 'title': 'Shows that match', 'kind': 'row',
                                   'items': [self.card(i) for i in self.discovery.order(items, self.rules)[:20]]}]
                answer['more'] = False
        # Hero fallbacks also respect the selection when none of the user's picks fit.
        if answer.get('hero') and self.e.by_id[answer['hero']['id']] not in self.allowed:
            answer['hero'] = self.detail(self.shelf[0])
            answer['featured'] = [answer['hero']]
        sort = self.rules.get('sort', 'relevance')
        if sort not in ('relevance', 'added'):
            key = lambda s: sort_key(s, sort, self.e.popularity[self.e.by_id[s['id']]])
            for row in answer['rows']:
                if row['kind'] != 'top10':
                    row['items'].sort(key=key)
            for field in ('fresh', 'soon', 'popular'):
                answer.get(field, []).sort(key=key)
        return answer
