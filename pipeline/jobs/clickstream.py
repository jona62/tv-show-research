"""Which TV shows the same readers look up: counts from Wikipedia's clickstream.

Wikimedia publishes, each month, how many times readers followed a link from one
English Wikipedia article to another (pairs under ten a month are left out), under
CC0. Readers who go from Breaking Bad's article to Mad Men's are a behavioural signal
the catalogue's own text cannot give: people interested in one are interested in the
other. This keeps, for each month, only the counts between articles about shows in
the catalogue, in both directions added together, keyed by TVmaze id.

    .venv/bin/python tools/manage.py job clickstream --cache data/cointerest.json.gz [--months 3]

The cache (gzip JSON, written atomically, deterministic):
    {"version": 1, "titles": {"<tvmaze id>": "Breaking_Bad", ...},
     "months": {"2026-08": {"<a>-<b>": count, ...}, ...}}   a < b, TVmaze ids
Each run fetches the English article titles of every show with a TVmaze id from
Wikidata, then streams each of the latest --months published months it does not
hold yet (about 500 MB compressed each, never written to disk) and keeps the latest
KEEP months. A month that fails to download, or breaks off part way, is skipped and
tried again next run. Each month is written to the cache as soon as it is counted, so
a run stopped part way keeps the months it finished, and a cache that does not read
is counted again from nothing. The last line printed is RESULT and a JSON summary:
the months held, the months wanted, those fetched and those skipped, with why. The
exit status is 1, and nothing is written, when the titles or the listing of months
cannot be fetched. --published only reads that listing and prints the latest
--months months as RESULT.
Environment: CLICKSTREAM_BASE (default https://dumps.wikimedia.org/other/clickstream),
WIKIDATA_SPARQL_URL (default https://query.wikidata.org/sparql).
"""
import argparse
import gzip
import http.client
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

AGENT = 'tv-taste-research/1.0 (+https://github.com/jona62/tv-show-research)'
BASE = os.environ.get('CLICKSTREAM_BASE', 'https://dumps.wikimedia.org/other/clickstream').rstrip('/')
SPARQL = os.environ.get('WIKIDATA_SPARQL_URL', 'https://query.wikidata.org/sparql')
KEEP = 6
MONTH = re.compile(r'href="(\d{4}-\d{2})/"')
# What a download can fail with: the connection or an HTTP error, and a gzip stream
# that breaks off (EOFError) or is corrupt (zlib.error).
FAILURES = (OSError, EOFError, ValueError, zlib.error, http.client.HTTPException)
TITLES_QUERY = """SELECT ?tvmaze ?title WHERE {
  ?item wdt:P8600 ?tvmaze .
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?title .
}"""


def fetch_titles(timeout=180):
    """{tvmaze id: English article title with underscores}, from Wikidata."""
    data = urllib.parse.urlencode({'query': TITLES_QUERY}).encode()
    request = urllib.request.Request(SPARQL, data=data, headers={
        'Accept': 'application/sparql-results+json', 'User-Agent': AGENT,
        'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        rows = json.load(response)['results']['bindings']
    titles = {}
    for row in rows:
        value = row['tvmaze']['value']
        if value.isdigit() and len(value) < 10:
            titles.setdefault(int(value), row['title']['value'].replace(' ', '_'))
    if not titles:
        raise ValueError('Wikidata returned no article titles.')
    return titles


def published(timeout=60):
    """The months the clickstream has been published for, oldest first."""
    request = urllib.request.Request(BASE + '/', headers={'User-Agent': AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return sorted(set(MONTH.findall(response.read().decode('utf-8', 'replace'))))


def count_month(lines, by_title):
    """{"a-b": count} for links between two shows' articles, both directions added."""
    pairs = {}
    for line in lines:
        prev, _, rest = line.partition('\t')
        a = by_title.get(prev)
        if a is None:
            continue
        curr, _, rest = rest.partition('\t')
        b = by_title.get(curr)
        if b is None or b == a:
            continue
        kind, _, n = rest.partition('\t')
        if kind != 'link':
            continue
        try:
            n = int(n)
        except ValueError:
            continue
        key = f'{min(a, b)}-{max(a, b)}'
        pairs[key] = pairs.get(key, 0) + n
    return pairs


def stream_month(month, by_title, timeout=120):
    url = f'{BASE}/{month}/clickstream-enwiki-{month}.tsv.gz'
    request = urllib.request.Request(url, headers={'User-Agent': AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with gzip.open(response, 'rt', encoding='utf-8', errors='replace') as lines:
            return count_month(lines, by_title)


def read(path):
    """The cache, or None when there is none; ValueError when it is not one."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, EOFError, ValueError) as exc:
        raise ValueError(f'{path.name} does not read: {exc}') from None
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('months'), dict):
        raise ValueError(f'{path.name} is not version 1 clickstream counts.')
    return data


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, separators=(',', ':'), sort_keys=True).encode()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as f:
                f.write(body)
        # mkstemp makes the file private; the refresher's files are readable by all.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def trim(cache):
    """The cache with only its latest KEEP months."""
    for month in sorted(cache['months'])[:-KEEP]:
        del cache['months'][month]
    return cache


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--cache', default='data/cointerest.json.gz')
    parser.add_argument('--months', type=int, default=3, help='latest published months to hold')
    parser.add_argument('--file', action='append', default=[], metavar='MONTH=PATH',
                        help='count a month from a local clickstream file instead of downloading it')
    parser.add_argument('--published', action='store_true',
                        help='only print the latest --months published months, as RESULT')
    args = parser.parse_args(argv)
    if args.published:
        try:
            months = published()[-args.months:]
        except FAILURES as exc:
            print(f'clickstream: failed to read the listing: {exc}', flush=True)
            return 1
        if not months:
            print('clickstream: the listing names no months', flush=True)
            return 1
        print('RESULT ' + json.dumps({'published': months}), flush=True)
        return 0
    try:
        cache = read(args.cache)
    except ValueError as exc:
        print(f'{exc}; counting it again from nothing', flush=True)
        cache = None
    cache = cache or {'version': 1, 'titles': {}, 'months': {}}
    started = time.time()
    local = dict(item.split('=', 1) for item in args.file)
    try:
        titles = fetch_titles()
        wanted = sorted(local) if local else published()[-args.months:]
    except (*FAILURES, KeyError, TypeError) as exc:
        print(f'clickstream: failed: {exc}', flush=True)
        return 1
    by_title = {title: show for show, title in titles.items()}
    cache['titles'] = {str(k): v for k, v in sorted(titles.items())}
    fetched, skipped = [], {}
    for month in wanted:
        if month in cache['months'] and month not in local:
            continue
        t = time.time()
        try:
            if month in local:
                with gzip.open(local[month], 'rt', encoding='utf-8', errors='replace') as lines:
                    counts = count_month(lines, by_title)
            else:
                counts = stream_month(month, by_title)
        except FAILURES as exc:
            print(f'{month}: skipped ({exc}); it will be tried again', file=sys.stderr, flush=True)
            skipped[month] = str(exc) or type(exc).__name__
            continue
        cache['months'][month] = dict(sorted(counts.items()))
        write(args.cache, trim(cache))
        fetched.append(month)
        print(f'{month}: {len(counts):,} show pairs in {time.time() - t:.0f}s', flush=True)
    write(args.cache, trim(cache))
    held = sorted(cache['months'])
    print(f'{len(titles):,} shows with English articles; months held: {", ".join(held)}; '
          f'{time.time() - started:.0f}s', flush=True)
    print('RESULT ' + json.dumps({'months': held, 'wanted': wanted, 'fetched': fetched, 'skipped': skipped,
                                  'titles': len(titles), 'seconds': round(time.time() - started, 1)}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
