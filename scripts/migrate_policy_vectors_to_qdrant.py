#!/usr/bin/env python
"""Migrate the verified local banking policy vectors into Qdrant."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env.storage")

from tau2.domains.banking_knowledge.qdrant_index import (  # noqa: E402
    DEFAULT_COLLECTION,
    configure_hnsw,
    create_qdrant_client,
    migrate_numpy_index,
)

VECTOR_ROOT = ROOT / "data" / "tau2" / "domains" / "banking_knowledge" / "vector_index"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=VECTOR_ROOT / "chunks.jsonl")
    parser.add_argument(
        "--index-dir", type=Path, default=VECTOR_ROOT / "qwen3-embedding-0.6b"
    )
    parser.add_argument(
        "--qdrant-path",
        type=Path,
        default=Path(os.getenv("POLICYPILOT_QDRANT_PATH", VECTOR_ROOT / "qdrant")),
    )
    parser.add_argument("--qdrant-url", default=os.getenv("POLICYPILOT_QDRANT_URL"))
    parser.add_argument(
        "--collection",
        default=os.getenv("POLICYPILOT_QDRANT_COLLECTION", DEFAULT_COLLECTION),
    )
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Validate and upgrade an existing collection without replacing points",
    )
    parser.add_argument("--wait-seconds", type=float, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.wait_seconds < 0:
        raise ValueError("--wait-seconds must be non-negative")
    if args.recreate and args.reuse_existing:
        raise ValueError("--recreate and --reuse-existing are mutually exclusive")
    qdrant_path = args.qdrant_path
    if not qdrant_path.is_absolute():
        qdrant_path = ROOT / qdrant_path
    manifest = migrate_numpy_index(
        chunks_path=args.chunks,
        index_dir=args.index_dir,
        collection=args.collection,
        qdrant_path=None if args.qdrant_url else qdrant_path,
        qdrant_url=args.qdrant_url,
        api_key=os.getenv("POLICYPILOT_QDRANT_API_KEY"),
        batch_size=args.batch_size,
        recreate=args.recreate,
        reuse_existing=args.reuse_existing,
    )
    if args.qdrant_url:
        client = create_qdrant_client(
            url=args.qdrant_url, api_key=os.getenv("POLICYPILOT_QDRANT_API_KEY")
        )
        try:
            manifest["hnsw"] = configure_hnsw(
                client, args.collection, wait_seconds=args.wait_seconds
            )
        finally:
            client.close()
    output = VECTOR_ROOT / "qdrant_migration_manifest.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
