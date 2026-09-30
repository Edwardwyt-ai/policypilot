"""Named context-channel budgets; values are limits, not fixed percentages."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ContextChannelBudget:
    minimum: int
    preferred: int
    maximum: int
    priority: int


CHANNEL_BUDGETS = {
    "goal": ContextChannelBudget(120, 900, 1800, 100),
    "needs": ContextChannelBudget(120, 1400, 2600, 95),
    "facts": ContextChannelBudget(200, 3200, 6400, 90),
    "evidence": ContextChannelBudget(200, 2400, 4800, 85),
    "rehydrated": ContextChannelBudget(0, 1200, 2400, 82),
    "recent_messages": ContextChannelBudget(300, 5000, 9000, 80),
    "skills": ContextChannelBudget(0, 1800, 3600, 60),
    "memory": ContextChannelBudget(0, 900, 1800, 40),
}


def bound_channel(name: str, value: str) -> str:
    budget = CHANNEL_BUDGETS[name]
    if len(value) <= budget.maximum:
        return value
    return value[: budget.maximum - 3] + "..."


def budget_manifest() -> dict[str, dict[str, int]]:
    return {name: asdict(value) for name, value in CHANNEL_BUDGETS.items()}
