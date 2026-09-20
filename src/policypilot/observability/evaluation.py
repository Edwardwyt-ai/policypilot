"""Offline metrics and durable output helpers for PolicyPilot V1 evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from policypilot.errors import PolicyPilotErrorType
from policypilot.evidence import parse_policy_references, summarize_text
from policypilot.observability.metrics import metrics_from_simulation
from policypilot.tool_policy import canonicalize_arguments, is_knowledge_tool
from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage
from tau2.data_model.simulation import SimulationRun

UNAVAILABLE_METRICS = [
    "context_section_sizes",
    "retrieval_latency_seconds",
    "tool_latency_seconds",
]


class ToolCallTrace(BaseModel):
    """Compact, deterministic representation of one trajectory tool call."""

    name: str
    canonical_args: str
    requestor: Literal["assistant", "user"]
    success: bool | None
    error: bool | None


class NodeLLMMetrics(BaseModel):
    calls: int = 0
    model: str | None = None
    provider: str | None = None
    latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost: float = 0.0
    cost_available: bool = True
    structured_valid_calls: int = 0
    structured_invalid_calls: int = 0
    retry_count: int = 0
    error_count: int = 0


class TaskEvaluationRecord(BaseModel):
    """Metrics for one task, including runner failures with no trajectory."""

    task_id: str
    status: Literal["completed", "error"] = "completed"
    error_type: str | None = None
    error_message: str | None = None
    reward: float | None = None
    db_check: bool | None = None
    db_reward: float | None = None
    required_actions_total: int = 0
    required_actions_completed: int = 0
    termination_reason: str | None = None
    success: bool = False
    total_steps: int = 0
    agent_tool_calls: int = 0
    user_tool_calls: int = 0
    total_tool_calls: int = 0
    knowledge_retrieval_calls: int = 0
    duplicate_call_count: int = 0
    tool_error_count: int = 0
    guard_allow_count: int | None = None
    guard_block_count: int | None = None
    guard_recover_count: int | None = None
    recovery_count: int = 0
    recovery_success_count: int | None = None
    error_category_counts: dict[str, int] = Field(default_factory=dict)
    agent_llm_calls: int = 0
    lightweight_llm_calls: int = 0
    main_decision_calls: int = 0
    node_llm_metrics: dict[str, NodeLLMMetrics] = Field(default_factory=dict)
    context_size_per_call_chars: list[int] = Field(default_factory=list)
    avg_context_size_chars: float | None = None
    max_context_size_chars: int | None = None
    min_context_size_chars: int | None = None
    episode_latency_seconds: float | None = None
    post_evaluation_llm_latency_seconds: float = 0.0
    end_to_end_latency_seconds: float | None = None
    agent_llm_latency_seconds: float | None = None
    user_llm_latency_seconds: float | None = None
    retrieval_latency_seconds: float | None = None
    tool_latency_seconds: float | None = None
    agent_cost: float | None = None
    user_cost: float | None = None
    total_cost: float | None = None
    cost_is_lower_bound: bool = False
    agent_input_tokens: int | None = None
    agent_output_tokens: int | None = None
    user_input_tokens: int | None = None
    user_output_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    result_path: str | None = None
    unavailable_metrics: list[str] = Field(default_factory=lambda: list(UNAVAILABLE_METRICS))


class FailureRecord(BaseModel):
    """Compact trajectory evidence for later human failure analysis."""

    task_id: str
    reward: float | None = None
    termination_reason: str | None = None
    total_steps: int = 0
    error_type: str | None = None
    error_message: str | None = None
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)
    retrieved_documents: list[dict[str, Any]] = Field(default_factory=list)
    guard_block_reasons: list[str] = Field(default_factory=list)
    recovery_categories: list[str] = Field(default_factory=list)
    current_goal: str | None = None
    final_open_questions: list[dict[str, str]] = Field(default_factory=list)
    final_known_facts: list[dict[str, Any]] = Field(default_factory=list)
    last_trajectory: list[dict[str, Any]] = Field(default_factory=list)
    result_path: str | None = None


class BatchSummary(BaseModel):
    """Aggregate metrics for one evaluation batch."""

    total_tasks: int
    completed_tasks: int
    runner_error_tasks: int
    successful_tasks: int
    failed_tasks: int
    success_rate: float
    average_reward: float
    db_success_rate: float | None
    required_action_completion_rate: float | None
    avg_steps: float
    avg_agent_tool_calls: float
    avg_total_tool_calls: float
    avg_retrieval_calls: float
    avg_duplicate_calls: float
    avg_guard_blocks: float | None
    avg_recovery_count: float
    max_step_termination_rate: float
    avg_context_size_chars: float | None
    p50_context_size_chars: float | None
    p95_context_size_chars: float | None
    avg_episode_latency_seconds: float | None
    p50_episode_latency_seconds: float | None
    p95_episode_latency_seconds: float | None
    total_agent_cost: float
    total_user_cost: float
    total_cost: float
    avg_cost_per_task: float
    cost_is_lower_bound: bool = False
    total_input_tokens: int | None
    total_output_tokens: int | None
    success_task_ids: list[str]
    failed_task_ids: list[str]
    termination_reason_counts: dict[str, int]
    error_category_counts: dict[str, int]
    source_db_sha256_before: str | None = None
    source_db_sha256_after: str | None = None
    source_db_unchanged: bool | None = None
    unavailable_metrics: list[str] = Field(default_factory=lambda: list(UNAVAILABLE_METRICS))


class BatchEvaluationResult(BaseModel):
    """Return value used by the CLI and unit tests."""

    task_records: list[TaskEvaluationRecord]
    failure_records: list[FailureRecord]
    summary: BatchSummary


def sha256_file(path: Path) -> str:
    """Hash a file without modifying it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: Sequence[float | int], quantile: float) -> float | None:
    """Return a linearly interpolated percentile for quantile in [0, 1]."""
    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _latest_metadata(simulation: SimulationRun) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for message in simulation.get_messages():
        if not isinstance(message, AssistantMessage) or not message.raw_data:
            continue
        value = message.raw_data.get("policypilot_v1")
        if isinstance(value, dict):
            latest = value
    return latest


def _token_counts(messages: Iterable[AssistantMessage | UserMessage]) -> tuple[int | None, int | None]:
    input_total = 0
    output_total = 0
    available = False
    for message in messages:
        usage = message.usage
        if not isinstance(usage, dict):
            continue
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if isinstance(prompt, (int, float)):
            input_total += int(prompt)
            available = True
        if isinstance(completion, (int, float)):
            output_total += int(completion)
            available = True
    if not available:
        return None, None
    return input_total, output_total


def _sum_optional(left: int | float | None, right: int | float | None) -> int | float | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


def _message_cost(messages: Sequence[AssistantMessage | UserMessage]) -> float | None:
    costs = [message.cost for message in messages if message.cost is not None]
    return sum(costs) if costs else None


def _node_llm_metrics(metadata: dict[str, Any]) -> dict[str, NodeLLMMetrics]:
    traces = metadata.get("llm_calls", [])
    if not isinstance(traces, list):
        return {}
    grouped: dict[str, NodeLLMMetrics] = {}
    for trace in traces:
        if not isinstance(trace, dict) or not isinstance(trace.get("node"), str):
            continue
        node = trace["node"]
        metric = grouped.setdefault(node, NodeLLMMetrics())
        metric.calls += 1
        metric.model = str(trace.get("model") or metric.model or "") or None
        metric.provider = str(trace.get("provider") or metric.provider or "") or None
        metric.latency_seconds += float(trace.get("latency_ms") or 0.0) / 1000
        metric.input_tokens += int(trace.get("input_tokens") or 0)
        metric.output_tokens += int(trace.get("output_tokens") or 0)
        metric.cached_input_tokens += int(trace.get("cached_input_tokens") or 0)
        metric.cost += float(trace.get("cost") or 0.0)
        metric.cost_available = metric.cost_available and bool(
            trace.get("cost_available", True)
        )
        valid = trace.get("structured_output_valid")
        metric.structured_valid_calls += int(valid is True)
        metric.structured_invalid_calls += int(valid is False)
        metric.retry_count += int(trace.get("retry_count") or 0)
        metric.error_count += int(bool(trace.get("error")))
    return grouped


def task_record_from_simulation(
    simulation: SimulationRun, result_path: Path | str
) -> TaskEvaluationRecord:
    """Extract task metrics only from the completed runtime trajectory."""
    messages = simulation.get_messages()
    assistant_messages = [m for m in messages if isinstance(m, AssistantMessage)]
    user_messages = [m for m in messages if isinstance(m, UserMessage)]
    generated_assistant = [
        m
        for m in assistant_messages
        if m.generation_time_seconds is not None or isinstance(m.usage, dict)
    ]
    generated_users = [
        m
        for m in user_messages
        if m.generation_time_seconds is not None or isinstance(m.usage, dict)
    ]
    agent_tool_calls = sum(len(m.tool_calls or []) for m in assistant_messages)
    user_tool_calls = sum(len(m.tool_calls or []) for m in user_messages)
    metadata = _latest_metadata(simulation)
    node_metrics = _node_llm_metrics(metadata)
    process = metrics_from_simulation(simulation)
    contexts = []
    for message in generated_assistant:
        message_metadata = (message.raw_data or {}).get("policypilot_v1", {})
        value = (
            message_metadata.get("context_estimated_size")
            if isinstance(message_metadata, dict)
            else None
        )
        if isinstance(value, int):
            contexts.append(value)

    reward_info = simulation.reward_info
    action_checks = reward_info.action_checks if reward_info else None
    required_total = len(action_checks or [])
    required_completed = sum(check.action_match for check in action_checks or [])
    db_check = reward_info.db_check if reward_info else None
    agent_input, agent_output = _token_counts(generated_assistant)
    user_input, user_output = _token_counts(generated_users)
    agent_latency_values = [
        m.generation_time_seconds
        for m in generated_assistant
        if m.generation_time_seconds is not None
    ]
    user_latency_values = [
        m.generation_time_seconds
        for m in generated_users
        if m.generation_time_seconds is not None
    ]
    tool_error_count = sum(
        bool(
            message.error
            or (message.content or "")
            .lstrip()
            .lower()
            .startswith(("error", "failed"))
        )
        for message in messages
        if isinstance(message, ToolMessage)
    )
    agent_cost = simulation.agent_cost
    if agent_cost is None:
        agent_cost = _message_cost(generated_assistant)
    user_cost = simulation.user_cost
    if user_cost is None:
        user_cost = _message_cost(generated_users)
    if node_metrics:
        agent_input = sum(item.input_tokens for item in node_metrics.values())
        agent_output = sum(item.output_tokens for item in node_metrics.values())
        agent_cost = sum(item.cost for item in node_metrics.values())
        agent_latency_values = [
            sum(item.latency_seconds for item in node_metrics.values())
        ]
    user_cost_available = all(
        not isinstance(message.usage, dict)
        or not message.usage
        or bool(message.cost)
        for message in generated_users
    )
    cost_is_lower_bound = (
        any(not item.cost_available for item in node_metrics.values())
        or not user_cost_available
    )
    post_evaluation_latency = node_metrics.get(
        "episode_extractor", NodeLLMMetrics()
    ).latency_seconds
    raw_error_counts = metadata.get("error_category_counts")
    error_counts = (
        {
            category.value: int(raw_error_counts.get(category.value, 0))
            for category in PolicyPilotErrorType
        }
        if isinstance(raw_error_counts, dict)
        else {}
    )
    recovery_count = (
        process.llm_retry_count
        + process.tool_retry_count
        + process.tool_repair_count
        + process.retrieval_rewrite_count
    )
    unavailable = list(UNAVAILABLE_METRICS)
    if not contexts:
        unavailable.append("context_size_per_call_chars")
    if not agent_latency_values:
        unavailable.append("agent_llm_latency_seconds")
    if not user_latency_values:
        unavailable.append("user_llm_latency_seconds")
    if agent_input is None and user_input is None:
        unavailable.extend(["input_tokens", "output_tokens"])
    if "guard_allow_count" not in metadata:
        unavailable.extend(
            ["guard_allow_count", "guard_block_count", "guard_recover_count"]
        )
    if not isinstance(raw_error_counts, dict):
        unavailable.append("error_category_counts")
    return TaskEvaluationRecord(
        task_id=simulation.task_id,
        reward=reward_info.reward if reward_info else None,
        db_check=db_check.db_match if db_check else None,
        db_reward=db_check.db_reward if db_check else None,
        required_actions_total=required_total,
        required_actions_completed=required_completed,
        termination_reason=simulation.termination_reason.value,
        success=bool(reward_info and reward_info.reward == 1.0),
        total_steps=process.total_steps,
        agent_tool_calls=agent_tool_calls,
        user_tool_calls=user_tool_calls,
        total_tool_calls=agent_tool_calls + user_tool_calls,
        knowledge_retrieval_calls=process.knowledge_retrieval_calls,
        duplicate_call_count=process.duplicate_call_count,
        tool_error_count=tool_error_count,
        guard_allow_count=metadata.get("guard_allow_count"),
        guard_block_count=metadata.get("guard_block_count"),
        guard_recover_count=metadata.get("guard_recover_count"),
        recovery_count=recovery_count,
        recovery_success_count=metadata.get(
            "recovery_success_count", process.recovery_success_count
        ),
        error_category_counts=error_counts,
        agent_llm_calls=(
            sum(item.calls for item in node_metrics.values())
            if node_metrics
            else len(generated_assistant)
        ),
        lightweight_llm_calls=sum(
            item.calls for node, item in node_metrics.items() if node != "decision"
        ),
        main_decision_calls=node_metrics.get("decision", NodeLLMMetrics()).calls,
        node_llm_metrics=node_metrics,
        context_size_per_call_chars=contexts,
        avg_context_size_chars=sum(contexts) / len(contexts) if contexts else None,
        max_context_size_chars=max(contexts) if contexts else None,
        min_context_size_chars=min(contexts) if contexts else None,
        episode_latency_seconds=simulation.duration,
        post_evaluation_llm_latency_seconds=post_evaluation_latency,
        end_to_end_latency_seconds=(simulation.duration + post_evaluation_latency),
        agent_llm_latency_seconds=(sum(agent_latency_values) if agent_latency_values else None),
        user_llm_latency_seconds=(sum(user_latency_values) if user_latency_values else None),
        agent_cost=agent_cost,
        user_cost=user_cost,
        total_cost=_sum_optional(agent_cost, user_cost),
        cost_is_lower_bound=cost_is_lower_bound,
        agent_input_tokens=agent_input,
        agent_output_tokens=agent_output,
        user_input_tokens=user_input,
        user_output_tokens=user_output,
        input_tokens=_sum_optional(agent_input, user_input),
        output_tokens=_sum_optional(agent_output, user_output),
        result_path=str(result_path),
        unavailable_metrics=unavailable,
    )


def task_error_record(task_id: str, exc: Exception) -> TaskEvaluationRecord:
    """Represent an exception that prevented a completed simulation."""
    return TaskEvaluationRecord(
        task_id=task_id,
        status="error",
        error_type=type(exc).__name__,
        error_message=summarize_text(str(exc), 1000),
        unavailable_metrics=["all_episode_metrics", *UNAVAILABLE_METRICS],
    )


def failure_record_from_simulation(
    simulation: SimulationRun, result_path: Path | str
) -> FailureRecord:
    """Build failure evidence without reading benchmark evaluation criteria."""
    messages = simulation.get_messages()
    tool_results = {
        message.id: message for message in messages if isinstance(message, ToolMessage)
    }
    calls: list[ToolCallTrace] = []
    queries: list[str] = []
    documents: dict[str, dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message, (AssistantMessage, UserMessage)):
            continue
        for call in message.tool_calls or []:
            result = tool_results.get(call.id)
            result_failed = bool(
                result
                and (
                    result.error
                    or (result.content or "")
                    .lstrip()
                    .lower()
                    .startswith(("error", "failed"))
                )
            )
            calls.append(
                ToolCallTrace(
                    name=call.name,
                    canonical_args=canonicalize_arguments(call.arguments),
                    requestor=call.requestor,
                    success=None if result is None else not result_failed,
                    error=None if result is None else result_failed,
                )
            )
            if is_knowledge_tool(call.name):
                query = call.arguments.get("query")
                if isinstance(query, str):
                    queries.append(query)
                if result:
                    for ref in parse_policy_references(result.content):
                        documents[ref.document_id] = ref.model_dump(mode="json")

    metadata = _latest_metadata(simulation)
    reward = simulation.reward_info.reward if simulation.reward_info else None
    return FailureRecord(
        task_id=simulation.task_id,
        reward=reward,
        termination_reason=simulation.termination_reason.value,
        total_steps=len(messages),
        tool_calls=calls,
        retrieval_queries=queries,
        retrieved_documents=list(documents.values()),
        guard_block_reasons=list(metadata.get("guard_block_reasons", [])),
        recovery_categories=list(metadata.get("recovery_categories", [])),
        current_goal=metadata.get("current_goal"),
        final_open_questions=list(metadata.get("open_questions", [])),
        final_known_facts=list(metadata.get("known_facts", [])),
        last_trajectory=[_trajectory_summary(m) for m in messages[-8:]],
        result_path=str(result_path),
    )


def failure_record_from_exception(task_id: str, exc: Exception) -> FailureRecord:
    """Build a failure record for a runner/API failure with no trajectory."""
    return FailureRecord(
        task_id=task_id,
        error_type=type(exc).__name__,
        error_message=summarize_text(str(exc), 1000),
    )


def _trajectory_summary(message: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"role": getattr(message, "role", "unknown")}
    turn_idx = getattr(message, "turn_idx", None)
    if turn_idx is not None:
        summary["turn_idx"] = turn_idx
    content = getattr(message, "content", None)
    if content:
        summary["content"] = summarize_text(content, 300)
    calls = getattr(message, "tool_calls", None)
    if calls:
        summary["tool_calls"] = [
            {"name": call.name, "canonical_args": canonicalize_arguments(call.arguments)}
            for call in calls
        ]
    if isinstance(message, ToolMessage):
        summary["tool_call_id"] = message.id
        summary["error"] = message.error
    return summary


def aggregate_records(
    records: Sequence[TaskEvaluationRecord],
    *,
    db_hash_before: str | None = None,
    db_hash_after: str | None = None,
) -> BatchSummary:
    """Aggregate all selected tasks; runner failures count as unsuccessful/reward 0."""
    total = len(records)
    completed = [record for record in records if record.status == "completed"]
    successful = [record for record in records if record.success]
    rewards = [record.reward if record.reward is not None else 0.0 for record in records]
    db_values = [record.db_check for record in completed if record.db_check is not None]
    actions_total = sum(record.required_actions_total for record in completed)
    actions_completed = sum(record.required_actions_completed for record in completed)
    guard_blocks = [
        record.guard_block_count
        for record in completed
        if record.guard_block_count is not None
    ]
    context_sizes = [
        size for record in completed for size in record.context_size_per_call_chars
    ]
    latencies = [
        record.episode_latency_seconds
        for record in completed
        if record.episode_latency_seconds is not None
    ]
    termination_counts = Counter(
        record.termination_reason or "runner_error" for record in records
    )
    error_counts: Counter[str] = Counter()
    for record in completed:
        error_counts.update(record.error_category_counts)

    def average(values: Sequence[int | float]) -> float:
        return sum(values) / len(values) if values else 0.0

    total_agent_cost = sum(record.agent_cost or 0 for record in records)
    total_user_cost = sum(record.user_cost or 0 for record in records)
    total_cost = total_agent_cost + total_user_cost
    token_inputs = [record.input_tokens for record in completed if record.input_tokens is not None]
    token_outputs = [record.output_tokens for record in completed if record.output_tokens is not None]
    return BatchSummary(
        total_tasks=total,
        completed_tasks=len(completed),
        runner_error_tasks=total - len(completed),
        successful_tasks=len(successful),
        failed_tasks=total - len(successful),
        success_rate=len(successful) / total if total else 0.0,
        average_reward=average(rewards),
        db_success_rate=(sum(bool(value) for value in db_values) / len(db_values) if db_values else None),
        required_action_completion_rate=(actions_completed / actions_total if actions_total else None),
        avg_steps=average([record.total_steps for record in records]),
        avg_agent_tool_calls=average([record.agent_tool_calls for record in records]),
        avg_total_tool_calls=average([record.total_tool_calls for record in records]),
        avg_retrieval_calls=average([record.knowledge_retrieval_calls for record in records]),
        avg_duplicate_calls=average([record.duplicate_call_count for record in records]),
        avg_guard_blocks=average(guard_blocks) if guard_blocks else None,
        avg_recovery_count=average([record.recovery_count for record in records]),
        max_step_termination_rate=(
            sum(record.termination_reason == "max_steps" for record in records) / total
            if total
            else 0.0
        ),
        avg_context_size_chars=average(context_sizes) if context_sizes else None,
        p50_context_size_chars=percentile(context_sizes, 0.50),
        p95_context_size_chars=percentile(context_sizes, 0.95),
        avg_episode_latency_seconds=average(latencies) if latencies else None,
        p50_episode_latency_seconds=percentile(latencies, 0.50),
        p95_episode_latency_seconds=percentile(latencies, 0.95),
        total_agent_cost=total_agent_cost,
        total_user_cost=total_user_cost,
        total_cost=total_cost,
        avg_cost_per_task=total_cost / total if total else 0.0,
        cost_is_lower_bound=any(record.cost_is_lower_bound for record in records),
        total_input_tokens=sum(token_inputs) if token_inputs else None,
        total_output_tokens=sum(token_outputs) if token_outputs else None,
        success_task_ids=[record.task_id for record in successful],
        failed_task_ids=[record.task_id for record in records if not record.success],
        termination_reason_counts=dict(sorted(termination_counts.items())),
        error_category_counts=dict(sorted(error_counts.items())),
        source_db_sha256_before=db_hash_before,
        source_db_sha256_after=db_hash_after,
        source_db_unchanged=(
            db_hash_before == db_hash_after
            if db_hash_before is not None and db_hash_after is not None
            else None
        ),
    )


def run_evaluation_batch(
    task_ids: Sequence[str],
    run_dir: Path,
    run_task: Callable[[str], tuple[SimulationRun, Path]],
    *,
    source_db_path: Path | None = None,
) -> BatchEvaluationResult:
    """Run isolated tasks and persist the growing batch after every attempt."""
    records: list[TaskEvaluationRecord] = []
    failures: list[FailureRecord] = []
    db_hash_before = sha256_file(source_db_path) if source_db_path else None
    for task_id in task_ids:
        try:
            simulation, result_path = run_task(task_id)
            record = task_record_from_simulation(simulation, result_path)
            records.append(record)
            if not record.success:
                failures.append(failure_record_from_simulation(simulation, result_path))
        except Exception as exc:
            records.append(task_error_record(task_id, exc))
            failures.append(failure_record_from_exception(task_id, exc))
        db_hash_after = sha256_file(source_db_path) if source_db_path else None
        summary = aggregate_records(
            records, db_hash_before=db_hash_before, db_hash_after=db_hash_after
        )
        write_evaluation_outputs(run_dir, records, failures, summary)
    if not records:
        summary = aggregate_records([], db_hash_before=db_hash_before, db_hash_after=db_hash_before)
        write_evaluation_outputs(run_dir, records, failures, summary)
    return BatchEvaluationResult(
        task_records=records, failure_records=failures, summary=summary
    )


def write_evaluation_outputs(
    run_dir: Path,
    records: Sequence[TaskEvaluationRecord],
    failures: Sequence[FailureRecord],
    summary: BatchSummary,
) -> None:
    """Atomically replace all derived batch outputs."""
    run_dir.mkdir(parents=True, exist_ok=True)
    _atomic_text(
        run_dir / "task_results.jsonl",
        "".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in records),
    )
    _atomic_text(
        run_dir / "failures.jsonl",
        "".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in failures),
    )
    _atomic_text(
        run_dir / "summary.json",
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
    )
    _write_summary_csv(run_dir / "summary.csv", records)


def write_config(path: Path, config: dict[str, Any]) -> None:
    """Persist a reproducibility config without leaking environment secrets."""
    _atomic_text(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def _write_summary_csv(path: Path, records: Sequence[TaskEvaluationRecord]) -> None:
    fields = list(TaskEvaluationRecord.model_fields)
    temp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = record.model_dump(mode="json")
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    row[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)
    temp.replace(path)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
