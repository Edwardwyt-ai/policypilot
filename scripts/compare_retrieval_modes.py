#!/usr/bin/env python
"""Compare sparse, dense, and hybrid retrieval on identical offline cases."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau2.domains.banking_knowledge.data_model import KnowledgeBase  # noqa: E402
from tau2.domains.banking_knowledge.hybrid_retrieval import (  # noqa: E402
    LocalHybridPolicyRetriever,
)
from tau2.domains.banking_knowledge.retrieval_metrics import (  # noqa: E402
    evaluate_rankings,
)

DOMAIN_ROOT = ROOT / "data" / "tau2" / "domains" / "banking_knowledge"
VECTOR_ROOT = DOMAIN_ROOT / "vector_index"


def _sample(items: list, count: int, seed: int) -> list:
    if count <= 0 or count >= len(items):
        return items
    return random.Random(seed).sample(items, count)


def _load_cases(document_sample: int, task_sample: int, seed: int):
    kb = KnowledgeBase.load(str(DOMAIN_ROOT / "documents"))
    tasks = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((DOMAIN_ROOT / "tasks").glob("task_*.json"))
    ]
    referenced_ids = sorted(
        {
            reference
            for task in tasks
            for reference in task.get("required_documents") or []
            if reference in kb.documents
        }
    )
    sampled_documents = _sample(referenced_ids, document_sample, seed)
    sampled_tasks = _sample(
        [task for task in tasks if task.get("required_documents")], task_sample, seed
    )
    cases = []
    for doc_id in sampled_documents:
        document = kb.documents[doc_id]
        cases.append(("document_title", document.title, {doc_id}, doc_id))
        cases.append(
            (
                "content_snippet",
                " ".join(document.content.split()[:20]),
                {doc_id},
                doc_id,
            )
        )
    for task in sampled_tasks:
        gold = set(task.get("required_documents") or []).intersection(kb.documents)
        if gold:
            cases.append(
                (
                    "task_scenario",
                    task["user_scenario"]["instructions"],
                    gold,
                    task["id"],
                )
            )
    return cases, len(referenced_ids), len(tasks)


def _document_ids(retriever, rows, limit=5):
    document_ids = []
    seen = set()
    for row in rows:
        document_id = retriever.chunks[row].document_id
        if document_id in seen:
            continue
        seen.add(document_id)
        document_ids.append(document_id)
        if len(document_ids) == limit:
            break
    return document_ids


def _search_all_modes(retriever, query: str):
    total_start = time.perf_counter()
    rewritten = retriever.rewriter.rewrite(query)
    rewrite_ms = (time.perf_counter() - total_start) * 1000

    sparse_start = time.perf_counter()
    sparse_scores = np.asarray(
        retriever.bm25.get_scores(list(rewritten.lexical_tokens)), dtype=np.float32
    )
    sparse_rows = retriever._top_rows(sparse_scores, retriever.candidate_k)
    sparse_ids = _document_ids(retriever, sparse_rows)
    sparse_ms = rewrite_ms + (time.perf_counter() - sparse_start) * 1000

    dense_start = time.perf_counter()
    query_vectors, _ = retriever.embedding_client.embed([rewritten.dense_query])
    query_vector = query_vectors[0]
    norm = np.linalg.norm(query_vector)
    if norm == 0:
        raise ValueError("Query embedding has zero norm")
    dense_scores = retriever.embeddings @ (query_vector / norm)
    dense_rows = retriever._top_rows(dense_scores, retriever.candidate_k)
    dense_ids = _document_ids(retriever, dense_rows)
    dense_ms = rewrite_ms + (time.perf_counter() - dense_start) * 1000

    hybrid_start = time.perf_counter()
    ranked = retriever._rerank(
        rewritten, dense_scores, sparse_scores, dense_rows, sparse_rows
    )
    hybrid_ids = [
        hit.document_id for hit in retriever._aggregate_documents(ranked, top_k=5)
    ]
    hybrid_rerank_ms = (time.perf_counter() - hybrid_start) * 1000
    hybrid_ms = sparse_ms + dense_ms - rewrite_ms + hybrid_rerank_ms
    return {
        "keyword_bm25": (sparse_ids, sparse_ms),
        "dense_qwen": (dense_ids, dense_ms),
        "hybrid": (hybrid_ids, hybrid_ms),
    }


def _latency(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))
    return {
        "mean_ms": statistics.mean(values),
        "p50_ms": statistics.median(values),
        "p95_ms": ordered[p95_index],
        "max_ms": max(values),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-sample", type=int, default=10)
    parser.add_argument("--task-sample", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--candidate-k", type=int, default=30)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases, available_documents, available_tasks = _load_cases(
        args.document_sample, args.task_sample, args.seed
    )
    retriever = LocalHybridPolicyRetriever(
        chunks_path=VECTOR_ROOT / "chunks.jsonl",
        index_dir=VECTOR_ROOT / "qwen3-embedding-0.6b",
        candidate_k=args.candidate_k,
        top_k=5,
    )
    rows: dict[str, dict[str, list[dict]]] = {
        mode: {} for mode in ("keyword_bm25", "dense_qwen", "hybrid")
    }
    for index, (case_type, query, gold, case_id) in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case_type}: {case_id}", flush=True)
        results = _search_all_modes(retriever, query)
        for mode, (ranking, latency_ms) in results.items():
            rows[mode].setdefault(case_type, []).append(
                {
                    "id": case_id,
                    "gold": sorted(gold),
                    "ranking": ranking,
                    "latency_ms": latency_ms,
                }
            )

    report = {}
    for mode, groups in rows.items():
        report[mode] = {}
        for case_type, case_rows in groups.items():
            metrics = evaluate_rankings(
                [row["ranking"] for row in case_rows],
                [set(row["gold"]) for row in case_rows],
            )
            metrics["latency"] = _latency(
                [row["latency_ms"] for row in case_rows]
            )
            report[mode][case_type] = {"metrics": metrics, "cases": case_rows}

    payload = {
        "created_at": datetime.now().astimezone().isoformat(),
        "method": {
            "seed": args.seed,
            "top_k": 5,
            "candidate_k": args.candidate_k,
            "document_sample": args.document_sample,
            "task_sample": args.task_sample,
            "available_referenced_documents": available_documents,
            "available_tasks": available_tasks,
            "labels": "required_documents, used only by this offline evaluator",
            "reranker": "disabled for all modes",
        },
        "results": report,
    }
    output = args.output or (
        ROOT
        / "data"
        / "analyses"
        / f"retrieval_modes_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    compact = {
        mode: {case_type: data["metrics"] for case_type, data in groups.items()}
        for mode, groups in report.items()
    }
    print(json.dumps({"report": str(output), "metrics": compact}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
