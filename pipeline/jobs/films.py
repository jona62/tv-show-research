"""Well-known films from Wikidata, so that a search for a film can find shows like it.

The catalogue is television only, so a search for Mad Max or Jurassic Park names
nothing in it. Their Wikidata genres and main subjects say what they are like, on the
same terms as the shows' own (build_facets.py), and build_films.py turns them into the
model's films.json.gz for Couchside's search.

This fetches every film with at least FILM_LINKS sitelinks (Wikipedia articles and the
like, a fair measure of how well known it is) and every film series, trilogy and film
franchise with at least SERIES_LINKS, and for each: its English (or default) label and
English aliases, its original titles (P1476, in their own languages), the year it first
came out (P577), its genres (P136) and their superclasses two levels up, its main
subjects (P921), and the series and franchises it is part of (P179, P8345), which let a
series take on what its films are like. The client, its batches, its retries and its
User-Agent are wikidata.py's.

    .venv/bin/python tools/manage.py job films [--out data/films.json.gz]

WIKIDATA_SPARQL_URL and WIKIDATA_BACKOFF_SECONDS work as they do for wikidata.py. The
last line printed is RESULT and a JSON summary; the exit status is 1 when the fetch
failed, and then nothing is written.

The cache is gzipped JSON, written whole or not at all, with sorted keys and lists
and no timestamp in the gzip header, so the same answers make the same bytes:

    {"version": 1,
     "fetched_at": "2026-09-29T04:00:00Z",       when the fetch started, UTC
     "source": "https://www.wikidata.org", "license": "CC0-1.0",
     "labels": {"Q130232": "drama film", ...},    English labels of genres, their
                                                  superclasses and subjects
     "parents": {"Q959790": ["Q1257444"], ...},   P279 superclasses of each genre and
                                                  of each of those superclasses
     "films": {"Q167726": {
         "kind": "film",                          "series" for a series, trilogy or franchise
         "links": 99,                             sitelinks
         "animated": true,                        only for an animated or anime film
         "year": 1993,                            earliest P577, when there is one
         "names": [["label", "en", "Jurassic Park"],   English and default labels, English
                   ["alias", "en", "JP"], ...],   aliases and original titles ("title")
         "genre": [...], "subject": [...],        P136 and P921
         "part_of": [...]}}}                      P179 and P8345 values that are in the cache too

Fields Wikidata has nothing for are left out. Only truthy (best rank) statements count.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import gzip
import json
import sys
import time
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
from . import wikidata                                                   # noqa: E402
from .wikidata import WikidataError, batched, entities, item_of, qnum, text_of  # noqa: E402

VERSION = 1
# Film, animated film, anime film and animated feature film; film series, film trilogy
# and film franchise. A media franchise can be a game's or a book's, so it stays out:
# its films carry its name.
FILM_CLASSES = ('Q11424', 'Q202866', 'Q20650540', 'Q29168811')
SERIES_CLASSES = ('Q24856', 'Q13593818', 'Q130371093')
ANIMATED = ('Q202866', 'Q20650540', 'Q29168811')
# About 9,000 films have 20 sitelinks or more (The Godfather has 132, Train to Busan 52);
# series are written about less, and 5 keeps some 250, Mad Max's (23) among them.
FILM_LINKS = 20
SERIES_LINKS = 5
# Genres and main subjects; the series and franchises a film is part of.
CLAIMS = ('P136', 'P921', 'P179', 'P8345')
BATCH = {'claims': 2000, 'dates': 2000, 'names': 1500}

Q_FILMS = ('#films\nSELECT ?item ?class ?links WHERE {{ VALUES ?class {{ {classes} }} '
           '?item wdt:P31 ?class ; wikibase:sitelinks ?links . FILTER(?links >= {least}) }}')
Q_DATES = '#dates\nSELECT ?item ?date WHERE {{ VALUES ?item {{ {items} }} ?item wdt:P577 ?date . }}'
Q_TITLES = '#titles\nSELECT ?item ?title WHERE {{ VALUES ?item {{ {items} }} ?item wdt:P1476 ?title . }}'
Q_FILM_NAMES = ('#film-names\nSELECT ?item ?name ?alias WHERE {{ VALUES ?item {{ {items} }} '
                '{{ ?item rdfs:label ?name BIND("label" AS ?alias) }} UNION '
                '{{ ?item skos:altLabel ?name BIND("alias" AS ?alias) }} '
                'FILTER(LANG(?name) = "en" || LANG(?name) = "mul") }}')


def found_films(client):
    """{item: (kind, sitelinks, animated)} for the films and the series well known enough."""
    found, drawn = {}, set()
    for classes, least, kind in ((FILM_CLASSES, FILM_LINKS, 'film'), (SERIES_CLASSES, SERIES_LINKS, 'series')):
        rows = client.select(Q_FILMS.format(classes=' '.join(f'wd:{c}' for c in classes), least=least))
        for row in rows:
            qid = item_of(row.get('item'))
            links, _lang = text_of(row.get('links'))
            if qid and links and links.isdigit():
                # An item that is both a film and a series is taken as the series.
                if kind == 'series' or qid not in found:
                    found[qid] = (kind, int(links))
                if item_of(row.get('class')) in ANIMATED:
                    drawn.add(qid)
    return {qid: (kind, links, qid in drawn) for qid, (kind, links) in found.items()}


def claims(client, items):
    """{item: {property: {items}}} for CLAIMS."""
    found = {}
    props = ' '.join(f'wdt:{p}' for p in CLAIMS)
    for _batch, rows in batched(client, items, BATCH['claims'],
                                lambda batch: wikidata.Q_CLAIMS.format(items=entities(batch), props=props)):
        for row in rows:
            qid, value = item_of(row.get('item')), item_of(row.get('v'))
            prop = (row.get('p') or {}).get('value') or ''
            prop = prop[len(wikidata.DIRECT):] if prop.startswith(wikidata.DIRECT) else None
            if qid and value and prop in CLAIMS:
                found.setdefault(qid, {}).setdefault(prop, set()).add(value)
    return found


def years(client, items):
    """{item: the earliest year of its publication dates}."""
    found = {}
    for _batch, rows in batched(client, items, BATCH['dates'], lambda batch: Q_DATES.format(items=entities(batch))):
        for row in rows:
            qid = item_of(row.get('item'))
            text, _lang = text_of(row.get('date'))
            if qid and text and text[:4].isdigit() and text[4:5] == '-':
                year = int(text[:4])
                if 1870 <= year <= 2100 and year < found.get(qid, 9999):
                    found[qid] = year
    return found


def names(client, items):
    """{item: {(kind, language, text)}}: English and default labels ('label') and aliases
    ('alias'), and original titles ('title') in their own languages."""
    found = {}
    for _batch, rows in batched(client, items, BATCH['names'], lambda batch: Q_FILM_NAMES.format(items=entities(batch))):
        for row in rows:
            qid = item_of(row.get('item'))
            text, lang = text_of(row.get('name'))
            kind, _lang = text_of(row.get('alias'))
            if qid and text and text.strip() and kind in ('label', 'alias'):
                found.setdefault(qid, set()).add((kind, lang, ' '.join(text.split())))
    for _batch, rows in batched(client, items, BATCH['names'], lambda batch: Q_TITLES.format(items=entities(batch))):
        for row in rows:
            qid = item_of(row.get('item'))
            text, lang = text_of(row.get('title'))
            if qid and text and text.strip():
                found.setdefault(qid, set()).add(('title', lang or '', ' '.join(text.split())))
    return found


def fetch(client, log=print, now=None):
    """The whole cache, as a dict ready to write."""
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    mark = [time.monotonic()]

    def stage(line):
        log(f'films: {line} ({time.monotonic() - mark[0]:.1f}s, {client.queries} queries so far)')
        mark[0] = time.monotonic()

    films = found_films(client)
    if not films:
        # The refresher also refuses a fetch with far fewer films than the last.
        raise WikidataError('no well-known films at all, which cannot be right')
    items = sorted(films, key=qnum)
    stage(f"{sum(1 for k, _l, _a in films.values() if k == 'film'):,} films with {FILM_LINKS}+ sitelinks and "
          f"{sum(1 for k, _l, _a in films.values() if k == 'series'):,} series with {SERIES_LINKS}+")
    facts = claims(client, items)
    stage(f'{sum(len(v) for props in facts.values() for v in props.values()):,} statements')
    dated = years(client, items)
    titled = names(client, items)
    stage(f'years for {len(dated):,} and names for {len(titled):,}')
    genres = {g for props in facts.values() for g in props.get('P136', ())}
    parents = wikidata.superclasses(client, genres)
    subjects = {s for props in facts.values() for s in props.get('P921', ())}
    labels = wikidata.english_labels(client, genres | subjects | set(parents)
                                     | {p for ups in parents.values() for p in ups})
    stage(f'{len(genres):,} genres, {len(subjects):,} subjects, labels for {len(labels):,}')

    out = {}
    for qid in items:
        kind, links, animated = films[qid]
        props = facts.get(qid, {})
        entry = {'kind': kind, 'links': links}
        if animated:
            entry['animated'] = True
        if qid in dated:
            entry['year'] = dated[qid]
        if titled.get(qid):
            entry['names'] = [list(name) for name in sorted(titled[qid])]
        for field, prop in (('genre', 'P136'), ('subject', 'P921')):
            if props.get(prop):
                entry[field] = sorted(props[prop], key=qnum)
        part_of = {v for p in ('P179', 'P8345') for v in props.get(p, ()) if v in films and v != qid}
        if part_of:
            entry['part_of'] = sorted(part_of, key=qnum)
        out[qid] = entry
    log(f'films: {len(out):,} films and series from {client.queries} queries, {client.bytes / 1e6:.1f} MB of answers, '
        f'{client.seconds:.0f}s waiting on the service, {time.monotonic() - started:.0f}s in all')
    return {'version': VERSION, 'fetched_at': wikidata.iso(now), 'source': 'https://www.wikidata.org',
            'license': 'CC0-1.0', 'labels': labels, 'parents': parents, 'films': out}


def read(path):
    """A cache this module wrote, or None when there is no file. Raises ValueError when
    the file is there but is not such a cache."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError, zlib.error, ValueError) as exc:
        raise ValueError(f'{path} is not a film cache: {exc}') from None
    if not isinstance(data, dict) or data.get('version') != VERSION \
            or not all(isinstance(data.get(k), dict) for k in ('films', 'labels', 'parents')):
        raise ValueError(f'{path} is not a version {VERSION} film cache.')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=ROOT / 'data' / 'films.json.gz',
                        help='where the cache goes (default data/films.json.gz)')
    args = parser.parse_args(argv)
    say = lambda line: print(line, flush=True)
    client = wikidata.Sparql(log=say)
    started = time.monotonic()
    try:
        cache = fetch(client, log=say)
    except WikidataError as exc:
        say(f'films: failed: {exc}')
        return 1
    body = wikidata.encode(cache)
    wikidata.write_atomic(args.out, body)
    summary = {'fetched_at': cache['fetched_at'], 'films': len(cache['films']),
               'series': sum(1 for f in cache['films'].values() if f['kind'] == 'series'),
               'queries': client.queries, 'bytes': len(body), 'seconds': round(time.monotonic() - started, 1)}
    say(f'films: wrote {args.out}, {len(body) / 1e6:.1f} MB')
    say('RESULT ' + json.dumps(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
