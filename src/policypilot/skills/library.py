"""Immutable Skill releases and explicit, evaluation-gated publication."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel, Field

from policypilot.skills.evolution_models import Candidate, SkillSpec, digest

CONSTRAINTS = (
    "Use only tools and arguments permitted by the runtime. Respect user authorization, "
    "current policy and verified observations. Never infer completion from a tool call "
    "or bypass verification of an uncertain write."
)


class PublishedSkill(BaseModel):
    spec: SkillSpec
    version: str
    candidate_id: str
    evidence_ids: list[str]
    trace_ids: list[str] = Field(default_factory=list)
    constraints: str = CONSTRAINTS


class Release(BaseModel):
    skills: dict[str, PublishedSkill] = Field(default_factory=dict)
    retired: set[str] = Field(default_factory=set)

    @property
    def id(self) -> str:
        return digest(
            {
                "skills": {
                    key: value.model_dump(mode="json")
                    for key, value in self.skills.items()
                },
                "retired": sorted(self.retired),
            }
        )


class SkillLibrary:
    """The active pointer, proposals and release history share one SQLite transaction."""

    def __init__(self, path: Path):
        self.path = path.resolve()

    @classmethod
    def configured(cls):
        path = os.getenv("POLICYPILOT_SKILL_LIBRARY")
        return cls(Path(path)) if path else None

    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.executescript(
            "CREATE TABLE IF NOT EXISTS releases (id TEXT PRIMARY KEY, payload TEXT);"
            "CREATE TABLE IF NOT EXISTS active (slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT);"
            "CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, payload TEXT);"
            "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, payload TEXT);"
        )
        return db

    @staticmethod
    def _active(db) -> Release:
        row = db.execute(
            "SELECT r.payload FROM active a JOIN releases r ON r.id=a.id"
        ).fetchone()
        return Release.model_validate_json(row[0]) if row else Release()

    def active(self) -> Release:
        if not self.path.is_file():
            return Release()
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as db:
            return self._active(db)

    def propose(self, candidate: Candidate) -> None:
        with closing(self._open()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO candidates VALUES (?, ?)",
                (candidate.candidate_id, candidate.model_dump_json()),
            )

    def candidate(self, candidate_id: str) -> Candidate:
        with closing(self._open()) as db:
            row = db.execute(
                "SELECT payload FROM candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return Candidate.model_validate_json(row[0])

    def promote(self, candidate_id, plan, observations, policy) -> Release:
        from policypilot.skills.skill_evaluation import evaluate

        candidate = self.candidate(candidate_id)
        with closing(self._open()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            before = self._active(db)
            after = preview(before, candidate, set(plan.builtin_ids))
            report = evaluate(candidate, before, after, plan, observations, policy)
            db.execute(
                "INSERT OR REPLACE INTO reports VALUES (?, ?)",
                (candidate_id, report.model_dump_json()),
            )
            if report.passed:
                self._activate(db, after)
        if not report.passed:
            raise ValueError("Candidate did not pass: " + "; ".join(report.reasons))
        return after

    @staticmethod
    def _activate(db, release):
        db.execute(
            "INSERT OR IGNORE INTO releases VALUES (?, ?)",
            (release.id, release.model_dump_json()),
        )
        db.execute("INSERT OR REPLACE INTO active VALUES (1, ?)", (release.id,))

    def rollback(self, release_id: str) -> Release:
        with closing(self._open()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM releases WHERE id=?", (release_id,)
            ).fetchone()
            if row is None and release_id != Release().id:
                raise KeyError(release_id)
            release = Release.model_validate_json(row[0]) if row else Release()
            self._activate(db, release)
        return release


def preview(base: Release, candidate: Candidate, builtin_ids: set[str]) -> Release:
    if candidate.base_release != base.id:
        raise ValueError("Candidate is based on a different active release")
    proposal = candidate.proposal
    targets = set(proposal.targets)
    existing = (builtin_ids | base.skills.keys()) - base.retired
    spec = proposal.skill
    if len(targets) != len(proposal.targets) or targets - existing:
        raise ValueError("Invalid or inactive target")
    if proposal.operation == "CREATE":
        valid = (
            not targets
            and spec is not None
            and spec.skill_id not in existing | base.retired
        )
    elif proposal.operation == "UPDATE":
        valid = len(targets) == 1 and spec is not None and spec.skill_id in targets
    elif proposal.operation == "MERGE":
        valid = (
            len(targets) >= 2
            and spec is not None
            and (
                spec.skill_id in targets or spec.skill_id not in existing | base.retired
            )
        )
    elif proposal.operation == "RETIRE":
        valid = len(targets) == 1 and spec is None
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid skill proposal for its operation")
    result = base.model_copy(deep=True)
    result.retired.update(targets)
    for target in targets:
        result.skills.pop(target, None)
    if spec:
        trigger = spec.trigger
        if not (
            trigger.intents
            or trigger.targets
            or trigger.need_sources
            or trigger.recovery_modes
        ):
            raise ValueError("An evolved skill requires a task-state trigger")
        result.retired.discard(spec.skill_id)
        result.skills[spec.skill_id] = PublishedSkill(
            spec=spec,
            version=candidate.candidate_id[:16],
            candidate_id=candidate.candidate_id,
            evidence_ids=candidate.evidence_ids,
            trace_ids=candidate.trace_ids,
        )
    return result
