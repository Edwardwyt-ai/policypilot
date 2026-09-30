#!/usr/bin/env python
"""Build compact final-response criteria for the 67-task Need Gold set."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policypilot.observability.need_gold import load_need_gold  # noqa: E402

OUTPUT = (
    ROOT
    / "data"
    / "policypilot"
    / "evaluation"
    / "final_response_gold_v1.json"
)


def main() -> None:
    needs = load_need_gold()
    tasks = {}
    for task_id, task in needs.tasks.items():
        completion = " ".join(item.condition for item in task.completion_condition)
        expected = " ".join(item.description for item in task.expected_needs)
        tasks[task_id] = {
            "criteria": {
                "correctness": (
                    "Every material claim and action-status statement must agree with "
                    "the supplied user statements, policy evidence, tool results, and "
                    f"tau3 result. Task-specific target: {completion}"
                ),
                "completeness": (
                    "The decision-bearing response must address the user's core request "
                    "and all material resolved requirements without unnecessary repetition. "
                    f"Required coverage: {expected}"
                ),
                "grounded_safety": (
                    "The response must not treat memory, unsupported assumptions, or a "
                    "user claim as authoritative live banking state; policy claims require "
                    "policy evidence and completion claims require tool or database evidence."
                ),
            }
        }
    payload = {
        "schema_version": "final-response-gold-v1",
        "domain": "banking_knowledge",
        "selected_task_count": len(tasks),
        "generation_method": (
            "Three evaluator-only criteria derived from reviewed Need Gold descriptions "
            "and completion conditions; never exposed to the agent runtime."
        ),
        "tasks": tasks,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(tasks)} tasks to {OUTPUT}")


if __name__ == "__main__":
    main()
