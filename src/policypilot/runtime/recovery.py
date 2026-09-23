"""Bounded recovery and task budget behavior."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from policypilot.runtime.actions import ValidationResult
from policypilot.runtime.observation import ObservationOutcome
from policypilot.state import NeedCandidate, PolicyPilotState
from policypilot.taxonomy import canonicalize_aspect
from policypilot.tool_policy import tool_signature
from tau2.data_model.message import AssistantMessage


class RecoveryHost(Protocol):
    config: Any
    budget: Any
    need_registry: Any
    source_resolver: Any
    need_resolver: Any

    def _record_valid_tool_calls(
        self,
        message: AssistantMessage,
        state: PolicyPilotState,
        need_id: str | None = None,
    ) -> None: ...


def recover_validation_failure(
    host: RecoveryHost,
    result: ValidationResult,
    state: PolicyPilotState,
) -> bool:
    """Translate recoverable Guard failures into candidates for NeedManager."""
    control = state.control
    if not result.recoverable_information_gap:
        return False
    if control.guard_recovery_attempts >= host.config.max_guard_recovery_attempts:
        control.recovery_failure_count += 1
        return False

    candidates: list[NeedCandidate] = []
    calls = result.proposed_action.get("tool_calls") or []
    if result.reason_code == "KB_UNBOUND":
        for call in calls[:1]:
            arguments = call.get("arguments") or {}
            query = str(arguments.get("query") or "").strip()
            target = state.goal.target or "banking_product"
            aspect = canonicalize_aspect(
                query, entity=target, scope=target
            ) or "product_terms"
            candidates.append(
                NeedCandidate(
                    entity=target,
                    aspect=aspect,
                    scope=target,
                    source="POLICY",
                    criticality="CRITICAL",
                    reason_code="required_action_blocked",
                    query_terms=[query] if query else [],
                    provenance="guard_recovery",
                )
            )
    elif result.reason_code == "MISSING_REQUIRED_ARGUMENT":
        for field_name in result.proposed_action.get("missing_fields") or []:
            label = str(field_name).replace("_", " ")
            candidates.append(
                NeedCandidate(
                    entity="user",
                    aspect=str(field_name),
                    source="USER",
                    criticality="CRITICAL",
                    reason_code="required_action_blocked",
                    question=f"Please provide the missing {label}.",
                    provenance="guard_recovery",
                )
            )
    elif result.reason_code == "UNVERIFIED_ARGUMENT":
        proposed_values = {
            key: value
            for call in calls[:1]
            for key, value in (call.get("arguments") or {}).items()
        }
        for field_name in result.proposed_action.get("missing_fields") or []:
            capability = next(
                (
                    item
                    for item in host.source_resolver.capabilities
                    if item.classification == "transaction_read"
                    and field_name in item.fields
                ),
                None,
            )
            if capability is None or field_name not in proposed_values:
                continue
            candidates.append(
                NeedCandidate(
                    entity="user",
                    aspect=str(field_name),
                    source="TOOL",
                    capability=capability.name,
                    tool_arguments={field_name: proposed_values[field_name]},
                    criticality="CRITICAL",
                    reason_code="authoritative_precondition",
                    purpose="PRE_MUTATION",
                    provenance="guard_recovery",
                )
            )
    if not candidates:
        return False

    control.guard_recovery_attempts += 1
    stats = host.need_registry.register_many(
        state, candidates, turn=len(state.messages)
    )
    for need in state.open_needs():
        host.source_resolver.resolve(need)
    host.need_resolver.resolve(state)
    recovered = stats.accepted_count > 0 or stats.deduplicated_count > 0
    if recovered:
        control.recovery_success_count += 1
    else:
        control.recovery_failure_count += 1
    return recovered


def recover_read_failure(
    host: RecoveryHost,
    outcomes: list[ObservationOutcome],
    state: PolicyPilotState,
) -> AssistantMessage | None:
    if len(outcomes) != 1:
        return None
    outcome = outcomes[0]
    if (
        not outcome.failed
        or outcome.classification != "transaction_read"
        or not outcome.tool_call
    ):
        return None
    signature = tool_signature(outcome.tool_call.name, outcome.tool_call.arguments)
    control = state.control
    attempts = control.tool_retry_attempts.get(signature, 0)
    original_need_id = next(
        (
            record.need_id
            for record in reversed(state.tool_history)
            if record.tool_call_id == outcome.tool_call.id
        ),
        None,
    )
    if attempts >= host.config.max_read_tool_retries:
        control.recovery_failure_count += 1
        need = next(
            (
                item
                for item in state.information_needs
                if item.id == original_need_id
            ),
            None,
        )
        if need is not None:
            need.status = "EXHAUSTED"
            need.exhausted = True
            need.blocking = need.critical
            need.actionable = False
            need.status_reason = "read_retry_limit_reached"
        return None
    call = outcome.tool_call.model_copy(
        update={"id": f"recovery_{uuid.uuid4().hex[:12]}"}
    )
    control.tool_retry_attempts[signature] = attempts + 1
    control.tool_retry_count += 1
    message = AssistantMessage(role="assistant", tool_calls=[call])
    host._record_valid_tool_calls(message, state, original_need_id)
    return message


def budget_exhaustion_message(
    host: RecoveryHost, state: PolicyPilotState
) -> AssistantMessage | None:
    control = state.control
    if control.step_count > host.budget.max_agent_steps:
        return AssistantMessage.text(
            "I cannot safely continue because the step budget has been exhausted."
        )
    if control.consecutive_error_count >= host.budget.max_consecutive_errors:
        return AssistantMessage.text(
            "I cannot safely continue because repeated errors prevented a reliable result."
        )
    return None
