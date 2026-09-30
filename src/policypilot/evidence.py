"""Evidence and provenance records for PolicyPilot decisions."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from policypilot.tool_context import project_tool_result

SourceType = Literal["user", "transaction_tool", "knowledge_retrieval", "tool_error"]

_POLICY_DOCUMENT = re.compile(
    r"(?m)^\s*\d+\.\s+([^\r\n]+)\r?\n"
    r"\s*ID:\s*(\S+)\r?\n"
    r"\s*Score:\s*([0-9.]+)\r?\n"
    r"\s*Content:\s*([\s\S]*?)"
    r"(?=^\s*\d+\.\s+.+?\r?\n\s*ID:|\n\n\[Timing:|\Z)"
)
_POLICY_SIGNAL = re.compile(
    r"\b(must|required|requires|limit|maximum|minimum|denied|rejected|"
    r"complete|in_progress|eligible|eligibility|wait|window|cannot|error)\b",
    re.I,
)
_POLICY_ACTION_SIGNAL = re.compile(
    r"\b(wait|retry|re-?submit|resubmit|attempt(?:ing)?|try again|next step|"
    r"before advising|after .* window|once .* passed)\b",
    re.I,
)
_POLICY_QUERY_ANCHORS = (
    re.compile(r"\bno[ -]annual[ -]fee\b", re.I),
    re.compile(r"\bannual fee|fees?|costs?|pricing|charges?\b", re.I),
    re.compile(r"\bsubscriptions?\b", re.I),
    re.compile(r"\beligib(?:le|ility)|requirements?|prerequisites?|qualif", re.I),
    re.compile(r"\bcash[ -]?back|rewards?|points?|returns?|rates?\b", re.I),
    re.compile(r"\bwait|timing|days?|months?|years?|window|deadline\b", re.I),
    re.compile(r"\blimits?|maximum|minimum|caps?|threshold\b", re.I),
)


class PolicyReference(BaseModel):
    """Reference parsed from a banking_knowledge retrieval result."""

    document_id: str
    title: str | None = None
    score: float | None = None


class EvidenceRecord(BaseModel):
    """A compact provenance record for one user or tool observation."""

    source_type: SourceType
    evidence_id: str = Field(default_factory=lambda: f"evidence_{uuid.uuid4().hex}")
    event_id: str | None = None
    payload_ref: str | None = None
    entity: str | None = None
    aspect: str | None = None
    selector: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
    turn_index: int
    summary: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None
    error: bool = False
    policy_refs: list[PolicyReference] = Field(default_factory=list)


def summarize_text(value: Any, limit: int = 500) -> str:
    """Return a compact one-line summary suitable for state and metrics."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _search_terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]{3,}", value.lower())
        if token not in {"and", "for", "from", "into", "the", "with"}
    }


def compact_policy_search(content: str, query: str, limit: int = 3600) -> str:
    """Keep short evidence from every ranked document, not only rank one."""
    documents = list(_POLICY_DOCUMENT.finditer(content))
    if not documents:
        return summarize_text(content, limit)

    query_terms = _search_terms(query)
    summaries = []
    per_document_limit = max(180, (limit - max(0, len(documents) - 1)) // len(documents))
    for document in documents:
        title, document_id, _, body = document.groups()
        lines = []
        for position, raw_line in enumerate(body.splitlines()):
            line = re.sub(r"^[\s#>*-]+", "", raw_line).strip()
            if not line:
                continue
            overlap = len(query_terms.intersection(_search_terms(line)))
            signal = 1 if _POLICY_SIGNAL.search(line) else 0
            lines.append((overlap * 3 + signal * 2, position, line))
        all_ranked = sorted(lines, key=lambda item: (-item[0], item[1]))
        ranked = []
        for anchor in _POLICY_QUERY_ANCHORS:
            if not anchor.search(query):
                continue
            anchor_line = next((item for item in all_ranked if anchor.search(item[2])), None)
            if anchor_line is not None and anchor_line not in ranked:
                ranked.append(anchor_line)
            if len(ranked) >= 3:
                break
        action_line = next(
            (
                item
                for item in all_ranked
                if _POLICY_ACTION_SIGNAL.search(item[2])
            ),
            None,
        )
        if action_line is not None and action_line not in ranked:
            ranked.append(action_line)
        for item in all_ranked:
            if item not in ranked:
                ranked.append(item)
            if len(ranked) >= 3:
                break
        ranked = ranked[:3]
        excerpt = " | ".join(
            summarize_text(
                item[2],
                180 if action_line is not None and item == action_line else 90,
            )
            for item in ranked
        )
        summaries.append(
            summarize_text(
                f"[{document_id}] {title}: {excerpt or 'No excerpt.'}",
                per_document_limit,
            )
        )
    return "\n".join(summaries)


def parse_policy_references(content: str | None) -> list[PolicyReference]:
    """Extract document provenance from tau2 KB_search formatted text."""
    if not content:
        return []
    refs: list[PolicyReference] = []
    current_title: str | None = None
    current_id: str | None = None
    current_score: float | None = None
    for line in content.splitlines():
        title_match = re.match(r"^\s*\d+\.\s+(.+?)\s*$", line)
        if title_match:
            if current_id is not None:
                refs.append(
                    PolicyReference(
                        document_id=current_id,
                        title=current_title,
                        score=current_score,
                    )
                )
            current_title = title_match.group(1)
            current_id = None
            current_score = None
            continue
        id_match = re.match(r"^\s*ID:\s*(\S+)\s*$", line)
        if id_match:
            current_id = id_match.group(1)
            continue
        score_match = re.match(r"^\s*Score:\s*([0-9.]+)\s*$", line)
        if score_match:
            try:
                current_score = float(score_match.group(1))
            except ValueError:
                current_score = None
    if current_id is not None:
        refs.append(
            PolicyReference(
                document_id=current_id,
                title=current_title,
                score=current_score,
            )
        )
    return refs


def make_tool_evidence(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str,
    content: str | None,
    turn_index: int,
    is_retrieval: bool,
    error: bool = False,
    event_id: str | None = None,
    payload_ref: str | None = None,
    focus: str = "",
) -> EvidenceRecord:
    """Create an evidence record from a tool result."""
    refs = parse_policy_references(content) if is_retrieval else []
    if is_retrieval and not refs and content and "No relevant documents found" in content:
        summary = "Retrieval returned no relevant documents."
    elif is_retrieval:
        summary = compact_policy_search(
            content or "",
            str(tool_args.get("query", "")),
        )
    else:
        projection = project_tool_result(content or "", focus=focus)
        summary = projection.content
    return EvidenceRecord(
        evidence_id=tool_call_id,
        event_id=event_id,
        payload_ref=payload_ref,
        source_type=(
            "tool_error"
            if error
            else "knowledge_retrieval"
            if is_retrieval
            else "transaction_tool"
        ),
        tool_name=tool_name,
        tool_args=tool_args,
        tool_call_id=tool_call_id,
        turn_index=turn_index,
        summary=summary,
        error=error,
        policy_refs=refs,
        metadata=(
            {
                "context_ref": {
                    "raw_chars": len(content or ""),
                    "summary_chars": len(summary),
                    "lossy": len(content or "") > len(summary),
                    "document_ids": [item.document_id for item in refs],
                },
                "source_ref": payload_ref,
            }
            if is_retrieval
            else {
                "projection": {
                    "filtered_fields": projection.filtered_fields,
                    "total_fields": projection.total_fields,
                    "range_selected": projection.range_selected,
                    "aggregation": projection.aggregation,
                },
                "context_ref": {
                    "raw_chars": len(content or ""),
                    "summary_chars": len(summary),
                    "lossy": len(content or "") > len(summary),
                },
                "source_ref": payload_ref,
            }
        ),
    )


def make_user_evidence(
    content: str,
    turn_index: int,
    *,
    event_id: str | None = None,
    payload_ref: str | None = None,
) -> EvidenceRecord:
    """Create a compact provenance record for a user observation."""
    return EvidenceRecord(
        event_id=event_id,
        payload_ref=payload_ref,
        source_type="user",
        turn_index=turn_index,
        summary=summarize_text(content),
        tool_name=None,
        tool_args=None,
        tool_call_id=None,
    )
