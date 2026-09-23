from policypilot.coverage import EvidenceResolver
from policypilot.evidence import EvidenceRecord
from policypilot.need_registry import NeedRegistry
from policypilot.planning import deterministic_semantic_plan, merge_semantic_plan
from policypilot.requirements import (
    render_requirement_gap_context,
    requirement_model,
    retrieval_coverage,
    retrieval_gaps,
)
from policypilot.retrieval import build_retrieval_query
from policypilot.state import InformationNeed, NeedCandidate, PolicyPilotState
from policypilot.state_updates import classify_intent
from tau2.data_model.message import SystemMessage


def state() -> PolicyPilotState:
    return PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")]
    )


def test_transaction_question_does_not_authorize_action_or_retarget_goal():
    value = state()
    first = "Compare personal cards for cash back."
    merge_semantic_plan(
        value,
        deterministic_semantic_plan(value, first, 0, classify_intent(first)),
        0,
    )

    follow_up = "I have no account. Should I just go ahead and apply?"
    plan = deterministic_semantic_plan(
        value, follow_up, 1, classify_intent(follow_up)
    )
    merge_semantic_plan(value, plan, 1)

    assert value.intent != "TRANSACTIONAL"
    assert value.goal.target == "card"


def test_hard_constraint_reopens_matching_resolved_policy_need():
    value = state()
    value.goal.objective = "Compare cards"
    value.goal.target = "card"
    need = InformationNeed(
        id="fee",
        semantic_key="POLICY|card|annual_fee|card",
        entity="card",
        aspect="annual_fee",
        scope="card",
        source="POLICY",
        status="RESOLVED",
        reason="comparison",
    )
    value.information_needs.append(need)

    text = "I must have no annual fee."
    merge_semantic_plan(
        value,
        deterministic_semantic_plan(value, text, 2, classify_intent(text)),
        2,
    )

    assert need.status == "REOPENED"
    assert need.blocking
    assert "no annual fee" in " ".join(need.query_terms).lower()


def test_partial_evidence_is_coverage_not_completion():
    value = state()
    NeedRegistry().register_many(
        value,
        [
            NeedCandidate(
                entity="Gold Card",
                aspect="annual_fee",
                scope="personal card",
                source="POLICY",
                criticality="CRITICAL",
                reason_code="explicit_hard_constraint",
            )
        ],
        turn=1,
    )
    need = value.information_needs[0]
    EvidenceResolver().resolve(
        value,
        EvidenceRecord(
            source_type="knowledge_retrieval",
            turn_index=2,
            summary="Gold Card business card has no annual fee.",
            tool_name="KB_search",
            tool_call_id="kb-1",
        ),
        trigger_need_id=need.id,
    )

    assert need.status == "PARTIALLY_COVERED"
    assert retrieval_coverage(value)[0].status == "PARTIAL"
    assert retrieval_gaps(value)[0].need_id == need.id


def test_requirement_gap_view_is_compact_and_derived():
    value = state()
    text = "Compare cards. I must have no annual fee and want the highest cash back."
    merge_semantic_plan(
        value,
        deterministic_semantic_plan(value, text, 0, classify_intent(text)),
        0,
    )
    NeedRegistry().register_many(
        value,
        [
            NeedCandidate(
                entity="Gold Card",
                aspect="annual_fee",
                scope="personal card",
                source="POLICY",
                criticality="CRITICAL",
                reason_code="explicit_hard_constraint",
            )
        ],
        turn=1,
    )

    model = requirement_model(value)
    rendered = render_requirement_gap_context(value)

    assert model.hard_constraints
    assert model.optimization_criteria
    assert "Gold_Card.annual_fee" in rendered or "gold_card.annual_fee" in rendered
    assert len(rendered) < 1200


def test_query_scoped_identity_is_not_rendered_into_query():
    value = state()
    need = InformationNeed(
        id="need:abc123def456",
        semantic_key="POLICY|card|rewards|card|query:abc123def456",
        entity="card",
        aspect="rewards",
        scope="card",
        source="POLICY",
        reason="decision correction",
        query_id="abc123def456",
        query_objective="compare cashback rates",
        query_terms=["query:abc123def456", "need:abc123def456"],
    )

    query = build_retrieval_query(value, need)

    assert "abc123def456" not in query
    assert "compare cashback rates" in query


def test_exhausted_policy_need_remains_visible_as_unresolved_gap():
    value = state()
    value.information_needs.append(
        InformationNeed(
            id="fee",
            entity="Gold Card",
            aspect="annual_fee",
            source="POLICY",
            status="EXHAUSTED",
            reason="retrieval budget exhausted",
            exhausted=True,
            blocking=False,
            actionable=False,
        )
    )

    gaps = retrieval_gaps(value)

    assert gaps[0].status == "EXHAUSTED"
    assert "EXHAUSTED" in render_requirement_gap_context(value)
