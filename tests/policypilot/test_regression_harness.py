import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_fixed_evaluation_splits_are_disjoint_and_cover_every_task_identity():
    payload = json.loads(
        (ROOT / "configs" / "evaluation_splits.json").read_text(encoding="utf-8")
    )
    names = ("dev", "regression", "validation_holdout", "final_test", "reserve")
    groups = [set(payload[name]) for name in names]

    assert sum(len(group) for group in groups) == 97
    assert len(set().union(*groups)) == 97
    assert all(not left.intersection(right) for i, left in enumerate(groups) for right in groups[i + 1 :])
    assert {"task_001", "task_010"}.issubset(set(payload["regression"]))
