"""Central mutation authorization, lifecycle, and read-back verification."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from policypilot.state import (
    ActionAuthorization,
    MutationRecord,
    MutationStatus,
    MutationTransition,
    PolicyPilotState,
)

_ACTION_PATTERNS = {
    "activate": r"\bactivate\b|激活",
    "apply": r"\bapply\b|申请",
    "cancel": r"\bcancel\b|取消",
    "change": r"\b(?:change|update|set|edit|modify)\b|修改|更改|更新",
    "close": r"\bclose\b|关闭|销户",
    "create": r"\b(?:create|open)\b|创建|开通|开户",
    "dispute": r"\bdispute\b|争议|拒付",
    "freeze": r"\b(?:freeze|lock|block)\b|冻结|锁定",
    "pay": r"\b(?:pay|payment)\b|支付|还款",
    "replace": r"\breplace\b|补卡|换卡",
    "retry": r"\b(?:retry|resubmit)\b|重试|重新提交",
    "submit": r"\b(?:submit|confirm|proceed|log|record|verify)\b|提交|确认|记录|验证|继续办理",
    "transfer": r"\b(?:transfer|send)\b|转账|汇款",
}
_TOOL_ACTION_ALIASES = {
    "set": "change",
    "update": "change",
    "edit": "change",
    "modify": "change",
    "open": "create",
    "resubmit": "retry",
    "send": "transfer",
    "confirm": "submit",
    "log": "submit",
}
_GENERIC_TOOL_TERMS = {
    "mutate", "mutation", "account", "card", "customer", "transaction",
    "verification", "details", "record",
}
_SENSITIVE_ARGUMENT = re.compile(
    r"(^|_)(amount|quantity|limit|destination|recipient|beneficiary|target|to_account|new)(_|$)",
    re.I,
)
_NEGATIVE_READBACK = ("not executed", "not applied", "unchanged", "no change")
_POSITIVE_STATUSES = {"updated", "applied", "completed", "confirmed", "success", "succeeded"}
_TRANSITIONS: dict[MutationStatus, set[MutationStatus]] = {
    "PLANNED": {"SENT", "FAILED"},
    "SENT": {"CONFIRMED", "UNKNOWN", "FAILED"},
    "UNKNOWN": {"CONFIRMED", "FAILED"},
    "CONFIRMED": set(),
    "FAILED": set(),
}


def _normalized(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return format(value, "g")
    return " ".join(str(value).casefold().split())


def _action_terms(text: str) -> list[str]:
    return sorted(
        name for name, pattern in _ACTION_PATTERNS.items() if re.search(pattern, text, re.I)
    )


def _authorized_values(text: str) -> list[str]:
    values = set(re.findall(r"(?<!\w)[+-]?(?:\d[\d,]*)(?:\.\d+)?(?!\w)", text))
    values.update(re.findall(r"\b[a-z0-9]+(?:[-_][a-z0-9]+)+\b", text.casefold()))
    return sorted(value.replace(",", "") for value in values)


def capture_action_authorization(
    state: PolicyPilotState,
    *,
    content: str,
    turn: int,
    evidence_ref: str | None,
    explicit: bool,
) -> ActionAuthorization | None:
    """Record an explicit user command without treating it as execution proof."""

    if not explicit:
        return None
    existing = next(
        (item for item in state.action_authorizations if item.source_turn == turn), None
    )
    if existing is not None:
        return existing
    authorization = ActionAuthorization(
        authorization_id=f"authorization_{uuid.uuid4().hex}",
        source_turn=turn,
        evidence_ref=evidence_ref,
        utterance=" ".join(content.split())[:1000],
        action_terms=_action_terms(content),
        authorized_values=_authorized_values(content),
        expires_turn=turn + 8,
    )
    state.action_authorizations.append(authorization)
    state.action_authorizations = state.action_authorizations[-12:]
    return authorization


def authorization_matches_tool(
    authorization: ActionAuthorization, tool_name: str, *, turn: int
) -> bool:
    if (
        authorization.revoked
        or authorization.consumed_by_mutation_id is not None
        or turn > authorization.expires_turn
    ):
        return False
    if authorization.bound_tool_name is not None:
        return authorization.bound_tool_name == tool_name
    tool_terms = {
        _TOOL_ACTION_ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9]+", tool_name.casefold())
        if token not in _GENERIC_TOOL_TERMS
    }
    if not tool_terms:
        return True
    return bool(tool_terms.intersection(authorization.action_terms))


def find_active_authorization(
    state: PolicyPilotState, tool_name: str, *, turn: int | None = None
) -> ActionAuthorization | None:
    current_turn = len(state.messages) if turn is None else turn
    return next(
        (
            item
            for item in reversed(state.action_authorizations)
            if authorization_matches_tool(item, tool_name, turn=current_turn)
        ),
        None,
    )


def operation_fingerprint(signature: str) -> str:
    """Return an Agent-side audit fingerprint, not a server idempotency token."""

    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MutationValidationIssue:
    reason_code: str
    details: str


class MutationManager:
    """Own every legal mutation-state transition inside PolicyPilot."""

    @staticmethod
    def validate(
        state: PolicyPilotState,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        signature: str,
    ) -> MutationValidationIssue | None:
        duplicate = MutationManager.validate_duplicate(state, signature=signature)
        if duplicate is not None:
            return duplicate
        return MutationManager.validate_authorization(
            state,
            tool_name=tool_name,
            arguments=arguments,
        )

    @staticmethod
    def validate_duplicate(
        state: PolicyPilotState, *, signature: str
    ) -> MutationValidationIssue | None:
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
            return MutationValidationIssue(
                "DUPLICATE_MUTATION",
                "Mutation with the same operation fingerprint is already "
                f"{prior.status.lower()}.",
            )
        return None

    @staticmethod
    def validate_authorization(
        state: PolicyPilotState,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MutationValidationIssue | None:
        authorization = find_active_authorization(state, tool_name)
        if authorization is None:
            return MutationValidationIssue(
                "MISSING_ACTION_AUTHORIZATION",
                "No unconsumed explicit user authorization matches this mutation.",
            )
        if authorization.bound_arguments and authorization.bound_arguments != arguments:
            return MutationValidationIssue(
                "AUTHORIZATION_ARGUMENT_MISMATCH",
                "The mutation arguments differ from the arguments bound to user authorization.",
            )
        missing_values = []
        utterance = authorization.utterance.casefold().replace(",", "")
        for name, value in arguments.items():
            sensitive = bool(_SENSITIVE_ARGUMENT.search(name))
            identifier = name.endswith("_id") or name in {
                "id", "account", "card", "customer"
            }
            if not sensitive or (identifier and name in {
                "id", "account_id", "card_id", "customer_id", "user_id",
                "transaction_id", "account", "card", "customer",
            }):
                continue
            normalized = _normalized(value).replace(",", "")
            if normalized and normalized not in utterance:
                missing_values.append(name)
        if missing_values:
            return MutationValidationIssue(
                "UNAUTHORIZED_ARGUMENT_VALUE",
                "Sensitive mutation values were not present in the explicit user authorization: "
                + ", ".join(sorted(missing_values)),
            )
        return None

    @staticmethod
    def record_sent(
        state: PolicyPilotState,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        signature: str,
        tool_call_id: str,
        turn: int,
    ) -> MutationRecord:
        authorization = find_active_authorization(state, tool_name, turn=turn)
        mutation_id = f"mutation_{uuid.uuid4().hex}"
        record = MutationRecord(
            mutation_id=mutation_id,
            operation_fingerprint=operation_fingerprint(signature),
            tool_name=tool_name,
            arguments=dict(arguments),
            signature=signature,
            tool_call_id=tool_call_id,
            status="PLANNED",
            planned_turn=turn,
            updated_turn=turn,
            authorization_id=authorization.authorization_id if authorization else None,
            expected_effect={
                key: value
                for key, value in arguments.items()
                if key != "id" and not key.endswith("_id")
            },
            status_history=[
                MutationTransition(
                    status="PLANNED",
                    turn=turn,
                    reason="validated_before_external_execution",
                    tool_call_id=tool_call_id,
                )
            ],
        )
        state.mutations.append(record)
        if authorization is not None:
            authorization.bound_tool_name = tool_name
            authorization.bound_arguments = dict(arguments)
            authorization.consumed_by_mutation_id = mutation_id
        MutationManager.transition(
            record,
            "SENT",
            turn=turn,
            reason="returned_to_environment_for_execution",
            tool_call_id=tool_call_id,
        )
        return record

    @staticmethod
    def transition(
        record: MutationRecord,
        status: MutationStatus,
        *,
        turn: int,
        reason: str,
        tool_call_id: str | None = None,
    ) -> None:
        if status == record.status:
            return
        if status not in _TRANSITIONS[record.status]:
            raise ValueError(f"Illegal mutation transition: {record.status} -> {status}")
        record.status = status
        record.updated_turn = turn
        record.details = reason
        record.status_history.append(
            MutationTransition(
                status=status,
                turn=turn,
                reason=reason,
                tool_call_id=tool_call_id,
            )
        )

    @staticmethod
    def record_tool_result(
        record: MutationRecord,
        *,
        succeeded: bool,
        turn: int,
        tool_call_id: str,
    ) -> MutationStatus:
        if record.status in {"CONFIRMED", "FAILED"}:
            return record.status
        status: MutationStatus = "CONFIRMED" if succeeded else "UNKNOWN"
        reason = (
            "Environment returned a successful mutation result."
            if succeeded
            else "Mutation execution failed or returned an ambiguous result."
        )
        MutationManager.transition(
            record,
            status,
            turn=turn,
            reason=reason,
            tool_call_id=tool_call_id,
        )
        return status

    @staticmethod
    def bind_verification_contract(
        record: MutationRecord,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        record.verification_tool = tool_name
        record.verification_arguments = dict(arguments)

    @staticmethod
    def apply_readback(
        state: PolicyPilotState, *, readback_tool_call_id: str, content: str
    ) -> str:
        record = next(
            (item for item in reversed(state.mutations) if item.status == "UNKNOWN"),
            None,
        )
        if record is None:
            return "UNKNOWN"
        readback = next(
            (
                item
                for item in reversed(state.tool_history)
                if item.tool_call_id == readback_tool_call_id
            ),
            None,
        )
        if record.verification_tool and (
            readback is None
            or readback.name != record.verification_tool
            or any(
                readback.arguments.get(key) != value
                for key, value in record.verification_arguments.items()
            )
        ):
            record.readback_tool_call_id = readback_tool_call_id
            record.details = "Read-back did not match the bound verification contract."
            return "UNKNOWN"
        lowered = content.casefold()
        if any(marker in lowered for marker in _NEGATIVE_READBACK):
            status: MutationStatus = "FAILED"
            reason = "Authoritative read-back explicitly reports no applied change."
        else:
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                parsed = None
            matches = _matching_effect_fields(parsed, record.expected_effect)
            positive = _contains_positive_status(parsed)
            if record.expected_effect and matches == set(record.expected_effect):
                status = "CONFIRMED"
                reason = "Authoritative read-back matched every expected effect field."
            elif not record.expected_effect and positive:
                status = "CONFIRMED"
                reason = "Authoritative read-back explicitly confirmed the operation status."
            else:
                record.readback_tool_call_id = readback_tool_call_id
                record.details = (
                    "Authoritative read-back did not prove every expected mutation effect."
                )
                return "UNKNOWN"
        MutationManager.transition(
            record,
            status,
            turn=len(state.messages),
            reason=reason,
            tool_call_id=readback_tool_call_id,
        )
        record.readback_tool_call_id = readback_tool_call_id
        return status


def _walk_pairs(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key).casefold(), item
            yield from _walk_pairs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_pairs(item)


def _matching_effect_fields(parsed: Any, expected: dict[str, Any]) -> set[str]:
    pairs = list(_walk_pairs(parsed)) if parsed is not None else []
    return {
        key
        for key, expected_value in expected.items()
        if any(
            observed_key == key.casefold()
            and _normalized(observed_value) == _normalized(expected_value)
            for observed_key, observed_value in pairs
        )
    }


def _contains_positive_status(parsed: Any) -> bool:
    return any(
        key in {"status", "state", "result"}
        and _normalized(value) in _POSITIVE_STATUSES
        for key, value in _walk_pairs(parsed)
    )


mutation_manager = MutationManager()
