"""Small task-local provenance models for observations and decision context."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class RawPayloadRecord(BaseModel):
    payload_id: str = Field(default_factory=lambda: _id("payload"))
    run_id: str
    event_id: str = Field(default_factory=lambda: _id("event"))
    source_type: str
    tool_call_id: str | None = None
    raw_content: str | None = None
    external_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version_metadata: dict[str, str] = Field(default_factory=dict)


class ContextManifest(BaseModel):
    context_id: str = Field(default_factory=lambda: _id("context"))
    run_id: str
    turn_id: int
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    need_ids: list[str] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    exposed_tools: list[str] = Field(default_factory=list)
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


def record_payload(
    state,
    *,
    source_type: str,
    raw_content: str,
    tool_call_id: str | None = None,
) -> RawPayloadRecord:
    record = RawPayloadRecord(
        run_id=state.run_id,
        source_type=source_type,
        tool_call_id=tool_call_id,
        raw_content=raw_content,
        version_metadata=dict(state.version_metadata),
    )
    state.raw_payloads.append(record)
    return record
