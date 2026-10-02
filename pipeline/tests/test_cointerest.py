"""Check the clickstream counts and the co-interest builder, offline.

Run from the repository root:  .venv/bin/python pipeline/tests/test_cointerest.py
"""
from pathlib import Path
import gzip
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
from jobs import clickstream                                   # noqa: E402
from backend.recommendation import facets                                        # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


by_title = {'Breaking_Bad': 169, 'Better_Call_Saul': 618, 'Mad_Men': 7, 'The_Wire': 179}
lines = [
    'Breaking_Bad\tMad_Men\tlink\t120\n',
    'Mad_Men\tBreaking_Bad\tlink\t30\n',
    'Breaking_Bad\tThe_Wire\tlink\t50\n',
    'Breaking_Bad\tBreaking_Bad\tlink\t999\n',       # a show to itself
    'Breaking_Bad\tMad_Men\texternal\t500\n',        # not a link between articles
    'Main_Page\tMad_Men\tlink\t900\n',               # not a show
    'Better_Call_Saul\tThe_Wire\tlink\tmany\n',      # a malformed count
]
counts = clickstream.count_month(iter(lines), by_title)
check('both directions of a pair add up', counts.get('7-169') == 150, counts)
check('only links between two shows count', set(counts) == {'7-169', '169-179'}, counts)

tmp = Path(tempfile.mkdtemp())
cache = {'version': 1, 'titles': {'169': 'Breaking_Bad'},
         'months': {'2026-05': {'7-169': 10}, '2026-06': {'7-169': 20}, '2026-07': {'7-169': 30, '169-179': 40},
                    '2026-08': {'7-169': 50, '7-179': 5}}}
clickstream.write(tmp / 'cache.json.gz', cache)
check('the cache reads back as written', clickstream.read(tmp / 'cache.json.gz') == cache)
first = (tmp / 'cache.json.gz').read_bytes()
clickstream.write(tmp / 'cache.json.gz', cache)
check('the cache is written the same way each time', (tmp / 'cache.json.gz').read_bytes() == first)
check('no cache reads as none', clickstream.read(tmp / 'nothing.json.gz') is None)
(tmp / 'bad.json.gz').write_bytes(gzip.compress(b'{"version": 2}'))
try:
    clickstream.read(tmp / 'bad.json.gz')
    check('a cache of another version is refused', False)
except ValueError:
    check('a cache of another version is refused', True)

sys.argv = ['x']
os.environ['TV_COINTEREST'] = str(tmp / 'cache.json.gz')
from jobs import build_cointerest                              # noqa: E402
near, used, pairs = build_cointerest.neighbours(cache)
check('the latest three months are used', used == ['2026-06', '2026-07', '2026-08'], used)
total = {169: 20 + 30 + 50 + 40, 7: 20 + 30 + 50 + 5, 179: 40 + 5}
expected = 100 / math.sqrt(total[169] * total[7])
got = dict(near[169])[7]
check('similarity is count over the root of both totals', abs(got - expected) < 1e-12, (got, expected))
check('links are symmetric', abs(dict(near[7])[169] - got) < 1e-12)
check('neighbours come strongest first', near[7] == sorted(near[7], key=lambda x: (-x[1], x[0])), near[7])

# The builder over a tiny catalogue.
model = tmp / 'model'
model.mkdir()
shows = [{'id': i, 'name': f'Show {i}', 'genres': []} for i in (7, 169, 179, 500)]
with gzip.open(model / 'catalog.json.gz', 'wt') as f:
    json.dump({'date': '2026-09-28', 'shows': shows}, f)
env = {**os.environ, 'TV_MODEL_OUT': str(model), 'TV_COINTEREST': str(tmp / 'cache.json.gz')}
run = subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'run.py'), 'build_cointerest'], env=env, capture_output=True, text=True)
check('the builder runs', run.returncode == 0, run.stderr[-300:])
matrix = facets.cointerest(model, len(shows))
indptr, indices, values = matrix
row = {indices[k]: values[k] for k in range(indptr[1], indptr[2])}          # show 169 is row 1
check('a show\'s row holds its neighbours by catalog index', set(row) == {0, 2}, row)
check('with the similarity the builder computed', abs(row[0] - expected) < 1e-6)
check('a show without links has an empty row', indptr[4] == indptr[3])
meta = json.load(gzip.open(model / 'cointerest.json.gz'))
check('the metadata names its months and licence', meta['months'] == used and meta['license'] == 'CC0-1.0', meta)
before = (model / 'cointerest.bin.gz').read_bytes()
subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'run.py'), 'build_cointerest'], env=env, capture_output=True)
check('the build is deterministic', (model / 'cointerest.bin.gz').read_bytes() == before)
try:
    facets.cointerest(model, len(shows) + 1)
    check('a matrix for another catalog size is refused', False)
except ValueError:
    check('a matrix for another catalog size is refused', True)
env['TV_COINTEREST'] = str(tmp / 'nothing.json.gz')
subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'run.py'), 'build_cointerest'], env=env, capture_output=True)
check('without counts the old files go, and the model has none', not (model / 'cointerest.bin.gz').exists()
      and facets.cointerest(model, len(shows)) is None)

shutil.rmtree(tmp, ignore_errors=True)
print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
