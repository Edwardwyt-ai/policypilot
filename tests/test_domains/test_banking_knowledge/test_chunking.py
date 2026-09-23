from __future__ import annotations

import json

from tau2.domains.banking_knowledge.chunking import (
    ChunkingConfig,
    chunk_document,
    load_and_chunk_documents,
    write_chunks_jsonl,
)
from tau2.domains.banking_knowledge.data_model import Document


def test_short_document_remains_one_chunk():
    document = Document(
        id="doc_short",
        title="Short policy",
        content="## Eligibility\n\nCustomers must be verified.",
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].document_id == document.id
    assert chunks[0].text == document.content
    assert chunks[0].metadata["section_paths"] == ["Eligibility"]


def test_long_document_respects_hard_limit_and_has_stable_ids():
    content = "## Rules\n\n" + " ".join(
        f"Requirement {index} must be checked." for index in range(180)
    )
    document = Document(id="doc_long", title="Long policy", content=content)
    config = ChunkingConfig(
        target_chars=420,
        max_chars=520,
        min_chars=120,
        overlap_chars=60,
    )

    first = chunk_document(document, config)
    second = chunk_document(document, config)

    assert len(first) > 1
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert all(len(chunk.text) <= config.max_chars for chunk in first)
    assert [chunk.metadata["chunk_index"] for chunk in first] == list(
        range(len(first))
    )
    assert all(chunk.metadata["chunk_count"] == len(first) for chunk in first)


def test_heading_paths_are_carried_into_chunk_metadata():
    document = Document(
        id="doc_sections",
        title="Policy sections",
        content=(
            "## Eligibility\n\nAdults only.\n\n"
            "### Verification\n\nPhoto ID required.\n\n"
            "## Fees\n\nNo annual fee."
        ),
    )

    chunks = chunk_document(
        document,
        ChunkingConfig(target_chars=60, max_chars=100, min_chars=20, overlap_chars=0),
    )

    paths = {
        path for chunk in chunks for path in chunk.metadata["section_paths"]
    }
    assert "Eligibility" in paths
    assert "Eligibility > Verification" in paths
    assert "Fees" in paths


def test_chunk_does_not_end_with_an_orphan_heading():
    document = Document(
        id="doc_headings",
        title="Heading boundaries",
        content=(
            "## First\n\n"
            + "First section sentence. " * 8
            + "\n\n## Second\n\n"
            + "Second section sentence. " * 8
        ),
    )

    chunks = chunk_document(
        document,
        ChunkingConfig(target_chars=180, max_chars=240, min_chars=50, overlap_chars=0),
    )

    assert len(chunks) > 1
    assert all(not chunk.text.splitlines()[-1].startswith("#") for chunk in chunks)


def test_directory_export_is_deterministic_jsonl(tmp_path):
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    for name, doc_id in (("b.json", "doc_b"), ("a.json", "doc_a")):
        (documents_dir / name).write_text(
            json.dumps(
                {"id": doc_id, "title": doc_id, "content": "## Policy\n\nText."}
            ),
            encoding="utf-8",
        )

    chunks = load_and_chunk_documents(documents_dir)
    output = tmp_path / "index" / "chunks.jsonl"
    count = write_chunks_jsonl(chunks, output)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert count == 2
    assert [row["document_id"] for row in rows] == ["doc_a", "doc_b"]
    assert all(row["metadata"]["source"].endswith(".json") for row in rows)
