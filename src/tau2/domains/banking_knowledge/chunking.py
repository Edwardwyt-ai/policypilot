"""Deterministic, structure-aware chunking for banking policy documents."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from tau2.domains.banking_knowledge.data_model import Document

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ChunkingConfig:
    """Character-based limits used by the offline policy chunker."""

    target_chars: int = 1200
    max_chars: int = 1600
    min_chars: int = 300
    overlap_chars: int = 160

    def __post_init__(self) -> None:
        if self.target_chars <= 0:
            raise ValueError("target_chars must be positive")
        if self.max_chars < self.target_chars:
            raise ValueError("max_chars must be greater than or equal to target_chars")
        if not 0 <= self.min_chars <= self.target_chars:
            raise ValueError("min_chars must be between 0 and target_chars")
        if not 0 <= self.overlap_chars < self.target_chars:
            raise ValueError("overlap_chars must be between 0 and target_chars")


@dataclass(frozen=True)
class DocumentChunk:
    """A retrieval-ready text unit with lineage back to its source document."""

    id: str
    document_id: str
    title: str
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Block:
    text: str
    section_path: tuple[str, ...]
    is_heading: bool = False


def _normalise_markdown(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n").strip()


def _markdown_blocks(content: str) -> list[_Block]:
    """Parse headings and paragraphs while retaining the active heading path."""
    blocks: list[_Block] = []
    section_stack: list[tuple[int, str]] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = "\n".join(paragraph).strip()
            if text:
                blocks.append(
                    _Block(
                        text=text,
                        section_path=tuple(title for _, title in section_stack),
                        is_heading=False,
                    )
                )
            paragraph.clear()

    for line in _normalise_markdown(content).splitlines():
        stripped = line.strip()
        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            heading_text = heading.group(2).strip()
            section_stack[:] = [
                (existing_level, title)
                for existing_level, title in section_stack
                if existing_level < level
            ]
            section_stack.append((level, heading_text))
            blocks.append(
                _Block(
                    text=stripped,
                    section_path=tuple(title for _, title in section_stack),
                    is_heading=True,
                )
            )
        elif not stripped:
            flush_paragraph()
        else:
            paragraph.append(line.rstrip())
    flush_paragraph()
    return blocks


def _split_at_whitespace(text: str, max_chars: int) -> list[str]:
    """Split one long string without dropping content or breaking most words."""
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _split_long_block(block: _Block, max_chars: int) -> list[_Block]:
    if len(block.text) <= max_chars:
        return [block]

    sentences = _SENTENCE_BOUNDARY_RE.split(block.text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for fragment in _split_at_whitespace(sentence, max_chars):
            candidate = f"{current} {fragment}".strip()
            if current and len(candidate) > max_chars:
                pieces.append(current)
                current = fragment
            else:
                current = candidate
    if current:
        pieces.append(current)
    return [
        _Block(
            text=piece,
            section_path=block.section_path,
            is_heading=block.is_heading,
        )
        for piece in pieces
    ]


def _joined_length(blocks: list[_Block]) -> int:
    return sum(len(block.text) for block in blocks) + max(0, len(blocks) - 1) * 2


def _overlap_tail(blocks: list[_Block], limit: int) -> list[_Block]:
    if limit <= 0:
        return []
    tail: list[_Block] = []
    size = 0
    for block in reversed(blocks):
        added = len(block.text) + (2 if tail else 0)
        if tail and size + added > limit:
            break
        if not tail and len(block.text) > limit:
            text = block.text[-limit:].lstrip()
            return [
                _Block(
                    text=text,
                    section_path=block.section_path,
                    is_heading=block.is_heading,
                )
            ] if text else []
        tail.insert(0, block)
        size += added
    return tail


def _pack_blocks(blocks: list[_Block], config: ChunkingConfig) -> list[list[_Block]]:
    expanded = [
        piece
        for block in blocks
        for piece in _split_long_block(block, config.max_chars)
    ]
    chunks: list[list[_Block]] = []
    current: list[_Block] = []

    for block in expanded:
        candidate = [*current, block]
        candidate_len = _joined_length(candidate)
        should_flush = current and (
            candidate_len > config.max_chars
            or (
                candidate_len > config.target_chars
                and _joined_length(current) >= config.min_chars
            )
        )
        if should_flush:
            pending_heading = current.pop() if current[-1].is_heading else None
            chunks.append(current)
            current = _overlap_tail(current, config.overlap_chars)
            if pending_heading is not None:
                current.append(pending_heading)
            while current and _joined_length([*current, block]) > config.max_chars:
                current.pop(0)
        current.append(block)

    if current:
        if chunks and _joined_length(current) < config.min_chars:
            merged = [*chunks[-1], *current]
            if _joined_length(merged) <= config.max_chars:
                chunks[-1] = merged
            else:
                chunks.append(current)
        else:
            chunks.append(current)
    return chunks


def chunk_document(
    document: Document,
    config: ChunkingConfig | None = None,
    *,
    source: str | None = None,
) -> list[DocumentChunk]:
    """Split one policy document into stable retrieval units."""
    config = config or ChunkingConfig()
    packed = _pack_blocks(_markdown_blocks(document.content), config)
    content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    chunk_count = len(packed)
    chunks: list[DocumentChunk] = []

    for index, blocks in enumerate(packed):
        text = "\n\n".join(block.text for block in blocks).strip()
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        section_paths = list(
            dict.fromkeys(" > ".join(block.section_path) for block in blocks if block.section_path)
        )
        chunk_id = f"{document.id}::chunk-{index:04d}-{text_hash[:10]}"
        chunks.append(
            DocumentChunk(
                id=chunk_id,
                document_id=document.id,
                title=document.title,
                text=text,
                metadata={
                    "chunk_index": index,
                    "chunk_count": chunk_count,
                    "char_count": len(text),
                    "section_paths": section_paths,
                    "source": source,
                    "document_sha256": content_hash,
                    "text_sha256": text_hash,
                },
            )
        )
    return chunks


def load_and_chunk_documents(
    documents_dir: Path,
    config: ChunkingConfig | None = None,
) -> list[DocumentChunk]:
    """Load every source JSON file in deterministic order and chunk it."""
    chunks: list[DocumentChunk] = []
    for path in sorted(documents_dir.glob("*.json"), key=lambda item: item.name):
        payload = json.loads(path.read_text(encoding="utf-8"))
        document = Document(**payload)
        chunks.extend(
            chunk_document(document, config, source=path.name)
        )
    return chunks


def write_chunks_jsonl(chunks: Iterable[DocumentChunk], output_path: Path) -> int:
    """Atomically write chunks as UTF-8 JSON Lines and return their count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    count = 0
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    temporary_path.replace(output_path)
    return count
