"""Canonical, budgeted policy query construction."""

from __future__ import annotations

import re
import uuid

from policypilot.state import InformationNeed, PolicyPilotState
from tau2.data_model.message import ToolCall, UserMessage
from tau2.environment.tool import Tool

_ASPECT_QUERY = {
    "annual_fee": "annual fee no annual fee fee-free",
    "rewards": "cashback rewards points rate",
    "eligibility_rule": "eligibility requirements conditions",
    "qualified_signup_definition": "qualified signup definition conditions",
    "reward_limit": "referral reward limit cap maximum",
    "payout_timeline": "reward payout timeline pending posting",
    "resubmission_rule": "resubmission retry waiting rule",
    "procedure": "procedure steps process",
    "escalation_path": "escalation support review path",
    "product_terms": "product terms conditions",
    "candidate_options": "available products options comparison",
}


def _unique(values):
    seen = set()
    result = []
    for value in values:
        value = " ".join(str(value).split()).strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def build_retrieval_query(
    state: PolicyPilotState, need: InformationNeed, rewrite: str | None = None
) -> str:
    """Build a stable skeleton without copying the raw user utterance."""

    entity = (
        ""
        if need.entity in {"policy", "product", "banking_product", "user"}
        else need.entity.replace("_", " ")
    )
    scoped_constraints = [
        f"{item.aspect.replace('_', ' ')} {item.value}"
        for item in state.goal.criteria
        if item.hard
    ]
    expansion = (
        "requirements exceptions" if state.control.pending_retrieval_rewrite else ""
    )
    terms = _unique(
        [
            entity,
            (need.scope or "").replace("_", " "),
            _ASPECT_QUERY.get(need.aspect, need.aspect.replace("_", " ")),
            *need.query_terms,
            need.query_objective or "",
            *scoped_constraints,
            expansion,
            rewrite or "",
        ]
    )
    query = " ".join(terms)
    # Internal lifecycle identifiers must never become retrieval vocabulary.
    query = " ".join(
        token
        for token in query.split()
        if not token.lower().startswith(("need:", "query:"))
        and not re.fullmatch(r"[0-9a-f]{10,}", token.lower())
    )
    return query[:500]


def build_global_retrieval_query(state: PolicyPilotState) -> str:
    """Build a goal-level recall query independent of one parsed Need."""

    latest_user = next(
        (
            (message.content or "").strip()
            for message in reversed(state.messages)
            if isinstance(message, UserMessage) and (message.content or "").strip()
        ),
        "",
    )
    hard_constraints = [item.value for item in state.goal.criteria if item.hard]
    preferences = [
        item.value for item in state.goal.criteria if item.kind == "PREFERENCE"
    ]
    optimization = [
        item.value for item in state.goal.criteria if item.kind == "OPTIMIZATION"
    ]
    terms = _unique(
        [
            state.goal.objective or "",
            (state.goal.target or "").replace("_", " "),
            *hard_constraints,
            *preferences,
            *optimization,
            latest_user,
        ]
    )
    return " ".join(terms)[:700]


def add_global_query_argument(
    state: PolicyPilotState,
    call: ToolCall,
    tool: Tool,
) -> str | None:
    """Attach the global channel only when the selected backend supports it."""

    if "global_query" not in tool.params.model_fields:
        return None
    global_query = build_global_retrieval_query(state)
    need_query = str((call.arguments or {}).get("query") or "").strip()
    if not global_query or global_query.casefold() == need_query.casefold():
        return None
    call.arguments = {**(call.arguments or {}), "global_query": global_query}
    return global_query


def build_retrieval_call(
    state: PolicyPilotState,
    need: InformationNeed,
    tool: Tool,
    rewrite: str | None = None,
) -> ToolCall:
    query = build_retrieval_query(state, need, rewrite)
    arguments = {"query": query}
    fields = tool.params.model_fields
    if "query" not in fields:
        first = next(iter(fields), None)
        arguments = {first: query} if first else {}
    call = ToolCall(
        id=f"need_{uuid.uuid4().hex[:12]}",
        name=tool.name,
        arguments=arguments,
        requestor="assistant",
    )
    global_query = add_global_query_argument(state, call, tool)
    event = {
        "turn": len(state.messages),
        "tool_call_id": call.id,
        "need_id": need.id,
        "semantic_need_key": need.semantic_key,
        "entity": need.entity,
        "aspect": need.aspect,
        "aspect_provenance": need.aspect_provenance,
        "scope": need.scope,
        "source": need.source,
        "status": "REQUESTED",
        "attempt": need.retrieval_attempts + 1,
        "attempt_committed": False,
        "query": query,
        "global_query": global_query,
        "retrieval_channels": [
            "need",
            *(["global_user"] if global_query else []),
        ],
        "candidate_documents": [],
        "coverage": None,
        "matched_need_ids": [],
        "partial_need_ids": [],
        "why_again": "coverage remained partial or absent"
        if need.retrieval_attempts
        else "initial unresolved policy gap",
    }
    state.control.pending_retrieval_events[call.id] = event
    return call
