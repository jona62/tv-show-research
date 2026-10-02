"""Check the app engine against the research recommender and its own contracts.

Run from the repository root:  .venv/bin/python app/tests/test_engine.py
"""
from pathlib import Path
import hashlib
import importlib.util
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))

from backend.recommendation.engine import Engine, DEFAULT_SETTINGS                      # noqa: E402
from backend.recommendation import engine as engine_module                                   # noqa: E402
reference_spec = importlib.util.spec_from_file_location('site_recommender', ROOT / 'site' / 'backend' / 'recommender.py')
recommender = importlib.util.module_from_spec(reference_spec)
reference_spec.loader.exec_module(recommender)
from backend.recommendation import taste as taste_module                                     # noqa: E402
from backend.recommendation.titles import normalize                                     # noqa: E402
from backend.fallback import answer                                                     # noqa: E402

PROFILE = [{'id': 13417, 'weight': 1}, {'id': 169, 'weight': 1}, {'id': 618, 'weight': 1},
           {'id': 42062, 'weight': .7}, {'id': 182, 'weight': 1}, {'id': 82, 'weight': .35},
           {'id': 80, 'weight': -1}]
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + detail if detail and not ok else ""}')
    if not ok:
        failures.append(name)


app = Engine(ROOT / 'data' / 'model')
reference = recommender.Engine()


def closeness_only(body):
    """The ranking with taste and the rating pull switched off and every liked show
    one interest, which leaves closeness alone: what the research engine ranks by."""
    saved = taste_module.STRENGTH, taste_module.QUALITY, engine_module.INTEREST_JOIN
    taste_module.STRENGTH, taste_module.QUALITY, engine_module.INTEREST_JOIN = 0.0, 0.0, 0.0
    try:
        return app.calculate(body)
    finally:
        taste_module.STRENGTH, taste_module.QUALITY, engine_module.INTEREST_JOIN = saved


# 1. Closeness alone ranks as the research engine does once the settings line up;
# scores are measured against the best pick, so they agree in proportion.
settings = {**DEFAULT_SETTINGS, 'rating_min': 0, 'known_min': 0, 'facets': 0}
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
    ('zero feature weights', {'profile': [{'id': 169, 'weight': 1}], 'settings': {'text': 0, 'themes': 0, 'genres': 0, 'facets': 0}}),
    ('unknown language', {'profile': [{'id': 169, 'weight': 1}], 'settings': {'language': 'Klingon'}}),
    ('oversized list', {'profile': [{'id': s['id'], 'weight': 1} for s in app.shows[:engine_module.MAX_LIST + 1]],
                        'settings': {}}),
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

# 9. Search finds the show a person means, however it is typed, on the real catalogue
# (titles.py says how; test_search.py checks each tier on its own).
SEARCHES = {
    'punctuation and spacing': [('greys anatomy', 67), ("grey's anatomy", 67), ('mr robot', 1871),
                                ('law and order svu', 103), ('law & order svu', 103), ('sponge bob', 713),
                                ('spongebob', 713), ('spongebob squarepants', 713)],
    'typos': [('breaking bda', 169), ('stranger thigns', 2993), ('sucession', 23470), ('sucesion', 23470),
              ('the wirre', 179), ('game of throne', 82), ('brooklyn nine nine', 49), ('brekaing bad', 169)],
    'numbers and short titles': [('brooklyn 99', 49), ('911', 28152), ('9-1-1', 28152), ('nine one one', 28152),
                                 ('24', 167), ('Lost', 123), ('You', 26856), ('Ted', 55832), ('ER', 547), ('v', 494),
                                 ('thirteen reasons why', 7194)],
    'ranking': [('office', 526), ('the office', 526), ('friends', 431), ('doctor who', 210)],
    'titles as they are typed': [('breaking b', 169), ('the last of', 46562), ('stranger thi', 2993), ('greys ana', 67)],
    'more words than the title': [('Demon Slayer: Kimetsu no Yaiba', 41469), ('stranger things season 4', 2993),
                                  ('the office us', 526), ('breaking bad amc series', 169)],
    'a year at the end': [('the office 2005', 526), ('the office 2001', 1292), ('doctor who 2005', 210),
                          ('doctor who 1963', 766), ('doctor who 2023', 72724), ('shogun 2024', 37336),
                          ('shogun 1980', 10460), ('space 1999', 5920)],
    'Criminal Minds query variants': [('Criminal Minds', 81), ('Minds Criminal', 81), ('Minds and Criminal', 81),
                                      ('Crimnal Minds', 81), ('Criminal Mnds', 81), ('Criminal Midns', 81),
                                      ('Criminal,Minds', 81), ('Criminal, Minds', 81), ('riminal Mind', 81)],
}
slowest = 0.0
for kind, cases in SEARCHES.items():
    wrong = []
    for q, want in cases:
        started = time.perf_counter()
        found = app.search(q)
        slowest = max(slowest, time.perf_counter() - started)
        if not found or found[0]['id'] != want:
            wrong.append((q, [(c['name'], c['year']) for c in found[:2]]))
    check(f'search copes with {kind}', not wrong, str(wrong))
spider = app.search('spider man')
check('spider man finds Spider-Man, best known first', spider[0]['name'] == 'Spider-Man'
      and [c['id'] for c in spider[:2]] == [c['id'] for c in app.search('Spider-Man')[:2]])
check('search returns each show once, a page at most',
      all(len({c['id'] for c in app.search(q)}) == len(app.search(q)) <= 12 for q in ('the', 'love', 'office', 'lost')))
check('a single character finds only titles of that one character',
      [c['id'] for c in app.search('v')][:2] == [494, 1039]
      and all(normalize([c.get('aka') or c['name']]) == ['a'] for c in app.search('a')))
check('nothing to search for finds nothing', app.search('') == [] and app.search(' ?! ') == [])
check('search keeps the card shape', set(app.search('lost')[0]) == {'id', 'name', 'year', 'channel', 'rating',
                                                                    'language', 'type', 'known'})
check('every search here answers in well under a second', slowest < .25, f'{slowest * 1000:.0f} ms')
criminal_family = {81, 3032, 1020, 50417}
check('Criminal Minds variants retain related series in the real catalogue', all(
    criminal_family <= {card['id'] for card in app.search(query)}
    for query, _want in SEARCHES['Criminal Minds query variants']))


class FranchiseRemote:
    def search(self, _query):
        # TVmaze's observed misspelling ranking puts spinoffs ahead of the primary.
        return [{'id': show_id, 'name': app.shows[app.by_id[show_id]]['name']}
                for show_id in (3032, 1020, 81, 50417)]


check('remote typo ranking cannot demote the real catalogue primary', all(
    answer(app, query, FranchiseRemote())['shows'][0]['id'] == 81
    for query in ('Crimnal Minds', 'Criminal Mnds', 'Criminal Midns')))

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
# A show with no plot, no genres and no facets (not even a network) has nothing to match on.
bare = next(s['id'] for i, s in enumerate(app.shows) if not s['summary_words'] and not s['genre_bits']
            and not (app.facets and app.facets.row_ptr[i + 1] > app.facets.row_ptr[i]))
blank = app.calculate({'profile': thin + [{'id': bare, 'weight': 1}], 'settings': {}, 'similar_to': [bare]})
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
    ('an oversized selection', {'profile': PROFILE, 'settings': {}, 'similar_to': list(range(1, engine_module.MAX_LIST + 2))},
     'up to 3,000'),
    ('choosing with an empty list', {'profile': [], 'settings': {}, 'similar_to': [169]}, 'on your list'),
]:
    try:
        app.calculate(body)
        check(f'rejects {label}', False)
    except ValueError as exc:
        check(f'rejects {label}', said in str(exc), str(exc))

# 12. Freshness between visits (fresh.py). Without a day and seed or seen counts the
# answer is the plain ranking; with them the first five hold, the rest rotate with the
# day's seed and what was shown lately, and places 12 and 20 go to shows from a little
# further down.
seed_of = lambda day: hashlib.sha256(f'test|{day}'.encode()).hexdigest()[:16]
MON, TUE = '2026-10-05', '2026-10-06'
fresh_body = lambda day, **extra: {'profile': PROFILE, 'settings': {}, 'day': day, 'seed': seed_of(day), **extra}
monday, tuesday = app.calculate(fresh_body(MON)), app.calculate(fresh_body(TUE))
top = ids(strict)
check('without freshness nothing says a day, a seed or a place',
      'fresh' not in strict and all('place' not in p for p in strict['picks']))
check('engaged ids alone change nothing', app.calculate({'profile': PROFILE, 'settings': {}, 'engaged': top[:3]}) == strict)
check('a day and its seed give the same answer every time', app.calculate(fresh_body(MON)) == monday)
check('the day and seed are echoed', monday['fresh'] == {'day': MON, 'seed': seed_of(MON)})
check('another day rotates the picks but keeps most of them',
      ids(monday) != ids(tuesday) and len(set(ids(monday)) & set(ids(tuesday))) >= 15,
      str(len(set(ids(monday)) & set(ids(tuesday)))))
check('the first five hold and are marked steady', ids(monday)[:5] == ids(tuesday)[:5] == top[:5]
      and all(p['place'] == 'steady' for p in monday['picks'][:5]))
places = lambda answer: [p['place'] for p in answer['picks']]
check('places 12 and 20 are a little different and the rest rotate',
      all(places(a) == ['steady'] * 5 + ['fresh'] * 6 + ['different'] + ['fresh'] * 7 + ['different'] + ['fresh'] * 4
          for a in (monday, tuesday)), places(monday))
floor = engine_module.DIFFERENT_FLOOR * strict['picks'][-1]['score']
check('a different pick comes from ranks 25 to 72 and clears the floor',
      all(25 <= p['rank'] <= 72 and p['score'] >= floor - .1 for a in (monday, tuesday) for p in a['picks']
          if p['place'] == 'different'))
check('every pick keeps its rank in the full ranking', all(
    p['rank'] == top.index(p['id']) + 1 for p in monday['picks'] if p['rank'] <= 24) and max(p['rank'] for p in monday['picks']) <= 72)
check('the list keeps its length, without repeats or rated shows',
      len(set(ids(monday))) == len(monday['picks']) == 24 and not rated & set(ids(monday)))
check('the rest of the answer is the plain one',
      {k: v for k, v in monday.items() if k not in ('picks', 'fresh')} == {k: v for k, v in strict.items() if k != 'picks'})
worn = app.calculate(fresh_body(MON, seen={str(top[2]): 50}))
check('a show shown day after day gives way at the top', top[2] not in ids(worn)[:5] and ids(worn)[:5] == [*top[:2], *top[3:6]])
check('unless it was engaged with', ids(app.calculate(fresh_body(MON, seen={str(top[2]): 50}, engaged=[top[2]])))[:5] == top[:5])
tired = app.calculate({'profile': PROFILE, 'settings': {}, 'seen': {str(top[0]): 50}})
check('seen counts without a seed move a show down, with no noise and no different places',
      tired['fresh'] == {'day': None, 'seed': None} and ids(tired)[:5] == [top[1], top[2], top[0], top[3], top[4]]
      and 'different' not in places(tired))
few = {'known_min': 95, 'year_min': 2018, 'type': 'documentary', 'status': 'Ended'}
thin_pool = app.calculate({'profile': PROFILE, 'settings': few, 'day': MON, 'seed': seed_of(MON)})
plain_pool = app.calculate({'profile': PROFILE, 'settings': few})
check('a pool too small to rotate shows all of itself', 5 < len(plain_pool['picks']) < 24
      and sorted(ids(thin_pool)) == sorted(ids(plain_pool)) and ids(thin_pool)[:5] == ids(plain_pool)[:5]
      and 'different' not in places(thin_pool))
check('an empty list still echoes the day', app.calculate({'profile': [], 'settings': {}, 'day': MON, 'seed': seed_of(MON)})['fresh']['day'] == MON)
check('validate keeps its three parts and read adds the freshness',
      len(app.validate(fresh_body(MON))) == 3 and app.read(fresh_body(MON))[3].seed == seed_of(MON))

# Two weeks of someone who opens the page daily and sees every pick: most of the list
# carries over, no plain top-ten show is gone for more than three days, nothing below 72.
shown_on, lists = {}, []
for n in range(14):
    day = f'2026-10-{n + 1:02d}'
    seen = {str(i): min(50, round(sum(.5 ** ((n - d) / 7) for d in ds), 1)) for i, ds in shown_on.items()}
    answer = app.calculate(fresh_body(day, seen={k: v for k, v in seen.items() if v >= .1}))
    lists.append(answer)
    for i in ids(answer):
        shown_on.setdefault(i, []).append(n)
carried = statistics.mean(len(set(ids(a)) & set(ids(b))) / 24 for a, b in zip(lists, lists[1:]))
check('over two weeks most of the list carries over from day to day', carried >= .6, f'{carried:.2f}')
gone = max(max((len(run) for run in ''.join('x' if i not in ids(a) else ' ' for a in lists).split()), default=0) for i in top[:10])
check('no top-ten show is gone for more than three days running', gone <= 3, str(gone))
check('nothing ranked below 72 is shown', max(p['rank'] for a in lists for p in a['picks']) <= 72)
check('and the fortnight shows more than one list\'s worth', len({i for a in lists for i in ids(a)}) >= 36)

for label, extra, said in [
    ('a day that is not a date', {'day': '2026-02-30', 'seed': 'ab' * 8}, 'YYYY-MM-DD'),
    ('a seed that is not hexadecimal', {'day': MON, 'seed': 'not-a-seed'}, 'hexadecimal'),
    ('a day without a seed', {'day': MON}, 'together'),
    ('a seen count out of range', {'seen': {'169': 51}}, '0 to 50'),
    ('seen shows not keyed by id', {'seen': {'Lost': 1}}, 'keyed by their id'),
    ('too many seen shows', {'seen': {str(i): 1 for i in range(301)}}, 'up to 300'),
    ('engaged ids that are not numbers', {'engaged': ['169']}, 'show ids'),
]:
    for how, call in (('calculate', app.calculate), ('validate', app.validate)):
        try:
            call({'profile': PROFILE, 'settings': {}, **extra})
            check(f'{how} rejects {label}', False)
        except ValueError as exc:
            check(f'{how} rejects {label}', said in str(exc), str(exc))

# Co-interest from Wikipedia's clickstream: readers of one show's article who go on to
# another's add to closeness, except between shows a franchise already links.
from backend.recommendation import facets as facets_module                                   # noqa: E402
import tempfile                                                  # noqa: E402
if app.co:
    bb, bcs, mad = app.by_id[169], app.by_id[618], next(i for i, s in enumerate(app.shows) if s['name'] == 'Mad Men')
    linked = dict(app.cointerest(bb))
    check('co-interest links Breaking Bad to shows its readers look up', mad in linked, sorted(linked)[:5])
    check('but not to a show it shares a franchise with', bcs not in linked)
    plain_near = app.facets.similarity(bb, app.facet_weights)[mad]
    check('a co-interest link adds to the facet closeness', app.components(bb)[3][mad] > plain_near + 1e-6)
    off = app.blend(bb, {**DEFAULT_SETTINGS, 'facets': 0})
    on = app.blend(bb, DEFAULT_SETTINGS)
    check('turning facets off turns co-interest off too', on[mad] > off[mad])
    check('a strong enough link is named as a tie', {'family': 'fans', 'label': ''} in app.ties(mad, bb)
          or linked.get(mad, 0) < engine_module.CO_TIE)
    empty = Path(tempfile.mkdtemp())
    check('a model without co-interest reads as none', facets_module.cointerest(empty, app.n) is None)
    try:
        facets_module.cointerest(ROOT / 'data' / 'model', app.n + 1)
        check('co-interest for another catalog size is refused', False)
    except ValueError as exc:
        check('co-interest for another catalog size is refused', 'rows' in str(exc), str(exc))
else:
    print('skip  the model has no co-interest yet')

# 13. Long lists. Past DENSE_MAX a list is ranked from each show's closest shows in the
# neighbour index (Wide), which must agree with the engine's own closeness.
import random                                                    # noqa: E402
if app.neighbours:
    recommendable = [i for i, s in enumerate(app.shows) if s['recommendable']]
    story = {**DEFAULT_SETTINGS, 'text': 70, 'themes': 20, 'genres': 10}
    for sample in (169, 2993, 44933, app.shows[4321]['id']):
        i = app.by_id[sample]
        exact = app.blend(i, DEFAULT_SETTINGS)
        best = sorted((j for j in recommendable if j != i), key=lambda j: -exact[j])[:app.neighbours.width]
        index, near, _evidence = app.row(i, DEFAULT_SETTINGS)
        cut = exact[best[-1]]
        check(f'the index holds the closest shows to {app.shows[i]["name"]}',
              set(index) == set(best) or all(exact[j] >= cut - 0.02 for j in index), str(sorted(set(best) - set(index))[:5]))
        check(f'and how close each sits, as the engine has it',
              all(abs(v - exact[j]) <= 0.02 * exact[j] + 0.01 for j, v in zip(index, near)))
        story_exact = app.blend(i, story)
        _index, story_near, _evidence = app.row(i, story)
        check('and other settings rebuild from its parts',
              all(abs(v - story_exact[j]) <= 0.02 * story_exact[j] + 0.02 for j, v in zip(index, story_near)))
        others = random.Random(sample).sample(recommendable, 20)
        check('closeness a pair at a time is the engine\'s',
              all(abs(v - exact[j]) < 1e-4 for v, j in zip(app.pairs(i, others, DEFAULT_SETTINGS), others)))

    # A long list, as someone who has watched a great deal might rate it: the best-known
    # shows, mostly liked, some loved, some only OK and some disliked.
    pool = sorted(recommendable, key=lambda i: (-app.popularity[i], app.shows[i]['id']))
    draw = random.Random(7)
    longest = [{'id': app.shows[i]['id'], 'weight': draw.choice((1, .7, .7, .7, .35, 0, -1))}
               for i in pool[:engine_module.MAX_LIST]]
    rated = {p['id'] for p in longest}
    started = time.perf_counter()
    answer = app.calculate({'profile': longest, 'settings': {}})
    spent = time.perf_counter() - started
    positives = [p for p in longest if p['weight'] > 0]
    check(f'a list of {engine_module.MAX_LIST:,} is answered, in {spent:.2f}s', len(answer['picks']) == 24 and spent < 5)
    check('none of its picks is a rated show', not rated & {p['id'] for p in answer['picks']})
    check('its liked shows come back cut to the ones it names',
          answer['liked_count'] == len(positives) and 0 < len(answer['liked']) <= 3 * engine_module.WIDE_LIKED
          and {p['because_id'] for p in answer['picks']} <= {s['id'] for s in answer['liked']})
    check('each pick links to each liked show sent', all(len(p['links']) == len(answer['liked']) for p in answer['picks']))
    check('its interests say how many shows each holds and name a few',
          answer['interests'] and all(0 < len(it['shows']) <= engine_module.WIDE_NAMED and it['size'] >= len(it['shows'])
                                      for it in answer['interests'])
          and sum(it['size'] for it in answer['interests']) == len(positives))
    check('the taste chart comes whole', answer['fit']['genres'] and all(0 < v <= 100 for v in answer['fit']['genres'].values()))
    liked = [p for p in longest if p['weight'] > 0]
    cut = engine_module.DENSE_MAX
    check('a list of the old limit is ranked as it always was, and one past it from the index',
          type(app.ranking(liked[:cut], [], engine_module.Closeness(app, DEFAULT_SETTINGS), DEFAULT_SETTINGS)).__name__ == 'Ranking'
          and type(app.ranking(liked[:cut + 1], [], {}, DEFAULT_SETTINGS)).__name__ == 'Wide')
    chosen = app.calculate({'profile': longest, 'settings': {}, 'similar_to': [positives[0]['id']]})
    check('a long list can still match just one of its shows',
          chosen['picks'] and all(p['because_id'] == positives[0]['id'] for p in chosen['picks']))
    story_answer = app.calculate({'profile': longest, 'settings': story})
    check('and takes other settings', story_answer['picks'] and story_answer['settings']['text'] == 70)
    # Without the index a long list is ranked from its most recent ratings alone.
    kept, app.neighbours = app.neighbours, None
    try:
        focused = app.focus(longest)
        started = time.perf_counter()
        fallback = app.calculate({'profile': longest, 'settings': {}})
        check('a model without the index ranks a long list from its most recent ratings',
              sum(1 for p in focused if p['weight']) == engine_module.DENSE_MAX and fallback['picks']
              and not rated & {p['id'] for p in fallback['picks']} and time.perf_counter() - started < 10)
    finally:
        app.neighbours = kept
    # Average linkage kept a best partner per group; it must merge as the plain way does.
    draw = random.Random(3)
    for size in (2, 7, 25, 60):
        sim = [[0.0] * size for _ in range(size)]
        for x in range(size):
            for y in range(x + 1, size):
                sim[x][y] = sim[y][x] = draw.random() * 0.3
        groups = [[x] for x in range(size)]
        while len(groups) > 1:
            link, pair = max((sum(sim[a][b] for a in g for b in h) / (len(g) * len(h)), (x, y))
                             for x, g in enumerate(groups) for y, h in enumerate(groups) if y > x)
            if link < engine_module.INTEREST_JOIN:
                break
            groups[pair[0]] = groups[pair[0]] + groups.pop(pair[1])
        mine = engine_module.average_linkage([row[:] for row in sim], engine_module.INTEREST_JOIN)
        check(f'average linkage of {size} merges as the plain way does',
              sorted(map(sorted, groups)) == sorted(mine))
else:
    print('skip  the model has no neighbour index yet')

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
