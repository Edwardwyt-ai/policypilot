"""Deterministic policy-evidence compatibility and coverage resolution."""

from __future__ import annotations

import re
from typing import Literal

from policypilot.evidence import EvidenceRecord
from policypilot.state import InformationNeed, PolicyPilotState
from policypilot.taxonomy import normalize_text

Coverage = Literal["MATCH", "PARTIAL", "NO_MATCH"]

_ASPECT_PATTERNS = {
    "annual_fee": r"annual fee|fee-free|no annual fee",
    "rewards": r"cash.?back|reward|points",
    "eligibility_rule": r"eligib|qualif|required|requirement|must|condition",
    "qualified_signup_definition": r"qualif|activate|approval|approved|open.*account|spend|condition",
    "reward_limit": r"limit|maximum|cap|up to|per (?:week|month|year)|rolling|more than",
    "payout_timeline": r"timeline|within|days?|weeks?|months?|billing cycle|posts?|pending",
    "resubmission_rule": r"resubmit|retry|try again|wait.*before",
    "procedure": r"procedure|steps?|how to|process|submit|apply",
    "escalation_path": r"escalat|human review|contact support|complaint|dispute",
    "product_terms": r"terms|conditions|policy",
    "candidate_options": r"options?|products?|cards?|accounts?",
    "identity_verification": r"identity|verify|verification|date of birth|address|phone|email",
}


def _evidence_text(evidence: EvidenceRecord) -> str:
    references = " ".join(
        f"{ref.document_id} {ref.title or ''}" for ref in evidence.policy_refs
    )
    return f"{references} {evidence.summary}".lower()


class EvidenceResolver:
    def coverage(self, need: InformationNeed, evidence: EvidenceRecord) -> Coverage:
        if need.source != "POLICY" or evidence.source_type != "knowledge_retrieval":
            return "NO_MATCH"
        text = _evidence_text(evidence)
        entity = normalize_text(need.entity)
        entity_match = entity in {"banking_product", "policy", "product", "unknown"}
        if entity == "referral":
            entity_match = "referral" in text or "refer a friend" in text
        elif entity not in {"banking_product", "policy", "product", "unknown"}:
            entity_match = entity.replace("_", " ") in text or entity in text

        scope = normalize_text(need.scope)
        scope_match = not scope or scope.replace("_", " ") in text or scope in text
        pattern = _ASPECT_PATTERNS.get(need.aspect)
        if pattern:
            aspect_match = bool(re.search(pattern, text, re.I))
        else:
            dynamic_terms = {
                token for token in normalize_text(need.aspect).split("_")
                if len(token) >= 3
            }
            aspect_match = bool(dynamic_terms) and dynamic_terms.issubset(
                set(normalize_text(text).split("_"))
            )
        if entity_match and scope_match and aspect_match:
            return "MATCH"
        if entity_match and (aspect_match or not scope_match):
            return "PARTIAL"
        return "NO_MATCH"

    def resolve(
        self,
        state: PolicyPilotState,
        evidence: EvidenceRecord,
        *,
        trigger_need_id: str | None = None,
    ) -> dict[str, object]:
        matched: list[str] = []
        partial: list[str] = []
        for need in state.open_needs("POLICY"):
            coverage = self.coverage(need, evidence)
            if coverage == "NO_MATCH":
                continue
            need.coverage = coverage
            if evidence.tool_call_id and evidence.tool_call_id not in need.evidence_refs:
                need.evidence_refs.append(evidence.tool_call_id)
            if coverage == "PARTIAL":
                partial.append(need.id)
                continue
            fact = next(
                (
                    item
                    for item in reversed(state.facts)
                    if item.source == "POLICY"
                    and item.evidence_ref == evidence.tool_call_id
                ),
                None,
            )
            state.resolve_need(
                need,
                evidence_refs=[evidence.tool_call_id] if evidence.tool_call_id else [],
                fact_id=fact.id if fact else None,
            )
            state.control.needs_resolved_count += 1
            matched.append(need.id)

        trigger = next(
            (item for item in state.information_needs if item.id == trigger_need_id),
            None,
        )
        trigger_coverage: Coverage = "NO_MATCH"
        if trigger is not None:
            trigger_coverage = self.coverage(trigger, evidence)
            trigger.coverage = trigger_coverage
        return {
            "coverage": trigger_coverage,
            "matched_need_ids": matched,
            "partial_need_ids": partial,
            "matched_evidence_count": len(matched),
        }
