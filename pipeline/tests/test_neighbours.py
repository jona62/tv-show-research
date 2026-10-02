"""Check pipeline/jobs/build_neighbours.py on a small model made by hand.

Run from the repository root:  .venv/bin/python pipeline/tests/test_neighbours.py

Twelve shows in three kinds (crime, cooking and space), plot words and genres to match,
one show that cannot be recommended and one with nothing to go on. app/tests/test_engine.py
checks the index built for the real model against the engine's own closeness; this
checks the script's arithmetic where the answer is known.
"""
from pathlib import Path
import gzip
import json
import math
import os
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'pipeline'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))
from backend.recommendation import neighbours  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


WORDS = ['murder', 'detective', 'police', 'chef', 'kitchen', 'recipe', 'starship', 'planet', 'crew']
GENRES = ['Crime', 'Food', 'Science-Fiction']
KINDS = {'crime': ([0, 1, 2], 0), 'food': ([3, 4, 5], 1), 'space': ([6, 7, 8], 2)}
SHOWS = [('crime', [0, 1]), ('crime', [0, 2]), ('crime', [1, 2]), ('crime', [0, 1, 2]),
         ('food', [3, 4]), ('food', [4, 5]), ('food', [3, 5]), ('food', [3, 4, 5]),
         ('space', [6, 7]), ('space', [7, 8]), ('space', [6, 8]), (None, [])]
BLOCKED = 3         # the fourth crime show cannot be recommended


def write_model(folder):
    """catalog.json.gz and vectors.bin.gz as pipeline/jobs/build_model.py lays them out."""
    shows, rows = [], []
    for n, (kind, words) in enumerate(SHOWS):
        genre = KINDS[kind][1] if kind else None
        shows.append({'id': 100 + n, 'name': f'Show {n}', 'genres': [GENRES[genre]] if kind else [],
                      'genre_bits': 1 << genre if kind else 0, 'theme_bits': 0, 'recommendable': n != BLOCKED})
        norm = math.sqrt(len(words)) if words else 1
        rows.append({w: 1 / norm for w in words})
    catalog = {'version': 'test', 'date': '2026-09-29', 'shows': shows, 'genres': GENRES, 'themes': [],
               'text_features': len(WORDS), 'metadata': {}}
    with gzip.open(folder / 'catalog.json.gz', 'wt') as f:
        json.dump(catalog, f)
    csr_ptr, csr_idx, csr_val = [0], [], []
    for row in rows:
        for w in sorted(row):
            csr_idx.append(w)
            csr_val.append(row[w])
        csr_ptr.append(len(csr_idx))
    csc_ptr, csc_idx, csc_val = [0], [], []
    for w in range(len(WORDS)):
        for i, row in enumerate(rows):
            if w in row:
                csc_idx.append(i)
                csc_val.append(row[w])
        csc_ptr.append(len(csc_idx))
    nnz = len(csr_idx)
    with gzip.open(folder / 'vectors.bin.gz', 'wb') as f:
        f.write(struct.pack('<III', len(rows), len(WORDS), nnz))
        for part, code in ((csr_ptr, 'I'), (csr_idx, 'I'), (csr_val, 'f'), (csc_ptr, 'I'), (csc_idx, 'I'), (csc_val, 'f')):
            f.write(struct.pack(f'<{len(part)}{code}', *part))
    return rows


def expected(rows, i, j):
    """The engine's default closeness for two shows here: 0.4 text, 0.25 genre, no themes."""
    text = sum(v * rows[j].get(w, 0.0) for w, v in rows[i].items())
    genre = 1.0 if SHOWS[i][0] and SHOWS[i][0] == SHOWS[j][0] else 0.0
    return 0.4 * text + 0.25 * genre


folder = Path(tempfile.mkdtemp(prefix='neighbours-test-'))
rows = write_model(folder)
env = {**os.environ, 'TV_MODEL_OUT': str(folder)}
first = subprocess.run([sys.executable, str(SCRIPTS / 'run.py'), 'build_neighbours'], env=env, capture_output=True, text=True)
check('build_neighbours.py runs on a small model', first.returncode == 0, first.stderr[-400:])
made = (folder / 'neighbours.bin.gz').read_bytes()
again = subprocess.run([sys.executable, str(SCRIPTS / 'run.py'), 'build_neighbours'], env=env, capture_output=True, text=True)
check('and makes the same bytes from the same model', again.returncode == 0
      and (folder / 'neighbours.bin.gz').read_bytes() == made)
found = neighbours.load(folder, len(SHOWS))
width = len(SHOWS) - 2
check('it keeps as many neighbours as there are other shows to recommend', found.width == width, found.width)
recommendable = {n for n in range(len(SHOWS)) if n != BLOCKED}
all_right = True
for i in range(len(SHOWS)):
    index, near, text, bonus = found.row(i)
    if i in index or BLOCKED in index or not set(index) <= recommendable - {i} or len(set(index)) != width:
        all_right = False
check('each row holds every other recommendable show, never itself or one that cannot be recommended', all_right)
close = [(i, found.row(i)) for i in range(len(SHOWS))]
check('closest first', all(list(near) == sorted(near, reverse=True) for _i, (_index, near, _t, _b) in close))
check('the closest shows are the same kind', all(SHOWS[index[0]][0] == SHOWS[i][0] for i, (index, *_rest) in close
                                                 if SHOWS[i][0]))
check('closeness is the engine\'s blend, to within its packing',
      all(abs(v - expected(rows, i, j)) <= 0.02 * expected(rows, i, j) + 0.005
          for i, (index, near, _t, _b) in close for j, v in zip(index, near)))
check('and so is the plot-text part', all(
    abs(t - sum(v * rows[j].get(w, 0.0) for w, v in rows[i].items())) <= 0.5 / 255
    for i, (index, _near, text, _b) in close for j, t in zip(index, text)))
check('with no facets or co-interest there is no bonus', all(not any(b) for _i, (_x, _n, _t, b) in close))
check('ties go to the lower catalog index, so a show with nothing lists shows in order',
      list(found.row(len(SHOWS) - 1)[0]) == sorted(recommendable - {len(SHOWS) - 1}))
check('each show\'s degree counts the rows it is in',
      list(found.degree) == [sum(n in found.row(i)[0] for i in range(len(SHOWS))) for n in range(len(SHOWS))])

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
