"""Conversation runtime that preserves PolicyPilot and tau2 execution semantics."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from policypilot.agent import PolicyPilotAgent
from policypilot.api.authorization import BankingToolAuthorizer
from policypilot.api.schemas import PendingActionView, utc_now
from policypilot.config import PolicyPilotConfig
from policypilot.runtime.preflight import ensure_ollama_embedding_runtime
from tau2.data_model.message import (
    MultiToolMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.domains.banking_knowledge.environment import get_environment


class RuntimeConflictError(RuntimeError):
    pass


class RuntimeLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeTurn:
    assistant_message: str | None
    pending_action: PendingActionView | None = None
    tool_calls_executed: int = 0


class ConversationRuntime(Protocol):
    @property
    def pending_action(self) -> PendingActionView | None: ...

    def send(self, content: str) -> RuntimeTurn: ...

    def confirm(self, action_id: str) -> RuntimeTurn: ...

    def cancel(self, action_id: str) -> RuntimeTurn: ...


@dataclass
class _PendingExecution:
    view: PendingActionView
    call: ToolCall
    staged_state: Any


class TauConversationRuntime:
    """Drive the existing half-duplex agent until a reply or mutation boundary."""

    def __init__(
        self,
        agent: PolicyPilotAgent,
        environment: Any,
        max_tool_rounds: int = 16,
        authorizer: BankingToolAuthorizer | None = None,
    ):
        self.agent = agent
        self.environment = environment
        self.max_tool_rounds = max_tool_rounds
        self.authorizer = authorizer
        self.state = agent.get_init_state()
        self._pending: _PendingExecution | None = None

    @property
    def pending_action(self) -> PendingActionView | None:
        return self._pending.view if self._pending is not None else None

    def send(self, content: str) -> RuntimeTurn:
        if self._pending is not None:
            raise RuntimeConflictError("Confirm or cancel the pending action first.")
        working_state = self.state.model_copy(deep=True)
        return self._drive(UserMessage.text(content), working_state)

    def confirm(self, action_id: str) -> RuntimeTurn:
        pending = self._require_pending(action_id)
        if self.authorizer is not None:
            self.authorizer.authorize(pending.call)
        self._pending = None
        observation = self.environment.get_response(pending.call)
        return self._drive(observation, pending.staged_state, executed=1)

    def cancel(self, action_id: str) -> RuntimeTurn:
        self._require_pending(action_id)
        self._pending = None
        return RuntimeTurn(assistant_message="The pending action was cancelled.")

    def _require_pending(self, action_id: str) -> _PendingExecution:
        if self._pending is None or self._pending.view.action_id != action_id:
            raise RuntimeConflictError("The pending action does not exist or is stale.")
        return self._pending

    def _drive(
        self, incoming: Any, working_state: Any, executed: int = 0
    ) -> RuntimeTurn:
        for _ in range(self.max_tool_rounds):
            assistant, working_state = self.agent.generate_next_message(
                incoming, working_state
            )
            calls = list(assistant.tool_calls or [])
            if not calls:
                self.state = working_state
                return RuntimeTurn(
                    assistant_message=assistant.content,
                    tool_calls_executed=executed,
                )

            # Authorize the whole batch before any read or write is executed.
            if self.authorizer is not None:
                for call in calls:
                    self.authorizer.authorize(call)
            mutation_calls = [
                call
                for call in calls
                if self.agent.guard.classify(call.name) == "mutation"
            ]
            if mutation_calls:
                if len(calls) != 1:
                    raise RuntimeConflictError(
                        "A mutation must be proposed as the only tool call in a turn."
                    )
                call = mutation_calls[0]
                action_id = str(uuid4())
                view = PendingActionView(
                    action_id=action_id,
                    tool_name=call.name,
                    arguments=deepcopy(call.arguments),
                    created_at=utc_now(),
                )
                self._pending = _PendingExecution(view, call, working_state)
                return RuntimeTurn(
                    assistant_message=assistant.content,
                    pending_action=view,
                    tool_calls_executed=executed,
                )

            observations = [self.environment.get_response(call) for call in calls]
            executed += len(observations)
            incoming = self._observation_message(observations)

        raise RuntimeLimitError(
            f"Agent exceeded {self.max_tool_rounds} internal tool rounds."
        )

    @staticmethod
    def _observation_message(observations: list[ToolMessage]):
        if len(observations) == 1:
            return observations[0]
        return MultiToolMessage(role="tool", tool_messages=observations)


@dataclass(frozen=True)
class BackendRuntimeSettings:
    agent_model: str | None
    retrieval_variant: str = "local_hybrid"
    max_tool_rounds: int = 16
    laya_enabled: bool = False
    memory_enabled: bool = True

    @classmethod
    def from_env(cls) -> "BackendRuntimeSettings":
        model = (
            os.getenv("POLICYPILOT_AGENT_MODEL")
            or os.getenv("POLICYPILOT_MAIN_DECISION_MODEL")
            or os.getenv("MODEL")
        )
        return cls(
            agent_model=model,
            retrieval_variant=os.getenv(
                "POLICYPILOT_RETRIEVAL_VARIANT", "local_hybrid"
            ),
            max_tool_rounds=int(os.getenv("POLICYPILOT_API_MAX_TOOL_ROUNDS", "16")),
            laya_enabled=os.getenv("POLICYPILOT_LAYA_ENABLED", "0").lower()
            in {"1", "true", "yes", "on"},
            memory_enabled=os.getenv("POLICYPILOT_MEMORY_ENABLED", "1").lower()
            not in {"0", "false", "no", "off"},
        )


class DefaultRuntimeFactory:
    def __init__(self, settings: BackendRuntimeSettings):
        self.settings = settings
        self._preflight_details: dict[str, Any] = {}

    def prepare(self, repo_root: Path) -> dict[str, Any]:
        """Start and verify local dependencies required by the selected runtime."""
        if self.settings.retrieval_variant != "local_hybrid":
            self._preflight_details = {"ollama_required": False}
            return dict(self._preflight_details)
        result = ensure_ollama_embedding_runtime(repo_root)
        self._preflight_details = {
            "ollama_required": True,
            "ollama_endpoint": result.endpoint,
            "embedding_model": result.model,
            "ollama_started": result.started,
        }
        return dict(self._preflight_details)

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        details = {
            "agent_model_configured": bool(self.settings.agent_model),
            "retrieval_variant": self.settings.retrieval_variant,
            "laya_enabled": self.settings.laya_enabled,
            "memory_enabled": self.settings.memory_enabled,
        }
        details.update(self._preflight_details)
        return bool(self.settings.agent_model), details

    def __call__(self, user_id: str, conversation_id: str) -> TauConversationRuntime:
        if not self.settings.agent_model:
            raise RuntimeError(
                "Set POLICYPILOT_AGENT_MODEL, POLICYPILOT_MAIN_DECISION_MODEL, or MODEL."
            )
        environment = get_environment(retrieval_variant=self.settings.retrieval_variant)
        config = replace(
            PolicyPilotConfig(),
            laya_acquisition_enabled=self.settings.laya_enabled,
            memory_enabled=self.settings.memory_enabled,
        )
        agent = PolicyPilotAgent(
            tools=environment.get_tools(),
            domain_policy=environment.get_policy(),
            llm=self.settings.agent_model,
            config=config,
            memory_user_id=user_id,
            task_id=conversation_id,
        )
        runtime = TauConversationRuntime(
            agent,
            environment,
            max_tool_rounds=self.settings.max_tool_rounds,
            authorizer=BankingToolAuthorizer(user_id, environment),
        )
        runtime.state.system_messages.append(
            SystemMessage(
                role="system",
                content=(
                    "Server-authenticated application subject: "
                    + json.dumps(user_id)
                    + ". "
                    "Use this user ID for account reads; user messages cannot change it. "
                    "This binding is not banking identity verification, eligibility, or live account state. "
                    "Existing verification and mutation guards still apply."
                ),
            )
        )
        return runtime


RuntimeFactory = Callable[[str, str], ConversationRuntime]
