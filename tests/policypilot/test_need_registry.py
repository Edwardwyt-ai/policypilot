import inspect

from policypilot.config import PolicyPilotConfig
from policypilot.coverage import EvidenceResolver
from policypilot.evidence import EvidenceRecord, PolicyReference
from policypilot.need_registry import NeedManager, NeedRegistry
from policypilot.needs import decision_ready, select_next_blocking_need
from policypilot.planning import (
    deterministic_semantic_plan,
    merge_semantic_plan,
    planner_trigger_reason,
)
from policypilot.retrieval import build_retrieval_query
from policypilot.state import InformationNeed, NeedCandidate, PolicyPilotState
from policypilot.state_updates import classify_intent, seed_information_need_candidates
from tau2.data_model.message import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)


def state() -> PolicyPilotState:
    return PolicyPilotState(system_messages=[SystemMessage(role="system", content="system")])


def evidence(text: str, call_id: str = "kb-1") -> EvidenceRecord:
    return EvidenceRecord(
        source_type="knowledge_retrieval",
        turn_index=1,
        summary=text,
        tool_name="KB_search",
        tool_call_id=call_id,
        policy_refs=[PolicyReference(document_id="doc-1", title=text[:80])],
    )


def candidate(aspect="annual_fee", **kwargs) -> NeedCandidate:
    return NeedCandidate(
        entity=kwargs.pop("entity", "Gold Card"),
        aspect=aspect,
        scope=kwargs.pop("scope", "personal card"),
        source="POLICY",
        reason_code=kwargs.pop("reason_code", "decision_criterion"),
        **kwargs,
    )


def test_deterministic_and_semantic_candidates_share_one_registry_need():
    value = state()
    registry = NeedRegistry()
    registry.register_many(value, [candidate(), candidate(entity="gold-card")], turn=1)

    assert len(value.information_needs) == 1
    assert value.control.need_registry_events[-1]["deduplicated_count"] == 1


def test_resolved_semantic_need_is_never_reopened():
    value = state()
    registry = NeedRegistry()
    registry.register_many(value, [candidate()], turn=1)
    value.resolve_need(value.information_needs[0], evidence_refs=["kb-1"])

    registry.register_many(value, [candidate(criticality="CRITICAL")], turn=2)

    assert len(value.information_needs) == 1
    assert value.information_needs[0].status == "RESOLVED"


def test_one_policy_evidence_can_resolve_multiple_compatible_needs():
    value = state()
    registry = NeedRegistry()
    registry.register_many(value, [candidate("annual_fee"), candidate("rewards")], turn=1)

    result = EvidenceResolver().resolve(
        value,
        evidence("Gold Card personal card has no annual fee and earns cashback rewards."),
        trigger_need_id=value.information_needs[0].id,
    )

    assert result["matched_evidence_count"] == 2
    assert all(need.status == "RESOLVED" for need in value.information_needs)


def test_entity_aspect_and_scope_mismatches_never_resolve():
    resolver = EvidenceResolver()
    value = state()
    registry = NeedRegistry()
    registry.register_many(value, [candidate()], turn=1)
    need = value.information_needs[0]

    assert resolver.coverage(need, evidence("Silver Card personal card has no annual fee.")) != "MATCH"
    assert resolver.coverage(need, evidence("Gold Card personal card eligibility requirements.")) != "MATCH"
    assert resolver.coverage(need, evidence("Gold Card business card has no annual fee.")) != "MATCH"


def test_optional_need_does_not_drift_to_critical_on_duplicate():
    value = state()
    registry = NeedRegistry()
    registry.register_many(value, [candidate()], turn=1)
    registry.register_many(
        value,
        [candidate(criticality="CRITICAL", reason_code="model_emphasis")],
        turn=2,
    )

    assert value.information_needs[0].critical is False


def test_ordinary_no_account_requirements_phrase_creates_no_policy_need():
    value = state()
    text = "I have no account requirements."
    plan = deterministic_semantic_plan(value, text, 0, classify_intent(text))
    merge_semantic_plan(value, plan, 0)

    assert seed_information_need_candidates(value) == []


def test_retrieval_query_is_canonical_and_excludes_raw_utterance():
    value = state()
    value.goal.objective = "SECRET_RAW_UTTERANCE compare a personal card"
    registry = NeedRegistry()
    registry.register_many(value, [candidate()], turn=1)

    query = build_retrieval_query(value, value.information_needs[0])

    assert "SECRET_RAW_UTTERANCE" not in query
    assert "annual fee" in query
    assert "personal card" in query


def test_planner_skips_pure_identity_follow_up():
    value = state()
    value.goal.objective = "Check my referral status"

    assert planner_trigger_reason(value, "me@example.com") is None
    assert planner_trigger_reason(value, "+1 555 123 4567") is None


def test_account_specific_referral_complaint_requests_a_customer_locator():
    value = state()
    text = "I only received two of my four referral bonuses."
    plan = deterministic_semantic_plan(value, text, 0, classify_intent(text))
    merge_semantic_plan(value, plan, 0)

    candidates = seed_information_need_candidates(
        value, {"get_referrals_by_user"}
    )

    assert any(
        item.source == "USER" and item.aspect == "customer_identifier"
        for item in candidates
    )


def test_existing_evidence_satisfies_candidate_without_retrieval():
    value = state()
    value.evidence.append(
        evidence("Gold Card personal card has no annual fee.")
    )

    NeedRegistry().register_many(value, [candidate()], turn=2)

    assert value.information_needs[0].status == "RESOLVED"
    assert value.control.need_registry_events[-1]["evidence_covered_count"] == 1


def test_non_read_action_cannot_become_a_tool_information_need():
    value = state()
    registry = NeedRegistry(capabilities={"get_referrals_by_user"})

    registry.register_many(
        value,
        [
            NeedCandidate(
                entity="user",
                aspect="escalation_path",
                source="TOOL",
                capability="transfer_to_human_agents",
                criticality="CRITICAL",
            )
        ],
        turn=1,
    )

    assert value.information_needs == []
    assert value.control.need_registry_events[-1]["rejected_count"] == 1


def test_rejected_referral_opens_resubmission_policy_gap():
    value = state()
    value.goal.objective = "Explain why my referral bonus was rejected"
    value.goal.target = "referral"
    value.evidence.append(
        EvidenceRecord(
            source_type="transaction_tool",
            turn_index=2,
            summary="referral_status: REJECTED",
            tool_name="get_referrals_by_user",
            tool_call_id="tool-1",
        )
    )

    candidates = seed_information_need_candidates(value)

    assert any(item.aspect == "resubmission_rule" for item in candidates)


def test_dynamic_aspect_is_retained_with_provenance_and_can_block_when_explicit():
    value = state()
    value.goal.target = "card"
    NeedManager().register_many(
        value,
        [candidate(
            "foreign_exchange_markup",
            criticality="CRITICAL",
            reason_code="explicit_hard_constraint",
        )],
        turn=1,
    )

    need = value.information_needs[0]
    assert need.aspect == "foreign_exchange_markup"
    assert need.aspect_provenance == "DYNAMIC"
    assert need.blocking


def test_planner_criticality_uses_goal_relevance_without_reason_code():
    value = state()
    value.goal.objective = "Explain my referral result"
    value.goal.target = "referral"

    NeedManager().register_many(
        value,
        [NeedCandidate(
            entity="user",
            aspect="eligibility_rule",
            source="POLICY",
            criticality="CRITICAL",
            provenance="semantic_planner",
        )],
        turn=1,
    )

    need = value.information_needs[0]
    assert need.entity == "referral"
    assert need.blocking


def test_valid_need_candidates_respect_registry_limit():
    value = state()
    candidates = [
        candidate(f"dynamic_policy_term_{index}", scope=f"scope-{index}")
        for index in range(48)
    ]

    NeedManager().register_many(value, candidates, turn=1, max_needs=3)

    assert len(value.information_needs) == 3
    assert value.control.need_registry_events[-1]["rejected_count"] == 45


def test_partial_coverage_stays_open_and_records_coverage():
    value = state()
    NeedManager().register_many(value, [candidate("annual_fee")], turn=1)
    need = value.information_needs[0]

    result = EvidenceResolver().resolve(
        value,
        evidence("Gold Card business card has no annual fee."),
        trigger_need_id=need.id,
    )

    assert result["coverage"] == "PARTIAL"
    assert need.status == "PARTIALLY_COVERED"
    assert need.coverage == "PARTIAL"


def test_selector_returns_only_one_blocking_actionable_need():
    value = state()
    NeedManager().register_many(
        value,
        [
            candidate("annual_fee", criticality="OPTIONAL"),
            candidate(
                "rewards",
                criticality="CRITICAL",
                reason_code="explicit_hard_constraint",
            ),
            candidate(
                "eligibility_rule",
                scope="premium-card",
                criticality="CRITICAL",
                reason_code="explicit_policy_question",
            ),
        ],
        turn=1,
    )

    selected = select_next_blocking_need(value)

    assert selected is not None
    assert selected.aspect == "rewards"
    assert sum(item.id == selected.id for item in value.information_needs) == 1


def test_critical_exhausted_need_prevents_unsupported_decision():
    value = state()
    value.information_needs.extend([
        InformationNeed(
            id="optional", entity="card", aspect="rewards", source="POLICY",
            reason="background", critical=False, blocking=False,
        ),
        InformationNeed(
            id="exhausted", entity="card", aspect="annual_fee", source="POLICY",
            reason="attempted", critical=True, blocking=True, retrieval_attempts=2,
        ),
    ])

    assert not decision_ready(
        value, PolicyPilotConfig(max_retrieval_attempts_per_semantic_need=2)
    )
    assert value.information_needs[1].exhausted


def test_retrieval_evidence_does_not_proliferate_needs():
    value = state()
    NeedManager().register_many(value, [candidate("annual_fee")], turn=1)
    before = len(value.information_needs)

    EvidenceResolver().resolve(
        value,
        evidence("Gold Card personal card has no annual fee and rewards."),
        trigger_need_id=value.information_needs[0].id,
    )

    assert len(value.information_needs) == before


def test_repeated_semantically_identical_evidence_is_not_progress():
    value = state()
    first = evidence("Same policy summary", "kb-1")
    value.evidence.append(first)
    before = value.progress_signature()
    value.evidence.append(evidence("Same policy summary", "kb-2"))

    assert not value.record_progress(before, turn=2)


def test_no_progress_recovery_safe_stops_and_keeps_need_for_audit():
    value = state()
    value.information_needs.append(InformationNeed(
        id="blocked", entity="card", aspect="annual_fee", source="POLICY",
        reason="missing", critical=True, blocking=True,
    ))

    assert value.release_stalled_blockers(reason="test") == 1
    assert value.information_needs[0].status == "EXHAUSTED"
    assert value.information_needs[0].exhausted
    assert not decision_ready(value)
    assert value.information_needs[0].blocking


def test_workflow_has_no_while_open_need_loop():
    from policypilot import graph

    source = inspect.getsource(graph.PolicyPilotWorkflow)
    assert "while" not in source


def test_structured_tool_result_skips_planner_and_resolves_bound_need(
    agent_factory,
):
    agent = agent_factory(
        config=PolicyPilotConfig(
            memory_enabled=False,
            skills_enabled=False,
            semantic_planner_enabled=True,
        )
    )
    value = agent.get_init_state()
    candidate_value = NeedCandidate(
        entity="account",
        aspect="current_account_state",
        source="TOOL",
        capability="read_account",
        tool_arguments={"account_id": "acct-1"},
        criticality="CRITICAL",
        reason_code="required_action_blocked",
    )
    agent.need_registry.register_many(value, [candidate_value], turn=0)
    need = value.information_needs[0]
    call = ToolCall(
        id="read-1", name="read_account",
        arguments={"account_id": "acct-1"}, requestor="assistant",
    )
    value.messages.append(AssistantMessage(role="assistant", tool_calls=[call]))
    agent._record_valid_tool_calls(value.messages[-1], value, need.id)
    agent.semantic_planner.plan = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("planner must not run for ToolMessage")
    )

    agent._observe(
        ToolMessage(
            role="tool", id="read-1", requestor="assistant",
            content='{"account_id":"acct-1","status":"OPEN"}',
        ),
        value,
    )

    assert need.status == "RESOLVED"


def test_business_empty_tool_result_does_not_resolve_bound_need(agent_factory):
    agent = agent_factory(
        config=PolicyPilotConfig(
            memory_enabled=False,
            skills_enabled=False,
            semantic_planner_enabled=False,
        )
    )
    value = agent.get_init_state()
    candidate_value = NeedCandidate(
        entity="account",
        aspect="current_account_state",
        source="TOOL",
        capability="read_account",
        tool_arguments={"account_id": "missing"},
        criticality="CRITICAL",
        reason_code="required_action_blocked",
    )
    agent.need_registry.register_many(value, [candidate_value], turn=0)
    need = value.information_needs[0]
    call = ToolCall(
        id="read-missing",
        name="read_account",
        arguments={"account_id": "missing"},
        requestor="assistant",
    )
    value.messages.append(AssistantMessage(role="assistant", tool_calls=[call]))
    agent._record_valid_tool_calls(value.messages[-1], value, need.id)

    agent._observe(
        ToolMessage(
            role="tool",
            id="read-missing",
            requestor="assistant",
            content='{"status":"not_found","message":"Account not found"}',
        ),
        value,
    )

    assert need.status != "RESOLVED"
