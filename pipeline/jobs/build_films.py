"""Build films.json.gz beside the model: well-known films and film series, each with its
names, its year and what it is like, in the genre and subject keys the shows' facets use
(build_facets.py), so that Couchside's search can rank shows like a film.

    TV_FILMS=data/films.json.gz .venv/bin/python tools/manage.py job build_films

It reads TV_MODEL_OUT (data/model): facets.json.gz there says which genre and subject keys
the shows carry, and only those are kept, since a film is only ever compared with
shows. TV_FILMS names the cache pipeline/jobs/films.py writes. Without a cache, or with no
facets to map to, nothing is written. The file is gzipped JSON with no timestamp in the
gzip header, so the same inputs make the same bytes:

    {"version": 1, "date": the facets' catalog date, "wikidata_fetched_at": ISO,
     "source": "https://www.wikidata.org", "license": "CC0-1.0",
     "films": [{"qid": "Q167726", "title": "Jurassic Park", "titles": [...], "aliases": [...],
                "year": 1993, "kind": "film", "links": 99, "animated": false,
                "genre": {"science fiction": 1.0, "adventure": 1.0, ...},
                "subject": {"Q430": 1.0}, "topics": ["cloning", "dinosaur"]}, ...]}

Genres are keyed as build_facets.py keys the shows', by their label with the medium
stripped ("post-apocalyptic film" is "post apocalyptic"), at 1 for the film's own and
at half the value of the class below for superclasses, two levels up. Subjects are its
main subjects (P921), by Q-id, at 1. A series also takes on what its films are like: a
genre or subject a third or more of them carry counts at the share of them that do,
unless the series names it itself. Topics are the English labels of its main subjects,
whether shows carry them or not, for a search to look for in the shows' own summaries:
at most 5, and none that is a place, a person or an event (a label with a capital).

The title is the English label, else the default one, else an original title (P1476);
other titles are the default label and original titles, at most 3, and aliases the
English aliases, at most 5, which a search trusts less: Wikidata has "Alien" among Taxi
Driver's. Every name loses a trailing qualifier
such as "(film)" and is 2 to 80 characters. Films are listed best known first; one with
no genre or subject the shows carry is left out.
"""
from pathlib import Path
import gzip
import json
import os
import re
import sys
import unicodedata

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
from .build_facets import PARENT_LEVELS, PARENT_SHARE, canonical_genre  # noqa: E402
from . import films as fetcher                                          # noqa: E402

VERSION = 1
MEMBERS = 1 / 3         # share of a series' films that must carry a genre for the series to
MOST_TITLES = 3         # other titles kept: the default label and original titles
MOST_ALIASES = 5        # English aliases kept
MOST_TOPICS = 5         # main subjects kept as words
NAME_LENGTH = (2, 80)
_QUALIFIER = re.compile(r'\s*[(\[][^()\[\]]*[)\]]$')


def fold(text):
    """A name with case, diacritics, spaces and punctuation set aside, for comparing."""
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if c.isalnum())


def vocabulary(model):
    """(date, genre keys, subject keys) the model's shows carry, from facets.json.gz, or
    None when the model has no facets."""
    path = Path(model) / 'facets.json.gz'
    if not path.is_file():
        return None
    meta = json.loads(gzip.decompress(path.read_bytes()))
    families = meta['families']
    keys = {name: set() for name in ('genre', 'subject')}
    for family, key, _label, _df in meta['tokens']:
        if families[family] in keys:
            keys[families[family]].add(key)
    return meta.get('date'), keys['genre'], keys['subject']


class Genres:
    """Genre keys for the cache's genre items, and the weights their superclasses add,
    as build_facets.Genres has them for the shows, over the shows' own genre keys."""

    def __init__(self, cache, known):
        self.labels, self.parents, self.known, self.keys = cache['labels'], cache['parents'], known, {}

    def key(self, qid):
        if qid not in self.keys:
            label = self.labels.get(qid)
            self.keys[qid] = canonical_genre(label) if label else None
        return self.keys[qid]

    def weights(self, genres):
        found = {}

        def add(key, weight):
            if key in self.known and weight > found.get(key, 0.0):
                found[key] = weight
        for genre in genres:
            add(self.key(genre), 1.0)
            frontier, weight = {genre}, 1.0
            for _level in range(PARENT_LEVELS):
                weight *= PARENT_SHARE
                frontier = {p for q in frontier for p in self.parents.get(q, ())}
                for parent in frontier:
                    add(self.key(parent), weight)
        return found


def names_of(entry):
    """(title, other titles, aliases) from a cached film's names: the title is its English
    label, else its default label, else an original title; other titles are its default
    label and original titles, and aliases its English aliases."""
    found = {'label en': [], 'label mul': [], 'title': [], 'alias': []}
    for kind, lang, text in entry.get('names', ()):
        if kind == 'label' and lang in ('en', 'mul'):
            found[f'label {lang}'].append(text)
        elif kind in ('title', 'alias'):
            found[kind].append(text)
    seen = set()

    def keep(texts, most):
        kept = []
        for text in texts:
            text = _QUALIFIER.sub('', ' '.join(text.split()))
            key = fold(text)
            if NAME_LENGTH[0] <= len(text) <= NAME_LENGTH[1] and key and key not in seen and len(kept) < most:
                seen.add(key)
                kept.append(text)
        return kept
    first = keep(found['label en'] + found['label mul'] + found['title'] + found['alias'], 1)
    if not first:
        return None, [], []
    return first[0], keep(found['label mul'] + found['title'], MOST_TITLES), keep(found['alias'], MOST_ALIASES)


def topics_of(qids, labels):
    """The words for a film's main subjects, as a search would type them: their English
    labels, those that are no place, person or event (which start with a capital)."""
    found = []
    for qid in qids:
        label = ' '.join((labels.get(qid) or '').split())
        if label[:1].islower() and 2 < len(label) <= 40 and label not in found:
            found.append(label)
    return found[:MOST_TOPICS]


def build(cache, genre_keys, subject_keys):
    """The film list, best known first, from a film cache and the keys the shows carry."""
    genres = Genres(cache, genre_keys)
    entries = cache['films']
    own = {}
    for qid, entry in entries.items():
        subjects = {s: 1.0 for s in entry.get('subject', ()) if s in subject_keys}
        own[qid] = (genres.weights(entry.get('genre', ())), subjects)
    members = {}
    for qid, entry in entries.items():
        for series in entry.get('part_of', ()):
            members.setdefault(series, []).append(qid)
    out = []
    for qid, entry in entries.items():
        title, titles, aliases = names_of(entry)
        if not title:
            continue
        genre, subject = dict(own[qid][0]), dict(own[qid][1])
        films = members.get(qid, []) if entry['kind'] == 'series' else []
        for which, mine in ((0, genre), (1, subject)):
            shares = {}
            for film in films:
                for key, weight in own[film][which].items():
                    shares[key] = shares.get(key, 0.0) + weight / len(films)
            for key, share in shares.items():
                if share >= MEMBERS and share > mine.get(key, 0.0):
                    mine[key] = round(share, 3)
        if not genre and not subject:
            continue
        # Every main subject, the shows' or not, as words: simulated reality is no show's
        # Wikidata subject, but summaries say it.
        said = list(entry.get('subject', ()))
        if films:
            counts = {}
            for film in films:
                for s in entries[film].get('subject', ()):
                    counts[s] = counts.get(s, 0) + 1
            said += sorted((s for s, n in counts.items() if n / len(films) >= MEMBERS and s not in said),
                           key=lambda s: (-counts[s], s))
        record = {'qid': qid, 'title': title, 'titles': titles, 'aliases': aliases, 'kind': entry['kind'],
                  'links': entry['links'], 'animated': bool(entry.get('animated')) or 'animation' in genre or 'anime' in genre,
                  'genre': dict(sorted(genre.items())), 'subject': dict(sorted(subject.items())),
                  'topics': topics_of(said, cache['labels'])}
        if entry.get('year'):
            record['year'] = entry['year']
        out.append(record)
    out.sort(key=lambda f: (-f['links'], fetcher.wikidata.qnum(f['qid'])))
    return out


def encode(value):
    return gzip.compress(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode(),
                         compresslevel=9, mtime=0)


def main():
    model = Path(os.environ.get('TV_MODEL_OUT') or ROOT / 'data/model')
    source = os.environ.get('TV_FILMS')
    if not source:
        print('TV_FILMS is not set; no film index built.', flush=True)
        return 0
    try:
        cache = fetcher.read(source)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if cache is None:
        print(f'No film cache at {source}; no film index built.', flush=True)
        return 0
    known = vocabulary(model)
    if known is None:
        print(f'No facets in {model} to map films to; no film index built.', flush=True)
        return 0
    date, genre_keys, subject_keys = known
    found = build(cache, genre_keys, subject_keys)
    if not found:
        print('No film carries a genre or subject the shows have; no film index built.', flush=True)
        return 0
    body = encode({'version': VERSION, 'date': date, 'wikidata_fetched_at': cache.get('fetched_at'),
                   'source': 'https://www.wikidata.org', 'license': 'CC0-1.0', 'films': found})
    fetcher.wikidata.write_atomic(model / 'films.json.gz', body)
    series = sum(1 for f in found if f['kind'] == 'series')
    print(f"{len(found):,} of {len(cache['films']):,} films and series kept ({series:,} series), "
          f'{sum(len(f["genre"]) for f in found):,} genre and {sum(len(f["subject"]) for f in found):,} subject '
          f'links; films.json.gz {len(body) / 1e6:.2f} MB', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
