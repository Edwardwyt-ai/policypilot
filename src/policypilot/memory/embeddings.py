"""Embedding providers for episodic-memory formation and recall."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

import httpx


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    version: str
    prompt_tokens: int = 0
    latency_ms: float = 0.0
    fallback_used: bool = False
    failed: bool = False


class EpisodeEmbedder(Protocol):
    model: str
    version: str

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch: ...


def normalize_vector(values: Sequence[float]) -> list[float]:
    vector = [float(value) for value in values]
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class OllamaEpisodeEmbedder:
    """Synchronous local Ollama embedding node with bounded failure behavior."""

    version = "ollama-native-v1"

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "qwen3-embedding:0.6b",
        timeout_seconds: float = 60.0,
        fallback: EpisodeEmbedder | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts:
            raise ValueError("Embedding batch must not be empty")
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.endpoint}/api/embed",
                    json={
                        "model": self.model,
                        "input": list(texts),
                        "truncate": True,
                        "keep_alive": "10m",
                    },
                )
                response.raise_for_status()
            payload = response.json()
            raw_vectors = payload.get("embeddings")
            if not isinstance(raw_vectors, list) or len(raw_vectors) != len(texts):
                raise ValueError("Ollama returned an invalid embedding batch")
            vectors = [normalize_vector(vector) for vector in raw_vectors]
            if any(not vector for vector in vectors):
                raise ValueError("Ollama returned an empty embedding vector")
            return EmbeddingBatch(
                vectors=vectors,
                model=self.model,
                version=self.version,
                prompt_tokens=int(payload.get("prompt_eval_count") or 0),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            if self.fallback is None:
                raise RuntimeError("Local memory embedding request failed") from exc
            fallback = self.fallback.embed(texts)
            return EmbeddingBatch(
                vectors=fallback.vectors,
                model=fallback.model,
                version=fallback.version,
                prompt_tokens=fallback.prompt_tokens,
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback_used=True,
                failed=True,
            )
