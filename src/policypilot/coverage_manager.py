"""Compact light-model manager for policy evidence coverage."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from policypilot.evidence import EvidenceRecord
from policypilot.state import InformationNeed, PolicyPilotState
from policypilot.taxonomy import normalize_text
from tau2.data_model.message import SystemMessage, UserMessage


class CoverageAssignment(BaseModel):
    """One accepted coverage decision; omission represents NO_MATCH."""

    need_id: str = Field(min_length=1, max_length=160)
    coverage: Literal["MATCH", "PARTIAL"]


class CoverageAssessment(BaseModel):
    assignments: list[CoverageAssignment] = Field(default_factory=list, max_length=8)


_PROMPT = """You are a strict policy evidence coverage judge.
Judge only the listed Needs against the single evidence packet.
MATCH means the evidence directly answers the Need for the same entity and scope,
including every listed hard requirement. PARTIAL means it is relevant but misses
part of the answer or requirement. Omit NO_MATCH Needs. Never invent Need IDs.
Return only the compact schema fields; do not explain your reasoning."""


def _evidence_text(evidence: EvidenceRecord) -> str:
    references = " ".join(
        f"{ref.document_id} {ref.title or ''}" for ref in evidence.policy_refs
    )
    return normalize_text(f"{references} {evidence.summary}")


class LightweightCoverageManager:
    """Batch semantic coverage over a bounded, purpose-built context."""

    def __init__(
        self,
        runtime: Any,
        *,
        max_candidate_needs: int = 8,
        max_context_chars: int = 2400,
        max_evidence_chars: int = 1400,
    ):
        self.runtime = runtime
        self.max_candidate_needs = max(1, min(max_candidate_needs, 8))
        self.max_context_chars = max(800, max_context_chars)
        self.max_evidence_chars = max(300, max_evidence_chars)

    def candidate_needs(
        self,
        state: PolicyPilotState,
        evidence: EvidenceRecord,
        trigger_need_id: str | None,
    ) -> list[InformationNeed]:
        open_needs = list(state.open_needs("POLICY"))
        text = _evidence_text(evidence)

        def score(need: InformationNeed) -> tuple[int, int, int]:
            entity = normalize_text(need.entity)
            aspect_terms = normalize_text(need.aspect).split("_")
            overlap = sum(term in text for term in aspect_terms if len(term) >= 3)
            entity_hit = int(
                entity
                in {
                    "banking_product",
                    "policy",
                    "product",
                    "card",
                    "account",
                    "unknown",
                }
                or entity in text
                or entity.replace("_", " ") in text
            )
            return (entity_hit, overlap, need.priority)

        trigger = next(
            (need for need in open_needs if need.id == trigger_need_id), None
        )
        others = [need for need in open_needs if need is not trigger]
        others.sort(key=score, reverse=True)
        ordered = ([trigger] if trigger is not None else []) + others
        return ordered[: self.max_candidate_needs]

    def _payload(
        self,
        state: PolicyPilotState,
        evidence: EvidenceRecord,
        candidates: list[InformationNeed],
    ) -> tuple[str, list[InformationNeed]]:
        need_rows = []
        for need in candidates:
            requirements = [
                criterion.value[:120]
                for criterion in state.goal.criteria
                if criterion.hard
                and normalize_text(criterion.aspect) == normalize_text(need.aspect)
            ][:2]
            need_rows.append(
                {
                    "id": need.id,
                    "entity": need.entity[:80],
                    "aspect": need.aspect[:80],
                    "scope": (need.scope or "")[:80],
                    "must": requirements,
                }
            )
        payload = {
            "needs": need_rows,
            "evidence": {
                "documents": [
                    {
                        "id": ref.document_id[:80],
                        "title": (ref.title or "")[:100],
                    }
                    for ref in evidence.policy_refs[:6]
                ],
                "summary": evidence.summary[: self.max_evidence_chars],
            },
        }
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) > self.max_context_chars:
            overflow = len(serialized) - self.max_context_chars
            summary = payload["evidence"]["summary"]
            payload["evidence"]["summary"] = summary[
                : max(300, len(summary) - overflow - 8)
            ]
            serialized = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )
        while len(serialized) > self.max_context_chars and len(need_rows) > 1:
            need_rows.pop()
            candidates = candidates[: len(need_rows)]
            serialized = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )
        if len(serialized) > self.max_context_chars:
            overflow = len(serialized) - self.max_context_chars
            summary = payload["evidence"]["summary"]
            payload["evidence"]["summary"] = summary[
                : max(120, len(summary) - overflow - 8)
            ]
            serialized = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )
        return serialized, candidates

    def assess(
        self,
        state: PolicyPilotState,
        evidence: EvidenceRecord,
        candidates: list[InformationNeed],
    ) -> tuple[dict[str, Literal["MATCH", "PARTIAL"]], list[InformationNeed]]:
        payload, included = self._payload(state, evidence, candidates)
        result = self.runtime.call_structured(
            "coverage_manager",
            [
                SystemMessage(role="system", content=_PROMPT),
                UserMessage.text(payload),
            ],
            CoverageAssessment,
            call_name="policypilot_coverage_manager",
            trace_metadata={
                "input_chars": len(payload),
                "candidate_needs": len(included),
                "omitted_needs": max(
                    0, len(state.open_needs("POLICY")) - len(included)
                ),
            },
        )
        allowed = {need.id for need in included}
        decisions: dict[str, Literal["MATCH", "PARTIAL"]] = {}
        for assignment in result.assignments:
            if assignment.need_id not in allowed:
                continue
            if decisions.get(assignment.need_id) != "MATCH":
                decisions[assignment.need_id] = assignment.coverage
        return decisions, included
