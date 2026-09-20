import pytest

from policypilot.compression import ToolContextCompressor
from policypilot.config import PolicyPilotConfig
from policypilot.context import build_agent_context
from policypilot.evaluation import task_record_from_simulation
from policypilot.llm_runtime import LLMRuntime
from policypilot.model_routing import ModelRouting, resolve_model_routing
from policypilot.planning import LLMSemanticPlanner, SemanticPlan
from policypilot.skills.matcher import LLMSkillFallback, SkillMatcher, SkillSelection
from policypilot.skills.models import SkillMetadata
from policypilot.state import PolicyPilotState, StructuredGoal
from tau2.data_model.message import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from tau2.data_model.simulation import (
    DBCheck,
    RewardInfo,
    SimulationRun,
    TerminationReason,
)
from tau2.utils.llm_utils import to_litellm_messages


def response(content, *, prompt=10, completion=3):
    return AssistantMessage(
        role="assistant",
        content=content,
        usage={
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_cache_hit_tokens": 4,
        },
        cost=0.001,
        generation_time_seconds=0.02,
    )


def test_model_routing_preserves_existing_model_and_supports_env(monkeypatch):
    for name in (
        "POLICYPILOT_LIGHT_MODEL",
        "LIGHT_MODEL",
        "DEEPSEEK_MODEL",
        "MODEL",
        "POLICYPILOT_MAIN_DECISION_MODEL",
        "MAIN_DECISION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    routing = resolve_model_routing("deepseek/deepseek-chat", PolicyPilotConfig())
    assert routing.light_model == "deepseek/deepseek-chat"
    assert routing.main_model == "deepseek/deepseek-chat"

    monkeypatch.setenv("POLICYPILOT_LIGHT_MODEL", "deepseek/light")
    monkeypatch.setenv("POLICYPILOT_MAIN_DECISION_MODEL", "deepseek/strong")
    routing = resolve_model_routing("fallback", PolicyPilotConfig())
    assert routing.model_for("semantic_planner") == "deepseek/light"
    assert routing.model_for("decision") == "deepseek/strong"


def test_structured_runtime_repairs_once_and_records_metrics():
    outputs = iter(["not-json", '{"skill_ids":["known"]}'])

    def fake_generate(**kwargs):
        return response(next(outputs))

    runtime = LLMRuntime(
        ModelRouting("light", "main"),
        generate_fn=fake_generate,
        structured_repair_attempts=1,
    )
    result = runtime.call_structured(
        "skill_matcher", [SystemMessage(role="system", content="select")], SkillSelection
    )

    assert result.skill_ids == ["known"]
    assert len(runtime.traces) == 2
    assert runtime.traces[0].structured_output_valid is False
    assert runtime.traces[1].structured_output_valid is True
    assert runtime.traces[1].retry_count == 1


class StaticRuntime:
    def __init__(self, result):
        self.result = result
        self.messages = None

    def call_structured(self, node, messages, schema, **kwargs):
        self.messages = messages
        return self.result


def test_semantic_planner_uses_compact_user_semantics_only():
    runtime = StaticRuntime(
        SemanticPlan(intent="INFORMATIONAL", model_route="LIGHT")
    )
    planner = LLMSemanticPlanner(runtime)
    state = PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")],
        goal=StructuredGoal(objective="Compare cards", target="card"),
    )
    state.messages.append(
        ToolMessage(role="tool", id="raw", requestor="assistant", content="X" * 20000)
    )

    plan = planner.plan(state, "I prefer no annual fee.", 2)

    payload = runtime.messages[1].content
    assert plan.model_route == "LIGHT"
    assert "I prefer no annual fee" in payload
    assert "X" * 100 not in payload


def test_skill_llm_is_only_fallback_and_cannot_invent_ids(tmp_path):
    metadata = [SkillMetadata(name="known", description="known", path=tmp_path)]
    runtime = StaticRuntime(SkillSelection(skill_ids=["known", "invented"]))
    matcher = SkillMatcher(semantic_fallback=LLMSkillFallback(runtime))
    state = PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")],
        goal=StructuredGoal(objective="Unusual request"),
    )
    assert matcher.match(state, metadata, event="NEW_GOAL") == ["known"]


def test_context_compressor_runs_only_over_budget(tools):
    runtime = StaticRuntime(
        type(
            "Compressed",
            (),
            {
                "summary": "relevant status",
                "retained_fields": ["status"],
                "omitted_fields": ["noise"],
            },
        )()
    )
    compressor = ToolContextCompressor(runtime, max_chars=100)
    state = PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")],
        goal=StructuredGoal(objective="Check status", target="account"),
    )
    state.messages.append(
        ToolMessage(role="tool", id="tool-1", requestor="assistant", content="A" * 2000)
    )
    build_agent_context(
        state,
        tools,
        PolicyPilotConfig(max_decision_context_chars=10000),
        compressor=compressor,
    )
    assert runtime.messages is None

    compressed = build_agent_context(
        state,
        tools,
        PolicyPilotConfig(max_decision_context_chars=100),
        compressor=compressor,
    )
    assert runtime.messages is not None
    assert "payload_ref" in " ".join(message.content or "" for message in compressed.messages)


def test_evaluation_uses_per_node_metrics_for_hidden_auxiliary_calls(tmp_path):
    traces = [
        {
            "run_id": "run",
            "task_id": "task_x",
            "node": "semantic_planner",
            "model": "deepseek/light",
            "provider": "deepseek",
            "input_tokens": 100,
            "output_tokens": 10,
            "cached_input_tokens": 20,
            "latency_ms": 200,
            "cost": 0.001,
            "structured_output_valid": True,
            "retry_count": 0,
            "error": None,
        },
        {
            "run_id": "run",
            "task_id": "task_x",
            "node": "decision",
            "model": "deepseek/main",
            "provider": "deepseek",
            "input_tokens": 300,
            "output_tokens": 20,
            "cached_input_tokens": 0,
            "latency_ms": 500,
            "cost": 0.004,
            "structured_output_valid": None,
            "retry_count": 0,
            "error": None,
        },
    ]
    assistant = response("done")
    assistant.raw_data = {"policypilot_v1": {"llm_calls": traces}}
    simulation = SimulationRun(
        id="sim",
        task_id="task_x",
        start_time="now",
        end_time="later",
        duration=1.0,
        termination_reason=TerminationReason.USER_STOP,
        messages=[assistant],
        reward_info=RewardInfo(reward=1.0, db_check=DBCheck(db_match=True, db_reward=1.0)),
    )

    record = task_record_from_simulation(simulation, tmp_path / "result.json")

    assert record.lightweight_llm_calls == 1
    assert record.main_decision_calls == 1
    assert record.agent_input_tokens == 400
    assert record.agent_cost == pytest.approx(0.005)


def test_deepseek_thinking_history_preserves_reasoning_content():
    generated = AssistantMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="KB_search",
                arguments={"query": "terms"},
                requestor="assistant",
            )
        ],
        raw_data={
            "choices": [
                {"message": {"reasoning_content": "Need authoritative terms."}}
            ]
        },
    )
    deterministic = AssistantMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call-2",
                name="KB_search",
                arguments={"query": "limits"},
                requestor="assistant",
            )
        ],
    )

    converted = to_litellm_messages(
        [generated, deterministic], preserve_reasoning_content=True
    )

    assert converted[0]["reasoning_content"] == "Need authoritative terms."
    assert converted[1]["reasoning_content"] == ""
