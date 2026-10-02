from collections.abc import Callable

import pytest

from policypilot.agent import PolicyPilotAgent
from policypilot.config import PolicyPilotConfig
from policypilot.tool_policy import ToolBudget
from tau2.environment.tool import as_tool
from tau2.environment.toolkit import ToolType, is_tool


@is_tool(ToolType.READ)
def read_account(account_id: str) -> str:
    """Read an account."""
    return f"account {account_id}"


@is_tool(ToolType.WRITE)
def mutate_account(account_id: str) -> str:
    """Mutate an account."""
    return f"mutated {account_id}"


@is_tool(ToolType.READ)
def KB_search(query: str) -> str:
    """Search the knowledge base."""
    return query


@is_tool(ToolType.WRITE)
def log_verification(
    name: str,
    user_id: str,
    address: str,
    email: str,
    phone_number: str,
    date_of_birth: str,
    time_verified: str,
) -> str:
    """Log a completed identity verification."""
    return f"Verified {name} at {time_verified}"


@pytest.fixture
def tools():
    return [
        as_tool(read_account),
        as_tool(mutate_account),
        as_tool(KB_search),
        as_tool(log_verification),
    ]


@pytest.fixture
def agent_factory(tools) -> Callable[..., PolicyPilotAgent]:
    def _factory(**kwargs) -> PolicyPilotAgent:
        kwargs.setdefault("config", PolicyPilotConfig(coverage_llm_enabled=False))
        return PolicyPilotAgent(
            tools=tools,
            domain_policy="Use the provided tools and policy.",
            llm="test-model",
            budget=kwargs.pop("budget", ToolBudget()),
            **kwargs,
        )

    return _factory
