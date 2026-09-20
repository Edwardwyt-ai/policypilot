"""Candidate-level cache for deterministic knowledge retrieval."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from tau2.knowledge.cache_backend import CacheBackend, InMemoryCacheBackend


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip().lower()


@dataclass(frozen=True)
class RetrievalCacheEntry:
    candidates: tuple[tuple[str, float], ...]
    created_at: float
    retriever_version: str
    kb_version: str
    retrieval_ms: float


@dataclass
class RetrievalCacheMetrics:
    hits: int = 0
    misses: int = 0
    saved_latency_ms: float = 0.0

    def snapshot(self) -> dict[str, float | int]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": self.hits / total if total else 0.0,
            "saved_latency_ms": round(self.saved_latency_ms, 3),
        }


@dataclass
class RetrievalCacheSettings:
    enabled: bool = False
    ttl_seconds: float | None = 900.0
    retriever_version: str = "v1"
    kb_version: str = "v1"


@dataclass
class RetrievalCache:
    backend: CacheBackend[RetrievalCacheEntry] = field(default_factory=InMemoryCacheBackend)
    settings: RetrievalCacheSettings = field(default_factory=RetrievalCacheSettings)
    metrics: RetrievalCacheMetrics = field(default_factory=RetrievalCacheMetrics)

    def key(self, query: str, *, filters: dict[str, Any], top_k: int | None, config: dict[str, Any]) -> str:
        payload = {
            "query": normalize_query(query),
            "filters": filters,
            "top_k": top_k,
            "retriever_version": self.settings.retriever_version,
            "kb_version": self.settings.kb_version,
            "config": config,
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

    def get(self, key: str) -> RetrievalCacheEntry | None:
        if not self.settings.enabled:
            return None
        entry = self.backend.get(key)
        if entry is None:
            self.metrics.misses += 1
            return None
        ttl = self.settings.ttl_seconds
        if ttl is not None and time.time() - entry.created_at > ttl:
            self.backend.delete(key)
            self.metrics.misses += 1
            return None
        if (
            entry.retriever_version != self.settings.retriever_version
            or entry.kb_version != self.settings.kb_version
        ):
            self.backend.delete(key)
            self.metrics.misses += 1
            return None
        self.metrics.hits += 1
        self.metrics.saved_latency_ms += entry.retrieval_ms
        return entry

    def set(self, key: str, candidates: list[tuple[str, float]], retrieval_ms: float) -> None:
        if not self.settings.enabled:
            return
        self.backend.set(
            key,
            RetrievalCacheEntry(
                candidates=tuple(candidates),
                created_at=time.time(),
                retriever_version=self.settings.retriever_version,
                kb_version=self.settings.kb_version,
                retrieval_ms=retrieval_ms,
            ),
        )


_cache = RetrievalCache()


def configure_retrieval_cache(
    *, enabled: bool, ttl_seconds: float | None, retriever_version: str, kb_version: str
) -> None:
    _cache.settings = RetrievalCacheSettings(
        enabled=enabled,
        ttl_seconds=ttl_seconds,
        retriever_version=retriever_version,
        kb_version=kb_version,
    )


def get_retrieval_cache() -> RetrievalCache:
    return _cache


def get_retrieval_cache_metrics() -> dict[str, float | int]:
    return _cache.metrics.snapshot()
