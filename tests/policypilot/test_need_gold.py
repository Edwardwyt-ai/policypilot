"""Integrity tests for the evaluator-only internal Need gold set."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from policypilot.observability.need_gold import (
    NeedGoldDataset,
    default_need_gold_path,
    load_need_gold,
)

ROOT = Path(__file__).absolute().parents[2]
TASKS_PATH = ROOT / "data" / "tau2" / "domains" / "banking_knowledge" / "tasks.json"


def test_need_gold_selects_67_of_97_real_tasks() -> None:
    source_tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    source_ids = {task["id"] for task in source_tasks}
    gold = load_need_gold()

    assert len(source_tasks) == gold.source_task_count == 97
    assert len(gold.tasks) == gold.selected_task_count == 67
    assert set(gold.tasks).issubset(source_ids)


def test_each_task_exposes_only_the_three_reusable_label_groups() -> None:
    raw = json.loads(default_need_gold_path().read_text(encoding="utf-8"))

    for task_id, task_gold in raw["tasks"].items():
        assert set(task_gold) == {
            "expected_needs",
            "allowed_acquisition",
            "completion_condition",
        }, task_id


def test_every_need_has_one_acquisition_rule_and_completion_condition() -> None:
    gold = load_need_gold()

    for task_id, task_gold in gold.tasks.items():
        expected_ids = {need.id for need in task_gold.expected_needs}
        acquisition_ids = {rule.need_id for rule in task_gold.allowed_acquisition}
        completion_ids = {rule.need_id for rule in task_gold.completion_condition}
        assert acquisition_ids == expected_ids, task_id
        assert completion_ids == expected_ids, task_id


def test_need_gold_rejects_orphan_rules() -> None:
    raw = json.loads(default_need_gold_path().read_text(encoding="utf-8"))
    one_task = next(iter(raw["tasks"].values()))
    one_task["allowed_acquisition"][0]["need_id"] = "orphan_need"

    with pytest.raises(ValidationError, match="allowed_acquisition"):
        NeedGoldDataset.model_validate(raw)


def test_gold_is_not_embedded_in_benchmark_task_payloads() -> None:
    source_text = TASKS_PATH.read_text(encoding="utf-8")

    assert "expected_needs" not in source_text
    assert "allowed_acquisition" not in source_text
    assert "completion_condition" not in source_text
