"""Build model/cointerest.bin.gz: for each catalog show, the shows its readers also look
up on Wikipedia, as a similarity from the clickstream counts (pipeline/jobs/clickstream.py).

Over the latest MONTHS months in the cache, the counts between two shows' articles are
added up, and their similarity is count / sqrt(total(a) x total(b)), each total being
all of a show's counts with other shows: a cosine-like measure that does not favour
shows whose articles are simply busy. Each show keeps its TOP strongest neighbours.

cointerest.bin.gz: struct '<4sII' (b'COI1', rows, nnz), then CSR indptr u32 (rows+1),
indices u32 (nnz), values f32 (nnz), rows in catalog order, indices ascending.
cointerest.json.gz: {"version": 1, "months": [...], "pairs": n, "shows": n, "source": ...}

Environment: TV_MODEL_OUT (reads catalog.json.gz there, writes there), TV_COINTEREST
(the cache, data/cointerest.json.gz when unset; set but empty, or naming no file, there
is none: nothing is written and any old files are removed).
"""
import gzip
import json
import math
import os
import struct
import sys
from array import array
from collections import defaultdict
from pathlib import Path

from . import clickstream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL = Path(os.environ.get('TV_MODEL_OUT') or ROOT / 'data/model')
CACHE = os.environ.get('TV_COINTEREST', str(ROOT / 'data' / 'cointerest.json.gz'))
MONTHS = 3
TOP = 100


def neighbours(cache, months=MONTHS):
    """{show id: [(other id, similarity), ...]} strongest first, and the months used."""
    used = sorted(cache['months'])[-months:]
    pair = defaultdict(int)
    for month in used:
        for key, n in cache['months'][month].items():
            a, _, b = key.partition('-')
            pair[int(a), int(b)] += n
    total = defaultdict(int)
    for (a, b), n in pair.items():
        total[a] += n
        total[b] += n
    near = defaultdict(list)
    for (a, b), n in sorted(pair.items()):
        s = n / math.sqrt(total[a] * total[b])
        near[a].append((b, s))
        near[b].append((a, s))
    return {a: sorted(v, key=lambda x: (-x[1], x[0]))[:TOP] for a, v in near.items()}, used, len(pair)


def main():
    cache = clickstream.read(CACHE) if CACHE else None
    targets = (MODEL / 'cointerest.bin.gz', MODEL / 'cointerest.json.gz')
    if not cache or not cache['months']:
        for path in targets:
            path.unlink(missing_ok=True)
        print('No clickstream counts; no co-interest for this model.', flush=True)
        return
    with gzip.open(MODEL / 'catalog.json.gz', 'rt', encoding='utf-8') as f:
        ids = [s['id'] for s in json.load(f)['shows']]
    index = {show: i for i, show in enumerate(ids)}
    near, used, pairs = neighbours(cache)
    indptr, indices, values = array('I', [0]), array('I'), array('f')
    for show in ids:
        row = sorted((index[b], s) for b, s in near.get(show, ()) if b in index)
        for j, s in row:
            indices.append(j)
            values.append(s)
        indptr.append(len(indices))
    for a in (indptr, indices, values):
        if sys.byteorder != 'little':
            a.byteswap()
    with gzip.GzipFile(filename=str(targets[0]), mode='wb', mtime=0) as f:
        f.write(struct.pack('<4sII', b'COI1', len(ids), len(indices)))
        f.write(indptr.tobytes() + indices.tobytes() + values.tobytes())
    meta = {'version': 1, 'months': used, 'pairs': pairs, 'shows': sum(1 for s in ids if s in near),
            'source': 'https://dumps.wikimedia.org/other/clickstream/', 'license': 'CC0-1.0'}
    with gzip.GzipFile(filename=str(targets[1]), mode='wb', mtime=0) as f:
        f.write(json.dumps(meta, sort_keys=True).encode())
    print(f"{meta['shows']:,} shows with co-interest from {', '.join(used)}, {len(indices):,} links, "
          f"{targets[0].stat().st_size / 1e6:.2f} MB", flush=True)


if __name__ == '__main__':
    main()
