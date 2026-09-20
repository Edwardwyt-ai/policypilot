"""Registration adapter for the tau2 registry."""

from policypilot.agent import create_policypilot_agent
from tau2.registry import registry

AGENT_NAME = "policypilot"


def register_policypilot(name: str = AGENT_NAME) -> str:
    """Register PolicyPilot with tau2's global registry if needed."""
    if registry.get_agent_factory(name) is None:
        registry.register_agent_factory(create_policypilot_agent, name)
    return name
