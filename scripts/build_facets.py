"""Build the taste facets beside the model: Wikidata's genres, makers, cast, franchises,
subjects and awards, and TVmaze's networks, one sparse row per catalog show.

    .venv/bin/python scripts/build_facets.py

It writes three files into TV_MODEL_OUT (model, which holds the catalog.json.gz read
here), all gzipped with no timestamp in the header, so the same inputs make the same
bytes:

  facets.bin.gz    the vectors.bin.gz layout: struct '<III' (rows, cols, nnz), then
                   CSR indptr u32 (rows + 1), indices u32 (nnz), data f32 (nnz), then
                   CSC indptr u32 (cols + 1), indices u32 (nnz), data f32 (nnz). Row i
                   is the catalog's show i; indices ascend within each row and column.
  facets.json.gz   {"version": 1, "date": the catalog's, "wikidata_fetched_at": ISO or
                   null, "families": [...], "tokens": [[family index, key, label, df],
                   ...] with the list index as the column, "coverage": {family: shows
                   with at least one of its tokens}, "linked": shows with Wikidata data}
  search.json.gz   {"version": 1, "aliases": {"<TVmaze id>": [names, ...]}}: Wikidata
                   labels and aliases in every language, for search

Families, each normalised on its own so that its part of a dot product between two
rows is that family's cosine similarity:

  genre      P136 genres, keyed by their label with the medium stripped, so that
             "crime television series", "crime film" and "crime fiction" are all
             "crime" and "comedy anime and manga" is "comedy", while "police
             procedural" or "isekai" stay as they are. A genre's superclasses (P279)
             count at half the value of the class below them, two levels up, but only
             when they are some show's genre in their own right, which keeps abstract
             classes such as "work of art" out.
  maker      creators (P170) at 1, screenwriters (P58), executive producers (P1431)
             and directors (P57) at 0.6, keyed by Q-id
  cast       cast members (P161)
  franchise  what the show is part of, belongs to, is based on, follows, is followed
             by, spun off into or takes place in (P179, P8345, P144, P155, P156,
             P4969, P1434), and the show's own item, so a spin-off naming its parent
             and a parent naming its spin-off share tokens. The series, franchises and
             universes those targets belong to count at half value, which joins House
             of the Dragon (based on Fire & Blood, part of A Song of Ice and Fire) to
             Game of Thrones (based on A Song of Ice and Fire).
  subject    main subjects (P921), narrative locations (P840), periods (P2408)
  network    the TVmaze network or web channel, keyed "tvmaze-network-20" or
             "tvmaze-web-1" and labelled with its name, for every show that has one
  award      awards received (P166) at 1 and nominations (P1411) at 0.5

A token's value is ln(N / df), N being the catalog's size and df the number of its
shows that have the token, times the multiplier above. Tokens fewer than two shows
have are dropped: they cannot link two shows. A token repeated through several
routes keeps its highest multiplier.

An alias loses any trailing qualifier in brackets, "(TV series)" and the like, and is
kept when it is 2 to 80 characters long and differs from the TVmaze name, and from
every alias kept before it, once case, diacritics, spaces and punctuation are set
aside. English names come first, then other names in Latin script, then the rest;
within each, the names the most languages use; at most 12 a show.

TV_RAW_DIR (data/raw) holds the TVmaze pages the networks come from, and TV_WIKIDATA
names the cache scripts/wikidata.py writes. Without one the files are still written,
from TVmaze alone: network tokens and no aliases.
"""
from pathlib import Path
import gzip
import json
import math
import os
import re
import struct
import sys
import unicodedata

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import wikidata                                                   # noqa: E402

VERSION = 1
FAMILIES = ('genre', 'maker', 'cast', 'franchise', 'subject', 'network', 'award')
MAKERS = {'P170': 1.0, 'P58': 0.6, 'P1431': 0.6, 'P57': 0.6}
AWARDS = {'award': 1.0, 'nominated': 0.5}
FRANCHISE = ('P179', 'P8345', 'P144', 'P155', 'P156', 'P4969', 'P1434')
SUBJECT = ('P921', 'P840', 'P2408')
PARENT_SHARE = 0.5          # a genre's superclass, and what a franchise target belongs to
PARENT_LEVELS = 2
MIN_DF = 2
MAX_ALIASES = 12
ALIAS_LENGTH = (2, 80)

# Genre labels name a medium as often as a genre. These go, wherever they stand as
# words of their own; the phrases protected first keep the words that belong to them.
PROTECTED = {'science fiction': 'science_fiction', 'speculative fiction': 'speculative_fiction',
             'non-fiction': 'nonfiction', 'weird fiction': 'weird_fiction', 'flash fiction': 'flash_fiction',
             'climate fiction': 'climate_fiction', 'film noir': 'noir'}
MEDIUM = ('anime and manga', 'television programme', 'television program', 'television series',
          'television serial', 'television show', 'tv programme', 'tv program', 'tv series', 'tv show',
          'web series', 'radio programme', 'radio program', 'radio series', 'on television', 'television',
          'radio', 'films', 'film', 'fiction', 'anime', 'manga', 'series', 'serial', 'programme', 'program',
          'work', 'genre')
# Labels that are a medium and nothing else, where the medium is the point.
WHOLE = {'anime and manga': 'anime', 'anime': 'anime', 'manga': 'anime', 'animation': 'animation',
         'animated series': 'animation', 'animated television series': 'animation', 'animated film': 'animation',
         'cartoon': 'animation'}
SYNONYMS = {'romantic': 'romance', 'animated': 'animation', 'adult animated': 'adult animation',
            'westerns': 'western', 'lgbt': 'lgbtq', 'lgbtq+': 'lgbtq', 'lgbtqia+': 'lgbtq', 'gay': 'lgbtq',
            'homosexuality': 'lgbtq', 'sci fi': 'science fiction', 'reality show': 'reality', 'sport': 'sports',
            'biographical': 'biography', 'satirical': 'satire', 'humor': 'comedy', 'humour': 'comedy'}
USELESS = {'', 'television', 'program', 'series', 'serial', 'show', 'fiction', 'genre', 'work', 'of art',
           'creative', 'audiovisual', 'narrative', 'art', 'arts', 'information', 'broadcasting', 'broadcast',
           'entertainment', 'literary', 'literature', 'visual', 'media', 'mass media', 'specialty channel',
           'channel', 'network', 'station', 'episode', 'programming', 'block', 'production', 'script', 'style',
           'video', 'audio', 'intellectual', 'written', 'dramatic', 'derivative', 'adaptation', 'artwork'}
_PROTECT = re.compile('|'.join(re.escape(k) for k in sorted(PROTECTED, key=len, reverse=True)))
_MEDIUM = re.compile(r'(?<![\w-])(?:' + '|'.join(re.escape(m) for m in MEDIUM) + r')(?![\w-])')
_QID = re.compile(r'Q[1-9]\d*')
_QUALIFIER = re.compile(r'\s*[(\[][^()\[\]]*[)\]]$')


def canonical_genre(label):
    """The genre key for a label: lowercase, the medium stripped, hyphens read as spaces.
    None for a label that says nothing about taste."""
    text = ' '.join(str(label).casefold().split())
    if text in WHOLE:
        return WHOLE[text]
    text = _PROTECT.sub(lambda m: PROTECTED[m[0]], text)
    text = _MEDIUM.sub(' ', text)
    text = re.sub(r'-related(?![\w-])', ' ', text)
    text = text.replace('_', ' ').replace('-', ' ')
    text = ' '.join(text.split()).strip(' ,:;/&')
    text = re.sub(r'^(?:and|or|&)\s+|\s+(?:and|or|&)$', '', text)
    text = SYNONYMS.get(text, text)
    # What is left of "genre of creative works" and the like is a fragment, not a genre.
    return None if text in USELESS or text.startswith('of ') else text


# Reading the inputs -----------------------------------------------------------------

def read_catalog(model):
    """The catalog's date and its shows as (id, name) pairs, in order, without keeping
    every show object: each is reduced as it is parsed."""
    def compact(pairs):
        keys = {k for k, _v in pairs}
        if {'id', 'name', 'genres'} <= keys:
            found = dict(pairs)
            return (found['id'], found['name'])
        return dict(pairs)
    with gzip.open(Path(model) / 'catalog.json.gz', 'rt', encoding='utf-8') as f:
        data = json.load(f, object_pairs_hook=compact)
    return data['date'], data['shows']


def read_channels(raw_dir):
    """{show id: [(key, name)]}: the TVmaze network and web channel of every show."""
    found = {}
    pages = sorted(Path(raw_dir).glob('page-*.json'))
    if not pages:
        raise SystemExit(f'No raw pages in {raw_dir}. Run scripts/download.py first.')
    for page in pages:
        for show in json.loads(page.read_bytes()):
            if not isinstance(show, dict) or type(show.get('id')) is not int:
                continue
            channels = []
            for field, kind in (('network', 'network'), ('webChannel', 'web')):
                channel = show.get(field)
                if isinstance(channel, dict) and type(channel.get('id')) is int:
                    key = f"tvmaze-{kind}-{channel['id']}"
                    name = channel.get('name') if isinstance(channel.get('name'), str) else ''
                    channels.append((key, ' '.join(name.split()) or key))
            found[show['id']] = channels
    return found


# Tokens --------------------------------------------------------------------------------

class Genres:
    """Genre keys for a cache's genre items, and the weights their superclasses add."""

    def __init__(self, cache):
        self.labels = cache['labels'] if cache else {}
        self.parents = cache['parents'] if cache else {}
        self.keys = {}
        direct = {g for entry in (cache['shows'].values() if cache else ()) for g in entry.get('genre', ())}
        # A superclass counts only when it is some show's genre in its own right.
        self.vocabulary = {self.key(g) for g in direct} | set(WHOLE.values())
        self.vocabulary.discard(None)

    def key(self, qid):
        if qid not in self.keys:
            label = self.labels.get(qid)
            self.keys[qid] = canonical_genre(label) if label else None
        return self.keys[qid]

    def weights(self, genres):
        found = {}

        def add(key, weight):
            if key and weight > found.get(key, 0.0):
                found[key] = weight
        for genre in genres:
            add(self.key(genre), 1.0)
            frontier, weight = {genre}, 1.0
            for _level in range(PARENT_LEVELS):
                weight *= PARENT_SHARE
                frontier = {p for q in frontier for p in self.parents.get(q, ())}
                for parent in frontier:
                    key = self.key(parent)
                    if key in self.vocabulary:
                        add(key, weight)
        return found


def show_tokens(entry, genres, channels, belongs=None):
    """{family: {key: multiplier}} for one show. entry is its cache record or None, and
    belongs the cache's {franchise target: what it belongs to}."""
    tokens = {family: {} for family in FAMILIES}

    def add(family, key, weight):
        if weight > tokens[family].get(key, 0.0):
            tokens[family][key] = weight
    if entry:
        tokens['genre'] = genres.weights(entry.get('genre', ()))
        for prop, weight in MAKERS.items():
            for qid in (entry.get('maker') or {}).get(prop, ()):
                add('maker', qid, weight)
        for qid in entry.get('cast', ()):
            add('cast', qid, 1.0)
        for prop in FRANCHISE:
            for qid in (entry.get('franchise') or {}).get(prop, ()):
                add('franchise', qid, 1.0)
                for group in (belongs or {}).get(qid, ()):
                    add('franchise', group, PARENT_SHARE)
        add('franchise', entry['qid'], 1.0)
        for prop in SUBJECT:
            for qid in (entry.get('subject') or {}).get(prop, ()):
                add('subject', qid, 1.0)
        for field, weight in AWARDS.items():
            for qid in entry.get(field, ()):
                add('award', qid, weight)
    for key, _name in channels:
        add('network', key, 1.0)
    return tokens


def token_order(token):
    family, key = token
    return (family, 0, int(key[1:]), '') if _QID.fullmatch(key) else (family, 1, 0, key)


def build(shows, channels, cache=None):
    """The facet matrix for catalog shows [(id, name)], as a dict of numpy arrays and
    token metadata. channels is read_channels(); cache a Wikidata cache or None."""
    n = len(shows)
    genres = Genres(cache)
    entries = cache['shows'] if cache else {}
    belongs = cache['belongs'] if cache else {}
    rows, channel_names = [], {}
    for show_id, _name in shows:
        mine = channels.get(show_id, ())
        for key, name in mine:
            channel_names.setdefault(key, name)
        found = show_tokens(entries.get(str(show_id)), genres, mine, belongs)
        rows.append({(f, key): w for f, family in enumerate(FAMILIES) for key, w in found[family].items()})
    df = {}
    for row in rows:
        for token in row:
            df[token] = df.get(token, 0) + 1
    kept = sorted((t for t, count in df.items() if count >= MIN_DF and math.log(n / count) > 0), key=token_order)
    column = {t: c for c, t in enumerate(kept)}
    idf = {t: math.log(n / df[t]) for t in kept}
    labels = cache['labels'] if cache else {}

    indptr = np.zeros(n + 1, dtype=np.int64)
    indices, values = [], []
    coverage = [0] * len(FAMILIES)
    for i, row in enumerate(rows):
        by_family = {}
        for token, weight in row.items():
            if token in column:
                by_family.setdefault(token[0], []).append((column[token], idf[token] * weight))
        cells = []
        for f, found in by_family.items():
            norm = math.sqrt(sum(v * v for _c, v in found))
            cells += [(c, v / norm) for c, v in found]
            coverage[f] += 1
        cells.sort()
        indices += [c for c, _v in cells]
        values += [v for _c, v in cells]
        indptr[i + 1] = indptr[i] + len(cells)
    indices = np.asarray(indices, dtype=np.int64)
    values = np.asarray(values, dtype=np.float64).astype(np.float32)
    row_of = np.repeat(np.arange(n, dtype=np.int64), np.diff(indptr))
    order = np.lexsort((row_of, indices))
    col_ptr = np.zeros(len(kept) + 1, dtype=np.int64)
    np.cumsum(np.bincount(indices, minlength=len(kept)), out=col_ptr[1:])

    def label(token):
        family, key = token
        if FAMILIES[family] == 'genre':
            return key
        if FAMILIES[family] == 'network':
            return channel_names.get(key, key)
        return labels.get(key, key)
    return {
        'shape': (n, len(kept)),
        'csr': (indptr, indices, values),
        'csc': (col_ptr, row_of[order], values[order]),
        'tokens': [[f, key, label((f, key)), df[(f, key)]] for f, key in kept],
        'coverage': {family: coverage[f] for f, family in enumerate(FAMILIES)},
        'linked': sum(1 for show_id, _name in shows if str(show_id) in entries),
    }


# Aliases -------------------------------------------------------------------------------

def fold(text):
    """A name with case, diacritics, spaces and punctuation set aside, for comparing."""
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if c.isalnum())


def latin(text):
    return all('LATIN' in unicodedata.name(c, '') for c in text if c.isalpha())


def english(lang):
    return lang == 'en' or lang.startswith('en-')


def aliases(name, names):
    """Up to 12 other names for a show, from [(language, text)] pairs. A trailing
    qualifier in brackets, such as "(TV series)" or "(anime)", is dropped first: it tells
    a show from others of the same name and is no part of the name."""
    own = fold(name)
    groups = {}
    for lang, text in names:
        text = _QUALIFIER.sub('', ' '.join(str(text).split()))
        key = fold(text)
        if not ALIAS_LENGTH[0] <= len(text) <= ALIAS_LENGTH[1] or not key or key == own:
            continue
        group = groups.setdefault(key, {})
        group.setdefault(text, set()).add(lang)
    ranked = []
    for key, texts in groups.items():
        def rank(text):
            return 0 if any(english(lang) for lang in texts[text]) else 1 if latin(text) else 2
        languages = set().union(*texts.values())
        best = min(texts, key=lambda t: (rank(t), -len(texts[t]), t))
        ranked.append((rank(best), -len(languages), best.casefold(), best))
    ranked.sort()
    return [text for *_order, text in ranked[:MAX_ALIASES]]


def search_aliases(shows, cache):
    entries = cache['shows'] if cache else {}
    found = {}
    for show_id, name in sorted(shows):
        entry = entries.get(str(show_id))
        if entry and entry.get('names'):
            names = aliases(name, entry['names'])
            if names:
                found[str(show_id)] = names
    return found


# Files ---------------------------------------------------------------------------------

def matrix_bytes(facets):
    rows, cols = facets['shape']
    indptr, indices, values = facets['csr']
    col_ptr, post_rows, post_values = facets['csc']
    parts = [struct.pack('<III', rows, cols, len(indices))]
    for array, dtype in ((indptr, '<u4'), (indices, '<u4'), (values, '<f4'),
                         (col_ptr, '<u4'), (post_rows, '<u4'), (post_values, '<f4')):
        parts.append(np.asarray(array).astype(dtype).tobytes())
    return b''.join(parts)


def gz_json(value):
    return gzip.compress(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode(),
                         compresslevel=9, mtime=0)


def write(model, date, facets, found_aliases, fetched_at):
    model = Path(model)
    outputs = {
        'facets.bin.gz': gzip.compress(matrix_bytes(facets), compresslevel=9, mtime=0),
        'facets.json.gz': gz_json({'version': VERSION, 'date': date, 'wikidata_fetched_at': fetched_at,
                                   'families': list(FAMILIES), 'tokens': facets['tokens'],
                                   'coverage': facets['coverage'], 'linked': facets['linked']}),
        'search.json.gz': gz_json({'version': VERSION, 'aliases': found_aliases}),
    }
    for name, body in outputs.items():
        (model / name).write_bytes(body)
    return {name: len(body) for name, body in outputs.items()}


def main():
    model = Path(os.environ.get('TV_MODEL_OUT') or ROOT / 'model')
    raw_dir = Path(os.environ.get('TV_RAW_DIR') or ROOT / 'data' / 'raw')
    source = os.environ.get('TV_WIKIDATA')
    # The catalog first: parsing it is the peak, and it is over before the cache loads.
    date, shows = read_catalog(model)
    channels = read_channels(raw_dir)
    cache = None
    if source:
        try:
            cache = wikidata.read(source)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        if cache is None:
            print(f'No Wikidata cache at {source}; building from TVmaze alone.', flush=True)
    else:
        print('TV_WIKIDATA is not set; building from TVmaze alone.', flush=True)
    facets = build(shows, channels, cache)
    found = search_aliases(shows, cache)
    sizes = write(model, date, facets, found, cache['fetched_at'] if cache else None)
    rows, cols = facets['shape']
    print(f"{rows:,} shows, {cols:,} tokens, {len(facets['csr'][1]):,} nonzeros; "
          f"{facets['linked']:,} shows linked to Wikidata, {len(found):,} with aliases", flush=True)
    counts = {}
    for f, _key, _label, _df in facets['tokens']:
        counts[f] = counts.get(f, 0) + 1
    for f, family in enumerate(FAMILIES):
        print(f"  {family:<10} {counts.get(f, 0):>7,} tokens, {facets['coverage'][family]:>7,} shows", flush=True)
    for name, size in sizes.items():
        print(f'  {name:<15} {size / 1e6:6.2f} MB', flush=True)


if __name__ == '__main__':
    main()
