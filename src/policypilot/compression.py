"""Budget-triggered, query-focused ToolMessage compression."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from policypilot.llm_runtime import LLMRuntime
from tau2.data_model.message import SystemMessage, UserMessage


class CompressedToolContext(BaseModel):
    summary: str
    retained_fields: list[str] = Field(default_factory=list)
    omitted_fields: list[str] = Field(default_factory=list)


class ToolContextCompressor:
    def __init__(self, runtime: LLMRuntime, max_chars: int = 420):
        self.runtime = runtime
        self.max_chars = max_chars
        self._cache: dict[str, str] = {}

    def compress_context(
        self,
        *,
        content: str,
        query_focus: str,
        target_tokens: int,
    ) -> str:
        """Compress one already-filtered decision context in one model call."""

        cache_key = hashlib.sha256(
            f"context\0{target_tokens}\0{query_focus}\0{content}".encode("utf-8")
        ).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self.runtime.call_structured(
            "context_compressor",
            [
                SystemMessage(
                    role="system",
                    content=(
                        "Compress the filtered decision context. Preserve exact IDs, "
                        "statuses, policy conditions, provenance, unresolved needs, and "
                        "the latest user correction. Remove repetition only."
                    ),
                ),
                UserMessage.text(
                    f"TARGET_TOKENS={target_tokens}\nFOCUS={query_focus[:800]}\n"
                    f"FILTERED_CONTEXT={content[:48000]}"
                ),
            ],
            CompressedToolContext,
            trace_metadata={"input_chars": len(content), "target_tokens": target_tokens},
        )
        compressed = json.dumps(
            {
                "summary": result.summary,
                "payload_ref": "filtered_decision_context",
                "retained_fields": result.retained_fields,
                "omission_metadata": {"omitted_fields": result.omitted_fields},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._cache[cache_key] = compressed
        return compressed

    def compress(
        self,
        *,
        content: str,
        query_focus: str,
        tool_call_id: str,
        evidence_ref: str | None,
    ) -> str:
        cache_key = hashlib.sha256(
            f"{tool_call_id}\0{query_focus}\0{content}".encode("utf-8")
        ).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self.runtime.call_structured(
            "context_compressor",
            [
                SystemMessage(
                    role="system",
                    content=(
                        "Compress the tool payload for the query focus. Preserve exact IDs, "
                        "statuses, timestamps, counters, policy conditions, and provenance "
                        "when relevant. Report omitted field names. Do not invent values."
                    ),
                ),
                UserMessage.text(
                    f"QUERY_FOCUS={query_focus[:1200]}\nTOOL_PAYLOAD={content[:12000]}"
                ),
            ],
            CompressedToolContext,
        )
        envelope = {
            "summary": result.summary[: self.max_chars],
            "provenance": {"tool_call_id": tool_call_id},
            "payload_ref": tool_call_id,
            "evidence_ref": evidence_ref,
            "retained_fields": result.retained_fields,
            "omission_metadata": {"omitted_fields": result.omitted_fields},
        }
        compressed = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        self._cache[cache_key] = compressed
        return compressed
