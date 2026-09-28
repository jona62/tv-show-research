"""Check fresh.py: parsing, determinism, and the guardrails for daily rotation.

Run from the repository root:  .venv/bin/python app/test_fresh.py
"""
from pathlib import Path
import hashlib
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fresh import Fresh, parse, dither, explore, pick_one, spread, shuffle_rows, DEPTH  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def rejects(name, body, said):
    try:
        parse(body)
    except ValueError as exc:
        check(name, said in str(exc), str(exc))
    else:
        check(name, False, 'accepted')


seed = lambda day: hashlib.sha256(f'salt|{day}'.encode()).hexdigest()[:16]
days = [f'2026-{m:02d}-{d:02d}' for m, top in ((10, 31), (11, 30)) for d in range(1, top + 1)][:60]
ranked = list(range(1000, 1300))

# 1. Parsing.
check('no freshness asked is falsy', not parse({}) and not parse({'profile': []}))
f = parse({'day': '2026-10-05', 'seed': 'ab' * 8, 'seen': {'12': 1.5, '13': 0}, 'engaged': [5], 'resting': [7],
           'tired': ['genre-drama']})
check('a full request parses', f.day == '2026-10-05' and f.seen == {12: 1.5} and 5 in f.engaged and 7 in f.resting
      and 'genre-drama' in f.tired)
check('an engaged show carries no fatigue', Fresh(seen={5: 3.0}, engaged=[5]).fatigue(5) == 0)
rejects('a bad day is refused', {'day': '2026-02-30', 'seed': 'ab' * 8}, 'YYYY-MM-DD')
rejects('a bad seed is refused', {'day': '2026-10-05', 'seed': 'xyz'}, 'hexadecimal')
rejects('a day without a seed is refused', {'day': '2026-10-05'}, 'together')
rejects('too many seen shows are refused', {'seen': {str(i): 1 for i in range(301)}}, 'up to 300')
rejects('a seen count out of range is refused', {'seen': {'1': 51}}, '0 to 50')
rejects('a seen count that is not a number is refused', {'seen': {'1': 'x'}}, '0 to 50')
rejects('engaged ids must be whole numbers', {'engaged': ['1']}, 'show ids')
rejects('row keys are checked', {'tired': ['Drama!']}, 'row keys')

# 2. Determinism, and nothing without a seed.
check('without freshness the plain ranking shows', dither(ranked, Fresh(), 'next', 24) == ranked[:24])
one = Fresh('2026-10-05', seed('2026-10-05'))
check('the same day and seed give the same list', dither(ranked, one, 'next', 24) == dither(ranked, Fresh('2026-10-05', seed('2026-10-05')), 'next', 24))
check('surfaces draw their own noise', dither(ranked, one, 'next', 24) != dither(ranked, one, 'rows', 24))
check('the top five stay put', dither(ranked, one, 'next', 24)[:5] == ranked[:5])
check('the list keeps its length and has no repeats', len(set(dither(ranked, one, 'next', 24))) == 24)

# 3. Sixty days of someone who opens the page daily and acts on nothing.
shown_days, lists = {}, []
for n, day in enumerate(days):
    seen = {i: sum(0.5 ** ((n - d) / 7) for d in ds if d < n) for i, ds in shown_days.items()}
    today = dither(ranked, Fresh(day, seed(day), {i: v for i, v in seen.items() if v >= 0.1}), 'next', 24)
    lists.append(today)
    for i in today:
        shown_days.setdefault(i, []).append(n)
overlap = statistics.mean(len(set(a) & set(b)) / 24 for a, b in zip(lists, lists[1:]))
check('most of the list carries over from day to day', overlap >= 0.6, round(overlap, 2))
check('but it does change', overlap <= 0.9, round(overlap, 2))
worst_absence = 0
for i in ranked[:10]:
    run = 0
    for today in lists:
        run = 0 if i in today else run + 1
        worst_absence = max(worst_absence, run)
check('no top-ten title is gone for more than three days running', worst_absence <= 3, worst_absence)
check('nothing below the top 72 ever shows', max(ranked.index(i) for today in lists for i in today) < DEPTH * 24)
distinct = len({i for today in lists[:30] for i in today})
check('a month shows several dozen titles, not the same 24', distinct >= 45, distinct)

# 4. Explore places, the hero and rows.
shown = dither(ranked, one, 'next', 24)
mixed, placed = explore(shown, ranked, one, 'next')
check('two titles from further down join at places 12 and 20', len(placed) == 2 and mixed[11] in placed and mixed[19] in placed
      and len(mixed) == 24 and all(24 <= ranked.index(i) <= 71 for i in placed))
check('explore does nothing without a seed', explore(shown, ranked, Fresh(), 'next') == (shown, set()))
heroes = [pick_one(ranked, Fresh(d, seed(d)), 'hero') for d in days]
check('the hero changes from day to day', len(set(heroes)) >= 6, heroes[:10])
check('the hero comes from the top ten', all(ranked.index(h) < 10 for h in heroes))
check('the best is the likeliest hero', heroes.count(ranked[0]) == max(heroes.count(h) for h in set(heroes)))
check('a resting hero is never drawn', all(pick_one(ranked, Fresh(d, seed(d), resting=ranked[:3]), 'hero') not in ranked[:3] for d in days))
check('without a seed the hero is the best', pick_one(ranked, Fresh(), 'hero') == ranked[0])
row = ['a1', 'a2', 'a3', 'b1', 'c1', 'a4']
spreaded = spread(row, lambda x: [x[0]])
check('a repeated network moves down the row', spreaded.index('b1') < row.index('b1') and spreaded[0] == 'a1')
check('the first places can be kept', spread(row, lambda x: [x[0]], keep=3)[:3] == row[:3])
rows = [f'r{n}' for n in range(12)]
reordered = shuffle_rows(rows, one, key_of=lambda r: r)
check('the first two rows stay, the rest reorder', reordered[:2] == rows[:2] and sorted(reordered) == sorted(rows)
      and reordered != rows)
tired = shuffle_rows(rows, Fresh('2026-10-05', seed('2026-10-05'), tired=['r2']), key_of=lambda r: r)
check('a row passed over for days goes last', tired[-1] == 'r2')
check('rows keep their order without freshness', shuffle_rows(rows, Fresh(), key_of=lambda r: r) == rows)

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
