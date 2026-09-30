"""Deterministic, bounded rehydration of task-local context references."""

from __future__ import annotations

import re
from dataclasses import dataclass

from policypilot.config import PolicyPilotConfig
from policypilot.evidence import EvidenceRecord, compact_policy_search
from policypilot.state import InformationNeed, PolicyPilotState
from policypilot.tool_context import project_tool_result

_ASCII_TOKEN = re.compile(r"[a-z0-9_]{3,}", re.I)
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_ACTIVE_STATUSES = {"OPEN", "PARTIALLY_COVERED", "REOPENED"}
_CONTEXT_HEADER = (
    "<rehydrated_context>\n"
    "BOUNDED DETAILS LOADED FROM TASK-LOCAL REFERENCES\n"
)
_CONTEXT_FOOTER = "\n</rehydrated_context>"


def _tokens(value: str) -> set[str]:
    """Return cheap multilingual terms without invoking an embedding model."""

    terms = {item.casefold() for item in _ASCII_TOKEN.findall(value)}
    for run in _CJK_RUN.findall(value):
        terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return terms


@dataclass(frozen=True)
class HydratedReference:
    evidence_id: str
    payload_ref: str
    source_type: str
    need_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    omitted_fields: tuple[str, ...]
    content: str

    def render(self) -> str:
        attributes = [
            f"evidence_id={self.evidence_id}",
            f"payload_ref={self.payload_ref}",
            f"source={self.source_type}",
        ]
        if self.need_ids:
            attributes.append(f"need_ids={','.join(self.need_ids)}")
        if self.document_ids:
            attributes.append(f"document_ids={','.join(self.document_ids)}")
        if self.omitted_fields:
            attributes.append(f"omitted={','.join(self.omitted_fields)}")
        return f"- {'; '.join(attributes)}\n  {self.content}"


@dataclass(frozen=True)
class RehydratedContext:
    references: tuple[HydratedReference, ...] = ()

    @property
    def payload_refs(self) -> list[str]:
        return [item.payload_ref for item in self.references]

    @property
    def evidence_ids(self) -> list[str]:
        return [item.evidence_id for item in self.references]

    @property
    def need_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                need_id for item in self.references for need_id in item.need_ids
            )
        )

    def render(self) -> str:
        if not self.references:
            return ""
        return (
            _CONTEXT_HEADER
            + "\n".join(item.render() for item in self.references)
            + _CONTEXT_FOOTER
        )


def _linked_needs(
    state: PolicyPilotState, evidence_id: str
) -> list[InformationNeed]:
    return [
        need for need in state.information_needs if evidence_id in need.evidence_refs
    ]


def _decision_focus(state: PolicyPilotState, needs: list[InformationNeed]) -> str:
    goal = state.goal
    return " ".join(
        [
            goal.objective or "",
            goal.target or "",
            *(criterion.value for criterion in goal.criteria),
            *(
                " ".join(
                    [
                        need.entity,
                        need.aspect,
                        need.scope or "",
                        need.reason,
                        need.query_objective or "",
                        *need.query_terms,
                    ]
                )
                for need in needs
            ),
        ]
    )


def _is_lossy(evidence: EvidenceRecord, raw_content: str) -> bool:
    projection = evidence.metadata.get("projection", {})
    if projection.get("range_selected"):
        return True
    if int(projection.get("filtered_fields") or 0) < int(
        projection.get("total_fields") or 0
    ):
        return True
    return len(" ".join(raw_content.split())) > len(evidence.summary) + 40


def _omitted_fields(evidence: EvidenceRecord) -> tuple[str, ...]:
    projection = evidence.metadata.get("projection", {})
    omitted: list[str] = []
    if int(projection.get("filtered_fields") or 0) < int(
        projection.get("total_fields") or 0
    ):
        omitted.append("unprojected_tool_fields")
    if projection.get("range_selected"):
        omitted.append("unselected_range_items")
    if evidence.source_type == "knowledge_retrieval":
        omitted.append("additional_policy_passages")
    return tuple(omitted)


def _hydrate_content(
    evidence: EvidenceRecord,
    raw_content: str,
    focus: str,
    limit: int,
) -> str:
    if evidence.source_type == "knowledge_retrieval":
        return compact_policy_search(raw_content, focus, limit=limit)[:limit]
    return project_tool_result(
        raw_content,
        focus=focus,
        max_fields=40,
        max_chars=limit,
    ).content[:limit]


def hydrate_context_refs(
    state: PolicyPilotState,
    config: PolicyPilotConfig | None = None,
) -> RehydratedContext:
    """Load only lossy tool evidence relevant to the current decision surface."""

    config = config or PolicyPilotConfig()
    if not config.context_rehydration_enabled:
        return RehydratedContext()
    payloads = {
        item.payload_id: item
        for item in state.raw_payloads
        if item.raw_content is not None
    }
    goal_focus = _decision_focus(state, state.open_needs())
    focus_tokens = _tokens(goal_focus)
    candidates: list[tuple[int, int, EvidenceRecord, list[InformationNeed]]] = []
    for evidence in state.evidence:
        if evidence.source_type not in {"knowledge_retrieval", "transaction_tool"}:
            continue
        if not evidence.payload_ref or evidence.payload_ref not in payloads:
            continue
        raw_content = payloads[evidence.payload_ref].raw_content or ""
        if not raw_content or not _is_lossy(evidence, raw_content):
            continue
        needs = _linked_needs(state, evidence.evidence_id)
        overlap = len(focus_tokens.intersection(_tokens(evidence.summary)))
        if not needs and focus_tokens and overlap == 0:
            continue
        score = overlap
        score += 100 if needs else 0
        score += 60 if any(need.critical for need in needs) else 0
        score += 30 if any(need.status in _ACTIVE_STATUSES for need in needs) else 0
        score += 15 if evidence.source_type == "knowledge_retrieval" else 0
        candidates.append((score, evidence.turn_index, evidence, needs))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    references: list[HydratedReference] = []
    seen_payloads: set[str] = set()
    remaining = config.max_rehydrated_context_chars - len(
        _CONTEXT_HEADER + _CONTEXT_FOOTER
    )
    for _, _, evidence, needs in candidates:
        if len(references) >= config.max_rehydrated_refs or remaining <= 0:
            break
        assert evidence.payload_ref is not None
        if evidence.payload_ref in seen_payloads:
            continue
        limit = min(config.max_rehydrated_ref_chars, remaining)
        focus = _decision_focus(state, needs or state.open_needs())
        content = _hydrate_content(
            evidence,
            payloads[evidence.payload_ref].raw_content or "",
            focus,
            limit,
        )
        if not content:
            continue
        reference = HydratedReference(
            evidence_id=evidence.evidence_id,
            payload_ref=evidence.payload_ref,
            source_type=evidence.source_type,
            need_ids=tuple(need.id for need in needs),
            document_ids=tuple(ref.document_id for ref in evidence.policy_refs),
            omitted_fields=_omitted_fields(evidence),
            content=content,
        )
        separator_chars = 1 if references else 0
        overflow = len(reference.render()) + separator_chars - remaining
        if overflow > 0:
            retained = len(content) - overflow
            if retained <= 0:
                continue
            reference = HydratedReference(
                evidence_id=reference.evidence_id,
                payload_ref=reference.payload_ref,
                source_type=reference.source_type,
                need_ids=reference.need_ids,
                document_ids=reference.document_ids,
                omitted_fields=reference.omitted_fields,
                content=content[:retained],
            )
        references.append(reference)
        seen_payloads.add(evidence.payload_ref)
        remaining -= len(reference.render()) + separator_chars
    return RehydratedContext(tuple(references))


__all__ = [
    "HydratedReference",
    "RehydratedContext",
    "hydrate_context_refs",
]
