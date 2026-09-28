"""Check the home page's rows past the first page: each interest's own (tier 2), rows to
explore (tier 3) and rows to browse (tier 4).

Run from the repository root:  .venv/bin/python couchside/test_explore_rows.py
It reads the repository's model/ directly and reaches nothing else.
"""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'couchside'))

from engine import Engine, FORMAT_GROUPS                                      # noqa: E402
from fresh import Fresh                                                       # noqa: E402
from library import (Library, Page, EVIDENCE, GENRE_ROWS, THEME_ROWS, FORMAT_ROWS, HIDDEN,  # noqa: E402
                     fans_of, slug)

engine = Engine(ROOT / 'model')
lib = Library(engine, ROOT / 'couchside' / 'art.bin.gz')
PERSONAS = {p['key']: p for name in ('personas.json', 'holdout.json')
            for p in json.loads((ROOT / 'scripts' / 'bench' / name).read_text())['personas']}
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def listed(*keys, most=60):
    """A list gathered from bench personas, loves, likes and dislikes as rated there."""
    found, seen = [], set()
    for key in keys:
        for role, weight in (('loves', 1), ('likes', .7), ('dislikes', -1)):
            for s in PERSONAS[key][role]:
                if s['id'] in engine.by_id and s['id'] not in seen and len(found) < most:
                    seen.add(s['id'])
                    found.append({'id': s['id'], 'weight': weight})
    return found


def seeded(day):
    return {'day': day, 'seed': hashlib.sha256(f'test|{day}'.encode()).hexdigest()[:16]}


def page_of(body):
    profile, settings, positives, negatives, rated, candidates, fresh = lib.prepare(body)
    return Page(lib, profile, settings, positives, negatives, rated, candidates, lib.read_list(body), fresh)


def built(page):
    """Each tier's rows as tier_rows() gives them."""
    return {tier: page.tier_rows(tier) for tier in (2, 3, 4)}


def described(tiers):
    return [(t, r.key, r.title, r.subtitle, r.kind_of, r.interest, r.personal, r.evidence, r.tier, list(r.items))
            for t, rows in tiers.items() for r in rows]


def first_page(page):
    """Every tier 0 row: the page's own candidates and My List, the first-visit rows and
    the genre, theme and format rows by their fixed names. Returns ({casefolded title:
    keys}, {key: casefolded titles})."""
    shelves, queues, different = page.shelves()
    named = [(s.key, s.title) for s in [*shelves, *(s for q in queues for s in q), different] if s]
    named += [('list', 'My List')]
    named += [(key, title) for key, title, _kind, _items in lib._cold_rows([], set(), Fresh(), 'Spanish', [])]
    named += [(key, title) for key, title, _items in lib.plain_rows()]
    named += [(f'genre-{g}'.lower(), title) for g, title in GENRE_ROWS.items()]
    named += [(f'theme-{slug(title)}', title) for title in THEME_ROWS.values()]
    named += [(f'format-{f}', title) for f, title in FORMAT_ROWS.items()]
    by_title, by_key = {}, {}
    for key, title in named:
        by_title.setdefault(title.casefold(), set()).add(key)
        by_key.setdefault(key, set()).add(title.casefold())
    return by_title, by_key


# The same evidence as the first page's rows of each sort, which rows past it stay below.
SORT = {'interest-gems': 'gems', 'interest-new': 'new', 'interest-popular': 'plain', 'interest-short': 'limited',
        'explore-language': 'place', 'explore-format': 'different', 'explore-genre': 'different',
        'browse-genre': 'genre', 'browse-theme': 'theme', 'browse-format': 'plain'}
PREFIXES = {'interest-gems': 'Hidden gem ', 'interest-popular': 'Popular ', 'interest-new': 'New ',
            'interest-short': 'Half-hour '}
LISTS = {
    'five shows': {'profile': [{'id': 169, 'weight': 1}, {'id': 82, 'weight': .7}, {'id': 44933, 'weight': 1},
                               {'id': 269, 'weight': .7}, {'id': 80, 'weight': -1}], 'list': [526, 431]},
    'one taste': {'profile': listed('prestige_crime')},
    'K-dramas': {'profile': listed('kdrama_romance')},
    'Japanese dramas': {'profile': listed('japanese_live_action')},
    'nature documentaries': {'profile': listed('nature_docs')},
    'twenty-five mixed': {'profile': listed('prestige_crime', 'british_panel', 'cozy_mystery', most=25), 'list': [2993]},
    'sixty mixed': {'profile': listed('prestige_crime', 'british_panel', 'cozy_mystery', 'shonen_anime',
                                      'adult_animation')},
    'a micro-genre named like a genre': {'profile': listed('psychological_anime', 'home_lifestyle', 'german_drama')},
    'with a day': {'profile': listed('prestige_crime', 'kdrama_romance', 'western'), **seeded('2026-10-05')},
}

counts = {tier: 0 for tier in (2, 3, 4)}
for shape, body in LISTS.items():
    body = {'settings': {}, 'list': [], **body}
    page = page_of(body)
    tiers = built(page)
    rows = [r for t in (2, 3, 4) for r in tiers[t]]
    for t in (2, 3, 4):
        counts[t] += len(tiers[t])

    # Built again, from scratch and on the same page, everything is the same.
    again = page_of(body)
    check(f'{shape}: two builds give the same rows, keys and cards', described(built(again)) == described(tiers))
    check(f'{shape}: asking a page again gives the same rows', described(built(page)) == described(tiers))
    raw = {2: page.interest_rows(), 3: page.explore_rows(), 4: page.browse_rows()}
    check(f'{shape}: every row is at least its shortest before tier_rows() looks',
          all(len(r.items) >= r.shortest for t in raw for r in raw[t]),
          [(r.key, len(r.items)) for t in raw for r in raw[t] if len(r.items) < r.shortest])
    check(f'{shape}: tier_rows() keeps them all and marks each with its tier',
          all([r.key for r in raw[t]] == [r.key for r in tiers[t]] and all(r.tier == t for r in tiers[t]) for t in raw))

    # Keys and titles.
    keys = [r.key for r in rows]
    check(f'{shape}: keys are unique', len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1])
    check(f'{shape}: keys are ones a browser may send back', all(re.fullmatch(r'[a-z0-9-]{1,60}', k) for k in keys))
    titles = [r.title.casefold() for r in rows]
    check(f'{shape}: titles are unique', len(titles) == len(set(titles)), [t for t in titles if titles.count(t) > 1])
    by_title, by_key = first_page(page)
    clashes = [(r.key, r.title, sorted(by_title[r.title.casefold()])) for r in rows
               if by_title.get(r.title.casefold(), {r.key}) != {r.key}]
    check(f'{shape}: no title is a first-page title, but a browse row\'s own', not clashes, clashes)
    reused = [r.key for r in rows if r.key in by_key and (r.tier != 4 or by_key[r.key] != {r.title.casefold()})]
    check(f'{shape}: only browse rows share a first-page key, and then its title too', not reused, reused)
    check(f'{shape}: titles are short', all(len(r.title.split()) <= 6 for r in rows), [r.title for r in rows])
    check(f'{shape}: no dash of any kind but a hyphen in a title or subtitle',
          not any(c in r.title + r.subtitle for r in rows for c in '\u2013\u2014'))

    # What every row holds, and what it weighs.
    rated = {engine.by_id[p['id']] for p in body['profile']}
    check(f'{shape}: no row holds a rated show', not any(rated & set(r.items) for r in rows))
    check(f'{shape}: no row holds a show kept off the page', not any(page.excluded & set(r.items) for r in rows))
    check(f'{shape}: no row holds a show twice', all(len(set(r.items)) == len(r.items) for r in rows))
    check(f'{shape}: every row weighs less than the first page\'s of its sort',
          all(r.evidence < EVIDENCE[SORT[r.kind_of]] for r in rows),
          [(r.key, r.evidence) for r in rows if r.evidence >= EVIDENCE[SORT.get(r.kind_of, 'top')]])
    check(f'{shape}: browse rows weigh less than the first page\'s genre rows',
          all(r.evidence < EVIDENCE['genre'] for r in tiers[4]))

    # Tier 2: each interest's own rows.
    shows = engine.shows
    for r in tiers[2]:
        check(f'{shape}: {r.title} serves an interest, for its fans', r.personal and r.interest is not None
              and r.subtitle == fans_of(page.interest_names(r.interest)) and r.title.startswith(PREFIXES[r.kind_of]))
        check(f'{shape}: {r.title} opens with shows that fit the interest', page.head_fits(r.items, r.interest))
        if r.kind_of == 'interest-new':
            check(f'{shape}: {r.title} is new', all(shows[i]['year'] >= lib.year - 1 for i in r.items))
        if r.kind_of == 'interest-short':
            check(f'{shape}: {r.title} runs half an hour or less',
                  all(0 < (shows[i]['runtime'] or 0) <= page.HALF_HOUR for i in r.items))
        if r.kind_of == 'interest-popular':
            pool = set(lib.popular_pool)
            check(f'{shape}: {r.title} is popular, most popular first', set(r.items) <= pool
                  and all(engine.popularity[a] >= engine.popularity[b] for a, b in zip(r.items, r.items[1:])))
        if r.kind_of == 'interest-gems':
            check(f'{shape}: {r.title} is little known and well rated', all(
                page.pop(i) <= HIDDEN[0] and (shows[i]['rating'] or 0) >= page.stats['rating_q75'] for i in r.items))
    interests = [r.interest for r in tiers[2]]
    check(f'{shape}: an interest has one row of a sort at most',
          len(set(zip(interests, (r.kind_of for r in tiers[2])))) == len(tiers[2]))

    # Tier 3: languages, formats and genres to explore.
    liked = [engine.by_id[p['id']] for p in body['profile'] if p['weight'] > 0]
    disliked = [engine.by_id[p['id']] for p in body['profile'] if p['weight'] < 0]
    languages = [r for r in tiers[3] if r.kind_of == 'explore-language']
    check(f'{shape}: a handful of languages at most', len(languages) <= page.EXPLORE_LANGUAGES)
    for r in tiers[3]:
        check(f'{shape}: {r.title} is not personal and opens with shows that fit',
              not r.personal and r.interest is None and page.head_fits(r.items))
        if r.kind_of == 'explore-language':
            language = r.title.removesuffix(' shows for you')
            check(f'{shape}: {r.title} is in a language nothing liked is in', r.key == f'lang-{slug(language)}'
                  and all(shows[i]['language'] == language for i in r.items)
                  and not any(shows[i]['language'] == language for i in liked))
        elif r.kind_of == 'explore-format':
            key = r.key.removeprefix('explore-')
            check(f'{shape}: {r.title} is a format the list has few of', key in FORMAT_ROWS
                  and all(shows[i]['type'] in FORMAT_GROUPS[key] for i in r.items)
                  and sum(lib._fits(key, i) for i in liked) <= page.EXPLORE_FEW * len(liked))
        else:
            genre = next((g for g in GENRE_ROWS if r.key == f'explore-{slug(g)}'), None)
            check(f'{shape}: {r.title} is a genre nothing rated has', genre not in (None, 'Drama', 'Comedy')
                  and all(genre in shows[i]['genres'] for i in r.items)
                  and not any(genre in shows[i]['genres'] for i in liked + disliked))
    different = page.different()
    if different:
        check(f'{shape}: no row to explore or browse repeats Something different', all(
            len(r.top12 & different.top12) < 0.5 * min(12, len(r.top12)) for r in tiers[3] + tiers[4]))
    repeats = [(a.key, b.key) for n, a in enumerate(tiers[3]) for b in tiers[3][:n]
               if len(a.top12 & b.top12) >= 0.5 * min(12, len(a.top12))]
    check(f'{shape}: no row to explore repeats another', not repeats, repeats)
    repeats = [(b.key, a.key) for a in tiers[3] for b in tiers[4] if len(a.top12 & b.top12) >= 0.5 * min(12, len(b.top12))]
    check(f'{shape}: no browse row repeats a row to explore', not repeats, repeats)
    tried = {r.key.removeprefix('explore-') for r in tiers[3] if r.key.startswith('explore-')}
    twice = [r.key for r in tiers[4] if r.key.split('-', 1)[1] in tried]
    check(f'{shape}: a genre or format with a row to try is not browsed again under its plain name', not twice, twice)

    # Tier 4: every genre, theme and format, as the first page cuts them.
    for r in tiers[4]:
        check(f'{shape}: {r.title} is not personal', not r.personal and r.interest is None)
        if r.kind_of == 'browse-genre':
            genre = next((g for g, title in GENRE_ROWS.items() if title == r.title), '')
            test = lambda i, g=genre: g in shows[i]['genres']
            check(f'{shape}: {r.title} keeps the first page\'s key and is cut as its genre rows are',
                  genre and r.key == f'genre-{genre}'.lower() and r.items == page.default(page.take(test))[0])
        elif r.kind_of == 'browse-theme':
            theme = next((t for t, title in THEME_ROWS.items() if title == r.title), None)
            bit = 1 << engine.themes.index(theme) if theme else 0
            test = lambda i, bit=bit: shows[i]['theme_bits'] & bit
            check(f'{shape}: {r.title} keeps the first page\'s key and is cut as its theme rows are',
                  theme and r.key == f'theme-{slug(r.title)}' and r.items == page.default(page.take(test))[0])
        else:
            key = r.key.removeprefix('browse-')
            check(f'{shape}: {r.title} has a key and name of its own, apart from the first-visit row\'s',
                  key in FORMAT_ROWS and r.title == f'{page.FORMAT_NAMES[key]} for you' and r.title != FORMAT_ROWS[key]
                  and r.items == page.default(page.take(lambda i, key=key: lib._fits(key, i)))[0])
    mine = {r.key: r.title for r in tiers[4]}
    own = [(s.key, s.title) for s in page.shelves()[0] if s.kind_of == 'genre']
    check(f'{shape}: the list\'s own genre and theme rows and their browse rows share keys and titles',
          all(mine.get(key, title) == title for key, title in own), own)

# Shapes the lists above must reach.
k_page = page_of({'settings': {}, 'list': [], 'profile': listed('kdrama_romance')})
k_rows = k_page.tier_rows(2)
check('an interest mostly in Korean keeps to it and says so', k_rows and all(
    'Korean' in r.title and all(engine.shows[i]['language'] == 'Korean' for i in r.items) for r in k_rows),
    [r.title for r in k_rows])
j_page = page_of({'settings': {}, 'list': [], 'profile': listed('japanese_live_action')})
check('an interest of live-action dramas keeps to live action', all(
    engine.shows[i]['type'] == 'Scripted' for r in j_page.tier_rows(2)
    if all(engine.shows[engine.by_id[p['id']]]['type'] == 'Scripted' for p in j_page.interests[r.interest])
    for i in r.items))
one = page_of({'settings': {}, 'list': [], 'profile': listed('prestige_crime')})
check('a list with one taste gets languages it has nothing in', any(r.kind_of == 'explore-language' for r in one.tier_rows(3)))
check('and genres it has not touched', any(r.kind_of == 'explore-genre' for r in one.tier_rows(3)))
check('an interest that is the whole list does not repeat Hidden gems for you',
      not any(r.kind_of == 'interest-gems' and len(r.top12 & one.gems().top12) >= 6 for r in one.tier_rows(2)))
check('every tier has rows across these lists', all(counts.values()), counts)
first = page_of({'profile': [{'id': 169, 'weight': 1}], 'settings': {}, 'list': []})
check('a list of one show still gets rows past the first page, and all of them fit',
      all(len(r.items) >= r.shortest for t in (2, 3, 4) for r in first.tier_rows(t)))

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures[:20])}')
print('all checks passed')
