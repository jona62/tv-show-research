"""Whether more ratings help: long lists against the same lists cut to their 60 most
recent ratings, on loves held out of both.

Each viewer is several bench personas united and extended to 300, 1,000 or 3,000
ratings with what someone of that taste plausibly also rated (large_lists.py). A third
of each persona's loves are held out before anything is drawn, so they are never on the
list, and each is ranked twice by the engine as the apps call it:

  full      the whole list, which the engine ranks from each show's closest shows
            (engine.Wide) past DENSE_MAX ratings
  recent    the list's 60 most recent ratings only, which the engine ranks as it ranks
            any list that short (engine.Ranking), as the apps did before lists could
            be longer

under the engine's default settings. A held-out love the settings filter out is left out
of both (large_lists.py only holds out loves the default pool holds). Reported per size
and persona file: the share of held-out loves ranked in the top 10, 24 and 100, the mean
reciprocal rank, the median rank, and how many had no score at all (ranked last).

    .venv/bin/python scripts/bench/large_bench.py
    .venv/bin/python scripts/bench/large_bench.py --sizes 300,1000 --viewers 8
    .venv/bin/python scripts/bench/large_bench.py --out /tmp/large.json --compare scripts/bench/large-baseline.json

personas.json is what the long-list constants were chosen on; holdout.json is the
honest check, never tuned on. The run is deterministic for a given engine and model.
"""
import argparse
import ast
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZES = (300, 1000, 3000)
FILES = ('personas.json', 'holdout.json')
RECENT = 60
HIT_AT = (10, 24, 100)


def ranks(engine, module, profile, targets, settings, pool):
    """Each target's place in the engine's full ordering for the profile, as calculate()
    orders it, by score and then show id, and whether it scored at all: a target scored
    zero ranks last."""
    parsed, settings, _chosen = engine.validate({'profile': profile, 'settings': settings})
    rated = {engine.by_id[p['id']] for p in parsed}
    parsed = engine.focus(parsed)
    positives = [p for p in parsed if p['weight'] > 0]
    negatives = [p for p in parsed if p['weight'] < 0]
    candidates = [i for i in pool if i not in rated]
    scores = engine.rank(candidates, positives, negatives, module.Closeness(engine, settings), settings)
    ordered = sorted((i for i in candidates if scores[i] > 0), key=lambda i: (-scores[i], engine.shows[i]['id']))
    place = {i: n + 1 for n, i in enumerate(ordered)}
    return [(place.get(engine.by_id[t], len(candidates)), engine.by_id[t] in place) for t in targets]


def summarize(found):
    n = len(found)
    if not n:
        return {'n': 0}
    places = [r for r, _scored in found]
    return {'n': n, **{f'hr{k}': round(sum(r <= k for r in places) / n, 4) for k in HIT_AT},
            'mrr': round(sum(1 / r for r in places) / n, 4), 'median': statistics.median_low(places),
            'unscored': sum(not scored for _r, scored in found)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--app', default=str(ROOT / 'app'))
    parser.add_argument('--model', default=str(ROOT / 'model'))
    parser.add_argument('--sizes', default=','.join(map(str, SIZES)))
    parser.add_argument('--files', default=','.join(FILES))
    parser.add_argument('--viewers', type=int, default=16, help='viewers per size and file')
    parser.add_argument('--out', help='write the report here as JSON')
    parser.add_argument('--compare', help='an earlier report to print deltas against')
    parser.add_argument('--set', action='append', default=[], metavar='NAME=VALUE',
                        help='try another value of an engine constant, such as WIDE_HUB=0')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.app).resolve()))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import engine as module
    for item in args.set:
        name, _eq, value = item.partition('=')
        if not hasattr(module, name):
            sys.exit(f'engine.py has no {name}')
        setattr(module, name, ast.literal_eval(value))
    from large_lists import Relations, viewers
    started = time.time()
    engine = module.Engine(args.model)
    if not engine.neighbours:
        sys.exit('The model has no neighbour index: build it with scripts/build_neighbours.py.')
    settings = dict(module.DEFAULT_SETTINGS)
    pool = [i for i in range(engine.n) if engine.eligible(i, settings)]
    relations = Relations(engine)
    base = json.loads(Path(args.compare).read_text()) if args.compare else None
    report = {'recent': RECENT, 'viewers': args.viewers, 'model': engine.version, 'set': args.set, 'results': {}}
    for name in args.files.split(','):
        for size in map(int, args.sizes.split(',')):
            found = {'full': [], 'recent': []}
            for v in viewers(engine, name, size=size, count=args.viewers, relations=relations):
                if not v.held:
                    continue
                found['full'] += ranks(engine, module, v.profile, v.held, settings, pool)
                found['recent'] += ranks(engine, module, v.recent(RECENT), v.held, settings, pool)
                engine.components.cache_clear()
                engine.blended.cache_clear()
            report['results'][f'{name} {size}'] = {kind: summarize(r) for kind, r in found.items()}
            print(f'{name} {size} done, {time.time() - started:.0f}s', file=sys.stderr)
    print(f'{"":<24}{"":>8}{"HR@10":>8}{"HR@24":>8}{"HR@100":>8}{"MRR":>8}{"median":>8}{"unscored":>10}')
    for key, block in report['results'].items():
        for kind, s in block.items():
            line = (f'{key if kind == "full" else "":<24}{kind:>8}{s["hr10"]:>8.1%}{s["hr24"]:>8.1%}{s["hr100"]:>8.1%}'
                    f'{s["mrr"]:>8.3f}{s["median"]:>8,}{s["unscored"]:>10}')
            then = (base or {}).get('results', {}).get(key, {}).get(kind)
            if then:
                line += (f'   vs earlier: HR@24 {100 * (s["hr24"] - then["hr24"]):+.1f}pt, '
                         f'MRR {s["mrr"] - then["mrr"]:+.3f}')
            print(line)
        print(f'{"":<24}{"":>8}  {block["full"]["n"]} held-out loves')
    print(f'\n{time.time() - started:.0f}s', file=sys.stderr)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
