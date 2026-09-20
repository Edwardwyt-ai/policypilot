#!/usr/bin/env python
"""Run a durable PolicyPilot V1 evaluation over banking_knowledge tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(ROOT / ".env")

from policypilot.evaluation import (  # noqa: E402
    run_evaluation_batch,
    sha256_file,
    write_config,
)
from policypilot.registry import register_policypilot  # noqa: E402
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.runner import get_tasks, run_tasks  # noqa: E402

DOMAIN = "banking_knowledge"
SOURCE_DB = ROOT / "data" / "tau2" / "domains" / DOMAIN / "db.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task-ids", nargs="+")
    selection.add_argument("--num-tasks", type=int)
    selection.add_argument("--task-file", type=Path)
    selection.add_argument(
        "--split",
        choices=("dev", "regression", "validation_holdout", "final_test", "reserve"),
    )
    parser.add_argument(
        "--selection",
        choices=("random", "first"),
        default="random",
        help="Selection mode used with --num-tasks (default: random).",
    )
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--user-model", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-errors", type=int, default=10)
    parser.add_argument("--save-to", required=True)
    parser.add_argument(
        "--splits-file",
        type=Path,
        default=ROOT / "configs" / "evaluation_splits.json",
    )
    return parser.parse_args()


def _read_task_file(path: Path) -> list[str]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            values.extend(item.strip() for item in stripped.split(",") if item.strip())
    if not values:
        raise ValueError(f"Task file is empty: {path}")
    return values


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def select_tasks(args: argparse.Namespace):
    """Select tasks by identity only; evaluation criteria are never inspected."""
    all_tasks = get_tasks(DOMAIN)
    by_id = {task.id: task for task in all_tasks}
    if args.task_ids:
        task_ids = args.task_ids
    elif args.split:
        split_payload = json.loads(args.splits_file.read_text(encoding="utf-8"))
        task_ids = list(split_payload[args.split])
    elif args.task_file:
        task_ids = _read_task_file(args.task_file)
    else:
        if args.num_tasks <= 0:
            raise ValueError("--num-tasks must be greater than zero")
        if args.num_tasks > len(all_tasks):
            raise ValueError(
                f"--num-tasks={args.num_tasks} exceeds available tasks ({len(all_tasks)})"
            )
        if args.selection == "first":
            task_ids = [task.id for task in all_tasks[: args.num_tasks]]
        else:
            task_ids = random.Random(args.seed).sample(
                [task.id for task in all_tasks], args.num_tasks
            )
    duplicates = [task_id for task_id in task_ids if task_ids.count(task_id) > 1]
    if duplicates:
        raise ValueError(f"Duplicate task ids are not allowed: {sorted(set(duplicates))}")
    missing = [task_id for task_id in task_ids if task_id not in by_id]
    if missing:
        raise ValueError(f"Unknown banking_knowledge task ids: {missing}")
    return task_ids, by_id


def main() -> None:
    args = parse_args()
    register_policypilot()
    task_ids, tasks_by_id = select_tasks(args)
    run_dir = ROOT / "data" / "simulations" / args.save_to
    if any((run_dir / name).exists() for name in ("task_results.jsonl", "summary.json")):
        raise FileExistsError(
            f"Evaluation output already exists: {run_dir}. Choose a new --save-to name."
        )
    run_dir.mkdir(parents=True, exist_ok=True)

    config_record = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "domain": DOMAIN,
        "agent": "policypilot",
        "agent_model": args.agent_model,
        "model_routing": {
            "light_model": os.getenv("POLICYPILOT_LIGHT_MODEL")
            or os.getenv("LIGHT_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or os.getenv("MODEL")
            or args.agent_model,
            "main_decision_model": os.getenv("POLICYPILOT_MAIN_DECISION_MODEL")
            or os.getenv("MAIN_DECISION_MODEL")
            or args.agent_model,
        },
        "user_model": args.user_model,
        "retrieval_config": "bm25",
        "task_ids": task_ids,
        "selection": args.split or (args.selection if args.num_tasks else "explicit"),
        "evaluation_split": args.split,
        "splits_file": str(args.splits_file) if args.split else None,
        "splits_file_sha256": sha256_file(args.splits_file) if args.split else None,
        "seed": args.seed,
        "max_steps": args.max_steps,
        "max_errors": args.max_errors,
        "execution": "sequential_isolated",
        "source_db_path": str(SOURCE_DB),
        "source_db_sha256_before": sha256_file(SOURCE_DB),
        "policypilot_source_sha256": _sha256_tree(ROOT / "src" / "policypilot"),
        "runner_sha256": sha256_file(Path(__file__)),
        "python_version": sys.version,
    }
    write_config(run_dir / "config.json", config_record)

    def run_one(task_id: str):
        task_dir = run_dir / "tasks" / task_id
        result_path = task_dir / "results.json"
        config = TextRunConfig(
            domain=DOMAIN,
            agent="policypilot",
            llm_agent=args.agent_model,
            llm_user=args.user_model,
            retrieval_config="bm25",
            task_ids=[task_id],
            seed=args.seed,
            max_steps=args.max_steps,
            max_errors=args.max_errors,
            max_concurrency=1,
            save_to=f"{args.save_to}/{task_id}",
        )
        results = run_tasks(
            config,
            [tasks_by_id[task_id]],
            save_path=result_path,
            save_dir=task_dir,
            console_display=False,
        )
        if len(results.simulations) != 1:
            raise RuntimeError(
                f"Expected one simulation for {task_id}, got {len(results.simulations)}"
            )
        return results.simulations[0], result_path

    evaluation = run_evaluation_batch(
        task_ids, run_dir, run_one, source_db_path=SOURCE_DB
    )
    summary = evaluation.summary
    print("Task\tStatus\tReward\tSuccess\tSteps\tTools\tRetrievals\tTermination")
    for record in evaluation.task_records:
        print(
            f"{record.task_id}\t{record.status}\t{record.reward}\t{record.success}\t"
            f"{record.total_steps}\t{record.total_tool_calls}\t"
            f"{record.knowledge_retrieval_calls}\t{record.termination_reason}"
        )
        for node, metric in record.node_llm_metrics.items():
            print(
                f"  {node}: calls={metric.calls} model={metric.model} "
                f"latency={metric.latency_seconds:.3f}s "
                f"tokens={metric.input_tokens}/{metric.output_tokens} "
                f"cost={metric.cost:.6f}"
                f"{'+' if not metric.cost_available else ''} "
                f"valid={metric.structured_valid_calls}/"
                f"{metric.structured_valid_calls + metric.structured_invalid_calls}"
            )
    print(
        f"\nCompleted {summary.completed_tasks}/{summary.total_tasks}; "
        f"success rate={summary.success_rate:.2%}; "
        f"average reward={summary.average_reward:.4f}; "
        f"total cost={summary.total_cost:.6f}"
        f"{' (lower bound)' if summary.cost_is_lower_bound else ''}; "
        f"source DB unchanged={summary.source_db_unchanged}"
    )
    print(f"Outputs: {run_dir}")


if __name__ == "__main__":
    main()
