"""Event-driven Skill runtime with phase and reference progressive disclosure."""

from __future__ import annotations

from policypilot.skills.loader import SkillLoader
from policypilot.skills.matcher import SkillMatcher
from policypilot.skills.models import (
    SkillGuidanceContext,
    SkillPhase,
    SkillReference,
    SkillTraceEvent,
)
from policypilot.skills.retrieval import eligible, rank_skills
from policypilot.state import PolicyPilotState


class SkillRuntime:
    def __init__(
        self,
        loader: SkillLoader | None = None,
        matcher: SkillMatcher | None = None,
        *,
        max_references_per_skill: int = 2,
        max_trace_events: int = 80,
        embedder=None,
    ):
        self.loader = loader or SkillLoader()
        self.matcher = matcher or SkillMatcher()
        self.max_references_per_skill = max_references_per_skill
        self.max_trace_events = max_trace_events
        self.selected: list[str] = []
        self.embedder = embedder
        self._last_route_key = None
        self.activated_versions: dict[str, str] = {}
        self.retrieved_versions: dict[str, str] = {}
        self.last_recovery_mode: str | None = None
        self.trace_events: list[SkillTraceEvent] = []

    def refresh(
        self,
        state: PolicyPilotState,
        *,
        event: str,
        recovery_mode: str | None = None,
    ) -> None:
        release = self.loader.release
        specs = {name: item.spec for name, item in release.skills.items()}
        allowed = {
            name for name, spec in specs.items() if eligible(spec, state, recovery_mode)
        }
        route_key = (
            state.goal.objective,
            state.goal.target,
            state.goal.comparative,
            tuple((c.aspect, c.value, c.hard) for c in state.goal.criteria),
            state.intent,
            tuple(sorted(allowed)),
            recovery_mode,
            tuple(sorted((n.source, n.aspect, n.critical) for n in state.open_needs())),
            tuple(
                sorted(
                    e.category for e in state.control.error_records if not e.resolved
                )
            ),
            state.control.retrieval_miss_count,
            bool(state.identity_mismatches),
        )
        if (
            self.loader.release.skills
            and route_key == self._last_route_key
            and event != "PLANNER_REQUEST"
        ):
            return
        self._last_route_key = route_key
        previous = tuple(self.selected)
        metadata = {item.name: item for item in self.loader.metadata()}
        selected = self.matcher.match(
            state,
            [item for name, item in metadata.items() if name not in specs],
            event=event,
            recovery_mode=recovery_mode,
        )
        for name in selected:
            self.retrieved_versions[name] = metadata[name].version
        if allowed and self.matcher.max_active_skills > 0:
            query = " ".join(
                filter(
                    None,
                    (
                        state.goal.objective,
                        state.goal.target,
                        state.intent,
                        recovery_mode,
                    ),
                )
            )
            ranked = rank_skills(
                query,
                [metadata[name] for name in sorted(allowed)],
                self.matcher.max_active_skills,
                self.embedder,
            )
            for item in ranked:
                self.retrieved_versions[item.name] = item.version
                self._trace(
                    SkillTraceEvent(
                        "skill_retrieved", item.name, item.version, reason=event
                    )
                )
            selected = ([item.name for item in ranked] + selected)[
                : self.matcher.max_active_skills
            ]
        self.selected = selected
        state.control.active_skill_versions = {
            name: metadata[name].version
            for name in selected
            if self.activated_versions.get(name) == metadata[name].version
        }
        self.last_recovery_mode = recovery_mode
        for skill_id in selected:
            item = metadata[skill_id]
            self._trace(
                SkillTraceEvent("skill_matched", skill_id, item.version, reason=event)
            )
        if previous != tuple(selected):
            for skill_id in sorted(set(previous).union(selected)):
                item = metadata.get(skill_id)
                self._trace(
                    SkillTraceEvent(
                        "skill_changed",
                        skill_id,
                        item.version if item else "unknown",
                        reason=f"{','.join(previous) or 'none'}->{','.join(selected) or 'none'}",
                    )
                )

    def get_guidance(
        self,
        phase: SkillPhase,
        state: PolicyPilotState,
        *,
        error_category: str | None = None,
        subgoal: str | None = None,
        max_chars: int = 1600,
    ) -> tuple[SkillGuidanceContext, ...]:
        tags = self._context_tags(state, phase, error_category, subgoal)
        contexts: list[SkillGuidanceContext] = []
        used_chars = 0
        for skill_id in self.selected:
            spec = self.loader.release.skills.get(skill_id)
            if spec and not eligible(spec.spec, state, self.last_recovery_mode):
                state.control.active_skill_versions.pop(skill_id, None)
                continue
            artifact = self.loader.load(skill_id)
            if artifact is None or phase not in artifact.metadata.phases:
                continue
            core = artifact.guidance(phase)
            if not core:
                continue
            references = self._select_references(
                artifact.available_references, phase, tags
            )
            loaded = []
            for reference in references:
                item = self.loader.load_reference(skill_id, reference)
                if item is None:
                    self._trace(
                        SkillTraceEvent(
                            "reference_skipped",
                            skill_id,
                            artifact.metadata.version,
                            phase,
                            (reference.id,),
                            "missing_or_unsafe",
                        )
                    )
                    continue
                candidate = SkillGuidanceContext(
                    skill_id,
                    artifact.metadata.version,
                    phase,
                    core,
                    tuple([*loaded, item]),
                )
                if used_chars + len(candidate.render()) > max_chars:
                    self._trace(
                        SkillTraceEvent(
                            "reference_skipped",
                            skill_id,
                            artifact.metadata.version,
                            phase,
                            (reference.id,),
                            "context_budget",
                        )
                    )
                    continue
                loaded.append(item)
                self._trace(
                    SkillTraceEvent(
                        "reference_loaded",
                        skill_id,
                        artifact.metadata.version,
                        phase,
                        (reference.id,),
                    )
                )
            context = SkillGuidanceContext(
                skill_id, artifact.metadata.version, phase, core, tuple(loaded)
            )
            rendered_size = len(context.render())
            if used_chars + rendered_size > max_chars:
                self._trace(
                    SkillTraceEvent(
                        "phase_guidance_skipped",
                        skill_id,
                        artifact.metadata.version,
                        phase,
                        reason="context_budget",
                    )
                )
                continue
            contexts.append(context)
            state.control.active_skill_versions[skill_id] = artifact.metadata.version
            self.activated_versions[skill_id] = artifact.metadata.version
            used_chars += rendered_size
            self._trace(
                SkillTraceEvent(
                    "phase_guidance_used",
                    skill_id,
                    artifact.metadata.version,
                    phase,
                    context.loaded_reference_ids,
                )
            )
        return tuple(contexts)

    def guidance(
        self,
        phase: SkillPhase,
        state: PolicyPilotState,
        *,
        error_category: str | None = None,
        subgoal: str | None = None,
        max_chars: int = 1600,
    ) -> str:
        return "\n\n".join(
            context.render()
            for context in self.get_guidance(
                phase,
                state,
                error_category=error_category,
                subgoal=subgoal,
                max_chars=max_chars,
            )
        )

    def snapshot(self) -> dict[str, object]:
        metadata = {item.name: item for item in self.loader.metadata()}
        return {
            "release_id": self.loader.release.id,
            "evaluation_candidate": self.loader.evaluation_candidate,
            "activated_versions": self.activated_versions.copy(),
            "retrieved_versions": self.retrieved_versions.copy(),
            "selected_skills": [
                {"skill_id": skill_id, "version": metadata[skill_id].version}
                for skill_id in self.selected
                if skill_id in metadata
            ],
            "recovery_mode": self.last_recovery_mode,
            "events": [item.to_dict() for item in self.trace_events],
        }

    def _select_references(
        self,
        references: tuple[SkillReference, ...],
        phase: SkillPhase,
        tags: set[str],
    ) -> list[SkillReference]:
        selected = [
            reference
            for reference in references
            if phase in reference.applicable_phases
            and (
                not reference.trigger_tags or tags.intersection(reference.trigger_tags)
            )
        ]
        return selected[: self.max_references_per_skill]

    def _context_tags(
        self,
        state: PolicyPilotState,
        phase: SkillPhase,
        error_category: str | None,
        subgoal: str | None,
    ) -> set[str]:
        tags = {phase}
        if state.goal.comparative:
            tags.update({"comparison", "candidate"})
        if state.goal.criteria:
            tags.add("constraints")
        for criterion in state.goal.criteria:
            tags.add(criterion.kind.lower())
        if state.intent == "TRANSACTIONAL":
            tags.update({"transaction", "prerequisite"})
        for need in state.open_needs():
            tags.update(
                {
                    "information-needs",
                    f"{need.source.lower()}-need",
                    need.purpose.lower().replace("_", "-"),
                }
            )
            if need.source in {"UNKNOWN", "USER"}:
                tags.add("ambiguity")
        if (
            state.control.pending_retrieval_rewrite
            or state.control.retrieval_miss_count
        ):
            tags.update({"retrieval", "retrieval-refinement", "retrieval-empty"})
        if len(state.control.retrieval_query_history) > 1:
            tags.add("retrieval-repeat")
        if state.identity_mismatches:
            tags.update({"conflict", "identity-conflict"})
        if any(fact.stale_at is not None for fact in state.facts):
            tags.update({"conflict", "stale-fact", "freshness"})
        category = error_category or self.last_recovery_mode
        if category:
            tags.update({"failure", category.lower().replace("_", "-")})
        if state.control.mutation_verification_required:
            tags.update({"mutation-uncertain", "verification", "conflict"})
        if subgoal:
            tags.update(
                part.lower() for part in subgoal.replace("_", "-").split() if part
            )
        return tags

    def _trace(self, event: SkillTraceEvent) -> None:
        self.trace_events = [*self.trace_events, event][-self.max_trace_events :]
