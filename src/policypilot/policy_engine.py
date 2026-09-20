"""Decision-policy interface placeholder for a later architecture phase."""

from __future__ import annotations

from typing import Protocol

from policypilot.state import PolicyPilotState
from tau2.data_model.message import AssistantMessage


class PolicyEngine(Protocol):
    def check(
        self, action: AssistantMessage, state: PolicyPilotState
    ) -> str | None: ...


class PassthroughPolicyEngine:
    def check(self, action: AssistantMessage, state: PolicyPilotState) -> str | None:
        return None
