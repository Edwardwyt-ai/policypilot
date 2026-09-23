#!/usr/bin/env python
"""Run the local policy query-rewrite, hybrid-retrieval, and rerank chain."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau2.domains.banking_knowledge.hybrid_retrieval import (  # noqa: E402
    LocalHybridPolicyRetriever,
    format_hybrid_search_response,
)
from tau2.domains.banking_knowledge.local_reranker import (  # noqa: E402
    QwenLocalReranker,
)

VECTOR_ROOT = (
    ROOT / "data" / "tau2" / "domains" / "banking_knowledge" / "vector_index"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=30)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument(
        "--reranker-model",
        type=Path,
        default=Path.home()
        / "Desktop"
        / "qwen-api"
        / "models"
        / "qwen3-reranker-0.6b",
    )
    parser.add_argument("--no-reranker", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    retriever = LocalHybridPolicyRetriever(
        chunks_path=VECTOR_ROOT / "chunks.jsonl",
        index_dir=VECTOR_ROOT / "qwen3-embedding-0.6b",
        endpoint=args.endpoint,
        model=args.model,
        candidate_k=args.candidate_k,
        top_k=args.top_k,
        reranker=(
            None
            if args.no_reranker
            else QwenLocalReranker(args.reranker_model)
        ),
    )
    print(format_hybrid_search_response(retriever.search(args.query)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
