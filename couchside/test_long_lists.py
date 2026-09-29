"""Check Couchside's pages for long lists, of hundreds and thousands of ratings.

Run from the repository root:  .venv/bin/python couchside/test_long_lists.py
It reads the repository's model, neighbour index and all, and builds pages for lists
made from the bench personas by scripts/bench/large_lists.py. A list longer than the
engine's DENSE_MAX is ranked from each show's closest shows (engine.Wide); these check
that every page a long list asks for holds together: nothing rated on it, rows of the
list's own, interests named but not listed whole, title pages and genres, the same page
for the same request, and each in reasonable time.
"""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'couchside'))
sys.path.insert(0, str(ROOT / 'scripts' / 'bench'))

import library                                                   # noqa: E402
from engine import DEFAULT_SETTINGS, DENSE_MAX, WIDE_NAMED, Engine   # noqa: E402
from large_lists import Relations, viewers                       # noqa: E402
from library import FIRST_PAGE, GLANCE, MORE, NOT_FOR_ME, Page   # noqa: E402

engine = Engine(ROOT / 'model')
lib = library.Library(engine, ROOT / 'couchside' / 'art.bin.gz')
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


if not engine.neighbours:
    sys.exit('The model has no neighbour index: build it with scripts/build_neighbours.py.')


def shown(rows):
    return [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:GLANCE]], **({'tier': r['tier']} if 'tier' in r else {})}
            for r in rows]


def cards(rows):
    return {c['id'] for r in rows if r['kind'] == 'row' for c in r['items']}


def holds_together(title, rated):
    """A title page's More like this: some shows and at most MORE, each some percent similar,
    most similar first; Fans also like apart from them; nothing on the list in either."""
    more, fans = [c['id'] for c in title['more']], [c['id'] for c in title['fans']]
    similar = [c['similar'] for c in title['more']]
    return (0 < len(more) <= MORE and all(60 <= s <= 99 for s in similar) and similar == sorted(similar, reverse=True)
            and len(fans) <= MORE and not set(more) & set(fans) and not rated & (set(more) | set(fans)))


relations = Relations(engine)
for size in (300, 1000, 3000):
    v = viewers(engine, 'personas.json', size=size, count=1, relations=relations)[0]
    rated = {p['id'] for p in v.profile}
    liked = [p for p in v.profile if p['weight'] > 0]
    saved = [s['id'] for s in engine.cards(v.held)][:2]
    body = {'profile': v.profile, 'settings': dict(DEFAULT_SETTINGS), 'list': saved, 'lang': ['en-GB'],
            'day': '2026-10-05', 'seed': '0123456789abcdef'}
    started = time.perf_counter()
    first = lib.home(body)
    spent = time.perf_counter() - started
    check(f'{size}: the first page comes in {spent:.2f}s', spent < 2.0)
    check(f'{size}: it has a hero and {FIRST_PAGE} rows, and none of the list on them',
          first['personal'] and first['hero'] and len(first['rows']) == FIRST_PAGE
          and not rated & cards(first['rows']) and first['hero']['id'] not in rated)
    check(f'{size}: the hero says which liked show it is for', first['hero']['because']
          and first['hero']['because']['id'] in {p['id'] for p in liked})
    check(f'{size}: rows of its own lead the page', first['rows'][0]['key'] == 'top'
          and any(r['key'].startswith('seed-') for r in first['rows']), [r['key'] for r in first['rows']])
    interests = first['interests']
    check(f'{size}: each interest is named for a few of its shows and says how many it holds',
          interests and all(0 < len(it['shows']) <= WIDE_NAMED and it['size'] >= len(it['shows'])
                            and len(it['names']) == len(it['shows']) for it in interests)
          and sum(it['size'] for it in interests) == len(liked))
    check(f'{size}: the same request makes the same page', lib.home(body)['rows'] == first['rows'])
    rows = list(first['rows'])
    started = time.perf_counter()
    more = lib.home({**body, 'shown': shown(rows), 'count': 6})
    spent = time.perf_counter() - started
    rows += more['rows']
    check(f'{size}: asking for more brings more rows in {spent:.2f}s', more['rows'] and spent < 2.0)
    for _ in range(6):
        if not more['more']:
            break
        more = lib.home({**body, 'shown': shown(rows), 'count': 6})
        rows += more['rows']
    check(f'{size}: {len(rows)} rows on, still nothing rated and no row twice',
          not rated & cards(rows) and len({r['key'] for r in rows}) == len(rows))
    started = time.perf_counter()
    title = lib.title({**body, 'id': v.held[0]})
    spent = time.perf_counter() - started
    check(f'{size}: a title page comes in {spent:.2f}s', spent < 1.0)
    check(f'{size}: it has more like this and fans also like, none of it rated',
          holds_together(title, rated) and title['show']['because'] and title['show']['match'])
    own = next(p['id'] for p in reversed(liked) if p['weight'] == 1)
    title = lib.title({**body, 'id': own})
    check(f'{size}: so does the page of a show it loves', holds_together(title, rated)
          and title['show']['because'] is None)
    browse = lib.browse({**body, 'genre': 'Drama'})
    check(f'{size}: a genre ranks for it', browse['personal'] and browse['rows']
          and not rated & {c['id'] for r in browse['rows'] for c in r['items']})

# A long list of nothing but dislikes: the home page is a first visit's, and a title page
# still has more like this of the title's own kind (for an English title, mostly English,
# as a first visit's is), none of it disliked.
known = sorted((i for i, s in enumerate(engine.shows) if s['recommendable']), key=lambda i: -engine.popularity[i])
dislikes = [{'id': engine.shows[i]['id'], 'weight': -1} for i in known[:200]]
home = lib.home({'profile': dislikes, 'settings': dict(DEFAULT_SETTINGS)})
check('a long list of dislikes alone gets a first visit\'s page', home['personal'] is False and home['rows'])
english = [i for i in known[300:] if engine.shows[i]['language'] == 'English']
language = {s['id']: s['language'] for s in engine.shows}
for i in (english[0], english[200], english[800]):
    started = time.perf_counter()
    title = lib.title({'profile': dislikes, 'settings': dict(DEFAULT_SETTINGS), 'id': engine.shows[i]['id']})
    spent = time.perf_counter() - started
    kin = sum(language[c['id']] == 'English' for c in title['more'])
    check(f'and its title page for {engine.shows[i]["name"]} has more like this of its kind in {spent:.2f}s',
          holds_together(title, {p['id'] for p in dislikes}) and kin >= len(title['more']) * 2 / 3 and spent < 1.0,
          f'{kin} of {len(title["more"])} in English')

# A long list's dislikes are weighed from the neighbour index: a show at least as like a
# disliked show as like the title, and very like it, stays off the title's More like this.
settings = dict(DEFAULT_SETTINGS)
title_show = english[0]
disliked_ids = {p['id'] for p in dislikes}
body = {'profile': dislikes, 'settings': settings, 'id': engine.shows[title_show]['id']}
before = [engine.by_id[c['id']] for c in lib.title(body)['more']]
likeness = lib.likeness(title_show, settings)
world, _fans = lib.kin(title_show)      # the title's own world counts as close as can be
# A twin among a shown show's closest, more like it than the title is, by likeness (what
# readers of both look up counting little), worked out exactly for the twin.
pair = next(((a, k) for a in before if a not in world for k, value in zip(*engine.row(a, settings)[:2])
             if k != title_show and k not in before and engine.shows[k]['id'] not in disliked_ids
             and value >= max(NOT_FOR_ME, likeness[a] + 0.05)
             and lib.likeness(k, settings)[a] >= max(NOT_FOR_ME, likeness[a] + 0.05)), None)
if pair:
    shown_before, twin = pair
    body = {**body, 'profile': dislikes + [{'id': engine.shows[twin]['id'], 'weight': -1}]}
    after = [engine.by_id[c['id']] for c in lib.title(body)['more']]
    check(f'a show very like a disliked one ({engine.shows[shown_before]["name"]}, like '
          f'{engine.shows[twin]["name"]}) leaves More like this', shown_before not in after and after)
else:
    check('a More like this show has a close twin to dislike', False)

# The old limit and one past it: a list of DENSE_MAX ratings is ranked as it always was.
v = viewers(engine, 'personas.json', size=300, count=1, relations=relations)[0]
for count, wide in ((DENSE_MAX, False), (DENSE_MAX + 1, True)):
    profile = [p for p in v.profile if p['weight'] != 0][-count:]
    body = {'profile': profile, 'settings': dict(DEFAULT_SETTINGS), 'list': []}
    parts = lib.prepare(body)
    page = Page(lib, *parts[:6], lib.read_list(body), parts[6])
    check(f'a list of {count} ratings is ranked {"from the index" if wide else "as before"}', page.taste.wide == wide)
    check(f'and its page holds together', len(lib.home(body)['rows']) == FIRST_PAGE)

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
