"""Paired evaluation over existing benchmark artifacts. No runs are launched here."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from policypilot.skills.evolution_models import digest
from policypilot.skills.experience import latest_skill_trace


class Trial(BaseModel):
    task_id: str
    seed: int
    scenario_group: str | None = None
    # Explicit evaluator-only labels. Include negatives with an empty list.
    expected_before: list[str]
    expected_after: list[str]
    expected_tool_sequence: list[str] | None = None
    expected_after_tool_sequence: list[str] | None = None


class EvaluationPlan(BaseModel):
    trials: list[Trial]
    builtin_ids: list[str]
    # Hash of a reviewed run configuration shared by the two arms.
    configuration_id: str = Field(min_length=1)
    reviewed_non_redundant: bool = False


class Observation(BaseModel):
    arm: Literal["baseline", "candidate"]
    release_id: str
    configuration_id: str
    task_id: str
    seed: int
    trace_id: str
    source: str
    retrieved: set[str] = Field(default_factory=set)
    selected: set[str]
    external_tool_error: bool = False
    executed_tools: list[str]
    success: bool
    tokens: int | None = Field(default=None, ge=0)
    latency: float = Field(ge=0)
    tool_calls: int = Field(ge=0)


class PromotionPolicy(BaseModel):
    min_tasks: int = Field(3, ge=2)
    min_success_delta: float = Field(0.0, ge=0, le=1)
    min_create_success_delta: float = Field(0.01, gt=0, le=1)
    min_selection_accuracy: float = Field(0.9, ge=0, le=1)
    min_execution_accuracy: float = Field(0.9, ge=0, le=1)
    max_token_growth: float = Field(0.15, ge=0)
    max_latency_growth: float = Field(0.20, ge=0)
    max_tool_call_growth: float = Field(0.10, ge=0)


class EvaluationReport(BaseModel):
    passed: bool
    reasons: list[str]
    metrics: dict[str, float]
    baseline_id: str
    candidate_release_id: str
    evidence: list[str]
    evaluation_digest: str


def run_configuration_id(config: dict) -> str:
    keys = (
        "agent_model",
        "user_model",
        "model_routing",
        "retrieval_config",
        "seed",
        "max_steps",
        "max_errors",
        "source_db_sha256_before",
        "policypilot_source_sha256",
        "runner_sha256",
        "skill_eval",
        "skill_dense",
        "builtin_skill_sha256",
        "python_hash_seed",
        "python_version",
    )
    required = {
        "user_model",
        "retrieval_config",
        "seed",
        "max_steps",
        "max_errors",
        "source_db_sha256_before",
        "policypilot_source_sha256",
        "runner_sha256",
    }
    if (
        not config.get("skill_eval")
        or not str(config.get("python_hash_seed")).isdigit()
    ):
        raise ValueError(
            "Skill A/B requires evaluation mode and a fixed PYTHONHASHSEED"
        )
    if not required <= config.keys() or not (
        {"agent_model", "model_routing"} & config.keys()
    ):
        raise ValueError("Run configuration is incomplete")
    return digest({key: config[key] for key in keys if key in config})


def from_simulation(
    simulation, path: Path, *, arm, configuration_id: str
) -> Observation:
    from policypilot.observability.evaluation import task_record_from_simulation
    from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolMessage

    if simulation.reward_info is None or simulation.seed is None:
        raise ValueError("Evaluation requires an evaluated simulation with a seed")
    metadata = latest_skill_trace(simulation)
    skills = metadata.get("skills") or {}
    release_id = skills.get("release_id")
    if (arm == "candidate") != bool(skills.get("evaluation_candidate")):
        raise ValueError("Trajectory was recorded with the wrong evaluation mode")
    if not release_id:
        raise ValueError("Trajectory lacks an instrumented Skill Library release")
    record = task_record_from_simulation(simulation, path)
    selected = set(skills.get("activated_versions", {}))
    retrieved = set(skills.get("retrieved_versions", {}))
    messages = simulation.get_messages()
    successful_calls = set()
    for message in messages:
        if isinstance(message, (ToolMessage, MultiToolMessage)):
            replies = (
                message.tool_messages
                if isinstance(message, MultiToolMessage)
                else [message]
            )
            successful_calls.update(reply.id for reply in replies if not reply.error)
    tools = [
        call.name
        for message in messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls or []
        if call.id in successful_calls
    ]
    return Observation(
        arm=arm,
        release_id=release_id,
        configuration_id=configuration_id,
        task_id=simulation.task_id,
        seed=simulation.seed,
        trace_id=(metadata.get("provenance") or {}).get("run_id") or simulation.id,
        source=str(path),
        retrieved=retrieved,
        selected=selected,
        executed_tools=tools,
        success=record.success,
        tokens=(
            record.agent_input_tokens + record.agent_output_tokens
            if record.agent_input_tokens is not None
            and record.agent_output_tokens is not None
            else None
        ),
        latency=simulation.duration,
        tool_calls=record.agent_tool_calls,
        external_tool_error=bool(record.tool_error_count),
    )


def attribute(
    observation: Observation,
    *,
    expected_skills,
    expected_tools,
    reviewed_content_defect: bool = False,
):
    """Conservative attribution. A content defect needs a reviewed contradiction."""
    if observation.success:
        return "unknown"
    if observation.external_tool_error:
        return "tool"
    expected = set(expected_skills)
    if expected - observation.retrieved:
        return "retrieval"
    if expected - observation.selected or observation.selected - expected:
        return "activation"
    if reviewed_content_defect:
        return "content"
    if expected_tools and not _subsequence(expected_tools, observation.executed_tools):
        return "execution"
    return "unknown"


def _expected_tools(trial, arm):
    if arm == "candidate" and trial.expected_after_tool_sequence is not None:
        return trial.expected_after_tool_sequence
    return trial.expected_tool_sequence


def _subsequence(expected, actual):
    stream = iter(actual)
    return all(any(item == target for item in stream) for target in expected)


def evaluate(
    candidate, baseline, after, plan, observations, policy
) -> EvaluationReport:
    trials = {(t.task_id, t.seed): t for t in plan.trials}
    task_ids = {task for task, _ in trials}
    if len(trials) != len(plan.trials) or len(task_ids) < policy.min_tasks:
        raise ValueError(
            "Evaluation requires distinct held-out tasks and unique trial pairs"
        )
    if "unknown-task" in candidate.training_task_ids or task_ids.intersection(
        candidate.training_task_ids
    ):
        raise ValueError("Independent evaluation tasks cannot be verified")
    if candidate.training_scenario_groups and (
        any(not trial.scenario_group for trial in trials.values())
        or set(candidate.training_scenario_groups).intersection(
            trial.scenario_group for trial in trials.values()
        )
    ):
        raise ValueError("Evaluation requires independent scenario groups")
    seen_traces = set(candidate.trace_ids)
    paired = {"baseline": {}, "candidate": {}}
    for row in observations:
        key = row.task_id, row.seed
        expected_release = baseline.id if row.arm == "baseline" else after.id
        if (
            row.release_id != expected_release
            or row.configuration_id != plan.configuration_id
            or key not in trials
            or row.trace_id in seen_traces
            or key in paired[row.arm]
        ):
            raise ValueError("Mismatched or reused evaluation trajectory")
        paired[row.arm][key] = row
        seen_traces.add(row.trace_id)
    if any(set(rows) != set(trials) for rows in paired.values()):
        raise ValueError("Both arms must contain exactly one observation per trial")
    metrics = {}
    reasons = []
    for arm, rows in paired.items():
        selection = []
        retrieval = []
        execution = []
        for key, row in rows.items():
            trial = trials[key]
            expected = (
                trial.expected_before if arm == "baseline" else trial.expected_after
            )
            selection.append(row.selected == set(expected))
            if expected:
                retrieval.append(set(expected) <= row.retrieved)
            sequence = _expected_tools(trial, arm)
            if sequence is not None:
                execution.append(
                    _subsequence(sequence, row.executed_tools)
                    if sequence
                    else not row.executed_tools
                )
        metrics[f"{arm}_success"] = sum(r.success for r in rows.values()) / len(rows)
        metrics[f"{arm}_selection"] = sum(selection) / len(selection)
        if retrieval:
            metrics[f"{arm}_retrieval"] = sum(retrieval) / len(retrieval)
        if execution:
            metrics[f"{arm}_execution"] = sum(execution) / len(execution)
    if any(
        not all(r.success for k, r in paired["candidate"].items() if k[0] == task)
        and all(r.success for k, r in paired["baseline"].items() if k[0] == task)
        for task in task_ids
    ):
        reasons.append("A previously successful task regressed")
    operation = candidate.proposal.operation
    skill = candidate.proposal.skill
    if skill:
        if operation == "CREATE" and not plan.reviewed_non_redundant:
            reasons.append("CREATE requires independent review of non-redundancy")
        positive = [t for t in trials.values() if skill.skill_id in t.expected_after]
        negative = [
            t for t in trials.values() if skill.skill_id not in t.expected_after
        ]
        if not positive or not negative:
            reasons.append("Missing positive or negative activation cases")
        if any(_expected_tools(t, "candidate") is None for t in positive):
            reasons.append("Missing execution expectations for positive cases")
        if any(
            skill.skill_id in paired["candidate"][t.task_id, t.seed].selected
            for t in negative
        ):
            reasons.append("Candidate activated on a negative case")
        if operation == "CREATE" and not any(
            not paired["baseline"][t.task_id, t.seed].success
            and paired["candidate"][t.task_id, t.seed].success
            for t in positive
        ):
            reasons.append("No utility gain on a new skill's positive cases")
    elif "candidate_execution" not in metrics:
        reasons.append("Missing execution regression cases")
    min_delta = (
        policy.min_create_success_delta
        if operation == "CREATE"
        else policy.min_success_delta
    )
    if metrics["candidate_success"] - metrics["baseline_success"] + 1e-9 < min_delta:
        reasons.append("Success improvement below threshold")
    if metrics.get("candidate_retrieval", 1.0) < policy.min_selection_accuracy:
        reasons.append("Retrieval coverage below threshold")
    if metrics["candidate_selection"] < policy.min_selection_accuracy:
        reasons.append("Selection accuracy below threshold")
    if metrics.get("candidate_execution", 0) < policy.min_execution_accuracy:
        reasons.append("Execution accuracy below threshold")
    for field, limit in (
        ("tokens", policy.max_token_growth),
        ("latency", policy.max_latency_growth),
        ("tool_calls", policy.max_tool_call_growth),
    ):
        values = [
            [getattr(r, field) for r in rows.values()] for rows in paired.values()
        ]
        if any(None in arm for arm in values):
            reasons.append(f"Missing {field} measurements")
            continue
        a, b = (sum(arm) / len(arm) for arm in values)
        metrics[f"baseline_{field}"] = a
        metrics[f"candidate_{field}"] = b
        if b > a * (1 + limit) + 1e-9:
            reasons.append(f"{field} growth above threshold")
    return EvaluationReport(
        passed=not reasons,
        reasons=reasons,
        metrics=metrics,
        baseline_id=baseline.id,
        candidate_release_id=after.id,
        evidence=[row.source for row in observations],
        evaluation_digest=digest(
            [
                candidate.model_dump(mode="json"),
                plan.model_dump(mode="json"),
                policy.model_dump(mode="json"),
                [
                    row.model_dump(mode="json", exclude={"selected", "retrieved"})
                    | {
                        "selected": sorted(row.selected),
                        "retrieved": sorted(row.retrieved),
                    }
                    for row in observations
                ],
            ]
        ),
    )
