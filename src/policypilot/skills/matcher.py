"""Deterministic, bounded matching for the six PolicyPilot skills."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from policypilot.errors import PolicyPilotErrorType
from policypilot.llm_runtime import LLMRuntime
from policypilot.skills.models import SkillMetadata
from policypilot.state import PolicyPilotState
from tau2.data_model.message import SystemMessage, UserMessage


class SkillSelection(BaseModel):
    skill_ids: list[str] = Field(default_factory=list)


class LLMSkillFallback:
    """Semantic fallback constrained to repository-discovered skill IDs."""

    def __init__(self, runtime: LLMRuntime):
        self.runtime = runtime

    def select(
        self,
        state: PolicyPilotState,
        metadata: list[SkillMetadata],
        *,
        event: str,
        limit: int,
    ) -> list[str]:
        allowed = [item.name for item in metadata]
        result = self.runtime.call_structured(
            "skill_matcher",
            [
                SystemMessage(
                    role="system",
                    content=(
                        "Select at most one ID from ALLOWED_SKILLS. Return an empty "
                        "list when none applies. Never invent an ID."
                    ),
                ),
                UserMessage.text(
                    f"EVENT={event}\nOBJECTIVE={state.goal.objective or ''}\n"
                    f"TARGET={state.goal.target or ''}\nINTENT={state.intent}\n"
                    f"OPEN_NEEDS={[n.source + ':' + n.aspect for n in state.open_needs()[:10]]}\n"
                    f"ALLOWED_SKILLS={allowed}"
                ),
            ],
            SkillSelection,
        )
        return [item for item in result.skill_ids if item in allowed][:1]


class SkillMatcher:
    def __init__(
        self,
        max_active_skills: int = 3,
        semantic_fallback: LLMSkillFallback | None = None,
    ):
        self.max_active_skills = max_active_skills
        self.semantic_fallback = semantic_fallback

    def match(
        self,
        state: PolicyPilotState,
        metadata: list[SkillMetadata],
        *,
        event: str,
        recovery_mode: str | None = None,
    ) -> list[str]:
        available = {item.name: item for item in metadata}
        matched: set[str] = set()
        open_needs = state.open_needs()
        error_categories = {
            item.category for item in state.control.error_records if not item.resolved
        }
        objective = " ".join(
            (state.goal.objective or "", state.goal.target or "")
        ).lower()

        if (
            state.goal.comparative or state.goal.criteria
        ) and "constraint-aware-recommendation" in available:
            matched.add("constraint-aware-recommendation")
        if (
            state.intent == "TRANSACTIONAL"
            and "policy-grounded-transaction" in available
        ):
            matched.add("policy-grounded-transaction")
        if (
            any(
                need.source == "UNKNOWN" or need.source == "USER" and need.critical
                for need in open_needs
            )
            or re.search(
                r"\b(ambiguous|unclear|which one|what do you mean)\b|歧义|不明确|哪一个",
                objective,
            )
        ) and "ambiguity-resolution" in available:
            matched.add("ambiguity-resolution")
        if (
            state.identity_mismatches
            or any(fact.stale_at is not None for fact in state.facts)
            or re.search(
                r"\b(conflict|mismatch|contradict|different)\b|冲突|不一致|矛盾",
                objective,
            )
        ) and "evidence-conflict-resolution" in available:
            matched.add("evidence-conflict-resolution")
        policy_needs = [need for need in open_needs if need.source == "POLICY"]
        if (
            policy_needs
            and (
                len(policy_needs) > 1
                or state.goal.comparative
                or state.intent == "TRANSACTIONAL"
                or state.control.retrieval_miss_count > 0
                or state.control.pending_retrieval_rewrite
            )
        ) and "retrieval-investigation" in available:
            matched.add("retrieval-investigation")
        if (
            event == "RECOVERY_MODE_CHANGE" or recovery_mode or error_categories
        ) and "failure-diagnosis" in available:
            matched.add("failure-diagnosis")
        if PolicyPilotErrorType.MUTATION_UNCERTAIN in error_categories:
            matched.add("evidence-conflict-resolution")

        ordered = sorted(
            (available[name] for name in matched if name in available),
            key=lambda item: (-item.priority, item.name),
        )
        selected = [item.name for item in ordered[: self.max_active_skills]]
        if selected or self.semantic_fallback is None or not state.goal.objective:
            return selected
        try:
            return self.semantic_fallback.select(
                state,
                metadata,
                event=event,
                limit=self.max_active_skills,
            )
        except Exception:
            return []
