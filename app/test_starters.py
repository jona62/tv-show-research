"""Check starters.py: the first-visit pool and the screens drawn from it.

Run from the repository root:  .venv/bin/python app/test_starters.py
It reads the real model, so what it holds to is what a visitor sees: determinism,
variety across days and visitors, the quotas, one title per franchise, the swaps a pick
makes and the 60% rule, the slots a language takes, and the same without facets.
"""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
import hashlib
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from engine import Engine, QUICK_PICKS                           # noqa: E402
import starters                                                  # noqa: E402
from starters import Starters, FACET_CAP, UNEXPLORED, MIN_RATING, UNRATED_POPULARITY, anchor_places  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def rejects(name, query, said, accept=''):
    try:
        starters.parse(parse_qs(query), accept)
    except ValueError as exc:
        check(name, said in str(exc), str(exc))
    else:
        check(name, False, 'accepted')


model = ROOT / 'app' / 'model'
e = Engine(model if (model / 'catalog.json.gz').exists() else ROOT / 'model')
started = time.perf_counter()
s = Starters(e)
built = time.perf_counter() - started
shows = e.shows
seeds = [hashlib.sha256(f'visitor {k}'.encode()).hexdigest()[:16] for k in range(60)]


def fresh(seed, rnd=0, picked=(), lang='en-US', count=24, pool=None):
    """A screen worked out afresh, not from the cache, for picked show ids."""
    pool = pool or s
    return pool._choose.__wrapped__(pool, seed, rnd, tuple(e.by_id[x] for x in picked if x in e.by_id), lang, count)


ids = lambda screen: [shows[slot.index]['id'] for slot in screen]
facet = lambda slot: s.facet_of(slot.index)


def sound(screen):
    """No title twice, no franchise twice, no facet over the cap."""
    keys = [s.keys(slot.index) for slot in screen]
    alone = all(not keys[a] & keys[b] for a in range(len(keys)) for b in range(a + 1, len(keys)))
    counts = {}
    for slot in screen:
        counts[facet(slot)] = counts.get(facet(slot), 0) + 1
    return len({slot.index for slot in screen}) == len(screen) and alone and max(counts.values()) <= FACET_CAP


def tally(screen):
    forms = [s.format_of(slot.index) for slot in screen]
    return {'formats': len(set(forms)), 'decades': len({starters.decade(shows[slot.index]['year']) for slot in screen
                                                        if shows[slot.index]['year']}),
            'cartoons': sum(f in ('animation', 'anime') for f in forms), 'unscripted': forms.count('unscripted'),
            'foreign': sum(shows[slot.index]['language'] not in (None, 'English') for slot in screen)}


# 1. The pool.
check(f'the pool builds in under 2 s ({built:.2f} s)', built < 2)
check(f'about 35 facets ({len(s.pool)})', 25 <= len(s.pool) <= 45, len(s.pool))
check('every facet keeps its best ten', all(len(pool) == 10 for pool in s.pool), [len(p) for p in s.pool])
pool = [i for p in s.pool for i in p]
check('every pooled title is eligible', all(
    shows[i]['recommendable'] and 'Adult' not in shows[i]['genres']
    and ((shows[i]['rating'] or 0) >= MIN_RATING or (shows[i]['rating'] is None and e.popularity[i] >= UNRATED_POPULARITY))
    for i in pool))
check('one title per franchise across the pool and its anchors',
      all(not s.keys(a) & s.keys(b) for n, a in enumerate(pool + list(s.anchors))
          for b in (pool + list(s.anchors))[n + 1:] if a != b))
check('the quick picks are anchors, and each format\'s most popular title joins them',
      {e.by_id[x] for x in QUICK_PICKS} <= set(s.anchors) and {s.format_of(i) for i in s.anchors} == set(starters.FORMATS))
check('facets span every format', {key[0] for key in s.facet_keys} == set(starters.FORMATS))
check('a facet is drawn from its best by S', all(
    [s.score[i] for i in p] == sorted((s.score[i] for i in p), reverse=True) for p in s.pool if len({
        starters.GROUP_OF.get(shows[i]['language'], shows[i]['language']) for i in p}) == 1))
group = lambda i: starters.GROUP_OF.get(shows[i]['language'], shows[i]['language'])
crowded = []
for n, ten in enumerate(s.pool):
    if s.facet_keys[n][0] == 'anime':
        continue
    members = [i for i, m in s.facet.items() if m == n]
    held = {g: sum(group(i) == g for i in ten) for g in {group(i) for i in members}}
    # A group outnumbers another by more than two only once the other has run out.
    crowded += [(s.labels[n], g, h) for g in held for h in held
                if held[g] - held[h] > starters.PER_GROUP and any(group(i) == h and i not in ten for i in members)]
check('no language group crowds a facet while others can fill it', not crowded, crowded)
star_trek = [i for i in pool if starters.stem(shows[i]['name']) == 'star trek']
check('shows sharing a name before a colon are one franchise', len(star_trek) <= 1, [shows[i]['name'] for i in star_trek])

# 2. Determinism, and variety across days and visitors.
a, b = fresh(seeds[0]), fresh(seeds[0])
check('the same seed, round, picks and language give the same screen', a == b and s.choose(seeds[0], 0, (), 'en-US') == a)
check('a screen holds 24 titles', all(len(fresh(seed)) == 24 for seed in seeds[:10]))
overlaps = [len(set(ids(fresh(x))) & set(ids(fresh(y)))) / 24 for x, y in zip(seeds[:30], seeds[1:31])]
check(f'two visitors share a third of their screen or less on average ({statistics.mean(overlaps):.0%})',
      statistics.mean(overlaps) <= 0.34, overlaps)
days = [hashlib.sha256(f'salt|2026-10-{d:02d}'.encode()).hexdigest()[:16] for d in range(1, 8)]
week = [set(ids(fresh(seed))) for seed in days]
check('one visitor\'s screen changes from day to day',
      all(len(x & y) <= 12 for x, y in zip(week, week[1:])), [len(x & y) for x, y in zip(week, week[1:])])
everyone = set().union(*(ids(fresh(seed)) for seed in seeds))
check(f'sixty visitors see well over a hundred titles between them ({len(everyone)})', len(everyone) > 120)
check('without a seed the screen is the plain one, with the quick picks leading',
      fresh(None) == fresh(None) and ids(fresh(None))[:2] == QUICK_PICKS[:2][::-1] or
      {ids(fresh(None))[0], ids(fresh(None))[1]} == set(QUICK_PICKS[:2]))

# 3. Every screen meets the quotas and the layout rules.
quota_misses, layout_misses, adjacent = [], [], []
for seed in seeds:
    for lang in ('en-US', 'ko', 'en-GB', '', 'es-MX', 'ja'):
        screen = fresh(seed, 0, (), lang)
        t = tally(screen)
        if any(t[k] < v for k, v in starters.QUOTAS.items()):
            quota_misses.append((seed, lang, t))
        if not sound(screen) or [q for q, slot in enumerate(screen) if slot.why == 'anchor'] != anchor_places(3, 24):
            layout_misses.append((seed, lang))
        adjacent.append(sum(facet(x) == facet(y) for x, y in zip(screen, screen[1:])))
check('every screen spans four formats, three decades, a cartoon, an unscripted title and two not in English',
      not quota_misses, quota_misses[:3])
check('no screen repeats a title, a franchise, or more than three of a facet; anchors sit at 0, 1 and 6',
      not layout_misses, layout_misses[:3])
check(f'no two titles of one facet side by side ({sum(adjacent)} pairs in {len(adjacent)} screens)',
      sum(adjacent) == 0, sum(adjacent))
first = [shows[fresh(seed)[0].index]['id'] for seed in seeds]
check('the first place is always a quick pick', all(x in QUICK_PICKS for x in first))
warm = [statistics.mean(s.familiarity(slot.index) for slot in screen[3:12]) -
        statistics.mean(s.familiarity(slot.index) for slot in screen[12:]) for screen in map(fresh, seeds[:20])]
check('the most familiar titles come first', min(warm) > 0, warm)

# 4. The visitor's language.
korean = [fresh(seed, 0, (), 'ko') for seed in seeds[:20]]
check('a Korean browser gets at least seven Korean titles',
      all(sum(shows[slot.index]['language'] == 'Korean' for slot in screen) >= 7 for screen in korean))
check('seven slots are its own, ranked by popularity within Korean', all(
    sum(slot.why == 'locale' for slot in screen) == 7 and all(shows[slot.index]['language'] == 'Korean'
                                                              for slot in screen if slot.why == 'locale')
    for screen in korean))
british = [fresh(seed, 0, (), 'en-GB') for seed in seeds[:20]]
check('en-GB takes four slots from British television', all(
    [shows[slot.index]['country'] for slot in screen if slot.why == 'locale'] == ['GB'] * 4 for screen in british))
indian = fresh(seeds[0], 0, (), 'en-IN')
check('en-IN takes them from India', [shows[slot.index]['country'] for slot in indian if slot.why == 'locale'] == ['IN'] * 4)
american = [fresh(seed, 0, (), 'en-US') for seed in seeds[:20]]
check('en-US has no locale slots; four explore facets not otherwise on screen', all(
    sum(slot.why == 'explore' for slot in screen) == 4 and not any(slot.why == 'locale' for slot in screen)
    for screen in american))
check('a language the catalogue lacks explores instead', not any(slot.why == 'locale' for slot in fresh(seeds[0], 0, (), 'eo'))
      and sum(slot.why == 'explore' for slot in fresh(seeds[0], 0, (), 'eo')) == 4)
mexican = fresh(seeds[0], 0, (), 'es-MX')
check('es-MX: Mexican shows in Spanish first, then Spanish from anywhere', sum(
    shows[slot.index]['language'] == 'Spanish' for slot in mexican if slot.why == 'locale') == 7 and any(
    shows[slot.index]['country'] == 'MX' for slot in mexican if slot.why == 'locale'))
check('language tags read as a language and a region', starters.locale('zh-Hant-TW') == ('Chinese', 'TW')
      and starters.locale('en-GB') == ('English', 'GB') and starters.locale('ko') == ('Korean', None)
      and starters.locale('not a tag!') == (None, None) and starters.locale('x' * 36) == (None, None))

# 5. A pick swaps three unpicked slots: a contrast, a neighbour and an unexplored facet.
swaps, contrasts, nears, unexplored_ok, kept_place = [], [], [], [], []
for seed in seeds[:30]:
    base = fresh(seed)
    at = 4
    pick = base[at]
    after = fresh(seed, 0, [shows[pick.index]['id']])
    changed = [q for q in range(24) if q != at and after[q].index != base[q].index]
    swaps.append(len(changed))
    kept_place.append(after[at].index == pick.index and after[at].why == 'picked')
    whys = {after[q].why: after[q] for q in changed}
    c = whys.get('contrast')
    if c:
        mine, theirs = shows[pick.index], shows[c.index]
        words = s.subgenres(pick.index) or set(mine['genres'])
        others = s.subgenres(c.index) or set(theirs['genres'])
        contrasts.append(facet(c) == facet(pick) and (
            starters.decade(mine['year']) != starters.decade(theirs['year']) or mine['language'] != theirs['language']
            or len(words & others) / len(words | others) < 0.5))
    n = whys.get('nearest')
    if n:
        nears.append(facet(n) != facet(pick) and facet(n) in s.near[facet(pick)][:6])
    u = whys.get('unexplored')
    if u:
        before = {facet(slot) for q, slot in enumerate(base) if q not in changed}
        unexplored_ok.append(facet(u) not in before and facet(u) != facet(pick))
check('a picked show stays where it was', all(kept_place))
check(f'each pick swaps exactly three other slots ({swaps})', all(x == 3 for x in swaps), swaps)
check('the swaps are a contrast, a neighbour and an unexplored facet', len(contrasts) >= 25 and len(nears) >= 25
      and len(unexplored_ok) >= 25, (len(contrasts), len(nears), len(unexplored_ok)))
check('a contrast shares the pick\'s facet but not its era, language or subgenre', all(contrasts))
check('a neighbour comes from one of the facets most like the pick\'s', all(nears), nears)
check('an unexplored title comes from a facet not on screen', all(unexplored_ok), unexplored_ok)

# 6. Ten picks in a row: picks stay put, and the screen never drills into one cluster.
share, stable, sound_all, moved = [], [], [], []
for seed in seeds[:20]:
    picked, places = [], {}
    screen = fresh(seed)
    for k in range(10):
        free = [q for q, slot in enumerate(screen) if slot.why != 'picked']
        q = free[(k * 5) % len(free)]
        picked.append(shows[screen[q].index]['id'])
        places[picked[-1]] = q
        before = screen
        screen = fresh(seed, 0, picked)
        moved.append(sum(1 for r in range(24) if r != q and before[r].why != 'picked' and screen[r].index != before[r].index))
        stable.append(all(shows[screen[p].index]['id'] == x and screen[p].why == 'picked' for x, p in places.items()))
        sound_all.append(sound(screen))
        explored = {facet(slot) for slot in screen if slot.why == 'picked'}
        unpicked = [slot for slot in screen if slot.why != 'picked']
        share.append(sum(facet(slot) not in explored for slot in unpicked) / len(unpicked))
check('picks keep their places through ten picks', all(stable))
check('the screen stays free of repeats and within the cap', all(sound_all))
check(f'at least 60% of unpicked titles come from facets with no pick (lowest {min(share):.0%})',
      min(share) >= UNEXPLORED - 1e-9)
check(f'a pick mostly changes three titles (median {statistics.median(moved)}, most {max(moved)})',
      statistics.median(moved) == 3 and max(moved) <= 8, moved)

# 7. Rounds, and picks the screen does not hold.
r0, r1 = fresh(seeds[0], 0), fresh(seeds[0], 1)
check('asking for different shows changes nearly every title', len(set(ids(r0)) & set(ids(r1))) <= 3,
      len(set(ids(r0)) & set(ids(r1))))
check('rounds run up to 50', len(fresh(seeds[0], 50)) == 24)
earlier = [shows[r0[q].index]['id'] for q in (3, 8)]
later = fresh(seeds[0], 1, earlier)
check('picks from an earlier round stay off the new screen, and so do their franchises',
      not set(earlier) & set(ids(later)) and all(
          not s.keys(slot.index) & s.keys(e.by_id[x]) for slot in later for x in earlier))
bb = e.by_id[169]
holding = next(seed for seed in seeds if any(slot.index == bb for slot in fresh(seed)))
saul = next(i for i, show in enumerate(shows) if show['name'] == 'Better Call Saul')
found = fresh(holding, 0, [shows[saul]['id']])
check('a show found by search stays off the screen but clears its franchise from it',
      bb not in {slot.index for slot in found} and saul not in {slot.index for slot in found} and sound(found))
check('unknown ids are dropped and repeats ignored', s.choose(seeds[0], 0, (999_999_999, 169, 169)) ==
      s.choose(seeds[0], 0, (169,)))
check('other screen sizes hold together', all(sound(fresh(seed, 0, (), 'en-US', n)) and len(fresh(seed, 0, (), 'en-US', n)) == n
                                              for seed in seeds[:5] for n in (6, 12, 36, 48)))

# 8. Requests.
check('a query reads', starters.parse(parse_qs('seed=0123456789abcdef&round=3&picked=169,82&lang=en-GB&count=12'))
      == ('0123456789abcdef', 3, [169, 82], 'en-GB', 12))
check('everything is optional', starters.parse({}) == (None, 0, [], '', 24))
check('Accept-Language stands in for a missing lang',
      starters.parse({}, 'ko-KR,ko;q=0.9,en-US;q=0.8')[3] == 'ko-KR' and starters.parse({}, '*, fr;q=0.5')[3] == 'fr')
rejects('a seed that is not 16 hex digits', 'seed=0123456789ABCDEF', 'seed')
rejects('a round past 50', 'round=51', 'round')
rejects('a negative round', 'round=-1', 'round')
rejects('a round in other digits', 'round=٣', 'round')
rejects('more than 20 picks', 'picked=' + ','.join(str(n) for n in range(1, 22)), 'up to 20')
rejects('a pick that is not an id', 'picked=169,abc', 'ids')
rejects('a pick twice', 'picked=169,169', 'once')
rejects('a language tag over 35 characters', 'lang=' + 'en-' + 'abcdefgh-' * 4, 'lang')
rejects('a language tag that is not one', 'lang=en_GB', 'lang')
rejects('a count below six', 'count=5', 'shows')
rejects('a count past 48', 'count=49', 'shows')
rejects('a parameter sent twice', 'seed=0123456789abcdef&seed=0123456789abcdef', 'once')

# 9. Speed.
twenty = []
for seed in seeds[:20]:
    picked = []
    for k in range(20):
        screen = fresh(seed, 0, picked)
        free = [slot for slot in screen if slot.why != 'picked']
        picked.append(shows[free[(k * 7) % len(free)].index]['id'])
    twenty.append((seed, tuple(picked)))
times = []
for seed, picked in twenty * 3:
    started = time.perf_counter()
    fresh(seed, 50, picked, 'ko')
    times.append((time.perf_counter() - started) * 1000)
times.sort()
check(f'a screen with 20 picks at round 50 takes under 20 ms (median {times[len(times) // 2]:.1f} ms, '
      f'95th {times[int(len(times) * .95)]:.1f} ms)', times[int(len(times) * .95)] < 20)

# 10. The same without facets: franchises by name, genres from TVmaze alone.
bare = SimpleNamespace(shows=e.shows, by_id=e.by_id, popularity=e.popularity, facets=None)
started = time.perf_counter()
plain = Starters(bare)
check(f'without facets the pool still builds ({time.perf_counter() - started:.2f} s, {len(plain.pool)} facets)',
      len(plain.pool) >= 15 and all(plain.pool))
plain_pool = [i for p in plain.pool for i in p]
check('without facets a franchise is a name before a colon', all(
    not plain.keys(a) & plain.keys(b) for n, a in enumerate(plain_pool) for b in plain_pool[n + 1:])
    and all(len(plain.keys(i)) == 1 for i in plain_pool))
bare_screens = [fresh(seed, pool=plain) for seed in seeds[:20]]
check('without facets every screen still meets the quotas', all(
    all(tally(screen)[k] >= v for k, v in starters.QUOTAS.items()) for screen in bare_screens))
bare_after = fresh(seeds[0], 0, [shows[bare_screens[0][5].index]['id']], pool=plain)
check('without facets a pick still swaps three', sum(
    a.index != b.index for a, b in zip(bare_screens[0], bare_after)) == 3 and bare_after[5].why == 'picked')
usable = Starters(e, lambda i: shows[i]['year'] and shows[i]['year'] >= 2000)
check('a usable test keeps out what an app cannot show', all(
    shows[i]['year'] >= 2000 for p in usable.pool for i in p) and all(shows[i]['year'] >= 2000 for i in usable.anchors))

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
