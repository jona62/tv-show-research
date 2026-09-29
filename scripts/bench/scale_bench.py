"""How long a request takes, how much memory it holds and how many bytes it moves, for
lists of 60, 300, 1,000 and 3,000 rated shows (large_lists.py builds them).

For each size and each of a few viewers, it times:

  home         Couchside's first home request (library.Library.home): the hero and
               the first eight rows
  more         the request for the next six rows, as a browser asks at the foot of
               the page
  title        a title page (library.Library.title) for a show near the list's taste
  recommend    Next Watch's recommendations (engine.Engine.calculate)

each cold, with the engine's per-show caches emptied first, as for a list the server
has not seen lately, and warm, straight after. Memory is the peak Python allocation
during a cold request, from tracemalloc, in a separate pass since tracing slows
everything down. Bytes are the JSON request as a browser sends it, with the list
packed as ids and rating codes where the engine reads that (engine.CODES) and as a
list of objects before, and the JSON answer.

    .venv/bin/python scripts/bench/scale_bench.py
    .venv/bin/python scripts/bench/scale_bench.py --sizes 60,300 --viewers 3
    .venv/bin/python scripts/bench/scale_bench.py --code /tmp/old/couchside --timeout 120

--code runs another copy of Couchside's modules (library.py and the engine beside it),
such as an earlier revision's, against the same model. A request running past
--timeout seconds is stopped and reported as such.
"""
import argparse
import gc
import json
import signal
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZES = (60, 300, 1000, 3000)
KINDS = ('home', 'more', 'title', 'recommend')


class Late(Exception):
    pass


def alarm(_signum, _frame):
    raise Late()


def timed(fn, limit):
    """(seconds, answer) or (None, None) when it ran past limit seconds."""
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, limit)
    t = time.perf_counter()
    try:
        answer = fn()
    except Late:
        return None, None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return time.perf_counter() - t, answer


def cold(engine):
    """Empty the engine's per-show caches (closeness arrays, and closest shows from the
    neighbour index), as for a list the server has not seen lately."""
    for name in ('components', 'blended', '_row'):
        cached = getattr(type(engine), name, None)
        if hasattr(cached, 'cache_clear'):
            cached.cache_clear()


def size_of(value, codes=None):
    """A request's bytes as the browser sends it: its list packed when the engine reads
    packed lists (codes, engine.CODES)."""
    if codes and isinstance(value, dict) and isinstance(value.get('profile'), list):
        code = {w: c for c, w in codes.items()}
        value = {**value, 'profile': {'ids': [p['id'] for p in value['profile']],
                                      'weights': ''.join(code[p['weight']] for p in value['profile'])}}
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--code', default=str(ROOT / 'couchside'), help='folder with library.py and the engine')
    parser.add_argument('--model', default=str(ROOT / 'model'))
    parser.add_argument('--sizes', default=','.join(map(str, SIZES)))
    parser.add_argument('--viewers', type=int, default=6, help='viewers per size')
    parser.add_argument('--memory', type=int, default=2, help='viewers per size traced for memory (0 for none)')
    parser.add_argument('--timeout', type=float, default=300.0, help='seconds before a request is given up')
    parser.add_argument('--kinds', default=','.join(KINDS))
    parser.add_argument('--out', help='write every measurement here as JSON')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.code).resolve()))
    sys.path.insert(0, str(ROOT / 'scripts' / 'bench'))
    import library
    import engine as module
    from engine import Engine, DEFAULT_SETTINGS
    from large_lists import viewers, Relations
    codes = getattr(module, 'CODES', None)
    t = time.perf_counter()
    engine = Engine(args.model)
    lib = library.Library(engine, ROOT / 'couchside' / 'art.bin.gz')
    # As the servers do once loaded: the collector leaves the model's objects alone.
    gc.collect()
    gc.freeze()
    print(f'engine and library loaded in {time.perf_counter() - t:.1f}s from {args.code}', file=sys.stderr)
    relations = Relations(engine)
    kinds = [k for k in args.kinds.split(',') if k]
    report = {}
    for size in map(int, args.sizes.split(',')):
        found = {k: {'cold': [], 'warm': [], 'bytes_in': [], 'bytes_out': [], 'memory': []} for k in kinds}
        people = viewers(engine, 'personas.json', size=size, count=args.viewers, relations=relations)
        for n, v in enumerate(people):
            body = {'profile': v.profile, 'settings': dict(DEFAULT_SETTINGS), 'list': [], 'lang': ['en-GB']}
            steps = {}
            steps['home'] = lambda: lib.home(body)

            def more():
                first = lib.home(body)
                shown = [{'key': r['key'], 'ids': [c['id'] for c in r['items'][:6]], **({'tier': r['tier']} if 'tier' in r else {})}
                         for r in first['rows']]
                return {**body, 'shown': shown, 'count': 6}
            titles = [p['id'] for p in v.profile if p['weight'] > 0][-1:]
            steps['title'] = lambda: lib.title({**body, 'id': v.held[0] if v.held else titles[0]})
            steps['recommend'] = lambda: engine.calculate({'profile': v.profile, 'settings': dict(DEFAULT_SETTINGS)})
            for kind in kinds:
                if kind == 'more':
                    cold(engine)
                    _s, ask = timed(more, args.timeout)
                    if ask is None:
                        found[kind]['cold'].append(None)
                        continue
                    run = lambda ask=ask: lib.home(ask)
                    request = ask
                else:
                    run = steps[kind]
                    request = body if kind != 'title' else {**body, 'id': 0}
                    if kind == 'recommend':
                        request = {'profile': v.profile, 'settings': dict(DEFAULT_SETTINGS)}
                cold(engine)
                seconds, answer = timed(run, args.timeout)
                found[kind]['cold'].append(seconds)
                if answer is None:
                    print(f'  {size} {v.key} {kind}: over {args.timeout:.0f}s', file=sys.stderr)
                    continue
                warm, _answer = timed(run, args.timeout)
                found[kind]['warm'].append(warm)
                found[kind]['bytes_in'].append(size_of(request, codes))
                found[kind]['bytes_out'].append(size_of(answer))
                if n < args.memory:
                    cold(engine)
                    tracemalloc.start()
                    try:
                        timed(run, args.timeout * 4)
                        found[kind]['memory'].append(tracemalloc.get_traced_memory()[1])
                    finally:
                        tracemalloc.stop()
                print(f'  {size} {v.key} {kind}: cold {seconds * 1000:.0f} ms, warm {warm * 1000:.0f} ms', file=sys.stderr)
        report[size] = found
    print(f'\n{"":<22}{"cold p50":>10}{"p95":>8}{"warm p50":>10}{"p95":>8}{"memory":>10}{"request":>10}{"answer":>10}')
    for size, found in report.items():
        print(f'{size:,} rated shows')
        for kind, rows in found.items():
            done = [s for s in rows['cold'] if s is not None]
            late = len(rows['cold']) - len(done)
            ms = lambda values, q: f'{1000 * pct(values, q):.0f}' if values else '-'
            memory = f'{max(rows["memory"]) / 1e6:.0f} MB' if rows['memory'] else '-'
            kb = lambda values: f'{statistics.median(values) / 1000:.1f} KB' if values else '-'
            line = (f'  {kind:<20}{ms(done, .5):>10}{ms(done, .95):>8}{ms(rows["warm"], .5):>10}{ms(rows["warm"], .95):>8}'
                    f'{memory:>10}{kb(rows["bytes_in"]):>10}{kb(rows["bytes_out"]):>10}')
            if late:
                line += f'  ({late} of {len(rows["cold"])} over {args.timeout:.0f}s)'
            print(line)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
