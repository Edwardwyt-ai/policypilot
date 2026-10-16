"""Seeded user initialization without benchmark tasks or expected answers."""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tau2.domains.banking_knowledge.data_model import TransactionalDB


class UserScenario(BaseModel):
    """Private simulator input, never injected into the tested agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = 1
    seed: int
    user_id: str
    language: str = "zh-CN"
    known_identity: dict[str, str]
    objective: str
    preference: str
    style: str
    disclosure: str
    mutation_policy: Literal["ask", "decline"]


class UserMove(BaseModel):
    """A simulator action; confirmation is a separate operation, not text."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["say", "confirm", "cancel", "stop"]
    content: str = Field(default="", max_length=4000)


def initialize_user(
    db: TransactionalDB, seed: int, user_id: str | None = None
) -> UserScenario:
    """Sample only from actual synthetic users, using a private random stream."""
    rng = random.Random(seed)
    users = db.users.data
    if not users:
        raise ValueError("The simulated database contains no users")
    selected = user_id if user_id is not None else rng.choice(sorted(users))
    if selected not in users:
        raise ValueError("Unknown simulated user ID")
    identity = {
        key: str(value)
        for key, value in users[selected].items()
        if key
        in {"name", "user_id", "address", "email", "phone_number", "date_of_birth"}
        and value is not None
    }
    return UserScenario(
        seed=seed,
        user_id=selected,
        known_identity=identity,
        objective=rng.choice(
            [
                "Explore personal card options that fit my everyday spending.",
                "Understand how I could reduce banking or card fees.",
                "Understand my existing accounts and available next steps.",
                "Understand rewards and cashback conditions before making a decision.",
            ]
        ),
        preference=rng.choice(
            [
                "Prefer lower ongoing costs, but consider tradeoffs.",
                "Prefer cashback and simple conditions.",
                "Prefer flexibility without committing to a new product yet.",
            ]
        ),
        style=rng.choice(
            ["brief and conversational", "uncertain and nontechnical", "detailed"]
        ),
        disclosure=rng.choice(
            [
                "Share preferences gradually when relevant.",
                "Explain the main preferences early.",
            ]
        ),
        mutation_policy=rng.choice(["ask", "decline"]),
    )
