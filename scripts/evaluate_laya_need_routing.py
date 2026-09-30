"""Offline Laya evaluation over the evaluator-only PolicyPilot Need Gold set."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from policypilot.acquisition import (
    ACQUISITION_PLAN_CRITERIA,
    ACQUISITION_PLAN_INSTRUCTIONS,
    LocalLayaBackend,
)
from policypilot.observability.need_gold import load_need_gold

ROOT = Path(__file__).absolute().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "analyses"
PLAN_SOURCES = {
    "POLICY_ONLY": {"POLICY"},
    "TOOL_ONLY": {"TOOL"},
    "USER_ONLY": {"USER"},
    "POLICY_AND_TOOL": {"POLICY", "TOOL"},
    "POLICY_AND_USER": {"POLICY", "USER"},
    "TOOL_AND_USER": {"TOOL", "USER"},
}


def _gold_plan(sources: list[str]) -> str:
    normalized = set()
    if "policy_kb" in sources:
        normalized.add("POLICY")
    if "transaction_tool" in sources:
        normalized.add("TOOL")
    if "user_dialogue" in sources:
        normalized.add("USER")
    for plan, plan_sources in PLAN_SOURCES.items():
        if normalized == plan_sources:
            return plan
    raise ValueError(f"Unsupported source combination: {sources!r}")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _ece(rows: list[dict[str, Any]], bins: int = 10) -> float:
    total = len(rows)
    error = 0.0
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket = [
            row
            for row in rows
            if low <= row["confidence"] <= high
            and (index == bins - 1 or row["confidence"] < high)
        ]
        if not bucket:
            continue
        accuracy = sum(row["correct"] for row in bucket) / len(bucket)
        confidence = statistics.fmean(row["confidence"] for row in bucket)
        error += len(bucket) / total * abs(accuracy - confidence)
    return error


def _source_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_source = {}
    for source in ("POLICY", "TOOL", "USER"):
        tp = sum(source in row["gold_sources"] and source in row["pred_sources"] for row in rows)
        fp = sum(source not in row["gold_sources"] and source in row["pred_sources"] for row in rows)
        fn = sum(source in row["gold_sources"] and source not in row["pred_sources"] for row in rows)
        per_source[source] = _prf(tp, fp, fn)
    macro_f1 = statistics.fmean(item["f1"] for item in per_source.values())
    tp = sum(item["tp"] for item in per_source.values())
    fp = sum(item["fp"] for item in per_source.values())
    fn = sum(item["fn"] for item in per_source.values())
    return {"per_source": per_source, "macro_f1": macro_f1, "micro": _prf(tp, fp, fn)}


def _bounded_capability_candidates(
    task_id: str,
    need_id: str,
    gold: list[str],
    universe: list[str],
    limit: int = 9,
) -> list[str]:
    selected = list(dict.fromkeys(gold))
    distractors = [item for item in universe if item not in selected]
    distractors.sort(
        key=lambda item: hashlib.sha256(
            f"need-gold-v1|{task_id}|{need_id}|{item}".encode()
        ).hexdigest()
    )
    selected.extend(distractors[: max(0, limit - len(selected))])
    return selected


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    gold = load_need_gold(Path(args.gold) if args.gold else None)
    backend = LocalLayaBackend(
        model=args.model,
        device=args.device,
        cache_dir=args.cache_dir,
    )
    load_started = time.perf_counter()
    agent = backend._load()
    load_seconds = time.perf_counter() - load_started

    gold_rows = []
    capability_universe = sorted(
        {
            capability
            for task in gold.tasks.values()
            for rule in task.allowed_acquisition
            for capability in rule.capabilities
        }
    )
    for task_id, task in gold.tasks.items():
        acquisitions = {item.need_id: item for item in task.allowed_acquisition}
        completions = {item.need_id: item for item in task.completion_condition}
        for need in task.expected_needs:
            acquisition = acquisitions[need.id]
            gold_rows.append(
                {
                    "task_id": task_id,
                    "need_id": need.id,
                    "description": need.description,
                    "completion_condition": completions[need.id].condition,
                    "gold_sources_raw": acquisition.sources,
                    "gold_plan": _gold_plan(acquisition.sources),
                    "gold_capabilities": acquisition.capabilities,
                }
            )

    plan_question = {
        "acquisition_plan": {
            "type": "choice",
            "instructions": ACQUISITION_PLAN_INSTRUCTIONS,
            "criteria": ACQUISITION_PLAN_CRITERIA,
        }
    }
    plan_latencies = []
    evaluated = []
    for index, row in enumerate(gold_rows, start=1):
        state = {"missing_proposition": row["description"]}
        started = time.perf_counter()
        result = agent.system_one(state, plan_question)
        plan_latencies.append((time.perf_counter() - started) * 1000)
        answer = result["answers"]["acquisition_plan"]
        predicted = answer["choice"]
        probabilities = answer.get("probabilities", {})
        confidence = float(answer.get("answer_confidence", 0.0))
        gold_plan = row["gold_plan"]
        evaluated.append(
            {
                **row,
                "predicted_plan": predicted,
                "gold_sources": sorted(PLAN_SOURCES[gold_plan]),
                "pred_sources": sorted(PLAN_SOURCES.get(predicted, set())),
                "confidence": confidence,
                "probabilities": probabilities,
                "correct": predicted == gold_plan,
            }
        )
        if index % 50 == 0:
            print(f"plan routing: {index}/{len(gold_rows)}")

    confusion: dict[str, Counter] = defaultdict(Counter)
    for row in evaluated:
        confusion[row["gold_plan"]][row["predicted_plan"]] += 1
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_need_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluated:
        by_task[row["task_id"]].append(row)
        by_need_id[row["need_id"]].append(row)
    thresholded = [row for row in evaluated if row["confidence"] >= args.threshold]
    brier = statistics.fmean(
        sum(
            (float(row["probabilities"].get(plan, 0.0)) - (plan == row["gold_plan"])) ** 2
            for plan in PLAN_SOURCES
        )
        for row in evaluated
    )

    capability_rows = []
    capability_latencies = []
    tool_rows = [row for row in gold_rows if "transaction_tool" in row["gold_sources_raw"]]
    for index, row in enumerate(tool_rows, start=1):
        candidates = _bounded_capability_candidates(
            row["task_id"],
            row["need_id"],
            row["gold_capabilities"],
            capability_universe,
        )
        question = {
            "capability": {
                "type": "choice",
                "instructions": (
                    "Choose the capability that best satisfies this missing banking Need."
                ),
                "criteria": {
                    item: item.replace("_", " ") for item in candidates
                },
            }
        }
        started = time.perf_counter()
        result = agent.system_one(
            {"missing_proposition": row["description"]}, question
        )
        capability_latencies.append((time.perf_counter() - started) * 1000)
        answer = result["answers"]["capability"]
        predicted = answer["choice"]
        confidence = float(answer.get("answer_confidence", 0.0))
        capability_rows.append(
            {
                **row,
                "candidates": candidates,
                "predicted_capability": predicted,
                "confidence": confidence,
                "correct": predicted in row["gold_capabilities"],
                "kind": (
                    "execution"
                    if "prior_verified_evidence" in row["gold_sources_raw"]
                    else "read_or_verification"
                ),
            }
        )
        if index % 50 == 0:
            print(f"capability routing: {index}/{len(tool_rows)}")

    def capability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        selected = [row for row in rows if row["confidence"] >= args.threshold]
        return {
            "count": len(rows),
            "hit_at_1": sum(row["correct"] for row in rows) / len(rows) if rows else 0.0,
            "coverage_at_threshold": len(selected) / len(rows) if rows else 0.0,
            "selective_accuracy": (
                sum(row["correct"] for row in selected) / len(selected) if selected else None
            ),
        }

    report = {
        "schema_version": "laya-need-routing-eval-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": {
            "path": str(Path(args.gold).resolve()) if args.gold else "default_need_gold_path",
            "tasks": len(gold.tasks),
            "needs": len(gold_rows),
            "tool_source_needs": len(tool_rows),
            "method": (
                "Gold Need descriptions only; task ids, need ids, completion conditions, "
                "and labels are excluded from model input."
            ),
        },
        "model": {
            "id": args.model,
            "device": str(agent.device),
            "threshold": args.threshold,
            "load_seconds": load_seconds,
        },
        "plan_routing": {
            "raw_exact_accuracy": sum(row["correct"] for row in evaluated) / len(evaluated),
            "coverage_at_threshold": len(thresholded) / len(evaluated),
            "selective_accuracy": (
                sum(row["correct"] for row in thresholded) / len(thresholded)
                if thresholded
                else None
            ),
            "source_metrics": _source_metrics(evaluated),
            "ece_10_bin": _ece(evaluated),
            "multiclass_brier": brier,
            "gold_distribution": dict(Counter(row["gold_plan"] for row in evaluated)),
            "predicted_distribution": dict(
                Counter(row["predicted_plan"] for row in evaluated)
            ),
            "confusion": {key: dict(value) for key, value in confusion.items()},
            "task_level": {
                "all_needs_correct": sum(
                    all(row["correct"] for row in rows) for rows in by_task.values()
                ),
                "any_need_correct": sum(
                    any(row["correct"] for row in rows) for rows in by_task.values()
                ),
                "task_count": len(by_task),
            },
            "per_need_id": {
                need_id: {
                    "count": len(rows),
                    "accuracy": sum(row["correct"] for row in rows) / len(rows),
                    "mean_confidence": statistics.fmean(
                        row["confidence"] for row in rows
                    ),
                }
                for need_id, rows in sorted(by_need_id.items())
            },
            "latency_ms": {
                "mean": statistics.fmean(plan_latencies),
                "p50": _percentile(plan_latencies, 0.5),
                "p95": _percentile(plan_latencies, 0.95),
                "max": max(plan_latencies),
            },
        },
        "capability_proxy": {
            "method": (
                "Each transaction-tool Need receives its Gold capability labels plus "
                "deterministic distractors, capped at nine candidates. This is not an "
                "end-to-end runtime tool-call score."
            ),
            "overall": capability_summary(capability_rows),
            "read_or_verification": capability_summary(
                [row for row in capability_rows if row["kind"] == "read_or_verification"]
            ),
            "execution_out_of_runtime_scope": capability_summary(
                [row for row in capability_rows if row["kind"] == "execution"]
            ),
            "per_gold_capability": {
                capability: capability_summary(
                    [
                        row
                        for row in capability_rows
                        if capability in row["gold_capabilities"]
                    ]
                )
                for capability in capability_universe
                if any(
                    capability in row["gold_capabilities"]
                    for row in capability_rows
                )
            },
            "latency_ms": {
                "mean": statistics.fmean(capability_latencies),
                "p50": _percentile(capability_latencies, 0.5),
                "p95": _percentile(capability_latencies, 0.95),
                "max": max(capability_latencies),
            },
        },
        "rows": {
            "plan": evaluated,
            "capability": capability_rows,
        },
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"laya_need_routing_{datetime.now():%Y%m%d_%H%M%S}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["output"] = str(output.resolve())
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold")
    parser.add_argument("--model", default="convaiinnovations/laya")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--cache-dir", default=".cache/huggingface")
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    report = evaluate(args)
    summary = {key: value for key, value in report.items() if key != "rows"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
