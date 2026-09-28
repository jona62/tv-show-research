"""Stand-ins for the rows of Couchside's tiers past today's (library.Page.personal_rows,
interest_rows, explore_rows and browse_rows), for exercising a home page that goes on
tier by tier before the real rows exist: rows of the kinds and numbers each tier holds,
cut with the page's own helpers. Nothing here is served.

    import stub_tiers
    with stub_tiers.installed(library.Page):
        ...
"""
from collections import Counter
import contextlib
import statistics

from engine import FORMAT_GROUPS
from library import (EVIDENCE, FILTER_POOL, FORMAT_ROWS, GENRE_ROWS, HIDDEN, INTEREST_FLOOR, MOST_INTERESTS,
                     NEIGHBOURS, THEME_ROWS, Shelf, fans_of, slug)
from taste import decade as decade_of


def personal_rows(page):
    """Tier 1: Because you loved (or liked) each liked show with enough similar shows,
    and a row for each network and decade two or more liked shows share."""
    e = page.e
    owner = {p['id']: k for k, interest in enumerate(page.interests) for p in interest}
    liked = sorted(page.positives, key=lambda p: (-p['weight'], -page.order[p['id']]))
    rows = []
    for p in liked:
        k = owner.get(p['id'])
        if p['weight'] >= .7 and k is not None and page.near(p['id'], k)[0] >= NEIGHBOURS:
            rows.append(page.seed_row(p, k))
    shows = [e.by_id[p['id']] for p in liked]
    networks = Counter(e.shows[i]['channel'] for i in shows if e.shows[i]['channel'])
    for channel, n in networks.most_common(4):
        if n >= 2:
            found, score = page.default(page.take(lambda i, c=channel: e.shows[i]['channel'] == c))
            rows.append(Shelf(f'network-{slug(channel)}', f'More from {channel}', 'network', found, score,
                              evidence=0.8))
    decades = Counter(decade_of(e.shows[i]['year']) for i in shows if e.shows[i]['year'])
    for label, n in decades.most_common(3):
        if n >= 2:
            found, score = page.default(page.take(lambda i, d=label: decade_of(e.shows[i]['year']) == d))
            rows.append(Shelf(f'decade-{slug(label)}', f'Your kind of shows from {label}', 'decade', found, score,
                              evidence=0.8))
    return rows


def interest_rows(page):
    """Tier 2: hidden gems, popular, new, finished and half-hour shows for each interest."""
    e = page.e
    floor = page.stats['rating_q75']
    kinds = (('gems', 'Hidden gems', lambda i: page.pop(i) <= HIDDEN[0] and (e.shows[i]['rating'] or 0) >= floor),
             ('popular', 'Popular', lambda i: page.pop(i) >= 0.9),
             ('new', 'New', lambda i: e.shows[i]['year'] >= page.lib.year - 1),
             ('ended', 'Finished', lambda i: e.shows[i]['status'] == 'Ended'),
             ('short', 'Half-hour', lambda i: 0 < (e.shows[i]['runtime'] or 0) <= 35))
    heavy = sorted((k for k, s in enumerate(page.share) if s >= INTEREST_FLOOR / 2),
                   key=lambda k: -page.share[k])[:MOST_INTERESTS]
    rows = []
    for k in heavy:
        names = page.interest_names(k)
        for kind, label, test in kinds:
            found, score = page.default(page.take(test, pool=page.by_interest[k]), k)
            rows.append(Shelf(f'{kind}-for-{slug(names[0], 30)}', f'{label} for fans of {names[0]}', f'{kind}-interest',
                              found, score, interest=k, evidence=0.8, subtitle=fans_of(names)))
    return rows


def explore_rows(page):
    """Tier 3: languages and genres or formats the list has none of, best fits first."""
    e, lib = page.e, page.lib
    liked = [e.by_id[p['id']] for p in page.positives]
    fits = lambda items: [i for i in items if page.taste.scores[i] > 0 and i not in page.excluded][:FILTER_POOL]
    rows = []
    languages = {e.shows[i]['language'] for i in liked}
    for language, items in lib.by_language.items():
        if language not in languages:
            found, score = page.default(fits(items))
            rows.append(Shelf(f'explore-{slug(language)}', f'Try something in {language}', 'explore', found, score,
                              personal=False, evidence=0.7))
    for key, label in [*GENRE_ROWS.items(), *FORMAT_ROWS.items()]:
        if not any(lib._fits(key, i) for i in liked):
            found, score = page.default(fits(lib.shelf_by_key.get(key, ())))
            rows.append(Shelf(f'try-{slug(key)}', f'{label} to try', 'explore', found, score, personal=False,
                              evidence=0.7))
    taste = lambda row: statistics.fmean(page.taste_of(i) for i in row.items[:10]) if row.items else 0.0
    return sorted(rows, key=lambda row: (-taste(row), row.key))


def browse_rows(page):
    """Tier 4: every genre, theme and format as a row, keyed as today's rows key them."""
    e = page.e
    rows = []
    for g, title in GENRE_ROWS.items():
        found, score = page.default(page.take(lambda i, g=g: g in e.shows[i]['genres']))
        rows.append(Shelf(f'genre-{g}'.lower(), title, 'genre', found, score, personal=False,
                          evidence=EVIDENCE['genre']))
    for t, title in THEME_ROWS.items():
        bit = 1 << e.themes.index(t)
        found, score = page.default(page.take(lambda i, bit=bit: e.shows[i]['theme_bits'] & bit))
        rows.append(Shelf(f'theme-{slug(title)}', title, 'genre', found, score, personal=False,
                          evidence=EVIDENCE['theme']))
    for key, title in FORMAT_ROWS.items():
        allowed = FORMAT_GROUPS[key]
        found, score = page.default(page.take(lambda i, a=allowed: e.shows[i]['type'] in a))
        rows.append(Shelf(f'format-{key}', title, 'genre', found, score, personal=False, evidence=EVIDENCE['genre']))
    return rows


STUBS = {'personal_rows': personal_rows, 'interest_rows': interest_rows, 'explore_rows': explore_rows,
         'browse_rows': browse_rows}


def install(page_class):
    """Put the stand-ins in place of the page's own tier rows, returning what they replace."""
    before = {name: getattr(page_class, name) for name in STUBS}
    for name, stub in STUBS.items():
        setattr(page_class, name, stub)
    return before


@contextlib.contextmanager
def installed(page_class, **others):
    """The stand-ins in place for a while, with any other methods given by name, such as
    personal_rows=lambda page: [] for a tier with no rows."""
    stubs = {**STUBS, **others}
    before = {name: getattr(page_class, name) for name in stubs}
    for name, stub in stubs.items():
        setattr(page_class, name, stub)
    try:
        yield
    finally:
        for name, original in before.items():
            setattr(page_class, name, original)
