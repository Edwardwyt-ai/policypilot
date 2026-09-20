"""Deterministic observation parsing before semantic planning."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from policypilot.evidence import EvidenceRecord
from policypilot.need_registry import NeedRegistry
from policypilot.state import FactRecord, IntentType, NeedCandidate, PolicyPilotState
from policypilot.taxonomy import canonicalize_aspect


def classify_intent(content: str) -> IntentType:
    lowered = content.lower()
    if re.search(r"\b(actually|instead|correction|i mean)\b|更正|改成", lowered):
        return "CORRECTION"
    if re.search(r"\b(close|change|freeze|replace|activate|transfer|submit|retry|apply|dispute|cancel|update)\b|关闭|修改|冻结|提交|重试|取消", lowered):
        return "TRANSACTIONAL"
    if re.search(r"\b(eligible|eligibility|qualify|can i)\b|资格|符合条件", lowered):
        return "ELIGIBILITY_CHECK"
    if re.search(r"\b(status|balance|check|track|current)\b|状态|余额|查询", lowered):
        return "STATUS_CHECK"
    if re.search(r"\b(what|why|how|explain|information|policy|which|best)\b|什么|为什么|如何|政策|哪个|最好", lowered):
        return "INFORMATIONAL"
    return "OTHER"


def _id(entity: str, aspect: str, turn: int) -> str:
    return f"{entity}:{aspect}:{turn}"


def _fact(state: PolicyPilotState, *, entity: str, aspect: str, value: Any, source: str, turn: int, evidence_ref: str, authoritative: bool, raw_path: str | None = None) -> None:
    observed_at = datetime.now(timezone.utc) if source == "TOOL" else None
    state.upsert_fact(FactRecord(
        id=_id(entity, aspect, turn), entity=entity, aspect=aspect, value=value,
        source=source, evidence_ref=evidence_ref, turn_index=turn,
        authoritative=authoritative, raw_path=raw_path, observed_at=observed_at,
        observed_version=state.control.observation_version,
    ))


_USER_FIELDS = {
    "user_id": re.compile(r"\buser[ _-]?id\s*(?:is|:|=)?\s*([a-z0-9_-]{4,})", re.I),
    "account_id": re.compile(r"\baccount[ _-]?id\s*(?:is|:|=)?\s*([a-z0-9_-]{4,})", re.I),
    "transaction_id": re.compile(r"\btransaction[ _-]?id\s*(?:is|:|=)?\s*([a-z0-9_-]{4,})", re.I),
    "card_id": re.compile(r"\bcard[ _-]?id\s*(?:is|:|=)?\s*([a-z0-9_-]{4,})", re.I),
    "email": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "phone_number": re.compile(r"\b(?:\+?\d[\d ()-]{7,}\d)\b"),
}


def update_facts_from_user_message(
    state: PolicyPilotState,
    content: str,
    turn_index: int,
    evidence_ref: str | None = None,
) -> None:
    ref = evidence_ref or f"user_turn:{turn_index}"
    for aspect, pattern in _USER_FIELDS.items():
        match = pattern.search(content)
        if match:
            _fact(state, entity="user", aspect=aspect, value=match.group(1) if match.lastindex else match.group(0), source="USER", turn=turn_index, evidence_ref=ref, authoritative=True)
    _fact(state, entity="user", aspect="utterance", value=content, source="USER", turn=turn_index, evidence_ref=ref, authoritative=True)


def seed_information_need_candidates(
    state: PolicyPilotState,
    capabilities: set[str] | None = None,
) -> list[NeedCandidate]:
    """Derive narrow authority candidates from explicit goal semantics."""

    goal = state.goal
    if not goal.objective:
        return []
    candidates: list[NeedCandidate] = []
    for criterion in goal.criteria:
        aspect = canonicalize_aspect(criterion.aspect, entity=goal.target or "", scope=goal.target)
        if aspect is None:
            continue
        candidates.append(NeedCandidate(
            entity=goal.target or "banking_product",
            aspect=aspect,
            scope=goal.target,
            source="POLICY",
            criticality="CRITICAL" if criterion.hard else "OPTIONAL",
            reason_code="explicit_hard_constraint" if criterion.hard else "decision_criterion",
            query_terms=[criterion.aspect.replace("_", " ")],
        ))
    if goal.comparative and goal.target:
        candidates.append(NeedCandidate(
            entity=goal.target, aspect="candidate_options", scope=goal.target,
            source="POLICY", criticality="CRITICAL", reason_code="required_action_blocked",
            query_terms=[goal.target, "available options"],
        ))
    if (
        goal.target
        and re.search(r"\bpolicy|terms?\b|政策|条款", goal.objective, re.I)
        and not candidates
    ):
        candidates.append(NeedCandidate(
            entity=goal.target, aspect="product_terms", scope=goal.target,
            source="POLICY", criticality="CRITICAL", reason_code="explicit_policy_question",
            query_terms=[goal.target, "policy terms"],
        ))
    objective = goal.objective.lower()
    if goal.target == "referral" or "referral" in objective:
        if re.search(r"\b(bonus|reward|paid|received|missing|only|how many|limit)\b", objective):
            candidates.append(NeedCandidate(
                entity="referral", aspect="reward_limit", scope="referral",
                source="POLICY", criticality="CRITICAL", reason_code="explicit_policy_question",
                query_terms=["referral bonus limit"],
            ))
        if re.search(r"\b(sign.?up|qualif|approved|requirements?)\b", objective):
            candidates.append(NeedCandidate(
                entity="referral", aspect="qualified_signup_definition", scope="referral",
                source="POLICY", criticality="CRITICAL", reason_code="explicit_policy_question",
                query_terms=["qualified referral signup"],
            ))
        rejected_referral = any(
            fact.source == "TOOL"
            and fact.aspect == "referral_status"
            and str(fact.value).upper() == "REJECTED"
            for fact in state.facts
        ) or any(
            item.source_type == "transaction_tool"
            and "referral" in (item.tool_name or "").lower()
            and re.search(r"\bREJECTED\b", item.summary)
            for item in state.evidence
        )
        if rejected_referral:
            candidates.append(NeedCandidate(
                entity="referral", aspect="resubmission_rule", scope="referral",
                source="POLICY", criticality="CRITICAL",
                reason_code="authoritative_precondition",
                query_terms=["rejected referral resubmission retry"],
            ))

        available = capabilities or set()
        user_id = state.get_fact("user_id", "user")
        email = state.get_fact("email", "user")
        phone = state.get_fact("phone_number", "user")
        identity_capability = (
            "get_user_information_by_email"
            if email and "get_user_information_by_email" in available
            else "get_user_information_by_phone"
            if phone and "get_user_information_by_phone" in available
            else None
        )
        if not user_id and identity_capability:
            key = "email" if email else "phone_number"
            value = email or phone
            candidates.append(NeedCandidate(
                entity="user", aspect="customer_identifier", source="TOOL",
                capability=identity_capability,
                tool_arguments={key: value.value} if value else {},
                criticality="CRITICAL", reason_code="required_action_blocked",
            ))
        if user_id and "get_referrals_by_user" in available:
            candidates.append(NeedCandidate(
                entity="referral", aspect="current_referral_records", source="TOOL",
                capability="get_referrals_by_user", tool_arguments={"user_id": user_id.value},
                criticality="CRITICAL", reason_code="required_action_blocked",
            ))
    has_locator = any(state.get_fact(aspect, "user") for aspect in ("user_id", "email", "phone_number"))
    needs_customer_state = any(
        item.source == "TOOL"
        and item.aspect
        in {"current_account_state", "current_transaction_state", "current_referral_records"}
        for item in candidates
    ) or (
        (goal.target == "referral" or "referral" in objective)
        and re.search(r"\b(my|i|received|missing|paid|status)\b", objective)
    )
    if (
        state.intent in {"STATUS_CHECK", "ELIGIBILITY_CHECK", "TRANSACTIONAL"}
        or needs_customer_state
    ) and not has_locator:
        candidates.append(NeedCandidate(
            entity="user", aspect="customer_identifier", source="USER",
            criticality="CRITICAL", reason_code="required_action_blocked",
            question="Which customer identifier can I use for the account lookup?",
        ))
    return candidates


def seed_information_needs(state: PolicyPilotState, turn_index: int, registry: NeedRegistry | None = None) -> None:
    """Compatibility wrapper; formal needs still enter through NeedRegistry."""

    (registry or NeedRegistry()).register_many(
        state, seed_information_need_candidates(state), turn=turn_index
    )


def _flatten(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _entity_from_path(path: str) -> str:
    parts = re.split(r"\.|\[|\]", path)
    candidate = next((part for part in parts if part and part not in {"data", "result", "items", "records"}), "tool_result")
    return re.sub(r"[^a-z0-9_-]+", "_", candidate.lower())


def _parse_tool_payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        parsed = {}
        for match in re.finditer(r"(?:^|\n|\s)([A-Za-z][A-Za-z0-9 _-]{1,48}):\s*(.+?)(?=\n|\s+[A-Za-z][A-Za-z0-9 _-]{1,48}:|$)", raw, re.S):
            parsed[match.group(1).strip()] = match.group(2).strip()
        return parsed or {"result": raw}


def update_facts_from_tool_evidence(state: PolicyPilotState, evidence: EvidenceRecord, raw_content: str | None = None) -> None:
    ref = evidence.evidence_id
    if evidence.source_type == "knowledge_retrieval":
        for policy_ref in evidence.policy_refs:
            entity = (policy_ref.title or policy_ref.document_id).split(":", 1)[0].strip().lower().replace(" ", "_")
            _fact(state, entity=entity or "policy", aspect="policy_document", value={"document_id": policy_ref.document_id, "title": policy_ref.title, "summary": evidence.summary}, source="POLICY", turn=evidence.turn_index, evidence_ref=ref, authoritative=True)
        return

    parsed = _parse_tool_payload(raw_content or evidence.summary)
    identity_lookup = bool(evidence.tool_name and re.search(r"get_user|user_information|customer", evidence.tool_name, re.I))
    for path, value in _flatten(parsed):
        aspect = re.sub(r"[^a-z0-9]+", "_", path.rsplit(".", 1)[-1].lower()).strip("_") or "result"
        entity = "user" if identity_lookup and aspect in {"user_id", "id", "email", "phone_number", "name", "address", "date_of_birth"} else _entity_from_path(path)
        if entity == "user" and aspect == "id":
            aspect = "user_id"
        _fact(state, entity=entity, aspect=aspect, value=value, source="TOOL", turn=evidence.turn_index, evidence_ref=ref, authoritative=True, raw_path=path)


def resolve_user_needs(state: PolicyPilotState) -> None:
    for need in state.open_needs("USER"):
        fact = state.get_fact(need.aspect, need.entity)
        if need.aspect == "customer_identifier" and fact is None:
            fact = state.get_fact("user_id", "user") or state.get_fact("email", "user") or state.get_fact("phone_number", "user")
        if fact:
            state.resolve_need(need, evidence_refs=[fact.evidence_ref] if fact.evidence_ref else [], fact_id=fact.id)
            state.control.needs_resolved_count += 1
