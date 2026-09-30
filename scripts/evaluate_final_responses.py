#!/usr/bin/env python
"""Judge saved PolicyPilot responses with the configured DeepSeek API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from policypilot.observability.final_response_judge import (  # noqa: E402
    FinalResponseJudge,
    build_judge_packet,
    load_final_response_gold,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-dir", type=Path)
    source.add_argument("--results", type=Path, nargs="+")
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument(
        "--model",
        default=os.getenv("POLICYPILOT_JUDGE_MODEL", "deepseek/deepseek-chat"),
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args()


def result_paths(args: argparse.Namespace) -> list[Path]:
    if args.results:
        return [path.resolve() for path in args.results]
    return sorted(args.run_dir.glob("tasks/*/results.json"))


def main() -> int:
    args = parse_args()
    gold = load_final_response_gold(args.gold)
    judge = FinalResponseJudge(args.model)
    selected = set(args.task_ids or gold.tasks)
    paths = result_paths(args)
    output_dir = args.output_dir or (
        args.run_dir if args.run_dir else ROOT / "data" / "analyses" / "final_response_judge"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "semantic_judgments.jsonl"

    records = []
    errors = []
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                simulations = payload.get("simulations") or []
                if len(simulations) != 1:
                    raise ValueError("Expected one simulation per results file")
                task_id = simulations[0]["task_id"]
                if task_id not in selected or task_id not in gold.tasks:
                    continue
                packet = build_judge_packet(payload, task_id)
                record = judge.judge(
                    task_id=task_id,
                    criteria=gold.tasks[task_id].criteria,
                    packet=packet,
                    result_path=str(path),
                )
                rendered = record.model_dump(mode="json")
                records.append(rendered)
                handle.write(json.dumps(rendered, ensure_ascii=False) + "\n")
                handle.flush()
                print(
                    f"{task_id}: semantic={record.semantic_score:.3f} "
                    f"pass={record.semantic_pass} "
                    f"latency={record.usage.latency_seconds:.2f}s"
                )
            except Exception as exc:
                error = {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
                errors.append(error)
                print(f"ERROR {path}: {error['error']}", file=sys.stderr)
                if args.fail_fast:
                    raise

    passed = sum(bool(item["semantic_pass"]) for item in records)
    costs = [item["usage"]["cost"] for item in records]
    summary = {
        "schema_version": "final-response-judge-report-v1",
        "model": args.model,
        "judged_tasks": len(records),
        "passed_tasks": passed,
        "semantic_pass_rate": passed / len(records) if records else 0.0,
        "average_semantic_score": (
            sum(item["semantic_score"] for item in records) / len(records)
            if records
            else 0.0
        ),
        "total_judge_cost": sum(costs),
        "errors": errors,
        "records_path": str(output_path),
    }
    summary_path = output_dir / "semantic_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if records and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
