"""Check the facet builder and the app's facet reader, on a small made-up catalog and on
the committed model.

Run from the repository root:  .venv/bin/python scripts/test_facets.py

Nothing here reaches Wikidata: the fixture's cache is written by hand in the shape
scripts/wikidata.py writes, and build_facets.py runs on it as the refresher runs it.
"""
from pathlib import Path
import gzip
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / 'app'))

import build_facets                                             # noqa: E402
import facets as reader                                         # noqa: E402
import titles                                                    # noqa: E402
import wikidata                                                 # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='facets-test-'))
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def rejects(label, fn, said):
    try:
        fn()
        check(label, False, 'accepted')
    except ValueError as exc:
        check(label, said in str(exc), str(exc))


# A small world ---------------------------------------------------------------------------

DATE = '2026-09-07'
SHOWS = [(1, 'Breaking Good'), (2, 'Better Call Paul'), (3, 'Procedural One'), (4, 'Detective Two'),
         (5, 'Plain Show'), (6, 'Nowhere'), (7, 'House of Dragons'), (8, 'Thrones'), (9, 'Loner'),
         (10, 'Awarded'), (11, 'Anime Show'), (12, 'La Casa de Papel'), (13, 'Anime Two')]
CHANNELS = {1: ('network', 20, 'AMC'), 2: ('network', 20, 'AMC'), 5: ('network', 20, 'AMC'),
            3: ('webChannel', 1, 'Netflix'), 4: ('webChannel', 1, 'Netflix'), 7: ('network', 8, 'HBO'),
            8: ('network', 8, 'HBO'), 9: ('webChannel', 99, 'Solo'), 10: ('network', 3, 'CBS'),
            11: ('network', 3, 'CBS'), 12: ('network', 3, 'CBS'), 13: ('network', 3, 'CBS')}
LABELS = {
    'Q101': 'crime television series', 'Q102': 'drama television series', 'Q103': 'crime film',
    'Q104': 'legal drama', 'Q105': 'police procedural', 'Q106': 'detective fiction', 'Q107': 'work of art',
    'Q108': 'isekai', 'Q109': 'television series', 'Q120': 'comedy anime and manga', 'Q121': 'anime and manga',
    'Q122': 'comedy', 'Q123': 'crime fiction', 'Q110': 'accidental travel', 'Q201': 'Vince', 'Q202': 'Peter',
    'Q203': 'Gould', 'Q204': 'Thomas', 'Q72': 'Ice Saga',
    'Q301': 'Bryan', 'Q302': 'Aaron', 'Q900': 'Nobody Else', 'Q70': 'Fire and Blood', 'Q71': 'Song of Ice',
    'Q401': 'Albuquerque', 'Q501': 'Best Drama', 'Q502': 'Best Writing', 'Q1': 'Breaking Good',
    'Q2': 'Better Call Paul'}
CACHE = {
    'version': 1, 'fetched_at': '2026-09-20T04:00:00Z', 'source': 'https://www.wikidata.org', 'license': 'CC0-1.0',
    'mapped': {'p8600': 11, 'imdb': 1}, 'labels': LABELS,
    'parents': {'Q105': ['Q106', 'Q107'], 'Q106': ['Q123'], 'Q101': ['Q109', 'Q123'], 'Q103': ['Q123'],
                'Q108': ['Q110'], 'Q120': ['Q121', 'Q122']},
    'belongs': {'Q70': ['Q71']},
    'shows': {
        '1': {'qid': 'Q1', 'via': 'p8600', 'genre': ['Q101', 'Q102'], 'maker': {'P170': ['Q201'], 'P58': ['Q202', 'Q204']},
              'cast': ['Q301', 'Q302'], 'franchise': {'P4969': ['Q2']}, 'subject': {'P840': ['Q401']},
              'award': ['Q501'], 'names': [['en', 'BG'], ['en', 'Breaking Good']]},
        '2': {'qid': 'Q2', 'via': 'p8600', 'genre': ['Q103', 'Q104'], 'maker': {'P170': ['Q203'], 'P58': ['Q201', 'Q204']},
              'cast': ['Q301'], 'franchise': {'P144': ['Q1']}, 'subject': {'P840': ['Q401']},
              'nominated': ['Q502']},
        '3': {'qid': 'Q3', 'via': 'p8600', 'genre': ['Q105']},
        '4': {'qid': 'Q4', 'via': 'imdb', 'genre': ['Q106', 'Q105']},
        '7': {'qid': 'Q7', 'via': 'p8600', 'franchise': {'P144': ['Q70'], 'P179': ['Q72']}},
        '8': {'qid': 'Q8', 'via': 'p8600', 'franchise': {'P144': ['Q71'], 'P179': ['Q72']}},
        '9': {'qid': 'Q9', 'via': 'p8600', 'genre': ['Q108'], 'cast': ['Q900']},
        '10': {'qid': 'Q10', 'via': 'p8600', 'award': ['Q501'], 'nominated': ['Q502']},
        '11': {'qid': 'Q11', 'via': 'p8600', 'genre': ['Q120']},
        '12': {'qid': 'Q12', 'via': 'p8600', 'genre': ['Q122'], 'names': [
            ['de', 'Haus des Geldes'], ['en', 'Money Heist'], ['es', 'La casa de papel'], ['fr', 'La Casa de Papel'],
            ['it', 'La casa di carta'], ['ja', 'ペーパー・ハウス'], ['en', 'Money heist'], ['xx', 'X'],
            ['yy', 'A' * 81], ['sr', 'Kuća od papira (serija)']]},
        '13': {'qid': 'Q13', 'via': 'p8600', 'genre': ['Q121']},
        '999': {'qid': 'Q999', 'via': 'p8600', 'cast': ['Q301']},
    }}


def make_world(folder, cache=True):
    folder = Path(folder)
    (folder / 'model').mkdir(parents=True)
    (folder / 'raw').mkdir()
    catalog = {'version': f'tvmaze-v2-{DATE}', 'date': DATE, 'text_features': 0, 'genres': [], 'themes': [],
               'metadata': {}, 'shows': [{'id': i, 'name': name, 'genres': [], 'year': 2020} for i, name in SHOWS]}
    (folder / 'model' / 'catalog.json.gz').write_bytes(gzip.compress(json.dumps(catalog).encode(), mtime=0))
    raw = []
    for i, name in SHOWS:
        show = {'id': i, 'name': name, 'network': None, 'webChannel': None}
        if i in CHANNELS:
            field, cid, cname = CHANNELS[i]
            show[field] = {'id': cid, 'name': cname}
        raw.append(show)
    (folder / 'raw' / 'page-000.json').write_text(json.dumps(raw))
    if cache:
        (folder / 'wikidata.json.gz').write_bytes(wikidata.encode(CACHE))
    return folder


def run_builder(folder, cache=True, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('TV_')}
    env.update(TV_MODEL_OUT=str(folder / 'model'), TV_RAW_DIR=str(folder / 'raw'), **(env_extra or {}))
    if cache:
        env['TV_WIKIDATA'] = str(folder / 'wikidata.json.gz')
    return subprocess.run([sys.executable, str(SCRIPTS / 'build_facets.py')], env=env, capture_output=True, text=True)


def read_matrix(model):
    """The facet matrix with numpy, as a reference the reader is checked against."""
    raw = gzip.decompress((Path(model) / 'facets.bin.gz').read_bytes())
    rows, cols, nnz = struct.unpack('<III', raw[:12])
    at, parts = 12, []
    for dtype, count in (('<u4', rows + 1), ('<u4', nnz), ('<f4', nnz), ('<u4', cols + 1), ('<u4', nnz), ('<f4', nnz)):
        parts.append(np.frombuffer(raw, dtype, count, at))
        at += 4 * count
    return (rows, cols, nnz), parts, len(raw)


def dense(parts, shape):
    rows, cols, _nnz = shape
    indptr, indices, data = parts[:3]
    matrix = np.zeros((rows, cols), dtype=np.float64)
    for i in range(rows):
        matrix[i, indices[indptr[i]:indptr[i + 1]]] = data[indptr[i]:indptr[i + 1]]
    return matrix


def gz_json(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


# 1. Genre keys -------------------------------------------------------------------------------

canon = build_facets.canonical_genre
for label, key in [('crime television series', 'crime'), ('crime film', 'crime'), ('crime fiction', 'crime'),
                   ('comedy anime and manga', 'comedy'), ('drama film', 'drama'), ('police procedural', 'police procedural'),
                   ('sitcom', 'sitcom'), ('isekai', 'isekai'), ('legal drama', 'legal drama'),
                   ('adult animated television series', 'adult animation'), ('crime drama', 'crime drama'),
                   ('science fiction television series', 'science fiction'), ('science fiction anime', 'science fiction'),
                   ('telenovela', 'telenovela'), ("children's television series", "children's"),
                   ('LGBT-related television series', 'lgbtq'), ('Westerns on television', 'western'),
                   ('non-fiction film', 'nonfiction'), ('post-apocalyptic television series', 'post apocalyptic'),
                   ('anime and manga', 'anime'), ('reality television', 'reality'), ('romance film', 'romance'),
                   ('romantic fiction', 'romance'), ('police television drama', 'police drama'),
                   ('Japanese television drama', 'japanese drama'), ('game show', 'game show'),
                   ('film noir', 'noir'), ('anime-influenced animation', 'anime influenced animation')]:
    check(f'the genre {label!r} is keyed {key!r}', canon(label) == key, canon(label))
for label in ('television series', 'television program', 'genre of creative works', 'work of art', 'film', 'fiction',
              'entertainment television program', 'web series', 'television serial'):
    check(f'the genre {label!r} says nothing and is dropped', canon(label) is None, canon(label))

genres = build_facets.Genres(CACHE)
check('a genre counts in full and its superclasses at half the value of the class below',
      genres.weights(['Q105']) == {'police procedural': 1.0, 'detective': 0.5, 'crime': 0.25}, genres.weights(['Q105']))
check('a superclass that is no show\'s genre is left out', genres.weights(['Q108']) == {'isekai': 1.0}
      and genres.key('Q110') == 'accidental travel' and 'accidental travel' not in genres.vocabulary)
check('a genre and a superclass with one key keep the higher value',
      genres.weights(['Q106', 'Q105']) == {'detective': 1.0, 'crime': 0.5, 'police procedural': 1.0})
check('"anime and manga" above an anime genre becomes anime at half value',
      genres.weights(['Q120']) == {'comedy': 1.0, 'anime': 0.5}, genres.weights(['Q120']))

# 2. Aliases ------------------------------------------------------------------------------------

names = CACHE['shows']['12']['names']
check('aliases: English first, then Latin script, then the rest; the TVmaze name, its variants and '
      'duplicates dropped, qualifiers stripped, lengths bounded',
      build_facets.aliases('La Casa de Papel', names)
      == ['Money Heist', 'Haus des Geldes', 'Kuća od papira', 'La casa di carta', 'ペーパー・ハウス'],
      build_facets.aliases('La Casa de Papel', names))
check('an alias differing only in spacing and punctuation is the same name',
      build_facets.aliases('Brooklyn Nine-Nine', [['en', 'Brooklyn Nine Nine'], ['en', 'Brooklyn 99'],
                                                  ['en', 'B99'], ['pl', 'brooklyn nine-nine!']])
      == ['B99', 'Brooklyn 99'])
check('diacritics are set aside when comparing', build_facets.aliases('Pokemon', [['fr', 'Pokémon']]) == [])
many = [['en', f'Name number {i:02d}'] for i in range(20)]
check('at most 12 aliases a show', len(build_facets.aliases('Show', many)) == 12)
shared = [['de', 'Gemeinsam'], ['nl', 'Gemeinsam'], ['sv', 'Gemeinsam'], ['da', 'Alleen']]
check('among Latin names, the ones more languages use come first',
      build_facets.aliases('Show', shared) == ['Gemeinsam', 'Alleen'])
crowded = [['en', f'Name number {i:02d}'] for i in range(20)] + [['ru', 'Атака титанов'], ['ko', '진격의 거인'], ['ja', '進撃の巨人']]
kept = build_facets.aliases('Attack on Titan', crowded, 'Japanese')
check('two names in other scripts survive a crowd of Latin ones, the show\'s own language first',
      len(kept) == 12 and kept[-2:][0] == '進撃の巨人' and len(kept[-2:]) == 2, kept[-3:])
few = build_facets.aliases('Show', [['en', 'One'], ['ja', 'ショー'], ['ko', '쇼타임'], ['ru', 'Шоу'], ['th', 'โชว์']])
check('other scripts fill the places Latin names leave', len(few) == 5 and few[0] == 'One', few)
plain = build_facets.aliases('Attack on Titan', crowded)
check('without a language, other scripts still keep their two places',
      len(plain) == 12 and all(not build_facets.latin(name) for name in plain[-2:]), plain[-3:])

# 3. The builder, end to end ---------------------------------------------------------------------

one, two = make_world(TMP / 'one'), make_world(TMP / 'two')
first, second = run_builder(one), run_builder(two)
check('build_facets.py runs on the fixture', first.returncode == 0 and second.returncode == 0,
      first.stderr[-500:] + second.stderr[-500:])
for name in ('facets.bin.gz', 'facets.json.gz', 'search.json.gz'):
    check(f'{name} is the same, byte for byte, when built twice',
          (one / 'model' / name).read_bytes() == (two / 'model' / name).read_bytes())
check('no timestamp in the gzip headers', all((one / 'model' / name).read_bytes()[4:8] == bytes(4)
                                              for name in ('facets.bin.gz', 'facets.json.gz', 'search.json.gz')))

model = one / 'model'
meta = gz_json(model / 'facets.json.gz')
shape, parts, size = read_matrix(model)
rows, cols, nnz = shape
indptr, indices, data, col_ptr, post_rows, post_data = parts
check('facets.bin.gz has the vectors.bin.gz layout, exactly',
      size == 12 + 4 * ((rows + 1) + 2 * nnz + (cols + 1) + 2 * nnz) and rows == len(SHOWS)
      and indptr[0] == 0 and indptr[-1] == nnz and col_ptr[-1] == nnz)
check('facets.json.gz names one token per column, grouped by family', len(meta['tokens']) == cols
      and [t[0] for t in meta['tokens']] == sorted(t[0] for t in meta['tokens']))
check('facets.json.gz carries the catalog date, the fetch date and the families',
      meta['version'] == 1 and meta['date'] == DATE and meta['wikidata_fetched_at'] == CACHE['fetched_at']
      and meta['families'] == list(build_facets.FAMILIES))
matrix = dense(parts, shape)
check('indices ascend within every row', all(np.all(np.diff(indices[indptr[i]:indptr[i + 1]].astype(np.int64)) > 0)
                                            for i in range(rows)))
check('indices ascend within every column', all(np.all(np.diff(post_rows[col_ptr[c]:col_ptr[c + 1]].astype(np.int64)) > 0)
                                               for c in range(cols)))
transposed = np.zeros((cols, rows))
for c in range(cols):
    transposed[c, post_rows[col_ptr[c]:col_ptr[c + 1]]] = post_data[col_ptr[c]:col_ptr[c + 1]]
check('the column half is the row half transposed', np.array_equal(transposed, matrix.T))
family_of = np.array([t[0] for t in meta['tokens']])
norms_ok = True
for i in range(rows):
    for f in range(len(meta['families'])):
        part = matrix[i, family_of == f]
        if np.any(part) and abs(float(np.sum(part * part)) - 1) > 1e-6:
            norms_ok = False
check('each family\'s slice of each row has unit length', norms_ok)
counts = np.diff(col_ptr.astype(np.int64))
check('each token\'s df is the number of shows that have it', [t[3] for t in meta['tokens']] == counts.tolist())
check('no token fewer than two shows have survives', min(t[3] for t in meta['tokens']) >= 2)
keys = {(meta['families'][t[0]], t[1]) for t in meta['tokens']}
check('tokens one show has are pruned: a lone cast member, genre and channel',
      ('cast', 'Q900') not in keys and ('genre', 'isekai') not in keys and ('network', 'tvmaze-web-99') not in keys)
check('a show outside the catalog counts for nothing', ('cast', 'Q301') in keys
      and next(t[3] for t in meta['tokens'] if t[1] == 'Q301') == 2)
check('useless genres are never tokens', not {k for f, k in keys if f == 'genre'} & {'of art', 'television series'})

column = {(meta['families'][t[0]], t[1]): c for c, t in enumerate(meta['tokens'])}
df = {(meta['families'][t[0]], t[1]): t[3] for t in meta['tokens']}
n = len(SHOWS)
row3 = matrix[2]
idf = lambda token: math.log(n / df[token])
check('a parent genre counts at half value, before the family is normalised',
      abs(row3[column['genre', 'detective']] / row3[column['genre', 'police procedural']]
          - 0.5 * idf(('genre', 'detective')) / idf(('genre', 'police procedural'))) < 1e-6
      and abs(row3[column['genre', 'crime']] / row3[column['genre', 'police procedural']]
              - 0.25 * idf(('genre', 'crime')) / idf(('genre', 'police procedural'))) < 1e-6)
row1, row2 = matrix[0], matrix[1]
check('a creator counts 1 and a screenwriter 0.6',
      abs(row1[column['maker', 'Q201']] / row1[column['maker', 'Q204']] - 1 / 0.6) < 1e-5
      and abs(row2[column['maker', 'Q201']] / row2[column['maker', 'Q204']] - 1) < 1e-6
      and ('maker', 'Q202') not in column and ('maker', 'Q203') not in column)
check('an award counts 1 and a nomination 0.5',
      abs(matrix[9, column['award', 'Q501']] / matrix[9, column['award', 'Q502']]
          - idf(('award', 'Q501')) / (0.5 * idf(('award', 'Q502')))) < 1e-5)


def cosine(i, j, family):
    mask = family_of == meta['families'].index(family)
    return float(matrix[i, mask] @ matrix[j, mask])


check('a spin-off naming its parent and the parent naming it share franchise tokens',
      cosine(0, 1, 'franchise') > 0.99 and {('franchise', 'Q1'), ('franchise', 'Q2')} <= keys)
check('a show based on a book in a series meets a show based on that series',
      cosine(6, 7, 'franchise') > 0.9 and ('franchise', 'Q71') in keys and ('franchise', 'Q70') not in keys)
check('the series one hop away counts at half value',
      abs(matrix[6, column['franchise', 'Q71']] / matrix[6, column['franchise', 'Q72']] - 0.5) < 1e-6
      and abs(matrix[7, column['franchise', 'Q71']] / matrix[7, column['franchise', 'Q72']] - 1) < 1e-6)
check('shows on one network share it', cosine(0, 4, 'network') > 0.99 and cosine(0, 2, 'network') == 0.0)
check('network tokens are keyed and labelled from TVmaze',
      {('network', 'tvmaze-network-20'), ('network', 'tvmaze-web-1')} <= keys
      and next(t[2] for t in meta['tokens'] if t[1] == 'tvmaze-network-20') == 'AMC')
check('Wikidata tokens carry their English labels', next(t[2] for t in meta['tokens'] if t[1] == 'Q201') == 'Vince')
check('coverage counts the shows each family reaches', meta['coverage'] == {
    'genre': 7, 'maker': 2, 'cast': 2, 'franchise': 4, 'subject': 2, 'network': 11, 'award': 3}, meta['coverage'])
check('linked counts the catalog shows with Wikidata data', meta['linked'] == 11)
search = gz_json(model / 'search.json.gz')
check('search.json.gz holds the aliases of catalog shows',
      search == {'version': 1, 'aliases': {'1': ['BG'], '12': build_facets.aliases('La Casa de Papel', names)}}, search)

# Without a cache the files are still whole: networks, and no aliases.
bare = make_world(TMP / 'bare', cache=False)
done = run_builder(bare, cache=False)
bare_meta = gz_json(bare / 'model' / 'facets.json.gz')
check('without a cache the builder still succeeds', done.returncode == 0 and 'TVmaze alone' in done.stdout, done.stderr)
check('without a cache there are network tokens only', {bare_meta['families'][t[0]] for t in bare_meta['tokens']} == {'network'}
      and bare_meta['linked'] == 0 and bare_meta['wikidata_fetched_at'] is None
      and bare_meta['families'] == list(build_facets.FAMILIES))
check('without a cache there are no aliases', gz_json(bare / 'model' / 'search.json.gz') == {'version': 1, 'aliases': {}})
missing = make_world(TMP / 'missing', cache=False)
done = run_builder(missing, env_extra={'TV_WIKIDATA': str(missing / 'nowhere.json.gz')}, cache=False)
check('a cache that is not there means TVmaze alone', done.returncode == 0 and 'No Wikidata cache' in done.stdout)
broken = make_world(TMP / 'broken')
(broken / 'wikidata.json.gz').write_bytes(b'not a cache')
done = run_builder(broken)
check('a broken cache stops the build with the reason', done.returncode != 0 and 'not a Wikidata cache' in done.stderr,
      done.stderr[-300:])

# 4. The reader -----------------------------------------------------------------------------------

loaded = reader.load(model, len(SHOWS))
check('the reader loads the facets', loaded is not None and loaded.n == rows and loaded.cols == cols
      and loaded.nnz == nnz and loaded.families == tuple(build_facets.FAMILIES))
check('the reader keeps every column\'s family, key, label and df',
      list(loaded.token_family) == [t[0] for t in meta['tokens']] and list(loaded.keys) == [t[1] for t in meta['tokens']]
      and list(loaded.labels) == [t[2] for t in meta['tokens']] and list(loaded.df) == [t[3] for t in meta['tokens']]
      and loaded.keys[-1] == meta['tokens'][-1][1] and loaded.labels[0] == meta['tokens'][0][2])
check('the reader holds typed arrays', all(type(a).__name__ == 'array' for a in (
    loaded.row_ptr, loaded.columns, loaded.values, loaded.col_ptr, loaded.post_rows, loaded.post_values,
    loaded.token_family, loaded.df)))
check('row(i) yields the row\'s columns and values in order',
      all([(c, round(v, 6)) for c, v in loaded.row(i)]
          == [(int(c), round(float(v), 6)) for c, v in zip(indices[indptr[i]:indptr[i + 1]], data[indptr[i]:indptr[i + 1]])]
          for i in range(rows)))
check('family ranges cover the columns in family order',
      loaded.family_ranges[0][0] == 0 and loaded.family_ranges[-1][1] == cols
      and all(loaded.token_family[c] == f for f, (a, b) in enumerate(loaded.family_ranges) for c in range(a, b)))


def reference(matrix, family_of, families, i, weights):
    w = np.array([weights.get(f, 0) for f in families], dtype=np.float64)[family_of]
    return (matrix * w[None, :]) @ matrix[i]


weights = {'genre': 1.5, 'maker': 2, 'cast': 0.5, 'franchise': 3, 'subject': 1, 'network': 0.25, 'award': 0.75}
worst = max(float(np.max(np.abs(np.asarray(loaded.similarity(i, weights)) - reference(matrix, family_of, meta['families'], i, weights))))
            for i in range(rows))
check('similarity matches a numpy reference for every show', worst < 1e-5, worst)
only = {'franchise': 1}
worst = max(float(np.max(np.abs(np.asarray(loaded.similarity(i, only)) - reference(matrix, family_of, meta['families'], i, only))))
            for i in range(rows))
check('families weighted zero are left out', worst < 1e-6
      and abs(loaded.similarity(0, only)[1] - cosine(0, 1, 'franchise')) < 1e-6, worst)
check('weights may come as a sequence in family order',
      list(loaded.similarity(0, [weights[f] for f in loaded.families])) == list(loaded.similarity(0, weights)))
check('similarity is an array over every show', len(loaded.similarity(3, weights)) == rows
      and type(loaded.similarity(3, weights)).__name__ == 'array' and loaded.similarity(3, weights).typecode == 'f')
rejects('an unknown family is refused', lambda: loaded.similarity(0, {'mood': 1}), 'Unknown facet families')
rejects('a sequence of the wrong length is refused', lambda: loaded.similarity(0, [1, 2]), 'one per family')
rejects('a weight that is not a number is refused', lambda: loaded.similarity(0, {'genre': float('nan')}), 'finite')
check('a model without facets loads as None', reader.load(TMP / 'nowhere', 5) is None)
rejects('facets for another catalog size are refused', lambda: reader.load(model, len(SHOWS) + 1), 'rows where the catalog has')
half = TMP / 'half'
half.mkdir()
shutil.copyfile(model / 'facets.bin.gz', half / 'facets.bin.gz')
rejects('one facet file without the other is refused', lambda: reader.load(half, len(SHOWS)), 'facets.json.gz is missing')
shutil.copyfile(bare / 'model' / 'facets.json.gz', half / 'facets.json.gz')
rejects('metadata for other columns is refused', lambda: reader.load(half, len(SHOWS)), 'tokens where facets.bin.gz has')
(half / 'facets.json.gz').write_bytes(b'garbage')
rejects('a file that does not decompress is refused', lambda: reader.load(half, len(SHOWS)), 'do not read')
(half / 'facets.bin.gz').write_bytes(gzip.compress(gzip.decompress((model / 'facets.bin.gz').read_bytes())[:-4]))
shutil.copyfile(model / 'facets.json.gz', half / 'facets.json.gz')
rejects('a truncated matrix is refused', lambda: reader.load(half, len(SHOWS)), 'truncated')

# 5. The committed model --------------------------------------------------------------------------

MODEL = ROOT / 'model'
if (MODEL / 'facets.bin.gz').exists():
    with gzip.open(MODEL / 'catalog.json.gz', 'rt') as f:
        catalog = json.load(f)
    by_id = {s['id']: i for i, s in enumerate(catalog['shows'])}
    live = reader.load(MODEL, len(catalog['shows']))
    real_meta = gz_json(MODEL / 'facets.json.gz')
    check('the committed facets fit the committed catalog', live is not None and live.n == len(catalog['shows'])
          and real_meta['date'] == catalog['date'])
    shape, parts, _size = read_matrix(MODEL)
    indptr, indices, data = parts[:3]
    real_family = np.frombuffer(live.token_family, dtype=np.uint8)

    def real_row(i):
        row = np.zeros(shape[1])
        row[indices[indptr[i]:indptr[i + 1]]] = data[indptr[i]:indptr[i + 1]]
        return row

    def real_reference(i, weights):
        w = np.array([weights.get(f, 0) for f in live.families], dtype=np.float64)[real_family]
        target = real_row(i) * w
        scores = np.zeros(shape[0])
        for j in range(shape[0]):
            a, b = indptr[j], indptr[j + 1]
            if a != b:
                scores[j] = float(np.dot(data[a:b], target[indices[a:b]]))
        return scores

    def real_cosine(a, b, family):
        mask = real_family == live.families.index(family)
        return float(real_row(by_id[a])[mask] @ real_row(by_id[b])[mask])

    for show_id in (169, 82, 526, 919):
        got = np.asarray(live.similarity(by_id[show_id], weights))
        check(f'similarity for show {show_id} matches numpy on the real model',
              float(np.max(np.abs(got - real_reference(by_id[show_id], weights)))) < 1e-5)
    check('Breaking Bad and Better Call Saul share franchise, makers, subjects and cast',
          real_cosine(169, 618, 'franchise') > 0.7 and real_cosine(169, 618, 'maker') > 0.2
          and real_cosine(169, 618, 'subject') > 0.3 and real_cosine(169, 618, 'cast') > 0.05)
    check('Game of Thrones and House of the Dragon share their franchise and makers',
          real_cosine(82, 44778, 'franchise') > 0.7 and real_cosine(82, 44778, 'maker') > 0.2)
    check('The Office and Parks and Recreation share makers', real_cosine(526, 174, 'maker') > 0.2)
    anime = {live.keys[c] for c, _v in live.row(by_id[919]) if live.families[live.token_family[c]] == 'genre'}
    check('Attack on Titan has anime genres', {'anime', 'dark fantasy', 'post apocalyptic'} <= anime, anime)
    names = titles.load_aliases(MODEL / 'search.json.gz')
    check('Money Heist finds La Casa de Papel', 'Money Heist' in names.get(27436, []))
    check('Shingeki no Kyojin finds Attack on Titan', 'Shingeki no Kyojin' in names.get(919, []))
    check('Brooklyn 99 finds Brooklyn Nine-Nine', 'Brooklyn 99' in names.get(49, []))
else:
    print('skip  the committed model has no facets yet')

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
