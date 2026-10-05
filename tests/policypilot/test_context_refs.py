from __future__ import annotations

import json

from policypilot.config import PolicyPilotConfig
from policypilot.context_refs import hydrate_context_refs
from policypilot.evidence import EvidenceRecord, PolicyReference
from policypilot.observability.metadata import attach_metrics_metadata
from policypilot.provenance import RawPayloadRecord
from policypilot.state import InformationNeed, PolicyPilotState, StructuredGoal
from policypilot.workflow.context import build_agent_context
from tau2.data_model.message import AssistantMessage, SystemMessage


def _state() -> PolicyPilotState:
    return PolicyPilotState(
        run_id="run-context-ref",
        system_messages=[SystemMessage(role="system", content="system")],
        goal=StructuredGoal(
            objective="Compare personal cashback cards and verify the reward cap",
            target="personal card",
        ),
    )


def _policy_payload() -> str:
    return """1. Cashback Card Terms
   ID: doc_cashback
   Score: 0.9123
   Content: ## Rewards
This personal card has no annual fee.
Cashback is capped at $500 per calendar year.
Purchases above the annual cap do not earn additional cashback.
Account eligibility is evaluated separately.

[Timing: retrieval=10ms, reranking=20ms, total=30ms]
"""


def _attach_policy_evidence(
    state: PolicyPilotState,
    *,
    evidence_id: str = "kb-1",
    payload_id: str = "payload-kb-1",
) -> None:
    raw = _policy_payload()
    state.raw_payloads.append(
        RawPayloadRecord(
            payload_id=payload_id,
            run_id=state.run_id,
            source_type="TOOL",
            tool_call_id=evidence_id,
            raw_content=raw,
        )
    )
    state.evidence.append(
        EvidenceRecord(
            evidence_id=evidence_id,
            payload_ref=payload_id,
            source_type="knowledge_retrieval",
            turn_index=4,
            summary="The personal card offers cashback.",
            tool_name="KB_search",
            tool_args={"query": "personal cashback reward cap"},
            tool_call_id=evidence_id,
            policy_refs=[
                PolicyReference(
                    document_id="doc_cashback",
                    title="Cashback Card Terms",
                    score=0.9123,
                )
            ],
            metadata={
                "context_ref": {
                    "raw_chars": len(raw),
                    "summary_chars": 34,
                    "lossy": True,
                }
            },
        )
    )
    state.information_needs.append(
        InformationNeed(
            id="need-reward-cap",
            entity="personal card",
            aspect="reward_cap",
            source="POLICY",
            status="RESOLVED",
            reason="Verify the annual cashback reward cap",
            critical=True,
            evidence_refs=[evidence_id],
        )
    )


def test_rehydrates_lossy_policy_evidence_from_payload_ref():
    state = _state()
    _attach_policy_evidence(state)

    result = hydrate_context_refs(state)

    assert result.payload_refs == ["payload-kb-1"]
    assert result.references[0].need_ids == ("need-reward-cap",)
    assert result.references[0].document_ids == ("doc_cashback",)
    assert "$500 per calendar year" in result.references[0].content
    assert "payload_ref=payload-kb-1" in result.render()


def test_does_not_rehydrate_user_payloads():
    state = _state()
    state.raw_payloads.append(
        RawPayloadRecord(
            payload_id="payload-user",
            run_id=state.run_id,
            source_type="USER",
            raw_content="My private user message should remain in message history.",
        )
    )
    state.evidence.append(
        EvidenceRecord(
            evidence_id="user-1",
            payload_ref="payload-user",
            source_type="user",
            turn_index=1,
            summary="User asked about cashback.",
        )
    )

    assert hydrate_context_refs(state).references == ()


def test_rehydration_deduplicates_payloads_and_obeys_budget():
    state = _state()
    _attach_policy_evidence(state)
    duplicate = state.evidence[0].model_copy(
        update={"evidence_id": "kb-duplicate", "turn_index": 5}
    )
    state.evidence.append(duplicate)
    state.information_needs[0].evidence_refs.append("kb-duplicate")
    config = PolicyPilotConfig(
        max_rehydrated_refs=2,
        max_rehydrated_ref_chars=90,
        max_rehydrated_context_chars=500,
    )

    result = hydrate_context_refs(state, config)

    assert len(result.references) == 1
    assert len(result.references[0].content) <= 90
    assert len(result.render()) <= config.max_rehydrated_context_chars


def test_transaction_payload_is_reprojected_instead_of_copied_raw():
    state = _state()
    state.goal.objective = "Check the current account status"
    raw = json.dumps(
        {
            "account_id": "acct-1",
            "status": "OPEN",
            "internal_note": "X" * 500,
            "unrelated_history": ["Y" * 200 for _ in range(10)],
        }
    )
    state.raw_payloads.append(
        RawPayloadRecord(
            payload_id="payload-account",
            run_id=state.run_id,
            source_type="TOOL",
            tool_call_id="read-1",
            raw_content=raw,
        )
    )
    state.evidence.append(
        EvidenceRecord(
            evidence_id="read-1",
            payload_ref="payload-account",
            source_type="transaction_tool",
            turn_index=3,
            summary='{"fields":{"status":"OPEN"}}',
            tool_name="read_account",
            tool_call_id="read-1",
            metadata={
                "projection": {
                    "filtered_fields": 1,
                    "total_fields": 13,
                    "range_selected": False,
                    "aggregation": {},
                }
            },
        )
    )
    state.information_needs.append(
        InformationNeed(
            id="need-status",
            entity="account",
            aspect="status",
            source="TOOL",
            status="RESOLVED",
            reason="Verify current account status",
            evidence_refs=["read-1"],
        )
    )

    result = hydrate_context_refs(state)

    assert '"status": "OPEN"' in result.references[0].content
    assert "X" * 100 not in result.references[0].content
    assert "Y" * 100 not in result.references[0].content


def test_context_manifest_records_rehydrated_payload_refs(tools):
    state = _state()
    _attach_policy_evidence(state)
    hydrated = hydrate_context_refs(state)

    context = build_agent_context(
        state,
        tools,
        rehydrated_context=hydrated.render(),
        rehydrated_refs=hydrated.payload_refs,
        rehydrated_evidence_ids=hydrated.evidence_ids,
        rehydrated_need_ids=hydrated.need_ids,
    )

    assert "<rehydrated_context>" in context.structured_summary
    manifest = state.context_manifests[-1]
    assert manifest.metadata["rehydrated_refs"] == ["payload-kb-1"]
    assert "kb-1" in manifest.evidence_ids
    assert "need-reward-cap" in manifest.need_ids
    assert manifest.metadata["channel_sizes"]["rehydrated"] > 0


def test_workflow_exposes_explicit_hydration_node(agent_factory):
    agent = agent_factory(
        config=PolicyPilotConfig(
            memory_enabled=False,
            skills_enabled=False,
            semantic_planner_enabled=False,
        )
    )
    state = _state()
    _attach_policy_evidence(state)

    update = agent.workflow.hydrate_context(
        {"policy_state": state, "node_trace": ["route_need"]}
    )

    assert update["node_trace"] == ["route_need", "hydrate_context"]
    assert update["rehydrated_context"].payload_refs == ["payload-kb-1"]
    assert state.control.context_rehydration_events[-1]["reference_count"] == 1


def test_hydration_events_are_exported_to_evaluation_metadata(agent_factory):
    agent = agent_factory(
        config=PolicyPilotConfig(
            memory_enabled=False,
            skills_enabled=False,
            semantic_planner_enabled=False,
        )
    )
    state = _state()
    state.control.context_rehydration_events.append(
        {
            "turn": 4,
            "payload_refs": ["payload-kb-1"],
            "evidence_ids": ["kb-1"],
            "need_ids": ["need-reward-cap"],
            "reference_count": 1,
            "content_chars": 120,
        }
    )
    message = AssistantMessage.text("done")

    attach_metrics_metadata(agent, message, state)

    exported = message.raw_data["policypilot_v1"]
    assert exported["context_rehydration_events"] == (
        state.control.context_rehydration_events
    )


def test_decision_context_prefers_need_bound_evidence_over_lexical_overlap(tools):
    state = _state()
    state.evidence.extend(
        [
            EvidenceRecord(
                evidence_id="bound-policy",
                source_type="knowledge_retrieval",
                turn_index=1,
                summary="The annual fee requirement is zero.",
            ),
            EvidenceRecord(
                evidence_id="lexical-only",
                source_type="knowledge_retrieval",
                turn_index=2,
                summary="Cashback card comparison marketing overview.",
            ),
        ]
    )
    state.information_needs.append(
        InformationNeed(
            id="need-fee",
            entity="personal card",
            aspect="annual_fee",
            source="POLICY",
            status="RESOLVED",
            reason="Verify the hard no-fee constraint",
            critical=True,
            evidence_refs=["bound-policy"],
        )
    )

    context = build_agent_context(
        state,
        tools,
        config=PolicyPilotConfig(max_context_evidence=1),
    )

    assert "bound-policy" in context.structured_summary
    assert "lexical-only" not in context.structured_summary
