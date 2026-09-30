from __future__ import annotations

import json

import numpy as np
import pytest

from tau2.domains.banking_knowledge.hybrid_retrieval import (
    LocalHybridPolicyRetriever,
)
from tau2.domains.banking_knowledge.qdrant_index import (
    QdrantDenseIndex,
    migrate_numpy_index,
)
from tau2.domains.banking_knowledge.vectorization import sha256_file


class _FakeEmbeddingClient:
    def embed(self, texts):
        assert texts
        return np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32), 3


def _write_source_index(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "doc_fee::chunk-0000-a",
            "document_id": "doc_fee",
            "title": "No Annual Fee Card",
            "text": "This personal card has no annual fee.",
            "metadata": {
                "section_paths": ["Fees"],
                "source": "fee.json",
                "text_sha256": "text-a",
                "document_sha256": "doc-a",
            },
        },
        {
            "id": "doc_travel::chunk-0000-b",
            "document_id": "doc_travel",
            "title": "Travel Card",
            "text": "This card earns travel points and charges an annual fee.",
            "metadata": {
                "section_paths": ["Rewards"],
                "source": "travel.json",
                "text_sha256": "text-b",
                "document_sha256": "doc-b",
            },
        },
    ]
    chunks_path.write_text(
        "".join(json.dumps(item) + "\n" for item in chunks), encoding="utf-8"
    )
    index_dir = tmp_path / "numpy_index"
    index_dir.mkdir()
    embeddings = np.asarray(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32
    )
    np.save(index_dir / "embeddings.npy", embeddings)
    (index_dir / "chunk_metadata.jsonl").write_text(
        "".join(
            json.dumps({"row": row, "chunk_id": item["id"]}) + "\n"
            for row, item in enumerate(chunks)
        ),
        encoding="utf-8",
    )
    manifest = {
        "model": "fake-model",
        "chunks_sha256": sha256_file(chunks_path),
        "row_count": 2,
        "dimensions": 3,
        "dtype": "float32",
    }
    (index_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return chunks_path, index_dir, manifest


def _open_index(qdrant_path, manifest):
    return QdrantDenseIndex(
        collection="policy_test",
        row_count=manifest["row_count"],
        dimensions=manifest["dimensions"],
        model=manifest["model"],
        chunks_sha256=manifest["chunks_sha256"],
        path=qdrant_path,
    )


def test_migrate_numpy_index_and_search_exact_top_k(tmp_path):
    chunks_path, index_dir, manifest = _write_source_index(tmp_path)
    qdrant_path = tmp_path / "qdrant"

    result = migrate_numpy_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        collection="policy_test",
        qdrant_path=qdrant_path,
    )
    assert result["row_count"] == 2
    assert result["sample_rows_verified"] == [0, 1]

    index = _open_index(qdrant_path, manifest)
    try:
        scores, rows = index.search(
            np.asarray([1.0, 0.0, 0.0], dtype=np.float32), limit=2
        )
        assert rows == [0, 1]
        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(0.0)
    finally:
        index.close()


def test_migration_requires_explicit_recreate(tmp_path):
    chunks_path, index_dir, _ = _write_source_index(tmp_path)
    qdrant_path = tmp_path / "qdrant"
    arguments = {
        "chunks_path": chunks_path,
        "index_dir": index_dir,
        "collection": "policy_test",
        "qdrant_path": qdrant_path,
    }
    migrate_numpy_index(**arguments)

    with pytest.raises(FileExistsError, match="--recreate"):
        migrate_numpy_index(**arguments)


def test_local_indexes_share_client_until_last_reference_closes(tmp_path):
    chunks_path, index_dir, manifest = _write_source_index(tmp_path)
    qdrant_path = tmp_path / "qdrant"
    migrate_numpy_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        collection="policy_test",
        qdrant_path=qdrant_path,
    )

    first = _open_index(qdrant_path, manifest)
    second = _open_index(qdrant_path, manifest)
    try:
        assert first.client is second.client
        first.close()

        scores, rows = second.search(
            np.asarray([0.0, 1.0, 0.0], dtype=np.float32), limit=1
        )
        assert rows == [1]
        assert scores[1] == pytest.approx(1.0)
    finally:
        first.close()
        second.close()


def test_hybrid_retriever_uses_qdrant_dense_backend(tmp_path):
    chunks_path, index_dir, manifest = _write_source_index(tmp_path)
    qdrant_path = tmp_path / "qdrant"
    migrate_numpy_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        collection="policy_test",
        qdrant_path=qdrant_path,
    )
    index = _open_index(qdrant_path, manifest)
    try:
        retriever = LocalHybridPolicyRetriever(
            chunks_path=chunks_path,
            index_dir=index_dir,
            model="fake-model",
            candidate_k=2,
            top_k=1,
            embedding_client=_FakeEmbeddingClient(),
            dense_index=index,
        )
        assert retriever.embeddings is None

        response = retriever.search("personal card without annual fee")

        assert response.hits[0].document_id == "doc_fee"
        assert response.hits[0].dense_score == pytest.approx(1.0)
    finally:
        index.close()
