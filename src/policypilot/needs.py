"""Information-need sourcing, resolution, and readiness."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from policypilot.config import PolicyPilotConfig
from policypilot.state import InformationNeed, PolicyPilotState
from policypilot.tool_policy import (
    classify_tool,
    is_knowledge_tool,
    tool_runtime_metadata,
)
from tau2.environment.tool import Tool


@dataclass(frozen=True)
class ToolCapability:
    name: str
    classification: str
    fields: frozenset[str]
    resource_tags: frozenset[str]

class SourceResolver:
    def __init__(self, tools: list[Tool]):
        self.capabilities = [
            ToolCapability(
                tool.name,
                classify_tool(tool),
                frozenset(tool.params.model_fields),
                tool_runtime_metadata(tool).resource_tags,
            )
            for tool in tools
        ]

    def resolve(self, need: InformationNeed) -> InformationNeed:
        if need.source != "UNKNOWN":
            return need
        aspect = need.aspect.lower()
        if any(token in aspect for token in ("policy", "eligibility", "fee", "reward", "limit", "timing", "procedure")):
            need.source = "POLICY"
            return need
        match = next((cap for cap in self.capabilities if cap.classification == "transaction_read" and (aspect in cap.name.lower() or aspect in cap.fields)), None)
        if match:
            need.source = "TOOL"
            need.capability = match.name
        elif need.entity == "user":
            need.source = "USER"
        return need

class NeedResolver:
    def __init__(self, config: PolicyPilotConfig | None = None):
        self.config = config or PolicyPilotConfig()

    def resolve(self, state: PolicyPilotState) -> None:
        for need in state.information_needs:
            if need.status in {"RESOLVED", "NOT_APPLICABLE", "EXHAUSTED"}:
                continue
            fact = next((fact for fact in reversed(state.facts) if fact.authoritative and fact.entity == need.entity and fact.aspect == need.aspect and self._authoritative_for(need, fact.source) and (not need.evidence_refs or fact.evidence_ref in need.evidence_refs)), None)
            if fact is None:
                if need.source == "TOOL" and self.config.task_fact_reuse_enabled:
                    state.control.task_fact_reuse_miss += 1
                continue
            if need.source == "TOOL" and not self._tool_fact_reusable(need, fact, state):
                continue
            need.status = "RESOLVED"
            need.resolved_by_fact_id = fact.id
            if fact.evidence_ref and fact.evidence_ref not in need.evidence_refs:
                need.evidence_refs.append(fact.evidence_ref)
            state.control.needs_resolved_count += 1
            if need.source == "TOOL" and self.config.task_fact_reuse_enabled:
                state.control.task_fact_reuse_hit += 1

    def _tool_fact_reusable(self, need, fact, state: PolicyPilotState) -> bool:
        if not self.config.task_fact_reuse_enabled:
            return True
        if need.purpose == "VERIFICATION" and fact.turn_index < need.created_turn:
            state.control.task_fact_forced_refresh += 1
            return False
        if fact.stale_at is not None:
            state.control.task_fact_reuse_stale += 1
            return False
        observed = fact.observed_at or fact.freshness
        if observed is None:
            state.control.task_fact_reuse_miss += 1
            return False
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        ttl = (
            self.config.pre_mutation_fact_ttl_seconds
            if need.purpose == "PRE_MUTATION"
            else self.config.planning_fact_ttl_seconds
        )
        if (datetime.now(timezone.utc) - observed).total_seconds() > ttl:
            state.control.task_fact_reuse_stale += 1
            return False
        return True

    @staticmethod
    def _authoritative_for(need: InformationNeed, source: str) -> bool:
        return (need.source, source) in {("USER", "USER"), ("TOOL", "TOOL"), ("POLICY", "POLICY")} or need.source == "UNKNOWN"


def attach_tool_fact_metadata(
    state: PolicyPilotState, *, evidence_ref: str, resource_tags: Iterable[str]
) -> None:
    """Tag facts emitted by one authoritative read for later invalidation."""
    tags = sorted(set(resource_tags))
    for fact in state.facts:
        if fact.source == "TOOL" and fact.evidence_ref == evidence_ref:
            fact.resource_tags = tags


def invalidate_tool_facts(state: PolicyPilotState, resource_tags: Iterable[str]) -> int:
    """Mark intersecting live facts stale after a mutation outcome."""
    invalidates = set(resource_tags)
    if not invalidates:
        return 0
    now = datetime.now(timezone.utc)
    count = 0
    for fact in state.facts:
        if fact.source != "TOOL" or fact.stale_at is not None:
            continue
        if invalidates.intersection(fact.resource_tags):
            fact.stale_at = now
            count += 1
    return count

def is_blocking_actionable(need: InformationNeed) -> bool:
    return (
        need.status in {"OPEN", "PARTIALLY_COVERED", "REOPENED"}
        and need.critical
        and need.blocking
        and need.actionable
        and not need.exhausted
        and need.source in {"USER", "POLICY", "TOOL"}
    )


def select_next_blocking_need(
    state: PolicyPilotState, config: PolicyPilotConfig | None = None
) -> InformationNeed | None:
    limits = config or PolicyPilotConfig()
    eligible = []
    for need in state.open_needs():
        attempt_limit = (
            need.max_attempts
            if need.max_attempts is not None
            else limits.max_retrieval_attempts_per_semantic_need
        )
        if (
            need.source == "POLICY"
            and need.retrieval_attempts
            >= attempt_limit
        ):
            need.exhausted = True
            need.actionable = False
            need.status = "EXHAUSTED"
            need.status_reason = "retrieval_attempt_limit_reached"
        if is_blocking_actionable(need):
            eligible.append(need)
    if eligible:
        return eligible[0]
    # Preserve a critical exhausted need as an explicit safe-stop reason.
    return next(
        (
            need
            for need in state.information_needs
            if need.status == "EXHAUSTED" and need.critical and need.blocking
        ),
        None,
    )


def decision_ready(
    state: PolicyPilotState, config: PolicyPilotConfig | None = None
) -> bool:
    return select_next_blocking_need(state, config) is None


def next_need(state: PolicyPilotState) -> InformationNeed | None:
    """Compatibility alias for the one blocking-Need selector."""
    return select_next_blocking_need(state)

def knowledge_tool(tools: list[Tool]) -> Tool | None:
    return next((tool for tool in tools if is_knowledge_tool(tool.name)), None)
