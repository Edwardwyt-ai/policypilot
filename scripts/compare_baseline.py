#!/usr/bin/env python
"""Compare built-in tau2 llm_agent against PolicyPilot on identical tasks."""

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
from tau2.metrics.agent_metrics import is_successful  # noqa: E402
from tau2.runner import get_tasks, run_tasks  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-ids", nargs="+", default=["task_001", "task_002", "task_003", "task_004", "task_005"])
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--user-model", required=True)
    parser.add_argument("--seed", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--max-errors", type=int, default=10)
    return parser.parse_args()


def run_agent(agent_name: str, args: argparse.Namespace):
    run_name = f"{agent_name}_comparison"
    config = TextRunConfig(
        domain="banking_knowledge",
        agent=agent_name,
        llm_agent=args.agent_model,
        llm_user=args.user_model,
        retrieval_config="bm25",
        task_ids=args.task_ids,
        seed=args.seed,
        max_steps=args.max_steps,
        max_errors=args.max_errors,
        max_concurrency=1,
        save_to=run_name,
    )
    tasks = get_tasks("banking_knowledge", task_ids=args.task_ids)
    save_dir = ROOT / "data" / "simulations" / run_name
    return run_tasks(
        config,
        tasks,
        save_path=save_dir / "results.json",
        save_dir=save_dir,
        console_display=True,
    )


def _reward(simulation):
    if simulation is None or simulation.reward_info is None:
        return None
    return simulation.reward_info.reward


def _success(simulation):
    reward = _reward(simulation)
    return is_successful(reward) if reward is not None else None


def _retry_count(metrics):
    if metrics is None:
        return None
    return (
        metrics.llm_retry_count
        + metrics.tool_retry_count
        + metrics.tool_repair_count
        + metrics.retrieval_rewrite_count
    )


def main() -> None:
    args = parse_args()
    register_policypilot()
    baseline = run_agent("llm_agent", args)
    policy = run_agent("policypilot", args)
    baseline_by_task = {sim.task_id: sim for sim in baseline.simulations}
    policy_by_task = {sim.task_id: sim for sim in policy.simulations}

    print(
        "\t".join(
            [
                "Task",
                "Baseline Success",
                "PolicyPilot V1 Success",
                "Baseline Reward",
                "PolicyPilot V1 Reward",
                "Baseline Steps",
                "PolicyPilot V1 Steps",
                "Baseline Tool Calls",
                "PolicyPilot V1 Tool Calls",
                "Baseline Duplicates",
                "PolicyPilot V1 Duplicates",
                "Baseline Errors",
                "PolicyPilot V1 Errors",
                "Baseline Goal Changes",
                "PolicyPilot V1 Goal Changes",
                "Baseline Retries",
                "PolicyPilot V1 Retries",
                "Baseline Recovery Success",
                "PolicyPilot V1 Recovery Success",
                "Baseline Context Size",
                "PolicyPilot V1 Context Size",
                "Baseline Latency",
                "PolicyPilot V1 Latency",
            ]
        )
    )
    for task_id in args.task_ids:
        base_sim = baseline_by_task.get(task_id)
        policy_sim = policy_by_task.get(task_id)
        base_metrics = metrics_from_simulation(base_sim) if base_sim else None
        policy_metrics = metrics_from_simulation(policy_sim) if policy_sim else None
        print(
            "\t".join(
                str(value)
                for value in [
                    task_id,
                    _success(base_sim),
                    _success(policy_sim),
                    _reward(base_sim),
                    _reward(policy_sim),
                    base_metrics.total_steps if base_metrics else None,
                    policy_metrics.total_steps if policy_metrics else None,
                    base_metrics.total_tool_calls if base_metrics else None,
                    policy_metrics.total_tool_calls if policy_metrics else None,
                    "N/A",
                    policy_metrics.duplicate_call_count if policy_metrics else None,
                    base_metrics.tool_error_count if base_metrics else None,
                    policy_metrics.tool_error_count if policy_metrics else None,
                    "N/A",
                    policy_metrics.goal_changes if policy_metrics else None,
                    "N/A",
                    _retry_count(policy_metrics),
                    "N/A",
                    policy_metrics.recovery_success_count if policy_metrics else None,
                    "N/A",
                    policy_metrics.context_estimated_size if policy_metrics else None,
                    base_metrics.latency if base_metrics else None,
                    policy_metrics.latency if policy_metrics else None,
                ]
            )
        )


if __name__ == "__main__":
    main()
