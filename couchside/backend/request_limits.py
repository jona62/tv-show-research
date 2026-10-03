"""Fixed request budgets with bounded per-address state. Health and assets are exempt."""
from collections import OrderedDict
from functools import lru_cache
import ipaddress
import math
import os
import threading
import time

MAX_CLIENTS = 20000


def _ip(value):
    parsed = ipaddress.ip_address(value)
    return parsed.ipv4_mapped if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped else parsed


@lru_cache(maxsize=8)
def _proxy_ips(configured):
    try:
        return frozenset(_ip(value.strip()) for value in configured.split(',') if value.strip())
    except ValueError:
        raise ValueError('COUCHSIDE_TRUSTED_PROXY_IPS must contain exact IP addresses, not networks or hostnames.') from None


def trusted_proxy_ips():
    """Only verified deployment peers are trusted beyond the local proxy."""
    return _proxy_ips(os.environ.get('COUCHSIDE_TRUSTED_PROXY_IPS', ''))


class Budget:
    def __init__(self, rate=8, burst=40, clock=time.monotonic, most=MAX_CLIENTS):
        # A proxy pool may send every client through every process. Keep enough
        # state for the supported 10,000-user population plus arrival churn;
        # splitting this bound by worker count would reset active rate limits.
        self.rate, self.burst, self.clock, self.most = rate, burst, clock, most
        self.lock, self.clients = threading.Lock(), OrderedDict()

    def take(self, key):
        now = self.clock()
        with self.lock:
            tokens, at = self.clients.pop(key, (self.burst, now))
            tokens = min(self.burst, tokens + max(0, now - at) * self.rate)
            wait = max(0, (1 - tokens) / self.rate)
            self.clients[key] = (tokens if wait else tokens - 1, now)
            while len(self.clients) > self.most:
                self.clients.popitem(last=False)
            return math.ceil(wait)


def address(peer, forwarded):
    """Walk verified proxies toward the nearest untrusted client, never past it."""
    try:
        source = _ip(peer)
    except ValueError:
        return peer
    trusted = trusted_proxy_ips()
    if not (source.is_loopback or source in trusted):
        return str(source)
    try:
        for value in reversed((forwarded or '').split(',')):
            hop = _ip(value.strip())
            if not (hop.is_loopback or hop in trusted):
                return str(hop)
    except ValueError:
        pass
    # Missing, malformed, or entirely trusted chains cannot identify a client.
    # Keep these requests on the immediate peer's budget rather than trusting
    # a caller-supplied address to the left of an unverified hop.
    return str(source)


class Requests:
    def __init__(self, client=None, global_budget=None):
        # Reject bad deployment trust configuration at startup, before serving.
        trusted_proxy_ips()
        # The runtime bounds concurrent work by route. A fixed global RPS ceiling
        # rejected cheap cache hits along with expensive work, regardless of load.
        workers = max(1, int(os.environ.get('COUCHSIDE_WORKERS', '1')))
        self.client = client or Budget(rate=8 / workers, burst=max(1, 40 / workers))
        self.global_budget = global_budget

    def take(self, peer, forwarded=''):
        wait = self.client.take(address(peer, forwarded))
        return wait or (self.global_budget.take('server') if self.global_budget else 0)
