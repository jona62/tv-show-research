"""Fixed request budgets with bounded per-address state. Health and assets are exempt."""
from collections import OrderedDict
import ipaddress
import math
import threading
import time


class Budget:
    def __init__(self, rate=8, burst=40, clock=time.monotonic, most=5000):
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
    """Only the local reverse proxy may supply a client address; public callers cannot spoof it."""
    try:
        source = ipaddress.ip_address(peer)
        if source.is_loopback and forwarded:
            return str(ipaddress.ip_address(forwarded.split(',')[-1].strip()))
        return str(source)
    except ValueError:
        return peer


class Requests:
    def __init__(self, client=None, global_budget=None):
        self.client = client or Budget()
        self.global_budget = global_budget or Budget(rate=24, burst=120, most=1)

    def take(self, peer, forwarded=''):
        wait = self.client.take(address(peer, forwarded))
        return wait or self.global_budget.take('server')
