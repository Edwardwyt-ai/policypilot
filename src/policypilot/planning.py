"""Bounded semantic deltas for deterministic and lightweight planning."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from policypilot.llm_runtime import LLMRuntime
from policypilot.prompts import SEMANTIC_PLANNER_PROMPT
from policypilot.state import (
    FactCandidate,
    GoalCriterion,
    IntentType,
    NeedCandidate,
    PolicyPilotState,
)
from policypilot.state_updates import is_explicit_action_request
from policypilot.taxonomy import canonicalize_aspect, normalize_text
from tau2.data_model.message import SystemMessage, UserMessage


class GoalDelta(BaseModel):
    objective: str | None = Field(default=None, max_length=500)
    target: str | None = Field(default=None, max_length=80)
    replace: bool = False
    complete: bool = False
    criteria: list[GoalCriterion] = Field(default_factory=list, max_length=6)


class SemanticPlan(BaseModel):
    """Compatibility name for the planner's bounded delta output."""

    intent_delta: IntentType | None = Field(
        default=None, validation_alias=AliasChoices("intent_delta", "intent")
    )
    goal_delta: GoalDelta = Field(default_factory=GoalDelta)
    fact_candidates: list[FactCandidate] = Field(default_factory=list, max_length=4)
    need_candidates: list[NeedCandidate] = Field(default_factory=list, max_length=6)
    subgoal_delta: str | None = Field(default=None, max_length=240)
    explicit_action_request: bool = False
    intent_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    model_route: Literal["DETERMINISTIC", "LIGHT"] = "LIGHT"

    @property
    def facts(self):
        return self.fact_candidates

    @property
    def information_needs(self):
        return self.need_candidates

    @property
    def intent(self):
        return self.intent_delta


PlannerOutput = SemanticPlan

_TARGET_PATTERN = re.compile(
    r"\b(cards?|accounts?|loans?|mortgages?|referrals?|transactions?|deposits?)\b",
    re.I,
)


def _mentioned_target(content: str) -> str | None:
    match = _TARGET_PATTERN.search(content)
    if match is None:
        return None
    prefix = content[max(0, match.start() - 24) : match.start()]
    if re.search(r"\b(?:have|has|with)\s+no\s+$|\bwithout\s+$|没有\s*$", prefix, re.I):
        return None
    return match.group(1).lower().removesuffix("s")


class PlannerModelRouter:
    def route(self, *, ambiguous: bool) -> Literal["LIGHT"]:
        return "LIGHT"


def planner_trigger_reason(state: PolicyPilotState, content: str) -> str | None:
    """Run the light planner only for a substantive goal event."""

    text = " ".join(content.split())
    if not text:
        return None
    if re.fullmatch(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        return None
    if re.fullmatch(r"(?:\+?\d[\d ()-]{7,}\d)", text):
        return None
    if state.goal.objective is None:
        return "new_goal"
    if re.search(r"\b(actually|instead|correction|i mean)\b|更正|改成|其实", text, re.I):
        return "goal_correction"
    if re.search(r"\b(must|without|prefer|ideally|highest|lowest|maximi[sz]e|minimi[sz]e)\b|必须|偏好|最好|最高|最低", text, re.I):
        return "constraint_change"
    mentioned_target = _mentioned_target(text)
    if (
        mentioned_target
        and state.goal.target
        and normalize_text(mentioned_target) != normalize_text(state.goal.target)
    ):
        return "goal_scope_changed"
    return None


class LLMSemanticPlanner:
    def __init__(self, runtime: LLMRuntime, capabilities: set[str] | None = None):
        self.runtime = runtime
        self.capabilities = sorted(capabilities or set())

    def plan(self, state: PolicyPilotState, content: str, turn: int, *, skill_guidance: str = "", trigger_reason: str = "new_goal", memory_hints: list[str] | None = None) -> SemanticPlan:
        payload = {
            "event": trigger_reason,
            "latest_user_message": content[:800],
            "goal": {
                "objective": state.goal.objective,
                "target": state.goal.target,
                "criteria": [{"kind": item.kind, "aspect": item.aspect, "value": item.value[:180]} for item in state.goal.criteria[-6:]],
            },
            "user_facts": [
                {"entity": fact.entity, "aspect": fact.aspect, "value": str(fact.value)[:120]}
                for fact in state.facts[-10:] if fact.source == "USER" and fact.aspect != "utterance"
            ][-4:],
            "active_needs": [{"entity": need.entity, "aspect": need.aspect, "scope": need.scope, "source": need.source} for need in state.open_needs()[:8]],
            "resolved_needs": [{"entity": need.entity, "aspect": need.aspect, "scope": need.scope} for need in state.resolved_needs()[-6:]],
            "relevant_evidence": [
                {"source": item.source_type, "summary": item.summary[:180]}
                for item in state.evidence
                if item.source_type in {"transaction_tool", "knowledge_retrieval"}
            ][-2:],
            "memory_hints": [hint[:180] for hint in (memory_hints or [])[:2]],
            "skill_guidance": skill_guidance[:400],
            "tool_capabilities": self.capabilities,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, default=str)
        plan = self.runtime.call_structured(
            "semantic_planner",
            [SystemMessage(role="system", content=SEMANTIC_PLANNER_PROMPT), UserMessage.text(payload_text)],
            SemanticPlan,
            trace_metadata={"trigger_reason": trigger_reason, "input_chars": len(payload_text)},
        )
        plan.model_route = "LIGHT"
        self._validate_delta(plan, turn)
        return plan

    def _validate_delta(self, plan: SemanticPlan, turn: int) -> None:
        valid_needs: list[NeedCandidate] = []
        for candidate in plan.need_candidates:
            aspect = canonicalize_aspect(candidate.aspect, entity=candidate.entity, scope=candidate.scope)
            if aspect is None:
                aspect = normalize_text(candidate.aspect)
            if not aspect:
                continue
            candidate.aspect = aspect
            candidate.provenance = "semantic_planner"
            if candidate.source == "TOOL" and candidate.capability not in self.capabilities:
                continue
            valid_needs.append(candidate)
        plan.need_candidates = valid_needs
        for criterion in plan.goal_delta.criteria:
            criterion.source_turn = turn


_HARD = re.compile(r"\b(must|cannot|can't|without|do not|don't)\b|必须|不能|不要", re.I)
_PREF = re.compile(r"\b(prefer|want|ideally|looking for|if possible)\b|偏好|希望|最好", re.I)
_OPT = re.compile(r"\b(best|highest|lowest|most|least|maximi[sz]e|minimi[sz]e)\b|最好|最高|最低|最大|最小", re.I)
_COMPARE = re.compile(r"\b(compare|which|best|alternative|option)\b|比较|哪个|选择|最适合", re.I)
_CORRECT = re.compile(r"\b(actually|instead|correction|i mean)\b|更正|改成|其实", re.I)


def _id(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha1(value.lower().encode()).hexdigest()[:12]}"


def deterministic_semantic_plan(state: PolicyPilotState, content: str, turn: int, intent: IntentType, memory_hints: list[str] | None = None) -> SemanticPlan:
    """Preserve explicit criteria without creating authoritative needs."""

    mentioned_target = _mentioned_target(content)
    replacing = bool(_CORRECT.search(content)) or bool(
        mentioned_target
        and state.goal.target
        and normalize_text(mentioned_target) != normalize_text(state.goal.target)
    )
    delta = GoalDelta(objective=content.strip(), replace=replacing)
    if mentioned_target and (state.goal.target is None or replacing):
        delta.target = mentioned_target
    for sentence in filter(None, (item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", content))):
        for clause in filter(None, (item.strip() for item in re.split(r"\b(?:and|but|while)\b|[,;]", sentence, flags=re.I))):
            kind = "CONSTRAINT" if _HARD.search(clause) else "OPTIMIZATION" if _OPT.search(clause) else "PREFERENCE" if _PREF.search(clause) else None
            aspect = canonicalize_aspect(clause, entity=clause)
            if not kind or aspect is None:
                continue
            delta.criteria.append(GoalCriterion(id=_id(kind.lower(), f"{aspect}:{clause}"), kind=kind, aspect=aspect, value=clause[:300], hard=kind == "CONSTRAINT", source_turn=turn))
    current = state.goal.objective or ""
    delta.objective = content.strip() if not current or replacing else current
    if memory_hints:
        state.control.route_trace.append(
            f"semantic_planner_memory_hints:{min(len(memory_hints), 2)}"
        )
    explicit_action = intent == "TRANSACTIONAL" and is_explicit_action_request(
        content
    )
    return SemanticPlan(
        intent_delta=intent,
        goal_delta=delta,
        explicit_action_request=explicit_action,
        intent_confidence=0.9 if explicit_action or intent != "TRANSACTIONAL" else 0.55,
        model_route="DETERMINISTIC",
    )


def merge_semantic_plan(state: PolicyPilotState, plan: SemanticPlan, turn: int) -> list[NeedCandidate]:
    """Merge goal/fact deltas and return candidates for the sole Need Registry."""

    delta = plan.goal_delta
    if delta.replace:
        for need in state.open_needs():
            state.mark_not_applicable(
                need, reason="superseded_by_goal_change", turn=turn
            )
        state.goal.criteria.clear()
        state.goal.comparative = False
    if delta.complete:
        state.goal.status = "COMPLETED"
    if delta.objective and (not state.goal.objective or delta.replace):
        state.goal.objective = delta.objective
        state.goal.source_turn = turn
        state.control.goal_change_count += 1
    if delta.target and (
        state.goal.target is None
        or delta.replace
        or normalize_text(delta.target) == normalize_text(state.goal.target)
    ):
        state.goal.target = delta.target
    state.goal.comparative = state.goal.comparative or bool(_COMPARE.search(delta.objective or ""))
    changed_hard_aspects: set[str] = set()
    for criterion in delta.criteria:
        existing = next((i for i, item in enumerate(state.goal.criteria) if item.id == criterion.id or (item.aspect, item.kind) == (criterion.aspect, criterion.kind)), None)
        if existing is None:
            state.goal.criteria.append(criterion)
            if criterion.hard:
                changed_hard_aspects.add(criterion.aspect)
        else:
            previous = state.goal.criteria[existing]
            state.goal.criteria[existing] = criterion
            if criterion.hard and criterion.value != previous.value:
                changed_hard_aspects.add(criterion.aspect)
    for need in state.information_needs:
        if (
            need.source == "POLICY"
            and need.status == "RESOLVED"
            and need.aspect in changed_hard_aspects
        ):
            state.mark_not_applicable(
                need,
                reason="superseded_by_hard_constraint_change",
                turn=turn,
            )
    state.goal.updated_turn = turn
    if plan.intent is not None:
        if plan.intent != "TRANSACTIONAL" or (
            plan.explicit_action_request and plan.intent_confidence >= 0.7
        ):
            state.intent = plan.intent
        else:
            state.control.route_trace.append("intent_transactional_rejected:not_explicit")
    for candidate in plan.fact_candidates:
        state.control.route_trace.append(f"planner_fact_candidate:{candidate.entity}.{candidate.aspect}")
    state.control.route_trace.append(f"semantic_planner:{plan.model_route}")
    return list(plan.need_candidates)
