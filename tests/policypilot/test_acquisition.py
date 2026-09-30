from __future__ import annotations

import os

import pytest

from policypilot.acquisition import AcquisitionPlanner, LocalLayaBackend
from policypilot.need_registry import NeedRegistry
from policypilot.state import FactRecord, NeedCandidate, PolicyPilotState
from tau2.data_model.message import SystemMessage


class FakeLayaBackend:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        return {
            "model": "laya-test",
            "answers": self.answers,
            "usage": {"input_tokens": 120, "output_tokens": 4},
        }


def value_with_account_id():
    value = PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")]
    )
    value.goal.objective = "Determine whether acct-secret is eligible"
    value.goal.target = "account"
    value.facts.append(
        FactRecord(
            id="account-id",
            entity="user",
            aspect="account_id",
            value="acct-secret",
            source="USER",
            turn_index=0,
            authoritative=True,
        )
    )
    return value


def semantic_candidate():
    return NeedCandidate(
        entity="account",
        aspect="eligibility_rule",
        scope="account",
        source="POLICY",
        criticality="CRITICAL",
        reason_code="required_action_blocked",
        provenance="semantic_planner",
    )


def test_laya_compiles_policy_and_tool_as_acquisitions_of_one_need(tools):
    backend = FakeLayaBackend(
        {
            "acquisition_plan": {
                "choice": "POLICY_AND_TOOL",
                "confidence": 0.96,
            },
            "read_capability": {
                "choice": "read_account",
                "confidence": 0.93,
            },
        }
    )
    planner = AcquisitionPlanner(tools, backend)
    state = value_with_account_id()

    planned = planner.plan(state, [semantic_candidate()], turn=1)
    NeedRegistry(capabilities={"read_account"}).register_many(
        state, planned, turn=1
    )

    assert len(state.information_needs) == 1
    need = state.information_needs[0]
    assert need.semantic_key == "account|eligibility_rule|account"
    assert [item.source for item in need.acquisitions] == ["POLICY", "TOOL"]
    assert need.acquisitions[1].capability == "read_account"
    assert need.acquisitions[1].tool_arguments == {"account_id": "acct-secret"}


def test_required_acquisitions_resolve_sequentially(tools):
    backend = FakeLayaBackend(
        {
            "acquisition_plan": {
                "choice": "POLICY_AND_TOOL",
                "confidence": 0.95,
            },
            "read_capability": {"choice": "read_account", "confidence": 0.95},
        }
    )
    state = value_with_account_id()
    planned = AcquisitionPlanner(tools, backend).plan(
        state, [semantic_candidate()], turn=1
    )
    NeedRegistry(capabilities={"read_account"}).register_many(
        state, planned, turn=1
    )
    need = state.information_needs[0]

    assert need.source == "POLICY"
    assert state.resolve_need(need, evidence_refs=["kb-1"]) is False
    assert need.status == "OPEN"
    assert need.source == "TOOL"
    assert need.capability == "read_account"
    assert state.resolve_need(need, evidence_refs=["tool-1"]) is True
    assert need.status == "RESOLVED"


def test_laya_state_excludes_fact_values_and_raw_messages(tools):
    backend = FakeLayaBackend(
        {
            "acquisition_plan": {"choice": "POLICY_ONLY", "confidence": 0.9},
            "read_capability": {"choice": "NONE", "confidence": 0.9},
        }
    )
    state = value_with_account_id()

    AcquisitionPlanner(tools, backend).plan(
        state, [semantic_candidate()], turn=1
    )

    payload = backend.calls[0][0]
    assert "acct-secret" not in repr(payload)
    assert payload["available_fact_fields"] == ["account_id"]


def test_local_laya_backend_loads_once_and_uses_no_api():
    calls = []

    class FakeAgent:
        def system_one(self, state, questions):
            calls.append((state, questions))
            return {"model": "runtime-laya", "answers": {}, "usage": {}}

    load_calls = []

    def fake_loader(model, *, device):
        load_calls.append((model, device))
        return FakeAgent()

    backend = LocalLayaBackend(
        model="local-laya-test",
        device="cuda",
        loader=fake_loader,
    )

    first = backend.decide({"need": {}}, {"plan": {"type": "choice"}})
    second = backend.decide({"need": {}}, {"plan": {"type": "choice"}})

    assert load_calls == [("local-laya-test", "cuda")]
    assert len(calls) == 2
    assert first["model"] == "local-laya-test"
    assert first["runtime_model"] == "runtime-laya"
    assert second["answers"] == {}


def test_no_backend_preserves_planner_hint_as_fallback(tools):
    state = value_with_account_id()

    planned = AcquisitionPlanner(tools, None).plan(
        state, [semantic_candidate()], turn=1
    )

    assert len(planned[0].acquisitions) == 1
    assert planned[0].acquisitions[0].source == "POLICY"
    assert planned[0].acquisitions[0].origin == "PLANNER_FALLBACK"


def test_low_confidence_laya_does_not_override_planner_hint(tools):
    backend = FakeLayaBackend(
        {
            "acquisition_plan": {
                "choice": "POLICY_AND_TOOL",
                "confidence": 0.74,
            },
            "read_capability": {"choice": "read_account", "confidence": 0.99},
        }
    )

    planned = AcquisitionPlanner(tools, backend).plan(
        value_with_account_id(), [semantic_candidate()], turn=1
    )

    assert [item.source for item in planned[0].acquisitions] == ["POLICY"]
    assert planned[0].acquisitions[0].origin == "PLANNER_FALLBACK"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("POLICYPILOT_RUN_LOCAL_LAYA") != "1",
    reason="set POLICYPILOT_RUN_LOCAL_LAYA=1 for the local model smoke test",
)
def test_real_local_laya_smoke():
    backend = LocalLayaBackend(
        model="convaiinnovations/laya",
        device=os.getenv("POLICYPILOT_LAYA_DEVICE", "auto"),
        cache_dir=os.getenv(
            "POLICYPILOT_LAYA_CACHE_DIR", ".cache/huggingface"
        ),
    )

    result = backend.decide(
        {"missing_proposition": "Determine the annual fee for a credit card."},
        {
            "acquisition_plan": {
                "type": "choice",
                "instructions": "Choose the authoritative evidence source.",
                "criteria": {
                    "POLICY_ONLY": "General product policy is sufficient.",
                    "TOOL_ONLY": "Current customer-specific state is required.",
                    "USER_ONLY": "Only the user knows the missing fact.",
                },
            }
        },
    )

    answer = result["answers"]["acquisition_plan"]
    assert answer["choice"] in {"POLICY_ONLY", "TOOL_ONLY", "USER_ONLY"}
    assert 0.0 <= answer["answer_confidence"] <= 1.0
    assert result["usage"]["output_tokens"] == 0


def test_registry_merges_same_semantic_need_across_authorities():
    state = value_with_account_id()
    registry = NeedRegistry(capabilities={"read_account"})
    candidates = [
        NeedCandidate(
            entity="account",
            aspect="eligibility_rule",
            scope="account",
            source="POLICY",
        ),
        NeedCandidate(
            entity="account",
            aspect="eligibility_rule",
            scope="account",
            source="TOOL",
            capability="read_account",
            tool_arguments={"account_id": "acct-secret"},
        ),
    ]

    registry.register_many(state, candidates, turn=1)

    assert len(state.information_needs) == 1
    assert {item.source for item in state.information_needs[0].acquisitions} == {
        "POLICY",
        "TOOL",
    }
