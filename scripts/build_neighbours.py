"""Build model/neighbours.bin.gz: each catalog show's WIDTH closest recommendable shows,
by the closeness the apps' engine uses under its default settings.

    .venv/bin/python scripts/build_neighbours.py

A list of a few dozen rated shows is ranked by working out how close every show in the
catalogue sits to each rated one (app/engine.py, Engine.blend), about 20 ms a show in
the apps' standard-library Python. A list of thousands cannot be ranked that way, so the
engine ranks a long one from this file instead: for each rated show, its closest shows
and how close. Kept this short, the lists also leave out the faint likeness any two
dramas have, which on the bench's long lists only added noise (scripts/bench/README.md).

Closeness is the engine's blend at its defaults: plot text 40, themes 35 and genres 25,
shared out, plus 0.3 times the facet closeness, which is franchise and maker ties
(FACET_WEIGHTS) and what the show's Wikipedia readers also look up (CO_WEIGHT x s^CO_POWER,
between shows that share no franchise). Those constants mirror app/engine.py, and
app/test_engine.py checks the file against the engine's own closeness, so the two cannot
drift apart unnoticed.

neighbours.bin.gz: struct '<4sII' (b'NBR1', rows, width), then four arrays of rows x
width, a row per catalog show in catalog order, its neighbours closest first, and one
of rows:

  index    u32, the neighbour's catalog index; never the show itself, and only
           recommendable shows
  near     u8, the closeness, as round(255 x sqrt(closeness / NEAR_MAX))
  text     u8, the plot-text cosine, as round(255 x cosine)
  bonus    u8, the facet closeness with the co-interest in it, before the 0.3, as
           round(255 x sqrt(bonus / BONUS_MAX))
  degree   u16 per show, how many shows count it among their closest

With text and bonus, and themes and genres from the catalog, the engine rebuilds the
closeness any other settings give. Environment: TV_MODEL_OUT (model), where the catalog,
vectors, facets and co-interest are read and the file is written. It takes about two
minutes and at most 820 MB on one thread of an M3 Pro laptop, as the refresher runs it.
"""
import gzip
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL = Path(os.environ.get('TV_MODEL_OUT') or ROOT / 'model')
WIDTH = 48
NEAR_MAX = 4.5
BONUS_MAX = 11.2
BLOCK = 128
# app/engine.py's DEFAULT_SETTINGS weights, FACET_WEIGHTS, CO_WEIGHT and CO_POWER.
TEXT, THEMES, GENRES, FACETS = 40, 35, 25, 30
FACET_WEIGHTS = {'franchise': 2.0, 'maker': 0.5, 'cast': 0.0, 'genre': 0.0, 'subject': 0.0,
                 'network': 0.0, 'award': 0.0}
CO_WEIGHT = 3.0
CO_POWER = 0.33


def read_vectors(path, rows):
    """The plot-text TF-IDF rows, unit length, as a CSR matrix."""
    with gzip.open(path, 'rb') as f:
        n, cols, nnz = struct.unpack('<III', f.read(12))
        if n != rows:
            raise SystemExit(f'vectors.bin.gz has {n:,} rows where the catalog has {rows:,} shows.')
        ptr = np.frombuffer(f.read(4 * (n + 1)), dtype='<u4').astype(np.int64)
        terms = np.frombuffer(f.read(4 * nnz), dtype='<u4').astype(np.int64)
        values = np.frombuffer(f.read(4 * nnz), dtype='<f4')
    return sp.csr_matrix((values, terms, ptr), shape=(n, cols))


def bits(masks, width):
    """A float32 indicator matrix of each show's bits, and one over the root of each show's
    count of them (zero for a show with none)."""
    out = np.zeros((len(masks), width), dtype=np.float32)
    for i, mask in enumerate(masks):
        while mask:
            low = mask & -mask
            out[i, low.bit_length() - 1] = 1.0
            mask ^= low
    count = out.sum(axis=1)
    inverse = np.zeros_like(count)
    np.divide(1.0, np.sqrt(count), out=inverse, where=count > 0)
    return out, inverse


def cosine_block(ind, inverse, start, end):
    """Bit-set cosine of shows start..end against every show: shared bits over the root of
    the product of their counts, and zero where either has none (Engine.components)."""
    out = ind[start:end] @ ind.T
    out *= inverse[start:end, None]
    out *= inverse[None, :]
    return out


def facet_matrices(model, n):
    """(weighted rows, columns) whose product is each pair's facet closeness, franchise
    and maker cosines weighted as the engine weights them, and each show's franchise
    tokens; (None, None, no franchises) when the model has no facets."""
    found = facets.load(model, n)
    if not found:
        return None, None, [frozenset()] * n
    known = [f for f in FACET_WEIGHTS if f in found.families]
    total = sum(FACET_WEIGHTS[f] for f in known) or 1
    family_weight = np.array([FACET_WEIGHTS.get(name, 0.0) / total for name in found.families], dtype=np.float32)
    column_family = np.frombuffer(found.token_family, dtype=np.uint8)
    rows = sp.csr_matrix((np.frombuffer(found.values, dtype=np.float32),
                          np.frombuffer(found.columns, dtype=np.uint32).astype(np.int64),
                          np.frombuffer(found.row_ptr, dtype=np.uint32).astype(np.int64)), shape=(n, found.cols))
    weight = family_weight[column_family]
    keep = np.nonzero(weight > 0)[0]
    kept = rows[:, keep].tocsr()
    weighted = kept.multiply(weight[keep][None, :]).tocsr()
    franchise = [frozenset()] * n
    if 'franchise' in found.families:
        start, end = found.family_ranges[found.families.index('franchise')]
        franchise = [frozenset(c for c, _v in found.row(i) if start <= c < end) for i in range(n)]
    return weighted, kept.T.tocsr(), franchise


def cointerest_matrix(model, n, franchise):
    """What each show's Wikipedia readers also look up, as the engine adds it to the facet
    slot: CO_WEIGHT / 0.3 x strength^CO_POWER, skipping shows that share a franchise."""
    found = facets.cointerest(model, n)
    if not found:
        return None
    indptr, indices, values = found
    scale = CO_WEIGHT / (FACETS / 100)
    rows, cols, vals = [], [], []
    for i in range(n):
        mine = franchise[i]
        for k in range(indptr[i], indptr[i + 1]):
            j = indices[k]
            if mine and mine & franchise[j]:
                continue
            rows.append(i)
            cols.append(j)
            vals.append(scale * values[k] ** CO_POWER)
    return sp.csr_matrix((np.array(vals, dtype=np.float32), (np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64))),
                         shape=(n, n))


def pack(values, most):
    """Values from 0 to most as bytes, finer toward zero: round(255 x sqrt(value / most))."""
    return np.rint(255 * np.sqrt(np.clip(values, 0.0, most) / most)).astype(np.uint8)


def build(model, width=WIDTH, block=BLOCK, say=print):
    """(index, near, text, bonus, degree) arrays for the model in the folder."""
    with gzip.open(model / 'catalog.json.gz', 'rt', encoding='utf-8') as f:
        catalog = json.load(f)
    shows = catalog['shows']
    n = len(shows)
    themes, theme_inverse = bits([s['theme_bits'] for s in shows], max(1, len(catalog['themes'])))
    genres, genre_inverse = bits([s['genre_bits'] for s in shows], max(1, len(catalog['genres'])))
    recommendable = np.array([bool(s['recommendable']) for s in shows])
    del catalog, shows
    vectors = read_vectors(model / 'vectors.bin.gz', n)
    columns = vectors.T.tocsr()
    weighted, facet_columns, franchise = facet_matrices(model, n)
    co = cointerest_matrix(model, n, franchise)
    del franchise
    total = TEXT + THEMES + GENRES
    a, b, c, d = TEXT / total, THEMES / total, GENRES / total, FACETS / 100
    blocked = ~recommendable
    width = min(width, max(1, int(recommendable.sum()) - 1))
    index = np.zeros((n, width), dtype='<u4')
    near = np.zeros((n, width), dtype=np.uint8)
    text = np.zeros((n, width), dtype=np.uint8)
    bonus = np.zeros((n, width), dtype=np.uint8)
    started = time.perf_counter()
    for start in range(0, n, block):
        end = min(n, start + block)
        rows = np.arange(end - start)[:, None]
        t = (vectors[start:end] @ columns).toarray()
        s = cosine_block(themes, theme_inverse, start, end)
        s *= b
        s += c * cosine_block(genres, genre_inverse, start, end)
        s += a * t
        extra = np.zeros_like(s)
        if weighted is not None:
            extra += (weighted[start:end] @ facet_columns).toarray()
        if co is not None:
            extra += co[start:end].toarray()
        s += d * extra
        s[:, blocked] = -1.0
        s[rows[:, 0], np.arange(start, end)] = -1.0
        top = np.argpartition(-s, width - 1, axis=1)[:, :width]
        value = np.take_along_axis(s, top, 1)
        order = np.lexsort((top, -value), axis=1)
        top = np.take_along_axis(top, order, 1)
        index[start:end] = top
        near[start:end] = pack(np.take_along_axis(value, order, 1), NEAR_MAX)
        text[start:end] = np.rint(255 * np.clip(t[rows, top], 0.0, 1.0)).astype(np.uint8)
        bonus[start:end] = pack(extra[rows, top], BONUS_MAX)
        del t, s, extra
        if start // block % 100 == 0:
            say(f'  {end:,} of {n:,} shows, {time.perf_counter() - started:.0f}s')
    degree = np.minimum(np.bincount(index.ravel(), minlength=n), 65535).astype('<u2')
    return index, near, text, bonus, degree


def write(path, index, near, text, bonus, degree):
    rows, width = index.shape
    with gzip.GzipFile(filename=str(path), mode='wb', mtime=0) as f:
        f.write(struct.pack('<4sII', b'NBR1', rows, width))
        for part in (index.astype('<u4'), near, text, bonus, degree.astype('<u2')):
            f.write(part.tobytes())


def main():
    started = time.perf_counter()
    built = build(MODEL, say=lambda line: print(line, flush=True))
    rows, width = built[0].shape
    target = MODEL / 'neighbours.bin.gz'
    temporary = target.with_name('.neighbours.bin.gz.tmp')
    write(temporary, *built)
    os.replace(temporary, target)
    print(f'{rows:,} shows with their {width} closest, {target.stat().st_size / 1e6:.1f} MB, '
          f'{time.perf_counter() - started:.0f}s', flush=True)


if __name__ == '__main__':
    main()
