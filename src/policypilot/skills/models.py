"""Runtime models for repository-backed PolicyPilot skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SkillPhase = Literal["planning", "decision", "recovery"]


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    version: str = "1.0"
    purpose: str = ""
    tags: tuple[str, ...] = ()
    phases: tuple[SkillPhase, ...] = ("planning", "decision", "recovery")
    priority: int = 50
    required_state_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillReference:
    id: str
    description: str
    path: Path
    applicable_phases: tuple[SkillPhase, ...]
    trigger_tags: tuple[str, ...] = ()
    priority: int = 50


@dataclass(frozen=True)
class SkillArtifact:
    metadata: SkillMetadata
    sections: dict[str, str] = field(default_factory=dict)
    available_references: tuple[SkillReference, ...] = ()

    def guidance(self, phase: SkillPhase) -> str:
        heading = {
            "planning": "Planning Guidance",
            "decision": "Decision Guidance",
            "recovery": "Recovery Guidance",
        }[phase]
        return self.sections.get(heading, "").strip()


@dataclass(frozen=True)
class LoadedSkillReference:
    metadata: SkillReference
    content: str


@dataclass(frozen=True)
class SkillGuidanceContext:
    skill_id: str
    skill_version: str
    phase: SkillPhase
    core_guidance: str
    loaded_references: tuple[LoadedSkillReference, ...] = ()

    @property
    def loaded_reference_ids(self) -> tuple[str, ...]:
        return tuple(item.metadata.id for item in self.loaded_references)

    def render(self) -> str:
        parts = [f"[{self.skill_id}@{self.skill_version}]", self.core_guidance]
        parts.extend(
            f'<skill_reference id="{item.metadata.id}">\n{item.content}\n</skill_reference>'
            for item in self.loaded_references
        )
        return "\n\n".join(part for part in parts if part)


@dataclass(frozen=True)
class SkillTraceEvent:
    event: str
    skill_id: str
    version: str
    phase: SkillPhase | None = None
    reference_ids: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event,
            "skill_id": self.skill_id,
            "version": self.version,
            "phase": self.phase,
            "reference_ids": list(self.reference_ids),
            "reason": self.reason,
        }
