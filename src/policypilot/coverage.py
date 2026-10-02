"""Bounded semantic policy-evidence coverage resolution."""

from __future__ import annotations

import re
from typing import Literal

from policypilot.coverage_manager import LightweightCoverageManager
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
    def __init__(
        self,
        manager: LightweightCoverageManager | None = None,
    ):
        self.manager = manager

    @property
    def semantic_enabled(self) -> bool:
        return self.manager is not None

    @staticmethod
    def _supports_hard_requirement(
        state: PolicyPilotState, need: InformationNeed, text: str
    ) -> bool:
        criteria = [
            item
            for item in state.goal.criteria
            if item.hard and item.aspect == need.aspect
        ]
        if not criteria:
            return True
        for criterion in criteria:
            required = normalize_text(criterion.value).replace("_", " ")
            if need.aspect == "annual_fee":
                requires_zero = bool(
                    re.search(r"\b(no|without|zero)\b.*\bannual fee\b|免年费|零年费", required, re.I)
                )
                if requires_zero and not re.search(
                    r"\b(no|zero) annual fee\b|annual fee[^\n.;]{0,20}(?:(?:\$\s*)?(?<![\d.])0(?:\.0+)?(?!\d)|waived)|fee-free|免年费|零年费",
                    text,
                    re.I,
                ):
                    return False
                limit = re.search(
                    r"(?:under|below|less than|at most|no more than|不超过|低于)\s*\$?\s*(\d+(?:\.\d+)?)",
                    required,
                    re.I,
                )
                observed = re.search(
                    r"annual fee[^\d$]{0,20}\$?\s*(\d+(?:\.\d+)?)",
                    text,
                    re.I,
                )
                if limit and (not observed or float(observed.group(1)) > float(limit.group(1))):
                    return False
            elif need.aspect == "rewards" and "cashback" in required:
                if not re.search(r"cash.?back", text, re.I):
                    return False
        return True

    def _deterministic_coverage(
        self,
        need: InformationNeed,
        evidence: EvidenceRecord,
        *,
        state: PolicyPilotState | None = None,
    ) -> Coverage:
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
            if state is not None and not self._supports_hard_requirement(
                state, need, text
            ):
                return "PARTIAL"
            return "MATCH"
        if entity_match and (aspect_match or not scope_match):
            return "PARTIAL"
        return "NO_MATCH"

    def coverage(
        self,
        need: InformationNeed,
        evidence: EvidenceRecord,
        *,
        state: PolicyPilotState | None = None,
    ) -> Coverage:
        """Return conservative synchronous coverage for registry lookbacks.

        When semantic coverage is enabled, deterministic matching may identify a
        relevant old evidence packet but cannot fully resolve a newly-created Need.
        The batched semantic manager owns MATCH decisions for live retrievals.
        """

        result = self._deterministic_coverage(need, evidence, state=state)
        if self.semantic_enabled and result == "MATCH":
            return "PARTIAL"
        return result

    @staticmethod
    def _identity_compatible(need: InformationNeed, text: str) -> bool:
        entity = normalize_text(need.entity)
        generic = {
            "banking_product",
            "policy",
            "product",
            "card",
            "account",
            "unknown",
        }
        if (
            entity not in generic
            and entity.replace("_", " ") not in text
            and entity not in text
        ):
            return False
        scope = normalize_text(need.scope or "")
        if "personal" in scope and "business" in text and "personal" not in text:
            return False
        if "business" in scope and "personal" in text and "business" not in text:
            return False
        return True

    def resolve(
        self,
        state: PolicyPilotState,
        evidence: EvidenceRecord,
        *,
        trigger_need_id: str | None = None,
    ) -> dict[str, object]:
        matched: list[str] = []
        partial: list[str] = []
        candidates = (
            self.manager.candidate_needs(state, evidence, trigger_need_id)
            if self.manager is not None
            else list(state.open_needs("POLICY"))
        )
        semantic_failed = False
        decisions: dict[str, Coverage] = {}
        included = candidates
        if self.semantic_enabled and candidates:
            try:
                decisions, included = self.manager.assess(
                    state, evidence, candidates
                )
                state.control.route_trace.append(
                    f"coverage_manager:LIGHT:{len(included)}"
                )
            except Exception as exc:
                semantic_failed = True
                state.control.route_trace.append(
                    f"coverage_manager:fallback:{type(exc).__name__}"
                )

        text = _evidence_text(evidence)
        for need in included:
            if self.semantic_enabled and not semantic_failed:
                coverage = decisions.get(need.id, "NO_MATCH")
            else:
                coverage = self._deterministic_coverage(need, evidence, state=state)
                if self.semantic_enabled and coverage == "MATCH":
                    coverage = "PARTIAL"
                if (
                    semantic_failed
                    and need.id == trigger_need_id
                    and coverage == "NO_MATCH"
                ):
                    coverage = "PARTIAL"
            if coverage == "MATCH" and (
                not self._identity_compatible(need, text)
                or not self._supports_hard_requirement(state, need, text)
            ):
                coverage = "PARTIAL"
            if coverage == "NO_MATCH":
                continue
            need.coverage = coverage
            if evidence.tool_call_id and evidence.tool_call_id not in need.evidence_refs:
                need.evidence_refs.append(evidence.tool_call_id)
            if coverage == "PARTIAL":
                need.status = "PARTIALLY_COVERED"
                need.status_reason = "evidence_partially_matches_need"
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
            fully_resolved = state.resolve_need(
                need,
                evidence_refs=[evidence.tool_call_id] if evidence.tool_call_id else [],
                fact_id=fact.id if fact else None,
            )
            if fully_resolved:
                state.control.needs_resolved_count += 1
            matched.append(need.id)

        trigger = next(
            (item for item in state.information_needs if item.id == trigger_need_id),
            None,
        )
        trigger_coverage: Coverage = "NO_MATCH"
        if trigger is not None:
            if trigger.id in matched:
                trigger_coverage = "MATCH"
            elif trigger.id in partial:
                trigger_coverage = "PARTIAL"
            trigger.coverage = trigger_coverage
            if trigger_coverage == "NO_MATCH" and trigger.query_id:
                trigger.status = "EXHAUSTED"
                trigger.exhausted = True
                trigger.actionable = False
                trigger.status_reason = "query_scoped_evidence_did_not_match"
        return {
            "coverage": trigger_coverage,
            "matched_need_ids": matched,
            "partial_need_ids": partial,
            "matched_evidence_count": len(matched),
        }
