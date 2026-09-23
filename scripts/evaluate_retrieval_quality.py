#!/usr/bin/env python
"""Compare feature-only hybrid retrieval with local Qwen reranking."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau2.domains.banking_knowledge.data_model import KnowledgeBase  # noqa: E402
from tau2.domains.banking_knowledge.hybrid_retrieval import (  # noqa: E402
    LocalHybridPolicyRetriever,
)
from tau2.domains.banking_knowledge.local_reranker import (  # noqa: E402
    QwenLocalReranker,
)
from tau2.domains.banking_knowledge.retrieval_metrics import (  # noqa: E402
    evaluate_rankings,
)
from tau2.domains.banking_knowledge.vectorization import (  # noqa: E402
    OllamaEmbeddingClient,
)

DOMAIN_ROOT = ROOT / "data" / "tau2" / "domains" / "banking_knowledge"
VECTOR_ROOT = DOMAIN_ROOT / "vector_index"


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def _latency_metrics(values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": statistics.mean(values),
        "p50_ms": statistics.median(values),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": max(values),
    }


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
    documents = _sample(referenced_ids, document_sample, seed)
    task_rows = _sample(
        [task for task in tasks if task.get("required_documents")],
        task_sample,
        seed,
    )

    cases = []
    for doc_id in documents:
        doc = kb.documents[doc_id]
        cases.append(("document_title", doc.title, {doc_id}, doc_id))
        snippet = " ".join(doc.content.split()[:20])
        cases.append(("content_snippet", snippet, {doc_id}, doc_id))
    for task in task_rows:
        gold = {
            reference
            for reference in task["required_documents"]
            if reference in kb.documents
        }
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


def _evaluate(retriever, cases):
    groups: dict[str, list[dict]] = {}
    for mode, query, gold, case_id in cases:
        response = retriever.search(query, top_k=5)
        groups.setdefault(mode, []).append(
            {
                "id": case_id,
                "gold": sorted(gold),
                "ranking": [hit.document_id for hit in response.hits],
                "latency_ms": response.timing_ms,
            }
        )

    report = {}
    for mode, rows in groups.items():
        metrics = evaluate_rankings(
            [row["ranking"] for row in rows],
            [set(row["gold"]) for row in rows],
        )
        metrics["latency"] = _latency_metrics(
            [row["latency_ms"]["total"] for row in rows]
        )
        metrics["model_rerank_latency"] = _latency_metrics(
            [row["latency_ms"]["model_rerank"] for row in rows]
        )
        report[mode] = {"metrics": metrics, "cases": rows}
    return report


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-sample", type=int, default=30)
    parser.add_argument("--task-sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--candidate-k", type=int, default=30)
    parser.add_argument("--rerank-k", type=int, default=20)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--embedding-model", default="qwen3-embedding:0.6b")
    parser.add_argument(
        "--reranker-model",
        type=Path,
        default=Path.home()
        / "Desktop"
        / "qwen-api"
        / "models"
        / "qwen3-reranker-0.6b",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases, available_documents, available_tasks = _load_cases(
        args.document_sample, args.task_sample, args.seed
    )
    common = {
        "chunks_path": VECTOR_ROOT / "chunks.jsonl",
        "index_dir": VECTOR_ROOT / "qwen3-embedding-0.6b",
        "model": args.embedding_model,
        "candidate_k": args.candidate_k,
        "top_k": 5,
        "rerank_candidate_k": args.rerank_k,
    }
    baseline = LocalHybridPolicyRetriever(
        **common,
        embedding_client=OllamaEmbeddingClient(
            endpoint=args.endpoint, model=args.embedding_model
        ),
    )
    qwen = LocalHybridPolicyRetriever(
        **common,
        embedding_client=OllamaEmbeddingClient(
            endpoint=args.endpoint, model=args.embedding_model
        ),
        reranker=QwenLocalReranker(args.reranker_model),
    )
    print(f"Evaluating {len(cases)} cases without model reranking...", flush=True)
    baseline_report = _evaluate(baseline, cases)
    print(f"Evaluating {len(cases)} cases with Qwen reranking...", flush=True)
    qwen_report = _evaluate(qwen, cases)

    payload = {
        "created_at": datetime.now().astimezone().isoformat(),
        "method": {
            "seed": args.seed,
            "top_k": 5,
            "candidate_k": args.candidate_k,
            "rerank_k": args.rerank_k,
            "document_sample": args.document_sample,
            "task_sample": args.task_sample,
            "available_referenced_documents": available_documents,
            "available_tasks": available_tasks,
            "labels": "required_documents, used only by this offline evaluator",
        },
        "feature_hybrid": baseline_report,
        "qwen_rerank": qwen_report,
    }
    output = args.output or (
        ROOT
        / "data"
        / "analyses"
        / f"retrieval_quality_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    compact = {
        variant: {
            mode: values["metrics"]
            for mode, values in payload[variant].items()
        }
        for variant in ("feature_hybrid", "qwen_rerank")
    }
    print(json.dumps({"report": str(output), "metrics": compact}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
