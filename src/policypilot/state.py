"""Canonical task-local semantic state for PolicyPilot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

from policypilot.errors import ErrorRecord, PolicyPilotErrorType
from policypilot.evidence import EvidenceRecord
from policypilot.provenance import ContextManifest, RawPayloadRecord
from tau2.data_model.message import APICompatibleMessage, SystemMessage

IntentType = Literal["INFORMATIONAL", "STATUS_CHECK", "ELIGIBILITY_CHECK", "TRANSACTIONAL", "CORRECTION", "OTHER"]
FactSource = Literal["USER", "TOOL", "POLICY"]
FactAuthorityScope = Literal[
    "USER_PROVIDED", "LIVE_SYSTEM", "POLICY_SOURCE", "UNVERIFIED"
]
NeedSource = Literal["USER", "POLICY", "TOOL", "UNKNOWN"]
NeedStatus = Literal[
    "OPEN",
    "PARTIALLY_COVERED",
    "REOPENED",
    "RESOLVED",
    "NOT_APPLICABLE",
    "EXHAUSTED",
]
NeedPurpose = Literal["PLANNING", "PRE_MUTATION", "VERIFICATION"]
AcquisitionStatus = Literal[
    "OPEN", "REQUESTED", "RESOLVED", "NOT_APPLICABLE", "EXHAUSTED"
]
DependencyKind = Literal["NEED", "FACT", "MUTATION"]
DependencyStrength = Literal["HARD", "SOFT"]
DependencyOrigin = Literal["DETERMINISTIC", "LLM"]
MutationStatus = Literal["PLANNED", "SENT", "CONFIRMED", "UNKNOWN", "FAILED"]
CriterionKind = Literal["CONSTRAINT", "PREFERENCE", "OPTIMIZATION"]

class GoalCriterion(BaseModel):
    id: str
    kind: CriterionKind
    aspect: str
    value: str
    condition: str | None = None
    hard: bool = False
    source_turn: int

class StructuredGoal(BaseModel):
    objective: str | None = None
    target: str | None = None
    criteria: list[GoalCriterion] = Field(default_factory=list)
    comparative: bool = False
    status: Literal["ACTIVE", "COMPLETED"] = "ACTIVE"
    source_turn: int = 0
    updated_turn: int = 0

    def criteria_of(self, kind: CriterionKind) -> list[GoalCriterion]:
        return [item for item in self.criteria if item.kind == kind]

class FactRecord(BaseModel):
    id: str
    entity: str
    aspect: str
    value: Any
    source: FactSource
    evidence_ref: str | None = None
    source_identifier: str | None = None
    turn_index: int
    authoritative: bool = False
    authority_scope: FactAuthorityScope | None = None
    freshness: datetime | None = None
    observed_at: datetime | None = None
    observed_version: int = 0
    stale_at: datetime | None = None
    resource_tags: list[str] = Field(default_factory=list)
    raw_path: str | None = None

    @model_validator(mode="after")
    def set_authority_scope(self):
        if self.authority_scope is None:
            self.authority_scope = (
                "UNVERIFIED"
                if not self.authoritative
                else {
                    "USER": "USER_PROVIDED",
                    "TOOL": "LIVE_SYSTEM",
                    "POLICY": "POLICY_SOURCE",
                }[self.source]
            )
        return self

    @property
    def key(self) -> str:
        return self.aspect if self.entity == "user" else f"{self.entity}.{self.aspect}"
    @property
    def source_type(self) -> str:
        return {"USER": "user", "TOOL": "transaction_tool", "POLICY": "knowledge_retrieval"}[self.source]
    @property
    def source_reference(self) -> str:
        return self.evidence_ref or self.source_identifier or self.source
    @property
    def verified(self) -> bool:
        # A user assertion may be usable as task input, but it is not an
        # independently verified live-system fact.
        return self.authoritative and self.source in {"TOOL", "POLICY"}

    @property
    def accepted(self) -> bool:
        """Whether this source is accepted for its own authority scope."""

        return self.authoritative


class FactCandidate(BaseModel):
    entity: str
    aspect: str
    value: Any


class DependencyHint(BaseModel):
    """A bounded semantic suggestion from the light planner.

    Hints never carry runtime IDs, strength, or blocking authority. The
    deterministic dependency validator resolves them against registered Needs.
    """

    entity: str = Field(min_length=1, max_length=80)
    aspect: str = Field(min_length=1, max_length=80)
    source: Literal["USER", "POLICY", "TOOL"] | None = None
    reason_code: str = "semantic_prerequisite"


class NeedDependency(BaseModel):
    kind: DependencyKind
    strength: DependencyStrength = "HARD"
    origin: DependencyOrigin = "DETERMINISTIC"
    reason_code: str
    upstream_semantic_key: str | None = None
    entity: str | None = None
    aspect: str | None = None
    expected_value: Any | None = None
    require_authoritative: bool = True
    require_verified: bool = False
    mutation_tool: str | None = None
    mutation_signature: str | None = None
    required_mutation_statuses: list[MutationStatus] = Field(
        default_factory=lambda: ["SENT", "CONFIRMED", "UNKNOWN"]
    )


class AcquisitionCandidate(BaseModel):
    """One bounded way to acquire evidence for a semantic Need."""

    source: Literal["USER", "POLICY", "TOOL"]
    capability: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    origin: Literal["DETERMINISTIC", "LAYA", "PLANNER_FALLBACK"] = "DETERMINISTIC"


class AcquisitionPlan(AcquisitionCandidate):
    id: str
    status: AcquisitionStatus = "OPEN"
    attempts: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    status_reason: str | None = None


class NeedCandidate(BaseModel):
    entity: str
    aspect: str = Field(min_length=1, max_length=80)
    scope: str | None = None
    # A planner source is only an acquisition hint. The Need identity itself is
    # source-free; AcquisitionPlanner compiles one or more authoritative routes.
    source: Literal["USER", "POLICY", "TOOL"] | None = None
    capability: str | None = None
    criticality: Literal["CRITICAL", "OPTIONAL"] = "OPTIONAL"
    reason_code: str | None = None
    query_terms: list[str] = Field(default_factory=list, max_length=4)
    question: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: NeedPurpose = "PLANNING"
    provenance: str = "deterministic"
    query_id: str | None = None
    query_objective: str | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    dependency_hints: list[DependencyHint] = Field(default_factory=list, max_length=4)
    acquisitions: list[AcquisitionCandidate] = Field(default_factory=list, max_length=4)

class InformationNeed(BaseModel):
    id: str
    entity: str
    aspect: str
    semantic_key: str = ""
    scope: str | None = None
    source: NeedSource = "UNKNOWN"
    status: NeedStatus = "OPEN"
    priority: int = 50
    critical: bool = True
    blocking: bool = True
    actionable: bool = True
    exhausted: bool = False
    reason: str
    query_terms: list[str] = Field(default_factory=list)
    question: str | None = None
    capability: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    resolved_by_fact_id: str | None = None
    resolved_at: datetime | None = None
    retrieval_attempts: int = 0
    acquisition_count: int = 0
    coverage: Literal["MATCH", "PARTIAL", "NO_MATCH"] | None = None
    aspect_provenance: Literal["CANONICAL", "DYNAMIC"] = "CANONICAL"
    provenance: str = "deterministic"
    created_turn: int = 0
    updated_turn: int = 0
    purpose: NeedPurpose = "PLANNING"
    query_id: str | None = None
    query_objective: str | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    status_reason: str | None = None
    dependencies: list[NeedDependency] = Field(default_factory=list)
    acquisitions: list[AcquisitionPlan] = Field(default_factory=list)
    active_acquisition_id: str | None = None

    def activate_next_acquisition(self) -> AcquisitionPlan | None:
        active = next(
            (
                item
                for item in self.acquisitions
                if item.id == self.active_acquisition_id
                and item.status in {"OPEN", "REQUESTED"}
            ),
            None,
        )
        if active is None:
            active = next(
                (
                    item
                    for item in self.acquisitions
                    if item.required and item.status == "OPEN"
                ),
                None,
            )
            self.active_acquisition_id = active.id if active else None
        if active is not None:
            self.source = active.source
            self.capability = active.capability
            self.tool_arguments = dict(active.tool_arguments)
        return active

class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    signature: str
    turn_index: int
    tool_call_id: str | None = None
    classification: str = "unknown"
    duplicate_candidate: bool = False
    blocked: bool = False
    recovery_attempt: bool = False
    result_summary: str | None = None
    error: bool = False
    need_id: str | None = None


class ActionAuthorization(BaseModel):
    """One explicit, bounded user authorization for a state-changing action."""

    authorization_id: str
    source_turn: int
    evidence_ref: str | None = None
    utterance: str
    action_terms: list[str] = Field(default_factory=list)
    authorized_values: list[str] = Field(default_factory=list)
    expires_turn: int
    bound_tool_name: str | None = None
    bound_arguments: dict[str, Any] = Field(default_factory=dict)
    consumed_by_mutation_id: str | None = None
    revoked: bool = False


class MutationTransition(BaseModel):
    status: MutationStatus
    turn: int
    reason: str
    tool_call_id: str | None = None


class MutationRecord(BaseModel):
    mutation_id: str
    operation_fingerprint: str = Field(
        validation_alias=AliasChoices("operation_fingerprint", "idempotency_key")
    )
    tool_name: str
    arguments: dict[str, Any]
    signature: str
    tool_call_id: str
    status: MutationStatus = "PLANNED"
    planned_turn: int
    updated_turn: int
    readback_tool_call_id: str | None = None
    details: str | None = None
    authorization_id: str | None = None
    verification_tool: str | None = None
    verification_arguments: dict[str, Any] = Field(default_factory=dict)
    expected_effect: dict[str, Any] = Field(default_factory=dict)
    status_history: list[MutationTransition] = Field(default_factory=list)

    @property
    def idempotency_key(self) -> str:
        """Compatibility accessor for checkpoints and integrations using the old name."""

        return self.operation_fingerprint

class ControlState(BaseModel):
    step_count: int = 0
    tool_call_count: int = 0
    error_count: int = 0
    consecutive_error_count: int = 0
    duplicate_call_count: int = 0
    retrieval_miss_count: int = 0
    observation_version: int = 0
    last_mutation_version: int = -1
    signature_versions: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    error_records: list[ErrorRecord] = Field(default_factory=list)
    tool_retry_attempts: dict[str, int] = Field(default_factory=dict)
    pending_retrieval_rewrite: bool = False
    retrieval_recovery_exhausted: bool = False
    last_retrieval_query: str | None = None
    mutation_verification_required: bool = False
    unsafe_to_retry: bool = False
    goal_change_count: int = 0
    facts_added_count: int = 0
    facts_updated_count: int = 0
    needs_added_count: int = 0
    needs_resolved_count: int = 0
    context_message_count: int = 0
    context_estimated_size: int = 0
    current_context_id: str | None = None
    llm_retry_count: int = 0
    tool_retry_count: int = 0
    tool_repair_count: int = 0
    retrieval_rewrite_count: int = 0
    goal_retrieval_call_count: int = 0
    recovery_success_count: int = 0
    recovery_failure_count: int = 0
    guard_recovery_attempts: int = 0
    fallback_need_count: int = 0
    need_candidates_created: int = 0
    need_candidates_accepted: int = 0
    need_candidates_rejected: int = 0
    route_trace: list[str] = Field(default_factory=list)
    retrieval_query_history: list[dict[str, Any]] = Field(default_factory=list)
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    prompt_cache_usage_reported: bool = False
    task_fact_reuse_hit: int = 0
    task_fact_reuse_miss: int = 0
    task_fact_reuse_stale: int = 0
    task_fact_forced_refresh: int = 0
    retrieval_cache_hits: int = 0
    retrieval_cache_misses: int = 0
    retrieval_cache_saved_latency_ms: float = 0.0
    embedding_cache_hits: int = 0
    embedding_cache_misses: int = 0
    planner_events: list[dict[str, Any]] = Field(default_factory=list)
    acquisition_planning_events: list[dict[str, Any]] = Field(default_factory=list)
    need_registry_events: list[dict[str, Any]] = Field(default_factory=list)
    pending_retrieval_events: dict[str, dict[str, Any]] = Field(default_factory=dict)
    retrieval_events: list[dict[str, Any]] = Field(default_factory=list)
    context_compressor_events: list[dict[str, Any]] = Field(default_factory=list)
    context_rehydration_events: list[dict[str, Any]] = Field(default_factory=list)
    need_selection_events: list[dict[str, Any]] = Field(default_factory=list)
    dependency_events: list[dict[str, Any]] = Field(default_factory=list)
    acquisition_events: list[dict[str, Any]] = Field(default_factory=list)
    progress_events: list[dict[str, Any]] = Field(default_factory=list)
    no_progress_count: int = 0

class PolicyPilotState(BaseModel):
    run_id: str = "unbound"
    task_id: str | None = None
    version_metadata: dict[str, str] = Field(default_factory=dict)
    system_messages: list[SystemMessage]
    messages: list[APICompatibleMessage] = Field(default_factory=list)
    goal: StructuredGoal = Field(default_factory=StructuredGoal)
    intent: IntentType = "OTHER"
    facts: list[FactRecord] = Field(default_factory=list)
    information_needs: list[InformationNeed] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    raw_payloads: list[RawPayloadRecord] = Field(default_factory=list)
    context_manifests: list[ContextManifest] = Field(default_factory=list)
    tool_history: list[ToolCallRecord] = Field(default_factory=list)
    action_authorizations: list[ActionAuthorization] = Field(default_factory=list)
    mutations: list[MutationRecord] = Field(default_factory=list)
    control: ControlState = Field(default_factory=ControlState)
    identity_matches: list[str] = Field(default_factory=list)
    identity_mismatches: list[str] = Field(default_factory=list)

    def upsert_fact(self, fact: FactRecord, max_facts: int = 80) -> str:
        for index, existing in enumerate(self.facts):
            if (existing.entity, existing.aspect) != (fact.entity, fact.aspect):
                continue
            if existing.value == fact.value and existing.authoritative >= fact.authoritative:
                if fact.source == "TOOL" and fact.observed_at is not None:
                    existing.evidence_ref = fact.evidence_ref
                    existing.turn_index = fact.turn_index
                    existing.observed_at = fact.observed_at
                    existing.observed_version = fact.observed_version
                    existing.stale_at = None
                    existing.resource_tags = fact.resource_tags
                return "unchanged"
            if existing.authoritative and not fact.authoritative:
                return "unchanged"
            self.facts[index] = fact
            self.control.facts_updated_count += 1
            return "updated"
        self.facts.append(fact)
        self.facts = self.facts[-max_facts:]
        self.control.facts_added_count += 1
        return "added"

    def get_fact(self, aspect: str, entity: str | None = None) -> FactRecord | None:
        return next((f for f in reversed(self.facts) if f.aspect == aspect and (entity is None or f.entity == entity)), None)

    def upsert_need(self, need: InformationNeed, max_needs: int | None = None) -> str:
        for index, existing in enumerate(self.information_needs):
            if existing.id == need.id or (
                need.semantic_key
                and existing.semantic_key == need.semantic_key
            ):
                if existing.status in {"RESOLVED", "NOT_APPLICABLE"} and need.status not in {
                    "RESOLVED",
                    "NOT_APPLICABLE",
                }:
                    return "already_satisfied"
                if existing.critical and not need.critical:
                    need.critical = True
                self.information_needs[index] = need
                return "updated"
        if max_needs is not None and len(self.information_needs) >= max_needs:
            return "limit_reached"
        self.information_needs.append(need)
        self.control.needs_added_count += 1
        return "added"

    def open_needs(self, source: NeedSource | None = None) -> list[InformationNeed]:
        active = {"OPEN", "PARTIALLY_COVERED", "REOPENED"}
        result = []
        for need in self.information_needs:
            if need.status not in active:
                continue
            need.activate_next_acquisition()
            if source is None or need.source == source:
                result.append(need)
        return sorted(result, key=lambda n: (-n.critical, -n.priority, n.created_turn))

    def resolved_needs(self) -> list[InformationNeed]:
        return [
            need
            for need in self.information_needs
            if need.status in {"RESOLVED", "NOT_APPLICABLE"}
        ]

    @staticmethod
    def resolve_need(
        need: InformationNeed,
        *,
        evidence_refs: list[str],
        fact_id: str | None = None,
    ) -> bool:
        need.evidence_refs = list(dict.fromkeys([*need.evidence_refs, *evidence_refs]))
        need.resolved_by_fact_id = fact_id
        active = need.activate_next_acquisition()
        if active is not None:
            active.status = "RESOLVED"
            active.evidence_refs = list(
                dict.fromkeys([*active.evidence_refs, *evidence_refs])
            )
            active.status_reason = "authoritative_evidence"
            need.active_acquisition_id = None
            if any(
                item.required and item.status != "RESOLVED"
                for item in need.acquisitions
            ):
                need.status = "OPEN"
                need.status_reason = "awaiting_required_acquisition"
                need.activate_next_acquisition()
                return False
        need.status = "RESOLVED"
        need.resolved_at = datetime.now(timezone.utc)
        need.status_reason = "authoritative_evidence"
        return True

    @staticmethod
    def reopen_need(need: InformationNeed, *, reason: str, turn: int) -> None:
        need.status = "REOPENED"
        need.blocking = need.critical
        need.actionable = True
        need.exhausted = False
        need.coverage = "PARTIAL" if need.evidence_refs else None
        need.resolved_by_fact_id = None
        need.resolved_at = None
        need.status_reason = reason
        need.updated_turn = turn
        for acquisition in need.acquisitions:
            if acquisition.required:
                acquisition.status = "OPEN"
                acquisition.status_reason = reason
        need.active_acquisition_id = None
        need.activate_next_acquisition()

    @staticmethod
    def mark_not_applicable(
        need: InformationNeed, *, reason: str, turn: int
    ) -> None:
        need.status = "NOT_APPLICABLE"
        need.blocking = False
        need.actionable = False
        need.exhausted = False
        need.status_reason = reason
        need.updated_turn = turn
        need.resolved_at = datetime.now(timezone.utc)
        for acquisition in need.acquisitions:
            if acquisition.status in {"OPEN", "REQUESTED"}:
                acquisition.status = "NOT_APPLICABLE"
                acquisition.status_reason = reason

    def add_error(self, error_type: str | PolicyPilotErrorType, message: str, *, source: str = "policypilot", retryable: bool = False, recovery_action: str | None = None, unsafe_to_retry: bool = False, attempts: int = 0) -> ErrorRecord:
        try:
            category = PolicyPilotErrorType(error_type)
        except ValueError:
            category = PolicyPilotErrorType.TOOL_EXECUTION_ERROR
        c = self.control
        c.error_count += 1
        c.consecutive_error_count += 1
        c.errors = [*c.errors, f"{category.value}: {message}"][-20:]
        record = ErrorRecord(category=category, source=source, message=" ".join(message.split())[:500], retryable=retryable, turn_index=len(self.messages), recovery_action=recovery_action, unsafe_to_retry=unsafe_to_retry, attempts=attempts)
        c.error_records = [*c.error_records, record][-20:]
        return record

    def resolve_latest_error(self, category: PolicyPilotErrorType) -> bool:
        for record in reversed(self.control.error_records):
            if record.category == category and not record.resolved:
                record.resolved = True
                self.control.recovery_success_count += 1
                return True
        return False

    def resolve_errors(self, category: PolicyPilotErrorType) -> bool:
        resolved = False
        for record in self.control.error_records:
            if record.category == category and not record.resolved:
                record.resolved = True
                resolved = True
        if resolved:
            self.control.recovery_success_count += 1
        return resolved

    def note_successful_observation(self) -> None:
        self.control.consecutive_error_count = 0
        self.control.observation_version += 1

    def progress_signature(self) -> tuple[Any, ...]:
        """Semantic progress only; repeated utterances and duplicate calls do not count."""
        facts = tuple(sorted(
            (fact.entity, fact.aspect, repr(fact.value), fact.source)
            for fact in self.facts
            if fact.aspect != "utterance"
        ))
        resolved = tuple(sorted(need.semantic_key or need.id for need in self.resolved_needs()))
        evidence = tuple(sorted({
            (item.source_type, item.summary)
            for item in self.evidence
            if item.source_type in {"transaction_tool", "knowledge_retrieval"}
        }))
        goal = (
            self.goal.objective,
            self.goal.target,
            tuple((item.kind, item.aspect, item.value, item.hard) for item in self.goal.criteria),
        )
        return goal, facts, resolved, evidence

    def record_progress(self, before: tuple[Any, ...], *, turn: int) -> bool:
        progressed = self.progress_signature() != before
        self.control.no_progress_count = 0 if progressed else self.control.no_progress_count + 1
        self.control.progress_events.append({
            "turn": turn,
            "progressed": progressed,
            "no_progress_count": self.control.no_progress_count,
        })
        return progressed

    def release_stalled_blockers(self, *, reason: str) -> int:
        released = 0
        for need in self.open_needs():
            if need.blocking:
                need.exhausted = True
                need.status = "EXHAUSTED"
                need.actionable = False
                need.status_reason = reason
                need.updated_turn = len(self.messages)
                released += 1
        if released:
            self.control.progress_events.append({
                "turn": len(self.messages), "recovery": reason, "released": released
            })
        return released
