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

The earlier page is couchside/library.py as it was at a git revision (--old, by default
the commit before the home page was rebuilt), run beside the current engine.

    .venv/bin/python scripts/bench/home_bench.py
    .venv/bin/python scripts/bench/home_bench.py --old e525e35 --out /tmp/home.json
"""
import argparse
import json
import random
import statistics
import subprocess
import sys
import time
import types
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUCHSIDE = ROOT / 'couchside'
FILES = ('personas.json', 'holdout.json')
WEIGHTS = {'loves': 1, 'likes': .7, 'dislikes': -1}
HELD = 0.2          # share of loves held out
SHARE = 0.15        # an interest this heavy should have one of the first eight rows
GLANCE = 6


def old_library(rev):
    """couchside/library.py at a revision, as a module beside the current engine."""
    source = subprocess.run(['git', 'show', f'{rev}:couchside/library.py'], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout
    module = types.ModuleType('library_old')
    module.__file__ = str(COUCHSIDE / 'library_old.py')
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def whole(lib, body):
    """Every row of a page: the new page is asked for eight rows and then six at a time;
    an earlier page without paging answers everything at once."""
    answer = lib.home(body)
    rows = list(answer['rows'])
    while answer.get('more'):
        shown = [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:GLANCE]]} for r in rows]
        answer = lib.home({**body, 'shown': shown})
        rows += answer['rows']
    return [r for r in rows if r['kind'] != 'list']


def score(rows, held, groups, heavy):
    first = lambda n: {c['id'] for r in rows[:n] for c in r['items'][:GLANCE]}
    cards = [c['id'] for r in rows for c in r['items']]
    given = set()
    for r in rows[:8]:
        owners = Counter(groups.get(c['id']) for c in r['items'][:GLANCE])
        owner, n = owners.most_common(1)[0] if owners else (None, 0)
        if owner is not None and n >= len(r['items'][:GLANCE]) / 2:
            given.add(owner)
    return {'rows': len(rows), 'hits3': len(held & first(3)), 'hits8': len(held & first(8)),
            'interests': not heavy or heavy <= given, 'repeats': len(cards) - len(set(cards)),
            'titles': [r['title'] for r in rows]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--old', default='e525e35', help='git revision of the earlier library.py')
    parser.add_argument('--out', help='write every persona\'s numbers here as JSON')
    args = parser.parse_args()
    sys.path.insert(0, str(COUCHSIDE))
    import library
    from engine import Engine, DEFAULT_SETTINGS
    engine = Engine(ROOT / 'model')
    art = COUCHSIDE / 'art.bin.gz'
    pages = {'old': old_library(args.old).Library(engine, art), 'new': library.Library(engine, art)}
    report, started = {}, time.time()
    for name in FILES:
        personas = json.loads((ROOT / 'scripts' / 'bench' / name).read_text())['personas']
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
            for which, lib in pages.items():
                t = time.perf_counter()
                rows = whole(lib, body)
                report[p['key']][which] = {**score(rows, held, groups, heavy), 'seconds': round(time.perf_counter() - t, 3)}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    held_total = sum(len(r['held']) for r in report.values())
    print(f'{len(report)} personas, {held_total} held-out loves, {time.time() - started:.0f}s\n')
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


if __name__ == '__main__':
    main()
