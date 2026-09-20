"""Minimal cache backend contract used at deterministic retrieval boundaries."""
from __future__ import annotations

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

