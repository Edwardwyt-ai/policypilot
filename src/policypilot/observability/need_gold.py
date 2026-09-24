"""Evaluator-only gold labels for reusable internal Need evaluation.

This module is intentionally outside the agent runtime.  It must only be
imported by offline evaluation and tests so hidden benchmark labels never
become planner context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AcquisitionSource = Literal[
    "user_dialogue",
    "policy_kb",
    "transaction_tool",
    "prior_verified_evidence",
]


class ExpectedNeed(BaseModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class AllowedAcquisition(BaseModel):
    need_id: str = Field(min_length=1)
    sources: list[AcquisitionSource] = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)


class CompletionCondition(BaseModel):
    need_id: str = Field(min_length=1)
    condition: str = Field(min_length=1)


class TaskNeedGold(BaseModel):
    expected_needs: list[ExpectedNeed] = Field(min_length=1)
    allowed_acquisition: list[AllowedAcquisition] = Field(min_length=1)
    completion_condition: list[CompletionCondition] = Field(min_length=1)

    @model_validator(mode="after")
    def references_are_complete(self) -> "TaskNeedGold":
        expected = [need.id for need in self.expected_needs]
        if len(expected) != len(set(expected)):
            raise ValueError("expected_needs contains duplicate ids")
        expected_set = set(expected)

        acquisition = [item.need_id for item in self.allowed_acquisition]
        completion = [item.need_id for item in self.completion_condition]
        if set(acquisition) != expected_set or len(acquisition) != len(set(acquisition)):
            raise ValueError("allowed_acquisition must cover every Need exactly once")
        if set(completion) != expected_set or len(completion) != len(set(completion)):
            raise ValueError("completion_condition must cover every Need exactly once")
        return self


class NeedGoldDataset(BaseModel):
    schema_version: Literal["need-gold-v1"]
    domain: Literal["banking_knowledge"]
    source_task_count: int = Field(ge=1)
    selected_task_count: int = Field(ge=1)
    selection_method: str = Field(min_length=1)
    tasks: dict[str, TaskNeedGold]

    @model_validator(mode="after")
    def selected_count_matches(self) -> "NeedGoldDataset":
        if self.selected_task_count != len(self.tasks):
            raise ValueError("selected_task_count does not match tasks")
        return self


def default_need_gold_path() -> Path:
    return (
        Path(__file__).absolute().parents[3]
        / "data"
        / "policypilot"
        / "evaluation"
        / "need_gold_v1.json"
    )


def load_need_gold(path: Path | None = None) -> NeedGoldDataset:
    gold_path = path or default_need_gold_path()
    return NeedGoldDataset.model_validate_json(gold_path.read_text(encoding="utf-8"))


def load_raw_need_gold(path: Path | None = None) -> dict:
    """Load labels for tools that need plain JSON rather than Pydantic models."""

    gold_path = path or default_need_gold_path()
    return json.loads(gold_path.read_text(encoding="utf-8"))


__all__ = [
    "AllowedAcquisition",
    "CompletionCondition",
    "ExpectedNeed",
    "NeedGoldDataset",
    "TaskNeedGold",
    "default_need_gold_path",
    "load_need_gold",
    "load_raw_need_gold",
]
