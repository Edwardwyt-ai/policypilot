"""Validated Need dependencies without introducing a second scheduler."""

from __future__ import annotations

from typing import Iterable

from policypilot.state import (
    DependencyHint,
    InformationNeed,
    NeedCandidate,
    NeedDependency,
    PolicyPilotState,
)
from policypilot.taxonomy import canonical_entity, canonicalize_aspect, normalize_text


def need_key(need: InformationNeed) -> str:
    return need.semantic_key or need.id


def _dependency_identity(dependency: NeedDependency) -> tuple:
    return (
        dependency.kind,
        dependency.upstream_semantic_key,
        dependency.entity,
        dependency.aspect,
        repr(dependency.expected_value),
        dependency.mutation_tool,
        dependency.mutation_signature,
    )


def _find_need(state: PolicyPilotState, key: str | None) -> InformationNeed | None:
    if not key:
        return None
    return next((item for item in state.information_needs if need_key(item) == key), None)


def _matching_fact(state: PolicyPilotState, dependency: NeedDependency):
    return next(
        (
            fact
            for fact in reversed(state.facts)
            if fact.entity == dependency.entity
            and fact.aspect == dependency.aspect
            and fact.stale_at is None
            and (
                not dependency.require_authoritative or fact.authoritative
            )
            and (not dependency.require_verified or fact.verified)
            and (
                dependency.expected_value is None
                or fact.value == dependency.expected_value
            )
        ),
        None,
    )


def dependency_satisfied(
    dependency: NeedDependency, state: PolicyPilotState
) -> bool:
    if dependency.kind == "NEED":
        upstream = _find_need(state, dependency.upstream_semantic_key)
        return upstream is not None and upstream.status in {
            "RESOLVED",
            "NOT_APPLICABLE",
        }
    if dependency.kind == "FACT":
        return _matching_fact(state, dependency) is not None
    if dependency.kind == "MUTATION":
        return any(
            (
                not dependency.mutation_signature
                or item.signature == dependency.mutation_signature
            )
            and (
                not dependency.mutation_tool
                or item.tool_name == dependency.mutation_tool
            )
            and item.status in dependency.required_mutation_statuses
            for item in state.mutations
        )
    return False


def dependency_blockers(
    need: InformationNeed,
    state: PolicyPilotState,
    *,
    strength: str = "HARD",
) -> list[NeedDependency]:
    return [
        dependency
        for dependency in need.dependencies
        if dependency.strength == strength
        and not dependency_satisfied(dependency, state)
    ]


def is_need_runnable(need: InformationNeed, state: PolicyPilotState) -> bool:
    return not dependency_blockers(need, state, strength="HARD")


def soft_missing_count(need: InformationNeed, state: PolicyPilotState) -> int:
    return len(dependency_blockers(need, state, strength="SOFT"))


class DependencyManager:
    """Build deterministic edges and validate bounded LLM hints."""

    def attach_for_candidates(
        self,
        state: PolicyPilotState,
        pairs: Iterable[tuple[InformationNeed, NeedCandidate]],
        *,
        turn: int,
    ) -> None:
        for need, candidate in pairs:
            self._attach_deterministic(state, need, candidate, turn=turn)
        # Resolve semantic hints only after every candidate in the batch exists.
        for need, candidate in pairs:
            self._attach_hints(state, need, candidate.dependency_hints, turn=turn)
        self._reconcile_hard_constraint_edges(state, turn=turn)

    def _reconcile_hard_constraint_edges(
        self, state: PolicyPilotState, *, turn: int
    ) -> None:
        """Connect Needs that may have been registered in different turns."""
        hard_aspects = {
            canonicalize_aspect(
                item.aspect,
                entity=state.goal.target or "",
                scope=state.goal.target,
            )
            or normalize_text(item.aspect)
            for item in state.goal.criteria
            if item.hard
        }
        if not hard_aspects:
            return
        upstreams = [
            item
            for item in state.information_needs
            if item.source == "POLICY" and item.aspect in hard_aspects
        ]
        for downstream in state.information_needs:
            if downstream.aspect != "candidate_options":
                continue
            for upstream in upstreams:
                if upstream.id == downstream.id:
                    continue
                self.add(
                    state,
                    downstream,
                    NeedDependency(
                        kind="NEED",
                        strength="HARD",
                        origin="DETERMINISTIC",
                        reason_code="hard_constraint_input",
                        upstream_semantic_key=need_key(upstream),
                    ),
                    turn=turn,
                )

    def _attach_deterministic(
        self,
        state: PolicyPilotState,
        need: InformationNeed,
        candidate: NeedCandidate,
        *,
        turn: int,
    ) -> None:
        if candidate.source == "TOOL":
            for aspect, value in candidate.tool_arguments.items():
                fact = next(
                    (
                        item
                        for item in reversed(state.facts)
                        if item.aspect == aspect
                        and item.value == value
                        and item.authoritative
                        and item.stale_at is None
                    ),
                    None,
                )
                if fact is not None:
                    self.add(
                        state,
                        need,
                        NeedDependency(
                            kind="FACT",
                            strength="HARD",
                            origin="DETERMINISTIC",
                            reason_code="tool_argument_fact",
                            entity=fact.entity,
                            aspect=fact.aspect,
                            expected_value=value,
                            # A read Need may itself be responsible for verifying
                            # this argument. Requiring prior verification here would
                            # make that prerequisite impossible to acquire.
                            require_verified=False,
                        ),
                        turn=turn,
                    )
                    continue
                producer = next(
                    (
                        item
                        for item in state.information_needs
                        if item.id != need.id
                        and item.aspect == aspect
                        and item.status
                        in {"OPEN", "PARTIALLY_COVERED", "REOPENED", "RESOLVED"}
                    ),
                    None,
                )
                if producer is not None:
                    self.add(
                        state,
                        need,
                        NeedDependency(
                            kind="NEED",
                            strength="HARD",
                            origin="DETERMINISTIC",
                            reason_code="tool_argument_need",
                            upstream_semantic_key=need_key(producer),
                        ),
                        turn=turn,
                    )

        if candidate.aspect == "candidate_options":
            hard_aspects = {item.aspect for item in state.goal.criteria if item.hard}
            for upstream in state.information_needs:
                if (
                    upstream.id != need.id
                    and upstream.source == "POLICY"
                    and upstream.aspect in hard_aspects
                ):
                    self.add(
                        state,
                        need,
                        NeedDependency(
                            kind="NEED",
                            strength="HARD",
                            origin="DETERMINISTIC",
                            reason_code="hard_constraint_input",
                            upstream_semantic_key=need_key(upstream),
                        ),
                        turn=turn,
                    )

        if candidate.purpose == "VERIFICATION":
            mutation = next(
                (
                    item
                    for item in reversed(state.mutations)
                    if item.tool_name == candidate.entity
                ),
                state.mutations[-1] if state.mutations else None,
            )
            if mutation is not None:
                self.add(
                    state,
                    need,
                    NeedDependency(
                        kind="MUTATION",
                        strength="HARD",
                        origin="DETERMINISTIC",
                        reason_code="mutation_verification",
                        mutation_tool=mutation.tool_name,
                        mutation_signature=mutation.signature,
                    ),
                    turn=turn,
                )

    def _attach_hints(
        self,
        state: PolicyPilotState,
        downstream: InformationNeed,
        hints: list[DependencyHint],
        *,
        turn: int,
    ) -> None:
        for hint in hints[:4]:
            aspect = canonicalize_aspect(
                hint.aspect, entity=hint.entity, scope=hint.entity
            ) or normalize_text(hint.aspect)
            entity = canonical_entity(hint.entity, aspect)
            upstream = next(
                (
                    item
                    for item in state.information_needs
                    if item.id != downstream.id
                    and item.entity == entity
                    and item.aspect == aspect
                    and (hint.source is None or item.source == hint.source)
                ),
                None,
            )
            if upstream is None:
                self._event(
                    state,
                    turn=turn,
                    downstream=downstream,
                    accepted=False,
                    reason="llm_hint_missing_upstream",
                )
                continue
            self.add(
                state,
                downstream,
                NeedDependency(
                    kind="NEED",
                    strength="SOFT",
                    origin="LLM",
                    reason_code=hint.reason_code,
                    upstream_semantic_key=need_key(upstream),
                ),
                turn=turn,
            )

    def add(
        self,
        state: PolicyPilotState,
        downstream: InformationNeed,
        dependency: NeedDependency,
        *,
        turn: int,
    ) -> bool:
        if dependency.origin == "LLM":
            dependency.strength = "SOFT"
        if dependency.kind == "NEED":
            upstream = _find_need(state, dependency.upstream_semantic_key)
            if upstream is None or upstream.id == downstream.id:
                self._event(
                    state,
                    turn=turn,
                    downstream=downstream,
                    accepted=False,
                    reason="invalid_need_dependency",
                )
                return False
            if self._would_cycle(state, downstream, upstream):
                self._event(
                    state,
                    turn=turn,
                    downstream=downstream,
                    accepted=False,
                    reason="dependency_cycle_rejected",
                )
                return False
            if dependency.strength == "HARD" and downstream.critical:
                upstream.critical = True
                upstream.blocking = True
        identity = _dependency_identity(dependency)
        if any(_dependency_identity(item) == identity for item in downstream.dependencies):
            return False
        downstream.dependencies.append(dependency)
        self._event(
            state,
            turn=turn,
            downstream=downstream,
            accepted=True,
            reason=dependency.reason_code,
            dependency=dependency,
        )
        return True

    @staticmethod
    def _would_cycle(
        state: PolicyPilotState,
        downstream: InformationNeed,
        upstream: InformationNeed,
    ) -> bool:
        target = need_key(downstream)
        stack = [need_key(upstream)]
        visited: set[str] = set()
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            item = _find_need(state, current)
            if item is None:
                continue
            stack.extend(
                dependency.upstream_semantic_key
                for dependency in item.dependencies
                if dependency.kind == "NEED"
                and dependency.upstream_semantic_key
            )
        return False

    @staticmethod
    def _event(
        state: PolicyPilotState,
        *,
        turn: int,
        downstream: InformationNeed,
        accepted: bool,
        reason: str,
        dependency: NeedDependency | None = None,
    ) -> None:
        state.control.dependency_events.append(
            {
                "turn": turn,
                "downstream_need_id": downstream.id,
                "downstream_semantic_key": need_key(downstream),
                "accepted": accepted,
                "reason": reason,
                "dependency": (
                    dependency.model_dump(mode="json") if dependency else None
                ),
            }
        )


def refresh_dependency_state(state: PolicyPilotState, *, turn: int) -> None:
    """Propagate terminal parents and reopen resolved Needs after stale inputs."""

    for need in state.information_needs:
        hard_need_dependencies = [
            item
            for item in need.dependencies
            if item.kind == "NEED" and item.strength == "HARD"
        ]
        parents = [
            parent
            for item in hard_need_dependencies
            if (parent := _find_need(state, item.upstream_semantic_key)) is not None
        ]
        exhausted_parent = next(
            (parent for parent in parents if parent.status == "EXHAUSTED"), None
        )
        if exhausted_parent is not None and need.status in {
            "OPEN",
            "PARTIALLY_COVERED",
            "REOPENED",
        }:
            if need.critical:
                need.status = "EXHAUSTED"
                need.exhausted = True
                need.actionable = False
                need.status_reason = f"dependency_exhausted:{need_key(exhausted_parent)}"
            else:
                state.mark_not_applicable(
                    need,
                    reason=f"dependency_exhausted:{need_key(exhausted_parent)}",
                    turn=turn,
                )
        if need.status == "RESOLVED" and dependency_blockers(
            need, state, strength="HARD"
        ):
            state.reopen_need(
                need, reason="dependency_invalidated", turn=turn
            )


def dependency_snapshot(need: InformationNeed, state: PolicyPilotState) -> dict:
    hard = dependency_blockers(need, state, strength="HARD")
    soft = dependency_blockers(need, state, strength="SOFT")
    return {
        "runnable": not hard,
        "hard_blocked_by": [item.model_dump(mode="json") for item in hard],
        "soft_missing": [item.model_dump(mode="json") for item in soft],
    }


__all__ = [
    "DependencyManager",
    "dependency_blockers",
    "dependency_satisfied",
    "dependency_snapshot",
    "is_need_runnable",
    "need_key",
    "refresh_dependency_state",
    "soft_missing_count",
]
