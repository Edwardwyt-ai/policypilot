"""Qdrant persistence with server HNSW and exact local test search."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from tau2.domains.banking_knowledge.vectorization import (
    ChunkInput,
    load_chunks,
    sha256_file,
)

DEFAULT_COLLECTION = "banking_policy_chunks_v1"
HNSW_M = 16
HNSW_EF_CONSTRUCT = 100
HNSW_EF_SEARCH = 128
_CLIENTS_LOCK = threading.Lock()
_LOCAL_CLIENTS: dict[str, tuple[Any, int]] = {}


def _qdrant_imports():
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as exc:
        raise RuntimeError(
            "Qdrant retrieval requires qdrant-client. Install the knowledge "
            "extra or run `pip install qdrant-client`."
        ) from exc
    return QdrantClient, models


def hnsw_collection_options() -> dict:
    """Low KB thresholds enable indexing for the small policy corpus."""
    _, models = _qdrant_imports()
    return {
        "hnsw_config": models.HnswConfigDiff(
            m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT, full_scan_threshold=1
        ),
        "optimizers_config": models.OptimizersConfigDiff(indexing_threshold=1),
    }


def configure_hnsw(client, collection: str, *, wait_seconds: float = 120) -> dict:
    """Update in place; never remove points or recreate an existing collection."""
    if wait_seconds < 0:
        raise ValueError("wait_seconds must be non-negative")
    if not client.update_collection(
        collection_name=collection, **hnsw_collection_options()
    ):
        raise RuntimeError("Qdrant rejected HNSW configuration")
    deadline = time.monotonic() + wait_seconds
    while True:
        info = client.get_collection(collection)
        hnsw = info.config.hnsw_config
        points = client.count(collection_name=collection, exact=True).count
        indexed = info.indexed_vectors_count or 0
        configured = (
            hnsw.m == HNSW_M
            and hnsw.ef_construct == HNSW_EF_CONSTRUCT
            and hnsw.full_scan_threshold == 1
            and info.config.optimizer_config.indexing_threshold == 1
        )
        ready = configured and str(info.status) == "green" and indexed >= points
        report = {
            "collection": collection,
            "hnsw_configured": configured,
            "index_ready": ready,
            "points_count": points,
            "indexed_vectors_count": indexed,
            "m": hnsw.m,
            "ef_construct": hnsw.ef_construct,
            "hnsw_ef": HNSW_EF_SEARCH,
        }
        if ready or wait_seconds == 0:
            return report
        if time.monotonic() >= deadline:
            raise TimeoutError(f"HNSW build is not ready: {report}; points preserved")
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def create_qdrant_client(
    *,
    path: str | Path | None = None,
    url: str | None = None,
    api_key: str | None = None,
):
    """Create one local-persistent or server-backed Qdrant client."""
    QdrantClient, _ = _qdrant_imports()
    if url:
        return QdrantClient(url=url, api_key=api_key or None)
    if path is None:
        raise ValueError("A Qdrant path or URL is required")
    qdrant_path = Path(path)
    qdrant_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(qdrant_path))


def _acquire_local_client(path: str | Path):
    key = str(Path(path).resolve())
    with _CLIENTS_LOCK:
        cached = _LOCAL_CLIENTS.get(key)
        if cached is not None:
            client, references = cached
            _LOCAL_CLIENTS[key] = (client, references + 1)
            return client, key
        client = create_qdrant_client(path=key)
        _LOCAL_CLIENTS[key] = (client, 1)
        return client, key


def _release_local_client(key: str) -> None:
    with _CLIENTS_LOCK:
        cached = _LOCAL_CLIENTS.get(key)
        if cached is None:
            return
        client, references = cached
        if references > 1:
            _LOCAL_CLIENTS[key] = (client, references - 1)
            return
        _LOCAL_CLIENTS.pop(key, None)
        client.close()


@dataclass(frozen=True)
class QdrantIndexManifest:
    collection: str
    model: str
    chunks_sha256: str
    row_count: int
    dimensions: int
    distance: str = "Dot"

    def metadata(self) -> dict[str, str | int]:
        return {
            "schema_version": 1,
            "model": self.model,
            "chunks_sha256": self.chunks_sha256,
            "row_count": self.row_count,
            "dimensions": self.dimensions,
            "distance": self.distance,
        }


class QdrantDenseIndex:
    """Expose row-aligned server ANN search; local mode remains exact."""

    def __init__(
        self,
        *,
        collection: str,
        row_count: int,
        dimensions: int,
        model: str,
        chunks_sha256: str,
        path: str | Path | None = None,
        url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.collection = collection
        self.row_count = row_count
        self.dimensions = dimensions
        self.model = model
        self.chunks_sha256 = chunks_sha256
        self.local_mode = not bool(url)
        self._local_client_key: str | None = None
        self._closed = False
        if self.local_mode:
            if path is None:
                raise ValueError("A local Qdrant path is required")
            self.client, self._local_client_key = _acquire_local_client(path)
        else:
            self.client = create_qdrant_client(url=url, api_key=api_key)
        try:
            self._validate()
        except Exception:
            self.close()
            raise

    def _validate(self) -> None:
        self.validate_collection(
            self.client,
            QdrantIndexManifest(
                collection=self.collection,
                model=self.model,
                chunks_sha256=self.chunks_sha256,
                row_count=self.row_count,
                dimensions=self.dimensions,
            ),
        )

    @staticmethod
    def validate_collection(client, manifest: QdrantIndexManifest) -> None:
        _, models = _qdrant_imports()
        if not client.collection_exists(manifest.collection):
            raise FileNotFoundError(
                f"Qdrant collection {manifest.collection!r} does not exist. Run "
                "`python scripts/migrate_policy_vectors_to_qdrant.py`."
            )
        info = client.get_collection(manifest.collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, models.VectorParams):
            raise ValueError("Policy collection must use one unnamed dense vector")
        if vectors.size != manifest.dimensions:
            raise ValueError(
                f"Qdrant vector size {vectors.size} does not match {manifest.dimensions}"
            )
        if vectors.distance != models.Distance.DOT:
            raise ValueError("Policy collection must use Dot distance")
        metadata = info.config.metadata or {}
        expected = manifest.metadata()
        mismatches = {
            key: (metadata.get(key), value)
            for key, value in expected.items()
            if metadata.get(key) != value
        }
        if mismatches:
            raise ValueError(f"Qdrant index manifest mismatch: {mismatches}")
        count = client.count(collection_name=manifest.collection, exact=True).count
        if count != manifest.row_count:
            raise ValueError(
                f"Qdrant point count {count} does not match {manifest.row_count} chunks"
            )

    def search(
        self, query_vector: np.ndarray, limit: int, *, exact: bool = False
    ) -> tuple[np.ndarray, list[int]]:
        """Return a dense score array and ranked source rows."""
        _, models = _qdrant_imports()
        if query_vector.shape != (self.dimensions,):
            raise ValueError(
                f"Query vector shape {query_vector.shape} does not match "
                f"({self.dimensions},)"
            )
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            search_params=(
                None
                if self.local_mode
                else models.SearchParams(
                    exact=exact, hnsw_ef=max(HNSW_EF_SEARCH, limit)
                )
            ),
            limit=min(limit, self.row_count),
            with_payload=["row", "chunk_id"],
            with_vectors=False,
        )
        scores = np.full(self.row_count, -1.0, dtype=np.float32)
        rows: list[int] = []
        for point in response.points:
            payload = point.payload or {}
            row = payload.get("row")
            if not isinstance(row, int) or not 0 <= row < self.row_count:
                raise ValueError(f"Qdrant point {point.id!r} has invalid row payload")
            if row in rows:
                raise ValueError(f"Qdrant returned duplicate row {row}")
            scores[row] = float(point.score)
            rows.append(row)
        return scores, rows

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._local_client_key is not None:
            _release_local_client(self._local_client_key)
        else:
            self.client.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _point_payload(chunk: ChunkInput, metadata: dict[str, Any], row: int) -> dict:
    return {
        "row": row,
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "text": chunk.text,
        "section_paths": list(chunk.metadata.get("section_paths") or []),
        "source": chunk.metadata.get("source"),
        "text_sha256": chunk.metadata.get("text_sha256"),
        "document_sha256": chunk.metadata.get("document_sha256"),
        "embedding_model": metadata.get("model"),
        "chunks_sha256": metadata.get("chunks_sha256"),
    }


def migrate_numpy_index(
    *,
    chunks_path: Path,
    index_dir: Path,
    collection: str = DEFAULT_COLLECTION,
    qdrant_path: Path | None = None,
    qdrant_url: str | None = None,
    api_key: str | None = None,
    batch_size: int = 128,
    recreate: bool = False,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    """Import the verified row-aligned NumPy index into Qdrant."""
    _, models = _qdrant_imports()
    chunks = load_chunks(chunks_path)
    index_manifest = json.loads(
        (index_dir / "manifest.json").read_text(encoding="utf-8")
    )
    metadata = [
        json.loads(line)
        for line in (index_dir / "chunk_metadata.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    embeddings = np.load(index_dir / "embeddings.npy", mmap_mode="r")
    row_count = len(chunks)
    if embeddings.ndim != 2 or embeddings.shape[0] != row_count:
        raise ValueError("Embedding rows do not match chunk count")
    if len(metadata) != row_count:
        raise ValueError("Metadata rows do not match chunk count")
    chunks_sha256 = sha256_file(chunks_path)
    if index_manifest.get("chunks_sha256") != chunks_sha256:
        raise ValueError("Chunk hash does not match the NumPy index manifest")
    if [item.id for item in chunks] != [item.get("chunk_id") for item in metadata]:
        raise ValueError("Chunk and metadata row order do not match")

    dimensions = int(embeddings.shape[1])
    manifest = QdrantIndexManifest(
        collection=collection,
        model=str(index_manifest["model"]),
        chunks_sha256=chunks_sha256,
        row_count=row_count,
        dimensions=dimensions,
    )
    client = create_qdrant_client(path=qdrant_path, url=qdrant_url, api_key=api_key)
    created = False
    try:
        exists = client.collection_exists(collection)
        if exists and not recreate and not reuse_existing:
            raise FileExistsError(
                f"Qdrant collection {collection!r} already exists; use --recreate"
            )
        if exists and recreate:
            client.delete_collection(collection)
            exists = False
        if exists:
            # Validate identity/count before any in-place configuration changes.
            QdrantDenseIndex.validate_collection(client, manifest)
            if qdrant_url:
                configure_hnsw(client, collection, wait_seconds=0)
        else:
            client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=dimensions, distance=models.Distance.DOT
                ),
                metadata=manifest.metadata(),
                **(hnsw_collection_options() if qdrant_url else {}),
            )
            created = True
        points = (
            models.PointStruct(
                id=row,
                vector=np.asarray(embeddings[row], dtype=np.float32).tolist(),
                payload=_point_payload(chunks[row], index_manifest, row),
            )
            for row in range(row_count)
        )
        if created:
            client.upload_points(
                collection_name=collection,
                points=points,
                batch_size=batch_size,
                parallel=1,
                wait=True,
            )
        count = client.count(collection_name=collection, exact=True).count
        if count != row_count:
            raise ValueError(f"Uploaded {count} points, expected {row_count}")
        sample_ids = sorted({0, row_count // 2, row_count - 1})
        samples = client.retrieve(
            collection_name=collection,
            ids=sample_ids,
            with_payload=True,
            with_vectors=True,
        )
        by_id = {int(item.id): item for item in samples}
        for row in sample_ids:
            record = by_id.get(row)
            if record is None or record.payload.get("chunk_id") != chunks[row].id:
                raise ValueError(f"Qdrant sample row {row} is misaligned")
            if not np.allclose(
                np.asarray(record.vector, dtype=np.float32), embeddings[row], atol=1e-6
            ):
                raise ValueError(f"Qdrant sample vector {row} differs from source")
    except Exception:
        if created and client.collection_exists(collection):
            client.delete_collection(collection)
        raise
    finally:
        client.close()

    return {
        **manifest.metadata(),
        "collection": collection,
        "backend": "url" if qdrant_url else "local_path",
        "location": qdrant_url or str(qdrant_path),
        "migrated_at": datetime.now(UTC).isoformat(),
        "sample_rows_verified": sample_ids,
        "index_mode": "hnsw" if qdrant_url else "local_exact",
        "reused_existing": exists,
    }


__all__ = [
    "DEFAULT_COLLECTION",
    "QdrantDenseIndex",
    "QdrantIndexManifest",
    "create_qdrant_client",
    "configure_hnsw",
    "migrate_numpy_index",
]
