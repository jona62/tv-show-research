"""Derive a one-byte-per-show popularity track from the raw TVmaze snapshot.

TVmaze publishes a 0-100 `weight` for every show, which the catalog build drops.
It is the only notability signal that covers the whole catalog: barely 13% of
shows carry a public rating, so a rating floor discards good titles simply for
being new. This writes the weights in catalog order so the engine can index them
directly, which costs about 60 KB instead of rebuilding the 18 MB catalog.

    .venv/bin/python tools/manage.py job build_popularity

TV_RAW_DIR (data/raw) and TV_MODEL_OUT (model, which holds the catalog read here)
move the paths. The gzip header carries no timestamp, so the output is repeatable.
"""
import gzip
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = Path(os.environ.get('TV_MODEL_OUT') or ROOT / 'data/model')
RAW_DIR = Path(os.environ.get('TV_RAW_DIR') or ROOT / 'data' / 'raw')
RAW = sorted(RAW_DIR.glob('page-*.json'))

if not RAW:
    raise SystemExit(f'No raw pages in {RAW_DIR}. Run pipeline/jobs/download.py first.')

weights = {}
for page in RAW:
    for show in json.loads(page.read_text()):
        weights[show['id']] = max(0, min(100, show.get('weight') or 0))

with gzip.open(MODEL / 'catalog.json.gz', 'rt') as f:
    shows = json.load(f)['shows']

missing = [s['id'] for s in shows if s['id'] not in weights]
track = bytes(weights.get(s['id'], 0) for s in shows)
out = MODEL / 'popularity.bin.gz'
with gzip.GzipFile(filename=str(out), mode='wb', compresslevel=9, mtime=0) as f:
    f.write(track)

print(f'{len(shows):,} shows · {len(missing):,} without a weight · '
      f'{out.stat().st_size / 1000:.1f} KB written to {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}')
