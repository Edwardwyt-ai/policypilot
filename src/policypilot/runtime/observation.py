"""Observation ingestion and deterministic state transitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from policypilot.errors import PolicyPilotErrorType
from policypilot.evidence import make_tool_evidence, make_user_evidence
from policypilot.needs import attach_tool_fact_metadata, invalidate_tool_facts
from policypilot.planning import (
    deterministic_semantic_plan,
    merge_semantic_plan,
    planner_trigger_reason,
)
from policypilot.provenance import record_payload
from policypilot.state import NeedCandidate, PolicyPilotState
from policypilot.state_updates import (
    classify_intent,
    resolve_user_needs,
    seed_information_need_candidates,
    update_facts_from_tool_evidence,
    update_facts_from_user_message,
)
from policypilot.tool_policy import is_knowledge_tool
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)


@dataclass(frozen=True)
class ObservationOutcome:
    tool_call: ToolCall | None = None
    classification: str = "unknown"
    failed: bool = False
    retrieval_empty: bool = False
    mutation_uncertain: bool = False


class ObservationHost(Protocol):
    config: Any
    llm_runtime: Any
    semantic_planner: Any
    acquisition_planner: Any
    need_registry: Any
    source_resolver: Any
    need_resolver: Any
    evidence_resolver: Any
    guard: Any
    memory: Any
    skills: Any

    def _skill_guidance(self, phase: str, state: PolicyPilotState) -> str: ...


def _read_result_is_conclusive(content: str) -> bool:
    """Distinguish a successful transport response from a useful business result."""

    normalized = " ".join(content.casefold().split())
    if not normalized or any(
        marker in normalized
        for marker in (
            "not found",
            "no records",
            "no results",
            "permission denied",
            "unauthorized",
            "access denied",
            "unable to locate",
        )
    ):
        return False
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return True
    if payload in (None, [], {}):
        return False
    if isinstance(payload, dict):
        status = str(payload.get("status", "")).casefold()
        if status in {"error", "failed", "not_found", "denied"}:
            return False
        if payload.get("success") is False:
            return False
    return True


def activate_recovery_skill(
    host: ObservationHost,
    outcomes: list[ObservationOutcome],
    state: PolicyPilotState,
) -> None:
    if not host.config.skills_enabled:
        return
    outcome = outcomes[0] if len(outcomes) == 1 else None
    mode = (
        "uncertain_mutation"
        if outcome and outcome.mutation_uncertain
        else "retrieval_empty"
        if outcome and outcome.retrieval_empty
        else "tool_execution"
        if outcome and outcome.failed
        else "recovery"
    )
    if mode != host.skills.last_recovery_mode:
        host.skills.refresh(state, event="RECOVERY_MODE_CHANGE", recovery_mode=mode)
    if host.memory is not None:
        host.memory.recall(state.goal.objective or "", trigger="RECOVERY_ENTERED")


def bind_memory_from_state(host: ObservationHost, state: PolicyPilotState) -> None:
    if host.memory is None:
        return
    identity = state.get_fact("user_id", "user") or state.get_fact("user_id")
    if (
        identity is not None
        and isinstance(identity.value, str)
        and identity.verified
        and host.memory.user_id is None
    ):
        host.memory.bind(identity.value, query=state.goal.objective or "")


def observe(
    host: ObservationHost, message: Message, state: PolicyPilotState
) -> list[ObservationOutcome]:
    progress_before = state.progress_signature()
    if isinstance(message, MultiToolMessage):
        outcomes = []
        for item in message.tool_messages:
            state.messages.append(item)
            outcomes.append(observe_tool_message(host, item, state))
        state.record_progress(progress_before, turn=len(state.messages))
        return outcomes
    state.messages.append(message)
    if isinstance(message, UserMessage):
        turn = len(state.messages) - 1
        payload = record_payload(
            state,
            source_type="USER",
            raw_content=message.content or "",
        )
        user_evidence = make_user_evidence(
            message.content or "",
            turn,
            event_id=payload.event_id,
            payload_ref=payload.payload_id,
        )
        previous_goal = (state.goal.objective, state.goal.target)
        trigger_reason = planner_trigger_reason(state, message.content or "")
        update_facts_from_user_message(
            state, message.content or "", turn, user_evidence.evidence_id
        )
        state.evidence.append(user_evidence)
        bind_memory_from_state(host, state)
        memory_hints = host.memory.planner_hints() if host.memory is not None else []
        plan = deterministic_semantic_plan(
            state,
            message.content or "",
            turn,
            classify_intent(message.content or ""),
            memory_hints=memory_hints,
        )
        candidates = merge_semantic_plan(state, plan, turn)
        skill_event = None
        if previous_goal != (state.goal.objective, state.goal.target):
            skill_event = (
                "NEW_GOAL" if previous_goal[0] is None else "MAJOR_SUBGOAL_CHANGE"
            )
        if host.config.skills_enabled and skill_event:
            host.skills.refresh(state, event=skill_event)
        planner_called = False
        planner_succeeded = False
        if host.config.semantic_planner_enabled and trigger_reason:
            planner_called = True
            trace_start = len(host.llm_runtime.traces)
            try:
                semantic_plan = host.semantic_planner.plan(
                    state,
                    message.content or "",
                    turn,
                    skill_guidance=host._skill_guidance("planning", state),
                    trigger_reason=trigger_reason,
                    memory_hints=memory_hints,
                )
                candidates.extend(merge_semantic_plan(state, semantic_plan, turn))
                planner_succeeded = True
            except Exception as exc:
                state.add_error(
                    PolicyPilotErrorType.LLM_TRANSIENT,
                    f"Semantic Planner validation failed: {exc}",
                    source="semantic_planner",
                )
                state.control.recovery_failure_count += 1
            planner_traces = host.llm_runtime.traces[trace_start:]
        else:
            planner_traces = []
        state.control.planner_events.append(
            {
                "turn": turn,
                "called": planner_called,
                "succeeded": planner_succeeded,
                "trigger_reason": trigger_reason,
                "candidate_count": len(candidates),
                "input_tokens": sum(item.input_tokens for item in planner_traces),
                "output_tokens": sum(item.output_tokens for item in planner_traces),
            }
        )
        if host.memory is not None:
            task_context = (
                f"objective={state.goal.objective or ''}; "
                f"target={state.goal.target or ''}; intent={state.intent}"
            )
            host.memory.observe_user(message.content or "", task_context)
            if skill_event:
                host.memory.recall(
                    state.goal.objective or "", trigger=skill_event
                )
        candidates.extend(
            seed_information_need_candidates(
                state, {item.name for item in host.source_resolver.capabilities}
            )
        )
        candidates = host.acquisition_planner.plan(state, candidates, turn=turn)
        host.need_registry.register_many(state, candidates, turn=turn)
        resolve_user_needs(state)
        for need in state.open_needs():
            host.source_resolver.resolve(need)
        host.need_resolver.resolve(state)
        state.note_successful_observation()
        if previous_goal != (state.goal.objective, state.goal.target):
            state.control.pending_retrieval_rewrite = False
            state.control.retrieval_recovery_exhausted = False
            state.control.last_retrieval_query = None
            state.control.goal_retrieval_call_count = 0
            state.control.retrieval_query_history.clear()
            state.control.fallback_need_count = 0
        state.record_progress(progress_before, turn=turn)
        return []
    if isinstance(message, ToolMessage):
        outcome = observe_tool_message(host, message, state)
        state.record_progress(progress_before, turn=len(state.messages))
        return [outcome]
    state.record_progress(progress_before, turn=len(state.messages))
    return []


def observe_tool_message(
    host: ObservationHost, message: ToolMessage, state: PolicyPilotState
) -> ObservationOutcome:
    matched = find_tool_call(message.id, state)
    name = matched.name if matched else "unknown"
    args = matched.arguments if matched else {}
    classification = host.guard.classify(name)
    retrieval = is_knowledge_tool(name)
    runtime_metadata = host.guard.metadata(name)
    content = message.content or ""
    payload = record_payload(
        state,
        source_type="TOOL",
        raw_content=content,
        tool_call_id=message.id,
    )
    empty = retrieval and "no relevant documents found" in content.lower()
    failed = bool(message.error)
    uncertain = failed and classification == "mutation"
    mutation_record = next(
        (
            item
            for item in reversed(state.mutations)
            if item.tool_call_id == message.id
        ),
        None,
    )
    evidence = make_tool_evidence(
        tool_name=name,
        tool_args=args,
        tool_call_id=message.id,
        content=content,
        turn_index=len(state.messages),
        is_retrieval=retrieval,
        error=failed,
        event_id=payload.event_id,
        payload_ref=payload.payload_id,
        focus=" ".join(
            [
                state.goal.objective or "",
                state.goal.target or "",
                *(need.reason for need in state.open_needs()),
            ]
        ),
    )
    state.evidence.append(evidence)
    update_tool_record(message.id, evidence.summary, failed, state)
    acquisition = next(
        (
            item
            for item in reversed(state.control.acquisition_events)
            if item.get("tool_call_id") == message.id
        ),
        None,
    )
    if acquisition is not None:
        acquisition.update(
            {
                "result": evidence.summary[:500],
                "result_type": evidence.source_type,
                "error": failed,
                "status": "FAILED" if failed else "COMPLETED",
            }
        )
    if failed or empty:
        if empty:
            state.control.retrieval_miss_count += 1
            state.control.pending_retrieval_rewrite = (
                state.control.retrieval_rewrite_count
                < host.config.max_retrieval_rewrite_attempts
            )
            state.control.retrieval_recovery_exhausted = (
                not state.control.pending_retrieval_rewrite
            )
        if uncertain:
            if mutation_record is not None:
                mutation_record.status = "UNKNOWN"
                mutation_record.updated_turn = len(state.messages)
                mutation_record.details = "Tool result was ambiguous or failed."
            state.control.mutation_verification_required = True
            state.control.unsafe_to_retry = True
            invalidate_tool_facts(state, runtime_metadata.invalidates)
            ensure_mutation_verification_need(
                host, name, args, state, runtime_metadata.invalidates
            )
        category = (
            PolicyPilotErrorType.RETRIEVAL_EMPTY
            if empty
            else PolicyPilotErrorType.MUTATION_UNCERTAIN
            if uncertain
            else PolicyPilotErrorType.TOOL_EXECUTION_ERROR
        )
        state.add_error(
            category,
            evidence.summary,
            source=name,
            retryable=not uncertain,
            unsafe_to_retry=uncertain,
        )
    else:
        state.note_successful_observation()
        if classification == "mutation":
            if mutation_record is not None:
                mutation_record.status = "CONFIRMED"
                mutation_record.updated_turn = len(state.messages)
                mutation_record.details = "Environment returned a successful result."
            invalidate_tool_facts(state, runtime_metadata.invalidates)
        elif classification != "transaction_read" or _read_result_is_conclusive(content):
            update_facts_from_tool_evidence(state, evidence, raw_content=content)
            attach_tool_fact_metadata(
                state,
                evidence_ref=message.id,
                resource_tags=runtime_metadata.resource_tags,
            )
        bind_memory_from_state(host, state)
        need_id = next(
            (
                record.need_id
                for record in reversed(state.tool_history)
                if record.tool_call_id == message.id
            ),
            None,
        )
        if need_id:
            need = next(
                (item for item in state.information_needs if item.id == need_id), None
            )
            if need:
                need.evidence_refs.append(message.id)
                if retrieval:
                    resolution = host.evidence_resolver.resolve(
                        state, evidence, trigger_need_id=need.id
                    )
                    event = next(
                        (
                            item
                            for item in reversed(state.control.retrieval_events)
                            if item.get("tool_call_id") == message.id
                            or item.get("need_id") == need.id
                            and item.get("status") == "REQUESTED"
                        ),
                        None,
                    )
                    if event is not None:
                        event.update(resolution)
                        event["status"] = (
                            "RESOLVED" if need.status == "RESOLVED" else "OPEN"
                        )
                        event["candidate_documents"] = [
                            ref.document_id for ref in evidence.policy_refs
                        ]
                    if acquisition is not None:
                        acquisition["coverage"] = resolution["coverage"]
                        acquisition["final_status"] = need.status
                if classification == "transaction_read" and need.source == "TOOL":
                    if need.purpose == "VERIFICATION":
                        status = apply_mutation_readback(state, message.id, content)
                        if status in {"CONFIRMED", "FAILED"}:
                            if need.status != "RESOLVED":
                                fully_resolved = state.resolve_need(
                                    need, evidence_refs=[message.id]
                                )
                                if fully_resolved:
                                    state.control.needs_resolved_count += 1
                            state.control.mutation_verification_required = False
                            state.control.unsafe_to_retry = False
                            state.resolve_latest_error(
                                PolicyPilotErrorType.MUTATION_UNCERTAIN
                            )
                    elif need.status != "RESOLVED" and _read_result_is_conclusive(content):
                        fully_resolved = state.resolve_need(
                            need, evidence_refs=[message.id]
                        )
                        if fully_resolved:
                            state.control.needs_resolved_count += 1
                if acquisition is not None:
                    acquisition["final_status"] = need.status
        if not retrieval:
            generated = seed_information_need_candidates(
                state, {item.name for item in host.source_resolver.capabilities}
            )
            host.need_registry.register_many(state, generated, turn=len(state.messages))
            resolve_user_needs(state)
        host.need_resolver.resolve(state)
        if host.config.skills_enabled and host.skills.last_recovery_mode is not None:
            host.skills.refresh(state, event="RECOVERY_MODE_CHANGE", recovery_mode=None)
    return ObservationOutcome(matched, classification, failed, empty, uncertain)


def apply_mutation_readback(
    state: PolicyPilotState, readback_tool_call_id: str, content: str
) -> str:
    """Conservatively classify an authoritative read-back without guessing."""
    record = next(
        (item for item in reversed(state.mutations) if item.status == "UNKNOWN"),
        None,
    )
    if record is None:
        return "UNKNOWN"
    lowered = content.lower()
    affirmative = False
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            affirmative = any(
                key.lower() in {"status", "state", "result"}
                and str(value).lower()
                in {"updated", "applied", "completed", "confirmed", "success"}
                for key, value in parsed.items()
            )
    except (TypeError, ValueError):
        pass
    effect_values = [
        str(value).lower()
        for key, value in record.arguments.items()
        if not key.lower().endswith("_id") and key.lower() != "id"
    ]
    if affirmative or effect_values and all(value in lowered for value in effect_values):
        status = "CONFIRMED"
        details = "Authoritative read-back contains every requested effect value."
    elif any(
        marker in lowered
        for marker in ("not executed", "not applied", "unchanged", "no change")
    ):
        status = "FAILED"
        details = "Authoritative read-back explicitly reports no applied change."
    else:
        status = "UNKNOWN"
        details = "Authoritative read-back did not prove whether the mutation applied."
    record.status = status
    record.updated_turn = len(state.messages)
    record.readback_tool_call_id = readback_tool_call_id
    record.details = details
    return status


def ensure_mutation_verification_need(
    host: ObservationHost,
    mutation_name: str,
    mutation_arguments: dict[str, Any],
    state: PolicyPilotState,
    invalidated_tags,
) -> None:
    tags = set(invalidated_tags)
    reads = sorted(
        (
            capability
            for capability in host.source_resolver.capabilities
            if capability.classification == "transaction_read"
            and tags.intersection(capability.resource_tags)
        ),
        key=lambda capability: (
            -len(tags.intersection(capability.resource_tags)),
            capability.name,
        ),
    )
    if not reads:
        return
    capability = reads[0]
    arguments = {
        key: value
        for key, value in mutation_arguments.items()
        if key in capability.fields
    }
    host.need_registry.register_many(
        state,
        [
            NeedCandidate(
                entity=mutation_name,
                aspect="mutation_outcome",
                source="TOOL",
                criticality="CRITICAL",
                reason_code="authoritative_precondition",
                capability=capability.name,
                tool_arguments=arguments,
                purpose="VERIFICATION",
            )
        ],
        turn=len(state.messages),
    )


def find_tool_call(call_id: str, state: PolicyPilotState) -> ToolCall | None:
    for prior in reversed(state.messages):
        if isinstance(prior, AssistantMessage):
            for call in prior.tool_calls or []:
                if call.id == call_id:
                    return call
    return None


def update_tool_record(
    call_id: str, summary: str, error: bool, state: PolicyPilotState
) -> None:
    for record in reversed(state.tool_history):
        if record.tool_call_id == call_id:
            record.result_summary = summary
            record.error = error
            return
