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
from library import FIRST_PAGE, GLANCE, MORE, Page               # noqa: E402

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
    title = lib.title({**body, 'id': v.held[0]})
    check(f'{size}: a title page has more like this, none of it rated',
          len(title['more']) == MORE and not rated & {c['id'] for c in title['more']}
          and title['show']['because'] and title['show']['match'])
    own = next(p['id'] for p in reversed(liked) if p['weight'] == 1)
    title = lib.title({**body, 'id': own})
    check(f'{size}: so does the page of a show it loves', len(title['more']) == MORE
          and not rated & {c['id'] for c in title['more']} and title['show']['because'] is None)
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
    more = lib.title({'profile': dislikes, 'settings': dict(DEFAULT_SETTINGS), 'id': engine.shows[i]['id']})['more']
    kin = sum(language[c['id']] == 'English' for c in more)
    check(f'and its title page for {engine.shows[i]["name"]} has more like this of its kind', len(more) == MORE
          and kin >= MORE * 2 // 3 and not {p['id'] for p in dislikes} & {c['id'] for c in more},
          f'{kin} of {len(more)} in English')

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
