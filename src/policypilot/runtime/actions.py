"""Decision calls, tool proposal validation, and action audit records."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from policypilot.errors import PolicyPilotErrorType
from policypilot.state import (
    InformationNeed,
    MutationRecord,
    NeedCandidate,
    PolicyPilotState,
    ToolCallRecord,
)
from policypilot.taxonomy import canonicalize_aspect
from policypilot.tool_policy import (
    is_decision_retrieval_tool,
    is_knowledge_tool,
    tool_signature,
)
from tau2.data_model.message import AssistantMessage, Message, ToolCall


class ActionHost(Protocol):
    tools: list[Any]
    llm_args: dict[str, Any]
    config: Any
    budget: Any
    guard: Any
    policy_engine: Any
    llm_runtime: Any

    def _decision_tools(self, state: PolicyPilotState) -> list[Any]: ...


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    error_type: PolicyPilotErrorType = PolicyPilotErrorType.TOOL_VALIDATION
    reason_code: str = "ALLOW"
    details: str | None = None
    proposed_action: dict[str, Any] = field(default_factory=dict)

    @property
    def recoverable_information_gap(self) -> bool:
        return self.reason_code in {"KB_UNBOUND", "MISSING_REQUIRED_ARGUMENT"}


def decision_fallback_candidates(message: AssistantMessage) -> list[NeedCandidate]:
    """Parse the Decision model's explicit missing-information protocol."""
    if message.tool_calls or not message.content:
        return []
    content = message.content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            return []
        content = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or set(payload) != {"missing_information"}:
        return []
    raw_candidates = payload["missing_information"]
    if not isinstance(raw_candidates, list) or not raw_candidates:
        return []
    candidates: list[NeedCandidate] = []
    try:
        for item in raw_candidates[:3]:
            candidate = NeedCandidate.model_validate(item)
            if candidate.criticality != "CRITICAL":
                return []
            candidates.append(
                candidate.model_copy(update={"provenance": "decision_fallback"})
            )
    except Exception:
        return []
    return candidates


def register_decision_fallback(
    host: ActionHost,
    candidates: list[NeedCandidate],
    state: PolicyPilotState,
) -> bool:
    if not candidates:
        return False
    control = state.control
    if (
        control.fallback_need_count
        >= host.config.max_decision_fallback_need_attempts
    ):
        control.recovery_failure_count += 1
        return False
    control.fallback_need_count += 1
    stats = host.need_registry.register_many(
        state, candidates, turn=len(state.messages)
    )
    for need in state.open_needs():
        host.source_resolver.resolve(need)
    host.need_resolver.resolve(state)
    return stats.accepted_count > 0 or stats.deduplicated_count > 0


def tool_call_for_need(
    host: ActionHost, need: InformationNeed, state: PolicyPilotState
) -> ToolCall | None:
    tool = host.guard.tools_by_name.get(need.capability or "")
    if tool is None:
        return None
    arguments = dict(need.tool_arguments)
    for field_name in tool.params.model_fields:
        if field_name in arguments:
            continue
        fact = state.get_fact(field_name, "user") or state.get_fact(field_name)
        if fact:
            arguments[field_name] = fact.value
    try:
        tool.params.model_validate(arguments)
    except Exception:
        return None
    return ToolCall(
        id=f"need_{uuid.uuid4().hex[:12]}",
        name=tool.name,
        arguments=arguments,
        requestor="assistant",
    )


def call_decision(
    host: ActionHost,
    messages: list[Message],
    state: PolicyPilotState,
    call_name: str,
) -> AssistantMessage | None:
    args = dict(host.llm_args)
    args.setdefault("num_retries", 0)
    for attempt in range(host.config.max_llm_retries + 1):
        try:
            response = host.llm_runtime.call_message(
                "decision",
                messages,
                tools=host._decision_tools(state),
                call_name=call_name,
                extra_args=args,
                retry_count=attempt,
            )
            if host.llm_runtime.traces and state.control.current_context_id:
                host.llm_runtime.traces[-1].metadata["context_id"] = (
                    state.control.current_context_id
                )
            if host.config.prompt_cache_metrics_enabled and response.usage:
                control = state.control
                control.prompt_cache_usage_reported = (
                    control.prompt_cache_usage_reported
                    or "prompt_cache_hit_tokens" in response.usage
                    or "prompt_cache_miss_tokens" in response.usage
                )
                control.prompt_cache_hit_tokens += int(
                    response.usage.get("prompt_cache_hit_tokens", 0)
                )
                control.prompt_cache_miss_tokens += int(
                    response.usage.get("prompt_cache_miss_tokens", 0)
                )
            return response
        except Exception as exc:
            retryable = attempt < host.config.max_llm_retries
            state.add_error(
                PolicyPilotErrorType.LLM_TRANSIENT,
                str(exc),
                source="llm",
                retryable=retryable,
                attempts=attempt + 1,
            )
            if not retryable:
                state.control.recovery_failure_count += 1
                return None
            state.control.llm_retry_count += 1
            time.sleep(host.config.llm_retry_base_seconds * (2**attempt))
    return None


def _bind_decision_retrieval(
    host: ActionHost,
    call: ToolCall,
    state: PolicyPilotState,
) -> str | None:
    """Bind a Decision-authored KB lookup without making old coverage a gate."""
    query = str((call.arguments or {}).get("query") or "").strip()
    if not query:
        return None
    target = state.goal.target or "banking_product"
    aspect = canonicalize_aspect(query, entity=target, scope=target) or "product_terms"
    canonical_candidate = NeedCandidate(
        entity=target,
        aspect=aspect,
        scope=target,
        source="POLICY",
        criticality="CRITICAL",
        reason_code="required_action_blocked",
        query_terms=[query],
        provenance="decision_direct",
    )
    semantic_key = host.need_registry.semantic_key(canonical_candidate, state)
    need = next(
        (
            item
            for item in state.information_needs
            if item.semantic_key == semantic_key
        ),
        None,
    )

    binding = "canonical"
    if need is not None and (
        need.retrieval_attempts
        >= host.config.max_retrieval_attempts_per_semantic_need
    ):
        # Prior broad coverage must not prevent a distinct corrective lookup.
        # Give the query its own bounded lifecycle while the task-wide budget
        # remains the ultimate cost limit.
        query_digest = hashlib.sha1(
            " ".join(query.casefold().split()).encode("utf-8")
        ).hexdigest()[:12]
        canonical_candidate = canonical_candidate.model_copy(
            update={
                "query_id": query_digest,
                "query_objective": query,
                "max_attempts": 1,
            }
        )
        semantic_key = host.need_registry.semantic_key(canonical_candidate, state)
        need = next(
            (
                item
                for item in state.information_needs
                if item.semantic_key == semantic_key
            ),
            None,
        )
        binding = "query_scoped"

    if need is None:
        host.need_registry.register_many(
            state, [canonical_candidate], turn=len(state.messages)
        )
        need = next(
            (
                item
                for item in state.information_needs
                if item.semantic_key == semantic_key
            ),
            None,
        )
    if need is None:
        return None

    # Direct Decision retrieval is an explicit signal that prior coverage was
    # insufficient. Reopen the canonical need instead of creating a parallel one.
    need.status = "REOPENED" if need.evidence_refs else "OPEN"
    need.critical = True
    need.blocking = True
    need.actionable = True
    need.exhausted = False
    need.coverage = "PARTIAL" if need.evidence_refs else None
    need.resolved_by_fact_id = None
    need.resolved_at = None
    need.reason = "decision_requested_retrieval"
    need.status_reason = "decision_identified_evidence_gap"
    need.query_terms = list(dict.fromkeys([*need.query_terms, query]))[-4:]
    need.updated_turn = len(state.messages)
    need.retrieval_attempts += 1
    need.acquisition_count += 1
    state.control.retrieval_events.append(
        {
            "turn": len(state.messages),
            "tool_call_id": call.id,
            "need_id": need.id,
            "semantic_need_key": need.semantic_key,
            "entity": need.entity,
            "aspect": need.aspect,
            "aspect_provenance": need.aspect_provenance,
            "scope": need.scope,
            "source": "POLICY",
            "status": "REQUESTED",
            "attempt": need.retrieval_attempts,
            "query": query,
            "candidate_documents": [],
            "coverage": None,
            "matched_need_ids": [],
            "partial_need_ids": [],
            "why_again": "Decision identified insufficient policy evidence",
            "origin": "decision",
            "binding": binding,
        }
    )
    state.control.retrieval_query_history.append(
        {"turn": len(state.messages), "need_id": need.id, "query": query}
    )
    return need.id


def _normalized_retrieval_query(call: ToolCall) -> str:
    query = str((call.arguments or {}).get("query") or "")
    return " ".join(query.casefold().split())


def _is_repeated_decision_query(call: ToolCall, state: PolicyPilotState) -> bool:
    normalized = _normalized_retrieval_query(call)
    return bool(normalized) and any(
        " ".join(str(item.get("query") or "").casefold().split()) == normalized
        for item in state.control.retrieval_query_history
    )


def validate_proposal(
    host: ActionHost, message: AssistantMessage, state: PolicyPilotState
) -> ValidationResult:
    if (
        len(message.tool_calls or []) > 1
        and all(
            is_decision_retrieval_tool(call.name)
            for call in message.tool_calls or []
        )
    ):
        # Keep Decision retrieval sequential so each new query can use the
        # evidence returned by the previous one and budgets remain predictable.
        message.tool_calls = [message.tool_calls[0]]
    proposed_action = message.model_dump(mode="json", exclude_none=True)
    if not message.tool_calls:
        error = host.policy_engine.check(message, state)
        return ValidationResult(
            allowed=error is None,
            reason_code="ALLOW" if error is None else "POLICY_REJECTED",
            details=error,
            proposed_action=proposed_action,
        )
    control = state.control
    if control.tool_call_count + len(message.tool_calls) > host.budget.max_tool_calls:
        return ValidationResult(
            allowed=False,
            error_type=PolicyPilotErrorType.MAX_TOOL_EXHAUSTION,
            reason_code="BUDGET_EXHAUSTED",
            details="Tool budget exceeded.",
            proposed_action=proposed_action,
        )
    proposed_retrievals = sum(
        is_knowledge_tool(call.name) for call in message.tool_calls
    )
    total_retrievals = sum(
        is_knowledge_tool(record.name) and not record.blocked
        for record in state.tool_history
    )
    if total_retrievals + proposed_retrievals > host.config.max_goal_retrieval_calls:
        return ValidationResult(
            allowed=False,
            reason_code="BUDGET_EXHAUSTED",
            details="Knowledge retrieval budget for the current goal is exhausted.",
            proposed_action=proposed_action,
        )
    for call in message.tool_calls:
        if call.name not in host.guard.tools_by_name:
            return ValidationResult(
                allowed=False,
                reason_code="UNAUTHORIZED_TOOL",
                details=f"Unknown tool '{call.name}'.",
                proposed_action=proposed_action,
            )
        error = host.guard.validate_tool_call(call)
        if error:
            tool = host.guard.tools_by_name.get(call.name)
            missing = []
            if tool is not None and isinstance(call.arguments, dict):
                missing = [
                    name
                    for name, field_info in tool.params.model_fields.items()
                    if field_info.is_required() and name not in call.arguments
                ]
            return ValidationResult(
                allowed=False,
                reason_code=(
                    "MISSING_REQUIRED_ARGUMENT" if missing else "SCHEMA_ERROR"
                ),
                details=error,
                proposed_action={**proposed_action, "missing_fields": missing},
            )
    for call in message.tool_calls:
        if is_knowledge_tool(call.name) and not any(
            item.get("tool_call_id") == call.id and item.get("status") == "REQUESTED"
            for item in state.control.retrieval_events
        ):
            direct_allowed = host.config.decision_knowledge_tools_enabled and (
                is_decision_retrieval_tool(call.name)
            )
            if not direct_allowed:
                return ValidationResult(
                    allowed=False,
                    reason_code="KB_UNBOUND",
                    details=(
                        "Knowledge lookup must originate from an unresolved "
                        "registered policy need or an authorized Decision lookup."
                    ),
                    proposed_action=proposed_action,
                )
            if _is_repeated_decision_query(call, state):
                control.duplicate_call_count += 1
                return ValidationResult(
                    allowed=False,
                    error_type=PolicyPilotErrorType.DUPLICATE_TOOL_CALL,
                    reason_code="DUPLICATE_RETRIEVAL_QUERY",
                    details="Repeated Decision knowledge query blocked.",
                    proposed_action=proposed_action,
                )
            # Binding is provenance and budgeting metadata, not permission for
            # a read-only lookup. A full Need registry must not become a safety
            # denial for an otherwise valid Decision query.
            _bind_decision_retrieval(host, call, state)
        classification = host.guard.classify(call.name)
        signature = tool_signature(call.name, call.arguments)
        if classification == "mutation":
            prior = next(
                (
                    item
                    for item in reversed(state.mutations)
                    if item.signature == signature
                    and item.status in {"SENT", "CONFIRMED", "UNKNOWN"}
                ),
                None,
            )
            if prior is not None:
                control.duplicate_call_count += 1
                return ValidationResult(
                    allowed=False,
                    error_type=PolicyPilotErrorType.DUPLICATE_TOOL_CALL,
                    reason_code="DUPLICATE_MUTATION",
                    details=(
                        "Mutation with the same idempotency signature is already "
                        f"{prior.status.lower()}."
                    ),
                    proposed_action=proposed_action,
                )
        if control.signature_versions.get(signature) == control.observation_version:
            control.duplicate_call_count += 1
            return ValidationResult(
                allowed=False,
                error_type=PolicyPilotErrorType.DUPLICATE_TOOL_CALL,
                reason_code="DUPLICATE",
                details="Duplicate tool call blocked.",
                proposed_action=proposed_action,
            )
        if classification == "transaction_read" and not any(
            need.status == "OPEN"
            and need.source == "TOOL"
            and need.capability == call.name
            and all(call.arguments.get(key) == value for key, value in need.tool_arguments.items())
            for need in state.information_needs
        ):
            return ValidationResult(
                allowed=False,
                reason_code="UNAUTHORIZED_TOOL",
                details="Transactional reads must originate from an unresolved registered tool need.",
                proposed_action=proposed_action,
            )
        if classification == "mutation" and call.name not in {
            tool.name for tool in host._decision_tools(state)
        }:
            return ValidationResult(
                allowed=False,
                reason_code="UNAUTHORIZED_TOOL",
                details="Mutation preconditions are not satisfied for this decision.",
                proposed_action=proposed_action,
            )
        if classification == "mutation" and control.mutation_verification_required:
            return ValidationResult(
                allowed=False,
                error_type=PolicyPilotErrorType.MUTATION_UNCERTAIN,
                reason_code="MUTATION_REQUIRES_READ",
                details="Mutation blocked pending read verification.",
                proposed_action=proposed_action,
            )
    return ValidationResult(allowed=True, proposed_action=proposed_action)


def proposal_error(
    host: ActionHost, message: AssistantMessage, state: PolicyPilotState
) -> tuple[str | None, PolicyPilotErrorType]:
    """Compatibility adapter for acquisition nodes and existing integrations."""
    result = validate_proposal(host, message, state)
    return result.details, result.error_type


def record_valid_tool_calls(
    host: ActionHost,
    message: AssistantMessage,
    state: PolicyPilotState,
    need_id: str | None = None,
) -> None:
    control = state.control
    for call in message.tool_calls or []:
        bound_need_id = need_id
        if bound_need_id is None and is_knowledge_tool(call.name):
            event = next(
                (
                    item
                    for item in reversed(control.retrieval_events)
                    if item.get("tool_call_id") == call.id
                ),
                None,
            )
            bound_need_id = event.get("need_id") if event else None
        signature = tool_signature(call.name, call.arguments)
        classification = host.guard.classify(call.name)
        state.tool_history.append(
            ToolCallRecord(
                name=call.name,
                arguments=call.arguments,
                signature=signature,
                turn_index=len(state.messages),
                tool_call_id=call.id,
                classification=classification,
                need_id=bound_need_id,
            )
        )
        control.signature_versions[signature] = control.observation_version
        control.tool_call_count += 1
        bound_need = next(
            (
                item
                for item in state.information_needs
                if item.id == bound_need_id
            ),
            None,
        )
        if bound_need is not None and not is_knowledge_tool(call.name):
            bound_need.acquisition_count += 1
        control.acquisition_events.append(
            {
                "turn": len(state.messages),
                "tool_call_id": call.id,
                "need_id": bound_need_id,
                "semantic_key": bound_need.semantic_key if bound_need else None,
                "source": bound_need.source if bound_need else "DECISION",
                "acquisition_type": classification,
                "status": "REQUESTED",
                "result": None,
                "final_status": bound_need.status if bound_need else None,
            }
        )
        if classification == "mutation":
            idempotency_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()
            state.mutations.append(
                MutationRecord(
                    mutation_id=f"mutation_{uuid.uuid4().hex}",
                    idempotency_key=idempotency_key,
                    tool_name=call.name,
                    arguments=dict(call.arguments),
                    signature=signature,
                    tool_call_id=call.id,
                    status="SENT",
                    planned_turn=len(state.messages),
                    updated_turn=len(state.messages),
                )
            )
            control.last_mutation_version = control.observation_version
        if is_knowledge_tool(call.name):
            control.goal_retrieval_call_count += 1
            control.last_retrieval_query = str(call.arguments.get("query", ""))
            if control.pending_retrieval_rewrite:
                control.pending_retrieval_rewrite = False
                control.retrieval_rewrite_count += 1


def record_blocked_tool_calls(
    host: ActionHost, message: AssistantMessage, state: PolicyPilotState
) -> None:
    for call in message.tool_calls or []:
        state.tool_history.append(
            ToolCallRecord(
                name=call.name,
                arguments=call.arguments,
                signature=tool_signature(call.name, call.arguments),
                turn_index=len(state.messages),
                tool_call_id=call.id,
                classification=host.guard.classify(call.name),
                blocked=True,
            )
        )
