import json

from policypilot.coverage import EvidenceResolver
from policypilot.coverage_manager import (
    CoverageAssessment,
    CoverageAssignment,
    LightweightCoverageManager,
)
from policypilot.evidence import EvidenceRecord, PolicyReference
from policypilot.state import GoalCriterion, InformationNeed, PolicyPilotState
from tau2.data_model.message import SystemMessage, UserMessage


class StaticCoverageRuntime:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or CoverageAssessment()
        self.error = error
        self.calls = []

    def call_structured(self, node, messages, schema, **kwargs):
        self.calls.append((node, messages, schema, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def make_state(*needs: InformationNeed) -> PolicyPilotState:
    return PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")],
        information_needs=list(needs),
    )


def need(
    need_id: str,
    aspect: str,
    *,
    entity: str = "card",
    scope: str | None = "personal card",
    query_id: str | None = None,
) -> InformationNeed:
    return InformationNeed(
        id=need_id,
        entity=entity,
        aspect=aspect,
        scope=scope,
        source="POLICY",
        reason="test requirement",
        query_id=query_id,
    )


def evidence(summary: str, *, title: str = "Card policy") -> EvidenceRecord:
    return EvidenceRecord(
        source_type="knowledge_retrieval",
        turn_index=2,
        summary=summary,
        tool_name="KB_search",
        tool_call_id="kb-1",
        policy_refs=[PolicyReference(document_id="doc-1", title=title)],
    )


def test_manager_batches_needs_and_uses_compact_context_only():
    fee = need("fee", "annual_fee")
    rewards = need("rewards", "rewards")
    runtime = StaticCoverageRuntime(
        CoverageAssessment(
            assignments=[
                CoverageAssignment(need_id="fee", coverage="MATCH"),
                CoverageAssignment(need_id="rewards", coverage="MATCH"),
            ]
        )
    )
    state = make_state(fee, rewards)
    state.messages.append(UserMessage.text("SECRET_HISTORY_" + "Z" * 4000))
    resolver = EvidenceResolver(
        LightweightCoverageManager(
            runtime,
            max_context_chars=900,
            max_evidence_chars=5000,
        )
    )

    result = resolver.resolve(
        state,
        evidence(
            "The personal card has no annual fee and provides cashback rewards. "
            + "X" * 5000
        ),
        trigger_need_id="fee",
    )

    assert len(runtime.calls) == 1
    node, messages, _, kwargs = runtime.calls[0]
    payload = messages[1].content
    assert node == "coverage_manager"
    assert len(payload) <= 900
    assert "SECRET_HISTORY" not in payload
    assert json.loads(payload)["needs"][0]["id"] == "fee"
    assert kwargs["trace_metadata"]["candidate_needs"] == 2
    assert result["matched_evidence_count"] == 2
    assert fee.status == rewards.status == "RESOLVED"


def test_manager_can_match_semantic_paraphrase_without_keyword_pattern():
    timeline = need(
        "timeline",
        "payout_timeline",
        entity="referral",
        scope="referral",
    )
    runtime = StaticCoverageRuntime(
        CoverageAssessment(
            assignments=[
                CoverageAssignment(need_id="timeline", coverage="MATCH")
            ]
        )
    )
    state = make_state(timeline)

    EvidenceResolver(LightweightCoverageManager(runtime)).resolve(
        state,
        evidence(
            "A qualifying referral bonus is credited on the second statement.",
            title="Referral terms",
        ),
        trigger_need_id="timeline",
    )

    assert timeline.status == "RESOLVED"


def test_deterministic_identity_veto_downgrades_wrong_entity_match():
    gold = need("gold-fee", "annual_fee", entity="Gold Card")
    runtime = StaticCoverageRuntime(
        CoverageAssessment(
            assignments=[
                CoverageAssignment(need_id="gold-fee", coverage="MATCH")
            ]
        )
    )
    state = make_state(gold)

    result = EvidenceResolver(LightweightCoverageManager(runtime)).resolve(
        state,
        evidence(
            "Silver Card personal card has no annual fee.",
            title="Silver Card pricing",
        ),
        trigger_need_id="gold-fee",
    )

    assert result["coverage"] == "PARTIAL"
    assert gold.status == "PARTIALLY_COVERED"


def test_hard_constraint_veto_prevents_false_full_coverage():
    fee = need("fee", "annual_fee")
    runtime = StaticCoverageRuntime(
        CoverageAssessment(
            assignments=[CoverageAssignment(need_id="fee", coverage="MATCH")]
        )
    )
    state = make_state(fee)
    state.goal.criteria.append(
        GoalCriterion(
            id="no-fee",
            kind="CONSTRAINT",
            aspect="annual_fee",
            value="must have no annual fee",
            hard=True,
            source_turn=0,
        )
    )

    EvidenceResolver(LightweightCoverageManager(runtime)).resolve(
        state,
        evidence("The personal card has an annual fee of $200."),
        trigger_need_id="fee",
    )

    assert fee.status == "PARTIALLY_COVERED"
    assert fee.coverage == "PARTIAL"


def test_manager_failure_keeps_trigger_need_open_and_not_exhausted():
    scoped = need(
        "query-need",
        "foreign_exchange_markup",
        query_id="query-1",
    )
    runtime = StaticCoverageRuntime(error=TimeoutError("light model unavailable"))
    state = make_state(scoped)

    result = EvidenceResolver(LightweightCoverageManager(runtime)).resolve(
        state,
        evidence("Unrelated policy text."),
        trigger_need_id="query-need",
    )

    assert result["coverage"] == "PARTIAL"
    assert scoped.status == "PARTIALLY_COVERED"
    assert not scoped.exhausted
    assert state.control.route_trace[-1] == "coverage_manager:fallback:TimeoutError"


def test_manager_ignores_invented_need_ids():
    fee = need("fee", "annual_fee", query_id="query-1")
    runtime = StaticCoverageRuntime(
        CoverageAssessment(
            assignments=[
                CoverageAssignment(need_id="invented", coverage="MATCH")
            ]
        )
    )
    state = make_state(fee)

    result = EvidenceResolver(LightweightCoverageManager(runtime)).resolve(
        state,
        evidence("The personal card has no annual fee."),
        trigger_need_id="fee",
    )

    assert result["coverage"] == "NO_MATCH"
    assert fee.status == "EXHAUSTED"
    assert fee.evidence_refs == []
