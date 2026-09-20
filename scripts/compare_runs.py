#!/usr/bin/env python
"""Compare two durable evaluate_v1 run directories without rerunning models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

METRICS = (
    "reward",
    "db_check",
    "required_actions_completed",
    "total_steps",
    "total_tool_calls",
    "knowledge_retrieval_calls",
    "main_decision_calls",
    "lightweight_llm_calls",
    "recovery_count",
    "input_tokens",
    "output_tokens",
    "total_cost",
    "end_to_end_latency_seconds",
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_records(run_dir: Path) -> dict[str, dict]:
    path = run_dir / "task_results.jsonl"
    return {
        item["task_id"]: item
        for line in path.read_text(encoding="utf-8").splitlines()
        if (item := json.loads(line))
    }


def delta(stable, candidate):
    if isinstance(stable, bool) or isinstance(candidate, bool):
        return int(bool(candidate)) - int(bool(stable))
    if isinstance(stable, (int, float)) and isinstance(candidate, (int, float)):
        return candidate - stable
    return None


def main():
    args = parse_args()
    stable = load_records(args.stable)
    candidate = load_records(args.candidate)
    common = sorted(set(stable).intersection(candidate))
    rows = []
    for task_id in common:
        row = {"task_id": task_id}
        for metric in METRICS:
            old = stable[task_id].get(metric)
            new = candidate[task_id].get(metric)
            row[metric] = {"stable": old, "candidate": new, "delta": delta(old, new)}
        rows.append(row)
    output = {
        "stable": str(args.stable),
        "candidate": str(args.candidate),
        "common_tasks": common,
        "stable_only": sorted(set(stable) - set(candidate)),
        "candidate_only": sorted(set(candidate) - set(stable)),
        "tasks": rows,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
