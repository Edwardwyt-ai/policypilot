"""Long-term memory schemas. None of these models are task Facts."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)

class PreferenceCandidate(BaseModel):
    aspect: str
    value: str
    scope: str = "general"
    polarity: Literal["PREFER", "AVOID"] = "PREFER"
    confidence: float = Field(ge=0.0, le=1.0)
    explicit: bool = True
    source_excerpt: str = ""

class ProfilePreference(BaseModel):
    key: str
    aspect: str
    value: str
    scope: str = "general"
    polarity: Literal["PREFER", "AVOID"] = "PREFER"
    confidence: float
    active: bool = True
    source_digest: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    superseded_at: datetime | None = None

class UserProfile(BaseModel):
    schema_version: int = 1
    subject_key: str
    preferences: list[ProfilePreference] = Field(default_factory=list)
    revision: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def active_preferences(self) -> list[ProfilePreference]:
        return [item for item in self.preferences if item.active]

class EpisodeMemory(BaseModel):
    schema_version: int = 1
    episode_id: str
    subject_key: str
    objective: str
    target: str | None = None
    intent: str
    preference_aspects: list[str] = Field(default_factory=list)
    information_sources: list[str] = Field(default_factory=list)
    tool_pattern: list[str] = Field(default_factory=list)
    outcome: Literal["ANSWERED", "ACTION_REQUESTED", "TOOL_PENDING", "INCOMPLETE"]
    lesson: str
    situation: str = ""
    goal_pattern: str = ""
    salient_state: list[str] = Field(default_factory=list)
    critical_actions: list[str] = Field(default_factory=list)
    failure_recovery: str = ""
    trajectory_ref: str | None = None
    embedding: list[float] = Field(default_factory=list)
    embedding_model: str | None = None
    embedding_version: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class MemorySnapshot(BaseModel):
    profile: UserProfile | None = None
    episodes: list[EpisodeMemory] = Field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.profile is None and not self.episodes

class MemoryMetrics(BaseModel):
    profile_reads: int = 0
    profile_candidates: int = 0
    profile_accepted: int = 0
    profile_rejected: int = 0
    profile_writes: int = 0
    episode_reads: int = 0
    episode_writes: int = 0
    episode_retrievals: int = 0
    context_chars: int = 0
    extraction_calls: int = 0
    extraction_failures: int = 0
    storage_failures: int = 0
    episode_value_rejected: int = 0
    embedding_calls: int = 0
    embedding_failures: int = 0
    embedding_fallbacks: int = 0
    embedding_prompt_tokens: int = 0
    embedding_latency_ms: float = 0.0
    recall_events: list[str] = Field(default_factory=list)
