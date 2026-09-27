"""Cache the complete TVmaze show index, with rate limiting and resumability.

Pages go to data/raw and the manifest to data/manifest.json unless TV_RAW_DIR and
TV_MANIFEST name other places. --out DIR downloads a complete set into DIR instead,
manifest at DIR/manifest.json, and leaves data/ alone. Every file is written whole
or not at all, so an interrupted run never leaves half a page behind.
"""
import concurrent.futures
import datetime
import hashlib
import json
import os
import pathlib
import threading
import time
import urllib.request
import urllib.error
import argparse
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = pathlib.Path(os.environ.get('TV_RAW_DIR') or ROOT / 'data/raw')
MANIFEST = pathlib.Path(os.environ.get('TV_MANIFEST') or ROOT / 'data/manifest.json')
lock = threading.Lock()
last = 0.0

def get(url):
    global last
    for attempt in range(6):
        with lock:
            time.sleep(max(0, .55 - (time.monotonic() - last)))
            last = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(url)

def write_atomic(path, body):
    """Write to a temporary name beside the file, then rename it into place."""
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        tmp.write_bytes(body)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

def page(n):
    path = RAW / f'page-{n:03d}.json'
    if not path.exists():
        body = get(f'https://api.tvmaze.com/shows?page={n}')
        assert isinstance(json.loads(body), list)
        write_atomic(path, body)
    return n, len(json.loads(path.read_text()))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true',help='Archive the current raw snapshot and download all pages again.')
    parser.add_argument('--out',metavar='DIR',type=pathlib.Path,
                        help='Download a complete set into DIR, manifest included, without touching data/. '
                             'Pages already in DIR are kept, so give a new directory for a fresh set.')
    args=parser.parse_args()
    if args.refresh and args.out:
        parser.error('--out never archives; use one or the other.')
    if args.out:
        RAW=args.out.resolve()
        manifest_path=RAW/'manifest.json'
    else:
        manifest_path=MANIFEST
    RAW.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        archive=RAW.parent/'archive'/stamp
        archive.mkdir(parents=True)
        shutil.move(str(RAW),str(archive/'raw'))
        RAW.mkdir(parents=True)
        if manifest_path.exists():shutil.move(str(manifest_path),str(archive/'manifest.json'))
        print(f'Archived the previous snapshot to {archive}',flush=True)
    if not (RAW / 'updates.json').exists():
        write_atomic(RAW / 'updates.json', get('https://api.tvmaze.com/updates/shows'))
    updates = json.loads((RAW / 'updates.json').read_text())
    pages = max(map(int, updates)) // 250 + 1
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for count, (n, size) in enumerate(pool.map(page, range(pages)), 1):
            total += size
            if count % 25 == 0 or count == pages:
                print(f'{count}/{pages} pages; {total:,} records', flush=True)
    manifest = {'source': 'https://www.tvmaze.com/api', 'license': 'CC BY-SA 4.0',
                'retrieved_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'pages': pages, 'records': total,
                'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(RAW.glob('page-*.json'))}}
    previous=json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if previous and previous.get('files')==manifest['files']:
        print('All pages match the cached snapshot; preserving its original retrieval date.',flush=True)
    else:
        write_atomic(manifest_path, json.dumps(manifest, indent=2).encode())
