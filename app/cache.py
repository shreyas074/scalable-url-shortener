"""
Cache layer for hot short_code -> original_url lookups.

Design note: redirects are read-heavy and latency-sensitive, so we never want
a redirect to cost a DB round trip if we can help it. This module exposes a
tiny interface (get/set/evict) so main.py doesn't care whether the backing
store is Redis or an in-process LRU cache.

If REDIS_URL is set and reachable, we use Redis (this is what you'd run in
production / describe as "the cache layer" in an interview). Otherwise we
fall back to an in-memory OrderedDict-based LRU so the project still runs
with zero external dependencies on a laptop.
"""
import os
from collections import OrderedDict
from threading import Lock
from typing import Optional

REDIS_URL = os.environ.get("REDIS_URL")

_backend = None
_redis_client = None

if REDIS_URL:
    try:
        import redis

        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        _backend = "redis"
    except Exception:
        _backend = None  # fall through to in-memory


class LRUCache:
    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._store: OrderedDict[str, str] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            if len(self._store) > self.capacity:
                self._store.popitem(last=False)  # evict least-recently-used

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


_lru = LRUCache(capacity=2000)


def cache_get(key: str) -> Optional[str]:
    if _backend == "redis":
        return _redis_client.get(key)
    return _lru.get(key)


def cache_set(key: str, value: str) -> None:
    if _backend == "redis":
        _redis_client.set(key, value, ex=3600)  # 1hr TTL in prod
        return
    _lru.set(key, value)


def cache_delete(key: str) -> None:
    if _backend == "redis":
        _redis_client.delete(key)
        return
    _lru.delete(key)


def backend_name() -> str:
    return _backend or "in-memory-lru"
