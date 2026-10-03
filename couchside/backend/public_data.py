"""Bounded prepared public responses, independent of the HTTP serving runtime.

Only public-data services use this cache. Authentication, lists and personalized
recommendations must never enter it. Stored bytes are immutable; concurrent
readers share both response construction and compression.
"""
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, replace
import gzip
import hashlib
import json
import math
import threading
import time

from . import telemetry


def tag(body):
    return '"' + hashlib.sha256(body).hexdigest()[:24] + '"'


def accepts_gzip(header):
    weights = {}
    for part in (header or '').split(','):
        coding, *parameters = part.split(';')
        weight = 1.0
        for parameter in parameters:
            name, _, raw = parameter.partition('=')
            if name.strip().lower() == 'q':
                try:
                    weight = float(raw)
                except ValueError:
                    weight = 0.0
        weights[coding.strip().lower()] = weight
    return weights.get('gzip', weights.get('x-gzip', weights.get('*', 0))) > 0


@dataclass(frozen=True)
class Representation:
    status: int
    body: bytes
    headers: tuple


@dataclass(frozen=True)
class PreparedResponse:
    body: bytes
    gzip: bytes | None
    etag: str
    gzip_etag: str | None
    max_age: int = 0
    status: int = 200

    @property
    def size(self):
        return len(self.body) + len(self.gzip or b'')

    @property
    def cache_control(self):
        return f'public, max-age={self.max_age}' if self.max_age > 0 and self.status == 200 else 'no-store'

    def select(self, accept_encoding='', if_none_match=None, head=False):
        compressed = self.gzip is not None and accepts_gzip(accept_encoding)
        body, validator = (self.gzip, self.gzip_etag) if compressed else (self.body, self.etag)
        names = {name.strip().removeprefix('W/') for name in (if_none_match or '').split(',')}
        fresh = self.max_age > 0 and self.status == 200 and ('*' in names or validator in names)
        status = 304 if fresh else self.status
        headers = [('Cache-Control', self.cache_control), ('Vary', 'Accept-Encoding')]
        if self.max_age > 0 and self.status == 200:
            headers.append(('ETag', validator))
        if not fresh:
            headers.extend((('Content-Type', 'application/json; charset=utf-8'),
                            ('Content-Length', str(len(body)))))
            if compressed:
                headers.append(('Content-Encoding', 'gzip'))
        if status == 503:
            headers.append(('Retry-After', '2'))
        return Representation(status, b'' if fresh or head else body, tuple(headers))


def prepare(value, max_age=0, status=200):
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    packed = gzip.compress(body, compresslevel=6, mtime=0) if len(body) >= 512 else None
    if packed is not None and len(packed) >= len(body) * .9:
        packed = None
    return PreparedResponse(body, packed, tag(body), tag(packed) if packed is not None else None,
                            max(0, int(max_age)) if status == 200 else 0, status)


class CacheBusy(RuntimeError):
    """Too many distinct responses are already being prepared."""


class PreparedCache:
    def __init__(self, max_bytes=32 * 1024 * 1024, most=512, max_pending=64, clock=time.monotonic):
        self.max_bytes, self.most, self.max_pending, self.clock = max_bytes, most, max_pending, clock
        self.lock, self.entries, self.pending = threading.Lock(), OrderedDict(), {}
        self.bytes = 0

    def _drop(self, key):
        found = self.entries.pop(key, None)
        if found:
            self.bytes -= found[1].size

    def get(self, key, build):
        with self.lock:
            now = self.clock()
            held = self.entries.get(key)
            if held and held[0] > now:
                self.entries.move_to_end(key)
                telemetry.cache('public_json', 'hit')
                return replace(held[1], max_age=max(1, math.floor(held[0] - now)))
            self._drop(key)
            pending = self.pending.get(key)
            owner = pending is None
            if owner:
                if len(self.pending) >= self.max_pending:
                    raise CacheBusy('Public show data is loading. Try again in a moment.')
                pending = self.pending[key] = Future()
        if not owner:
            telemetry.cache('public_json_inflight', 'coalesced')
            return pending.result(timeout=10)
        telemetry.cache('public_json', 'miss')
        try:
            found = build()
            if found.status == 200 and found.max_age > 0 and found.size <= self.max_bytes:
                with self.lock:
                    now = self.clock()
                    for stale in [k for k, held in self.entries.items() if held[0] <= now]:
                        self._drop(stale)
                    self.entries[key] = (now + found.max_age, found)
                    self.bytes += found.size
                    while self.entries and (self.bytes > self.max_bytes or len(self.entries) > self.most):
                        self._drop(next(iter(self.entries)))
            pending.set_result(found)
            return found
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)
