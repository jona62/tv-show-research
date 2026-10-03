"""Bounded, short-lived computed answers keyed by every recommendation input.

Only JSON bytes are retained. Every reader receives new objects, so HTTP artwork
decoration or a filtered view cannot change another request's answer.
"""
from collections import OrderedDict
from concurrent.futures import Future
from functools import wraps
import hashlib
import json
import os
import threading
import time
from .. import telemetry


def configured(name, default, maximum):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return min(value, maximum) if value > 0 else default


class Answers:
    def __init__(self, most=None, max_bytes=None, ttl=60, clock=time.monotonic):
        if most is None:
            most = configured('COUCHSIDE_RECOMMENDATION_CACHE_ENTRIES', 1024, 50000)
        if max_bytes is None:
            max_bytes = configured('COUCHSIDE_RECOMMENDATION_CACHE_MB', 32, 512) * 1024 * 1024
        self.most, self.max_bytes, self.ttl, self.clock = most, max_bytes, ttl, clock
        self.lock, self.kept, self.pending = threading.Lock(), OrderedDict(), {}
        self.bytes = self.hits = self.misses = self.coalesced = 0
        self.generation = 0

    def clear(self):
        """Invalidate retained answers without letting older work republish them."""
        with self.lock:
            self.generation += 1
            self.kept.clear()
            self.pending.clear()
            self.bytes = 0

    def get(self, key, make):
        body = None
        with self.lock:
            held = self.kept.get(key)
            if held and held[0] > self.clock():
                self.kept.move_to_end(key)
                self.hits += 1
                telemetry.cache('recommendation_answers', 'hit')
                body = held[1]
            elif held:
                self.bytes -= len(self.kept.pop(key)[1])
            if body is None:
                pending = self.pending.get(key)
                owner = pending is None
                if owner:
                    generation = self.generation
                    pending = Future()
                    if len(self.pending) < 128:
                        self.pending[key] = pending
                    self.misses += 1
                    telemetry.cache('recommendation_answers', 'miss')
                else:
                    self.coalesced += 1
                    telemetry.cache('recommendation_answers', 'coalesced')
        if body is not None:
            return json.loads(body)
        if not owner:
            return json.loads(pending.result())
        try:
            value = make()
            body = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
            with self.lock:
                if generation == self.generation and len(body) <= self.max_bytes:
                    previous = self.kept.pop(key, None)
                    self.bytes -= len(previous[1]) if previous else 0
                    self.kept[key] = (self.clock() + self.ttl, body)
                    self.bytes += len(body)
                    while len(self.kept) > self.most or self.bytes > self.max_bytes:
                        self.bytes -= len(self.kept.popitem(last=False)[1][1])
            pending.set_result(body)
            return value
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self.lock:
                if self.pending.get(key) is pending:
                    self.pending.pop(key)


def response(method):
    @wraps(method)
    def cached(library, body):
        discovery = getattr(library, 'discovery', None)
        scope = (method.__name__, id(library.e), getattr(library, 'rules', {}),
                 discovery.store.revision if discovery else 0, library.ahead)
        try:
            key = hashlib.sha256(json.dumps((scope, body), sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).encode()).digest()
        except (TypeError, ValueError):
            return method(library, body)
        return library.answers.get(key, lambda: method(library, body))
    return cached
