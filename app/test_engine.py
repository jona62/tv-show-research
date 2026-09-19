"""Check the app engine against the research recommender and its own contracts.

Run from the repository root:  .venv/bin/python app/test_engine.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'site'))

from engine import Engine, DEFAULT_SETTINGS                      # noqa: E402
import recommender                                               # noqa: E402

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

# 1. Same ranking as the research engine once the settings line up.
settings = {**DEFAULT_SETTINGS, 'rating_min': 0, 'known_min': 0}
mine = app.calculate({'profile': PROFILE, 'settings': settings})
theirs = reference.calculate({'profile': PROFILE, 'settings': {**settings, 'axis_x': 'all', 'axis_y': 'all'}})
overlap = min(len(mine['picks']), len(theirs['recommendations']))
check('ranking matches the research engine',
      [p['id'] for p in mine['picks'][:overlap]] == [p['id'] for p in theirs['recommendations'][:overlap]],
      f"{[p['name'] for p in mine['picks'][:3]]} vs {[p['name'] for p in theirs['recommendations'][:3]]}")
check('scores match the research engine',
      all(abs(a['score'] - b['score']) < .11 for a, b in zip(mine['picks'], theirs['recommendations'])))
check('candidate pool matches', mine['candidate_count'] == theirs['candidate_count'])

# 2. Nothing you have rated is ever recommended back.
rated = {p['id'] for p in PROFILE}
check('rated shows are excluded', not rated & {p['id'] for p in mine['picks']})

# 3. The popularity default keeps obscure titles out without demanding a rating.
strict = app.calculate({'profile': PROFILE, 'settings': {}})
check('default excludes obscure titles', all(p['known'] >= 85 for p in strict['picks']))
check('default is narrower than no floor', strict['candidate_count'] < mine['candidate_count'])
loose = app.calculate({'profile': PROFILE, 'settings': {'known_min': 0}})
check('popularity floor narrows the pool', strict['candidate_count'] < loose['candidate_count'])
check('popularity keeps good unrated titles',
      any(p['rating'] is None for p in app.calculate(
          {'profile': PROFILE, 'settings': {'known_min': 60}})['picks']))
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

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
