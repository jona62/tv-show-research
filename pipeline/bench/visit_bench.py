"""Offline check of how Couchside's home page changes from one visit to the next, over the bench personas.

Each persona in personas.json and holdout.json rates its shows less a fifth of its loves,
held out as home_bench.py holds them out, and opens the app VISITS times a day for DAYS
days. The browser's memory is kept as fresh.js keeps it: each visit sees the hero and the
first six cards of each of the first eight rows, the first page, and opens, rates and
lists nothing. Each visit is asked for three ways:

  plain    no day or seed: the page the other benchmarks read
  day      the day, its seed and what earlier days showed: every visit of a day got the
           day's page before visits had seeds of their own
  visit    as Couchside asks now: the visit's seed as well, each earlier visit the same day
           that showed a title, among its cards or as its hero, counting half a day's
           showing (a whole day's at most), and the heroes of the day's earlier visits
           resting

and each is read, over every visit, for:

  held-out loves in the first 3 and 8 rows   among each row's first six cards
  hero's place                 its place among the picks (1 is the best), median and
                               95th percentile
  Top picks led by the best    the plain page's first card first
  the best three               the plain page's first three all among the first six
  best six in the first six    how many of the plain page's first six are there
  furthest in the first six    the lowest place among the picks there, 95th percentile

and, from one visit to the next the same day and from a day's last visit to the next
day's first, for:

  hero new                     another hero than the visit before's
  Top picks' first card new    another first card than the visit before's
  new in Top picks' first six  cards that were not among them the visit before
  rows new and moved           of the first eight rows, rows that were not among them the
                               visit before, and places that hold another row
  cards kept                   of each other row's first six, the share it opened with the
                               visit before too, over rows among the first eight both times

    .venv/bin/python pipeline/bench/visit_bench.py
    .venv/bin/python pipeline/bench/visit_bench.py --visits 8 --days 2
    .venv/bin/python pipeline/bench/visit_bench.py --set VISIT=0.5 --set LEAD_STEEP=2
"""
import argparse
import hashlib
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path
from runtime import module as runtime_module

ROOT = Path(__file__).resolve().parents[2]
COUCHSIDE = ROOT / 'couchside'
sys.path.insert(0, str(ROOT / 'pipeline' / 'bench'))
from home_bench import FILES, WEIGHTS, HELD, GLANCE  # noqa: E402

FIRST_ROWS = 8      # the first page, which a visit sees
HALF_LIFE = 7       # fresh.js's
HERO_REST = 7
TODAY = 0.5         # an earlier visit the same day, as fresh.js counts it
MODES = ('plain', 'day', 'visit')


class Memory:
    """What fresh.js keeps for one browser: the days each title was seen, the visits of its
    latest day it was seen in, and each day's heroes in the order they were shown."""

    def __init__(self):
        self.days, self.visits, self.heroes = {}, {}, {}

    def fields(self, day, visit):
        """The seen counts and resting heroes a request carries, as fresh.js's freshness
        works them out; visit 0 is a request without one, as before visits."""
        seen = {}
        featured = set(self.heroes.get(day, ())) if visit else set()
        for show_id, days in self.days.items():
            count = sum(0.5 ** ((day - d) / HALF_LIFE) for d in days if d < day)
            if visit:
                cards = sum(1 for k in self.visits.get(show_id, ()) if k < visit) if days[-1] == day else 0
                count += TODAY * min(2, cards + (show_id in featured))
            count = math.floor(count * 10 + 0.5) / 10
            if count >= 0.1:
                seen[str(show_id)] = min(count, 50)
        for show_id in featured - set(self.days):
            seen[str(show_id)] = TODAY
        seen = dict(sorted(seen.items(), key=lambda kv: (-kv[1], int(kv[0])))[:300])
        resting = [ids[0] for d, ids in sorted(self.heroes.items()) if day - HERO_REST <= d < day and ids]
        if visit:
            resting += self.heroes.get(day, [])
        return seen, list(dict.fromkeys(resting))[-60:]

    def note(self, day, visit, shown, hero):
        for show_id in shown:
            days = self.days.setdefault(show_id, [])
            if day not in days:
                days.append(day)
                self.visits[show_id] = []
            if visit and visit not in self.visits[show_id]:
                self.visits[show_id] = (self.visits[show_id] + [visit])[-2:]
        heroes = self.heroes.setdefault(day, [])
        if hero not in heroes:
            heroes.append(hero)


def seed(*parts):
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:16]


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float('nan')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--visits', type=int, default=5, help='visits a day')
    parser.add_argument('--days', type=int, default=3)
    parser.add_argument('--set', action='append', default=[], metavar='NAME=VALUE',
                        help='set one of fresh.py\'s constants for the run, such as VISIT=0.5')
    parser.add_argument('--out', help='write every persona\'s numbers here as JSON')
    args = parser.parse_args()
    fresh = runtime_module(COUCHSIDE, 'fresh')
    library = runtime_module(COUCHSIDE, 'library')
    engine_module = runtime_module(COUCHSIDE, 'engine')
    Engine, DEFAULT_SETTINGS = engine_module.Engine, engine_module.DEFAULT_SETTINGS
    for item in args.set:
        name, _, value = item.partition('=')
        if not hasattr(fresh, name):
            parser.error(f'fresh.py has no {name}')
        setattr(fresh, name, type(getattr(fresh, name))(value))
    engine = Engine(ROOT / 'data' / 'model')
    lib = library.Library(engine, COUCHSIDE / 'assets' / 'model' / 'art.bin.gz')
    lib.ahead = False
    started = time.time()
    report = {}
    for name in FILES:
        for p in json.loads((ROOT / 'pipeline' / 'bench' / name).read_text())['personas']:
            loves = [s['id'] for s in p['loves'] if s['id'] in engine.by_id]
            held = set(random.Random(p['key']).sample(loves, max(1, round(HELD * len(loves)))))
            profile = [{'id': s['id'], 'weight': w} for role, w in WEIGHTS.items() for s in p[role]
                       if s['id'] in engine.by_id and s['id'] not in held]
            body = {'profile': profile, 'settings': dict(DEFAULT_SETTINGS), 'list': []}
            prepared = lib.prepare(body)
            page = library.Page(lib, *prepared[:6], lib.read_list(body), prepared[6])
            place = {engine.shows[i]['id']: n + 1 for n, i in enumerate(page.usable)}
            plain = lib.home(body)
            best6 = next(([c['id'] for c in r['items'][:GLANCE]] for r in plain['rows'] if r['key'] == 'top'), [])
            visits = {mode: [] for mode in MODES}
            memories = {'day': Memory(), 'visit': Memory()}
            for d in range(1, args.days + 1):
                day = f'2026-10-{d:02d}'
                pages = {}
                for k in range(1, args.visits + 1):
                    for mode in MODES:
                        if mode == 'plain':
                            answer = plain
                        elif mode == 'day' and k > 1:
                            answer = pages['day']
                        else:
                            visit = k if mode == 'visit' else 0
                            seen, resting = memories[mode].fields(d, visit)
                            ask = {**body, 'day': day, 'seed': seed(p['key'], day), 'seen': seen, 'resting': resting}
                            if visit:
                                ask['visit'] = seed(p['key'], day, visit)
                            answer = lib.home(ask)
                        pages[mode] = answer
                        rows = [r for r in answer['rows'] if r['kind'] != 'list'][:FIRST_ROWS]
                        firsts = {r['key']: [c['id'] for c in r['items'][:GLANCE]] for r in rows}
                        opened = {i for ids in firsts.values() for i in ids}
                        first3 = {i for r in rows[:3] for i in firsts[r['key']]}
                        hero = answer['hero']['id']
                        visits[mode].append({'day': d, 'visit': k, 'hero': hero, 'keys': [r['key'] for r in rows],
                                             'firsts': firsts, 'hits3': len(held & first3), 'hits8': len(held & opened)})
                        if mode != 'plain':
                            memories[mode].note(d, k if mode == 'visit' else 0, opened, hero)
            report[p['key']] = {'file': name, 'held': len(held), 'best6': best6, 'place': place, 'visits': visits}
    print(f'{len(report)} personas, {sum(r["held"] for r in report.values())} held-out loves, '
          f'{args.days} days of {args.visits} visits, {time.time() - started:.0f}s'
          f'{", " + ", ".join(args.set) if args.set else ""}\n')
    summary(report)
    if args.out:
        Path(args.out).write_text(json.dumps({k: {**v, 'place': None} for k, v in report.items()}, indent=1))


def changes(v, before, out):
    """What changed from one visit to the next, added to out."""
    top, last = v['firsts'].get('top', []), before['firsts'].get('top', [])
    out['hero_new'].append(v['hero'] != before['hero'])
    if top and last:
        out['first_new'].append(top[0] != last[0])
        out['new6'].append(len(set(top) - set(last)))
    out['moved'].append(sum(1 for a, b in zip(v['keys'], before['keys']) if a != b))
    out['new_rows'].append(len(set(v['keys']) - set(before['keys'])))
    for key, ids in v['firsts'].items():
        if key not in ('top', 'top10') and key in before['firsts']:
            out['kept'].append(len(set(ids) & set(before['firsts'][key])) / max(1, len(ids)))


def summary(report):
    held = sum(r['held'] for r in report.values())
    rows, days = {}, {}
    for mode in MODES:
        out = {'hits3': 0, 'hits8': 0, 'n': 0, 'hero_new': [], 'hero_place': [], 'first_new': [], 'new6': [],
               'best6': [], 'furthest': [], 'moved': [], 'new_rows': [], 'kept': [], 'led': [], 'best3': []}
        overnight = {'hero_new': [], 'first_new': [], 'new6': [], 'moved': [], 'new_rows': [], 'kept': []}
        for r in report.values():
            place = r['place']
            before = None
            for v in r['visits'][mode]:
                out['hits3'] += v['hits3']
                out['hits8'] += v['hits8']
                out['n'] += 1
                out['hero_place'].append(place.get(v['hero'], len(place) + 1))
                top = v['firsts'].get('top', [])
                if top and r['best6']:
                    out['best6'].append(len(set(top) & set(r['best6'])))
                    out['furthest'].append(max(place.get(i, len(place) + 1) for i in top))
                    out['led'].append(top[0] == r['best6'][0])
                    out['best3'].append(set(r['best6'][:3]) <= set(top))
                if before is not None:
                    changes(v, before, out if before['day'] == v['day'] else overnight)
                before = v
        rows[mode], days[mode] = out, overnight
    visits = rows['plain']['n'] / len(report)
    print(f'{"":<40}{"plain":>9}{"day":>9}{"visit":>9}')
    line = lambda label, values: print(f'  {label:<38}' + ''.join(f'{v:>9}' for v in values))
    mean = lambda values, f='{:.2f}': f.format(statistics.mean(values)) if values else 'n/a'
    for key, text in (('hits3', 'held-out loves in first 3 rows'), ('hits8', 'held-out loves in first 8 rows')):
        line(text, [f'{rows[m][key] / rows[m]["n"] / held * len(report):.1%}' for m in MODES])
    line('hero\'s place, median', [f'{statistics.median(rows[m]["hero_place"]):g}' for m in MODES])
    line('hero\'s place, 95th percentile', [f'{pct(rows[m]["hero_place"], .95):g}' for m in MODES])
    line('Top picks led by the best', [mean(rows[m]['led'], '{:.0%}') for m in MODES])
    line('the best three in the first six', [mean(rows[m]['best3'], '{:.0%}') for m in MODES])
    line('best six in the first six', [mean(rows[m]['best6']) for m in MODES])
    line('furthest in the first six, 95th pct', [f'{pct(rows[m]["furthest"], .95):g}' for m in MODES])
    for label, table in (('from one visit to the next the same day', rows), ('from a day\'s last visit to the next day\'s first',
                                                                            days)):
        print(f'\n  {label}')
        line('hero new', [mean(table[m]['hero_new'], '{:.0%}') for m in MODES])
        line('Top picks\' first card new', [mean(table[m]['first_new'], '{:.0%}') for m in MODES])
        line('new in Top picks\' first six', [mean(table[m]['new6']) for m in MODES])
        line('of the first eight rows, new', [mean(table[m]['new_rows']) for m in MODES])
        line('of the first eight rows, moved', [mean(table[m]['moved']) for m in MODES])
        line('a row\'s first six kept', [mean(table[m]['kept'], '{:.0%}') for m in MODES])
    print(f'\n  {visits:.0f} visits a persona')


if __name__ == '__main__':
    main()
