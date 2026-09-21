from policypilot.config import PolicyPilotConfig
from policypilot.workflow.context import build_agent_context
from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage


def config():
    return PolicyPilotConfig(
        memory_enabled=False,
        semantic_planner_enabled=False,
        skill_llm_fallback_enabled=False,
    )


def test_user_observation_has_raw_payload_evidence_and_fact_chain(agent_factory):
    agent = agent_factory(config=config(), task_id="task-provenance")
    state = agent.get_init_state()

    agent._observe(UserMessage.text("My account_id is account-1234."), state)

    payload = state.raw_payloads[-1]
    evidence = state.evidence[-1]
    fact = state.get_fact("account_id", "user")
    assert payload.run_id == state.run_id
    assert payload.source_type == "USER"
    assert evidence.payload_ref == payload.payload_id
    assert evidence.event_id == payload.event_id
    assert fact is not None and fact.evidence_ref == evidence.evidence_id


def test_tool_observation_preserves_payload_reference(agent_factory):
    agent = agent_factory(config=config())
    state = agent.get_init_state()
    call = ToolCall(
        id="read-1",
        name="read_account",
        arguments={"account_id": "a1"},
        requestor="assistant",
    )
    state.messages.append(AssistantMessage(role="assistant", tool_calls=[call]))

    agent._observe(
        ToolMessage(
            role="tool",
            id="read-1",
            requestor="assistant",
            content='{"account_id":"a1","status":"OPEN"}',
        ),
        state,
    )

    payload = state.raw_payloads[-1]
    evidence = state.evidence[-1]
    assert evidence.evidence_id == "read-1"
    assert evidence.payload_ref == payload.payload_id
    assert payload.tool_call_id == "read-1"
    assert state.get_fact("status") is not None
    assert state.get_fact("status").evidence_ref == evidence.evidence_id


def test_context_manifest_records_the_actual_selected_surface(agent_factory):
    agent = agent_factory(config=config())
    state = agent.get_init_state()
    agent._observe(UserMessage.text("Compare cards with no annual fee."), state)
    tools = agent._decision_tools(state)

    context = build_agent_context(
        state,
        tools,
        agent.config,
        skills=["constraint-aware-recommendation"],
        model=agent._decision_model(),
        prompt_version=agent.config.prompt_version,
    )

    manifest = state.context_manifests[-1]
    assert context.context_id == manifest.context_id
    assert manifest.fact_ids
    assert manifest.evidence_ids
    assert manifest.need_ids
    assert "KB_search" in manifest.exposed_tools
    assert manifest.skills == ["constraint-aware-recommendation"]
    evidence = next(item for item in state.evidence if item.evidence_id in manifest.evidence_ids)
    payload = next(item for item in state.raw_payloads if item.payload_id == evidence.payload_ref)
    assert payload.event_id == evidence.event_id
