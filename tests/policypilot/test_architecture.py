import json

from policypilot.config import PolicyPilotConfig
from policypilot.context import build_agent_context
from policypilot.coverage import EvidenceResolver
from policypilot.evidence import EvidenceRecord
from policypilot.needs import NeedResolver, SourceResolver, decision_ready
from policypilot.planning import deterministic_semantic_plan, merge_semantic_plan
from policypilot.retrieval import build_retrieval_query
from policypilot.state import FactRecord, InformationNeed, PolicyPilotState
from policypilot.state_updates import (
    classify_intent,
    seed_information_needs,
    update_facts_from_tool_evidence,
    update_facts_from_user_message,
)
from tau2.data_model.message import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)


def state():
    return PolicyPilotState(system_messages=[SystemMessage(role="system", content="system")])


def apply_user(value, text, turn=0):
    update_facts_from_user_message(value, text, turn)
    plan = deterministic_semantic_plan(value, text, turn, classify_intent(text))
    merge_semantic_plan(value, plan, turn)
    seed_information_needs(value, turn)


def test_semantic_plan_keeps_goal_constraints_and_optimization_across_turns():
    value = state()
    apply_user(value, "Compare personal cards. I must have no annual fee and want the highest cash back.")
    apply_user(value, "I would prefer travel rewards too.", 1)

    assert value.goal.target == "card"
    assert value.goal.comparative
    assert any(item.hard and item.aspect == "annual_fee" for item in value.goal.criteria)
    assert any(item.kind == "OPTIMIZATION" and item.aspect == "rewards" for item in value.goal.criteria)
    assert any(item.kind == "PREFERENCE" for item in value.goal.criteria)


def test_comparative_goal_requires_candidate_options_before_decision():
    value = state()
    apply_user(value, "Compare personal cards for the best cash back.")

    need = next(
        item for item in value.open_needs("POLICY") if item.aspect == "candidate_options"
    )
    assert need.critical
    assert need.blocking
    assert not decision_ready(value)


def test_correction_replaces_goal_without_parallel_goal_state():
    value = state()
    apply_user(value, "I want to compare cards.")
    apply_user(value, "Actually, compare savings accounts instead.", 2)

    assert value.goal.objective == "Actually, compare savings accounts instead."
    assert not hasattr(value, "active_goal")
    assert not hasattr(value, "decision_requirements")


def test_raw_tool_parse_preserves_candidate_namespaces_before_compression():
    value = state()
    raw = json.dumps({"records": [{"id": "a", "status": "OPEN"}, {"id": "b", "status": "CLOSED"}]})
    evidence = EvidenceRecord(source_type="transaction_tool", turn_index=1, summary="records", tool_name="read_accounts", tool_call_id="call_1")

    update_facts_from_tool_evidence(value, evidence, raw)

    statuses = [fact for fact in value.facts if fact.aspect == "status"]
    assert len(statuses) == 2
    assert {fact.raw_path for fact in statuses} == {"records[0].status", "records[1].status"}
    assert {fact.value for fact in statuses} == {"OPEN", "CLOSED"}


def test_need_resolution_requires_entity_aspect_authority_and_evidence():
    value = state()
    need = InformationNeed(id="policy:alpha:fee", entity="alpha", aspect="annual_fee", source="POLICY", reason="Need authoritative fee.", evidence_refs=["kb_1"])
    value.information_needs.append(need)
    value.facts.append(FactRecord(id="wrong", entity="beta", aspect="annual_fee", value="0", source="POLICY", evidence_ref="kb_1", turn_index=1, authoritative=True))
    NeedResolver().resolve(value)
    assert need.status == "OPEN"

    value.facts.append(FactRecord(id="right", entity="alpha", aspect="annual_fee", value="0", source="POLICY", evidence_ref="kb_1", turn_index=1, authoritative=True))
    NeedResolver().resolve(value)
    assert need.status == "RESOLVED"
    assert need.resolved_by_fact_id == "right"


def test_non_empty_irrelevant_retrieval_does_not_resolve_policy_gap():
    value = state()
    need = InformationNeed(
        id="semantic:policy-gap",
        entity="referral",
        aspect="reward_limit",
        semantic_key="POLICY|referral|reward_limit|referral",
        scope="referral",
        source="POLICY",
        reason="Need the program terms.",
    )
    value.information_needs.append(need)
    value.facts.append(
        FactRecord(
            id="retrieved-policy",
            entity="retrieved_document",
            aspect="policy_document",
            value="terms",
            source="POLICY",
            evidence_ref="kb_1",
            turn_index=1,
            authoritative=True,
        )
    )

    result = EvidenceResolver().resolve(
        value,
        EvidenceRecord(
            source_type="knowledge_retrieval",
            turn_index=1,
            summary="A card has no annual fee.",
            tool_name="KB_search",
            tool_call_id="kb_1",
        ),
        trigger_need_id=need.id,
    )

    assert result["coverage"] == "NO_MATCH"
    assert need.status == "OPEN"
    assert need.resolved_by_fact_id is None


def test_customer_locator_resolves_identifier_question_without_faking_user_id():
    value = state()
    apply_user(value, "Please check the current referral status.")
    update_facts_from_user_message(value, "Use me@example.com.", 1)
    from policypilot.state_updates import resolve_user_needs

    resolve_user_needs(value)

    need = next(item for item in value.information_needs if item.id == "user:user_id")
    assert need.status == "RESOLVED"
    assert value.get_fact("user_id", "user") is None


def test_source_resolver_uses_tool_capabilities_and_unknown_fallback(tools):
    resolver = SourceResolver(tools)
    account = InformationNeed(id="account", entity="account", aspect="account_id", reason="Read account.")
    unknown = InformationNeed(id="mystery", entity="external", aspect="unmapped_signal", reason="No authority.")
    resolver.resolve(account)
    resolver.resolve(unknown)
    assert account.source in {"TOOL", "USER"}
    assert unknown.source == "UNKNOWN"


def test_query_is_need_driven_and_cannot_drop_hard_constraints():
    value = state()
    apply_user(value, "Compare cards. I must have no annual fee and want the highest cash back.")
    need = InformationNeed(id="policy:beta:eligibility", entity="Beta Card", aspect="eligibility", source="POLICY", reason="Missing candidate eligibility.", query_terms=["subscription requirements"])

    query = build_retrieval_query(value, need, "semantic expansion")

    assert "Beta Card" in query
    assert "eligibility" in query
    assert "subscription requirements" in query
    assert "no annual fee" in query


def test_critical_open_need_blocks_decision_readiness():
    value = state()
    value.information_needs.append(InformationNeed(id="user:id", entity="user", aspect="user_id", source="USER", reason="Identifier needed.", critical=True))
    assert not decision_ready(value)
    value.information_needs[0].status = "RESOLVED"
    assert decision_ready(value)


def test_context_contains_canonical_state_not_coverage_matrix(tools):
    value = state()
    apply_user(value, "Compare cards. I must have no annual fee.")
    context = build_agent_context(value, tools)
    assert "OPEN INFORMATION NEEDS" in context.structured_summary
    assert "CONSTRAINT annual_fee" in context.structured_summary
    assert "retrieval_coverage" not in context.structured_summary
    assert "decision_requirements" not in context.structured_summary


def test_context_deterministically_bounds_large_fact_values(tools):
    value = state()
    value.goal.objective = "Explain referral terms"
    value.facts.append(
        FactRecord(
            id="large-policy",
            entity="referral",
            aspect="policy",
            value="policy " * 20000,
            source="POLICY",
            evidence_ref="kb-large",
            turn_index=1,
            authoritative=True,
        )
    )

    context = build_agent_context(value, tools)

    assert len(context.structured_summary) < 5000
    assert "kb-large" in context.structured_summary


def test_recent_context_keeps_tool_result_with_its_call(tools):
    value = state()
    value.goal.objective = "Explain policy"
    value.messages.extend(
        [SystemMessage(role="system", content=f"old-{index}") for index in range(3)]
    )
    value.messages.extend(
        [
            AssistantMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="paired-call",
                        name="KB_search",
                        arguments={"query": "policy"},
                        requestor="assistant",
                    )
                ],
            ),
            ToolMessage(
                role="tool",
                id="paired-call",
                requestor="assistant",
                content="policy result",
            ),
        ]
    )

    context = build_agent_context(
        value, tools, config=PolicyPilotConfig(max_recent_messages=1)
    )

    assert isinstance(context.recent_messages[0], AssistantMessage)
    assert isinstance(context.recent_messages[1], ToolMessage)


def test_resolved_policy_need_is_not_reopened_by_follow_up_turn():
    value = state()
    apply_user(value, "Explain the referral policy.")
    need = next(item for item in value.information_needs if item.source == "POLICY")
    need.status = "RESOLVED"

    apply_user(value, "Thanks, please continue.", 2)

    same_need = next(item for item in value.information_needs if item.id == need.id)
    assert same_need.status == "RESOLVED"
