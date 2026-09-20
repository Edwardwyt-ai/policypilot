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
from policypilot.state import PolicyPilotState


class SkillRuntime:
    def __init__(
        self,
        loader: SkillLoader | None = None,
        matcher: SkillMatcher | None = None,
        *,
        max_references_per_skill: int = 2,
        max_trace_events: int = 80,
    ):
        self.loader = loader or SkillLoader()
        self.matcher = matcher or SkillMatcher()
        self.max_references_per_skill = max_references_per_skill
        self.max_trace_events = max_trace_events
        self.selected: list[str] = []
        self.last_recovery_mode: str | None = None
        self.trace_events: list[SkillTraceEvent] = []

    def refresh(
        self,
        state: PolicyPilotState,
        *,
        event: str,
        recovery_mode: str | None = None,
    ) -> None:
        previous = tuple(self.selected)
        selected = self.matcher.match(
            state,
            self.loader.metadata(),
            event=event,
            recovery_mode=recovery_mode,
        )
        self.selected = selected
        self.last_recovery_mode = recovery_mode
        metadata = {item.name: item for item in self.loader.metadata()}
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
