"""Offline vector-index construction for chunked banking policy documents."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx
import numpy as np
from numpy.lib.format import open_memmap


@dataclass(frozen=True)
class ChunkInput:
    """The minimal chunk information required for document embedding."""

    id: str
    document_id: str
    title: str
    text: str
    metadata: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_chunks(path: Path) -> list[ChunkInput]:
    chunks: list[ChunkInput] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        chunk = ChunkInput(
            id=payload["id"],
            document_id=payload["document_id"],
            title=payload["title"],
            text=payload["text"],
            metadata=payload.get("metadata", {}),
        )
        if chunk.id in seen_ids:
            raise ValueError(f"Duplicate chunk id at line {line_number}: {chunk.id}")
        if not chunk.text.strip():
            raise ValueError(f"Empty chunk text at line {line_number}: {chunk.id}")
        seen_ids.add(chunk.id)
        chunks.append(chunk)
    if not chunks:
        raise ValueError(f"No chunks found in {path}")
    return chunks


def build_embedding_text(chunk: ChunkInput) -> str:
    """Add concise document context without duplicating the full metadata."""
    sections = chunk.metadata.get("section_paths") or []
    parts = [f"Title: {chunk.title}"]
    if sections:
        parts.append(f"Sections: {' | '.join(str(value) for value in sections)}")
    parts.append(chunk.text)
    return "\n".join(parts)


class OllamaEmbeddingClient:
    """Small synchronous client for Ollama's native embedding endpoint."""

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:11434",
        model: str = "qwen3-embedding:0.6b",
        timeout_seconds: float = 300.0,
        retries: int = 3,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    def embed(self, texts: Sequence[str]) -> tuple[np.ndarray, int]:
        if not texts:
            raise ValueError("Embedding batch must not be empty")
        payload = {
            "model": self.model,
            "input": list(texts),
            "truncate": True,
            "keep_alive": "10m",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(f"{self.endpoint}/api/embed", json=payload)
                    response.raise_for_status()
                body = response.json()
                embeddings = np.asarray(body.get("embeddings"), dtype=np.float32)
                if embeddings.ndim != 2 or embeddings.shape[0] != len(texts):
                    raise ValueError(
                        "Ollama returned an invalid embedding shape: "
                        f"{embeddings.shape}; expected {len(texts)} rows"
                    )
                if not np.isfinite(embeddings).all():
                    raise ValueError("Ollama returned NaN or infinite embedding values")
                return embeddings, int(body.get("prompt_eval_count") or 0)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(
            f"Embedding request failed after {self.retries} attempts"
        ) from last_error


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_metadata(chunks: Sequence[ChunkInput], path: Path) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row, chunk in enumerate(chunks):
            payload = {
                "row": row,
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "title": chunk.title,
                "section_paths": chunk.metadata.get("section_paths") or [],
                "source": chunk.metadata.get("source"),
                "text_sha256": chunk.metadata.get("text_sha256"),
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    temporary.replace(path)


def build_vector_index(
    *,
    chunks_path: Path,
    output_dir: Path,
    client: OllamaEmbeddingClient,
    batch_size: int = 16,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Embed all chunks into a resumable, row-aligned NumPy index."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    chunks = load_chunks(chunks_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_sha256 = sha256_file(chunks_path)
    progress_path = output_dir / "progress.json"
    partial_path = output_dir / "embeddings.partial.npy"
    final_path = output_dir / "embeddings.npy"
    metadata_path = output_dir / "chunk_metadata.jsonl"
    manifest_path = output_dir / "manifest.json"

    completed_rows = 0
    dimensions: int | None = None
    total_prompt_tokens = 0
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        expected = {
            "model": client.model,
            "chunks_sha256": chunks_sha256,
            "row_count": len(chunks),
        }
        for key, value in expected.items():
            if progress.get(key) != value:
                raise ValueError(
                    f"Existing embedding progress has incompatible {key}: "
                    f"{progress.get(key)!r} != {value!r}"
                )
        completed_rows = int(progress["completed_rows"])
        dimensions = int(progress["dimensions"])
        total_prompt_tokens = int(progress.get("prompt_eval_count") or 0)
        if not partial_path.exists():
            raise ValueError("Embedding progress exists but partial array is missing")

    started = time.perf_counter()
    matrix: np.memmap | None = None
    try:
        if dimensions is not None:
            matrix = open_memmap(partial_path, mode="r+")
            if matrix.shape != (len(chunks), dimensions):
                raise ValueError(
                    f"Partial embedding shape is {matrix.shape}, expected "
                    f"{(len(chunks), dimensions)}"
                )

        for start in range(completed_rows, len(chunks), batch_size):
            end = min(start + batch_size, len(chunks))
            texts = [build_embedding_text(chunk) for chunk in chunks[start:end]]
            batch, prompt_tokens = client.embed(texts)
            if matrix is None:
                dimensions = int(batch.shape[1])
                matrix = open_memmap(
                    partial_path,
                    mode="w+",
                    dtype=np.float32,
                    shape=(len(chunks), dimensions),
                )
            if batch.shape[1] != dimensions:
                raise ValueError(
                    f"Embedding dimension changed from {dimensions} to {batch.shape[1]}"
                )
            matrix[start:end] = batch
            matrix.flush()
            completed_rows = end
            total_prompt_tokens += prompt_tokens
            _write_json_atomic(
                progress_path,
                {
                    "model": client.model,
                    "chunks_sha256": chunks_sha256,
                    "row_count": len(chunks),
                    "dimensions": dimensions,
                    "completed_rows": completed_rows,
                    "prompt_eval_count": total_prompt_tokens,
                },
            )
            if progress_callback is not None:
                progress_callback(completed_rows, len(chunks))
    finally:
        if matrix is not None:
            matrix.flush()
            del matrix

    partial_path.replace(final_path)
    progress_path.unlink(missing_ok=True)
    _write_metadata(chunks, metadata_path)

    embeddings = np.load(final_path, mmap_mode="r")
    norms = np.linalg.norm(embeddings, axis=1)
    elapsed_seconds = time.perf_counter() - started
    manifest = {
        "schema_version": 1,
        "model": client.model,
        "endpoint": client.endpoint,
        "chunks_file": str(chunks_path.name),
        "chunks_sha256": chunks_sha256,
        "row_count": int(embeddings.shape[0]),
        "dimensions": int(embeddings.shape[1]),
        "dtype": str(embeddings.dtype),
        "batch_size": batch_size,
        "prompt_eval_count": total_prompt_tokens,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "embedding_norms": {
            "min": float(norms.min()),
            "mean": float(norms.mean()),
            "max": float(norms.max()),
        },
        "files": {
            "embeddings": final_path.name,
            "embeddings_sha256": sha256_file(final_path),
            "metadata": metadata_path.name,
            "metadata_sha256": sha256_file(metadata_path),
        },
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest
