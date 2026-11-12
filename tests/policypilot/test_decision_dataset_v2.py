import json
import runpy
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import validate

from policypilot.observability.decision_prompt_eval import (
    ExpectedDecision,
    contract_errors,
    digest,
    load_dataset,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/policypilot/evaluation/decision_gepa_v2"


def rows():
    return [r for split in load_dataset(DATA).values() for r in split]


def probes():
    return {
        p["id"]: p
        for p in (
            json.loads(line)
            for line in (DATA / "judge_probes.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    }


def test_balanced_abilities_and_grouped_contrasts():
    splits = load_dataset(DATA)
    seen_groups, seen_pairs = set(), set()
    for split, cases in splits.items():
        assert len(cases) == 32
        assert set(Counter(c.provenance["ability"] for c in cases).values()) == {4}
        groups = {c.family for c in cases}
        pairs = {c.provenance["pair_id"] for c in cases}
        assert len(groups) == 8 and len(pairs) == 16
        assert not groups & seen_groups
        assert not pairs & seen_pairs
        seen_groups |= groups
        seen_pairs |= pairs
        assert all(
            c.split == split and c.provenance["exact_historical_replay"] == "false"
            for c in cases
        )
    paired = defaultdict(list)
    for row in rows():
        paired[row.provenance["pair_id"]].append(row)
    assert len(paired) == 48
    assert all(
        len(pair) == 2 and pair[0].expected != pair[1].expected
        for pair in paired.values()
    )


def test_no_v1_input_reuse_or_duplicate_frozen_inputs():
    v1 = load_dataset(ROOT / "data/policypilot/evaluation/decision_gepa_v1")
    old = {digest(row.input) for cases in v1.values() for row in cases}
    current = [digest(row.input) for row in rows()]
    assert not old.intersection(current)
    assert len(set(current)) == 96


def test_all_positive_probes_are_runtime_and_schema_compatible():
    fixtures = probes()
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    assert digest(list(fixtures.values())) == manifest["judge_probes_sha256"]
    for row in rows():
        positive = fixtures[row.id]["positive"]
        assert contract_errors(row, positive) == [], row.id
        if row.expected.kind == "tool_call":
            function = positive["tool_calls"][0]["function"]
            schema = next(
                t["function"]["parameters"]
                for t in row.input["tools"]
                if t["function"]["name"] == function["name"]
            )
            validate(json.loads(function["arguments"]), schema)
        assert "expected" not in row.input and "rubric" not in row.input
        assert "required_documents" not in json.dumps(row.input)


def test_counterfactual_foils_are_not_claimed_to_be_semantically_verified():
    fixtures = probes()
    semantic_only = 0
    for row in rows():
        fixture = fixtures[row.id]
        assert fixture["semantic_review_required"] is True
        assert fixture["positive"] != fixture["negative"]
        if not contract_errors(row, fixture["negative"]):
            semantic_only += 1
        if fixture["safety_negative"]:
            assert contract_errors(row, fixture["safety_negative"]) == []
    assert semantic_only > 0


def test_queries_allow_semantic_rewrites_but_reject_schema_errors():
    row = next(r for r in rows() if r.expected.tool == "KB_search")
    output = {
        "tool_calls": [
            {
                "function": {
                    "name": "KB_search",
                    "arguments": {
                        "query": "Personal cashback cards: annual charges and subscription eligibility"
                    },
                }
            }
        ]
    }
    assert contract_errors(row, output) == []
    output["tool_calls"][0]["function"]["arguments"] = {"query": 42}
    assert contract_errors(row, output)


def test_context_loading_allows_legitimate_pagination():
    row = next(r for r in rows() if r.expected.tool == "load_context_ref")
    arguments = {**row.expected.arguments, "length": 2000, "offset": 0}
    output = {
        "tool_calls": [
            {"function": {"name": "load_context_ref", "arguments": arguments}}
        ]
    }
    assert contract_errors(row, output) == []
    arguments["length"] = 99999
    assert contract_errors(row, output)


def test_positive_mutation_outcomes_are_tool_messages_not_memory():
    for row in rows():
        if row.provenance["ability"] != "mutation_verification":
            continue
        messages = row.input["messages"]
        events = [
            m
            for m in messages
            if m["role"] == "tool" and m.get("tool_call_id") == "observed-operation"
        ]
        assert len(events) == 1
        assert not any(
            "Fresh authoritative tool postcondition" in str(m) for m in messages
        )
        if row.expected.kind == "answer":
            assert "TIMEOUT" not in events[0]["content"]
        else:
            assert "UNKNOWN" in events[0]["content"]


def test_builder_is_deterministic_and_cannot_execute_business_tools(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "No tool or paid model execution during dataset construction"
        )

    monkeypatch.setattr("tau2.environment.tool.Tool.__call__", forbidden)
    monkeypatch.setattr("litellm.completion", forbidden)
    build = runpy.run_path(str(ROOT / "scripts/build_decision_gepa_v2.py"))["build"]
    built, _ = build()
    assert {row.id: row.model_dump() for row in built} == {
        row.id: row.model_dump() for row in rows()
    }


def test_draft_data_blocks_paid_modes_before_any_provider_call(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Draft guard must run before any model call")

    monkeypatch.setattr("litellm.completion", forbidden)
    monkeypatch.setattr(
        "sys.argv",
        ["optimize_decision_prompt.py", "--mode", "optimize", "--data", str(DATA)],
    )
    main = runpy.run_path(str(ROOT / "scripts/optimize_decision_prompt.py"))["main"]
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_manifest_freezes_labels_as_well_as_inputs():
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    cases = load_dataset(DATA)["train"]
    assert digest([c.model_dump() for c in cases]) == manifest["split_hashes"]["train"]
    changed = deepcopy(cases)
    changed[0].expected.rubric = "Altered criterion"
    assert (
        digest([c.model_dump() for c in changed]) != manifest["split_hashes"]["train"]
    )


def test_inconsistent_gold_contracts_are_rejected():
    from pydantic import ValidationError

    for values in (
        {"kind": "tool_call", "rubric": "Next action"},
        {"kind": "answer", "rubric": "Answer", "tool": "KB_search"},
        {
            "kind": "tool_call",
            "rubric": "Search",
            "tool": "KB_search",
            "arguments": {"query": "fixed"},
            "free_arguments": ["query"],
        },
    ):
        with pytest.raises(ValidationError):
            ExpectedDecision.model_validate(values)


@pytest.mark.parametrize("variants", [1, 2])
def test_judge_calibration_uses_only_train_and_preserves_probe_hash(variants):
    entry = runpy.run_path(str(ROOT / "scripts/optimize_decision_prompt.py"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    fixtures = list(probes().values())
    observed = []

    def evaluate(example, prediction):
        assert example.split == "train"
        observed.append((example.id, prediction))
        is_positive = prediction != probes()[example.id]["safety_negative"]
        return float(is_positive), {"feedback": "mock", "scores": {}}

    results = entry["calibrate_judge"](
        {**load_dataset(DATA), "manifest": manifest},
        fixtures,
        evaluate,
        variants=variants,
    )
    assert len(results) == len(observed) == 24 * variants
    assert all(r["score"] == r["expected_score"] for r in results)
    assert len({r["ability"] for r in results}) == 4
    fixtures[0]["positive"]["content"] = "Changed probe"
    with pytest.raises(ValueError, match="hash"):
        entry["calibrate_judge"](
            {**load_dataset(DATA), "manifest": manifest}, fixtures, evaluate
        )
    assert len(observed) == 24 * variants
