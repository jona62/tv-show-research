"""Each show's closest shows, read from neighbours.bin.gz beside the model.

pipeline/jobs/build_neighbours.py writes it every night: for every catalog show, its WIDTH
closest recommendable shows under the engine's default closeness, closest first, with
the plot-text and facet parts of each, and how many shows count each show among their
closest. The engine ranks a long list from these (engine.Wide), since working out how
close every show sits to each of thousands of rated ones is out of reach in
standard-library Python. Standard library only, every value in a typed array or bytes,
about 30 MB a model. Couchside's build.py copies this file, like engine.py.

    found = load(model_dir, engine.n)       # None when the model has none
    indices, near, text, bonus = found.row(i)
"""
from array import array
from pathlib import Path
import gzip
import struct
import sys
import zlib

MAGIC = b'NBR1'
# How closeness and the facet part are packed into a byte: round(255 x sqrt(value / most)),
# finer where most values lie. pipeline/jobs/build_neighbours.py packs with the same.
NEAR_MAX = 4.5
BONUS_MAX = 11.2
NEAR = tuple(NEAR_MAX * (q / 255) ** 2 for q in range(256))
TEXT = tuple(q / 255 for q in range(256))
BONUS = tuple(BONUS_MAX * (q / 255) ** 2 for q in range(256))


class Neighbours:
    """rows x width neighbours: catalog indices, closeness, plot-text closeness and the
    facet part, and each show's degree."""

    def __init__(self, rows, width, index, near, text, bonus, degree):
        self.rows, self.width = rows, width
        self.index, self.near, self.text, self.bonus, self.degree = index, near, text, bonus, degree

    def row(self, i):
        """(indices, closeness at the default settings, plot-text closeness, facet part)
        for show i, closest first."""
        lo = i * self.width
        hi = lo + self.width
        return (self.index[lo:hi], list(map(NEAR.__getitem__, self.near[lo:hi])),
                list(map(TEXT.__getitem__, self.text[lo:hi])), list(map(BONUS.__getitem__, self.bonus[lo:hi])))


def load(model_dir, n):
    """The model's neighbours, or None when it has none. ValueError when the file is
    there but does not fit a catalog of n shows."""
    path = Path(model_dir) / 'neighbours.bin.gz'
    if not path.exists():
        return None
    try:
        with gzip.open(path, 'rb') as f:
            head = f.read(12)
            if len(head) != 12:
                raise ValueError('neighbours.bin.gz is truncated.')
            magic, rows, width = struct.unpack('<4sII', head)
            if magic != MAGIC:
                raise ValueError('neighbours.bin.gz is not a neighbour index.')
            if rows != n:
                raise ValueError(f'neighbours.bin.gz has {rows:,} rows where the catalog has {n:,} shows.')
            if not 0 < width <= 1024:
                raise ValueError('neighbours.bin.gz has no sensible width.')
            count = rows * width
            index, degree = array('I'), array('H')
            index.frombytes(f.read(4 * count))
            near, text, bonus = f.read(count), f.read(count), f.read(count)
            degree.frombytes(f.read(2 * rows))
            if sys.byteorder != 'little':
                index.byteswap()
                degree.byteswap()
            if len(index) != count or len(near) != count or len(text) != count or len(bonus) != count \
                    or len(degree) != rows or f.read(1):
                raise ValueError('neighbours.bin.gz does not hold rows x width neighbours.')
    except (OSError, EOFError, struct.error, zlib.error) as exc:
        raise ValueError(f'neighbours.bin.gz does not read: {exc}') from None
    if count and max(index) >= n:
        raise ValueError('neighbours.bin.gz points outside the catalog.')
    return Neighbours(rows, width, index, near, text, bonus, degree)
