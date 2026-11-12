"""Minimal cache backend contract used at deterministic retrieval boundaries."""

from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class CacheBackend(ABC, Generic[T]):
    @abstractmethod
    def get(self, key: str) -> T | None: ...

    @abstractmethod
    def set(self, key: str, value: T) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class InMemoryCacheBackend(CacheBackend[T]):
    """Thread-safe process-local backend with no external dependency."""

    def __init__(self):
        self._values: dict[str, T] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> T | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: T) -> None:
        with self._lock:
            self._values[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)


class RedisCacheBackend(CacheBackend[T]):
    """TTL-bound JSON cache; unavailable or malformed entries are cache misses."""

    def __init__(
        self,
        *,
        url: str,
        ttl_seconds: int = 900,
        encode=lambda value: value,
        decode=lambda value: value,
        prefix: str = "policypilot:retrieval:v1:",
        client=None,
    ):
        from redis import Redis

        self.client = client or Redis.from_url(
            url, socket_timeout=1, socket_connect_timeout=1
        )
        self.ttl_seconds = max(1, ttl_seconds)
        self.encode = encode
        self.decode = decode
        self.prefix = prefix

    def get(self, key: str) -> T | None:
        from redis.exceptions import RedisError

        try:
            value = self.client.get(self.prefix + key)
            return self.decode(json.loads(value)) if value is not None else None
        except (RedisError, ValueError, TypeError, KeyError):
            logging.getLogger(__name__).warning(
                "Retrieval cache unavailable or invalid; treating as miss"
            )
            return None

    def set(self, key: str, value: T) -> None:
        from redis.exceptions import RedisError

        try:
            self.client.set(
                self.prefix + key, json.dumps(self.encode(value)), ex=self.ttl_seconds
            )
        except RedisError:
            logging.getLogger(__name__).warning(
                "Retrieval cache unavailable; result not cached"
            )

    def delete(self, key: str) -> None:
        from redis.exceptions import RedisError

        try:
            self.client.delete(self.prefix + key)
        except RedisError:
            logging.getLogger(__name__).warning(
                "Retrieval cache unavailable; delete skipped"
            )


def configured_text_cache():
    url = os.getenv("POLICYPILOT_REDIS_URL")
    return (
        RedisCacheBackend[str](url=url, prefix="policypilot:policy-response:v1:")
        if url
        else None
    )
