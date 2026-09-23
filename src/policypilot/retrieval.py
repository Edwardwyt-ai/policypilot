"""Canonical, budgeted policy query construction."""
from __future__ import annotations

import re
import uuid

from policypilot.state import InformationNeed, PolicyPilotState
from tau2.data_model.message import ToolCall
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


def build_retrieval_query(state: PolicyPilotState, need: InformationNeed, rewrite: str | None = None) -> str:
    """Build a stable skeleton without copying the raw user utterance."""

    entity = "" if need.entity in {"policy", "product", "banking_product", "user"} else need.entity.replace("_", " ")
    hard_constraint_terms = {
        "annual_fee": "no annual fee",
        "rewards": "cashback rewards",
    }
    scoped_constraints = [
        hard_constraint_terms.get(item.aspect, item.aspect.replace("_", " "))
        for item in state.goal.criteria
        if item.hard
    ]
    expansion = "requirements exceptions" if state.control.pending_retrieval_rewrite else ""
    terms = _unique([
        entity,
        (need.scope or "").replace("_", " "),
        _ASPECT_QUERY.get(need.aspect, need.aspect.replace("_", " ")),
        *need.query_terms,
        need.query_objective or "",
        *scoped_constraints,
        expansion,
        rewrite or "",
    ])
    query = " ".join(terms)
    # Internal lifecycle identifiers must never become retrieval vocabulary.
    query = " ".join(
        token
        for token in query.split()
        if not token.lower().startswith(("need:", "query:"))
        and not re.fullmatch(r"[0-9a-f]{10,}", token.lower())
    )
    return query[:500]


def build_retrieval_call(state: PolicyPilotState, need: InformationNeed, tool: Tool, rewrite: str | None = None) -> ToolCall:
    query = build_retrieval_query(state, need, rewrite)
    arguments = {"query": query}
    fields = tool.params.model_fields
    if "query" not in fields:
        first = next(iter(fields), None)
        arguments = {first: query} if first else {}
    call = ToolCall(id=f"need_{uuid.uuid4().hex[:12]}", name=tool.name, arguments=arguments, requestor="assistant")
    need.retrieval_attempts += 1
    need.acquisition_count += 1
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
        "attempt": need.retrieval_attempts,
        "query": query,
        "candidate_documents": [],
        "coverage": None,
        "matched_need_ids": [],
        "partial_need_ids": [],
        "why_again": "coverage remained partial or absent" if need.retrieval_attempts > 1 else "initial unresolved policy gap",
    }
    state.control.retrieval_events.append(event)
    state.control.retrieval_query_history.append({"turn": len(state.messages), "need_id": need.id, "query": query})
    return call
