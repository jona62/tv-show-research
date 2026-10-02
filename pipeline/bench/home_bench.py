"""Offline check of Couchside's home page against an earlier one, over the bench personas.

For each persona in personas.json and holdout.json a fifth of its loves (at least one,
chosen by a generator seeded with the persona's key) is held out, and each home page is
built from the rest of its ratings under the default settings, with no day or seed so
both pages are their plain selves. Each page is read as the browser would read it, every
row of it, and scored on:

  loves in the first 3 rows    held-out loves among the first six cards of the first
  loves in the first 8 rows    three rows, and of the first eight (a show counts once)
  interests in the first 8     whether every interest holding 15% or more of the list's
                               weight has one of the first eight rows given to it: a row
                               at least half of whose first six cards the engine scored
                               for that interest
  repeats                      cards on the page beyond each show's first appearance

and, over the whole page, however long it runs:

  rows per page                median, fewest and most
  loves found by depth         where each held-out love first opens a row (among its
                               first six cards): rows 1-8, 9-20, 21-40, 41-80 or 81 on
  distinct shows               different shows on the page
  not personal                 the share of rows cut for anyone rather than the list
                               (the Top 10, Popular, a first visit's rows, rows to
                               explore and browse), from the page laid out at once
  rows by tier                 rows placed in today's rows (0) and each tier past them
  time                         seconds for the first request and for each request for
                               more, at the median and the 95th percentile. Each list
                               is asked for once first, so the engine's cache holds its
                               rated shows for both pages, as it does for a browser
                               paging down; the first page is the median of three tries
                               on each page, in turn
  today's rows match           whether the page's first rows are the earlier page's,
                               keys, order and cards, up to where the earlier one ends:
                               with --old at the last page with a fixed length
                               (7dafad2), today's rows must not have changed

The earlier page is Couchside's library as it was at a git revision (--old, by default
the last page with a fixed length), run beside the current engine. --stub-tiers stands
the rows of pipeline/bench/stub_tiers.py in for the tiers past today's rows.

    .venv/bin/python pipeline/bench/home_bench.py
    .venv/bin/python pipeline/bench/home_bench.py --stub-tiers
    .venv/bin/python pipeline/bench/home_bench.py --old e525e35 --out /tmp/home.json
"""
import argparse
import json
import random
import re
import statistics
import subprocess
import sys
import time
import types
from collections import Counter
from pathlib import Path
from runtime import module as runtime_module

ROOT = Path(__file__).resolve().parents[2]
COUCHSIDE = ROOT / 'couchside'
FILES = ('personas.json', 'holdout.json')
WEIGHTS = {'loves': 1, 'likes': .7, 'dislikes': -1}
HELD = 0.2          # share of loves held out
SHARE = 0.15        # an interest this heavy should have one of the first eight rows
GLANCE = 6
DEPTHS = ((1, 8), (9, 20), (21, 40), (41, 80), (81, None))
TRIES = 3           # first pages timed on each page, for the median


def old_library(rev):
    """Read either layout at a revision, running beside the current engine."""
    paths = ('couchside/backend/recommendation/library.py', 'couchside/library.py')
    for path in paths:
        found = subprocess.run(['git', 'show', f'{rev}:{path}'], cwd=ROOT,
                               capture_output=True, text=True)
        if found.returncode == 0:
            source = found.stdout
            break
    else:
        raise ValueError(f'No Couchside library found at git revision {rev}.')
    # Historical flat libraries import the current engine by its old module names.
    source = re.sub(r'(?m)^from (engine|fresh|starters|taste) import ',
                    r'from backend.recommendation.\1 import ', source)
    module = types.ModuleType('backend.recommendation.library_old')
    module.__package__ = 'backend.recommendation'
    module.__file__ = str(COUCHSIDE / 'backend' / 'recommendation' / 'library_old.py')
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def whole(lib, body, times=None):
    """Every row of a page: the new page is asked for eight rows and then six at a time,
    each request saying which rows it shows and, past today's rows, their tiers; an
    earlier page without paging answers everything at once. With times, each request's
    seconds go in it as ('first' or 'next', seconds, whether it asks past today's rows)."""
    t = time.perf_counter()
    answer = lib.home(body)
    if times is not None:
        times.append(('first', time.perf_counter() - t, False))
    rows = list(answer['rows'])
    while answer.get('more'):
        shown = [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:GLANCE]], **({'tier': r['tier']} if 'tier' in r else {})}
                 for r in rows]
        t = time.perf_counter()
        answer = lib.home({**body, 'shown': shown})
        if times is not None:
            times.append(('next', time.perf_counter() - t, any('tier' in s for s in shown)))
        rows += answer['rows']
    return [r for r in rows if r['kind'] != 'list']


def first_page(lib, body):
    t = time.perf_counter()
    lib.home(body)
    return time.perf_counter() - t


def personal(module, lib, body):
    """Whether each row of the page laid out at once is personal, by key ({} for a page
    too old to say)."""
    try:
        profile, settings, positives, negatives, rated, candidates, fresh = lib.prepare(body)
        page = module.Page(lib, profile, settings, positives, negatives, rated, candidates, lib.read_list(body), fresh)
        return {shelf.key: shelf.personal for shelf, _items in page.layout([])[1]}
    except (AttributeError, TypeError):
        return {}


def score(rows, held, groups, heavy, mine):
    first = lambda n: {c['id'] for r in rows[:n] for c in r['items'][:GLANCE]}
    cards = [c['id'] for r in rows for c in r['items']]
    given = set()
    for r in rows[:8]:
        owners = Counter(groups.get(c['id']) for c in r['items'][:GLANCE])
        owner, n = owners.most_common(1)[0] if owners else (None, 0)
        if owner is not None and n >= len(r['items'][:GLANCE]) / 2:
            given.add(owner)
    found = {}
    for n, r in enumerate(rows, 1):
        for c in r['items'][:GLANCE]:
            if c['id'] in held and c['id'] not in found:
                found[c['id']] = next(k for k, (lo, hi) in enumerate(DEPTHS) if lo <= n and (hi is None or n <= hi))
    return {'rows': len(rows), 'hits3': len(held & first(3)), 'hits8': len(held & first(8)),
            'interests': not heavy or heavy <= given, 'repeats': len(cards) - len(set(cards)),
            'distinct': len(set(cards)), 'depths': [sum(1 for d in found.values() if d == k) for k in range(len(DEPTHS))],
            'plain': sum(1 for r in rows if mine.get(r['key']) is False), 'known': sum(1 for r in rows if r['key'] in mine),
            'tiers': dict(Counter(r.get('tier', 0) for r in rows)), 'titles': [r['title'] for r in rows]}


def cut(rows):
    return [(r['key'], r['title'], [c['id'] for c in r['items']]) for r in rows]


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float('nan')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--old', default='7dafad2', help='git revision of the earlier library.py')
    parser.add_argument('--out', help='write every persona\'s numbers here as JSON')
    parser.add_argument('--stub-tiers', action='store_true', help='stand-in rows for the tiers past today\'s rows')
    args = parser.parse_args()
    library = runtime_module(COUCHSIDE, 'library')
    engine_module = runtime_module(COUCHSIDE, 'engine')
    Engine, DEFAULT_SETTINGS = engine_module.Engine, engine_module.DEFAULT_SETTINGS
    if args.stub_tiers:
        sys.path.insert(0, str(ROOT / 'pipeline' / 'bench'))
        import stub_tiers
        stub_tiers.install(library.Page)
    engine = Engine(ROOT / 'data' / 'model')
    art = COUCHSIDE / 'assets' / 'model' / 'art.bin.gz'
    modules = {'old': old_library(args.old), 'new': library}
    pages = {which: module.Library(engine, art) for which, module in modules.items()}
    # Each page is laid out in the requests timed, never behind a first one (library.Kept).
    for lib in pages.values():
        lib.ahead = False
    report, started = {}, time.time()
    times = {'old': [], 'new': []}
    for name in FILES:
        personas = json.loads((ROOT / 'pipeline' / 'bench' / name).read_text())['personas']
        for p in personas:
            loves = [s['id'] for s in p['loves'] if s['id'] in engine.by_id]
            held = set(random.Random(p['key']).sample(loves, max(1, round(HELD * len(loves)))))
            profile = [{'id': s['id'], 'weight': w} for role, w in WEIGHTS.items() for s in p[role]
                       if s['id'] in engine.by_id and s['id'] not in held]
            body = {'profile': profile, 'settings': dict(DEFAULT_SETTINGS), 'list': []}
            # Which interest the engine scores each show for, and the interests heavy enough.
            _p, settings, positives, negatives, rated, candidates, _f = pages['new'].prepare(body)
            taste = library.Taste(pages['new'], positives, negatives, settings, candidates)
            groups = {engine.shows[i]['id']: k for i, k in taste.ranking.group.items()}
            total = sum(q['weight'] for q in positives)
            heavy = {k for k, interest in enumerate(taste.ranking.interests)
                     if sum(q['weight'] for q in interest) >= SHARE * total}
            report[p['key']] = {'file': name, 'held': sorted(held)}
            for lib in pages.values():
                lib.home(body)
            firsts = {'old': [], 'new': []}
            for n in range(TRIES):
                for which in (('old', 'new') if n % 2 == 0 else ('new', 'old')):
                    firsts[which].append(first_page(pages[which], body))
            rows = {}
            for which, lib in pages.items():
                t = time.perf_counter()
                paged = []
                rows[which] = whole(lib, body, paged)
                seconds = time.perf_counter() - t
                times[which] += [('first', statistics.median(firsts[which]), False)] + paged[1:]
                report[p['key']][which] = {**score(rows[which], held, groups, heavy, personal(modules[which], lib, body)),
                                           'seconds': round(seconds, 3)}
            report[p['key']]['today'] = cut(rows['new'][:len(rows['old'])]) == cut(rows['old'])
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    held_total = sum(len(r['held']) for r in report.values())
    print(f'{len(report)} personas, {held_total} held-out loves, {time.time() - started:.0f}s'
          f'{", stand-in rows past today" if args.stub_tiers else ""}\n')
    print(f'{"":<34}{"old":>10}{"new":>10}')
    for label, file in (('all personas', None), ('personas.json', FILES[0]), ('holdout.json', FILES[1])):
        chosen = [r for r in report.values() if file is None or r['file'] == file]
        held_n = sum(len(r['held']) for r in chosen)
        print(f'{label} ({len(chosen)} personas, {held_n} held-out loves)')
        for key, text in (('hits3', 'held-out loves in first 3 rows'), ('hits8', 'held-out loves in first 8 rows')):
            old, new = (sum(r[w][key] for r in chosen) for w in ('old', 'new'))
            print(f'  {text:<32}{old:>5} {old / held_n:>4.0%}{new:>5} {new / held_n:>4.0%}')
        old, new = (sum(r[w]['interests'] for r in chosen) for w in ('old', 'new'))
        print(f'  {"every 15% interest in first 8":<32}{old:>5} {old / len(chosen):>4.0%}{new:>5} {new / len(chosen):>4.0%}')
        for key, text in (('repeats', 'repeated cards per page'), ('rows', 'rows per page'), ('seconds', 'seconds per page')):
            old, new = (statistics.mean(r[w][key] for r in chosen) for w in ('old', 'new'))
            print(f'  {text:<32}{old:>10.2f}{new:>10.2f}')
    chosen = list(report.values())
    print(f'\nthe whole page, all personas ({held_total} held-out loves)')
    for w in ('old', 'new'):
        lengths = [r[w]['rows'] for r in chosen]
        print(f'  {w} rows per page: median {statistics.median(lengths):g}, fewest {min(lengths)}, most {max(lengths)}')
    print(f'  {"held-out loves found":<32}{"old":>10}{"new":>10}')
    for k, (lo, hi) in enumerate(DEPTHS):
        old, new = (sum(r[w]['depths'][k] for r in chosen) for w in ('old', 'new'))
        label = f'in rows {lo}-{hi}' if hi else f'in rows {lo} on'
        print(f'  {label:<32}{old:>5} {old / held_total:>4.0%}{new:>5} {new / held_total:>4.0%}')
    old, new = (sum(sum(r[w]['depths']) for r in chosen) for w in ('old', 'new'))
    print(f'  {"anywhere on the page":<32}{old:>5} {old / held_total:>4.0%}{new:>5} {new / held_total:>4.0%}')
    for key, text in (('repeats', 'repeated cards per page'), ('distinct', 'distinct shows per page')):
        old, new = (statistics.mean(r[w][key] for r in chosen) for w in ('old', 'new'))
        print(f'  {text:<32}{old:>10.1f}{new:>10.1f}')
    shares = []
    for w in ('old', 'new'):
        known = sum(r[w]['known'] for r in chosen)
        shares.append(f'{sum(r[w]["plain"] for r in chosen) / known:>10.0%}' if known else f'{"n/a":>10}')
    print(f'  {"rows that are not personal":<32}{"".join(shares)}')
    tiers = Counter()
    for r in chosen:
        tiers.update(r['new']['tiers'])
    print('  new rows per page by tier: ' + ', '.join(f'{t}: {n / len(chosen):.1f}' for t, n in sorted(tiers.items())))
    print(f'\ntime per request, in ms{"":<10}{"p50":>8}{"p95":>8}  (old, then new)')
    for label, pick in (('first page', lambda k, below: k == 'first'), ('asking for more', lambda k, below: k == 'next'),
                        ('  of them past today\'s rows', lambda k, below: k == 'next' and below)):
        for w in ('old', 'new'):
            values = [s for k, s, below in times[w] if pick(k, below)]
            if values:
                print(f'  {label + " (" + w + ")":<34}{1000 * statistics.median(values):>6.0f}{1000 * pct(values, .95):>8.0f}'
                      f'{"":>4}{len(values)} requests')
    first = {w: [s for k, s, _below in times[w] if k == 'first'] for w in ('old', 'new')}
    print(f'  first page, new against old: p50 {statistics.median(first["new"]) / statistics.median(first["old"]):.2f}, '
          f'p95 {pct(first["new"], .95) / pct(first["old"], .95):.2f}')
    same = sum(r['today'] for r in chosen)
    print(f'\ntoday\'s rows match --old {args.old} (keys, order and cards, as far as it goes): {same} of {len(chosen)}')


if __name__ == '__main__':
    main()
