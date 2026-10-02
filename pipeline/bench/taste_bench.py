"""Offline taste benchmark for the Next Watch recommender (app/backend/recommendation/engine.py).

Replays the viewer personas in personas.json through the engine and measures how
well the ranking recovers shows each persona is known to like, so a ranking change
can be judged by numbers rather than by eyeballing a few lists:

  leave-one-out  each loved or liked show is held out in turn; the profile is every
                 other rating (loves 1, likes 0.7, dislikes -1) and the held-out
                 show's rank is read from the full ordering, not just the top 24
  few-shot       three seeded-random loved or liked shows are the whole profile
                 (five draws per persona) and the other positives are the targets
  dislikes       a held-out dislike should stay out of the top 24, and a profile of
                 loves and likes alone should not surface the persona's dislikes

each under the product defaults and under a wide pool with no popularity or year
floor. Targets the filters remove count as misses and are reported.

    .venv/bin/python pipeline/bench/taste_bench.py
    .venv/bin/python pipeline/bench/taste_bench.py --out /tmp/run.json \\
        --compare pipeline/bench/baseline.json
    .venv/bin/python pipeline/bench/taste_bench.py --find "the office"

Everything is deterministic for a given engine, model and persona file; only the
runtime varies. README.md beside this file explains how to read the numbers.
"""
import argparse
import hashlib
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from runtime import module as runtime_module, source_path

ROOT = Path(__file__).resolve().parents[2]
BENCH_VERSION = 1
SEED = 20260927
TOP = 24                      # what the product shows; calculate() returns this many
HIT_AT = (10, 24, 100)
FEW_SHOT_SIZE = 3
FEW_SHOT_DRAWS = 5
WEIGHTS = {'loves': 1, 'likes': .7, 'dislikes': -1}
PERSONA_SIZE = (8, 15)
MIN_POSITIVES = FEW_SHOT_SIZE + 2
# Each protocol runs on the engine's own DEFAULT_SETTINGS with only these keys
# overridden, so a new settings key or a changed default flows straight through.
SETTINGS = {
    'default': {},
    'wide': {'known_min': 0, 'year_min': 1900},
}


def fail(lines):
    print('\n'.join(['taste_bench: cannot run'] + [f'  {line}' for line in lines]), file=sys.stderr)
    raise SystemExit(2)


def shown(path):
    """A path relative to the repository when it sits inside it, so reports carry
    no machine-specific prefix."""
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


# --------------------------------------------------------------------- engine

def load_engine(app_dir, model_dir):
    """Load a current or historical app's engine through its public constructor."""
    app_dir, model_dir = Path(app_dir).resolve(), Path(model_dir).resolve()
    try:
        module = runtime_module(app_dir, 'engine')
    except FileNotFoundError as error:
        fail([str(error)])
    return module, module.Engine(model_dir)


def recommend(engine, profile, settings):
    """Public API: calculate()'s answer, and the ids it picks, best first, cut to the top 24."""
    result = engine.calculate({'profile': profile, 'settings': settings})
    return result, [p['id'] for p in result['picks']][:TOP]


class Ranker:
    """ADAPTER: the one place that reaches past Engine.calculate().

    calculate() returns only the top 24, and the leave-one-out and few-shot
    protocols need a held-out show's rank in the full ordering. This mirrors
    calculate() step by step with the engine's own methods: validate the request,
    take the eligible pool minus every rated show, blend one affinity array per
    rated show, rank, and order by (-score, show id) keeping positive scores.
    Affinities are cached per show, so the rounds over one persona reuse them.
    Catalog indices never leave this class and Ranking; the rest speaks show ids.

    When the engine's scoring changes shape, update these two classes and nothing
    else. run_persona() compares Ranker's top 24 with calculate() for every persona
    and stops the run on any difference, so drift cannot pass silently.
    """

    def __init__(self, engine, module, settings):
        self.engine = engine
        _, self.settings, _ = engine.validate({'profile': [], 'settings': settings})
        kind = self.settings['type']
        self.formats = None if kind == 'all' else set(module.FORMAT_GROUPS.get(kind, (kind,)))
        self.pool = [i for i in range(engine.n) if engine.eligible(i, self.settings, self.formats)]
        self.pool_array = np.array(self.pool, dtype=np.int64)
        self.ids = np.array([s['id'] for s in engine.shows], dtype=np.int64)
        self.affinity = {}

    def forget(self):
        """Drop cached affinities between personas to bound memory."""
        self.affinity.clear()

    def rank(self, profile):
        engine = self.engine
        parsed, settings, _ = engine.validate({'profile': profile, 'settings': self.settings})
        positives = [p for p in parsed if p['weight'] > 0]
        negatives = [p for p in parsed if p['weight'] < 0]
        rated = {engine.by_id[p['id']] for p in parsed}
        candidates = [i for i in self.pool if i not in rated]
        for p in positives + negatives:
            if p['id'] not in self.affinity:
                self.affinity[p['id']] = engine.blend(engine.by_id[p['id']], settings)
        scores = engine.rank(candidates, positives, negatives, self.affinity, settings)
        kept = self.pool_array[~np.isin(self.pool_array, list(rated))]
        return Ranking(np.frombuffer(scores, dtype=np.float32), kept, self.ids, engine.by_id)

    def reason(self, show_id):
        """Which filter keeps a show out of the pool, for the report."""
        index = self.engine.by_id[show_id]
        relaxed = {'known_min': 0, 'year_min': 1900, 'runtime_min': 0, 'rating_min': 0}
        for key, value in relaxed.items():
            if self.settings.get(key, value) != value and self.engine.eligible(
                    index, {**self.settings, key: value}, self.formats):
                return key
        if self.engine.eligible(index, {**self.settings, **relaxed}, self.formats):
            return 'several'
        return 'never eligible'


class Ranking:
    """One scored pool, ordered by calculate()'s key: (-score, show id)."""

    def __init__(self, scores, candidates, ids, by_id):
        self.scores, self.ids, self.by_id = scores, ids, by_id
        self.size = len(candidates)
        self.member = np.zeros(len(scores), dtype=bool)
        self.member[candidates] = True
        self.cand_scores = scores[candidates]
        self.cand_ids = ids[candidates]

    def place(self, show_id):
        """(rank, status). Status is 'filtered' when the settings removed the show
        (rank None), 'unscored' when it is a candidate scored zero, which the
        product never shows (it ranks last), and 'ranked' otherwise."""
        index = self.by_id[show_id]
        if not self.member[index]:
            return None, 'filtered'
        score = self.scores[index]
        if score <= 0:
            return self.size, 'unscored'
        better = np.count_nonzero(self.cand_scores > score)
        tied = np.count_nonzero((self.cand_scores == score) & (self.cand_ids < show_id))
        return int(better + tied) + 1, 'ranked'

    def top(self, k=TOP):
        keep = self.cand_scores > 0
        order = np.lexsort((self.cand_ids[keep], -self.cand_scores[keep]))[:k]
        return [int(i) for i in self.cand_ids[keep][order]]


# ------------------------------------------------------------------- personas

def load_personas(path, engine, only=()):
    """Read the persona file and hold every entry to the catalog: the id must exist
    and carry the recorded name and premiere year. Any problem stops the run."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        fail([f'{path}: {e}'])
    personas = doc.get('personas') if isinstance(doc, dict) else doc
    if not isinstance(personas, list) or not personas:
        fail([f'{path}: expected a list of personas'])
    problems, keys = [], set()
    for n, p in enumerate(personas):
        where = f"persona {n + 1} ({p.get('key', '?') if isinstance(p, dict) else '?'})"
        if not isinstance(p, dict) or not all(isinstance(p.get(k), str) and p[k] for k in ('key', 'label')):
            problems.append(f'{where}: needs a key and a label')
            continue
        if p['key'] in keys:
            problems.append(f'{where}: duplicate key')
        keys.add(p['key'])
        ids = []
        for role in WEIGHTS:
            entries = p.get(role, [])
            if not isinstance(entries, list):
                problems.append(f'{where}: {role} must be a list')
                continue
            for e in entries:
                if not isinstance(e, dict) or type(e.get('id')) is not int:
                    problems.append(f'{where}: {role} entry {e!r} needs an integer id')
                    continue
                ids.append(e['id'])
                card = next(iter(engine.cards([e['id']])), None)
                if card is None:
                    problems.append(f"{where}: id {e['id']} ({e.get('name')}) is not in the catalog")
                elif card['name'] != e.get('name') or card['year'] != e.get('year'):
                    problems.append(f"{where}: id {e['id']} is recorded as {e.get('name')!r} ({e.get('year')}) "
                                    f"but the catalog holds {card['name']!r} ({card['year']})")
        if len(set(ids)) != len(ids):
            problems.append(f'{where}: a show appears more than once')
        if not PERSONA_SIZE[0] <= len(ids) <= PERSONA_SIZE[1]:
            problems.append(f'{where}: {len(ids)} shows, expected {PERSONA_SIZE[0]} to {PERSONA_SIZE[1]}')
        if len(p.get('loves', [])) + len(p.get('likes', [])) < MIN_POSITIVES:
            problems.append(f'{where}: needs at least {MIN_POSITIVES} loved or liked shows')
    unknown = set(only) - keys
    if unknown:
        problems.append(f"unknown persona keys: {', '.join(sorted(unknown))}")
    if problems:
        fail(problems)
    return [p for p in personas if not only or p['key'] in only]


def ratings(persona):
    """The persona as rated shows: loves, then likes, then dislikes, in file order."""
    return [{'id': e['id'], 'weight': WEIGHTS[role], 'name': e['name']}
            for role in WEIGHTS for e in persona.get(role, [])]


def as_profile(rows):
    return [{'id': r['id'], 'weight': r['weight']} for r in rows]


def few_shot_draws(persona_key, count, seed):
    """Distinct three-show subsets of the positives, seeded per persona so adding or
    reordering personas never changes another persona's draws."""
    rng = random.Random(f'{seed}:{persona_key}')
    draws = []
    while len(draws) < min(FEW_SHOT_DRAWS, math.comb(count, FEW_SHOT_SIZE)):
        pick = tuple(sorted(rng.sample(range(count), FEW_SHOT_SIZE)))
        if pick not in draws:
            draws.append(pick)
    return draws


# -------------------------------------------------------------------- metrics

def summarize(ranks):
    """Hit rates, MRR and the lower median rank over targets. None marks a target
    the filters removed: it is a miss and sorts after every ranked target."""
    n = len(ranks)
    if not n:
        return {'n': 0, 'filtered': 0, **{f'hr{k}': None for k in HIT_AT}, 'mrr': None, 'median_rank': None}
    ranked = [r for r in ranks if r is not None]
    out = {'n': n, 'filtered': n - len(ranked)}
    for k in HIT_AT:
        out[f'hr{k}'] = round(sum(r <= k for r in ranked) / n, 4)
    out['mrr'] = round(sum(1 / r for r in ranked) / n, 4)
    median = statistics.median_low([r if r is not None else math.inf for r in ranks])
    out['median_rank'] = None if median == math.inf else median
    return out


def run_persona(engine, ranker, persona, settings, seed, allow_drift):
    """Every protocol for one persona under one setting."""
    rows = ratings(persona)
    positives = [r for r in rows if r['weight'] > 0]
    dislikes = [r for r in rows if r['weight'] < 0]
    drift = []

    def checked_picks(profile):
        """calculate()'s picks for the full profile, checked against the adapter for
        the same profile: the same top 24 in the same order from a pool of the same
        size. One check per persona and setting."""
        result, picks = recommend(engine, profile, settings)
        ranking = ranker.rank(profile)
        mine, pool = ranking.top(TOP), result.get('candidate_count', ranking.size)
        if mine != picks or pool != ranking.size:
            drift.append('full profile')
            message = (f"adapter drift for {persona['key']}: calculate() picked {picks[:4]}... from {pool} "
                       f"candidates, Ranker ordered {mine[:4]}... from {ranking.size}; "
                       f"update Ranker to mirror Engine.calculate()")
            if not allow_drift:
                fail([message])
            print(f'warning: {message}', file=sys.stderr)
        return picks

    def target(row, ranking):
        rank, status = ranking.place(row['id'])
        entry = {'id': row['id'], 'name': row['name'], 'weight': row['weight'], 'rank': rank}
        if status == 'filtered':
            entry['filtered'] = ranker.reason(row['id'])
        elif status == 'unscored':
            entry['unscored'] = True
        return entry

    def without(row):
        return as_profile([r for r in rows if r is not row])

    # Leave-one-out: every other rating is the profile.
    loo = [target(row, ranker.rank(without(row))) for row in positives]

    # Few-shot: three positives are the whole profile; the other positives are targets.
    draws = []
    for draw in few_shot_draws(persona['key'], len(positives), seed):
        ranking = ranker.rank(as_profile([positives[i] for i in draw]))
        targets = [row['id'] for i, row in enumerate(positives) if i not in draw]
        draws.append({'profile': [positives[i]['id'] for i in draw], 'targets': targets,
                      'ranks': [ranking.place(t)[0] for t in targets]})

    # Dislikes: a held-out dislike should stay out of the top 24, and loves and
    # likes alone should not pull the persona's dislikes into it.
    held = [target(row, ranker.rank(without(row))) for row in dislikes]
    liked_only = recommend(engine, as_profile(positives), settings)[1] if dislikes else []
    surfaced = [r['id'] for r in dislikes if r['id'] in liked_only]

    picks = checked_picks(as_profile(rows))
    cards = engine.cards(picks)
    known = [c['known'] for c in cards if c.get('known') is not None]
    return {
        'loo': {**summarize([t['rank'] for t in loo]), 'unscored': sum('unscored' in t for t in loo),
                'targets': loo},
        'few_shot': {**summarize([rank for d in draws for rank in d['ranks']]), 'draws': draws},
        'dislikes': {
            'held_out': len(held),
            'held_out_top24': sum(t['rank'] is not None and t['rank'] <= TOP for t in held),
            'targets': held,
            'liked_only_top24': len(surfaced),
            'liked_only_surfaced': surfaced,
        },
        'picks': [[c['id'], c['name']] for c in cards],
        'pick_popularity': round(statistics.fmean(known), 2) if known else None,
        'adapter_drift': drift,
    }


def aggregate(results, pool, runtime):
    """Targets pooled across personas, so each counts once, plus persona means that
    weigh every viewer equally."""
    people = list(results.values())
    loo = summarize([t['rank'] for r in people for t in r['loo']['targets']])
    few = summarize([rank for r in people for d in r['few_shot']['draws'] for rank in d['ranks']])
    held = [t['rank'] for r in people for t in r['dislikes']['targets']]
    held_out = sum(r['dislikes']['held_out'] for r in people)
    held_top = sum(r['dislikes']['held_out_top24'] for r in people)
    surfaced = sum(r['dislikes']['liked_only_top24'] for r in people)
    picks = [p[0] for r in people for p in r['picks']]
    pops = [r['pick_popularity'] for r in people if r['pick_popularity'] is not None]
    filtered_by = {}
    for r in people:
        for t in r['loo']['targets']:
            if 'filtered' in t:
                filtered_by[t['filtered']] = filtered_by.get(t['filtered'], 0) + 1
    held_median = statistics.median_low([r if r is not None else math.inf for r in held]) if held else None
    return {
        'pool': pool,
        'loo': {
            **loo,
            'unscored': sum(r['loo']['unscored'] for r in people),
            'filtered_by': dict(sorted(filtered_by.items())),
            'persona_hr24': round(statistics.fmean(r['loo']['hr24'] for r in people), 4),
            'persona_mrr': round(statistics.fmean(r['loo']['mrr'] for r in people), 4),
        },
        'few_shot': {**few, 'persona_hr24': round(statistics.fmean(r['few_shot']['hr24'] for r in people), 4)},
        'dislikes': {
            'personas': sum(1 for r in people if r['dislikes']['held_out']),
            'held_out': held_out,
            'held_out_top24': held_top,
            'held_out_top24_rate': round(held_top / held_out, 4) if held_out else None,
            'held_out_median_rank': None if held_median in (None, math.inf) else held_median,
            'liked_only_top24': surfaced,
            'liked_only_top24_rate': round(surfaced / held_out, 4) if held_out else None,
        },
        'picks': {
            'distinct': len(set(picks)),
            'slots': len(picks),
            'share_of_slots': round(len(set(picks)) / len(picks), 4) if picks else None,
            'mean_popularity': round(statistics.fmean(pops), 2) if pops else None,
        },
        'adapter_drift': sum(len(r['adapter_drift']) for r in people),
        'runtime_s': round(runtime, 1),
    }


# --------------------------------------------------------------------- output

ROWS = [
    # label, path in a setting's summary, format, which way is better
    ('pool (eligible shows)', ('pool',), 'int', None),
    ('leave-one-out targets', ('loo', 'n'), 'int', None),
    ('  filtered out', ('loo', 'filtered'), 'int', 'down'),
    ('  HR@10', ('loo', 'hr10'), 'pct', 'up'),
    ('  HR@24', ('loo', 'hr24'), 'pct', 'up'),
    ('  HR@100', ('loo', 'hr100'), 'pct', 'up'),
    ('  MRR', ('loo', 'mrr'), 'mrr', 'up'),
    ('  median rank', ('loo', 'median_rank'), 'rank', 'down'),
    ('  HR@24, persona mean', ('loo', 'persona_hr24'), 'pct', 'up'),
    ('few-shot targets', ('few_shot', 'n'), 'int', None),
    ('  filtered out', ('few_shot', 'filtered'), 'int', 'down'),
    ('  HR@10', ('few_shot', 'hr10'), 'pct', 'up'),
    ('  HR@24', ('few_shot', 'hr24'), 'pct', 'up'),
    ('  HR@100', ('few_shot', 'hr100'), 'pct', 'up'),
    ('  MRR', ('few_shot', 'mrr'), 'mrr', 'up'),
    ('  median rank', ('few_shot', 'median_rank'), 'rank', 'down'),
    ('held-out dislikes', ('dislikes', 'held_out'), 'int', None),
    ('  landed in the top 24', ('dislikes', 'held_out_top24_rate'), 'pct', 'down'),
    ('  median rank', ('dislikes', 'held_out_median_rank'), 'rank', 'up'),
    ('  in top 24 of loves and likes alone', ('dislikes', 'liked_only_top24_rate'), 'pct', 'down'),
    ('distinct picks across personas', ('picks', 'distinct'), 'int', 'up'),
    ('mean popularity of the top 24', ('picks', 'mean_popularity'), 'num', None),
    ('compute time (s), summed over workers', ('runtime_s',), 'num', None),
]


def dig(d, path):
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return None
        d = d[key]
    return d


def fmt(value, kind):
    if value is None:
        return 'n/a'
    return {'int': f'{value:,}', 'pct': f'{value:.1%}', 'mrr': f'{value:.3f}',
            'rank': f'{value:,}', 'num': f'{value:.1f}'}[kind]


def fmt_delta(now, then, kind, better):
    if now is None or then is None:
        return ''
    delta = now - then
    if abs(delta) < 1e-9:
        return '='
    text = {'pct': f'{delta * 100:+.1f}pt', 'mrr': f'{delta:+.3f}', 'num': f'{delta:+.1f}'}.get(kind, f'{delta:+,}')
    if better:
        text += ' better' if (delta > 0) == (better == 'up') else ' worse'
    return text


def to_json(value, depth=0):
    """Indented JSON that keeps short objects and lists on one line, so a report
    stays small enough to commit and diffs by target rather than by bracket."""
    flat = json.dumps(value, ensure_ascii=False)
    scalars = isinstance(value, list) and not any(isinstance(v, (dict, list)) for v in value)
    if not isinstance(value, (dict, list)) or len(flat) <= 120 or not value or scalars:
        return flat
    pad, inner = ' ' * depth, ' ' * (depth + 1)
    if isinstance(value, dict):
        body = ',\n'.join(f'{inner}{json.dumps(k, ensure_ascii=False)}: {to_json(v, depth + 1)}'
                          for k, v in value.items())
        return '{\n' + body + '\n' + pad + '}'
    return '[\n' + ',\n'.join(inner + to_json(v, depth + 1) for v in value) + '\n' + pad + ']'


def print_summary(report, base=None):
    names = list(report['settings'])
    run, people = report['run'], report['personas']
    print(f"Taste bench v{report['bench']['version']}: {people['count']} personas, {people['ratings']} ratings; "
          f"model {run['model_version']} ({run['catalog_shows']:,} shows); engine {run['engine_sha256']}")
    if base:
        print(f"Compared with {base['_path']}: model {base['run'].get('model_version')}, "
              f"engine {base['run'].get('engine_sha256')}, git {base['run'].get('git')}")
        if base['personas'].get('sha256') != people['sha256']:
            print('  note: the persona file differs from that run, so deltas mix engine and test changes')
        mine = {k for s in report['settings'].values() for k in s['personas']}
        theirs = {k for s in base['settings'].values() for k in s.get('personas', {})}
        if mine != theirs:
            print(f'  note: this run covers {len(mine)} personas and that one {len(theirs)}, '
                  f'{len(mine & theirs)} in common, so the totals are not like for like')
        if base['bench'] != report['bench']:
            print('  note: the protocol parameters differ from that run')
    width = 38
    print(f"{'':<{width}}" + ''.join(f'{n:>12}' + (f"{'vs earlier':>18}" if base else '') for n in names))
    for label, path, kind, better in ROWS:
        cells = []
        for n in names:
            now = dig(report['settings'][n], ('summary',) + path)
            cells.append(f'{fmt(now, kind):>12}')
            if base:
                then = dig(base['settings'].get(n, {}), ('summary',) + path)
                cells.append(f'{fmt_delta(now, then, kind, better):>18}')
        print(f'{label:<{width}}' + ''.join(cells))
    for n in names:
        s = report['settings'][n]['summary']
        if s['loo']['filtered_by']:
            print(f"{n}: leave-one-out targets filtered by "
                  + ', '.join(f'{k} {v}' for k, v in s['loo']['filtered_by'].items()))
        if s['adapter_drift']:
            print(f"{n}: the adapter disagreed with calculate() {s['adapter_drift']} times")


def print_personas(report, limit, base=None):
    for n, block in report['settings'].items():
        rows = sorted(block['personas'].items(), key=lambda kv: (kv[1]['loo']['mrr'], kv[1]['loo']['hr24'], kv[0]))
        shown_rows = rows if limit is None else rows[:limit]
        title = 'every persona' if limit is None else f'weakest {len(shown_rows)} personas'
        print(f'\n{title} by leave-one-out MRR, {n}')
        print(f"  {'persona':<24}{'n':>3}{'filt':>5}{'HR@10':>7}{'HR@24':>7}{'MRR':>7}{'median':>8}"
              f"{'few HR@24':>10}{'dislikes':>10}" + (f"{'MRR vs earlier':>20}" if base else ''))
        for key, r in shown_rows:
            d = r['dislikes']
            dis = f"{d['held_out_top24']}/{d['held_out']}, {d['liked_only_top24']}" if d['held_out'] else '-'
            line = (f"  {key:<24}{r['loo']['n']:>3}{r['loo']['filtered']:>5}{r['loo']['hr10']:>7.0%}"
                    f"{r['loo']['hr24']:>7.0%}{r['loo']['mrr']:>7.3f}{fmt(r['loo']['median_rank'], 'rank'):>8}"
                    f"{r['few_shot']['hr24']:>10.0%}{dis:>10}")
            if base:
                then = dig(base['settings'].get(n, {}), ('personas', key, 'loo', 'mrr'))
                line += f"{fmt_delta(r['loo']['mrr'], then, 'mrr', 'up'):>20}"
            print(line)
    print('\n  dislikes: held-out dislikes that reached the top 24 / dislikes held out, then how many '
          'dislikes the top 24 of loves and likes alone holds')


def print_movers(report, base, count=5):
    for n, block in report['settings'].items():
        earlier = dig(base['settings'].get(n, {}), ('personas',)) or {}
        moves = sorted((r['loo']['mrr'] - earlier[k]['loo']['mrr'], k)
                       for k, r in block['personas'].items() if k in earlier)
        gains = sum(d >= 5e-4 for d, _ in moves)
        losses = sum(d <= -5e-4 for d, _ in moves)
        up = [f'{k} {d:+.3f}' for d, k in reversed(moves) if d >= 5e-4][:count]
        down = [f'{k} {d:+.3f}' for d, k in moves if d <= -5e-4][:count]
        print(f'\n{n}: leave-one-out MRR rose for {gains} personas, fell for {losses}, '
              f'held for {len(moves) - gains - losses}')
        print(f"  biggest gains: {', '.join(up) or 'none'}")
        print(f"  biggest losses: {', '.join(down) or 'none'}")


# ----------------------------------------------------------------------- runs

WORKER = {}


def start_worker(app, model, names, loaded=None):
    """Hold an engine and one Ranker per setting. A spawned worker loads its own
    engine; the single-process path hands over the one already loaded."""
    module, engine = loaded or load_engine(app, model)
    settings = {n: {**module.DEFAULT_SETTINGS, **SETTINGS[n]} for n in names}
    WORKER.update(engine=engine, settings=settings,
                  rankers={n: Ranker(engine, module, settings[n]) for n in names})


def run_one(persona, seed, allow_drift):
    """One persona under every setting, back to back, so the engine's own per-show
    cache is still warm when the second setting blends the same shows."""
    out, spent = {}, {}
    for n, ranker in WORKER['rankers'].items():
        t = time.perf_counter()
        out[n] = run_persona(WORKER['engine'], ranker, persona, WORKER['settings'][n], seed, allow_drift)
        ranker.forget()
        spent[n] = time.perf_counter() - t
    return out, spent


def run_all(personas, args, names, loaded):
    """Per-setting results keyed by persona, in persona order, and per-setting
    compute seconds. --jobs above 1 spreads personas over spawned processes, each
    loading its own engine; results are identical either way."""
    results, timings = {n: {} for n in names}, {n: 0.0 for n in names}

    def collect(count, persona, out, spent):
        for n in names:
            results[n][persona['key']] = out[n]
            timings[n] += spent[n]
        print(f"[{count}/{len(personas)}] {persona['key']} {sum(spent.values()):.1f}s", file=sys.stderr)

    if args.jobs <= 1:
        start_worker(args.app, args.model, names, loaded)
        for count, persona in enumerate(personas, 1):
            collect(count, persona, *run_one(persona, args.seed, args.allow_drift))
        return results, timings
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    pool = ProcessPoolExecutor(args.jobs, mp_context=multiprocessing.get_context('spawn'),
                               initializer=start_worker, initargs=(args.app, args.model, names))
    try:
        futures = [pool.submit(run_one, p, args.seed, args.allow_drift) for p in personas]
        for count, (persona, future) in enumerate(zip(personas, futures), 1):
            collect(count, persona, *future.result())
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()
    return results, timings


# ----------------------------------------------------------------------- main

def git_describe():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'describe', '--always', '--dirty'],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def sha256(path, length=12):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:length]


def find(engine, queries):
    for q in queries:
        print(f'{q}:')
        for c in engine.search(q):
            print(f"  {c['id']:>6}  {c['name'][:50]:<50} {c['year'] or '----'}  {c['type'] or '':<11} "
                  f"{c['language'] or '-':<10} popularity {c.get('known')}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--app', default=str(ROOT / 'app'), help='app root with backend/recommendation/engine.py; legacy roots also work')
    parser.add_argument('--model', default=str(ROOT / 'data' / 'model'), help='model folder (default data/model/)')
    parser.add_argument('--personas', default=str(Path(__file__).resolve().parent / 'personas.json'))
    parser.add_argument('--out', help='write the JSON report here')
    parser.add_argument('--compare', metavar='REPORT', help='print deltas against an earlier report')
    parser.add_argument('--settings', default=','.join(SETTINGS),
                        help=f"comma list of settings to run (default {','.join(SETTINGS)})")
    parser.add_argument('--persona', action='append', default=[], metavar='KEY', help='run only these personas')
    parser.add_argument('--seed', type=int, default=SEED, help=f'few-shot seed (default {SEED})')
    parser.add_argument('--jobs', type=int, default=1,
                        help='worker processes; each loads its own engine, about 0.7 GB (default 1)')
    parser.add_argument('--by-persona', action='store_true', help='print every persona, not just the weakest')
    parser.add_argument('--allow-drift', action='store_true',
                        help='warn instead of stopping when the adapter disagrees with calculate()')
    parser.add_argument('--check', action='store_true', help='validate the persona file and stop')
    parser.add_argument('--find', nargs='+', metavar='TITLE', help='look titles up in the catalog and stop')
    args = parser.parse_args(argv)

    names = [n.strip() for n in args.settings.split(',') if n.strip()]
    if not names or set(names) - set(SETTINGS):
        fail([f"--settings takes a comma list of {', '.join(SETTINGS)}"])
    base = None
    if args.compare:
        try:
            base = {**json.loads(Path(args.compare).read_text()), '_path': args.compare}
        except (OSError, ValueError) as e:
            fail([f'--compare {args.compare}: {e}'])

    started = time.perf_counter()
    module, engine = load_engine(args.app, args.model)
    if args.find:
        find(engine, args.find)
        return
    personas = load_personas(args.personas, engine, args.persona)
    rated = sum(len(ratings(p)) for p in personas)
    print(f'{len(personas)} personas and {rated} ratings match the catalog', file=sys.stderr)
    if args.check:
        return

    results, timings = run_all(personas, args, names, (module, engine))
    rankers = WORKER.get('rankers') or {n: Ranker(engine, module, {**module.DEFAULT_SETTINGS, **SETTINGS[n]})
                                        for n in names}

    report = {
        'bench': {'version': BENCH_VERSION, 'seed': args.seed, 'top': TOP, 'hit_at': list(HIT_AT),
                  'few_shot': {'size': FEW_SHOT_SIZE, 'draws': FEW_SHOT_DRAWS}, 'weights': WEIGHTS},
        'run': {
            'engine': shown(source_path(args.app, 'engine')),
            'engine_sha256': sha256(source_path(args.app, 'engine')),
            'git': git_describe(),
            'model': shown(args.model),
            'model_version': getattr(engine, 'version', None),
            'model_date': getattr(engine, 'date', None),
            'catalog_shows': engine.n,
            'default_settings': dict(module.DEFAULT_SETTINGS),
            'python': platform.python_version(),
            'runtime_s': round(time.perf_counter() - started, 1),
        },
        'personas': {'file': shown(args.personas), 'sha256': sha256(args.personas), 'count': len(personas),
                     'ratings': rated},
        'settings': {n: {
            'overrides': SETTINGS[n],
            'settings': rankers[n].settings,
            'summary': aggregate(results[n], len(rankers[n].pool), timings[n]),
            'personas': results[n],
        } for n in names},
    }

    print_summary(report, base)
    print_personas(report, None if args.by_persona else 8, base)
    if base:
        print_movers(report, base)
    print(f"\ntotal runtime {report['run']['runtime_s']}s", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(to_json(report) + '\n')
        print(f'report written to {args.out}', file=sys.stderr)


if __name__ == '__main__':
    main()
