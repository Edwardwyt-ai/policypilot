"""Derived decision requirements, coverage, and retrieval gaps.

The canonical data remains StructuredGoal + InformationNeed. These views are
computed on demand so PolicyPilot does not maintain a second mutable state tree.
"""

from __future__ import annotations

from dataclasses import dataclass

from policypilot.retrieval import build_retrieval_call, build_retrieval_query
from policypilot.state import PolicyPilotState


@dataclass(frozen=True)
class RequirementModel:
    objective: str | None
    hard_constraints: tuple[str, ...]
    preferences: tuple[str, ...]
    optimization_criteria: tuple[str, ...]


@dataclass(frozen=True)
class CoverageItem:
    candidate: str
    aspect: str
    status: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalGap:
    need_id: str
    candidate: str
    aspect: str
    reason: str
    critical: bool
    status: str


def requirement_model(state: PolicyPilotState) -> RequirementModel:
    criteria = state.goal.criteria
    return RequirementModel(
        objective=state.goal.objective,
        hard_constraints=tuple(item.value for item in criteria if item.hard),
        preferences=tuple(
            item.value for item in criteria if item.kind == "PREFERENCE"
        ),
        optimization_criteria=tuple(
            item.value for item in criteria if item.kind == "OPTIMIZATION"
        ),
    )


def retrieval_coverage(state: PolicyPilotState) -> tuple[CoverageItem, ...]:
    return tuple(
        CoverageItem(
            candidate=need.entity,
            aspect=need.aspect,
            status=(
                "COVERED"
                if need.status == "RESOLVED"
                else "NOT_APPLICABLE"
                if need.status == "NOT_APPLICABLE"
                else "PARTIAL"
                if need.status == "PARTIALLY_COVERED" or need.coverage == "PARTIAL"
                else "MISSING"
            ),
            evidence_refs=tuple(need.evidence_refs),
        )
        for need in state.information_needs
        if need.source == "POLICY"
    )


def retrieval_gaps(state: PolicyPilotState) -> tuple[RetrievalGap, ...]:
    return tuple(
        RetrievalGap(
            need_id=need.id,
            candidate=need.entity,
            aspect=need.aspect,
            reason=need.reason,
            critical=need.critical,
            status=need.status,
        )
        for need in state.information_needs
        if need.source == "POLICY"
        and need.status not in {"RESOLVED", "NOT_APPLICABLE"}
    )


def render_requirement_gap_context(
    state: PolicyPilotState, *, max_items: int = 8
) -> str:
    requirements = requirement_model(state)
    gaps = retrieval_gaps(state)[:max_items]
    lines = [
        "DECISION REQUIREMENTS",
        f"objective={requirements.objective or 'None'}",
        "hard=" + ("; ".join(requirements.hard_constraints) or "None"),
        "preferences=" + ("; ".join(requirements.preferences) or "None"),
        "optimize=" + ("; ".join(requirements.optimization_criteria) or "None"),
        "RETRIEVAL GAPS",
    ]
    lines.extend(
        f"- {item.candidate}.{item.aspect} [{item.status}]: {item.reason}"
        for item in gaps
    )
    if not gaps:
        lines.append("- None")
    return "\n".join(lines)

__all__ = [
    "CoverageItem",
    "RequirementModel",
    "RetrievalGap",
    "build_retrieval_call",
    "build_retrieval_query",
    "render_requirement_gap_context",
    "requirement_model",
    "retrieval_coverage",
    "retrieval_gaps",
]
