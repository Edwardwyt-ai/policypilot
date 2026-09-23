#!/usr/bin/env python
"""Embed chunked banking policies with a local Ollama model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau2.domains.banking_knowledge.vectorization import (  # noqa: E402
    OllamaEmbeddingClient,
    build_vector_index,
)

VECTOR_ROOT = (
    ROOT / "data" / "tau2" / "domains" / "banking_knowledge" / "vector_index"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=VECTOR_ROOT / "chunks.jsonl")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=VECTOR_ROOT / "qwen3-embedding-0.6b",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = OllamaEmbeddingClient(
        endpoint=args.endpoint,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
    )

    def show_progress(completed: int, total: int) -> None:
        print(f"Embedded {completed}/{total} chunks", flush=True)

    manifest = build_vector_index(
        chunks_path=args.chunks,
        output_dir=args.output_dir,
        client=client,
        batch_size=args.batch_size,
        progress_callback=show_progress,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
