"""Need-driven LangGraph workflow with external tau2 tool execution."""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from policypilot.config import PolicyPilotConfig
from policypilot.dependencies import dependency_snapshot
from policypilot.errors import PolicyPilotErrorType
from policypilot.needs import (
    decision_ready,
    knowledge_tool,
    select_next_blocking_need,
)
from policypilot.retrieval import build_retrieval_call
from policypilot.runtime.actions import ValidationResult
from policypilot.state import InformationNeed, PolicyPilotState
from policypilot.workflow.context import AgentContext, build_agent_context
from tau2.agent.base_agent import ValidAgentInputMessage
from tau2.data_model.message import AssistantMessage, Message, ToolCall
from tau2.environment.tool import Tool


class PolicyPilotGraphState(TypedDict, total=False):
    policy_state: PolicyPilotState
    latest_observation: ValidAgentInputMessage
    observation_outcomes: list[Any]
    constructed_context: AgentContext
    proposed_action: AssistantMessage
    final_action: AssistantMessage
    active_need: InformationNeed
    validation_error: str
    validation_result: ValidationResult
    recovery_exhausted: bool
    fallback_registered: bool
    node_trace: list[str]


class WorkflowHost(Protocol):
    tools: list[Tool]
    config: PolicyPilotConfig
    context_compressor: Any

    def _observe(self, message: Message, state: PolicyPilotState) -> list[Any]: ...
    def _budget_exhaustion_message(
        self, state: PolicyPilotState
    ) -> AssistantMessage | None: ...
    def _recover_read_failure(
        self, outcomes: list[Any], state: PolicyPilotState
    ) -> AssistantMessage | None: ...
    def _call_llm(
        self, messages: list[Message], state: PolicyPilotState, call_name: str
    ) -> AssistantMessage | None: ...
    def _proposal_error(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> tuple[str | None, PolicyPilotErrorType]: ...
    def _validate_proposal(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> ValidationResult: ...
    def _recover_validation_failure(
        self, result: ValidationResult, state: PolicyPilotState
    ) -> bool: ...
    def _decision_tools(self, state: PolicyPilotState) -> list[Tool]: ...
    def _decision_fallback_candidates(
        self, message: AssistantMessage
    ) -> list[Any]: ...
    def _register_decision_fallback(
        self, candidates: list[Any], state: PolicyPilotState
    ) -> bool: ...
    def _record_valid_tool_calls(
        self,
        message: AssistantMessage,
        state: PolicyPilotState,
        need_id: str | None = None,
    ) -> None: ...
    def _record_blocked_tool_calls(
        self, message: AssistantMessage, state: PolicyPilotState
    ) -> None: ...
    def _finish_message(self, message: AssistantMessage, state: PolicyPilotState): ...
    def _tool_call_for_need(
        self, need: InformationNeed, state: PolicyPilotState
    ) -> ToolCall | None: ...
    def _memory_context(self) -> str: ...
    def _skill_guidance(self, phase: str, state: PolicyPilotState) -> str: ...
    def _active_skill_ids(self) -> list[str]: ...
    def _memory_ids(self) -> list[str]: ...
    def _decision_model(self) -> str: ...
    def _activate_recovery_skill(
        self, outcomes: list[Any], state: PolicyPilotState
    ) -> None: ...


Route = Literal[
    "recover",
    "route_need",
    "ask_user",
    "retrieve_policy",
    "read_tool",
    "unknown",
    "decision",
    "validate",
    "finalize",
]


class PolicyPilotWorkflow:
    def __init__(self, host: WorkflowHost):
        self.host = host
        graph = StateGraph(PolicyPilotGraphState)
        for name in (
            "ingest",
            "update_state",
            "recover",
            "route_need",
            "ask_user",
            "retrieve_policy",
            "read_tool",
            "unknown",
            "build_context",
            "decision",
            "validate",
            "guard_recover",
            "finalize",
        ):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "ingest")
        graph.add_conditional_edges(
            "ingest",
            self.after_ingest,
            {"update_state": "update_state", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "update_state",
            self.after_update,
            {"recover": "recover", "route_need": "route_need", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "recover",
            self.after_recover,
            {"route_need": "route_need", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "route_need",
            self.need_route,
            {
                "ask_user": "ask_user",
                "retrieve_policy": "retrieve_policy",
                "read_tool": "read_tool",
                "unknown": "unknown",
                "decision": "build_context",
            },
        )
        for name in ("ask_user", "retrieve_policy", "read_tool", "unknown"):
            graph.add_edge(name, "finalize")
        graph.add_edge("build_context", "decision")
        graph.add_conditional_edges(
            "decision",
            self.after_decision,
            {
                "finalize": "finalize",
                "validate": "validate",
                "route_need": "route_need",
            },
        )
        graph.add_conditional_edges(
            "validate",
            self.after_validate,
            {"guard_recover": "guard_recover", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "guard_recover",
            self.after_guard_recover,
            {"route_need": "route_need", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)
        self.compiled = graph.compile()

    def invoke(
        self, observation: ValidAgentInputMessage, policy_state: PolicyPilotState
    ) -> PolicyPilotGraphState:
        return cast(
            PolicyPilotGraphState,
            self.compiled.invoke(
                {
                    "policy_state": policy_state,
                    "latest_observation": observation,
                    "node_trace": [],
                },
                config={"recursion_limit": self.host.config.max_graph_steps},
            ),
        )

    @staticmethod
    def trace(state, node, **updates):
        return {"node_trace": [*state.get("node_trace", []), node], **updates}

    def ingest(self, gs):
        final = self.host._budget_exhaustion_message(gs["policy_state"])
        return self.trace(gs, "ingest", **({"final_action": final} if final else {}))

    @staticmethod
    def after_ingest(gs):
        return "finalize" if gs.get("final_action") else "update_state"

    def update_state(self, gs):
        state = gs["policy_state"]
        outcomes = self.host._observe(gs["latest_observation"], state)
        state.control.step_count += 1
        if state.control.no_progress_count >= self.host.config.max_no_progress_turns:
            state.release_stalled_blockers(reason="bounded_no_progress_recovery")
        final = self.host._budget_exhaustion_message(state)
        return self.trace(
            gs,
            "update_state",
            policy_state=state,
            observation_outcomes=outcomes,
            **({"final_action": final} if final else {}),
        )

    @staticmethod
    def after_update(gs):
        if gs.get("final_action"):
            return "finalize"
        outcomes = gs.get("observation_outcomes", [])
        if any(
            getattr(o, "failed", False) or getattr(o, "retrieval_empty", False)
            for o in outcomes
        ):
            return "recover"
        return "route_need"

    def recover(self, gs):
        self.host._activate_recovery_skill(
            gs.get("observation_outcomes", []), gs["policy_state"]
        )
        recovered = self.host._recover_read_failure(
            gs.get("observation_outcomes", []), gs["policy_state"]
        )
        return self.trace(
            gs, "recover", **({"final_action": recovered} if recovered else {})
        )

    @staticmethod
    def after_recover(gs):
        return "finalize" if gs.get("final_action") else "route_need"

    def route_need(self, gs):
        state = gs["policy_state"]
        need = select_next_blocking_need(state, self.host.config)
        state.control.need_selection_events.append({
            "turn": len(state.messages),
            "selected_need_id": need.id if need else None,
            "semantic_key": need.semantic_key if need else None,
            "source": need.source if need else None,
            "criticality": "CRITICAL" if need and need.critical else None,
            "dependency": dependency_snapshot(need, state) if need else None,
            "blocking_open_count": sum(
                item.status == "OPEN" and item.blocking and not item.exhausted
                for item in state.information_needs
            ),
            "optional_open_count": sum(
                item.status == "OPEN" and not item.blocking
                for item in state.information_needs
            ),
        })
        return self.trace(gs, "route_need", active_need=need)

    def need_route(self, gs):
        state = gs["policy_state"]
        need = gs.get("active_need")
        if decision_ready(state, self.host.config):
            return "decision"
        if need is not None and need.status == "EXHAUSTED":
            return "unknown"
        return {
            "USER": "ask_user",
            "POLICY": "retrieve_policy",
            "TOOL": "read_tool",
        }.get(need.source if need else "UNKNOWN", "unknown")

    def ask_user(self, gs):
        need = gs["active_need"]
        need.acquisition_count += 1
        gs["policy_state"].control.acquisition_events.append({
            "turn": len(gs["policy_state"].messages),
            "tool_call_id": None,
            "need_id": need.id,
            "semantic_key": need.semantic_key,
            "source": "USER",
            "acquisition_type": "clarification",
            "status": "REQUESTED",
            "result": None,
            "final_status": need.status,
        })
        text = (
            need.question
            or f"Please provide the missing {need.aspect.replace('_', ' ')}."
        )
        return self.trace(gs, "ask_user", final_action=AssistantMessage.text(text))

    def retrieve_policy(self, gs):
        state = gs["policy_state"]
        need = gs["active_need"]
        tool = knowledge_tool(self.host.tools)
        if tool is None:
            return self.trace(
                gs,
                "retrieve_policy",
                final_action=AssistantMessage.text(
                    "I cannot access the policy source needed to continue."
                ),
            )
        message = AssistantMessage(
            role="assistant", tool_calls=[build_retrieval_call(state, need, tool)]
        )
        error, _ = self.host._proposal_error(message, state)
        if error:
            return self.trace(
                gs,
                "retrieve_policy",
                final_action=AssistantMessage.text(
                    "I cannot safely complete the required policy lookup."
                ),
            )
        self.host._record_valid_tool_calls(message, state, need.id)
        return self.trace(
            gs, "retrieve_policy", policy_state=state, final_action=message
        )

    def read_tool(self, gs):
        state = gs["policy_state"]
        need = gs["active_need"]
        call = self.host._tool_call_for_need(need, state)
        if call is None:
            return self.trace(
                gs,
                "read_tool",
                final_action=AssistantMessage.text(
                    f"I need additional information to perform the {need.aspect.replace('_', ' ')} lookup."
                ),
            )
        message = AssistantMessage(role="assistant", tool_calls=[call])
        error, _ = self.host._proposal_error(message, state)
        if error:
            return self.trace(
                gs,
                "read_tool",
                final_action=AssistantMessage.text(
                    "I cannot safely perform the required account lookup."
                ),
            )
        self.host._record_valid_tool_calls(message, state, need.id)
        return self.trace(gs, "read_tool", policy_state=state, final_action=message)

    def unknown(self, gs):
        need = gs.get("active_need")
        if need is not None and need.status == "EXHAUSTED":
            text = (
                "I cannot safely complete this request because the required "
                f"{need.aspect.replace('_', ' ')} information could not be verified."
            )
        else:
            text = (
                f"I need clarification about {need.aspect.replace('_', ' ')} before I can continue."
                if need
                else "I need clarification before I can continue."
            )
        return self.trace(
            gs,
            "unknown",
            final_action=AssistantMessage.text(text),
        )

    def build_context(self, gs):
        state = gs["policy_state"]
        context = build_agent_context(
            state,
            self.host._decision_tools(state),
            self.host.config,
            memory_context=self.host._memory_context(),
            memory_ids=self.host._memory_ids(),
            skill_guidance=self.host._skill_guidance("decision", state),
            skills=self.host._active_skill_ids(),
            model=self.host._decision_model(),
            prompt_version=self.host.config.prompt_version,
            compressor=self.host.context_compressor,
        )
        state.control.context_message_count = len(context.messages)
        state.control.context_estimated_size = context.estimated_size
        state.control.current_context_id = context.context_id
        return self.trace(
            gs, "build_context", policy_state=state, constructed_context=context
        )

    def decision(self, gs):
        result = self.host._call_llm(
            gs["constructed_context"].messages,
            gs["policy_state"],
            "policypilot_decision",
        )
        if result is None:
            return self.trace(
                gs,
                "decision",
                final_action=AssistantMessage.text(
                    "I cannot safely continue because the model call failed."
                ),
            )
        candidates = self.host._decision_fallback_candidates(result)
        if candidates:
            registered = self.host._register_decision_fallback(
                candidates, gs["policy_state"]
            )
            if registered:
                return self.trace(gs, "decision", fallback_registered=True)
            return self.trace(
                gs,
                "decision",
                final_action=AssistantMessage.text(
                    "I cannot safely continue because the information recovery budget was exhausted."
                ),
            )
        return self.trace(gs, "decision", proposed_action=result)

    @staticmethod
    def after_decision(gs):
        if gs.get("final_action"):
            return "finalize"
        if gs.get("fallback_registered"):
            return "route_need"
        return "validate"

    def validate(self, gs):
        proposal = gs["proposed_action"]
        state = gs["policy_state"]
        result = self.host._validate_proposal(proposal, state)
        if not result.allowed:
            self.host._record_blocked_tool_calls(proposal, state)
            state.add_error(
                result.error_type,
                result.details or result.reason_code,
                source="tool_guard",
                retryable=result.recoverable_information_gap,
                recovery_action=(
                    "register_information_need"
                    if result.recoverable_information_gap
                    else "safe_stop"
                ),
            )
            safe_stop = (
                {}
                if result.recoverable_information_gap
                else {
                    "final_action": AssistantMessage.text(
                        "I cannot safely perform that action with the information available."
                    )
                }
            )
            return self.trace(
                gs,
                "validate",
                policy_state=state,
                validation_result=result,
                validation_error=result.details or result.reason_code,
                **safe_stop,
            )
        self.host._record_valid_tool_calls(proposal, state)
        return self.trace(gs, "validate", policy_state=state, final_action=proposal)

    @staticmethod
    def after_validate(gs):
        result = gs.get("validation_result")
        return (
            "guard_recover"
            if result is not None and result.recoverable_information_gap
            else "finalize"
        )

    def guard_recover(self, gs):
        state = gs["policy_state"]
        result = gs["validation_result"]
        recovered = self.host._recover_validation_failure(result, state)
        if recovered:
            state.resolve_latest_error(result.error_type)
            return self.trace(gs, "guard_recover", policy_state=state)
        return self.trace(
            gs,
            "guard_recover",
            policy_state=state,
            recovery_exhausted=True,
            final_action=AssistantMessage.text(
                "I cannot safely perform that action with the information available."
            ),
        )

    @staticmethod
    def after_guard_recover(gs):
        return "finalize" if gs.get("final_action") else "route_need"

    def finalize(self, gs):
        message, state = self.host._finish_message(
            gs["final_action"], gs["policy_state"]
        )
        state.control.route_trace.extend(gs.get("node_trace", []))
        return self.trace(gs, "finalize", final_action=message, policy_state=state)
