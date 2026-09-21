"""tau2 adapter and dependency composition for PolicyPilot."""

from __future__ import annotations

from typing import Optional

from langgraph.errors import GraphRecursionError

from policypilot.checkpoint import JsonCheckpointStore
from policypilot.compression import ToolContextCompressor
from policypilot.config import PolicyPilotConfig
from policypilot.coverage import EvidenceResolver
from policypilot.errors import PolicyPilotErrorType
from policypilot.llm_runtime import LLMRuntime
from policypilot.memory.episodic import LLMEpisodeExtractor
from policypilot.memory.profile import (
    LLMPreferenceExtractor,
    PreferenceExtractor,
    ProfileMemoryGate,
    ProfileMemoryManager,
)
from policypilot.memory.service import MemoryService
from policypilot.memory.store import JsonMemoryStore
from policypilot.model_routing import resolve_model_routing
from policypilot.need_registry import NeedRegistry
from policypilot.needs import NeedResolver, SourceResolver
from policypilot.observability.metadata import (
    attach_metrics_metadata,
)
from policypilot.observability.metadata import (
    on_evaluation_complete as record_evaluation,
)
from policypilot.planning import LLMSemanticPlanner
from policypilot.policy_engine import PassthroughPolicyEngine
from policypilot.prompts import build_system_prompt
from policypilot.runtime.actions import (
    call_decision,
    decision_fallback_candidates,
    proposal_error,
    record_blocked_tool_calls,
    record_valid_tool_calls,
    register_decision_fallback,
    tool_call_for_need,
    validate_proposal,
)
from policypilot.runtime.observation import (
    ObservationOutcome,
    activate_recovery_skill,
    bind_memory_from_state,
    observe,
    observe_tool_message,
)
from policypilot.runtime.recovery import (
    budget_exhaustion_message,
    recover_read_failure,
    recover_validation_failure,
)
from policypilot.skills import SkillMatcher, SkillRuntime
from policypilot.skills.matcher import LLMSkillFallback
from policypilot.state import InformationNeed, PolicyPilotState
from policypilot.tool_policy import ToolBudget, ToolCallGuard, ToolExposureResolver
from policypilot.workflow.graph import PolicyPilotGraphState, PolicyPilotWorkflow
from tau2.agent.base.llm_config import LLMConfigMixin
from tau2.agent.base_agent import (
    HalfDuplexAgent,
    ValidAgentInputMessage,
    is_valid_agent_history_message,
)
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from tau2.environment.tool import Tool
from tau2.knowledge.embeddings_cache import (
    configure_embedding_cache,
    get_embedding_cache_metrics,
)
from tau2.knowledge.retrieval_cache import (
    configure_retrieval_cache,
    get_retrieval_cache_metrics,
)


class PolicyPilotAgent(LLMConfigMixin, HalfDuplexAgent[PolicyPilotState]):
    """Thin tau2 adapter that composes PolicyPilot's domain services."""

    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        llm: str,
        llm_args: Optional[dict] = None,
        budget: ToolBudget | None = None,
        config: PolicyPilotConfig | None = None,
        memory_store: JsonMemoryStore | None = None,
        memory_user_id: str | None = None,
        memory_extractor: PreferenceExtractor | None = None,
        task_id: str | None = None,
        llm_runtime: LLMRuntime | None = None,
    ):
        tools = sorted(tools, key=lambda tool: tool.name)
        super().__init__(
            tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args
        )
        self.budget = budget or ToolBudget()
        self.config = config or PolicyPilotConfig()
        self.task_id = task_id
        self.checkpoints = JsonCheckpointStore(self.config.checkpoint_dir)
        self.model_routing = resolve_model_routing(self.llm, self.config)
        self.llm_runtime = llm_runtime or LLMRuntime(
            self.model_routing,
            llm_args=self.llm_args,
            task_id=task_id,
            light_temperature=self.config.light_temperature,
            structured_repair_attempts=self.config.structured_repair_attempts,
        )

        source_resolver = SourceResolver(tools)
        read_capability_names = {
            item.name
            for item in source_resolver.capabilities
            if item.classification == "transaction_read"
        }
        self.semantic_planner = LLMSemanticPlanner(
            self.llm_runtime, read_capability_names
        )
        self.evidence_resolver = EvidenceResolver()
        self.need_registry = NeedRegistry(
            capabilities=read_capability_names,
            evidence_resolver=self.evidence_resolver,
        )
        self.context_compressor = (
            ToolContextCompressor(
                self.llm_runtime, self.config.max_compressed_tool_chars
            )
            if self.config.context_compressor_enabled
            else None
        )
        self.guard = ToolCallGuard(tools, self.budget)
        self.tool_exposure = ToolExposureResolver(
            tools,
            expose_knowledge=self.config.decision_knowledge_tools_enabled,
        )
        self.source_resolver = source_resolver
        self.need_resolver = NeedResolver(self.config)

        skill_fallback = (
            LLMSkillFallback(self.llm_runtime)
            if self.config.skill_llm_fallback_enabled
            else None
        )
        self.skills = SkillRuntime(
            matcher=SkillMatcher(
                self.config.max_active_skills,
                semantic_fallback=skill_fallback,
            ),
            max_references_per_skill=self.config.max_skill_references_per_skill,
            max_trace_events=self.config.max_skill_trace_events,
        )

        configure_retrieval_cache(
            enabled=self.config.retrieval_cache_enabled,
            ttl_seconds=self.config.retrieval_cache_ttl,
            retriever_version=self.config.retriever_version,
            kb_version=self.config.kb_version,
        )
        configure_embedding_cache(
            enabled=self.config.embedding_cache_enabled,
            model_version=self.config.embedding_model_version,
            chunking_version=self.config.chunking_version,
        )
        self._retrieval_cache_baseline = get_retrieval_cache_metrics()
        self._embedding_cache_baseline = get_embedding_cache_metrics()

        self.policy_engine = PassthroughPolicyEngine()
        self.memory: MemoryService | None = None
        if self.config.memory_enabled:
            store = memory_store or JsonMemoryStore(
                self.config.memory_dir,
                max_episodes_per_user=self.config.memory_max_episodes_per_user,
            )
            extractor = memory_extractor or LLMPreferenceExtractor(
                runtime=self.llm_runtime,
            )
            manager = ProfileMemoryManager(
                store,
                extractor,
                ProfileMemoryGate(self.config.memory_min_profile_confidence),
            )
            self.memory = MemoryService(
                store,
                manager,
                max_recalled_episodes=self.config.memory_max_recalled_episodes,
                max_context_chars=self.config.memory_max_context_chars,
                episode_extractor=LLMEpisodeExtractor(self.llm_runtime),
            )
            if memory_user_id:
                self.memory.bind(memory_user_id)

        self.workflow = PolicyPilotWorkflow(self)
        self.last_graph_state: PolicyPilotGraphState | None = None

    @property
    def system_prompt(self) -> str:
        return build_system_prompt(self.domain_policy)

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> PolicyPilotState:
        history = list(message_history or [])
        assert all(is_valid_agent_history_message(message) for message in history)
        state = PolicyPilotState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            run_id=self.llm_runtime.run_id,
            task_id=self.task_id,
            version_metadata={
                "agent_version": self.config.agent_version,
                "prompt_version": self.config.prompt_version,
                "retriever_version": self.config.retriever_version,
                "kb_version": self.config.kb_version,
            },
        )
        for message in history:
            self._observe(message, state)
        return state

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: PolicyPilotState
    ):
        try:
            result = self.workflow.invoke(message, state)
        except GraphRecursionError:
            state.add_error(
                PolicyPilotErrorType.BUDGET_EXHAUSTED,
                "Internal graph recursion limit reached.",
                source="langgraph",
            )
            state.control.recovery_failure_count += 1
            return self._finish_message(
                AssistantMessage.text(
                    "I cannot safely continue because the internal recovery budget was exhausted."
                ),
                state,
            )
        self.last_graph_state = result
        return result["final_action"], result["policy_state"]

    def save_checkpoint(self, state: PolicyPilotState):
        if not self.task_id:
            raise ValueError("A task_id is required to save a checkpoint.")
        return self.checkpoints.save(self.task_id, state)

    def load_checkpoint(self) -> PolicyPilotState | None:
        if not self.task_id:
            raise ValueError("A task_id is required to load a checkpoint.")
        return self.checkpoints.load(self.task_id)

    def _finish_message(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> tuple[AssistantMessage, PolicyPilotState]:
        state.messages.append(message)
        self._attach_metrics_metadata(message, state)
        return message, state

    def _memory_context(self) -> str:
        return self.memory.context() if self.memory is not None else ""

    def _memory_ids(self) -> list[str]:
        if self.memory is None:
            return []
        result = [item.episode_id for item in self.memory.snapshot.episodes]
        profile = self.memory.snapshot.profile
        if profile is not None:
            result.append(f"profile:{profile.subject_key}")
        return result

    def _active_skill_ids(self) -> list[str]:
        return list(self.skills.selected) if self.config.skills_enabled else []

    def _decision_model(self) -> str:
        return self.model_routing.model_for("decision")

    def _skill_guidance(self, phase: str, state: PolicyPilotState) -> str:
        if not self.config.skills_enabled:
            return ""
        return self.skills.guidance(
            phase,
            state,
            max_chars=self.config.max_skill_guidance_chars,
        )

    # Compatibility delegates keep the graph host contract and existing tests stable.
    def _activate_recovery_skill(
        self, outcomes: list[ObservationOutcome], state: PolicyPilotState
    ) -> None:
        activate_recovery_skill(self, outcomes, state)

    def _bind_memory_from_state(self, state: PolicyPilotState) -> None:
        bind_memory_from_state(self, state)

    def _observe(
        self, message: Message, state: PolicyPilotState
    ) -> list[ObservationOutcome]:
        return observe(self, message, state)

    def _observe_tool_message(
        self, message: ToolMessage, state: PolicyPilotState
    ) -> ObservationOutcome:
        return observe_tool_message(self, message, state)

    def _tool_call_for_need(
        self, need: InformationNeed, state: PolicyPilotState
    ) -> ToolCall | None:
        return tool_call_for_need(self, need, state)

    def _recover_read_failure(
        self, outcomes: list[ObservationOutcome], state: PolicyPilotState
    ) -> AssistantMessage | None:
        return recover_read_failure(self, outcomes, state)

    def _call_llm(
        self, messages: list[Message], state: PolicyPilotState, call_name: str
    ) -> AssistantMessage | None:
        return call_decision(self, messages, state, call_name)

    def _proposal_error(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> tuple[str | None, PolicyPilotErrorType]:
        return proposal_error(self, message, state)

    def _validate_proposal(self, message: AssistantMessage, state: PolicyPilotState):
        return validate_proposal(self, message, state)

    def _recover_validation_failure(self, result, state: PolicyPilotState) -> bool:
        return recover_validation_failure(self, result, state)

    def _decision_tools(self, state: PolicyPilotState) -> list[Tool]:
        return self.tool_exposure.for_decision(state)

    @staticmethod
    def _decision_fallback_candidates(message: AssistantMessage):
        return decision_fallback_candidates(message)

    def _register_decision_fallback(self, candidates, state: PolicyPilotState) -> bool:
        return register_decision_fallback(self, candidates, state)

    def _record_valid_tool_calls(
        self,
        message: AssistantMessage,
        state: PolicyPilotState,
        need_id: str | None = None,
    ) -> None:
        record_valid_tool_calls(self, message, state, need_id)

    def _record_blocked_tool_calls(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> None:
        record_blocked_tool_calls(self, message, state)

    def _budget_exhaustion_message(
        self, state: PolicyPilotState
    ) -> AssistantMessage | None:
        return budget_exhaustion_message(self, state)

    def _attach_metrics_metadata(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> None:
        attach_metrics_metadata(self, message, state)

    def on_evaluation_complete(self, simulation) -> None:
        record_evaluation(self, simulation)


def create_policypilot_agent(tools, domain_policy, **kwargs) -> PolicyPilotAgent:
    return PolicyPilotAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
        config=kwargs.get("policypilot_config"),
        memory_store=kwargs.get("memory_store"),
        memory_user_id=kwargs.get("memory_user_id"),
        memory_extractor=kwargs.get("memory_extractor"),
        task_id=getattr(kwargs.get("task"), "id", None),
        llm_runtime=kwargs.get("llm_runtime"),
    )
