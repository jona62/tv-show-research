"""Facts about TVmaze's shows from Wikidata, for the recommender's taste features.

Wikidata is CC0, so unlike TMDB its facts may feed the ranking. A show is matched to
its Wikidata item by the item's TVmaze series id (P8600). A show no item names that
way is matched by the IMDb id TVmaze keeps for it (P345), but only to an item that
carries no TVmaze id of its own and that no other show reaches too. For every matched
item this fetches its genres (P136) and their superclasses (P279) two levels up, its
makers (creator P170, screenwriter P58, executive producer P1431, director P57), its
cast (P161), its franchise links (part of the series P179, media franchise P8345,
based on P144, follows P155, followed by P156, derivative work P4969, fictional
universe P1434) and, one hop further, the series, franchises and universes those
belong to, its subjects (main subject P921, narrative location P840, set in period
P2408), awards received (P166) and nominations (P1411), original broadcaster (P449),
country of origin (P495), an English label for every item any of those name, and the
show's own labels and aliases in every language, for search. The hop is what joins
House of the Dragon, based on Fire & Blood, to Game of Thrones: that book is part of
the series A Song of Ice and Fire, which Game of Thrones is based on.

Queries go one at a time to the Wikidata Query Service. Long lists travel as VALUES
batches small enough to finish far inside the service's 60 second limit, and a batch
the service still runs out of time on is split in half and asked again. A 429 waits
out its Retry-After; server errors and dropped connections back off and retry.
Standard library only.

    .venv/bin/python tools/manage.py job wikidata [--out data/wikidata.json.gz]

TV_RAW_DIR (data/raw) holds the TVmaze pages read for IMDb ids, and
WIKIDATA_SPARQL_URL replaces the endpoint, which the tests point at a fake one.
WIKIDATA_BACKOFF_SECONDS (5) is the first wait after a failed query; it doubles each
time. The last line printed is RESULT and a JSON summary; the exit status is 1 when
the fetch failed, and then nothing is written.

The cache is gzipped JSON, written whole or not at all, with sorted keys and lists
and no timestamp in the gzip header, so the same answers make the same bytes:

    {"version": 1,
     "fetched_at": "2026-09-27T12:00:00Z",       when the fetch started, UTC
     "source": "https://www.wikidata.org", "license": "CC0-1.0",
     "mapped": {"p8600": 38307, "imdb": 270},     shows matched by each route
     "labels": {"Q1079": "Breaking Bad", ...},    a label for every item named below:
                                                  English, else the "mul" default,
                                                  else the one most languages share
     "parents": {"Q959790": ["Q1257444"], ...},   P279 superclasses of each genre and
                                                  of each of those superclasses
     "belongs": {"Q55611675": ["Q45875", ...]},   the P179, P8345 and P1434 values of
                                                  every franchise link's target
     "shows": {"169": {                           TVmaze id
         "qid": "Q1079", "via": "p8600",          the item, and the route ("imdb")
         "genre": [...],                          P136
         "maker": {"P170": [...], "P58": [...], "P1431": [...], "P57": [...]},
         "cast": [...],                           P161
         "franchise": {"P179": [...], "P8345": [...], "P144": [...], "P155": [...],
                       "P156": [...], "P4969": [...], "P1434": [...]},
         "subject": {"P921": [...], "P840": [...], "P2408": [...]},
         "award": [...], "nominated": [...],      P166 and P1411
         "broadcaster": [...], "origin": [...],   P449 and P495
         "names": [["cs", "Perníkový táta"], ["en", "Breaking Bad"], ...]}}}

Lists of items hold Q-ids sorted by number. A field, or a property inside one, is
left out when Wikidata has nothing for it. Only truthy (best rank) statements count.
"names" holds each distinct language and text pair among the item's labels and
aliases, sorted. A TVmaze id Wikidata names but the raw pages lack is kept, so a show
that appears in a later catalog is covered too.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import argparse
import gzip
import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = 'https://query.wikidata.org/sparql'
AGENT = 'tv-taste-research/1.0 (https://github.com/jona62/tv-show-research)'
VERSION = 1
ENTITY = 'http://www.wikidata.org/entity/'
DIRECT = 'http://www.wikidata.org/prop/direct/'
QID = re.compile(r'Q[1-9]\d{0,11}')
IMDB = re.compile(r'tt\d{5,10}')
TVMAZE = re.compile(r'[1-9]\d{0,9}')
# Fields holding one property's items, and fields grouping several properties.
LISTS = {'genre': 'P136', 'cast': 'P161', 'award': 'P166', 'nominated': 'P1411',
         'broadcaster': 'P449', 'origin': 'P495'}
GROUPS = {'maker': ('P170', 'P58', 'P1431', 'P57'),
          'franchise': ('P179', 'P8345', 'P144', 'P155', 'P156', 'P4969', 'P1434'),
          'subject': ('P921', 'P840', 'P2408')}
# Everything but the cast, which is most of the rows, goes in one query per batch.
CLAIMS = tuple(p for field, p in LISTS.items() if field != 'cast') + tuple(p for ps in GROUPS.values() for p in ps)
# What a franchise link's target belongs to: its series, franchise and fictional universe.
BELONGS = ('P179', 'P8345', 'P1434')
BATCH = {'imdb': 2000, 'claims': 2000, 'cast': 2000, 'parents': 3000, 'labels': 2500, 'names': 1500}
PARENT_LEVELS = 2
MAX_TIMEOUTS = 12          # queries the service ran out of time on, in one fetch, before giving up
MAX_BODY = 256 << 20

# The first line of each query names it, for the logs and the tests' fake service.
Q_TVMAZE = '#tvmaze\nSELECT ?item ?id WHERE { ?item wdt:P8600 ?id . }'
# Without the hint the service joins every P345 statement against the list; with it,
# each id is looked up on its own, several times faster.
Q_IMDB = ('#imdb\nSELECT ?item ?imdb WHERE {{ hint:Query hint:optimizer "None" . '
          'VALUES ?imdb {{ {values} }} ?item wdt:P345 ?imdb . }}')
Q_CLAIMS = ('#claims\nSELECT ?item ?p ?v WHERE {{ VALUES ?item {{ {items} }} VALUES ?p {{ {props} }} '
            '?item ?p ?v . FILTER(isIRI(?v)) }}')
Q_CAST = '#cast\nSELECT ?item ?v WHERE {{ VALUES ?item {{ {items} }} ?item wdt:P161 ?v . FILTER(isIRI(?v)) }}'
Q_PARENTS = '#parents\nSELECT ?item ?v WHERE {{ VALUES ?item {{ {items} }} ?item wdt:P279 ?v . FILTER(isIRI(?v)) }}'
Q_LABELS = ('#labels\nSELECT ?item ?label WHERE {{ VALUES ?item {{ {items} }} ?item rdfs:label ?label . '
            'FILTER(LANG(?label) = "en" || LANG(?label) = "mul") }}')
Q_ANY_LABEL = '#any-labels\nSELECT ?item ?label WHERE {{ VALUES ?item {{ {items} }} ?item rdfs:label ?label . }}'
Q_NAMES = ('#names\nSELECT ?item ?name WHERE {{ VALUES ?item {{ {items} }} '
           '{{ ?item rdfs:label ?name }} UNION {{ ?item skos:altLabel ?name }} }}')


class WikidataError(Exception):
    """The service kept failing, or answered something that cannot be used."""


class QueryTimeout(WikidataError):
    """The service ran out of time on one query; a smaller batch may do."""


def iso(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def qnum(qid):
    return int(qid[1:])


def item_of(cell):
    """The Q-id a result cell names, or None for anything else: a property, an unknown
    value, a literal."""
    if not isinstance(cell, dict) or cell.get('type') != 'uri':
        return None
    value = cell.get('value') or ''
    qid = value[len(ENTITY):] if value.startswith(ENTITY) else ''
    return qid if QID.fullmatch(qid) else None


def text_of(cell):
    """A literal's text and language tag, or (None, None)."""
    if not isinstance(cell, dict) or cell.get('type') != 'literal' or not isinstance(cell.get('value'), str):
        return None, None
    return cell['value'], cell.get('xml:lang') or ''


def retry_after(value, default):
    """Seconds to wait from a Retry-After header: a number or an HTTP date, at most ten
    minutes."""
    if value:
        try:
            return min(max(float(value), 0.0), 600.0)
        except ValueError:
            try:
                wait = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
                return min(max(wait, 0.0), 600.0)
            except (TypeError, ValueError):
                pass
    return default


# Talking to the query service --------------------------------------------------------

class Sparql:
    """SELECT queries against one endpoint, one at a time, POSTed so that long VALUES
    lists fit. Counts its queries, time and bytes for the summary."""

    def __init__(self, endpoint=None, attempts=6, backoff=None, timeout=75.0, sleep=time.sleep, log=print):
        self.endpoint = endpoint or os.environ.get('WIKIDATA_SPARQL_URL') or ENDPOINT
        if backoff is None:
            backoff = float(os.environ.get('WIKIDATA_BACKOFF_SECONDS') or 5)
        self.attempts, self.backoff, self.timeout = attempts, backoff, timeout
        self.sleep, self.log = sleep, log
        # A local endpoint is the tests' fake, which no proxy should see.
        local = (urlsplit(self.endpoint).hostname or '').lower() in ('localhost', '127.0.0.1', '::1')
        self.opener = build_opener(ProxyHandler({})) if local else build_opener()
        self.queries, self.seconds, self.bytes, self.timeouts = 0, 0.0, 0, 0

    def select(self, query, split=False):
        """The result rows, a list of {variable: cell}. When the service runs out of time
        on a query that can be split, this raises QueryTimeout at once; any other query
        is retried like any other failure. Raises WikidataError once retries are spent."""
        what = query.split('\n', 1)[0].lstrip('#') or 'query'
        problem, limited, attempt = 'no answer', 0, 0
        while attempt < self.attempts:
            started, timed_out = time.monotonic(), False
            try:
                body = self._post(query)
            except HTTPError as exc:
                detail = self._error_text(exc)
                if exc.code == 429 and limited < 20:
                    limited += 1
                    wait = retry_after(exc.headers.get('Retry-After'), max(self.backoff, 1.0) * 2)
                    self.log(f'wikidata: {what}: rate limited; waiting {wait:.0f}s as asked')
                    self.sleep(wait)
                    continue
                if exc.code < 500 and exc.code != 429:
                    raise WikidataError(f'{what}: the query service answered {exc.code}: {detail[:200]}') from None
                timed_out = exc.code == 504 or 'TimeoutException' in detail
                problem = f'status {exc.code}' + (', out of time' if timed_out else '')
            except (socket.timeout, TimeoutError):
                timed_out, problem = True, 'no answer in time'
            except (URLError, OSError, http.client.HTTPException, EOFError, zlib.error) as exc:
                problem = type(exc).__name__ + (f' ({exc.reason})' if isinstance(exc, URLError) else '')
            else:
                self.queries += 1
                self.seconds += time.monotonic() - started
                self.bytes += len(body)
                try:
                    rows = json.loads(body)['results']['bindings']
                except (ValueError, KeyError, TypeError):
                    # Results stream as they are found, so a query stopped by the time
                    # limit can end in a cut-off body under a 200 status.
                    timed_out, problem = True, 'a cut-off answer'
                else:
                    if not isinstance(rows, list):
                        raise WikidataError(f'{what}: the answer holds no result rows')
                    return rows
            if timed_out and split:
                raise self._timed_out(what, problem)
            attempt += 1
            if attempt < self.attempts:
                wait = min(self.backoff * 2 ** (attempt - 1), 120.0)
                self.log(f'wikidata: {what}: {problem}; trying again in {wait:.0f}s')
                self.sleep(wait)
        raise WikidataError(f'{what}: gave up after {self.attempts} attempts ({problem})')

    def _post(self, query):
        request = Request(self.endpoint, data=urlencode({'query': query}).encode(), method='POST', headers={
            'User-Agent': AGENT, 'Accept': 'application/sparql-results+json', 'Accept-Encoding': 'gzip',
            'Content-Type': 'application/x-www-form-urlencoded'})
        with self.opener.open(request, timeout=self.timeout) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise WikidataError('an answer was larger than 256 MB')
            if (response.headers.get('Content-Encoding') or '').lower() == 'gzip':
                body = gzip.decompress(body)
        return body

    @staticmethod
    def _error_text(exc):
        try:
            raw = exc.read(1 << 16) or b''
            if (exc.headers.get('Content-Encoding') or '').lower() == 'gzip':
                raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, 1 << 16)
            return raw.decode('utf-8', 'replace')
        except Exception:
            return ''

    def _timed_out(self, what, problem):
        self.timeouts += 1
        if self.timeouts > MAX_TIMEOUTS:
            return WikidataError(f'{what}: the query service ran out of time {self.timeouts} times; giving up')
        self.log(f'wikidata: {what}: {problem}; splitting the batch')
        return QueryTimeout(what)


def batched(client, values, size, build):
    """(batch, rows) for values, size at a time. A batch the service runs out of time on
    is split in half and each half asked on its own; a single value is only retried."""
    pending = [values[i:i + size] for i in range(0, len(values), size)]
    while pending:
        batch = pending.pop(0)
        try:
            rows = client.select(build(batch), split=len(batch) > 1)
        except QueryTimeout:
            half = len(batch) // 2
            pending[:0] = [batch[:half], batch[half:]]
            continue
        yield batch, rows


def entities(qids):
    return ' '.join(f'wd:{q}' for q in qids)


# The steps of a fetch ------------------------------------------------------------------

def load_imdb(raw_dir):
    """{TVmaze id: IMDb id or None} for every show in the raw pages."""
    found = {}
    for page in sorted(Path(raw_dir).glob('page-*.json')):
        for show in json.loads(page.read_bytes()):
            if not isinstance(show, dict) or type(show.get('id')) is not int:
                continue
            ext = show.get('externals') if isinstance(show.get('externals'), dict) else {}
            imdb = ext.get('imdb')
            found[show['id']] = imdb if isinstance(imdb, str) and IMDB.fullmatch(imdb) else None
    return found


def tvmaze_items(client):
    """{TVmaze id: [items, oldest first]} from P8600, and {item: {TVmaze ids}}."""
    by_show, by_item = {}, {}
    for row in client.select(Q_TVMAZE):
        qid = item_of(row.get('item'))
        value, _lang = text_of(row.get('id'))
        if qid and value and TVMAZE.fullmatch(value):
            by_show.setdefault(int(value), set()).add(qid)
            by_item.setdefault(qid, set()).add(int(value))
    return {k: sorted(v, key=qnum) for k, v in by_show.items()}, by_item


def imdb_items(client, imdbs):
    """{IMDb id: {items}} for the ids Wikidata knows (P345)."""
    found, wanted = {}, sorted(set(imdbs))
    build = lambda batch: Q_IMDB.format(values=' '.join(f'"{i}"' for i in batch))
    for _batch, rows in batched(client, wanted, BATCH['imdb'], build):
        for row in rows:
            qid = item_of(row.get('item'))
            value, _lang = text_of(row.get('imdb'))
            if qid and value in imdbs:
                found.setdefault(value, set()).add(qid)
    return found


def match(by_show, by_item, unmatched, imdb_hits):
    """{TVmaze id: (item, route)}. P8600 first; when several items name one show, the
    oldest (lowest numbered) is taken. Then IMDb, for shows no item names: an item with
    a TVmaze id of its own already belongs to that show, and an item two shows both
    reach is left to neither. Also returns counts of the shows left out."""
    chosen = {show: (items[0], 'p8600') for show, items in by_show.items()}
    claims, skipped = {}, {'item has a TVmaze id': 0, 'item reached twice': 0}
    for show, imdb in sorted(unmatched.items()):
        if show in chosen or imdb not in imdb_hits:
            continue
        free = sorted((q for q in imdb_hits[imdb] if q not in by_item), key=qnum)
        if not free:
            skipped['item has a TVmaze id'] += 1
            continue
        claims.setdefault(free[0], []).append(show)
    for qid, shows in claims.items():
        if len(shows) > 1:
            skipped['item reached twice'] += len(shows)
        else:
            chosen[shows[0]] = (qid, 'imdb')
    return chosen, skipped


def statements(client, items):
    """{item: {property: {items}}} for every property the features use."""
    found = {}
    props = ' '.join(f'wdt:{p}' for p in CLAIMS)
    for _batch, rows in batched(client, items, BATCH['claims'],
                                lambda batch: Q_CLAIMS.format(items=entities(batch), props=props)):
        for row in rows:
            qid, value = item_of(row.get('item')), item_of(row.get('v'))
            prop = (row.get('p') or {}).get('value') or ''
            prop = prop[len(DIRECT):] if prop.startswith(DIRECT) else None
            if qid and value and prop in CLAIMS:
                found.setdefault(qid, {}).setdefault(prop, set()).add(value)
    for _batch, rows in batched(client, items, BATCH['cast'], lambda batch: Q_CAST.format(items=entities(batch))):
        for row in rows:
            qid, value = item_of(row.get('item')), item_of(row.get('v'))
            if qid and value:
                found.setdefault(qid, {}).setdefault('P161', set()).add(value)
    return found


def belonging(client, targets):
    """{item: [the series, franchises and universes it belongs to]} for franchise targets."""
    found = {}
    props = ' '.join(f'wdt:{p}' for p in BELONGS)
    for _batch, rows in batched(client, sorted(set(targets), key=qnum), BATCH['claims'],
                                lambda batch: Q_CLAIMS.format(items=entities(batch), props=props)):
        for row in rows:
            qid, value = item_of(row.get('item')), item_of(row.get('v'))
            prop = (row.get('p') or {}).get('value') or ''
            if qid and value and value != qid and prop[len(DIRECT):] in BELONGS and prop.startswith(DIRECT):
                found.setdefault(qid, set()).add(value)
    return {qid: sorted(values, key=qnum) for qid, values in found.items()}


def superclasses(client, genres, levels=PARENT_LEVELS):
    """{class: [superclasses]} for the genres and, level by level, for what they are
    subclasses of."""
    parents, frontier, seen = {}, sorted(set(genres), key=qnum), set(genres)
    for _level in range(levels):
        found = {}
        for _batch, rows in batched(client, frontier, BATCH['parents'],
                                    lambda batch: Q_PARENTS.format(items=entities(batch))):
            for row in rows:
                qid, value = item_of(row.get('item')), item_of(row.get('v'))
                if qid and value and value != qid:
                    found.setdefault(qid, set()).add(value)
        for qid, ups in found.items():
            parents[qid] = sorted(ups, key=qnum)
        frontier = sorted({p for ups in found.values() for p in ups} - seen, key=qnum)
        seen.update(frontier)
    return parents


def english_labels(client, qids):
    """{item: label}: English, else the "mul" default label, else the label the most of
    its languages share (the shortest such, then the first in code point order)."""
    labels, fallback = {}, {}
    wanted = sorted(set(qids), key=qnum)
    for _batch, rows in batched(client, wanted, BATCH['labels'], lambda batch: Q_LABELS.format(items=entities(batch))):
        for row in rows:
            qid = item_of(row.get('item'))
            text, lang = text_of(row.get('label'))
            if qid and text and text.strip():
                (labels if lang == 'en' else fallback)[qid] = ' '.join(text.split())
    for qid, text in fallback.items():
        labels.setdefault(qid, text)
    missing = [q for q in wanted if q not in labels]
    texts = {}
    for _batch, rows in batched(client, missing, BATCH['labels'], lambda batch: Q_ANY_LABEL.format(items=entities(batch))):
        for row in rows:
            qid = item_of(row.get('item'))
            text, _lang = text_of(row.get('label'))
            if qid and text and text.strip():
                counts = texts.setdefault(qid, {})
                text = ' '.join(text.split())
                counts[text] = counts.get(text, 0) + 1
    for qid, counts in texts.items():
        labels[qid] = min(counts, key=lambda t: (-counts[t], len(t), t))
    return labels


def all_names(client, items):
    """{item: {(language, text)}} from the item's labels and aliases."""
    names = {}
    for _batch, rows in batched(client, items, BATCH['names'], lambda batch: Q_NAMES.format(items=entities(batch))):
        for row in rows:
            qid = item_of(row.get('item'))
            text, lang = text_of(row.get('name'))
            if qid and text and text.strip():
                names.setdefault(qid, set()).add((lang, ' '.join(text.split())))
    return names


def fetch(raw_dir, client, log=print, now=None):
    """The whole cache, as a dict ready to write."""
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    mark = [time.monotonic()]

    def stage(line):
        log(f'wikidata: {line} ({time.monotonic() - mark[0]:.1f}s, {client.queries} queries so far)')
        mark[0] = time.monotonic()

    by_show, by_item = tvmaze_items(client)
    if not by_show:
        raise WikidataError('no item carries a TVmaze id, which cannot be right')
    raw = load_imdb(raw_dir)
    unmatched = {show: imdb for show, imdb in raw.items() if imdb and show not in by_show}
    stage(f'{len(by_show):,} TVmaze ids on {len(by_item):,} items, {sum(1 for s in by_show if s in raw):,} of them '
          f'among the {len(raw):,} raw shows; {len(unmatched):,} other raw shows have an IMDb id')
    imdb_hits = imdb_items(client, set(unmatched.values())) if unmatched else {}
    chosen, skipped = match(by_show, by_item, unmatched, imdb_hits)
    routes = {route: sum(1 for _q, r in chosen.values() if r == route) for route in ('p8600', 'imdb')}
    stage(f"matched {routes['p8600']:,} shows by TVmaze id and {routes['imdb']:,} by IMDb id; "
          f"by IMDb id, {skipped['item has a TVmaze id']:,} reached an item with a TVmaze id of its own "
          f"and {skipped['item reached twice']:,} an item another show reached too")
    items = sorted({qid for qid, _route in chosen.values()}, key=qnum)
    facts = statements(client, items)
    stage(f'{sum(len(v) for props in facts.values() for v in props.values()):,} statements for {len(items):,} items')
    targets = {v for props in facts.values() for p in GROUPS['franchise'] for v in props.get(p, ())}
    belongs = belonging(client, targets)
    stage(f'{len(targets):,} franchise targets; {len(belongs):,} belong to a series, franchise or universe')
    genres = {g for props in facts.values() for g in props.get('P136', ())}
    parents = superclasses(client, genres)
    stage(f'{len(genres):,} genres; {len(parents):,} classes with superclasses')
    named = {v for props in facts.values() for values in props.values() for v in values}
    named |= {p for ups in parents.values() for p in ups} | set(parents)
    named |= {v for values in belongs.values() for v in values}
    labels = english_labels(client, named)
    stage(f'labels for {len(labels):,} of {len(named):,} items')
    names = all_names(client, items)
    stage(f'{sum(len(v) for v in names.values()):,} names for {len(names):,} items')

    shows = {}
    for show, (qid, route) in sorted(chosen.items()):
        props = facts.get(qid, {})
        entry = {'qid': qid, 'via': route}
        for field, prop in LISTS.items():
            if props.get(prop):
                entry[field] = sorted(props[prop], key=qnum)
        for field, group in GROUPS.items():
            found = {p: sorted(props[p], key=qnum) for p in group if props.get(p)}
            if found:
                entry[field] = found
        if names.get(qid):
            entry['names'] = [list(pair) for pair in sorted(names[qid])]
        shows[str(show)] = entry
    log(f'wikidata: {len(shows):,} shows from {client.queries} queries, {client.bytes / 1e6:.1f} MB of answers, '
        f'{client.seconds:.0f}s waiting on the service, {time.monotonic() - started:.0f}s in all')
    return {'version': VERSION, 'fetched_at': iso(now), 'source': 'https://www.wikidata.org', 'license': 'CC0-1.0',
            'mapped': routes, 'labels': labels, 'parents': parents, 'belongs': belongs, 'shows': shows}


# Files -----------------------------------------------------------------------------------

def encode(cache):
    body = json.dumps(cache, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return gzip.compress(body, compresslevel=9, mtime=0)


def write_atomic(path, body):
    """Whole or not at all, and readable by the apps, which run as other users."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        with open(tmp, 'wb') as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read(path):
    """A cache this module wrote, or None when there is no file. Raises ValueError when
    the file is there but is not such a cache."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError, zlib.error, ValueError) as exc:
        raise ValueError(f'{path} is not a Wikidata cache: {exc}') from None
    if not isinstance(data, dict) or data.get('version') != VERSION \
            or not all(isinstance(data.get(k), dict) for k in ('shows', 'labels', 'parents', 'belongs')):
        raise ValueError(f'{path} is not a version {VERSION} Wikidata cache.')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=ROOT / 'data' / 'wikidata.json.gz',
                        help='where the cache goes (default data/wikidata.json.gz)')
    args = parser.parse_args(argv)
    raw_dir = Path(os.environ.get('TV_RAW_DIR') or ROOT / 'data' / 'raw')
    if not any(raw_dir.glob('page-*.json')):
        print(f'No raw pages in {raw_dir}; run pipeline/jobs/download.py first.', file=sys.stderr)
        return 2
    say = lambda line: print(line, flush=True)
    client = Sparql(log=say)
    started = time.monotonic()
    try:
        cache = fetch(raw_dir, client, log=say)
    except WikidataError as exc:
        say(f'wikidata: failed: {exc}')
        return 1
    body = encode(cache)
    write_atomic(args.out, body)
    summary = {'fetched_at': cache['fetched_at'], 'shows': len(cache['shows']), 'mapped': cache['mapped'],
               'labels': len(cache['labels']), 'queries': client.queries, 'bytes': len(body),
               'seconds': round(time.monotonic() - started, 1)}
    say(f'wikidata: wrote {args.out}, {len(body) / 1e6:.1f} MB')
    say('RESULT ' + json.dumps(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
