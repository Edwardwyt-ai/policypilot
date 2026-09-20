"""Process metrics derived from PolicyPilot state or tau2 trajectories."""

from __future__ import annotations

from dataclasses import dataclass

from policypilot.state import PolicyPilotState
from policypilot.tool_policy import is_knowledge_tool
from tau2.data_model.message import AssistantMessage, Message, ToolMessage
from tau2.data_model.simulation import SimulationRun


@dataclass(frozen=True)
class ProcessMetrics:
    """Process metrics independent of tau2 reward semantics."""

    total_steps: int = 0
    total_tool_calls: int = 0
    knowledge_retrieval_calls: int = 0
    transactional_read_calls: int = 0
    mutation_calls: int = 0
    duplicate_call_count: int = 0
    tool_error_count: int = 0
    retrieval_miss_count: int = 0
    conversation_turns: int = 0
    latency: float | None = None
    goal_changes: int = 0
    facts_added: int = 0
    facts_updated: int = 0
    open_questions_added: int = 0
    open_questions_resolved: int = 0
    context_message_count: int = 0
    context_estimated_size: int = 0
    llm_retry_count: int = 0
    tool_retry_count: int = 0
    tool_repair_count: int = 0
    retrieval_rewrite_count: int = 0
    recovery_success_count: int = 0
    recovery_failure_count: int = 0
    memory_profile_reads: int = 0
    memory_profile_writes: int = 0
    memory_episode_reads: int = 0
    memory_episode_writes: int = 0
    memory_context_chars: int = 0
    memory_extraction_calls: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    retrieval_cache_hits: int = 0
    retrieval_cache_misses: int = 0
    retrieval_cache_saved_latency_ms: float = 0.0
    embedding_cache_hits: int = 0
    embedding_cache_misses: int = 0
    task_fact_reuse_hit: int = 0
    task_fact_reuse_miss: int = 0
    task_fact_reuse_stale: int = 0
    task_fact_forced_refresh: int = 0


def metrics_from_state(state: PolicyPilotState) -> ProcessMetrics:
    """Compute process metrics from PolicyPilot's internal state."""
    control = state.control
    transactional_reads = sum(
        1 for record in state.tool_history if record.classification == "transaction_read"
    )
    mutations = sum(1 for record in state.tool_history if record.classification == "mutation")
    retrievals = sum(1 for record in state.tool_history if record.classification == "knowledge")
    return ProcessMetrics(
        total_steps=len(state.messages),
        total_tool_calls=control.tool_call_count,
        knowledge_retrieval_calls=retrievals,
        transactional_read_calls=transactional_reads,
        mutation_calls=mutations,
        duplicate_call_count=control.duplicate_call_count,
        tool_error_count=control.error_count,
        retrieval_miss_count=control.retrieval_miss_count,
        conversation_turns=len([m for m in state.messages if getattr(m, "role", None) in {"user", "assistant"}]),
        goal_changes=control.goal_change_count,
        facts_added=control.facts_added_count,
        facts_updated=control.facts_updated_count,
        open_questions_added=control.needs_added_count,
        open_questions_resolved=control.needs_resolved_count,
        context_message_count=control.context_message_count,
        context_estimated_size=control.context_estimated_size,
        llm_retry_count=control.llm_retry_count,
        tool_retry_count=control.tool_retry_count,
        tool_repair_count=control.tool_repair_count,
        retrieval_rewrite_count=control.retrieval_rewrite_count,
        recovery_success_count=control.recovery_success_count,
        recovery_failure_count=control.recovery_failure_count,
        prompt_cache_hit_tokens=control.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=control.prompt_cache_miss_tokens,
        retrieval_cache_hits=control.retrieval_cache_hits,
        retrieval_cache_misses=control.retrieval_cache_misses,
        retrieval_cache_saved_latency_ms=control.retrieval_cache_saved_latency_ms,
        embedding_cache_hits=control.embedding_cache_hits,
        embedding_cache_misses=control.embedding_cache_misses,
        task_fact_reuse_hit=control.task_fact_reuse_hit,
        task_fact_reuse_miss=control.task_fact_reuse_miss,
        task_fact_reuse_stale=control.task_fact_reuse_stale,
        task_fact_forced_refresh=control.task_fact_forced_refresh,
    )


def metrics_from_simulation(simulation: SimulationRun) -> ProcessMetrics:
    """Compute lightweight process metrics from a saved tau2 simulation."""
    messages: list[Message] = simulation.get_messages()
    tool_calls = 0
    retrieval_calls = 0
    tool_errors = 0
    retrieval_misses = 0
    policypilot = {}
    for message in messages:
        if isinstance(message, AssistantMessage) and message.tool_calls:
            for call in message.tool_calls:
                tool_calls += 1
                if is_knowledge_tool(call.name):
                    retrieval_calls += 1
        if isinstance(message, ToolMessage):
            if message.error:
                tool_errors += 1
            if message.content and "No relevant documents found" in message.content:
                retrieval_misses += 1
        if isinstance(message, AssistantMessage) and message.raw_data:
            metadata = message.raw_data.get("policypilot_v1")
            if isinstance(metadata, dict):
                policypilot = metadata
    memory = policypilot.get("memory", {})
    if not isinstance(memory, dict):
        memory = {}
    cache = policypilot.get("cache", {})
    if not isinstance(cache, dict):
        cache = {}
    prompt_cache = cache.get("prompt", {}) if isinstance(cache.get("prompt", {}), dict) else {}
    retrieval_cache = cache.get("retrieval", {}) if isinstance(cache.get("retrieval", {}), dict) else {}
    embedding_cache = cache.get("embedding", {}) if isinstance(cache.get("embedding", {}), dict) else {}
    task_fact = cache.get("task_fact", {}) if isinstance(cache.get("task_fact", {}), dict) else {}
    return ProcessMetrics(
        total_steps=len(messages),
        total_tool_calls=tool_calls,
        knowledge_retrieval_calls=retrieval_calls,
        duplicate_call_count=policypilot.get("duplicate_call_count", 0),
        tool_error_count=policypilot.get("error_count", tool_errors),
        retrieval_miss_count=policypilot.get("retrieval_miss_count", retrieval_misses),
        conversation_turns=len([m for m in messages if getattr(m, "role", None) in {"user", "assistant"}]),
        latency=simulation.duration,
        goal_changes=policypilot.get("goal_changes", 0),
        facts_added=policypilot.get("facts_added", 0),
        facts_updated=policypilot.get("facts_updated", 0),
        open_questions_added=policypilot.get("open_questions_added", 0),
        open_questions_resolved=policypilot.get("open_questions_resolved", 0),
        context_message_count=policypilot.get("context_message_count", 0),
        context_estimated_size=policypilot.get("context_estimated_size", 0),
        llm_retry_count=policypilot.get("llm_retry_count", 0),
        tool_retry_count=policypilot.get("tool_retry_count", 0),
        tool_repair_count=policypilot.get("tool_repair_count", 0),
        retrieval_rewrite_count=policypilot.get("retrieval_rewrite_count", 0),
        recovery_success_count=policypilot.get("recovery_success_count", 0),
        recovery_failure_count=policypilot.get("recovery_failure_count", 0),
        memory_profile_reads=memory.get("profile_reads", 0),
        memory_profile_writes=memory.get("profile_writes", 0),
        memory_episode_reads=memory.get("episode_reads", 0),
        memory_episode_writes=memory.get("episode_writes", 0),
        memory_context_chars=memory.get("context_chars", 0),
        memory_extraction_calls=memory.get("extraction_calls", 0),
        prompt_cache_hit_tokens=prompt_cache.get("hit_tokens", 0),
        prompt_cache_miss_tokens=prompt_cache.get("miss_tokens", 0),
        retrieval_cache_hits=retrieval_cache.get("hits", 0),
        retrieval_cache_misses=retrieval_cache.get("misses", 0),
        retrieval_cache_saved_latency_ms=retrieval_cache.get("saved_latency_ms", 0.0),
        embedding_cache_hits=embedding_cache.get("hits", 0),
        embedding_cache_misses=embedding_cache.get("misses", 0),
        task_fact_reuse_hit=task_fact.get("reuse_hit", 0),
        task_fact_reuse_miss=task_fact.get("reuse_miss", 0),
        task_fact_reuse_stale=task_fact.get("stale", 0),
        task_fact_forced_refresh=task_fact.get("forced_refresh", 0),
    )
