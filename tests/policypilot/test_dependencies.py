from datetime import datetime, timezone

from policypilot.dependencies import (
    DependencyManager,
    dependency_blockers,
    is_need_runnable,
    refresh_dependency_state,
)
from policypilot.need_registry import NeedManager
from policypilot.needs import decision_ready, select_next_blocking_need
from policypilot.state import (
    DependencyHint,
    FactRecord,
    GoalCriterion,
    InformationNeed,
    MutationRecord,
    NeedCandidate,
    NeedDependency,
    PolicyPilotState,
)
from tau2.data_model.message import SystemMessage


def state() -> PolicyPilotState:
    return PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")]
    )


def policy_candidate(aspect: str, **kwargs) -> NeedCandidate:
    values = {
        "entity": "card",
        "aspect": aspect,
        "scope": "card",
        "source": "POLICY",
        "criticality": "CRITICAL",
        "reason_code": "required_action_blocked",
    }
    values.update(kwargs)
    return NeedCandidate(**values)


def test_hard_constraint_dependency_orders_candidate_search():
    value = state()
    value.goal.criteria.append(
        GoalCriterion(
            id="annual-fee",
            kind="CONSTRAINT",
            aspect="annual_fee",
            value="0",
            hard=True,
            source_turn=0,
        )
    )
    # Register the downstream in an earlier turn. Reconciliation must work across
    # planner/guard batches rather than relying on candidate order.
    manager = NeedManager()
    manager.register_many(value, [policy_candidate("candidate_options")], turn=1)
    manager.register_many(value, [policy_candidate("annual_fee")], turn=2)

    options = next(item for item in value.information_needs if item.aspect == "candidate_options")
    fee = next(item for item in value.information_needs if item.aspect == "annual_fee")
    dependency = next(item for item in options.dependencies if item.kind == "NEED")

    assert dependency.strength == "HARD"
    assert dependency.origin == "DETERMINISTIC"
    assert dependency.upstream_semantic_key == fee.semantic_key
    assert select_next_blocking_need(value) is fee

    value.resolve_need(fee, evidence_refs=["kb:fee"])
    assert select_next_blocking_need(value) is options


def test_stale_fact_reopens_resolved_dependent_need():
    value = state()
    fact = FactRecord(
        id="account-id",
        entity="user",
        aspect="account_id",
        value="acct-1",
        source="TOOL",
        turn_index=0,
        authoritative=True,
        observed_at=datetime.now(timezone.utc),
    )
    value.facts.append(fact)
    manager = NeedManager(capabilities={"read_account"})
    manager.register_many(
        value,
        [
            NeedCandidate(
                entity="account",
                aspect="current_account_state",
                source="TOOL",
                capability="read_account",
                tool_arguments={"account_id": "acct-1"},
                criticality="CRITICAL",
                reason_code="required_action_blocked",
            )
        ],
        turn=1,
    )
    need = value.information_needs[0]
    assert any(item.kind == "FACT" for item in need.dependencies)
    assert is_need_runnable(need, value)

    value.resolve_need(need, evidence_refs=["tool:read"])
    fact.stale_at = datetime.now(timezone.utc)
    refresh_dependency_state(value, turn=2)

    assert need.status == "REOPENED"
    assert dependency_blockers(need, value, strength="HARD")
    assert not decision_ready(value)


def test_llm_dependency_hint_is_soft_and_cannot_block_execution():
    value = state()
    NeedManager().register_many(
        value,
        [
            policy_candidate("annual_fee"),
            policy_candidate(
                "rewards",
                dependency_hints=[
                    DependencyHint(
                        entity="card",
                        aspect="annual_fee",
                        source="POLICY",
                    )
                ],
            ),
        ],
        turn=1,
    )
    rewards = next(item for item in value.information_needs if item.aspect == "rewards")

    dependency = rewards.dependencies[0]
    assert dependency.origin == "LLM"
    assert dependency.strength == "SOFT"
    assert is_need_runnable(rewards, value)


def test_dependency_cycle_is_rejected():
    value = state()
    first = InformationNeed(
        id="first",
        semantic_key="first",
        entity="card",
        aspect="annual_fee",
        source="POLICY",
        reason="fee",
    )
    second = InformationNeed(
        id="second",
        semantic_key="second",
        entity="card",
        aspect="rewards",
        source="POLICY",
        reason="rewards",
    )
    value.information_needs.extend([first, second])
    manager = DependencyManager()

    assert manager.add(
        value,
        first,
        NeedDependency(
            kind="NEED",
            strength="SOFT",
            origin="LLM",
            reason_code="semantic_prerequisite",
            upstream_semantic_key="second",
        ),
        turn=1,
    )
    assert not manager.add(
        value,
        second,
        NeedDependency(
            kind="NEED",
            strength="SOFT",
            origin="LLM",
            reason_code="semantic_prerequisite",
            upstream_semantic_key="first",
        ),
        turn=1,
    )
    assert value.control.dependency_events[-1]["reason"] == "dependency_cycle_rejected"


def test_verification_need_depends_on_sent_mutation():
    value = state()
    value.mutations.append(
        MutationRecord(
            mutation_id="mutation-1",
            idempotency_key="key-1",
            tool_name="mutate_account",
            arguments={"account_id": "acct-1"},
            signature="mutate_account:acct-1",
            tool_call_id="call-1",
            status="SENT",
            planned_turn=1,
            updated_turn=1,
        )
    )
    NeedManager(capabilities={"read_account"}).register_many(
        value,
        [
            NeedCandidate(
                entity="mutate_account",
                aspect="verification_status",
                source="TOOL",
                capability="read_account",
                criticality="CRITICAL",
                reason_code="required_action_blocked",
                purpose="VERIFICATION",
            )
        ],
        turn=2,
    )
    need = value.information_needs[0]

    dependency = next(item for item in need.dependencies if item.kind == "MUTATION")
    assert dependency.mutation_signature == "mutate_account:acct-1"
    assert is_need_runnable(need, value)


def test_exhausted_hard_parent_propagates_to_critical_child():
    value = state()
    parent = InformationNeed(
        id="parent",
        semantic_key="parent",
        entity="card",
        aspect="annual_fee",
        source="POLICY",
        status="EXHAUSTED",
        exhausted=True,
        actionable=False,
        reason="fee",
    )
    child = InformationNeed(
        id="child",
        semantic_key="child",
        entity="card",
        aspect="candidate_options",
        source="POLICY",
        reason="options",
        dependencies=[
            NeedDependency(
                kind="NEED",
                strength="HARD",
                origin="DETERMINISTIC",
                reason_code="hard_constraint_input",
                upstream_semantic_key="parent",
            )
        ],
    )
    value.information_needs.extend([parent, child])

    refresh_dependency_state(value, turn=3)

    assert child.status == "EXHAUSTED"
    assert child.status_reason == "dependency_exhausted:parent"
