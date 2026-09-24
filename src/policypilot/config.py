"""Configuration for PolicyPilot's task-local decision layer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyPilotConfig:
    """Small, deterministic limits used by context building and recovery."""

    max_recent_messages: int = 12
    max_context_facts: int = 30
    max_context_evidence: int = 3
    max_context_tool_history: int = 8
    max_context_tool_message_chars: int = 800
    max_information_needs: int = 40
    max_llm_retries: int = 2
    llm_retry_base_seconds: float = 0.25
    max_read_tool_retries: int = 1
    max_tool_repair_attempts: int = 1
    max_duplicate_recovery_attempts: int = 1
    max_guard_recovery_attempts: int = 2
    max_decision_fallback_need_attempts: int = 1
    max_retrieval_rewrite_attempts: int = 1
    max_goal_retrieval_calls: int = 6
    max_retrieval_attempts_per_semantic_need: int = 2
    decision_knowledge_tools_enabled: bool = True
    max_no_progress_turns: int = 3
    max_graph_steps: int = 20
    light_model: str | None = None
    main_decision_model: str | None = None
    light_temperature: float = 0.1
    structured_repair_attempts: int = 1
    semantic_planner_enabled: bool = True
    skill_llm_fallback_enabled: bool = True
    context_compressor_enabled: bool = True
    max_decision_context_chars: int = 40000
    max_decision_context_tokens: int = 12000
    context_compressor_target_tokens: int = 9000
    max_compressed_tool_chars: int = 420
    memory_enabled: bool = True
    memory_dir: str = "data/policypilot_memory"
    memory_model: str | None = None
    memory_min_profile_confidence: float = 0.7
    memory_max_episodes_per_user: int = 100
    memory_max_recalled_episodes: int = 3
    memory_max_context_chars: int = 1800
    memory_embedding_enabled: bool = True
    memory_embedding_endpoint: str = "http://127.0.0.1:11434"
    memory_embedding_model: str = "qwen3-embedding:0.6b"
    memory_embedding_timeout_seconds: float = 60.0
    skills_enabled: bool = True
    max_skill_guidance_chars: int = 3600
    max_active_skills: int = 3
    max_skill_references_per_skill: int = 2
    max_skill_trace_events: int = 80
    prompt_cache_metrics_enabled: bool = True
    retrieval_cache_enabled: bool = True
    retrieval_cache_ttl: float | None = 900.0
    retriever_version: str = "v1"
    kb_version: str = "v1"
    embedding_cache_enabled: bool = True
    embedding_model_version: str = "v1"
    chunking_version: str = "v1"
    task_fact_reuse_enabled: bool = True
    planning_fact_ttl_seconds: float = 300.0
    pre_mutation_fact_ttl_seconds: float = 60.0
    agent_version: str = "policypilot-v1"
    prompt_version: str = "decision-v2"
    checkpoint_dir: str = "data/policypilot_checkpoints"
