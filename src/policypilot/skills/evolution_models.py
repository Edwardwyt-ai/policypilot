"""Contracts shared by offline skill discovery, evaluation, and runtime loading."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SkillID = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
]
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)
]
Attribution = Literal[
    "retrieval", "activation", "content", "execution", "tool", "unknown"
]


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


class EvidenceSource(BaseModel):
    kind: Literal["episode", "trajectory"]
    source_id: str
    source_path: str | None = None
    scenario_group: str | None = None
    trace_id: str
    task_id: str
    task_type: str
    success: bool | None = None
    active_skills: dict[str, str] = Field(default_factory=dict)
    attribution: Attribution = "unknown"
    failure_mode: str = ""
    observations: list[ShortText] = Field(max_length=24)


class Pattern(BaseModel):
    kind: Literal["SUCCESS_STRATEGY", "FAILURE_LESSON", "PIVOT", "PROCEDURE"]
    behavior_key: SkillID
    steps: list[ShortText] = Field(min_length=2, max_length=6)
    lesson: ShortText
    evidence_indexes: list[int] = Field(min_length=1, max_length=8)


class Extraction(BaseModel):
    patterns: list[Pattern] = Field(max_length=4)


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Each specified field is a conjunctive requirement. Values within a field are alternatives.
    intents: list[
        Literal[
            "INFORMATIONAL",
            "STATUS_CHECK",
            "ELIGIBILITY_CHECK",
            "TRANSACTIONAL",
            "CORRECTION",
            "OTHER",
        ]
    ] = Field(max_length=6)
    targets: list[ShortText] = Field(max_length=8)
    need_sources: list[Literal["USER", "POLICY", "TOOL", "UNKNOWN"]] = Field(
        max_length=4
    )
    recovery_modes: list[
        Literal["uncertain_mutation", "retrieval_empty", "tool_execution", "recovery"]
    ] = Field(max_length=4)


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: SkillID
    description: ShortText
    trigger: Trigger
    preconditions: list[
        Literal[
            "goal", "evidence", "verified_tool_fact", "open_need", "no_uncertain_write"
        ]
    ] = Field(max_length=5)
    procedure: list[ShortText] = Field(min_length=2, max_length=5)
    # Runtime owns the fixed constraints. Generated text has no access to authority settings.


class Proposal(BaseModel):
    operation: Literal["CREATE", "UPDATE", "MERGE", "RETIRE", "NO_OP"]
    targets: list[SkillID] = Field(max_length=4)
    skill: SkillSpec | None
    rationale: ShortText


class Candidate(BaseModel):
    candidate_id: str
    base_release: str
    proposal: Proposal
    cluster_id: str
    evidence_ids: list[str]
    trace_ids: list[str]
    evidence_snapshot: list[dict] = Field(default_factory=list)
    training_task_ids: list[str]
    training_scenario_groups: list[str] = Field(default_factory=list)


class EvolutionConfig(BaseModel):
    batch_size: int = Field(32, ge=1)
    cluster_candidates: int = Field(32, ge=1)
    similarity_min: float = Field(0.68, ge=0, le=1)
    representatives_per_outcome: int = Field(3, ge=1, le=8)
    min_success_tasks: int = Field(3, ge=2)
    min_repeated_failures: int = Field(3, ge=2)
    min_rate_samples: int = Field(4, ge=2)
    rate_drop: float = Field(0.20, gt=0, le=1)
    related_skills: int = Field(5, ge=1, le=12)
    max_extraction_calls: int = Field(16, ge=1)
    max_optimizer_calls: int = Field(4, ge=1)
    cluster_scan_limit: int = Field(128, ge=1)
    max_prompt_chars: int = Field(12000, ge=1000)
