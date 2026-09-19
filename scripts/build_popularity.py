"""Derive a one-byte-per-show popularity track from the raw TVmaze snapshot.

TVmaze publishes a 0-100 `weight` for every show, which the catalog build drops.
It is the only notability signal that covers the whole catalog: barely 13% of
shows carry a public rating, so a rating floor discards good titles simply for
being new. This writes the weights in catalog order so the engine can index them
directly, which costs about 60 KB instead of rebuilding the 18 MB catalog.

    .venv/bin/python scripts/build_popularity.py
"""
import glob
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'site' / 'model'
RAW = sorted(glob.glob(str(ROOT / 'data' / 'raw' / 'page-*.json')))

if not RAW:
    raise SystemExit('No raw pages in data/raw. Run scripts/download.py first.')

weights = {}
for page in RAW:
    for show in json.loads(Path(page).read_text()):
        weights[show['id']] = max(0, min(100, show.get('weight') or 0))

with gzip.open(MODEL / 'catalog.json.gz', 'rt') as f:
    shows = json.load(f)['shows']

missing = [s['id'] for s in shows if s['id'] not in weights]
track = bytes(weights.get(s['id'], 0) for s in shows)
out = MODEL / 'popularity.bin.gz'
with gzip.open(out, 'wb', compresslevel=9) as f:
    f.write(track)

print(f'{len(shows):,} shows · {len(missing):,} without a weight · '
      f'{out.stat().st_size / 1000:.1f} KB written to {out.relative_to(ROOT)}')
