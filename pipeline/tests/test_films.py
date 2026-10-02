"""Check the film index: the fetch (films.py) against a pretend query service, and the
build (build_films.py) on a small made-up cache and facets, as the refresher runs it; then
the committed model's own film index.

Run from the repository root:  .venv/bin/python pipeline/tests/test_films.py

Nothing here reaches Wikidata: the pretend service answers the fetch's queries from a
dict of items, and the fixture cache is written by hand in the shape films.py writes.
"""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'pipeline'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from jobs import build_films                                              # noqa: E402
from jobs import films                                                    # noqa: E402
from jobs import wikidata                                                 # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='films-test-'))
NOW = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


# 1. The fetch, against a pretend query service ---------------------------------------------

ITEMS = {
    # Three films of a series, the first dystopian and the rest post-apocalyptic.
    'Q10': {'P31': ['Q11424'], 'links': 45, 'P136': ['Q1002', 'Q1007'], 'P179': ['Q20'], 'P577': ['1979-04-12T00:00:00Z'],
            'labels': [('en', 'Road Warrior')], 'aliases': [('en', 'Road Warrior (film)')]},
    'Q11': {'P31': ['Q11424'], 'links': 40, 'P136': ['Q1001', 'Q1002'], 'P179': ['Q20'],
            'P577': ['1982-05-01T00:00:00Z', '1981-12-24T00:00:00Z'], 'labels': [('en', 'Road Warrior 2')]},
    'Q12': {'P31': ['Q11424'], 'links': 70, 'P136': ['Q1001', 'Q1002', 'Q1003'], 'P179': ['Q20', 'Q999'],
            'labels': [('en', 'Road Warrior: Fury')]},
    'Q20': {'P31': ['Q24856'], 'links': 23, 'P136': ['Q1007'], 'labels': [('en', 'Road Warrior'), ('fr', 'La Route')],
            'aliases': [('en', 'Road Warrior series')]},
    # An anime film by its original title, and a film only just too little known.
    'Q30': {'P31': ['Q20650540'], 'links': 90, 'P136': ['Q1003'], 'P921': ['Q2001', 'Q2003'],
            'P1476': [('ja', '恐竜の島')], 'labels': [('mul', 'Dino Island')]},
    'Q40': {'P31': ['Q11424'], 'links': 19, 'labels': [('en', 'Too Little Known')]},
    # A series only just known enough, and a book series, which is not a film at all.
    'Q50': {'P31': ['Q13593818'], 'links': 5, 'labels': [('en', 'The Trilogy')]},
    'Q60': {'P31': ['Q1667921'], 'links': 99, 'labels': [('en', 'A Book Series')]},
    'Q1001': {'P279': ['Q1003'], 'labels': [('en', 'post-apocalyptic film')]},
    'Q1002': {'labels': [('en', 'action film')]},
    'Q1003': {'P279': ['Q1004'], 'labels': [('en', 'science fiction film')]},
    'Q1004': {'labels': [('en', 'speculative fiction')]},
    'Q1007': {'labels': [('en', 'dystopian film')]},
    'Q2001': {'labels': [('en', 'dinosaur')]},
    'Q2003': {'labels': [('en', 'Isla Nublar')]},
}
ENTITY = wikidata.ENTITY


class Service:
    """Answers the fetch's queries from ITEMS, by the tag on each query's first line."""

    def __init__(self, items):
        self.items, self.tags = items, []

    def answer(self, query):
        tag = query.split('\n', 1)[0].lstrip('#')
        self.tags.append(tag)
        uri = lambda q: {'type': 'uri', 'value': ENTITY + q}
        lit = lambda text, lang=None, kind=None: {'type': 'literal', 'value': str(text),
                                                  **({'xml:lang': lang} if lang else {}), **({'datatype': kind} if kind else {})}
        block = re.search(r'VALUES \?item \{([^}]*)\}', query)
        items = re.findall(r'wd:(Q\d+)', block[1]) if block else []
        known = lambda q: self.items.get(q, {})
        if tag == 'films':
            classes = re.findall(r'wd:(Q\d+)', re.search(r'VALUES \?class \{([^}]*)\}', query)[1])
            least = int(re.search(r'FILTER\(\?links >= (\d+)\)', query)[1])
            return [{'item': uri(q), 'class': uri(c), 'links': lit(d['links'], kind='xsd:integer')}
                    for q, d in self.items.items() for c in d.get('P31', []) if c in classes and d['links'] >= least]
        if tag == 'claims':
            props = re.findall(r'wdt:(P\d+)', re.search(r'VALUES \?p \{([^}]*)\}', query)[1])
            return [{'item': uri(q), 'p': {'type': 'uri', 'value': wikidata.DIRECT + p}, 'v': uri(v)}
                    for q in items for p in props for v in known(q).get(p, [])]
        if tag == 'dates':
            return [{'item': uri(q), 'date': lit(v, kind='xsd:dateTime')} for q in items for v in known(q).get('P577', [])]
        if tag == 'titles':
            return [{'item': uri(q), 'title': lit(text, lang)} for q in items for lang, text in known(q).get('P1476', [])]
        if tag == 'film-names':
            return [{'item': uri(q), 'name': lit(text, lang), 'alias': lit(kind)} for q in items
                    for kind, field in (('label', 'labels'), ('alias', 'aliases'))
                    for lang, text in known(q).get(field, []) if lang in ('en', 'mul')]
        if tag == 'parents':
            return [{'item': uri(q), 'v': uri(v)} for q in items for v in known(q).get('P279', [])]
        if tag in ('labels', 'any-labels'):
            return [{'item': uri(q), 'label': lit(text, lang)} for q in items for lang, text in known(q).get('labels', [])
                    if tag == 'any-labels' or lang in ('en', 'mul')]
        raise AssertionError(f'unexpected query {tag}')


class Client:
    """wikidata.Sparql's shape, answered by a Service in process."""

    def __init__(self, service):
        self.service, self.queries, self.bytes, self.seconds = service, 0, 0, 0.0

    def select(self, query, split=False):
        self.queries += 1
        return self.service.answer(query)


service = Service(ITEMS)
cache = films.fetch(Client(service), log=lambda _line: None, now=NOW)
found = cache['films']
check('every film and series known well enough is fetched, and nothing else',
      sorted(found, key=wikidata.qnum) == ['Q10', 'Q11', 'Q12', 'Q20', 'Q30', 'Q50'], sorted(found))
check('series are told from films, and an animated film is marked', found['Q20']['kind'] == 'series'
      and found['Q50']['kind'] == 'series' and found['Q10']['kind'] == 'film' and found['Q30'].get('animated')
      and 'animated' not in found['Q10'])
check('sitelinks and the earliest year are kept', found['Q12']['links'] == 70 and found['Q11']['year'] == 1981
      and found['Q10']['year'] == 1979 and 'year' not in found['Q12'])
check('labels, aliases and original titles are kept apart', found['Q10']['names'] == [
    ['alias', 'en', 'Road Warrior (film)'], ['label', 'en', 'Road Warrior']] and found['Q30']['names'] == [
    ['label', 'mul', 'Dino Island'], ['title', 'ja', '恐竜の島']] and ['label', 'fr', 'La Route'] not in found['Q20']['names'])
check('genres and subjects are sorted Q-ids', found['Q12']['genre'] == ['Q1001', 'Q1002', 'Q1003']
      and found['Q30']['subject'] == ['Q2001', 'Q2003'])
check('a film is part of only the series the cache holds', found['Q12']['part_of'] == ['Q20'] and 'part_of' not in found['Q30'])
check('superclasses go two levels up from each genre, and every genre, superclass and subject has a label',
      cache['parents'] == {'Q1001': ['Q1003'], 'Q1003': ['Q1004']} and cache['labels']['Q1004'] == 'speculative fiction'
      and cache['labels']['Q2003'] == 'Isla Nublar' and cache['labels']['Q1001'] == 'post-apocalyptic film')
check('the fetch time and the licence are recorded', cache['fetched_at'] == '2026-09-29T04:00:00Z'
      and cache['license'] == 'CC0-1.0' and cache['version'] == 1)
body = wikidata.encode(cache)
check('the cache encodes to the same bytes every time', body == wikidata.encode(json.loads(json.dumps(cache))))
try:
    films.fetch(Client(Service({})), log=lambda _line: None)
    check('a service that knows no films fails the fetch', False, 'accepted')
except wikidata.WikidataError as exc:
    check('a service that knows no films fails the fetch', 'no well-known films' in str(exc), str(exc))
(TMP / 'cache-v2.json.gz').write_bytes(gzip.compress(json.dumps({**cache, 'version': 2}).encode()))
try:
    films.read(TMP / 'cache-v2.json.gz')
    check('a cache of another version is refused', False)
except ValueError as exc:
    check('a cache of another version is refused', 'version 1' in str(exc))
check('no cache file reads as None', films.read(TMP / 'none.json.gz') is None)

# The script itself, over HTTP, as the refresher runs it.


class Web:
    def __init__(self, service, down=False):
        web = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                query = parse_qs(self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()).get('query', [''])[0]
                web.agents.append(self.headers.get('User-Agent'))
                if down:
                    status, body = 503, b'down'
                else:
                    status = 200
                    body = json.dumps({'head': {'vars': []}, 'results': {'bindings': service.answer(query)}}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/sparql-results+json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass
        self.agents = []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/sparql'

    def close(self):
        self.server.shutdown()
        self.server.server_close()


web, down = Web(Service(ITEMS)), Web(Service({}), down=True)
env = {**{k: v for k, v in os.environ.items() if not k.startswith(('TV_', 'WIKIDATA_'))},
       'WIKIDATA_SPARQL_URL': web.url, 'WIKIDATA_BACKOFF_SECONDS': '0.01'}
out = TMP / 'cli.json.gz'
done = subprocess.run([sys.executable, str(SCRIPTS / 'run.py'), 'films', '--out', str(out)], env=env,
                      capture_output=True, text=True, timeout=120)
result = next((line for line in reversed(done.stdout.splitlines()) if line.startswith('RESULT ')), '')
check('films.py --out writes the cache and ends with RESULT', done.returncode == 0 and out.is_file()
      and json.loads(result[len('RESULT '):]) | {'queries': 0, 'bytes': 0, 'seconds': 0} == {
          'fetched_at': json.loads(result[len('RESULT '):])['fetched_at'], 'films': 6, 'series': 2,
          'queries': 0, 'bytes': 0, 'seconds': 0}, done.stdout[-500:] + done.stderr[-500:])
check('it asks with the project\'s own User-Agent and no one\'s email',
      set(web.agents) == {wikidata.AGENT} and '@' not in wikidata.AGENT)
done = subprocess.run([sys.executable, str(SCRIPTS / 'run.py'), 'films', '--out', str(TMP / 'never.json.gz')],
                      env={**env, 'WIKIDATA_SPARQL_URL': down.url}, capture_output=True, text=True, timeout=120)
check('a fetch that fails exits 1 and writes nothing', done.returncode == 1 and 'films: failed' in done.stdout
      and not (TMP / 'never.json.gz').exists(), done.stdout[-300:])
web.close()
down.close()

# 2. The build, on a small cache and the facets it maps to ----------------------------------

model = TMP / 'model'
model.mkdir()
FAMILIES = ['genre', 'maker', 'cast', 'franchise', 'subject', 'network', 'award']
TOKENS = [[0, 'action', 'action', 900], [0, 'dystopian', 'dystopian', 60], [0, 'post apocalyptic', 'post apocalyptic', 140],
          [0, 'science fiction', 'science fiction', 1700], [0, 'speculative fiction', 'speculative fiction', 2800],
          [4, 'Q2001', 'dinosaur', 6], [4, 'Q2003', 'Isla Nublar', 2]]
(model / 'facets.json.gz').write_bytes(gzip.compress(json.dumps(
    {'version': 1, 'date': '2026-09-07', 'families': FAMILIES, 'tokens': TOKENS}).encode(), mtime=0))
cache_path = TMP / 'films.json.gz'
cache_path.write_bytes(body)


def build(source=cache_path, folder=model):
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('TV_')}, 'TV_MODEL_OUT': str(folder)}
    if source is not None:
        env['TV_FILMS'] = str(source)
    return subprocess.run([sys.executable, str(SCRIPTS / 'run.py'), 'build_films'], env=env, capture_output=True, text=True)


done = build()
index = json.loads(gzip.decompress((model / 'films.json.gz').read_bytes()))
by = {f['qid']: f for f in index['films']}
check('the build writes films.json.gz with its dates and source', done.returncode == 0 and index['version'] == 1
      and index['date'] == '2026-09-07' and index['wikidata_fetched_at'] == '2026-09-29T04:00:00Z'
      and index['license'] == 'CC0-1.0', done.stdout + done.stderr)
check('genres are keyed as the shows\' are, the medium stripped, and superclasses count at half, then a quarter',
      by['Q11']['genre'] == {'action': 1.0, 'post apocalyptic': 1.0, 'science fiction': 0.5, 'speculative fiction': 0.25},
      by['Q11']['genre'])
check('a series takes on what a third or more of its films carry, at their share, besides its own genres',
      by['Q20']['genre'] == {'action': 1.0, 'dystopian': 1.0, 'post apocalyptic': 0.667, 'science fiction': 0.5},
      by['Q20']['genre'])
check('only the shows\' own keys are kept: subjects by Q-id, weighed 1', by['Q30']['subject'] == {'Q2001': 1.0, 'Q2003': 1.0}
      and by['Q30']['genre'] == {'science fiction': 1.0, 'speculative fiction': 0.5})
check('a subject that is no place or event is kept as a word to look for', by['Q30']['topics'] == ['dinosaur'])
check('a film with nothing the shows carry is left out', 'Q50' not in by)
check('the title is the English label, else the default one; other titles and aliases apart, qualifiers dropped',
      by['Q10']['title'] == 'Road Warrior' and by['Q10']['aliases'] == [] and by['Q30']['title'] == 'Dino Island'
      and by['Q30']['titles'] == ['恐竜の島'] and by['Q20']['aliases'] == ['Road Warrior series'])
check('an animated film says so', by['Q30']['animated'] is True and by['Q10']['animated'] is False)
check('films are listed best known first', [f['qid'] for f in index['films']] == ['Q30', 'Q12', 'Q10', 'Q11', 'Q20'])
first = (model / 'films.json.gz').read_bytes()
build()
check('the same inputs make the same bytes', (model / 'films.json.gz').read_bytes() == first and first[4:8] == bytes(4))
(model / 'films.json.gz').unlink()
done = build(source=None)
check('without TV_FILMS nothing is written', done.returncode == 0 and 'TV_FILMS is not set' in done.stdout
      and not (model / 'films.json.gz').exists())
done = build(source=TMP / 'missing.json.gz')
check('without a cache nothing is written', done.returncode == 0 and 'No film cache' in done.stdout
      and not (model / 'films.json.gz').exists())
(TMP / 'broken.json.gz').write_bytes(b'not gzip')
done = build(source=TMP / 'broken.json.gz')
check('a broken cache fails the build, and writes nothing', done.returncode != 0 and 'not a film cache' in done.stderr
      and not (model / 'films.json.gz').exists(), done.stderr[-300:])
bare = TMP / 'bare'
bare.mkdir()
done = build(folder=bare)
check('without facets to map to nothing is written', done.returncode == 0 and 'No facets' in done.stdout
      and not (bare / 'films.json.gz').exists())
check('names are folded as the build compares them', build_films.fold('Amélie  Poulain!') == 'ameliepoulain')

# 3. The committed model's own film index --------------------------------------------------

path = ROOT / 'data/model' / 'films.json.gz'
committed = json.loads(gzip.decompress(path.read_bytes()))
meta = json.loads(gzip.decompress((ROOT / 'data/model' / 'facets.json.gz').read_bytes()))
keys = {(meta['families'][f], key) for f, key, _label, _df in meta['tokens']}
titles = {f['title'] for f in committed['films']}
check('the committed film index is small, and built for the committed facets', path.stat().st_size < 3_000_000
      and committed['date'] == meta['date'], path.stat().st_size)
check('it holds thousands of well-known films and some series', len(committed['films']) > 5000
      and sum(1 for f in committed['films'] if f['kind'] == 'series') > 100)
check('every key it names is one the shows carry', all(('genre', k) in keys for f in committed['films'] for k in f['genre'])
      and all(('subject', k) in keys for f in committed['films'] for k in f['subject']))
check('the films the search is judged on are there', {'Mad Max', 'Jurassic Park', 'The Godfather', 'The Matrix',
                                                        'Parasite', 'Spirited Away'} <= titles)

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f'{len(failures)} check(s) failed')
    sys.exit(1)
print('all film checks passed')
