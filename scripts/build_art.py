"""Derive Couchside's poster and end-year track from the raw TVmaze snapshot.

The catalog build keeps no images, and Couchside is mostly posters. Every TVmaze
poster lives at a URL made of its image id and a bucket of id // 2500, the same
for the medium and the original size, so one integer per show is enough to
rebuild both. The year a show ended rides along, because "2008 to 2013" reads
better than a start year alone.

Written in catalog order so the app can index it directly: a four-byte magic,
the show count, then one little-endian uint32 image id per show (0 for none)
and one uint16 end year per show (0 for none). About 400 KB gzipped, which the
release uploader carries without complaint, so it lives in couchside/.

    .venv/bin/python scripts/build_art.py

TV_RAW_DIR (data/raw), TV_MODEL_OUT (model, which holds the catalog read here) and
TV_ART_OUT (couchside/art.bin.gz) move the paths. The gzip header carries no
timestamp, so the output is repeatable.
"""
from array import array
import gzip
import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = Path(os.environ.get('TV_RAW_DIR') or ROOT / 'data' / 'raw')
RAW = sorted(RAW_DIR.glob('page-*.json'))
MODEL = Path(os.environ.get('TV_MODEL_OUT') or ROOT / 'model')
OUT = Path(os.environ.get('TV_ART_OUT') or ROOT / 'couchside' / 'art.bin.gz')
POSTER = re.compile(r'https://static\.tvmaze\.com/uploads/images/medium_portrait/(\d+)/(\d+)\.jpg')

if not RAW:
    raise SystemExit(f'No raw pages in {RAW_DIR}. Run scripts/download.py first.')

art = {}
for page in RAW:
    for show in json.loads(page.read_text()):
        image = (show.get('image') or {}).get('medium') or ''
        match = POSTER.fullmatch(image)
        # The bucket is derivable, so a poster whose bucket breaks the rule is left out
        # rather than rebuilt at a URL that would not load.
        image_id = int(match[2]) if match and int(match[1]) == int(match[2]) // 2500 else 0
        ended = show.get('ended') or ''
        art[show['id']] = (image_id, int(ended[:4]) if ended[:4].isdigit() else 0)

with gzip.open(MODEL / 'catalog.json.gz', 'rt') as f:
    shows = json.load(f)['shows']

images = array('I', (art.get(s['id'], (0, 0))[0] for s in shows))
ended = array('H', (art.get(s['id'], (0, 0))[1] for s in shows))
if sys.byteorder != 'little':
    images.byteswap()
    ended.byteswap()
with gzip.GzipFile(filename=str(OUT), mode='wb', compresslevel=9, mtime=0) as f:
    f.write(b'ART1' + struct.pack('<I', len(shows)) + images.tobytes() + ended.tobytes())

with_poster = sum(1 for i in images if i)
print(f'{len(shows):,} shows · {with_poster:,} with a poster · '
      f'{OUT.stat().st_size / 1000:.1f} KB written to {OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT}')
