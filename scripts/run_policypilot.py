#!/usr/bin/env python
"""Run PolicyPilot on tau2 banking_knowledge tasks."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PYTHONUTF8", "1")

from policypilot.metrics import metrics_from_simulation  # noqa: E402
from policypilot.registry import register_policypilot  # noqa: E402
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.runner import get_tasks, run_tasks  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-ids", nargs="+", default=["task_001"])
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--user-model", required=True)
    parser.add_argument("--seed", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--max-errors", type=int, default=10)
    parser.add_argument("--save-to", default="policypilot_v1")
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--retrieval-config", default="local_hybrid")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    register_policypilot()
    config = TextRunConfig(
        domain="banking_knowledge",
        agent="policypilot",
        llm_agent=args.agent_model,
        llm_user=args.user_model,
        retrieval_config=args.retrieval_config,
        task_ids=args.task_ids,
        seed=args.seed,
        max_steps=args.max_steps,
        max_errors=args.max_errors,
        max_concurrency=args.max_concurrency,
        save_to=args.save_to,
    )
    tasks = get_tasks("banking_knowledge", task_ids=args.task_ids)
    save_dir = ROOT / "data" / "simulations" / args.save_to
    results = run_tasks(
        config,
        tasks,
        save_path=save_dir / "results.json",
        save_dir=save_dir,
        console_display=True,
    )
    print(
        "Task\tReward\tSteps\tTool Calls\tRetrieval Calls\tErrors\t"
        "Goal Changes\tRetries\tRecovery Success\tContext Size\tLatency"
    )
    for sim in results.simulations:
        metrics = metrics_from_simulation(sim)
        reward = sim.reward_info.reward if sim.reward_info else None
        print(
            f"{sim.task_id}\t{reward}\t{metrics.total_steps}\t"
            f"{metrics.total_tool_calls}\t{metrics.knowledge_retrieval_calls}\t"
            f"{metrics.tool_error_count}\t{metrics.goal_changes}\t"
            f"{metrics.llm_retry_count + metrics.tool_retry_count + metrics.tool_repair_count + metrics.retrieval_rewrite_count}\t"
            f"{metrics.recovery_success_count}\t{metrics.context_estimated_size}\t"
            f"{metrics.latency:.2f}"
        )


if __name__ == "__main__":
    main()
