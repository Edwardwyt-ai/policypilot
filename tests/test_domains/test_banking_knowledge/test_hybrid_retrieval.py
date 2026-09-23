from __future__ import annotations

import json

import numpy as np

from policypilot.evidence import parse_policy_references
from tau2.domains.banking_knowledge.hybrid_retrieval import (
    ConstraintPreservingQueryRewriter,
    LocalHybridPolicyRetriever,
    format_hybrid_search_response,
)
from tau2.domains.banking_knowledge.vectorization import sha256_file


class _FakeEmbeddingClient:
    def embed(self, texts):
        assert len(texts) == 1
        assert texts[0].startswith("Instruct:")
        return np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32), 10


class _FakeReranker:
    def score(self, query, documents):
        assert query == "general card"
        return np.asarray(
            [0.99 if "cash back" in document.lower() else 0.01 for document in documents],
            dtype=np.float32,
        )


def _write_index(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "doc_dense::chunk-0000-a",
            "document_id": "doc_dense",
            "title": "General card overview",
            "text": "A general personal card overview and application process.",
            "metadata": {"section_paths": ["Overview"], "source": "dense.json"},
        },
        {
            "id": "doc_fee::chunk-0000-b",
            "document_id": "doc_fee",
            "title": "Cash Back Card Fees",
            "text": "This personal cash back card has no annual fee.",
            "metadata": {"section_paths": ["Fees"], "source": "fee.json"},
        },
        {
            "id": "doc_savings::chunk-0000-c",
            "document_id": "doc_savings",
            "title": "Savings Account",
            "text": "The savings account earns interest.",
            "metadata": {"section_paths": ["Rates"], "source": "savings.json"},
        },
    ]
    chunks_path.write_text(
        "".join(json.dumps(row) + "\n" for row in chunks), encoding="utf-8"
    )

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    vectors = np.asarray(
        [[1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    np.save(index_dir / "embeddings.npy", vectors)
    metadata = [
        {"row": index, "chunk_id": row["id"]}
        for index, row in enumerate(chunks)
    ]
    (index_dir / "chunk_metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in metadata), encoding="utf-8"
    )
    (index_dir / "manifest.json").write_text(
        json.dumps(
            {
                "model": "fake-model",
                "chunks_sha256": sha256_file(chunks_path),
            }
        ),
        encoding="utf-8",
    )
    return chunks_path, index_dir


def test_query_rewrite_preserves_negation_numbers_and_original_terms():
    rewritten = ConstraintPreservingQueryRewriter().rewrite(
        "personal card with no annual fee and at least 2% cash back"
    )

    assert rewritten.normalized == (
        "personal card with no annual fee and at least 2% cash back"
    )
    assert {"personal", "card", "annual", "fee", "2", "cash", "back"}.issubset(
        rewritten.anchors
    )
    assert "no annual fee" in rewritten.exact_phrases
    assert any(
        phrase.startswith("at least 2") for phrase in rewritten.exact_phrases
    )
    assert rewritten.dense_query.endswith(f"Query:{rewritten.normalized}")


def test_hybrid_retrieval_reranks_constraint_covering_document(tmp_path):
    chunks_path, index_dir = _write_index(tmp_path)
    retriever = LocalHybridPolicyRetriever(
        chunks_path=chunks_path,
        index_dir=index_dir,
        model="fake-model",
        candidate_k=3,
        top_k=2,
        embedding_client=_FakeEmbeddingClient(),
    )

    response = retriever.search("personal cash back card with no annual fee")

    assert response.hits[0].document_id == "doc_fee"
    assert response.hits[0].anchor_coverage == 1.0
    assert response.hits[0].chunk_ids == ("doc_fee::chunk-0000-b",)
    assert set(response.timing_ms) == {
        "rewrite",
        "sparse",
        "dense",
        "feature_rerank",
        "model_rerank",
        "rerank",
        "total",
    }


def test_model_reranker_can_override_feature_order(tmp_path):
    chunks_path, index_dir = _write_index(tmp_path)
    retriever = LocalHybridPolicyRetriever(
        chunks_path=chunks_path,
        index_dir=index_dir,
        model="fake-model",
        candidate_k=3,
        top_k=2,
        embedding_client=_FakeEmbeddingClient(),
        reranker=_FakeReranker(),
    )

    response = retriever.search("general card")

    assert response.hits[0].document_id == "doc_fee"
    assert response.timing_ms["model_rerank"] >= 0


def test_hybrid_output_keeps_existing_evidence_parser_contract(tmp_path):
    chunks_path, index_dir = _write_index(tmp_path)
    retriever = LocalHybridPolicyRetriever(
        chunks_path=chunks_path,
        index_dir=index_dir,
        model="fake-model",
        candidate_k=3,
        top_k=2,
        embedding_client=_FakeEmbeddingClient(),
    )

    output = format_hybrid_search_response(
        retriever.search("personal cash back card with no annual fee")
    )
    references = parse_policy_references(output)

    assert references[0].document_id == "doc_fee"
    assert references[0].title == "Cash Back Card Fees"
    assert "[Timing: rewrite=" in output


def test_scope_conflict_penalizes_opposite_product_type():
    assert LocalHybridPolicyRetriever._scope_conflict(
        {"personal", "card"}, {"business", "rewards", "card"}
    )
    assert not LocalHybridPolicyRetriever._scope_conflict(
        {"personal", "business", "card"}, {"business", "rewards", "card"}
    )
    assert not LocalHybridPolicyRetriever._scope_conflict(
        {"personal", "card"}, {"personal", "rewards", "card"}
    )
