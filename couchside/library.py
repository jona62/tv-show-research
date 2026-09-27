"""Couchside's shelves: rows, title pages and match scores over the shared engine.

The engine answers one question, what to watch next. A streaming front page asks
several at once (top picks, more like each show you loved, the best of a genre for
you, what is new), so this works out how close everything sits to each rated show
once per request and cuts every row from that. Nothing about a person is kept
between requests.
"""
from array import array
from datetime import date
from functools import lru_cache
import gzip
import struct
import sys

from engine import FORMAT_GROUPS, QUICK_PICKS

IMAGE = 'https://static.tvmaze.com/uploads/images/{size}/{bucket}/{image}.jpg'
ROW = 20            # cards in a row
SHORTEST = 6        # a row with fewer cards than this is left out
MORE = 12           # cards under More like this
SEEDS = 3           # "Because you loved" rows
GLANCE = 6          # cards a row shows before scrolling, kept distinct across rows
MAX_SAVED = 200     # My List, the same ceiling the transfer code carries

GENRE_ROWS = {
    'Action': 'Action shows', 'Adventure': 'Adventures', 'Anime': 'Anime', 'Children': 'For the kids',
    'Comedy': 'Comedies', 'Crime': 'Crime TV shows', 'DIY': 'DIY and makeovers', 'Drama': 'Dramas',
    'Espionage': 'Spy shows', 'Family': 'Family watching', 'Fantasy': 'Fantasy shows', 'Food': 'Food shows',
    'History': 'History shows', 'Horror': 'Horror', 'Legal': 'Legal dramas', 'Medical': 'Medical shows',
    'Music': 'Music shows', 'Mystery': 'Mysteries', 'Nature': 'Nature shows', 'Romance': 'Romance',
    'Science-Fiction': 'Sci-fi shows', 'Sports': 'Sports shows', 'Supernatural': 'Supernatural shows',
    'Thriller': 'Thrillers', 'Travel': 'Travel shows', 'War': 'War stories', 'Western': 'Westerns',
}
THEME_ROWS = {
    'Crime / illicit enterprise': 'Crime and the underworld', 'Money / class': 'Money and class',
    'Family ties': 'Family ties', 'Power / ambition': 'Power and ambition',
    'Deception / secrets': 'Secrets and lies', 'Danger / survival': 'Survival stories',
    'Adventure / quest': 'Quests and adventures', 'Law / investigation': 'Cases to crack',
    'Friendship / youth': 'Friendship and growing up', 'Romance': 'Love stories',
    'Supernatural / fantasy': 'Otherworldly stories', 'Humor': 'Shows that make you laugh',
    'Science / technology': 'Science and technology', 'Space / other worlds': 'Other worlds',
    'Medicine / health': 'Life and death in medicine', 'War / military': 'War and the military',
    'History / period setting': 'Period pieces', 'Work / business': 'Workplace stories',
    'School / education': 'School stories', 'Identity / self-discovery': 'Finding yourself',
    'Revenge / redemption': 'Revenge and redemption', 'Psychology / mental health': 'Minds under pressure',
    'Competition / achievement': 'Winners and contenders', 'Sport / athletics': 'Sporting lives',
    'Music / performance': 'Music and performance', 'Food / cooking': 'Food and cooking',
    'Nature / wildlife': 'Nature and wildlife', 'Travel / cultures': 'Travel and cultures',
    'Relationships / dating': 'Love and dating', 'Home / design': 'Home and design',
    'Belief / spirituality': 'Faith and belief', 'Mystery / puzzles': 'Mysteries to solve',
}
# Rows for a first visit, before anything is rated: best known first.
COLD_ROWS = [('genre', 'Drama'), ('genre', 'Comedy'), ('genre', 'Crime'), ('genre', 'Science-Fiction'),
             ('format', 'animation'), ('genre', 'Thriller'), ('format', 'documentary'),
             ('genre', 'Fantasy'), ('format', 'unscripted'), ('genre', 'Anime')]
FORMAT_ROWS = {'animation': 'Animated series', 'documentary': 'Documentaries', 'unscripted': 'Reality and competition'}
NEW_DAYS = 150      # a show premiered this recently before the snapshot wears a New badge
DESCRIPTION = 'Rows of TV shows picked for your taste, with trailers, where to watch and My List.'


def lower_first(label):
    """'Crime TV shows' as 'crime TV shows', leaving 'DIY and makeovers' alone."""
    return label[0].lower() + label[1:] if label[1:2].islower() else label


class Rows:
    """Rows being cut for one page. The first cards of a row are the ones a screen shows
    at a glance, so those skip anything an earlier row already opened with. The rest
    keep their own order: a row about Breaking Bad should still hold the shows closest
    to it."""

    def __init__(self, library, taste):
        self.lib, self.taste, self.used, self.rows = library, taste, set(), []

    def add(self, key, title, items, kind='row', fresh=True):
        if fresh:
            head = [i for i in items if i not in self.used][:GLANCE]
            items = head + [i for i in items if i not in head][:ROW - len(head)]
            self.used.update(head)
        else:
            items = items[:ROW]
        if len(items) >= SHORTEST:
            self.fixed(key, title, items, kind)

    def fixed(self, key, title, items, kind='row'):
        self.rows.append({'key': key, 'title': title, 'kind': kind,
                          'items': [self.lib.card(i, self.taste) for i in items]})


class Taste:
    """One request's view of a list: how close every show sits to each rated show, and
    the scores the plain ranking gives. Built once and cut into every row."""

    def __init__(self, library, positives, negatives, settings, candidates):
        self.lib, self.e = library, library.e
        self.positives, self.negatives, self.settings = positives, negatives, settings
        self.candidates = candidates
        key = (settings['text'], settings['themes'], settings['genres'])
        self.affinities = {p['id']: library.blend(self.e.by_id[p['id']], *key) for p in positives + negatives}
        self.scores = self.e.rank(candidates, positives, negatives, self.affinities, settings)
        self.best = max((self.scores[i] for i in candidates), default=0.0)
        self.extra = {}

    def ranked(self, scoring=None):
        """Candidates in order for the whole list, or for a few of its shows."""
        scores = self.scores if scoring is None else self.e.rank(
            self.candidates, scoring, self.negatives, self.affinities, self.settings)
        return sorted((i for i in self.candidates if scores[i] > 0), key=lambda i: (-scores[i], self.e.shows[i]['id']))

    def score_others(self, indices):
        """Scores for shows outside the pool (rated, obscure, filtered out), worked out
        in one pass so a match can be shown for anything on screen."""
        missing = [i for i in dict.fromkeys(indices) if i not in self.extra]
        if missing and self.positives:
            scores = self.e.rank(missing, self.positives, self.negatives, self.affinities, self.settings)
            self.extra.update((i, scores[i]) for i in missing)

    def match(self, i):
        """The same scale Next Watch uses: 99 is your best pick, and everything else is
        measured against it. None when a show scores nothing at all."""
        score = self.extra.get(i, self.scores[i]) if self.positives else 0.0
        if score <= 0 or self.best <= 0:
            return None
        return max(1, min(99, round(score / self.best * 99)))

    def closest(self, i):
        """The liked show a title sits nearest to, with the signals they share."""
        source = max(self.positives, key=lambda p: self.affinities[p['id']][i])
        mine, theirs = self.e.signals(i), self.e.signals(self.e.by_id[source['id']])
        shared = [t.split(' / ')[0] for t in mine[0] if t in theirs[0]] + [g for g in mine[1] if g in theirs[1]]
        seen, labels = set(), []
        for label in shared:
            if label.lower() not in seen:
                seen.add(label.lower())
                labels.append(label)
        return {'id': source['id'], 'name': self.e.shows[self.e.by_id[source['id']]]['name'],
                'loved': source['weight'] == 1, 'shared': labels[:3]}


class Library:
    def __init__(self, engine, art_path):
        self.e = e = engine
        with gzip.open(art_path, 'rb') as f:
            data = f.read()
        if data[:4] != b'ART1':
            raise ValueError('Not a Couchside art file.')
        (count,) = struct.unpack('<I', data[4:8])
        if count != e.n or len(data) != 8 + 6 * count:
            raise ValueError('Art track does not match the catalog.')
        self.images = array('I')
        self.images.frombytes(data[8:8 + 4 * count])
        self.ended = array('H')
        self.ended.frombytes(data[8 + 4 * count:])
        if sys.byteorder != 'little':
            self.images.byteswap()
            self.ended.byteswap()
        self.year = int(e.date[:4])
        self.blend = lru_cache(maxsize=96)(self._blend)

        # Everything below is the same for everyone, so it is worked out once.
        rating = lambda i: e.shows[i]['rating'] or 0
        shelf = [i for i, s in enumerate(e.shows) if s['recommendable'] and self.images[i] and e.popularity[i] >= 85]
        shelf.sort(key=lambda i: (-e.popularity[i], -rating(i), e.shows[i]['id']))
        self.shelf = shelf
        current = [i for i in shelf if e.shows[i]['year'] >= self.year - 1
                   or (e.shows[i]['status'] == 'Running' and e.shows[i]['year'] >= self.year - 5)]
        self.top10 = current[:10]
        self.top10_set = set(self.top10)
        today = date.fromisoformat(e.date)
        self.recent = {i for i in shelf if e.shows[i]['premiered']
                       and 0 <= (today - date.fromisoformat(e.shows[i]['premiered'])).days <= NEW_DAYS}
        self.popular = [i for i in shelf if i not in set(self.top10)][:ROW]
        self.acclaimed = sorted((i for i in shelf if rating(i) >= 8.5), key=lambda i: (-rating(i), e.shows[i]['id']))
        self.fresh = [i for i in shelf if e.shows[i]['year'] == self.year]
        soon = [i for i, s in enumerate(e.shows)
                if (s['premiered'] or '') > e.date and self.images[i] and e.popularity[i] >= 90]
        self.soon = sorted(soon, key=lambda i: (e.shows[i]['premiered'], -e.popularity[i]))[:ROW]
        self.cold = []
        for kind, value in COLD_ROWS:
            if kind == 'genre':
                items = [i for i in shelf if value in e.shows[i]['genres']]
                title = GENRE_ROWS[value]
            else:
                allowed = FORMAT_GROUPS[value]
                items = [i for i in shelf if e.shows[i]['type'] in allowed]
                title = FORMAT_ROWS[value]
            self.cold.append((f'{kind}-{value}'.lower(), title, items))
        self.starters = self._starters()
        # Everything a person can browse by, each fronted by its best-known show that no
        # earlier tile already uses, so the grid does not repeat one poster.
        self.genres, fronted = [], set()
        for key, label in [*GENRE_ROWS.items(), *FORMAT_ROWS.items()]:
            fits = [i for i in shelf if self._fits(key, i)]
            top = next((i for i in fits if i not in fronted), fits[0] if fits else None)
            if top is not None:
                fronted.add(top)
                self.genres.append({'key': key, 'label': label, 'poster': self.poster(top)})

    # ------------------------------------------------------------ shapes

    def _blend(self, index, text, themes, genres):
        return self.e.blend(index, {'text': text, 'themes': themes, 'genres': genres})

    def poster(self, i, size='medium_portrait'):
        image = self.images[i]
        return IMAGE.format(size=size, bucket=image // 2500, image=image) if image else None

    def card(self, i, taste=None):
        s = self.e.shows[i]
        return {'id': s['id'], 'name': s['name'], 'year': s['year'], 'poster': self.poster(i),
                'genres': s['genres'][:3], 'runtime': s['runtime'], 'type': s['type'],
                'match': taste.match(i) if taste else None,
                'badge': 'top10' if i in self.top10_set else 'new' if i in self.recent else None}

    def _fits(self, key, i):
        """Whether show i belongs under a genre, or under a format such as animation."""
        if key in FORMAT_ROWS:
            return self.e.shows[i]['type'] in FORMAT_GROUPS[key]
        return key in self.e.shows[i]['genres']

    def detail(self, i, taste=None):
        themes, _genres = self.e.signals(i)
        return {**self.e.full(i), 'ended': self.ended[i] or None, 'premiered': self.e.shows[i]['premiered'],
                'poster': self.poster(i), 'art': self.poster(i, 'original_untouched'),
                'themes': [t.split(' / ')[0] for t in themes], 'match': taste.match(i) if taste else None}

    def _starters(self):
        """Posters for a first visit to pick from: recognisable titles, spread across kinds."""
        e, picked = self.e, []
        for show_id in QUICK_PICKS:
            i = e.by_id.get(show_id)
            if i is not None and self.images[i]:
                picked.append(i)
        for _key, _title, items in self.cold:
            picked += [i for i in items if i not in picked][:3]
        return [self.card(i) for i in picked[:40]]

    # ------------------------------------------------------------ requests

    def read_list(self, body):
        """My List as ids, most recently added last. Unknown ids are dropped, which is
        what a list saved against an older snapshot needs."""
        ids = body.get('list', [])
        if not isinstance(ids, list) or len(ids) > MAX_SAVED:
            raise ValueError(f'My List can hold up to {MAX_SAVED} shows.')
        if any(type(i) is not int for i in ids):
            raise ValueError('Show ids must be whole numbers.')
        return [self.e.by_id[i] for i in dict.fromkeys(ids) if i in self.e.by_id]

    def prepare(self, body):
        profile, settings, _chosen = self.e.validate(body)
        positives = [p for p in profile if p['weight'] > 0]
        negatives = [p for p in profile if p['weight'] < 0]
        rated = {p['id'] for p in profile}
        kind = settings['type']
        formats = None if kind == 'all' else set(FORMAT_GROUPS.get(kind, (kind,)))
        candidates = [i for i, s in enumerate(self.e.shows)
                      if s['id'] not in rated and self.e.eligible(i, settings, formats)]
        return profile, settings, positives, negatives, rated, candidates

    def home(self, body):
        profile, settings, positives, negatives, rated, candidates = self.prepare(body)
        saved = self.read_list(body)
        e = self.e
        if not positives:
            return self._cold(saved, rated)
        taste = Taste(self, positives, negatives, settings, candidates)
        top = taste.ranked()
        unrated = lambda items: [i for i in items if e.shows[i]['id'] not in rated]
        fixed = self.top10 + unrated(self.acclaimed) + unrated(self.popular) + unrated(self.fresh) + saved
        taste.score_others(fixed)

        out = Rows(self, taste)
        add = out.add

        # Seeds for "Because you loved": loved before liked, newest first.
        order = {p['id']: n for n, p in enumerate(profile)}
        seeds = sorted(positives, key=lambda p: (-p['weight'], -order[p['id']]))[:SEEDS]
        seed_rows = []
        for seed in seeds:
            verb = 'loved' if seed['weight'] == 1 else 'liked'
            name = e.shows[e.by_id[seed['id']]]['name']
            seed_rows.append((f'seed-{seed["id"]}', f'Because you {verb} {name}', taste.ranked([seed])))

        genre_weight, theme_weight = {}, {}
        for p in positives:
            themes, genres = e.signals(e.by_id[p['id']])
            for g in genres:
                if g in GENRE_ROWS:
                    genre_weight[g] = genre_weight.get(g, 0) + p['weight']
            for t in themes:
                theme_weight[t] = theme_weight.get(t, 0) + p['weight']
        genres = sorted(genre_weight, key=lambda g: (-genre_weight[g], g))[:2]
        themes = sorted(theme_weight, key=lambda t: (-theme_weight[t], t))[:1]

        add('top', 'Top picks for you', top)
        if seed_rows:
            add(*seed_rows[0])
        out.fixed('top10', 'Top 10 shows today', self.top10, 'top10')
        for g in genres[:1]:
            add(f'genre-{g}'.lower(), GENRE_ROWS[g], [i for i in top if g in e.shows[i]['genres']])
        if len(seed_rows) > 1:
            add(*seed_rows[1])
        add('new', 'New for you', [i for i in top if e.shows[i]['year'] >= self.year - 1])
        for t in themes:
            bit = 1 << e.themes.index(t)
            add('theme', THEME_ROWS[t], [i for i in top if e.shows[i]['theme_bits'] & bit])
        for g in genres[1:]:
            add(f'genre-{g}'.lower(), GENRE_ROWS[g], [i for i in top if g in e.shows[i]['genres']])
        if len(seed_rows) > 2:
            add(*seed_rows[2])
        by_taste = lambda items: sorted(items, key=lambda i: (-(taste.match(i) or 0), e.shows[i]['id']))
        add('acclaimed', 'Critically acclaimed', by_taste(unrated(self.acclaimed)))
        add('popular', 'Popular right now', unrated(self.popular), fresh=False)

        hero = top[0] if top else self.top10[0]
        taste.score_others([hero])
        return {
            'personal': True, 'date': e.date,
            'hero': {**self.detail(hero, taste), 'because': taste.closest(hero) if top else None},
            'rows': out.rows,
            'top10': [self.card(i, taste) for i in self.top10],
            'fresh': [self.card(i, taste) for i in by_taste(unrated(self.fresh))[:ROW]],
            'soon': [{**self.card(i), 'premiered': e.shows[i]['premiered']} for i in self.soon],
            # My List is drawn by the page, which keeps it instant; these carry its matches.
            'list': [self.card(i, taste) for i in saved],
            'message': '' if top else 'Nothing matches these settings. Widen the catalogue in your profile menu.',
        }

    def _cold(self, saved, rated):
        rows = [{'key': 'top10', 'title': 'Top 10 shows today', 'kind': 'top10',
                 'items': [self.card(i) for i in self.top10]}]
        rows.append({'key': 'popular', 'title': 'Popular right now', 'kind': 'row', 'items': [self.card(i) for i in self.popular]})
        for key, title, items in self.cold:
            rows.append({'key': key, 'title': title, 'kind': 'row',
                         'items': [self.card(i) for i in items if self.e.shows[i]['id'] not in rated][:ROW]})
        rows.insert(3, {'key': 'acclaimed', 'title': 'Critically acclaimed', 'kind': 'row',
                        'items': [self.card(i) for i in self.acclaimed[:ROW]]})
        return {
            'personal': False, 'date': self.e.date,
            'hero': {**self.detail(self.top10[0]), 'because': None},
            'rows': [r for r in rows if len(r['items']) >= SHORTEST],
            'top10': [self.card(i) for i in self.top10],
            'fresh': [self.card(i) for i in self.fresh[:ROW]],
            'soon': [{**self.card(i), 'premiered': self.e.shows[i]['premiered']} for i in self.soon],
            'list': [self.card(i) for i in saved],
            'message': '',
        }

    def browse(self, body):
        """Rows for one genre or format: ranked for you once you have rated something,
        by popularity before that."""
        key = body.get('genre') if isinstance(body, dict) else None
        if not isinstance(key, str) or (key not in GENRE_ROWS and key not in FORMAT_ROWS):
            raise ValueError('Choose a genre to browse.')
        profile, settings, positives, negatives, rated, candidates = self.prepare(body)
        e = self.e
        label = GENRE_ROWS.get(key) or FORMAT_ROWS[key]
        noun = lower_first(label)
        shelf = [i for i in self.shelf if self._fits(key, i) and e.shows[i]['id'] not in rated]
        taste = Taste(self, positives, negatives, settings, candidates) if positives else None
        out = Rows(self, taste)
        rating = lambda i: e.shows[i]['rating'] or 0
        acclaimed = [i for i in shelf if rating(i) >= 8]
        if taste:
            taste.score_others(shelf)
            top = [i for i in taste.ranked() if self._fits(key, i)]
            out.add('top', f'Top {noun} for you', top)
            out.add('new', f'New {noun} for you', [i for i in top if e.shows[i]['year'] >= self.year - 1])
            out.add('acclaimed', f'Acclaimed {noun}', sorted(acclaimed, key=lambda i: (-(taste.match(i) or 0), e.shows[i]['id'])))
            out.add('popular', f'Popular {noun}', shelf)
            out.add('more', f'More {noun} you might like', top[ROW:])
        else:
            out.add('popular', f'Popular {noun}', shelf)
            out.add('new', f'New {noun}', [i for i in shelf if e.shows[i]['year'] >= self.year - 1])
            out.add('acclaimed', f'Acclaimed {noun}', sorted(acclaimed, key=lambda i: (-rating(i), e.shows[i]['id'])))
            out.add('more', f'More {noun}', shelf[ROW:])
        return {'genre': key, 'title': label, 'personal': bool(taste), 'rows': out.rows}

    def title(self, body):
        show_id = body.get('id') if isinstance(body, dict) else None
        if type(show_id) is not int or show_id not in self.e.by_id:
            raise ValueError('That show is not in this catalog.')
        profile, settings, positives, negatives, rated, candidates = self.prepare(body)
        e, i = self.e, self.e.by_id[show_id]
        taste = Taste(self, positives, negatives, settings, candidates) if positives else None
        key = (settings['text'], settings['themes'], settings['genres'])
        # More like this: closeness to this one show, less the pull of anything disliked.
        affinities = {show_id: self.blend(i, *key)}
        affinities.update(taste.affinities if taste else
                          {p['id']: self.blend(e.by_id[p['id']], *key) for p in negatives})
        pool = [j for j in candidates if j != i]
        near = e.rank(pool, [{'id': show_id, 'weight': 1}], negatives, affinities, settings)
        more = sorted((j for j in pool if near[j] > 0), key=lambda j: (-near[j], e.shows[j]['id']))[:MORE]
        if taste:
            taste.score_others([i, *more])
        show = self.detail(i, taste)
        show['because'] = taste.closest(i) if taste and show_id not in rated else None
        show['summary'] = show['summary'] or ''
        return {'show': show, 'more': [{**self.card(j, taste), 'summary': e.shows[j]['summary'] or ''} for j in more]}

    def cards(self, ids):
        return [self.card(self.e.by_id[i]) for i in ids if i in self.e.by_id]
