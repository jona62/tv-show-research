"""Check the home page's tier 1 rows: more rows from a viewer's own list (Page.personal_rows).

Run from the repository root:  .venv/bin/python couchside/test_personal_rows.py
It reads the repository's model and nothing else, and builds pages for lists drawn from the
bench personas, each twice, to see that the same list gives the same rows.
"""
from collections import Counter
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'couchside'))

import library                                                   # noqa: E402
from engine import Engine                                        # noqa: E402
from fresh import ROW_KEY                                        # noqa: E402
from library import GLANCE, Page, slug                           # noqa: E402

engine = Engine(ROOT / 'model')
lib = library.Library(engine, ROOT / 'couchside' / 'art.bin.gz')
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


PERSONAS = {p['key']: p for name in ('personas.json', 'holdout.json')
            for p in json.loads((ROOT / 'scripts' / 'bench' / name).read_text())['personas']}


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


def page_of(profile):
    body = {'profile': profile, 'settings': {}, 'list': []}
    profile, settings, positives, negatives, rated, candidates, fresh = lib.prepare(body)
    return Page(lib, profile, settings, positives, negatives, rated, candidates, lib.read_list(body), fresh)


def wording(row):
    """A row's title less the name of the show it is about, which can be long by itself."""
    return row.title.replace(engine.shows[row.seed]['name'], '', 1) if row.seed is not None else row.title


def shape(rows):
    """Everything about a list of rows that should not change between two builds."""
    return [(r.key, r.title, r.subtitle, r.kind_of, r.interest, r.evidence, r.tier, r.seed, list(r.items))
            for r in rows]


# Each Starring row's key back to its actor's facet column.
_start, _end = engine.facets.family_ranges[engine.facets.families.index('cast')]
ACTORS = {f'cast-{slug(engine.facets.keys[c])}': c for c in range(_start, _end)}

LISTS = {
    'prestige crime': listed('prestige_crime'),
    'police procedurals': listed('police_procedural'),
    'Star Trek': listed('star_trek'),
    'K-drama romance': listed('kdrama_romance'),
    'nineties nostalgia': listed('nineties_nostalgia'),
    'sixty mixed': listed('prestige_crime', 'british_panel', 'cozy_mystery', 'shonen_anime', 'adult_animation'),
    'one show': [{'id': 169, 'weight': 1}],
}
kinds = set()
for name, profile in LISTS.items():
    page = page_of(profile)
    rows = page.tier_rows(1)
    kinds.update(r.kind_of for r in rows)
    keys = [r.key for r in rows]
    rated = {p['id'] for p in profile}
    liked = {p['id']: p['weight'] for p in profile if p['weight'] >= .7}
    check(f'{name}: tier 1 has rows', bool(rows) or name == 'one show', keys)
    check(f'{name}: no key twice', len(keys) == len(set(keys)), keys)
    check(f'{name}: no title twice', len({r.title.casefold() for r in rows}) == len(rows), [r.title for r in rows])
    check(f'{name}: keys are keys the browser can send back', all(ROW_KEY.match(k) for k in keys), keys)
    check(f'{name}: titles are short and without dashes', all(r.title and len(wording(r).split()) <= 7
                                                              and '—' not in r.title + r.subtitle for r in rows),
          [r.title for r in rows if len(wording(r).split()) > 7])
    check(f'{name}: every row holds at least its shortest, each show once',
          all(len(r.items) >= r.shortest and len(set(r.items)) == len(r.items) for r in rows),
          [(r.key, len(r.items)) for r in rows if len(r.items) < r.shortest])
    check(f'{name}: every row is tier 1 and personal', all(r.tier == 1 and r.personal for r in rows))
    check(f'{name}: every row serves one of the list\'s interests', all(
        r.interest is not None and 0 <= r.interest < len(page.interests) for r in rows))
    check(f'{name}: evidence sits between 0 and 1', all(0 < r.evidence <= 1 for r in rows))
    shown = {engine.shows[i]['id'] for r in rows for i in r.items}
    check(f'{name}: no rated show in any row', not shown & rated, shown & rated)
    check(f'{name}: nothing kept off the page for a Not for me', not {i for r in rows for i in r.items} & page.excluded)
    # Seed rows: tier 0's key and title, one for each liked show at most, none tier 0 queues.
    shelves, queues, different = page.shelves()
    first_page = [s for s in shelves + [s for q in queues for s in q]]
    seeds = [r for r in rows if r.kind_of == 'seed']
    check(f'{name}: seed rows keep tier 0\'s key and title', all(
        r.key == f'seed-{engine.shows[r.seed]["id"]}' and engine.shows[r.seed]['id'] in liked
        and r.title == f'Because you {"loved" if liked[engine.shows[r.seed]["id"]] == 1 else "liked"} '
                       f'{engine.shows[r.seed]["name"]}' for r in seeds), [r.key for r in seeds])
    check(f'{name}: no seed or cast row the first page already queues',
          not {r.key for r in rows} & {s.key for s in first_page if s.key.startswith(('seed-', 'cast-'))})
    before = [s.items for s in first_page if s.kind_of == 'seed']
    fine = True
    for r in seeds:
        fine &= all(page.repeats(r.items, other) < .5 for other in before)
        before.append(r.items)
    check(f'{name}: no seed row repeats half of a seed row before it', fine)
    # Fans rows: what readers of the liked show also look up, never its own franchise.
    for r in rows:
        if r.kind_of != 'fans':
            continue
        links = {i for i, _s in engine.cointerest(r.seed)}
        check(f'{name}: {r.title} holds only what its readers also look up', set(r.items) <= links)
        check(f'{name}: {r.title} pairs no show with its own franchise',
              not any(engine.franchises(i) & engine.franchises(r.seed) for i in r.items))
        seed = next((s for s in first_page + seeds if s.key == f'seed-{engine.shows[r.seed]["id"]}'), None)
        check(f'{name}: {r.title} repeats neither its seed row nor Top picks',
              page.repeats(r.items, page.calibrated()) < .5 and (not seed or page.repeats(r.items, seed.items) < .5))
    top = page.calibrated()
    check(f'{name}: no channel, decade or subject row repeats half of Top picks', all(
        page.repeats(r.items, top) < .5 for r in rows if r.kind_of in ('channel', 'decade', 'subject')))
    given = Counter()
    for r in rows:
        if r.kind_of == 'cast':
            c = ACTORS[r.key]
            given.update(p['id'] for p in page.positives if c in lib.facet_sets(engine.by_id[p['id']])[3])
    check(f'{name}: a liked show gives at most {page.CAST_PER_SHOW} Starring rows',
          max(given.values(), default=0) <= page.CAST_PER_SHOW, given)
    # The same list gives the same rows, built again or asked again.
    again = page_of(profile)
    check(f'{name}: a second build gives the same rows', shape(again.tier_rows(1)) == shape(rows))
    check(f'{name}: asking the same page twice gives the same rows',
          shape(page.personal_rows()) == shape(page.personal_rows()))

check('the lists reach every kind of tier 1 row', kinds == {'seed', 'fans', 'cast', 'channel', 'decade', 'subject'},
      kinds)

# Titles for subjects, as Wikidata labels them.
page = page_of([{'id': 169, 'weight': 1}])
for label, title in [('organized crime', 'Shows about organized crime'), ('serial killer', 'Shows about serial killers'),
                     ('dysfunctional family', 'Shows about dysfunctional families'), ('politics', 'Shows about politics'),
                     ('time travel', 'Time-travel stories'), ('1980s', 'Shows set in the 1980s'),
                     ('22nd century', 'Shows set in the 22nd century'), ('future', 'Shows set in the future'),
                     ('World War II', 'Shows about World War II'), ('The Holocaust', 'Shows about the Holocaust'),
                     ('Vietnam War', 'Shows about the Vietnam War'),
                     ('New York City Police Department', 'Shows about the NYPD'),
                     ('New York City', 'Shows set in New York City'), ('United Kingdom', 'Shows set in the United Kingdom'),
                     ('Russian Empire', 'Shows set in the Russian Empire')]:
    check(f'the subject {label} reads "{title}"', page.subject_title(label)[0] == title, page.subject_title(label))
check('a subject with no letters to name it has no title', page.subject_title('2 + 2')[0] is None)
check('a channel named in another script keys by its facet key',
      Page.key_slug('Россия 1', 'tvmaze-network-239') == 'tvmaze-network-239' and Page.key_slug('HBO', 'x') == 'hbo')

# Keeping a row apart from the rows above it.
other = list(range(100, 130))
items = list(range(100, 112)) + list(range(200, 220))
kept = Page.apart(items, [other])
check('apart() leaves out what the other row opens with', not set(kept) & set(other[:GLANCE]))
check('apart() keeps under half of the other row\'s first twelve', Page.repeats(kept, other) < .5, kept[:12])
check('apart() keeps the rest in order', [i for i in kept if i >= 200] == list(range(200, 220)))
short = Page.apart(list(range(100, 112)) + [300, 301, 302], [other])
check('a row too short to reach twelve keeps under half by its own length', Page.repeats(short, other) < .5, short)

# Without co-interest or facets there are fewer kinds, and nothing breaks.
co, facets = engine.co, engine.facets
try:
    engine.co = None
    kinds_without = {r.kind_of for r in page_of(LISTS['prestige crime']).tier_rows(1)}
    check('without co-interest there are no fans rows', 'fans' not in kinds_without and 'seed' in kinds_without,
          kinds_without)
    engine.facets = None
    kinds_without = {r.kind_of for r in page_of(LISTS['prestige crime']).tier_rows(1)}
    check('without facets there are no cast, channel or subject rows',
          kinds_without <= {'seed', 'decade'} and 'seed' in kinds_without, kinds_without)
finally:
    engine.co, engine.facets = co, facets

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
