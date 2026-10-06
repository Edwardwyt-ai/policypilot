"""Constraint-preserving query rewrite, hybrid retrieval, and reranking."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from tau2.domains.banking_knowledge.local_reranker import PassageReranker
from tau2.domains.banking_knowledge.vectorization import (
    ChunkInput,
    OllamaEmbeddingClient,
    load_chunks,
    sha256_file,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", re.I)
_QUOTED_RE = re.compile(r"[\"']([^\"']{2,80})[\"']")
_NEGATED_RE = re.compile(
    r"\b(?:no|not|without|under|over|at least|at most|minimum|maximum)"
    r"(?:\s+(?!(?:and|or|but|with|at least|at most)\b)[a-z0-9%$-]+){1,4}",
    re.I,
)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_QUERY_INSTRUCTION = (
    "Given a banking policy search query, retrieve passages that directly answer "
    "the query while preserving every stated constraint"
)
_MUTUALLY_EXCLUSIVE_SCOPES = (
    ("personal", "business"),
    ("credit", "debit"),
    ("checking", "savings"),
)


def tokenize(text: str) -> list[str]:
    """Tokenize English policy text consistently for sparse retrieval."""
    return [token.lower().replace("_", "-") for token in _TOKEN_RE.findall(text)]


@dataclass(frozen=True)
class RewrittenQuery:
    original: str
    normalized: str
    lexical_tokens: tuple[str, ...]
    dense_query: str
    anchors: tuple[str, ...]
    exact_phrases: tuple[str, ...]


class ConstraintPreservingQueryRewriter:
    """Create sparse and dense forms without deleting original constraints."""

    def rewrite(self, query: str) -> RewrittenQuery:
        normalized = " ".join(query.split()).strip()
        if not normalized:
            raise ValueError("Search query must not be empty")

        lexical_tokens = tuple(tokenize(normalized))
        anchors = tuple(
            dict.fromkeys(
                token
                for token in lexical_tokens
                if token not in _STOP_WORDS and (len(token) >= 3 or token.isdigit())
            )
        )
        phrases = [match.group(1).lower() for match in _QUOTED_RE.finditer(normalized)]
        phrases.extend(
            match.group(0).lower() for match in _NEGATED_RE.finditer(normalized)
        )
        exact_phrases = tuple(dict.fromkeys(phrases))
        dense_query = f"Instruct: {_QUERY_INSTRUCTION}\nQuery:{normalized}"
        return RewrittenQuery(
            original=query,
            normalized=normalized,
            lexical_tokens=lexical_tokens,
            dense_query=dense_query,
            anchors=anchors,
            exact_phrases=exact_phrases,
        )


@dataclass(frozen=True)
class HybridSearchHit:
    document_id: str
    title: str
    score: float
    content: str
    chunk_ids: tuple[str, ...]
    dense_score: float
    sparse_score: float
    anchor_coverage: float


@dataclass(frozen=True)
class HybridSearchResponse:
    query: RewrittenQuery
    hits: tuple[HybridSearchHit, ...]
    timing_ms: dict[str, float] = field(default_factory=dict)
    channel_queries: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _ChunkScore:
    row: int
    fused_score: float
    dense_score: float
    sparse_score: float
    anchor_coverage: float
    model_score: float | None = None


class DenseIndex(Protocol):
    """Minimal dense backend contract used by the hybrid retriever."""

    def search(
        self, query_vector: np.ndarray, limit: int
    ) -> tuple[np.ndarray, list[int]]: ...


class LocalHybridPolicyRetriever:
    """Search a prebuilt chunk index with sparse+dense retrieval and reranking."""

    def __init__(
        self,
        *,
        chunks_path: Path,
        index_dir: Path,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "qwen3-embedding:0.6b",
        candidate_k: int = 30,
        top_k: int = 5,
        chunks_per_document: int = 2,
        embedding_client: OllamaEmbeddingClient | None = None,
        dense_index: DenseIndex | None = None,
        reranker: PassageReranker | None = None,
        rerank_candidate_k: int = 20,
        model_rerank_weight: float = 0.35,
        need_channel_weight: float = 0.65,
    ) -> None:
        if candidate_k < top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        self.chunks_path = chunks_path
        self.index_dir = index_dir
        self.candidate_k = candidate_k
        self.top_k = top_k
        self.chunks_per_document = chunks_per_document
        self.rewriter = ConstraintPreservingQueryRewriter()
        self.embedding_client = embedding_client or OllamaEmbeddingClient(
            endpoint=endpoint,
            model=model,
        )
        self.dense_index = dense_index
        self.reranker = reranker
        self.rerank_candidate_k = rerank_candidate_k
        if not 0.0 <= model_rerank_weight <= 1.0:
            raise ValueError("model_rerank_weight must be between 0 and 1")
        self.model_rerank_weight = model_rerank_weight
        if not 0.0 <= need_channel_weight <= 1.0:
            raise ValueError("need_channel_weight must be between 0 and 1")
        self.need_channel_weight = need_channel_weight

        self.chunks = load_chunks(chunks_path)
        self.embeddings: np.ndarray | None = None
        self.metadata: list[dict] = []
        if self.dense_index is None:
            self.embeddings = np.load(index_dir / "embeddings.npy", mmap_mode="r")
            self.metadata = [
                json.loads(line)
                for line in (index_dir / "chunk_metadata.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self._validate_index(model)
        corpus = [tokenize(self._searchable_text(chunk)) for chunk in self.chunks]
        self.bm25 = BM25Okapi(corpus)

    @staticmethod
    def _searchable_text(chunk: ChunkInput) -> str:
        sections = " ".join(chunk.metadata.get("section_paths") or [])
        return f"{chunk.title}\n{sections}\n{chunk.text}"

    def _validate_index(self, model: str) -> None:
        if self.embeddings is None:
            raise ValueError("NumPy index is not loaded")
        manifest = json.loads(
            (self.index_dir / "manifest.json").read_text(encoding="utf-8")
        )
        expected_rows = len(self.chunks)
        if self.embeddings.ndim != 2 or self.embeddings.shape[0] != expected_rows:
            raise ValueError(
                f"Embedding rows {self.embeddings.shape} do not match {expected_rows} chunks"
            )
        if len(self.metadata) != expected_rows:
            raise ValueError("Chunk metadata row count does not match embeddings")
        if manifest.get("model") != model:
            raise ValueError(
                f"Index model {manifest.get('model')!r} does not match {model!r}"
            )
        if manifest.get("chunks_sha256") != sha256_file(self.chunks_path):
            raise ValueError("Chunk file changed after the embedding index was built")
        chunk_ids = [chunk.id for chunk in self.chunks]
        metadata_ids = [row.get("chunk_id") for row in self.metadata]
        if chunk_ids != metadata_ids:
            raise ValueError("Chunk metadata order does not match chunk input order")

    @staticmethod
    def _top_rows(scores: np.ndarray, limit: int) -> list[int]:
        limit = min(limit, scores.shape[0])
        if limit <= 0:
            return []
        indices = np.argpartition(scores, -limit)[-limit:]
        return [int(index) for index in indices[np.argsort(scores[indices])[::-1]]]

    @staticmethod
    def _normalise_positive(value: float, maximum: float) -> float:
        return max(0.0, value / maximum) if maximum > 0 else 0.0

    @staticmethod
    def _scope_conflict(query_tokens: set[str], title_tokens: set[str]) -> bool:
        """Detect an opposite product scope only when the query chose one side."""
        for left, right in _MUTUALLY_EXCLUSIVE_SCOPES:
            if left in query_tokens and right not in query_tokens:
                if right in title_tokens and left not in title_tokens:
                    return True
            if right in query_tokens and left not in query_tokens:
                if left in title_tokens and right not in title_tokens:
                    return True
        return False

    def _rerank(
        self,
        rewritten: RewrittenQuery,
        dense_scores: np.ndarray,
        sparse_scores: np.ndarray,
        dense_rows: list[int],
        sparse_rows: list[int],
    ) -> list[_ChunkScore]:
        dense_rank = {row: rank for rank, row in enumerate(dense_rows, start=1)}
        sparse_rank = {row: rank for rank, row in enumerate(sparse_rows, start=1)}
        candidates = set(dense_rows) | set(sparse_rows)
        max_sparse = max((float(sparse_scores[row]) for row in candidates), default=0.0)
        query_anchors = set(rewritten.anchors)
        query_tokens = set(rewritten.lexical_tokens)
        ranked: list[_ChunkScore] = []

        for row in candidates:
            chunk = self.chunks[row]
            searchable = self._searchable_text(chunk).lower()
            document_tokens = set(tokenize(searchable))
            anchor_coverage = (
                len(query_anchors.intersection(document_tokens)) / len(query_anchors)
                if query_anchors
                else 0.0
            )
            title_tokens = set(tokenize(chunk.title))
            title_coverage = (
                len(query_anchors.intersection(title_tokens)) / len(query_anchors)
                if query_anchors
                else 0.0
            )
            phrase_coverage = (
                sum(phrase in searchable for phrase in rewritten.exact_phrases)
                / len(rewritten.exact_phrases)
                if rewritten.exact_phrases
                else 0.0
            )
            dense = float(dense_scores[row])
            dense_normalized = min(1.0, max(0.0, (dense + 1.0) / 2.0))
            sparse = float(sparse_scores[row])
            sparse_normalized = self._normalise_positive(sparse, max_sparse)
            rrf = 0.0
            if row in dense_rank:
                rrf += 1.0 / (60 + dense_rank[row])
            if row in sparse_rank:
                rrf += 1.0 / (60 + sparse_rank[row])
            rrf_normalized = min(1.0, rrf * 31.0)
            fused = (
                0.34 * dense_normalized
                + 0.24 * sparse_normalized
                + 0.20 * anchor_coverage
                + 0.14 * title_coverage
                + 0.04 * phrase_coverage
                + 0.04 * rrf_normalized
            )
            if self._scope_conflict(query_tokens, title_tokens):
                fused -= 0.18
            ranked.append(
                _ChunkScore(
                    row=row,
                    fused_score=fused,
                    dense_score=dense,
                    sparse_score=sparse,
                    anchor_coverage=anchor_coverage,
                )
            )
        return sorted(ranked, key=lambda item: item.fused_score, reverse=True)

    def _model_rerank(
        self, rewritten: RewrittenQuery, ranked: list[_ChunkScore]
    ) -> list[_ChunkScore]:
        if self.reranker is None or not ranked:
            return ranked
        limit = min(self.rerank_candidate_k, len(ranked))
        head = ranked[:limit]
        documents = [self._searchable_text(self.chunks[item.row]) for item in head]
        model_scores = self.reranker.score(rewritten.normalized, documents)
        if model_scores.shape != (limit,):
            raise ValueError("Reranker score count does not match candidate count")

        model_weight = self.model_rerank_weight
        feature_weight = 1.0 - model_weight
        rescored = [
            _ChunkScore(
                row=item.row,
                fused_score=(
                    model_weight * float(model_score)
                    + feature_weight * item.fused_score
                ),
                dense_score=item.dense_score,
                sparse_score=item.sparse_score,
                anchor_coverage=item.anchor_coverage,
                model_score=float(model_score),
            )
            for item, model_score in zip(head, model_scores, strict=True)
        ]
        rescored.sort(key=lambda item: item.fused_score, reverse=True)
        return rescored + ranked[limit:]

    def _aggregate_documents(
        self, ranked_chunks: list[_ChunkScore], top_k: int
    ) -> tuple[HybridSearchHit, ...]:
        groups: dict[str, list[_ChunkScore]] = {}
        for score in ranked_chunks:
            chunk = self.chunks[score.row]
            group = groups.setdefault(chunk.document_id, [])
            if len(group) < self.chunks_per_document:
                group.append(score)

        hits: list[HybridSearchHit] = []
        for document_id, scores in groups.items():
            best = scores[0]
            chunks = [self.chunks[item.row] for item in scores]
            aggregate_score = best.fused_score
            if len(scores) > 1:
                aggregate_score += 0.02 * scores[1].fused_score
            content = "\n\n--- Relevant policy excerpt ---\n\n".join(
                chunk.text for chunk in chunks
            )
            hits.append(
                HybridSearchHit(
                    document_id=document_id,
                    title=chunks[0].title,
                    score=min(1.0, aggregate_score),
                    content=content,
                    chunk_ids=tuple(chunk.id for chunk in chunks),
                    dense_score=best.dense_score,
                    sparse_score=best.sparse_score,
                    anchor_coverage=best.anchor_coverage,
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return tuple(hits[:top_k])

    def _retrieve_features(
        self, query: str
    ) -> tuple[RewrittenQuery, list[_ChunkScore], dict[str, float]]:
        rewrite_start = time.perf_counter()
        rewritten = self.rewriter.rewrite(query)
        rewrite_ms = (time.perf_counter() - rewrite_start) * 1000

        sparse_start = time.perf_counter()
        sparse_scores = np.asarray(
            self.bm25.get_scores(list(rewritten.lexical_tokens)), dtype=np.float32
        )
        sparse_rows = self._top_rows(sparse_scores, self.candidate_k)
        sparse_ms = (time.perf_counter() - sparse_start) * 1000

        dense_start = time.perf_counter()
        query_vectors, _ = self.embedding_client.embed([rewritten.dense_query])
        query_vector = query_vectors[0]
        norm = np.linalg.norm(query_vector)
        if norm == 0:
            raise ValueError("Query embedding has zero norm")
        normalized_query = query_vector / norm
        if self.dense_index is not None:
            dense_scores, dense_rows = self.dense_index.search(
                normalized_query, self.candidate_k
            )
        else:
            if self.embeddings is None:
                raise RuntimeError("No dense retrieval backend is configured")
            dense_scores = self.embeddings @ normalized_query
            dense_rows = self._top_rows(dense_scores, self.candidate_k)
        dense_ms = (time.perf_counter() - dense_start) * 1000

        feature_rerank_start = time.perf_counter()
        ranked = self._rerank(
            rewritten,
            dense_scores,
            sparse_scores,
            dense_rows,
            sparse_rows,
        )
        feature_rerank_ms = (time.perf_counter() - feature_rerank_start) * 1000
        return (
            rewritten,
            ranked,
            {
                "rewrite": rewrite_ms,
                "sparse": sparse_ms,
                "dense": dense_ms,
                "feature_rerank": feature_rerank_ms,
            },
        )

    @staticmethod
    def _fuse_channels(
        channels: list[tuple[list[_ChunkScore], float]],
    ) -> list[_ChunkScore]:
        """Fuse ranked channel candidates without comparing raw rank positions alone."""

        by_row: dict[int, list[tuple[_ChunkScore, float, int]]] = {}
        for ranked, weight in channels:
            for rank, item in enumerate(ranked, start=1):
                by_row.setdefault(item.row, []).append((item, weight, rank))

        fused: list[_ChunkScore] = []
        for row, contributions in by_row.items():
            weighted_feature = sum(
                weight * max(0.0, item.fused_score) for item, weight, _ in contributions
            )
            weighted_rrf = sum(
                weight / (60 + rank) for _, weight, rank in contributions
            )
            # 61 maps a rank-1 contribution close to one while retaining the
            # cross-channel agreement bonus of reciprocal-rank fusion.
            score = 0.72 * weighted_feature + 0.28 * min(1.0, weighted_rrf * 61)
            total_weight = sum(weight for _, weight, _ in contributions) or 1.0
            fused.append(
                _ChunkScore(
                    row=row,
                    fused_score=score,
                    dense_score=sum(
                        item.dense_score * weight for item, weight, _ in contributions
                    )
                    / total_weight,
                    sparse_score=sum(
                        item.sparse_score * weight for item, weight, _ in contributions
                    )
                    / total_weight,
                    anchor_coverage=max(
                        item.anchor_coverage for item, _, _ in contributions
                    ),
                )
            )
        return sorted(fused, key=lambda item: item.fused_score, reverse=True)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        global_query: str | None = None,
    ) -> HybridSearchResponse:
        total_start = time.perf_counter()
        rewritten, ranked, timing = self._retrieve_features(query)
        channel_queries = [("need", rewritten.normalized)]

        normalized_global = " ".join((global_query or "").split()).strip()
        fusion_ms = 0.0
        if (
            normalized_global
            and normalized_global.casefold() != rewritten.normalized.casefold()
        ):
            global_rewritten, global_ranked, global_timing = self._retrieve_features(
                normalized_global
            )
            channel_queries.append(("global_user", global_rewritten.normalized))
            fusion_start = time.perf_counter()
            ranked = self._fuse_channels(
                [
                    (ranked, self.need_channel_weight),
                    (global_ranked, 1.0 - self.need_channel_weight),
                ]
            )
            fusion_ms = (time.perf_counter() - fusion_start) * 1000
            for key in ("rewrite", "sparse", "dense", "feature_rerank"):
                timing[key] += global_timing[key]
            rerank_query = self.rewriter.rewrite(
                f"{rewritten.normalized} {global_rewritten.normalized}"
            )
        else:
            rerank_query = rewritten

        model_rerank_start = time.perf_counter()
        ranked = self._model_rerank(rerank_query, ranked)
        model_rerank_ms = (time.perf_counter() - model_rerank_start) * 1000
        hits = self._aggregate_documents(ranked, top_k or self.top_k)
        rerank_ms = timing["feature_rerank"] + model_rerank_ms
        total_ms = (time.perf_counter() - total_start) * 1000
        timing.update(
            {
                "model_rerank": model_rerank_ms,
                "rerank": rerank_ms,
                "total": total_ms,
            }
        )
        if len(channel_queries) > 1:
            timing["fusion"] = fusion_ms
        return HybridSearchResponse(
            query=rewritten,
            hits=hits,
            timing_ms=timing,
            channel_queries=tuple(channel_queries),
        )


def format_hybrid_search_response(response: HybridSearchResponse) -> str:
    """Preserve the legacy KB_search text contract consumed by PolicyPilot."""
    if not response.hits:
        return (
            "No relevant documents found.\n\n"
            f"[Timing: retrieval={response.timing_ms['total']:.0f}ms, "
            f"reranking={response.timing_ms['rerank']:.0f}ms, "
            f"total={response.timing_ms['total']:.0f}ms]"
        )

    formatted = []
    for index, hit in enumerate(response.hits, start=1):
        formatted.append(
            f"{index}. {hit.title}\n"
            f"   ID: {hit.document_id}\n"
            f"   Score: {hit.score:.4f}\n"
            f"   Content: {hit.content}\n"
        )
    timing = response.timing_ms
    channels = ", ".join(name for name, _ in response.channel_queries) or "need"
    return "\n".join(formatted) + (
        f"\n\n[Retrieval channels: {channels}]"
        f"\n\n[Timing: rewrite={timing['rewrite']:.0f}ms, "
        f"sparse={timing['sparse']:.0f}ms, dense={timing['dense']:.0f}ms, "
        f"retrieval={timing['sparse'] + timing['dense']:.0f}ms, "
        f"reranking={timing['rerank']:.0f}ms, total={timing['total']:.0f}ms]"
    )
