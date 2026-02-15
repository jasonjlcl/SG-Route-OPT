from __future__ import annotations

import json
import threading
import time
from typing import Any

import redis

from app.utils.settings import get_settings


class CacheBackend:
    def get(self, key: str) -> Any:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class RedisCache(CacheBackend):
    def __init__(self, redis_url: str):
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.client.ping()

    def get(self, key: str) -> Any:
        raw = self.client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        raw = json.dumps(value, default=str)
        if ttl_seconds:
            self.client.setex(key, ttl_seconds, raw)
        else:
            self.client.set(key, raw)

    def delete(self, key: str) -> None:
        self.client.delete(key)


class InMemoryCache(CacheBackend):
    def __init__(self):
        self._store: dict[str, tuple[float | None, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            data = self._store.get(key)
            if data is None:
                return None
            expire_at, value = data
            if expire_at is not None and expire_at < time.time():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        expire_at = time.time() + ttl_seconds if ttl_seconds else None
        with self._lock:
            self._store[key] = (expire_at, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


_CACHE: CacheBackend | None = None


def get_cache() -> CacheBackend:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    settings = get_settings()
    try:
        _CACHE = RedisCache(settings.redis_url)
    except Exception:  # noqa: BLE001
        _CACHE = InMemoryCache()
    return _CACHE
