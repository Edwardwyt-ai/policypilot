from __future__ import annotations

import json

import numpy as np

from tau2.domains.banking_knowledge.vectorization import (
    ChunkInput,
    OllamaEmbeddingClient,
    build_embedding_text,
    build_vector_index,
)


def test_build_embedding_text_includes_title_section_and_body():
    chunk = ChunkInput(
        id="chunk-1",
        document_id="doc-1",
        title="Account policy",
        text="No annual fee.",
        metadata={"section_paths": ["Fees", "Eligibility > Fees"]},
    )

    text = build_embedding_text(chunk)

    assert text == (
        "Title: Account policy\n"
        "Sections: Fees | Eligibility > Fees\n"
        "No annual fee."
    )


class _FakeClient(OllamaEmbeddingClient):
    def __init__(self):
        super().__init__(endpoint="http://local.test", model="fake-embedding")

    def embed(self, texts):
        rows = []
        for text in texts:
            value = float(len(text))
            rows.append([value, value + 1, value + 2])
        return np.asarray(rows, dtype=np.float32), len(texts) * 10


def test_build_vector_index_keeps_rows_aligned(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    rows = [
        {
            "id": f"chunk-{index}",
            "document_id": f"doc-{index}",
            "title": f"Title {index}",
            "text": f"Policy text {index}",
            "metadata": {"section_paths": [f"Section {index}"]},
        }
        for index in range(3)
    ]
    chunks_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    manifest = build_vector_index(
        chunks_path=chunks_path,
        output_dir=tmp_path / "index",
        client=_FakeClient(),
        batch_size=2,
    )

    vectors = np.load(tmp_path / "index" / "embeddings.npy")
    metadata = [
        json.loads(line)
        for line in (tmp_path / "index" / "chunk_metadata.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert vectors.shape == (3, 3)
    assert [row["chunk_id"] for row in metadata] == [
        "chunk-0",
        "chunk-1",
        "chunk-2",
    ]
    assert [row["row"] for row in metadata] == [0, 1, 2]
    assert manifest["prompt_eval_count"] == 30
