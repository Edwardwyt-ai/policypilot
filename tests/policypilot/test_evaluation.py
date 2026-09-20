"""Offline tests for the durable PolicyPilot V1 evaluation harness."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from policypilot.evaluation import (
    TaskEvaluationRecord,
    aggregate_records,
    failure_record_from_simulation,
    percentile,
    run_evaluation_batch,
    task_record_from_simulation,
    write_config,
)
from tau2.data_model.message import (
    AssistantMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.data_model.simulation import (
    ActionCheck,
    DBCheck,
    RewardInfo,
    SimulationRun,
    TerminationReason,
)
from tau2.data_model.tasks import Action


def _simulation(task_id: str, reward: float = 1.0) -> SimulationRun:
    tool_call = ToolCall(
        id=f"call-{task_id}",
        name="KB_search",
        arguments={"query": "cash deposit policy", "top_k": 3},
        requestor="assistant",
    )
    metadata = {
        "context_estimated_size": 1200,
        "duplicate_call_count": 1,
        "error_count": 1,
        "guard_allow_count": 1,
        "guard_block_count": 1,
        "guard_recover_count": 1,
        "recovery_success_count": 1,
        "error_category_counts": {"duplicate_tool_call": 1},
        "guard_block_reasons": ["duplicate blocked"],
        "recovery_categories": ["duplicate_tool_call"],
        "current_goal": "understand cash deposits",
        "open_questions": [{"key": "limit", "question": "What is the limit?"}],
        "known_facts": [
            {
                "key": "account_id",
                "value": "acc-1",
                "source_type": "transaction_tool",
                "verified": True,
            }
        ],
    }
    messages = [
        UserMessage.text(
            "Tell me the cash deposit policy",
            usage={"prompt_tokens": 20, "completion_tokens": 10},
            generation_time_seconds=0.4,
        ),
        AssistantMessage.text(
            "",
            tool_calls=[tool_call],
            usage={"prompt_tokens": 100, "completion_tokens": 25},
            generation_time_seconds=1.5,
            raw_data={"policypilot_v1": metadata},
        ),
        ToolMessage(
            id=tool_call.id,
            role="tool",
            content=(
                "1. Cash deposit policy\n"
                "ID: policy-cash-1\n"
                "Score: 0.91\n"
                "Content: Deposits are supported."
            ),
            requestor="assistant",
        ),
        AssistantMessage.text(
            "Here is the policy.",
            usage={"prompt_tokens": 150, "completion_tokens": 30},
            generation_time_seconds=2.0,
            raw_data={"policypilot_v1": {**metadata, "context_estimated_size": 1800}},
        ),
    ]
    action = Action(
        action_id="a1",
        name="KB_search",
        arguments={"query": "cash deposit policy", "top_k": 3},
    )
    return SimulationRun(
        id=f"sim-{task_id}",
        task_id=task_id,
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:00:04",
        duration=4.0,
        termination_reason=TerminationReason.USER_STOP,
        agent_cost=0.03,
        user_cost=0.01,
        reward_info=RewardInfo(
            reward=reward,
            db_check=DBCheck(db_match=reward == 1.0, db_reward=reward),
            action_checks=[
                ActionCheck(action=action, action_match=reward == 1.0, action_reward=reward)
            ],
        ),
        messages=messages,
    )


def test_task_metrics_use_structured_trajectory_fields(tmp_path: Path) -> None:
    record = task_record_from_simulation(_simulation("task_001"), tmp_path / "results.json")

    assert record.success is True
    assert record.db_check is True
    assert (record.required_actions_completed, record.required_actions_total) == (1, 1)
    assert (record.agent_tool_calls, record.user_tool_calls) == (1, 0)
    assert record.context_size_per_call_chars == [1200, 1800]
    assert record.avg_context_size_chars == 1500
    assert record.agent_llm_latency_seconds == 3.5
    assert record.user_llm_latency_seconds == 0.4
    assert (record.input_tokens, record.output_tokens) == (270, 65)
    assert record.total_cost == pytest.approx(0.04)
    assert record.retrieval_latency_seconds is None
    assert "retrieval_latency_seconds" in record.unavailable_metrics


def test_message_cost_is_used_when_tau2_episode_cost_is_missing(tmp_path: Path) -> None:
    simulation = _simulation("task_cost").model_copy(
        update={"agent_cost": None, "user_cost": None}
    )
    messages = simulation.get_messages()
    messages[0].cost = 0.01
    messages[1].cost = 0.02
    messages[3].cost = 0.03

    record = task_record_from_simulation(simulation, tmp_path / "results.json")

    assert record.agent_cost == pytest.approx(0.05)
    assert record.user_cost == pytest.approx(0.01)
    assert record.total_cost == pytest.approx(0.06)


def test_percentile_and_summary_calculations() -> None:
    assert percentile([0, 10, 20, 30], 0.50) == 15
    assert percentile([0, 10, 20, 30], 0.95) == pytest.approx(28.5)
    assert percentile([], 0.50) is None
    with pytest.raises(ValueError):
        percentile([1], 1.1)

    first = TaskEvaluationRecord(
        task_id="task_001",
        reward=1,
        success=True,
        db_check=True,
        required_actions_total=2,
        required_actions_completed=2,
        total_steps=10,
        agent_tool_calls=3,
        total_tool_calls=4,
        knowledge_retrieval_calls=2,
        guard_block_count=0,
        context_size_per_call_chars=[100, 200],
        episode_latency_seconds=10,
        agent_cost=0.3,
        user_cost=0.1,
    )
    second = TaskEvaluationRecord(
        task_id="task_002",
        reward=0,
        success=False,
        db_check=False,
        required_actions_total=2,
        required_actions_completed=1,
        termination_reason="max_steps",
        total_steps=20,
        guard_block_count=2,
        context_size_per_call_chars=[300],
        episode_latency_seconds=30,
        agent_cost=0.2,
        user_cost=0.1,
    )
    summary = aggregate_records([first, second])

    assert summary.success_rate == 0.5
    assert summary.average_reward == 0.5
    assert summary.db_success_rate == 0.5
    assert summary.required_action_completion_rate == 0.75
    assert summary.avg_steps == 15
    assert summary.avg_guard_blocks == 1
    assert summary.max_step_termination_rate == 0.5
    assert summary.p50_context_size_chars == 200
    assert summary.avg_episode_latency_seconds == 20
    assert summary.total_cost == pytest.approx(0.7)


def test_failure_record_contains_offline_evidence_only(tmp_path: Path) -> None:
    simulation = _simulation("task_fail", reward=0.0)
    failure = failure_record_from_simulation(simulation, tmp_path / "results.json")

    assert failure.tool_calls[0].name == "KB_search"
    assert failure.tool_calls[0].canonical_args == (
        '{"query":"cash deposit policy","top_k":3}'
    )
    assert failure.retrieval_queries == ["cash deposit policy"]
    assert failure.retrieved_documents[0]["document_id"] == "policy-cash-1"
    assert failure.guard_block_reasons == ["duplicate blocked"]
    assert failure.current_goal == "understand cash deposits"
    assert failure.final_known_facts[0]["key"] == "account_id"
    assert len(failure.last_trajectory) == 4


def test_batch_continues_after_exception_and_outputs_reload(tmp_path: Path) -> None:
    run_dir = tmp_path / "eval"
    source_db = tmp_path / "db.json"
    source_db.write_text('{"stable": true}', encoding="utf-8")
    attempted = []

    def run_task(task_id: str):
        attempted.append(task_id)
        if task_id == "task_boom":
            raise RuntimeError("simulated API outage")
        result_path = run_dir / "tasks" / task_id / "results.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text('{"trajectory": true}', encoding="utf-8")
        return _simulation(task_id, reward=1.0), result_path

    result = run_evaluation_batch(
        ["task_001", "task_boom", "task_002"],
        run_dir,
        run_task,
        source_db_path=source_db,
    )

    assert attempted == ["task_001", "task_boom", "task_002"]
    assert len(result.task_records) == 3
    assert result.summary.successful_tasks == 2
    assert result.summary.runner_error_tasks == 1
    assert result.summary.source_db_unchanged is True
    assert len(result.failure_records) == 1
    assert result.failure_records[0].error_type == "RuntimeError"

    task_rows = [
        json.loads(line)
        for line in (run_dir / "task_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    failure_rows = [
        json.loads(line)
        for line in (run_dir / "failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    with (run_dir / "summary.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(task_rows) == len(csv_rows) == 3
    assert len(failure_rows) == 1
    assert summary["total_tasks"] == 3


def test_evaluation_never_serializes_hidden_ground_truth(tmp_path: Path) -> None:
    hidden_marker = "HIDDEN_REFERENCE_ACTION_DO_NOT_EXPOSE"
    simulation = _simulation("task_hidden", reward=0.0)
    record = task_record_from_simulation(simulation, tmp_path / "results.json")
    failure = failure_record_from_simulation(simulation, tmp_path / "results.json")

    serialized = record.model_dump_json() + failure.model_dump_json()
    assert hidden_marker not in serialized
    # The extraction API accepts only a completed SimulationRun, never a benchmark Task.
    assert "evaluation_criteria" not in serialized
    assert "required_documents" not in serialized


def test_config_is_json_and_contains_no_environment_secret(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write_config(path, {"agent_model": "deepseek/deepseek-chat", "seed": 0})
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded["seed"] == 0
    assert "API_KEY" not in path.read_text(encoding="utf-8")
