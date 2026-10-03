"""Public show backdrops, shared across browsers through a bounded durable cache."""
from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path
from urllib.error import HTTPError, URLError
import os
import re
import sqlite3
import threading
import time

from .http_client import Client, State, state_path
from .live import LiveError
from . import telemetry

DAY = 86400
MAX_IMAGE = 5 * 1024 * 1024
MAX_CACHE = 128 * 1024 * 1024
# Only provider-generated raster paths are accepted; there is no public URL proxy.
IMAGE_URL = re.compile(
    r'https://(?:image\.tmdb\.org/t/p/(?:w\d{2,4}|original)/[A-Za-z0-9_-]{1,100}'
    r'|static\.tvmaze\.com/uploads/images/(?:original_untouched|original|o|medium_landscape|medium_portrait)/\d{1,9}/\d{1,12})'
    r'\.(?:jpg|jpeg|png|webp)'
)
DISPLAY_WIDTHS = {780, 1280}


def backdrop_width(query):
    """Two provider sizes keep public cache variants bounded, without a URL proxy."""
    values = query.get('w')
    if values is None:
        return None
    if len(values) != 1 or values[0] not in {'780', '1280'}:
        raise ValueError('Choose a supported background image size.')
    return int(values[0])


def display_source(source, width):
    if width is not None and width not in DISPLAY_WIDTHS:
        raise ValueError('Choose a supported background image size.')
    if width and source.startswith('https://image.tmdb.org/'):
        return re.sub(r'/t/p/(?:w\d{2,4}|original)/', f'/t/p/w{width}/', source)
    return source


def image_kind(body):
    """Serve a raster type from its bytes, never an upstream HTML or SVG answer."""
    if body.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if body.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if body.startswith(b'RIFF') and body[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('Not a supported raster image')


def cache_path():
    return Path(os.environ.get('ARTWORK_CACHE') or state_path().with_name('artwork.sqlite3'))


class Backdrops:
    """Resolve one show once, and keep image bytes outside the smaller API cache.

    The existing HTTP reader supplies bounded streaming, same-origin redirects,
    retries, pooling, per-host pacing, durable storage and URL request coalescing.
    This layer also coalesces the metadata lookup by show and caches missing art.
    """
    def __init__(self, resolve, reader=None, clock=time.monotonic, size=512, ttl=6 * 3600):
        self.resolve, self.reader, self.clock, self.size, self.ttl = resolve, reader, clock, size, ttl
        self.lock = threading.Lock()
        self.sources, self.inflight, self.resolving = OrderedDict(), {}, {}
        self.missing_variants = OrderedDict()

    def _reader(self):
        with self.lock:
            if self.reader is None:
                self.reader = Client(State(cache_path(), max_bytes=MAX_CACHE))
            return self.reader

    def _remember(self, show_id, source, ttl):
        with self.lock:
            self.sources[show_id] = (self.clock() + ttl, source)
            self.sources.move_to_end(show_id)
            while len(self.sources) > self.size:
                self.sources.popitem(last=False)

    def get(self, show_id, width=None):
        if width is not None and width not in DISPLAY_WIDTHS:
            raise ValueError('Choose a supported background image size.')
        key = (show_id, width)
        with self.lock:
            pending = self.inflight.get(key)
            owner = pending is None
            if owner:
                pending = self.inflight[key] = Future()
        if not owner:
            telemetry.cache('artwork_inflight', 'coalesced', 'image')
            try:
                return pending.result(timeout=16)
            except TimeoutError:
                raise LiveError('The background image is still loading.', 503) from None
        try:
            value = self._get(show_id, width)
            pending.set_result(value)
            return value
        except Exception as error:
            pending.set_exception(error)
            raise
        finally:
            with self.lock:
                self.inflight.pop(key, None)

    def _source(self, show_id):
        with self.lock:
            held = self.sources.get(show_id)
            if held and held[0] > self.clock():
                self.sources.move_to_end(show_id)
                telemetry.cache('artwork_source_memory', 'hit' if held[1] else 'negative', 'image')
                return held[1]
            telemetry.cache('artwork_source_memory', 'miss', 'image')
            pending = self.resolving.get(show_id)
            owner = pending is None
            if owner:
                pending = self.resolving[show_id] = Future()
        if not owner:
            telemetry.cache('artwork_source_inflight', 'coalesced', 'image')
            try:
                return pending.result(timeout=16)
            except TimeoutError:
                raise LiveError('The background image is still loading.', 503) from None
        try:
            source = self.resolve(show_id)
            if source is not None and (not isinstance(source, str) or not IMAGE_URL.fullmatch(source)):
                raise LiveError('The background image is not available.')
            self._remember(show_id, source, self.ttl if source else 300)
            pending.set_result(source)
            return source
        except Exception as error:
            pending.set_exception(error)
            raise
        finally:
            with self.lock:
                self.resolving.pop(show_id, None)

    def _read(self, source):
        value = self._reader().get(source, headers={'Accept': 'image/jpeg,image/png,image/webp'},
                                   ttl=7 * DAY, stale=30 * DAY, max_bytes=MAX_IMAGE,
                                   budget=8, validate=image_kind)
        image_kind(value.body)
        return value

    def _get(self, show_id, width):
        source = self._source(show_id)
        if not source:
            return None
        try:
            variant = display_source(source, width)
            with self.lock:
                if self.missing_variants.get(variant, 0) > self.clock():
                    variant = source
            try:
                return self._read(variant)
            except HTTPError as error:
                # A provider thumbnail can be absent while the original exists.
                if error.code != 404 or variant == source:
                    raise
                with self.lock:
                    self.missing_variants[variant] = self.clock() + 300
                    self.missing_variants.move_to_end(variant)
                    while len(self.missing_variants) > self.size * 2:
                        self.missing_variants.popitem(last=False)
                return self._read(source)
        except HTTPError as error:
            if error.code == 404:
                self._remember(show_id, None, 300)
                return None
            raise LiveError('The background image could not be reached.') from None
        except (URLError, OSError, ValueError, sqlite3.Error):
            raise LiveError('The background image could not be reached.') from None
