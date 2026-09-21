from policypilot.config import PolicyPilotConfig
from policypilot.runtime.actions import (
    decision_fallback_candidates,
    register_decision_fallback,
    validate_proposal,
)
from policypilot.runtime.recovery import recover_validation_failure
from policypilot.state import FactRecord, InformationNeed
from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage


def tool_message(name: str, arguments: dict, call_id: str = "call-1"):
    return AssistantMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
                requestor="assistant",
            )
        ],
    )


def test_main_decision_sees_bounded_knowledge_but_not_transaction_reads(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    state.intent = "TRANSACTIONAL"

    exposed = {tool.name for tool in agent._decision_tools(state)}

    assert "KB_search" in exposed
    assert "read_account" not in exposed
    assert "mutate_account" in exposed


def test_main_decision_knowledge_permission_can_be_disabled(agent_factory):
    agent = agent_factory(
        config=PolicyPilotConfig(
            memory_enabled=False,
            decision_knowledge_tools_enabled=False,
        )
    )

    exposed = {tool.name for tool in agent._decision_tools(agent.get_init_state())}

    assert "KB_search" not in exposed


def test_decision_retrieval_reopens_and_binds_resolved_need(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    state.goal.target = "card"
    need = InformationNeed(
        id="policy-card-rewards",
        semantic_key="POLICY|card|rewards|card",
        entity="card",
        aspect="rewards",
        scope="card",
        source="POLICY",
        status="RESOLVED",
        reason="ranking_requires_reward_rates",
        retrieval_attempts=1,
        evidence_refs=["weak-evidence"],
        coverage="MATCH",
    )
    state.information_needs.append(need)
    proposal = tool_message(
        "KB_search",
        {"query": "best personal card cashback for everyday spending"},
        call_id="decision-kb-1",
    )

    result = validate_proposal(agent, proposal, state)
    agent._record_valid_tool_calls(proposal, state)

    assert result.allowed
    assert need.status == "OPEN"
    assert need.blocking
    assert need.coverage == "PARTIAL"
    assert need.retrieval_attempts == 2
    assert state.control.retrieval_events[-1]["origin"] == "decision"
    assert state.control.retrieval_events[-1]["need_id"] == need.id
    assert state.tool_history[-1].need_id == need.id


def test_decision_retrieval_uses_query_scoped_need_after_canonical_limit(
    agent_factory,
):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    state.goal.target = "card"
    canonical = InformationNeed(
        id="policy-card-rewards",
        semantic_key="POLICY|card|rewards|card",
        entity="card",
        aspect="rewards",
        scope="card",
        source="POLICY",
        status="RESOLVED",
        reason="ranking_requires_reward_rates",
        retrieval_attempts=2,
        evidence_refs=["broad-evidence"],
        coverage="MATCH",
    )
    state.information_needs.append(canonical)
    proposal = tool_message(
        "KB_search",
        {"query": "compare personal card cashback rates"},
        call_id="decision-kb-corrective",
    )

    result = validate_proposal(agent, proposal, state)
    agent._record_valid_tool_calls(proposal, state)

    assert result.allowed
    assert canonical.status == "RESOLVED"
    event = state.control.retrieval_events[-1]
    assert event["binding"] == "query_scoped"
    assert event["origin"] == "decision"
    assert event["need_id"] != canonical.id
    scoped = next(
        item for item in state.information_needs if item.id == event["need_id"]
    )
    assert scoped.status == "OPEN"
    assert scoped.retrieval_attempts == 1
    assert state.tool_history[-1].need_id == scoped.id


def test_decision_retrieval_blocks_same_query_across_observations(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    state.goal.target = "card"
    first = tool_message(
        "KB_search",
        {"query": "personal card cashback comparison"},
        call_id="decision-kb-first",
    )
    assert validate_proposal(agent, first, state).allowed
    agent._record_valid_tool_calls(first, state)
    state.control.observation_version += 1

    repeated = tool_message(
        "KB_search",
        {"query": "  PERSONAL   card cashback comparison  "},
        call_id="decision-kb-repeated",
    )
    result = validate_proposal(agent, repeated, state)

    assert not result.allowed
    assert result.reason_code == "DUPLICATE_RETRIEVAL_QUERY"
    assert state.control.duplicate_call_count == 1
    assert len(state.control.retrieval_events) == 1


def test_decision_retrieval_executes_one_query_per_turn(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    state.goal.target = "card"
    proposal = AssistantMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="decision-kb-1",
                name="KB_search",
                arguments={
                    "query": "best personal card cashback for everyday spending"
                },
                requestor="assistant",
            ),
            ToolCall(
                id="decision-kb-2",
                name="KB_search",
                arguments={"query": "credit card rewards comparison"},
                requestor="assistant",
            ),
        ],
    )

    result = validate_proposal(agent, proposal, state)

    assert result.allowed
    assert [call.id for call in proposal.tool_calls] == ["decision-kb-1"]
    assert [event["tool_call_id"] for event in state.control.retrieval_events] == [
        "decision-kb-1"
    ]


def test_policy_need_uses_formal_retrieval_node(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    need = InformationNeed(
        id="policy-card-fee",
        entity="card",
        aspect="annual_fee",
        scope="card",
        source="POLICY",
        reason="explicit_hard_constraint",
        critical=True,
        blocking=True,
    )
    state.information_needs.append(need)

    result = agent.workflow.retrieve_policy(
        {"policy_state": state, "active_need": need, "node_trace": []}
    )

    action = result["final_action"]
    assert action.tool_calls[0].name == "KB_search"
    assert state.control.retrieval_events[-1]["need_id"] == need.id
    assert state.tool_history[-1].need_id == need.id


def test_guard_missing_argument_creates_need_through_manager(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    result = validate_proposal(agent, tool_message("mutate_account", {}), state)

    recovered = recover_validation_failure(agent, result, state)

    assert result.reason_code == "MISSING_REQUIRED_ARGUMENT"
    assert recovered
    need = state.open_needs("USER")[0]
    assert need.aspect == "account_id"
    assert need.provenance == "guard_recovery"
    assert state.control.need_registry_events[-1]["accepted_count"] == 1


def test_duplicate_block_does_not_create_need(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    proposal = tool_message("mutate_account", {"account_id": "a1"})
    signature = "mutate_account:{\"account_id\":\"a1\"}"
    state.control.signature_versions[signature] = state.control.observation_version
    result = validate_proposal(agent, proposal, state)

    recovered = recover_validation_failure(agent, result, state)

    assert result.reason_code == "DUPLICATE"
    assert not recovered
    assert state.information_needs == []


def test_guard_recovery_attempt_limit_safe_stops(agent_factory):
    config = PolicyPilotConfig(
        memory_enabled=False,
        max_guard_recovery_attempts=0,
        decision_knowledge_tools_enabled=False,
    )
    agent = agent_factory(config=config)
    state = agent.get_init_state()
    result = validate_proposal(
        agent, tool_message("KB_search", {"query": "card fee"}), state
    )

    graph_result = agent.workflow.guard_recover(
        {
            "policy_state": state,
            "validation_result": result,
            "node_trace": [],
        }
    )

    assert result.reason_code == "KB_UNBOUND"
    assert graph_result["recovery_exhausted"]
    assert graph_result["final_action"].content.startswith("I cannot safely")
    assert state.information_needs == []


def test_graph_only_returns_tool_call_for_tau_environment(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    need = InformationNeed(
        id="read-account",
        entity="account",
        aspect="account_id",
        source="TOOL",
        capability="read_account",
        tool_arguments={"account_id": "a1"},
        reason="authoritative_precondition",
    )
    state.information_needs.append(need)

    result = agent.workflow.read_tool(
        {"policy_state": state, "active_need": need, "node_trace": []}
    )

    assert result["final_action"].tool_calls[0].name == "read_account"
    assert state.tool_history[-1].result_summary is None
    assert not any(item.source_type == "transaction_tool" for item in state.evidence)


def test_decision_missing_information_fallback_is_bounded_and_registered(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    message = AssistantMessage.text(
        '{"missing_information":[{"entity":"card","aspect":"eligibility",'
        '"source":"POLICY","criticality":"CRITICAL",'
        '"reason_code":"required_action_blocked","query_terms":["requirements"]}]}'
    )

    candidates = decision_fallback_candidates(message)
    assert register_decision_fallback(agent, candidates, state)
    assert state.open_needs("POLICY")[0].provenance == "decision_fallback"
    assert state.control.fallback_need_count == 1

    assert not register_decision_fallback(agent, candidates, state)
    assert state.control.fallback_need_count == 1


def test_mutation_exposed_when_dialogue_and_authoritative_facts_satisfy_preconditions(
    agent_factory,
):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    state.messages.append(AssistantMessage.text("I need to log verification now."))
    state.messages.append(UserMessage.text("I confirm my identity details."))
    for turn, aspect in enumerate(
        ("name", "user_id", "address", "email", "phone_number", "date_of_birth")
    ):
        state.facts.append(
            FactRecord(
                id=f"fact-{turn}",
                entity="user",
                aspect=aspect,
                value=f"value-{turn}",
                source="TOOL",
                turn_index=turn,
                authoritative=True,
            )
        )

    exposed = {tool.name for tool in agent._decision_tools(state)}

    assert "log_verification" in exposed


def test_guard_recovery_preserves_canonical_gap_from_blocked_query(agent_factory):
    agent = agent_factory(
        config=PolicyPilotConfig(
            memory_enabled=False,
            decision_knowledge_tools_enabled=False,
        )
    )
    state = agent.get_init_state()
    state.goal.target = "card"
    result = validate_proposal(
        agent,
        tool_message(
            "KB_search", {"query": "personal card annual fee no fee"}
        ),
        state,
    )

    assert recover_validation_failure(agent, result, state)
    need = state.open_needs("POLICY")[0]
    assert need.aspect == "annual_fee"
    assert need.query_terms == ["personal card annual fee no fee"]
