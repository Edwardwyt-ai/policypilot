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
        if any(
            need.status == "EXHAUSTED" and need.critical and need.blocking
            for need in state.information_needs
        ):
            return "A critical information need is exhausted and remains unresolved."
        content = (action.content or "").casefold()
        claims_success = any(
            marker in content
            for marker in (
                "successfully completed",
                "has been completed",
                "was completed",
                "successfully updated",
                "successfully changed",
            )
        )
        if claims_success and not any(
            mutation.status == "CONFIRMED" for mutation in state.mutations
        ):
            return "The response claims a completed mutation without confirmation."
        return None
