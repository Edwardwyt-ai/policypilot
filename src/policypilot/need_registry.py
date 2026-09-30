"""Single normalized entry point for every PolicyPilot information need."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from policypilot.coverage import EvidenceResolver
from policypilot.dependencies import DependencyManager
from policypilot.state import (
    AcquisitionCandidate,
    AcquisitionPlan,
    InformationNeed,
    NeedCandidate,
    PolicyPilotState,
)
from policypilot.taxonomy import canonical_entity, canonicalize_aspect, normalize_text


@dataclass(frozen=True)
class NeedRegistrationStats:
    candidate_count: int = 0
    accepted_count: int = 0
    deduplicated_count: int = 0
    already_satisfied_count: int = 0
    evidence_covered_count: int = 0
    rejected_count: int = 0
    new_open_count: int = 0
    new_resolved_count: int = 0
    dynamic_aspect_count: int = 0


class NeedManager:
    def __init__(
        self,
        *,
        capabilities: set[str] | None = None,
        evidence_resolver: EvidenceResolver | None = None,
        dependency_manager: DependencyManager | None = None,
        max_needs: int = 40,
    ):
        self.capabilities = capabilities or set()
        self.evidence_resolver = evidence_resolver or EvidenceResolver()
        self.dependency_manager = dependency_manager or DependencyManager()
        self.max_needs = max_needs

    @staticmethod
    def _requirement_fingerprint(state: PolicyPilotState, aspect: str) -> str:
        values = sorted(
            normalize_text(item.value)
            for item in state.goal.criteria
            if item.hard and item.aspect == aspect
        )
        if not values:
            return ""
        return hashlib.sha1("|".join(values).encode("utf-8")).hexdigest()[:10]

    @staticmethod
    def _normalized_candidate(
        state: PolicyPilotState, candidate: NeedCandidate
    ) -> tuple[str, str, str | None, str]:
        canonical = canonicalize_aspect(
            candidate.aspect, entity=candidate.entity, scope=candidate.scope
        )
        aspect = canonical or normalize_text(candidate.aspect)
        provenance = "CANONICAL" if canonical else "DYNAMIC"
        entity = canonical_entity(candidate.entity, aspect)
        if (
            entity in {"unknown", "banking_product"}
            or candidate.source == "POLICY" and entity == "user" and not candidate.scope
        ) and state.goal.target:
            entity = canonical_entity(state.goal.target, aspect)
        scope = normalize_text(candidate.scope)
        if aspect == "current_referral_records":
            scope = "current_user"
        elif aspect == "customer_identifier":
            scope = ""
        if not scope and candidate.source in {"POLICY", "TOOL"}:
            scope = entity
        return entity, aspect, scope or None, provenance

    @classmethod
    def semantic_key(cls, candidate: NeedCandidate, state: PolicyPilotState | None = None) -> str:
        value = state or PolicyPilotState(system_messages=[])
        entity, aspect, scope, _ = cls._normalized_candidate(value, candidate)
        base = f"{entity}|{aspect}|{scope or '*'}"
        requirement = cls._requirement_fingerprint(value, aspect)
        if requirement:
            base = f"{base}|requirement:{requirement}"
        return f"{base}|query:{candidate.query_id}" if candidate.query_id else base

    @staticmethod
    def _blocking(
        state: PolicyPilotState,
        candidate: NeedCandidate,
        *,
        entity: str,
        aspect: str,
        scope: str | None,
        provenance: str,
    ) -> bool:
        if candidate.criticality != "CRITICAL":
            return False
        if provenance == "DYNAMIC" and aspect in {
            "policy", "requirement", "requirements", "terms", "information"
        }:
            return False
        if candidate.reason_code in {
            "explicit_hard_constraint",
            "explicit_policy_question",
            "goal_scope_changed",
            "required_action_blocked",
            "authoritative_precondition",
        }:
            return True
        target = normalize_text(state.goal.target)
        target_entity = canonical_entity(target, aspect) if target else ""
        hard_aspects = {
            canonicalize_aspect(item.aspect, entity=entity, scope=scope)
            or normalize_text(item.aspect)
            for item in state.goal.criteria
            if item.hard
        }
        goal_relevant = bool(
            target
            and (
                entity == target_entity
                or normalize_text(scope) in {target, target_entity}
                or aspect in hard_aspects
            )
        )
        return goal_relevant and bool(
            candidate.acquisitions
            or candidate.source in {"USER", "POLICY", "TOOL"}
        )

    @staticmethod
    def _candidate_acquisitions(candidate: NeedCandidate) -> list[AcquisitionCandidate]:
        if candidate.acquisitions:
            return candidate.acquisitions
        if candidate.source is None:
            return []
        return [
            AcquisitionCandidate(
                source=candidate.source,
                capability=candidate.capability,
                tool_arguments=candidate.tool_arguments,
                origin=(
                    "DETERMINISTIC"
                    if candidate.provenance != "semantic_planner"
                    else "PLANNER_FALLBACK"
                ),
            )
        ]

    @staticmethod
    def _acquisition_identity(item: AcquisitionCandidate | AcquisitionPlan) -> tuple:
        arguments = json.dumps(
            item.tool_arguments,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return item.source, item.capability, arguments

    @classmethod
    def _merge_acquisitions(
        cls,
        need: InformationNeed,
        candidates: list[AcquisitionCandidate],
        *,
        semantic_key: str,
    ) -> int:
        existing = {cls._acquisition_identity(item) for item in need.acquisitions}
        added = 0
        for candidate in candidates:
            identity = cls._acquisition_identity(candidate)
            if identity in existing:
                continue
            digest = hashlib.sha1(
                f"{semantic_key}|{identity!r}".encode("utf-8")
            ).hexdigest()[:12]
            need.acquisitions.append(
                AcquisitionPlan(id=f"acq:{digest}", **candidate.model_dump())
            )
            existing.add(identity)
            added += 1
        need.activate_next_acquisition()
        return added

    def register_many(
        self,
        state: PolicyPilotState,
        candidates: list[NeedCandidate],
        *,
        turn: int,
        max_needs: int | None = None,
    ) -> NeedRegistrationStats:
        state.control.need_candidates_created += len(candidates)
        accepted = deduplicated = satisfied = covered = rejected = 0
        new_open = new_resolved = dynamic = 0
        dependency_pairs: list[tuple[InformationNeed, NeedCandidate]] = []
        for candidate in candidates:
            acquisitions = self._candidate_acquisitions(candidate)
            if not acquisitions:
                rejected += 1
                continue
            if candidate.source is None:
                candidate.source = acquisitions[0].source
                candidate.capability = acquisitions[0].capability
                candidate.tool_arguments = dict(acquisitions[0].tool_arguments)
            entity, aspect, normalized_scope, aspect_provenance = self._normalized_candidate(
                state, candidate
            )
            if not aspect:
                rejected += 1
                continue
            key = f"{entity}|{aspect}|{normalized_scope or '*'}"
            requirement = self._requirement_fingerprint(state, aspect)
            if requirement:
                key = f"{key}|requirement:{requirement}"
            if candidate.query_id:
                key = f"{key}|query:{candidate.query_id}"
            blocking = self._blocking(
                state,
                candidate,
                entity=entity,
                aspect=aspect,
                scope=normalized_scope,
                provenance=aspect_provenance,
            )
            dynamic += aspect_provenance == "DYNAMIC"
            invalid_tool_acquisition = any(
                item.source == "TOOL"
                and (
                    not item.capability
                    or self.capabilities
                    and item.capability not in self.capabilities
                )
                for item in acquisitions
            )
            if invalid_tool_acquisition:
                rejected += 1
                continue
            if aspect == "product_terms" and entity in {
                "account",
                "banking_product",
                "referral",
            } and not candidate.scope:
                rejected += 1
                continue
            existing = next(
                (item for item in state.information_needs if item.semantic_key == key),
                None,
            )
            if existing is not None:
                dependency_pairs.append((existing, candidate))
                acquisition_added = self._merge_acquisitions(
                    existing, acquisitions, semantic_key=key
                )
                if existing.status in {"RESOLVED", "NOT_APPLICABLE"}:
                    if acquisition_added:
                        existing.status = "OPEN"
                        existing.blocking = existing.critical
                        existing.actionable = True
                        existing.resolved_at = None
                        existing.status_reason = "new_required_acquisition"
                        existing.activate_next_acquisition()
                        deduplicated += 1
                    else:
                        satisfied += 1
                else:
                    deduplicated += 1
                    if candidate.capability:
                        existing.capability = candidate.capability
                    if candidate.tool_arguments:
                        existing.tool_arguments.update(candidate.tool_arguments)
                        existing.priority = max(existing.priority, 95)
                    if (
                        blocking
                        and not existing.blocking
                        and candidate.reason_code
                        in {
                            "goal_scope_changed",
                            "required_action_blocked",
                            "authoritative_precondition",
                        }
                    ):
                        existing.critical = True
                        existing.blocking = True
                continue

            effective_limit = max_needs if max_needs is not None else self.max_needs
            if len(state.information_needs) >= effective_limit:
                rejected += 1
                continue

            covered_by = []
            partial_refs = []
            has_policy_acquisition = any(
                item.source == "POLICY" for item in acquisitions
            )
            evidence_items = reversed(state.evidence) if has_policy_acquisition else []
            for evidence in evidence_items:
                probe = InformationNeed(
                    id="candidate",
                    semantic_key=key,
                    entity=entity,
                    aspect=aspect,
                    scope=normalized_scope or None,
                    source="POLICY",
                    reason=candidate.reason_code or "semantic_delta",
                    critical=blocking,
                    blocking=blocking,
                )
                coverage = self.evidence_resolver.coverage(probe, evidence, state=state)
                if coverage == "MATCH" and evidence.tool_call_id:
                    covered_by.append(evidence.tool_call_id)
                elif coverage == "PARTIAL" and evidence.tool_call_id:
                    partial_refs.append(evidence.tool_call_id)
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
            need_id = (
                "user:user_id"
                if candidate.source == "USER"
                and aspect == "customer_identifier"
                else f"need:{digest}"
            )
            need = InformationNeed(
                id=need_id,
                semantic_key=key,
                entity=entity,
                aspect=aspect,
                scope=normalized_scope or None,
                source=candidate.source,
                reason=candidate.reason_code or "semantic_delta",
                critical=blocking,
                blocking=blocking,
                actionable=candidate.source in {"USER", "POLICY", "TOOL"},
                priority=(
                    100
                    if candidate.source == "USER" and candidate.criticality == "CRITICAL"
                    else 95
                    if candidate.source == "TOOL" and candidate.tool_arguments
                    else 90
                    if candidate.criticality == "CRITICAL"
                    else 50
                ),
                query_terms=candidate.query_terms,
                question=candidate.question,
                capability=candidate.capability,
                tool_arguments=candidate.tool_arguments,
                evidence_refs=list(dict.fromkeys([*covered_by, *partial_refs])),
                created_turn=turn,
                updated_turn=turn,
                purpose=candidate.purpose,
                aspect_provenance=aspect_provenance,
                provenance=candidate.provenance,
                query_id=candidate.query_id,
                query_objective=candidate.query_objective,
                max_attempts=candidate.max_attempts,
            )
            self._merge_acquisitions(need, acquisitions, semantic_key=key)
            if covered_by:
                policy_acquisition = next(
                    (
                        item
                        for item in need.acquisitions
                        if item.source == "POLICY" and item.status == "OPEN"
                    ),
                    None,
                )
                if policy_acquisition is not None:
                    need.active_acquisition_id = policy_acquisition.id
                    need.source = "POLICY"
                fully_resolved = state.resolve_need(need, evidence_refs=covered_by)
                if fully_resolved:
                    state.control.needs_resolved_count += 1
                covered += 1
                new_resolved += int(fully_resolved)
                new_open += int(not fully_resolved)
            else:
                new_open += 1
            state.upsert_need(need, max_needs=effective_limit)
            dependency_pairs.append((need, candidate))
            accepted += 1

        self.dependency_manager.attach_for_candidates(
            state, dependency_pairs, turn=turn
        )

        stats = NeedRegistrationStats(
            candidate_count=len(candidates),
            accepted_count=accepted,
            deduplicated_count=deduplicated,
            already_satisfied_count=satisfied,
            evidence_covered_count=covered,
            rejected_count=rejected,
            new_open_count=new_open,
            new_resolved_count=new_resolved,
            dynamic_aspect_count=dynamic,
        )
        state.control.need_registry_events.append(
            {"turn": turn, **stats.__dict__}
        )
        state.control.need_candidates_accepted += accepted
        state.control.need_candidates_rejected += rejected
        return stats


# Backward-compatible import name. NeedManager is the single lifecycle owner.
NeedRegistry = NeedManager
