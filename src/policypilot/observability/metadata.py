"""Serialize runtime state into stable PolicyPilot evaluation metadata."""

from __future__ import annotations

from typing import Any, Protocol

from policypilot.errors import PolicyPilotErrorType
from policypilot.state import PolicyPilotState
from tau2.data_model.message import AssistantMessage
from tau2.knowledge.embeddings_cache import get_embedding_cache_metrics
from tau2.knowledge.retrieval_cache import get_retrieval_cache_metrics


class MetadataHost(Protocol):
    config: Any
    model_routing: Any
    llm_runtime: Any
    skills: Any
    memory: Any
    last_graph_state: Any
    _retrieval_cache_baseline: dict[str, Any]
    _embedding_cache_baseline: dict[str, Any]


def cache_delta(current: dict, baseline: dict) -> dict:
    hits = int(current.get("hits", 0)) - int(baseline.get("hits", 0))
    misses = int(current.get("misses", 0)) - int(baseline.get("misses", 0))
    total = hits + misses
    result = {
        "hits": hits,
        "misses": misses,
        "hit_ratio": hits / total if total else 0.0,
    }
    if "saved_latency_ms" in current:
        result["saved_latency_ms"] = round(
            float(current.get("saved_latency_ms", 0.0))
            - float(baseline.get("saved_latency_ms", 0.0)),
            3,
        )
    return result


def attach_metrics_metadata(
    host: MetadataHost, message: AssistantMessage, state: PolicyPilotState
) -> None:
    control = state.control
    raw = dict(message.raw_data or {})
    prompt_cache_total = (
        control.prompt_cache_hit_tokens + control.prompt_cache_miss_tokens
    )
    retrieval_cache = cache_delta(
        get_retrieval_cache_metrics(), host._retrieval_cache_baseline
    )
    embedding_cache = cache_delta(
        get_embedding_cache_metrics(), host._embedding_cache_baseline
    )
    control.retrieval_cache_hits = int(retrieval_cache["hits"])
    control.retrieval_cache_misses = int(retrieval_cache["misses"])
    control.retrieval_cache_saved_latency_ms = float(
        retrieval_cache.get("saved_latency_ms", 0.0)
    )
    control.embedding_cache_hits = int(embedding_cache["hits"])
    control.embedding_cache_misses = int(embedding_cache["misses"])
    open_user = list(state.open_needs("USER"))
    raw["policypilot_v1"] = {
        "step_count": control.step_count,
        "goal_changes": control.goal_change_count,
        "facts_added": control.facts_added_count,
        "facts_updated": control.facts_updated_count,
        "open_questions_added": control.needs_added_count,
        "open_questions_resolved": control.needs_resolved_count,
        "context_message_count": control.context_message_count,
        "context_estimated_size": control.context_estimated_size,
        "llm_retry_count": control.llm_retry_count,
        "tool_retry_count": control.tool_retry_count,
        "tool_repair_count": control.tool_repair_count,
        "retrieval_rewrite_count": control.retrieval_rewrite_count,
        "recovery_success_count": control.recovery_success_count,
        "recovery_failure_count": control.recovery_failure_count,
        "duplicate_call_count": control.duplicate_call_count,
        "retrieval_miss_count": control.retrieval_miss_count,
        "error_count": control.error_count,
        "guard_allow_count": sum(not record.blocked for record in state.tool_history),
        "guard_block_count": sum(record.blocked for record in state.tool_history),
        "guard_recover_count": sum(record.resolved for record in control.error_records),
        "guard_block_reasons": [
            record.message
            for record in control.error_records
            if record.source == "tool_guard"
        ],
        "error_category_counts": {
            error.value: sum(
                record.category == error for record in control.error_records
            )
            for error in PolicyPilotErrorType
        },
        "recovery_categories": sorted(
            {record.category.value for record in control.error_records}
        ),
        "current_goal": state.goal.objective,
        "goal": state.goal.model_dump(mode="json"),
        "information_needs": [
            need.model_dump(mode="json") for need in state.information_needs
        ],
        "retrieval_query_plans": control.retrieval_query_history,
        "planner_events": control.planner_events,
        "need_registry_events": control.need_registry_events,
        "retrieval_events": control.retrieval_events,
        "context_compressor_events": control.context_compressor_events,
        "need_selection_events": control.need_selection_events,
        "acquisition_events": control.acquisition_events,
        "progress_events": control.progress_events,
        "no_progress_count": control.no_progress_count,
        "open_questions": [
            {"key": need.id, "question": need.question or need.reason}
            for need in open_user
        ],
        "known_facts": [
            {
                "key": fact.key,
                "value": fact.value,
                "source_type": fact.source_type,
                "verified": fact.verified,
            }
            for fact in state.facts
        ],
        "tool_history": [
            record.model_dump(mode="json") for record in state.tool_history
        ],
        "route_trace": control.route_trace,
        "provenance": {
            "run_id": state.run_id,
            "raw_payload_count": len(state.raw_payloads),
            "evidence_count": len(state.evidence),
            "context_manifests": [
                item.model_dump(mode="json") for item in state.context_manifests
            ],
            "version_metadata": state.version_metadata,
        },
        "model_routing": host.model_routing.as_dict(),
        "llm_calls": host.llm_runtime.snapshot(),
        "skills": (
            host.skills.snapshot() if host.config.skills_enabled else {"enabled": False}
        ),
        "cache": {
            "prompt": {
                "reported_by_provider": control.prompt_cache_usage_reported,
                "hit_tokens": control.prompt_cache_hit_tokens,
                "miss_tokens": control.prompt_cache_miss_tokens,
                "hit_ratio": (
                    control.prompt_cache_hit_tokens / prompt_cache_total
                    if prompt_cache_total
                    else 0.0
                ),
            },
            "retrieval": retrieval_cache,
            "embedding": embedding_cache,
            "task_fact": {
                "reuse_hit": control.task_fact_reuse_hit,
                "reuse_miss": control.task_fact_reuse_miss,
                "stale": control.task_fact_reuse_stale,
                "forced_refresh": control.task_fact_forced_refresh,
            },
        },
        "memory": (
            host.memory.metrics.model_dump()
            if host.memory is not None
            else {"enabled": False}
        ),
    }
    message.raw_data = raw


def on_evaluation_complete(host: MetadataHost, simulation) -> None:
    """Form one episode after tau2 has attached the real evaluator result."""
    if host.memory is None or host.last_graph_state is None:
        return
    state = host.last_graph_state.get("policy_state")
    if state is None:
        return
    final_message = next(
        (
            message
            for message in reversed(state.messages)
            if isinstance(message, AssistantMessage)
        ),
        None,
    )
    if final_message is None:
        return
    reward = simulation.reward_info
    db_check = reward.db_check if reward else None
    evaluation = {
        "reward": reward.reward if reward else None,
        "db_check": db_check.db_match if db_check else None,
        "required_actions_completed": (
            sum(check.action_match for check in (reward.action_checks or []))
            if reward
            else 0
        ),
        "required_actions_total": len(reward.action_checks or []) if reward else 0,
        "termination_reason": simulation.termination_reason.value,
    }
    host.memory.record_episode(state, final_message, evaluation=evaluation)
    attach_metrics_metadata(host, final_message, state)
