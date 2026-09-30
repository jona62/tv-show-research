"""Check fresh.py: parsing, determinism, and the guardrails for daily rotation.

Run from the repository root:  .venv/bin/python app/test_fresh.py
"""
from pathlib import Path
import hashlib
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fresh import Fresh, parse, dither, rotate, explore, pick_one, spread, shuffle_rows, DEPTH, LEAD_TOP  # noqa: E402

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

# 5. Visits: Couchside's app opened several times a day, each visit with a seed of its own.
visit_seed = lambda day, k: hashlib.sha256(f'salt|{day}|{k}'.encode()).hexdigest()[:16]
f = parse({'day': '2026-10-05', 'seed': 'ab' * 8, 'visit': 'cd' * 8})
check('a visit parses beside its day and seed', f.visit == 'cd' * 8 and f.echo() == {'day': '2026-10-05', 'seed': 'ab' * 8,
                                                                                      'visit': 'cd' * 8})
check('a day without a visit is as it was', parse({'day': '2026-10-05', 'seed': 'ab' * 8}).visit is None
      and one.echo() == {'day': '2026-10-05', 'seed': seed('2026-10-05')})
rejects('a malformed visit is refused', {'day': '2026-10-05', 'seed': 'ab' * 8, 'visit': 'xyz'}, 'hexadecimal')
rejects('a visit without its day and seed is refused', {'visit': 'cd' * 8}, 'with its day and seed')


def visit(day, k, seen=None, resting=()):
    return Fresh(day, seed(day), seen, (), resting, (), visit_seed(day, k))


check('without a rotating head, a visit keeps the first places as the day does',
      dither(ranked, visit('2026-10-05', 1), 'row-a', 20, pinned=2)[:2] == ranked[:2])
check('the same visit gives the same list, rotating head and all',
      dither(ranked, visit('2026-10-05', 3), 'row-top', 20, rotating=6)
      == dither(ranked, visit('2026-10-05', 3), 'row-top', 20, rotating=6))
check('without a visit a rotating head holds still, as the day\'s pinned places',
      dither(ranked, one, 'row-top', 20, pinned=2, rotating=6) == dither(ranked, one, 'row-top', 20, pinned=2))
check('and without a seed rotating draws nothing', rotate(ranked, Fresh(), 'row-top', 6) == ranked[:6])


def overlap(a, b):
    return len(set(a) & set(b)) / len(a)


# The visits of a day stay nearer each other than two days do, past the first places.
same_day = statistics.mean(overlap(dither(ranked, visit(d, 1), 'row-a', 20)[5:], dither(ranked, visit(d, 2), 'row-a', 20)[5:])
                           for d in days[:30])
next_day = statistics.mean(overlap(dither(ranked, visit(d, 1), 'row-a', 20)[5:], dither(ranked, visit(e, 1), 'row-a', 20)[5:])
                           for d, e in zip(days[:30], days[1:31]))
check('the visits of a day share more of a list than two days do', same_day > next_day + 0.05,
      (round(same_day, 2), round(next_day, 2)))
check('but still differ', same_day < 0.95, round(same_day, 2))

# Five visits a day for thirty days, each seeing Top picks' first six: what earlier visits
# the same day showed counts half a day each (a day at most), as fresh.js counts it.
led, best3, fresh_faces, deepest = [], [], [], 0
for n, day in enumerate(days[:30]):
    today_seen, before = {}, None
    for k in range(1, 6):
        head = rotate(ranked, visit(day, k, {i: min(1.0, 0.5 * c) for i, c in today_seen.items()}), 'row-top', 6)
        led.append(head[0] == ranked[0])
        best3.append(set(ranked[:3]) <= set(head))
        deepest = max(deepest, max(ranked.index(i) for i in head))
        if before:
            fresh_faces.append(len(set(head) - set(before)))
        before = head
        for i in head:
            today_seen[i] = today_seen.get(i, 0) + 1
check('the best leads Top picks about three visits in four', 0.6 <= statistics.mean(led) <= 0.9, statistics.mean(led))
check('the best three are among the first six almost every visit', statistics.mean(best3) >= 0.85, statistics.mean(best3))
check('one or two of the first six are new each visit', 1 <= statistics.mean(fresh_faces) <= 2.5,
      statistics.mean(fresh_faces))
check('and none comes from below the best ten by rank and fatigue, the best dozen by rank alone', deepest < LEAD_TOP + 2,
      deepest)

# The hero: a new one each visit, never one shown earlier the same day.
shown_today, heroes = [], []
for k in range(1, 6):
    hero = pick_one(ranked, visit('2026-10-05', k, resting=shown_today), 'hero')
    heroes.append(hero)
    shown_today.append(hero)
check('each visit draws its own hero, none shown earlier the same day', len(set(heroes)) == 5, heroes)
check('from the best picks', all(ranked.index(h) < 10 + len(heroes) for h in heroes), [ranked.index(h) for h in heroes])
check('and the same visit draws the same one', pick_one(ranked, visit('2026-10-05', 2), 'hero')
      == pick_one(ranked, visit('2026-10-05', 2), 'hero'))

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
