#!/usr/bin/env python
"""Create deterministic JSONL chunks from the banking policy documents."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau2.domains.banking_knowledge.chunking import (  # noqa: E402
    ChunkingConfig,
    load_and_chunk_documents,
    write_chunks_jsonl,
)

DEFAULT_DOCUMENTS_DIR = (
    ROOT / "data" / "tau2" / "domains" / "banking_knowledge" / "documents"
)
DEFAULT_OUTPUT_DIR = (
    ROOT / "data" / "tau2" / "domains" / "banking_knowledge" / "vector_index"
)


def display_path(path: Path) -> str:
    """Prefer a portable repository-relative path in generated metadata."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents-dir", type=Path, default=DEFAULT_DOCUMENTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-chars", type=int, default=1200)
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--overlap-chars", type=int, default=160)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ChunkingConfig(
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        overlap_chars=args.overlap_chars,
    )
    chunks = load_and_chunk_documents(args.documents_dir, config)
    chunks_path = args.output_dir / "chunks.jsonl"
    count = write_chunks_jsonl(chunks, chunks_path)

    source_documents = len({chunk.document_id for chunk in chunks})
    char_counts = sorted(len(chunk.text) for chunk in chunks)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source_documents_dir": display_path(args.documents_dir),
        "chunks_file": chunks_path.name,
        "source_document_count": source_documents,
        "chunk_count": count,
        "chunking": {
            "target_chars": config.target_chars,
            "max_chars": config.max_chars,
            "min_chars": config.min_chars,
            "overlap_chars": config.overlap_chars,
        },
        "chunk_chars": {
            "min": char_counts[0] if char_counts else 0,
            "median": char_counts[len(char_counts) // 2] if char_counts else 0,
            "max": char_counts[-1] if char_counts else 0,
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
