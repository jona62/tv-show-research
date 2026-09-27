"""Check the app engine against the research recommender and its own contracts.

Run from the repository root:  .venv/bin/python app/test_engine.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'site'))

from engine import Engine, DEFAULT_SETTINGS                      # noqa: E402
import engine as engine_module                                   # noqa: E402
import recommender                                               # noqa: E402
import taste as taste_module                                     # noqa: E402

PROFILE = [{'id': 13417, 'weight': 1}, {'id': 169, 'weight': 1}, {'id': 618, 'weight': 1},
           {'id': 42062, 'weight': .7}, {'id': 182, 'weight': 1}, {'id': 82, 'weight': .35},
           {'id': 80, 'weight': -1}]
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + detail if detail and not ok else ""}')
    if not ok:
        failures.append(name)


app = Engine(ROOT / 'app' / 'model')
reference = recommender.Engine()


def closeness_only(body):
    """The ranking with taste switched off and every liked show one interest, which
    leaves closeness alone: what the research engine ranks by."""
    saved = taste_module.STRENGTH, engine_module.INTEREST_JOIN
    taste_module.STRENGTH, engine_module.INTEREST_JOIN = 0.0, 0.0
    try:
        return app.calculate(body)
    finally:
        taste_module.STRENGTH, engine_module.INTEREST_JOIN = saved


# 1. Closeness alone ranks as the research engine does once the settings line up;
# scores are measured against the best pick, so they agree in proportion.
settings = {**DEFAULT_SETTINGS, 'rating_min': 0, 'known_min': 0}
mine = closeness_only({'profile': PROFILE, 'settings': settings})
theirs = reference.calculate({'profile': PROFILE, 'settings': {**settings, 'axis_x': 'all', 'axis_y': 'all'}})
overlap = min(len(mine['picks']), len(theirs['recommendations']))
check('closeness alone ranks as the research engine does',
      [p['id'] for p in mine['picks'][:overlap]] == [p['id'] for p in theirs['recommendations'][:overlap]],
      f"{[p['name'] for p in mine['picks'][:3]]} vs {[p['name'] for p in theirs['recommendations'][:3]]}")
top_mine, top_theirs = mine['picks'][0]['score'], theirs['recommendations'][0]['score']
check('and scores in the same proportions',
      all(abs(a['score'] / top_mine - b['score'] / top_theirs) < .003
          for a, b in zip(mine['picks'], theirs['recommendations'])))
check('candidate pool matches', mine['candidate_count'] == theirs['candidate_count'])
tasted = app.calculate({'profile': PROFILE, 'settings': settings})
median = lambda values: sorted(values)[len(values) // 2]
check('taste lifts the shows a list like this one watches over obscure ones',
      median([p['known'] for p in tasted['picks']]) > median([p['known'] for p in mine['picks']]),
      f"{median([p['known'] for p in tasted['picks']])} vs {median([p['known'] for p in mine['picks']])}")

# 2. Nothing you have rated is ever recommended back.
rated = {p['id'] for p in PROFILE}
check('rated shows are excluded', not rated & {p['id'] for p in mine['picks']})

# 3. The popularity default keeps obscure titles out without demanding a rating.
strict = app.calculate({'profile': PROFILE, 'settings': {}})
check('default settings return picks', len(strict['picks']) > 0)
check('default excludes obscure titles', all(p['known'] >= 85 for p in strict['picks']))
check('default is narrower than no floor', strict['candidate_count'] < mine['candidate_count'])
loose = app.calculate({'profile': PROFILE, 'settings': {'known_min': 0}})
check('popularity floor narrows the pool', strict['candidate_count'] < loose['candidate_count'])
check('a popularity floor does not demand a rating',
      any(app.shows[i]['rating'] is None for i in range(app.n) if app.eligible(i, {**DEFAULT_SETTINGS, 'known_min': 60})))
check('popularity covers the whole catalog', len(app.popularity) == app.n and max(app.popularity) == 100)

# 4. Every pick can explain itself.
check('every pick names a closest liked show', all(p['because'] for p in strict['picks']))
check('every pick carries its own signals', all('themes' in p and 'genres' in p for p in strict['picks']))
check('shared signals really are shared', all(
    set(p['shared_themes']) <= set(p['themes']) and set(p['shared_genres']) <= set(p['genres'])
    for p in strict['picks']))

# 5. Liked shows come back with what the taste chart needs.
liked = {s['id'] for s in strict['liked']}
check('liked payload covers every positive rating', liked == {p['id'] for p in PROFILE if p['weight'] > 0})
check('liked payload carries weights and signals',
      all(s['weight'] > 0 and isinstance(s['themes'], list) and isinstance(s['genres'], list) for s in strict['liked']))

# 6. Dislikes push matches down.
without = app.calculate({'profile': [p for p in PROFILE if p['weight'] > 0], 'settings': {}})
check('a dislike changes the ranking',
      [p['id'] for p in without['picks']] != [p['id'] for p in strict['picks']]
      or any(p['penalised'] for p in strict['picks']))

# 7. An empty or rating-free list asks for input instead of failing.
empty = app.calculate({'profile': [], 'settings': {}})
check('empty list returns guidance', empty['picks'] == [] and 'liked' in empty['message'])
neutral = app.calculate({'profile': [{'id': 169, 'weight': 0}], 'settings': {}})
check('neutral-only list returns guidance', neutral['picks'] == [] and neutral['positive_count'] == 0)

# 8. Bad input is rejected, not absorbed.
for label, body in [
    ('unknown show id', {'profile': [{'id': -5, 'weight': 1}], 'settings': {}}),
    ('duplicate show', {'profile': [{'id': 169, 'weight': 1}, {'id': 169, 'weight': .7}], 'settings': {}}),
    ('invalid rating', {'profile': [{'id': 169, 'weight': .5}], 'settings': {}}),
    ('out-of-range setting', {'profile': [{'id': 169, 'weight': 1}], 'settings': {'closest': 4}}),
    ('out-of-range popularity', {'profile': [{'id': 169, 'weight': 1}], 'settings': {'known_min': 140}}),
    ('zero feature weights', {'profile': [{'id': 169, 'weight': 1}], 'settings': {'text': 0, 'themes': 0, 'genres': 0}}),
    ('unknown language', {'profile': [{'id': 169, 'weight': 1}], 'settings': {'language': 'Klingon'}}),
    ('oversized list', {'profile': [{'id': i, 'weight': 1} for i in range(1, 80)], 'settings': {}}),
]:
    try:
        app.calculate(body)
        check(f'rejects {label}', False)
    except ValueError:
        check(f'rejects {label}', True)

# 8b. Id resolution, which an imported transfer code relies on.
cards = app.cards([13417, 169, 999_999_999, 527])
check('cards resolve ids in order', [c['id'] for c in cards] == [13417, 169, 527])
check('cards drop ids the catalog no longer has', len(cards) == 3)
check('cards carry what a list row shows',
      all({'name', 'year', 'channel', 'known'} <= set(c) for c in cards))
check('cards of nothing is nothing', app.cards([]) == [])

# 9a. Format groups are television formats, and each one narrows the pool.
for group, expect in [('scripted', 'Scripted'), ('animation', 'Animation'), ('documentary', 'Documentary')]:
    picks = app.calculate({'profile': PROFILE, 'settings': {'type': group}})['picks']
    check(f'format group {group} only returns {expect}', picks and all(p['type'] == expect for p in picks))
unscripted = app.calculate({'profile': PROFILE, 'settings': {'type': 'unscripted'}})['picks']
check('format group unscripted excludes scripted drama',
      unscripted and all(p['type'] not in ('Scripted', 'Animation', 'Documentary') for p in unscripted))

# 9. Search puts the best-known title first and stays inside its bounds.
check('search prefers the best-known match', app.search('the office')[0]['id'] == 526)
check('search finds the original Friends', app.search('friends')[0]['id'] == 431)
check('search needs two characters', app.search('a') == [])
check('search caps its results', len(app.search('the')) <= 12)

# 10. Character names stay out of the plot terms.
gangs = app.shows[app.by_id[next(h['id'] for h in app.search('Gangs of London') if h['name'] == 'Gangs of London')]]
check('plot terms drop character names', 'sean' not in app.plot_words(gangs) and 'wallace' not in app.plot_words(gangs))

# 11. Picks can be matched to chosen shows alone. The pool, the dislikes and the
# taste payload stay exactly as they are; only the scoring set shrinks.
narrow = app.calculate({'profile': PROFILE, 'settings': {}, 'similar_to': [618, 13417]})
plain = app.calculate({'profile': PROFILE, 'settings': {}, 'similar_to': []})
ids = lambda r: [p['id'] for p in r['picks']]
same_scores = lambda a, b: all(x['score'] == y['score'] for x, y in zip(a['picks'], b['picks']))
check('an empty selection is the plain ranking', ids(plain) == ids(strict) and same_scores(plain, strict))
check('the selection is echoed in list order',
      narrow['similar_to'] == [13417, 618] and strict['similar_to'] == [] and empty['similar_to'] == [])
check('every pick is closest to a chosen show',
      narrow['picks'] and all(p['because_id'] in (13417, 618) for p in narrow['picks']))
one = app.calculate({'profile': PROFILE, 'settings': {}, 'similar_to': [618]})
check('one chosen show sources every pick', one['picks'] and all(p['because_id'] == 618 for p in one['picks']))
check('narrowing changes the ranking', ids(one) != ids(strict))
check('narrowing keeps the pool', narrow['candidate_count'] == strict['candidate_count'])
check('narrowing keeps rated shows out', not rated & set(ids(narrow)))
check('taste stays the whole list',
      {s['id'] for s in narrow['liked']} == liked and narrow['features'] == strict['features']
      and narrow['breadth'] == strict['breadth'] and narrow['context'] == strict['context']
      and narrow['positive_count'] == strict['positive_count'])
check('links cover every liked show', all(len(p['links']) == len(narrow['liked']) for p in narrow['picks']))
check('narrowing keeps the whole list\'s taste and interests',
      narrow['taste'] == strict['taste'] and narrow['interests'] == strict['interests'])
rerated = [p if p['id'] in (13417, 618) or p['weight'] < 0 else {**p, 'weight': 0} for p in PROFILE]
body = {'profile': PROFILE, 'settings': {}, 'similar_to': [618, 13417]}
same = closeness_only({'profile': rerated, 'settings': {}})
check('by closeness alone, narrowing matches re-rating the other shows as neutral',
      ids(closeness_only(body)) == ids(same) and all(abs(a['score'] - b['score']) < .01 for a, b in zip(closeness_only(body)['picks'], same['picks'])))
only_liked = [p for p in PROFILE if p['weight'] > 0]
solo = closeness_only({'profile': only_liked, 'settings': {}, 'similar_to': [618]})
at = [s['id'] for s in solo['liked']].index(618)
top = solo['picks'][0]['links'][at]
check('by closeness alone, one chosen show scores in proportion to its own similarity',
      solo['picks'] and all(abs(p['score'] - p['links'][at] / top * 100) < .3 for p in solo['picks']))
check('dislikes still count when narrowed', any(p['penalised'] for p in one['picks']))
every = app.calculate({'profile': PROFILE, 'settings': {}, 'similar_to': [p['id'] for p in only_liked]})
check('choosing every liked show is the plain ranking',
      ids(every) == ids(strict) and same_scores(every, strict) and every['similar_to'] == [p['id'] for p in only_liked])
okay = app.calculate({'profile': PROFILE, 'settings': {}, 'similar_to': [82]})
check('a show rated OK can be chosen', okay['picks'] and all(p['because_id'] == 82 for p in okay['picks']))
# Peaky Blinders has a 12-word summary; 1699 has no summary, themes or genres at all.
thin = [{'id': 269, 'weight': 1}, {'id': 1699, 'weight': 1}, {'id': 169, 'weight': 1}]
warn = lambda chosen: app.calculate({'profile': thin, 'settings': {}, 'similar_to': chosen})['warning']
check('the plot warning follows the chosen shows', warn([169]) == '' and 'your shows' in warn([]))
check('one thin chosen show is named', warn([269, 169]).startswith('Peaky Blinders has'))
check('several thin chosen shows are counted together', warn([269, 1699]).startswith('Some of the shows you chose'))
far = app.calculate({'profile': PROFILE, 'settings': {'year_min': 2100}, 'similar_to': [13417]})
check('an empty pool keeps its message when narrowed', far['picks'] == [] and 'Widen' in far['message'])
blank = app.calculate({'profile': thin, 'settings': {}, 'similar_to': [1699]})
check('a chosen show with no signals says so',
      blank['picks'] == [] and blank['candidate_count'] > 0 and 'shows you chose' in blank['message'])
for label, body, said in [
    ('a selection that is not a list', {'profile': PROFILE, 'settings': {}, 'similar_to': 169}, 'as a list'),
    ('a null selection', {'profile': PROFILE, 'settings': {}, 'similar_to': None}, 'as a list'),
    ('a selection of strings', {'profile': PROFILE, 'settings': {}, 'similar_to': ['169']}, 'whole numbers'),
    ('a boolean chosen id', {'profile': PROFILE, 'settings': {}, 'similar_to': [True]}, 'whole numbers'),
    ('a fractional chosen id', {'profile': PROFILE, 'settings': {}, 'similar_to': [169.0]}, 'whole numbers'),
    ('a repeated chosen show', {'profile': PROFILE, 'settings': {}, 'similar_to': [169, 169]}, 'only once'),
    ('choosing a disliked show', {'profile': PROFILE, 'settings': {}, 'similar_to': [80]}, 'counted as liked'),
    ('choosing a show not on the list', {'profile': PROFILE, 'settings': {}, 'similar_to': [999_999_999]}, 'on your list'),
    ('choosing a neutral show', {'profile': [{'id': 169, 'weight': 0}], 'settings': {}, 'similar_to': [169]}, 'counted as liked'),
    ('an oversized selection', {'profile': PROFILE, 'settings': {}, 'similar_to': list(range(1, 62))}, 'up to 60'),
    ('choosing with an empty list', {'profile': [], 'settings': {}, 'similar_to': [169]}, 'on your list'),
]:
    try:
        app.calculate(body)
        check(f'rejects {label}', False)
    except ValueError as exc:
        check(f'rejects {label}', said in str(exc), str(exc))

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
