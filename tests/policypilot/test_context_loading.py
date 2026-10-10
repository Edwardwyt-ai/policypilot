from dataclasses import replace

import pytest

from policypilot.config import PolicyPilotConfig
from policypilot.context_loading import ContextBudgetError, context_tool, load_snapshot
from policypilot.provenance import ContextManifest, record_payload
from policypilot.state import PolicyPilotState, StructuredGoal
from policypilot.workflow.context import build_agent_context
from tau2.data_model.message import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)


def config(**kwargs):
    return replace(
        PolicyPilotConfig(),
        memory_enabled=False,
        skills_enabled=False,
        laya_acquisition_enabled=False,
        coverage_llm_enabled=False,
        **kwargs,
    )


def state_with_history():
    return PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="Trusted rules")],
        goal=StructuredGoal(objective="Check account status"),
        messages=[
            UserMessage.text("Old preference: no annual fee. " * 1000),
            UserMessage.text("Check my account status."),
        ],
    )


def test_under_window_preserves_entire_dialogue_without_archival():
    state = state_with_history()
    context = build_agent_context(
        state,
        [],
        config(max_decision_context_chars=60000, max_decision_context_tokens=20000),
    )
    assert context.messages[-2:] == state.messages
    assert not state.raw_payloads
    assert not state.context_manifests[-1].metadata["loadable_refs"]


def test_overflow_archives_and_loads_exact_omitted_snapshot():
    state = state_with_history()
    cfg = config(max_decision_context_chars=10000)
    context = build_agent_context(state, [], cfg)
    assert context.estimated_size < 10000
    assert state.context_manifests[-1].metadata["compressed"]
    ref = state.context_manifests[-1].metadata["loadable_refs"][0]
    request = {"payload_ref": ref, "offset": 19, "length": 70}
    page = load_snapshot(state, request, cfg, previous_requests=[], loaded_chars=0)
    raw = next(p.raw_content for p in state.raw_payloads if p.payload_id == ref)
    assert page["content"] == raw[19:89]
    assert page["next_offset"] == 89
    assert page["historical_snapshot"]
    assert not state.facts and not state.evidence
    assert context_tool().openai_schema["function"]["name"] == "load_context_ref"


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "foreign",
        "stale",
        "disabled",
        "budget",
        "duplicate",
        "offset",
        "extra",
    ],
)
def test_load_capability_and_budget_boundaries(case):
    state = PolicyPilotState(system_messages=[])
    payload = record_payload(
        state, source_type="TOOL", raw_content='{"nested": {"status": "old"}}'
    )
    state.context_manifests.append(
        ContextManifest(
            run_id=state.run_id,
            turn_id=0,
            model="test",
            prompt_version="test",
            metadata={"loadable_refs": [payload.payload_id]},
        )
    )
    request = {"payload_ref": payload.payload_id, "offset": 0, "length": 10}
    cfg, previous, loaded = config(), [], 0
    if case == "unknown":
        request["payload_ref"] = "not-listed"
    elif case == "foreign":
        payload.run_id = "another-run"
    elif case == "stale":
        state.messages.append(UserMessage.text("new turn"))
    elif case == "disabled":
        cfg = config(context_rehydration_enabled=False)
    elif case == "budget":
        loaded = cfg.max_rehydrated_context_chars
    elif case == "duplicate":
        previous = [request]
    elif case == "offset":
        request["offset"] = 10000
    else:
        request["path"] = "hidden_tasks.json"
    with pytest.raises(ValueError):
        load_snapshot(
            state, request, cfg, previous_requests=previous, loaded_chars=loaded
        )


def test_impossible_pinned_window_fails_closed():
    with pytest.raises(ContextBudgetError):
        build_agent_context(
            state_with_history(), [], config(max_decision_context_chars=100)
        )


def test_summary_failure_keeps_pinned_state_and_recoverable_reference():
    class BrokenCompressor:
        def compress_context(self, **kwargs):
            raise ValueError("bad summary response")

    state = state_with_history()
    result = build_agent_context(
        state,
        [],
        config(max_decision_context_chars=10000),
        compressor=BrokenCompressor(),
    )
    assert "Check account status" in result.structured_summary
    assert state.context_manifests[-1].metadata["loadable_refs"]
    assert (
        "bad summary response" in state.control.context_compressor_events[-1]["error"]
    )


def test_snapshot_loading_respects_remaining_character_budget():
    state = state_with_history()
    cfg = config(max_decision_context_chars=10000)
    build_agent_context(state, [], cfg)
    ref = state.context_manifests[-1].metadata["loadable_refs"][0]
    page = load_snapshot(
        state,
        {"payload_ref": ref, "length": 1000},
        cfg,
        previous_requests=[],
        loaded_chars=cfg.max_rehydrated_context_chars - 7,
    )
    assert len(page["content"]) == 7
    with pytest.raises(ValueError, match="call budget"):
        load_snapshot(
            state,
            {"payload_ref": ref},
            cfg,
            previous_requests=[{}] * cfg.max_context_load_calls,
            loaded_chars=0,
        )


def test_graph_handles_explicit_load_without_external_tool_or_state_promotion(
    agent_factory, monkeypatch
):
    agent = agent_factory(config=config(max_decision_context_chars=10000))
    state = state_with_history()
    monkeypatch.setattr(agent, "_observe", lambda *args: [])
    seen = []

    def decision(messages, state, call_name):
        seen.append(messages)
        if len(seen) == 1:
            assert "load_context_ref" in {t.name for t in agent._decision_tools(state)}
            ref = state.context_manifests[-1].metadata["loadable_refs"][0]
            return AssistantMessage.text(
                "",
                tool_calls=[
                    ToolCall(
                        id="load-1",
                        name="load_context_ref",
                        arguments={"payload_ref": ref, "length": 80},
                    )
                ],
            )
        assert isinstance(messages[-1], ToolMessage)
        assert "historical_snapshot" in messages[-1].content
        return AssistantMessage.text(
            "Answer from historical context, not a live balance."
        )

    monkeypatch.setattr(agent, "_call_llm", decision)
    result = agent.workflow.invoke(state.messages[-1], state)
    assert not result["final_action"].tool_calls
    assert "load_context" in result["node_trace"]
    assert "hydrate_context" not in result["node_trace"]
    assert len(seen) == 2
    assert not state.facts and not state.evidence
    assert len(state.messages) == 3  # Only the final assistant reply is added.
    assert state.control.context_rehydration_events[-1]["status"] == "LOADED"
