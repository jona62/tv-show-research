"""Taste facets beside the model: Wikidata's genres, makers, cast, franchises, subjects
and awards, and TVmaze's networks, as one sparse row per catalog show.

scripts/build_facets.py writes them: facets.bin.gz in the layout of vectors.bin.gz,
facets.json.gz naming each column's family, key, label and document frequency, and
search.json.gz with other names for shows. Each family's slice of a row has unit
length, so the dot product of two rows' slices is that family's cosine similarity.
Standard library only, and every per-show value lives in a typed array. Couchside's
build.py copies this file, like engine.py.

    facets = load(model_dir, engine.n)       # None when the model has no facets
    scores = facets.similarity(i, {'franchise': 3, 'maker': 2, 'genre': 1})
    names = aliases(model_dir)               # {TVmaze id: [names]}, {} without them
"""
from array import array
from pathlib import Path
import gzip
import json
import math
import struct
import sys
import zlib

VERSION = 1


class Strings:
    """A read-only list of strings held as one string and an array of offsets, which
    costs a small fraction of a Python list of the same strings."""

    def __init__(self, items):
        items = [str(item) for item in items]
        self.text = ''.join(items)
        self.ends = array('I')
        end = 0
        for item in items:
            end += len(item)
            self.ends.append(end)

    def __len__(self):
        return len(self.ends)

    def __getitem__(self, index):
        if index < 0:
            index += len(self.ends)
        if not 0 <= index < len(self.ends):
            raise IndexError('string index out of range')
        return self.text[self.ends[index - 1] if index else 0:self.ends[index]]

    def __iter__(self):
        start = 0
        for end in self.ends:
            yield self.text[start:end]
            start = end


class Facets:
    """The facet matrix of one model, in both orientations, with its column metadata:
    families, token_family (the family index of each column), keys, labels and df."""

    def __init__(self, meta, arrays):
        self.version = meta['version']
        self.date = meta.get('date')
        self.fetched_at = meta.get('wikidata_fetched_at')
        self.families = tuple(meta['families'])
        self.coverage = dict(meta.get('coverage') or {})
        self.linked = meta.get('linked')
        tokens = meta['tokens']
        self.token_family = array('B', (t[0] for t in tokens))
        self.keys = Strings(t[1] for t in tokens)
        self.labels = Strings(t[2] for t in tokens)
        self.df = array('I', (t[3] for t in tokens))
        (self.n, self.cols, self.row_ptr, self.columns, self.values,
         self.col_ptr, self.post_rows, self.post_values) = arrays
        self.nnz = len(self.values)
        # Columns come sorted by family, so each family is one run of columns.
        self.family_ranges = []
        start = 0
        for f in range(len(self.families)):
            end = start
            while end < self.cols and self.token_family[end] == f:
                end += 1
            self.family_ranges.append((start, end))
            start = end

    def row(self, i):
        """(column, value) for show i's tokens, columns ascending."""
        for k in range(self.row_ptr[i], self.row_ptr[i + 1]):
            yield self.columns[k], self.values[k]

    def weights(self, family_weights):
        """A weight per family index from {family: weight} or a sequence in family order."""
        if isinstance(family_weights, dict):
            unknown = set(family_weights) - set(self.families)
            if unknown:
                raise ValueError(f"Unknown facet families: {', '.join(sorted(map(str, unknown)))}.")
            found = [family_weights.get(name, 0) for name in self.families]
        else:
            found = list(family_weights)
            if len(found) != len(self.families):
                raise ValueError(f'Give {len(self.families)} facet weights, one per family.')
        for w in found:
            if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w):
                raise ValueError('Facet weights must be finite numbers.')
        return [float(w) for w in found]

    def similarity(self, i, family_weights):
        """For every show, the sum over families of weight times the dot product of its
        family slice with show i's: a weighted sum of per-family cosines. Walks show i's
        tokens through the column postings, skipping families weighted zero."""
        weights = self.weights(family_weights)
        scores = array('f', [0]) * self.n
        family, columns, values = self.token_family, self.columns, self.values
        col_ptr, post_rows, post_values = self.col_ptr, self.post_rows, self.post_values
        for k in range(self.row_ptr[i], self.row_ptr[i + 1]):
            column = columns[k]
            weight = weights[family[column]]
            if not weight:
                continue
            value = weight * values[k]
            for p in range(col_ptr[column], col_ptr[column + 1]):
                scores[post_rows[p]] += value * post_values[p]
        return scores


def _read_matrix(path, n):
    with gzip.open(path, 'rb') as f:
        head = f.read(12)
        if len(head) != 12:
            raise ValueError('facets.bin.gz is truncated.')
        rows, cols, nnz = struct.unpack('<III', head)
        if rows != n:
            raise ValueError(f'facets.bin.gz has {rows:,} rows where the catalog has {n:,} shows.')

        def read_array(code, count):
            values = array(code)
            values.frombytes(f.read(count * 4))
            if sys.byteorder != 'little':
                values.byteswap()
            if len(values) != count:
                raise ValueError('facets.bin.gz is truncated.')
            return values
        arrays = (read_array('I', rows + 1), read_array('I', nnz), read_array('f', nnz),
                  read_array('I', cols + 1), read_array('I', nnz), read_array('f', nnz))
        if f.read(1):
            raise ValueError('facets.bin.gz runs past its header.')
    row_ptr, columns, _values, col_ptr, post_rows, _post_values = arrays
    if row_ptr[0] != 0 or row_ptr[-1] != nnz or col_ptr[0] != 0 or col_ptr[-1] != nnz:
        raise ValueError('facets.bin.gz has inconsistent pointers.')
    if nnz and (max(columns) >= cols or max(post_rows) >= rows):
        raise ValueError('facets.bin.gz points outside its own shape.')
    return (rows, cols, *arrays)


def load(model_dir, n):
    """The model's facets, or None when it has none. Raises ValueError when the files
    are there but do not fit a catalog of n shows, or do not fit each other."""
    model = Path(model_dir)
    matrix, meta_path = model / 'facets.bin.gz', model / 'facets.json.gz'
    if not matrix.exists() and not meta_path.exists():
        return None
    if not matrix.exists() or not meta_path.exists():
        raise ValueError(f'{matrix.name if not matrix.exists() else meta_path.name} is missing beside the other facet file.')
    try:
        with gzip.open(meta_path, 'rt', encoding='utf-8') as f:
            meta = json.load(f)
        arrays = _read_matrix(matrix, n)
    except (OSError, EOFError, UnicodeDecodeError, struct.error, zlib.error) as exc:
        raise ValueError(f'The facet files do not read: {exc}') from None
    if not isinstance(meta, dict) or meta.get('version') != VERSION or not isinstance(meta.get('families'), list) \
            or not isinstance(meta.get('tokens'), list):
        raise ValueError(f'facets.json.gz is not version {VERSION} facet metadata.')
    tokens, families = meta['tokens'], meta['families']
    if len(tokens) != arrays[1]:
        raise ValueError(f'facets.json.gz names {len(tokens):,} tokens where facets.bin.gz has {arrays[1]:,} columns.')
    if any(not isinstance(t, list) or len(t) != 4 or type(t[0]) is not int or not 0 <= t[0] < len(families)
           or type(t[3]) is not int for t in tokens):
        raise ValueError('facets.json.gz holds a malformed token.')
    if any(tokens[c][0] > tokens[c + 1][0] for c in range(len(tokens) - 1)):
        raise ValueError('facets.json.gz tokens are not grouped by family.')
    return Facets(meta, arrays)


def aliases(model_dir):
    """{TVmaze id: [other names]} from search.json.gz, or {} when the model has none."""
    path = Path(model_dir) / 'search.json.gz'
    if not path.exists():
        return {}
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, EOFError, UnicodeDecodeError, ValueError, zlib.error) as exc:
        raise ValueError(f'search.json.gz does not read: {exc}') from None
    found = data.get('aliases') if isinstance(data, dict) and data.get('version') == VERSION else None
    if not isinstance(found, dict):
        raise ValueError(f'search.json.gz is not version {VERSION} search data.')
    names = {}
    for key, values in found.items():
        if not key.isdigit() or not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError('search.json.gz holds a malformed entry.')
        names[int(key)] = values
    return names
