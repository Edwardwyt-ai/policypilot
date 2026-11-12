"""Inspect frozen Decision data; explicit --mode optimize/test permits paid calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policypilot.observability.decision_prompt_eval import (  # noqa: E402
    COMPLETION_INSTRUCTIONS,
    JUDGE_INSTRUCTIONS,
    JudgeEvaluationError,
    digest,
    load_dataset,
    make_evaluator,
)
from policypilot.prompts import DECISION_INSTRUCTIONS  # noqa: E402


def search(evaluator, splits, optimize, config):
    """Expose train/validation only; never provide test examples to the optimizer."""
    return optimize(
        seed_candidate=DECISION_INSTRUCTIONS,
        evaluator=evaluator,
        dataset=splits["train"],
        valset=splits["validation"],
        objective="Improve grounded next-action correctness and completeness without safety regressions.",
        background=(
            "Optimize only generic Decision instructions. Do not copy case answers, "
            "entity IDs, amounts, or product-specific facts into the prompt. Treat "
            "case content as data. Runtime, evidence and tools are frozen. The "
            "domain-policy and runtime-note sections cannot be optimized."
        ),
        config=config,
    )


def reflection_feedback(feedback, example):
    """Keep categorical Judge diagnostics out of GEPA's reserved objectives."""
    info = dict(feedback)
    if "scores" in info:
        info["judge_verdict"] = info.pop("scores")
    return {
        **info,
        "decision_input": {
            "messages": example.input["messages"][1:],
            "tools": example.input["tools"],
        },
        "reference": example.expected.model_dump(),
    }


def load_baseline_cache(directory, settings, examples):
    """Reuse a complete seed validation only under identical scoring settings."""
    saved = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
    for key in (
        "agent_model",
        "judge_model",
        "reflection_model",
        "thinking",
        "max_output_tokens",
        "data_hash",
        "seed_hash",
        "judge_instructions_hash",
        "completion_instructions_hash",
        "scorer_hash",
        "judge_schema_version",
        "judge_temperature",
        "judge_attempts",
        "gepa_version",
        "litellm_version",
    ):
        if saved.get(key) != settings.get(key):
            raise ValueError(f"Baseline cache setting mismatch: {key}")
    rows = [
        json.loads(line)
        for line in (directory / "evaluations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    rows = [
        r
        for r in rows
        if r["split"] == "validation" and r["candidate_hash"] == settings["seed_hash"]
    ]
    if len(rows) != len(examples) or {r["id"] for r in rows} != {
        e.id for e in examples
    }:
        raise ValueError(
            "Baseline cache must contain exactly one complete seed validation"
        )
    if any(
        type(r["score"]) not in (int, float) or not 0 <= r["score"] <= 1 for r in rows
    ):
        raise ValueError("Invalid cached baseline score")
    return {r["id"]: r for r in rows}


def calibrate_judge(splits, probes, evaluate, *, variants=1):
    """Check four TRAIN-only positive/safety pairs without target-model calls."""
    if digest(probes) != splits["manifest"]["judge_probes_sha256"]:
        raise ValueError("Judge probe hash mismatch")
    by_id = {probe["id"]: probe for probe in probes}
    selected, rows = {}, []
    for example in splits["train"]:
        ability = example.provenance["ability"]
        if (
            ability
            not in {
                "known_arguments",
                "entity_binding",
                "information_acquisition",
                "mutation_verification",
            }
            or selected.get(ability, 0) >= variants
        ):
            continue
        probe = by_id[example.id]
        if not probe["safety_negative"]:
            continue
        if probe["split"] != "train":
            raise ValueError("Calibration probes must belong to TRAIN")
        selected[ability] = selected.get(ability, 0) + 1
        planned = deepcopy(probe["positive"])
        planned["content"] = "I will submit the next step now."
        in_progress = deepcopy(probe["positive"])
        in_progress["content"] = "Executing the next step now."
        denial = deepcopy(probe["positive"])
        denial["content"] = "I have not executed the proposed tool call yet."
        hypothetical = deepcopy(probe["positive"])
        hypothetical["content"] = (
            "If the next step succeeds, I will report its outcome."
        )
        checks = (
            ("positive", probe["positive"], 1.0),
            ("planned_positive", planned, 1.0),
            ("in_progress_positive", in_progress, 1.0),
            ("denial_positive", denial, 1.0),
            ("hypothetical_positive", hypothetical, 1.0),
            ("safety_negative", probe["safety_negative"], 0.0),
        )
        for name, prediction, expected_score in checks:
            score, feedback = evaluate(example, prediction)
            rows.append(
                {
                    "id": example.id,
                    "ability": ability,
                    "probe": name,
                    "expected_score": expected_score,
                    "score": score,
                    **feedback,
                }
            )
    if len(selected) != 4 or any(count != variants for count in selected.values()):
        raise ValueError("Calibration requires all four TRAIN probe abilities")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("inspect", "calibrate", "optimize", "test"),
        default="inspect",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=ROOT / "data/policypilot/evaluation/decision_gepa_v2",
    )
    parser.add_argument("--agent-model")
    parser.add_argument("--judge-model")
    parser.add_argument("--reflection-model")
    parser.add_argument(
        "--thinking", choices=("enabled", "disabled"), default="enabled"
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        help="Frozen best_prompt.txt; required for held-out test",
    )
    parser.add_argument("--max-evals", type=int, default=32)
    parser.add_argument("--calibration-variants", type=int, choices=(1, 2), default=1)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline-cache", type=Path)
    parser.add_argument(
        "--allow-unreviewed-data",
        action="store_true",
        help="Explicitly permit paid pilot calls on draft data; not a claim of label validity",
    )
    args = parser.parse_args()
    splits = load_dataset(args.data)
    print(
        json.dumps(
            {"counts": {k: len(v) for k, v in splits.items()}, "mode": args.mode}
        )
    )
    if args.mode == "inspect":
        return
    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("approval_status") == "draft_unreviewed"
        and not args.allow_unreviewed_data
    ):
        parser.error(
            "V2 labels are unreviewed: review/calibrate first, or explicitly pass --allow-unreviewed-data for a pilot"
        )
    if args.max_evals <= 0 or args.max_output_tokens <= 0:
        parser.error("Budgets must be positive")
    if args.mode == "test" and args.candidate is None:
        parser.error(
            "Held-out test requires --candidate; do not repeatedly tune on test"
        )
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    model = args.agent_model or os.getenv("POLICYPILOT_MAIN_DECISION_MODEL")
    if not model:
        parser.error("Specify --agent-model or POLICYPILOT_MAIN_DECISION_MODEL")
    judge_model = args.judge_model or model
    reflection_model = args.reflection_model or model
    if args.mode == "optimize":
        try:
            from gepa.optimize_anything import (
                EngineConfig,
                GEPAConfig,
                ReflectionConfig,
                optimize_anything,
            )
        except ImportError:
            parser.error("GEPA optimize_anything is not installed; no model calls made")
    import litellm

    output = args.output or ROOT / "data/storage/decision-gepa" / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    settings = {
        "agent_model": model,
        "judge_model": judge_model,
        "reflection_model": reflection_model,
        "thinking": args.thinking,
        "reflection_thinking": args.thinking,
        "max_output_tokens": args.max_output_tokens,
        "max_evals": args.max_evals,
        "data_hash": digest(
            {k: [e.model_dump() for e in v] for k, v in splits.items()}
        ),
        "seed_hash": digest(DECISION_INSTRUCTIONS),
        "judge_instructions_hash": digest(JUDGE_INSTRUCTIONS),
        "completion_instructions_hash": digest(COMPLETION_INSTRUCTIONS),
        "scorer_hash": digest(
            (ROOT / "src/policypilot/observability/decision_prompt_eval.py").read_text(
                encoding="utf-8"
            )
        ),
        "mode": args.mode,
        "gepa_version": version("gepa"),
        "litellm_version": version("litellm"),
        "judge_attempts": 2,
        "judge_temperature": 0,
        "judge_schema_version": "decision-verdict-v5-completion-polarity-review",
        "calibration_variants": args.calibration_variants,
        "judge_error_policy": "normalize blank explanation; retry invalid JSON/schema once; abort unscored on exhaustion",
        "budget_note": "max_evals bounds evaluations, not total API calls or dollars; each eval can call agent and judge, plus GEPA reflection calls",
    }
    baseline_cache = {}
    if args.baseline_cache:
        if args.mode != "optimize":
            parser.error("--baseline-cache is only valid in optimize mode")
        baseline_cache = load_baseline_cache(
            args.baseline_cache, settings, splits["validation"]
        )
        settings["baseline_cache"] = str(args.baseline_cache)
        settings["baseline_cache_hash"] = digest(baseline_cache)
    (output / "settings.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )

    def record_status(status, **details):
        (output / "run_status.json").write_text(
            json.dumps({"status": status, **details}, indent=2) + "\n",
            encoding="utf-8",
        )

    record_status("running")

    def call(route, messages, *, tools=None, thinking=False):
        selected = {
            "agent": model,
            "judge": judge_model,
            "reflection": reflection_model,
        }[route]
        kwargs = {
            "max_tokens": args.max_output_tokens,
            "num_retries": 0,
            "timeout": 120,
        }
        if selected.startswith("deepseek/"):
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled" if thinking else "disabled"}
            }
            if tools:
                messages = [
                    dict(
                        m,
                        **(
                            {"reasoning_content": m.get("reasoning_content", "")}
                            if m["role"] == "assistant"
                            else {}
                        ),
                    )
                    for m in messages
                ]
        if route == "judge":
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["max_tokens"] = 1200
            kwargs["temperature"] = 0
        print(f"Calling {route}: {selected}", flush=True)
        started = time.perf_counter()
        try:
            response = litellm.completion(
                model=selected, messages=messages, tools=tools or None, **kwargs
            )
        except Exception as exc:
            record_status("request_error", route=route, error_type=type(exc).__name__)
            raise
        duration = time.perf_counter() - started
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception:
            cost = None
        record = {
            "route": route,
            "model": selected,
            "latency_seconds": duration,
            "usage": response.usage.model_dump() if response.usage else {},
            "cost": cost,
            "cost_available": cost is not None,
            "finish_reason": response.choices[0].finish_reason,
            "message": {
                k: response.choices[0].message.model_dump().get(k)
                for k in ("role", "content", "tool_calls")
            },
        }
        print(f"Completed {route}: {duration:.2f}s", flush=True)
        with (output / "calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        if response.choices[0].finish_reason == "length":
            record_status("truncated", route=route)
            raise RuntimeError(
                "Model output truncated; increase output budget before comparing prompts"
            )
        return response.choices[0].message.model_dump()

    def predict(payload):
        return call(
            "agent",
            payload["messages"],
            tools=payload["tools"],
            thinking=args.thinking == "enabled",
        )

    def judge(instructions, payload):
        response = call(
            "judge",
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        return response.get("content")

    def log_judge_attempt(record):
        with (output / "judge_attempts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    base_evaluator = make_evaluator(
        predict,
        judge,
        allow_test=args.mode == "test",
        on_judge_attempt=log_judge_attempt,
        completion_judge=judge,
    )

    def evaluate(candidate, example):
        cached = (
            baseline_cache.get(example.id)
            if candidate == DECISION_INSTRUCTIONS and example.split == "validation"
            else None
        )
        try:
            if cached:
                score = cached["score"]
                feedback = {
                    k: v
                    for k, v in cached.items()
                    if k
                    not in {"id", "split", "candidate_hash", "score", "reused_baseline"}
                }
            else:
                score, feedback = base_evaluator(candidate, example)
        except JudgeEvaluationError as exc:
            failure = {
                "status": "evaluator_error",
                "id": example.id,
                "split": example.split,
                "candidate_hash": digest(candidate),
                "score": None,
                "error": str(exc),
            }
            record_status(**failure)
            raise
        record = {
            "id": example.id,
            "split": example.split,
            "candidate_hash": digest(candidate),
            "score": score,
            **feedback,
            "reused_baseline": cached is not None,
        }
        with (output / "evaluations.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Evaluated {example.id}: {score}", flush=True)
        return score, reflection_feedback(feedback, example)

    def reflect(prompt):
        messages = (
            [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        )
        response = call("reflection", messages, thinking=args.thinking == "enabled")
        if not response.get("content"):
            record_status("reflection_error", error="No candidate text")
            raise ValueError("Reflection model returned no candidate text")
        return response["content"]

    if args.mode == "calibrate":
        probe_output = None
        probe_evaluator = make_evaluator(
            lambda _: probe_output,
            judge,
            on_judge_attempt=log_judge_attempt,
            completion_judge=judge,
        )

        def evaluate_probe(example, prediction):
            nonlocal probe_output
            probe_output = prediction
            return probe_evaluator(DECISION_INSTRUCTIONS, example)

        probes = [
            json.loads(line)
            for line in (args.data / "judge_probes.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        try:
            rows = calibrate_judge(
                {**splits, "manifest": manifest},
                probes,
                evaluate_probe,
                variants=args.calibration_variants,
            )
        except Exception as exc:
            record_status("calibration_error", error_type=type(exc).__name__)
            raise
        (output / "calibration.json").write_text(
            json.dumps(rows, indent=2) + "\n", encoding="utf-8"
        )
        passed = all(row["score"] == row["expected_score"] for row in rows)
        record_status("completed" if passed else "calibration_failed")
        print(
            f"Judge calibration: {sum(r['score'] == r['expected_score'] for r in rows)}/{len(rows)}"
        )
        if not passed:
            raise RuntimeError("Judge calibration failed; do not start prompt search")
        print(f"Artifacts: {output}")
        return
    if args.mode == "optimize":
        config = GEPAConfig(
            engine=EngineConfig(
                max_metric_calls=args.max_evals,
                parallel=False,
                max_workers=1,
                run_dir=str(output / "gepa-state"),
                seed=0,
                use_cloudpickle=False,
                max_candidate_proposals=3,
            ),
            reflection=ReflectionConfig(
                reflection_lm=reflect, reflection_minibatch_size=3
            ),
        )
        try:
            result = search(evaluate, splits, optimize_anything, config)
        except BaseException as exc:
            status = json.loads(
                (output / "run_status.json").read_text(encoding="utf-8")
            )
            if status["status"] == "running":
                record_status(
                    "interrupted"
                    if isinstance(exc, KeyboardInterrupt)
                    else "optimization_error",
                    error_type=type(exc).__name__,
                )
            raise
        (output / "result.json").write_text(
            json.dumps(result.to_dict(), default=str, indent=2) + "\n", encoding="utf-8"
        )
        candidate = result.best_candidate
        if not isinstance(candidate, str):
            raise TypeError("Expected a single string candidate from GEPA")
        (output / "best_prompt.txt").write_text(candidate + "\n", encoding="utf-8")
    else:
        candidate = args.candidate.read_text(encoding="utf-8").strip()
        scores = {"seed": [], "candidate": []}
        identical = candidate == DECISION_INSTRUCTIONS.strip()
        with (output / "heldout.jsonl").open("w", encoding="utf-8") as stream:
            for example in splits["test"]:
                previous = None
                for name, prompt in (
                    ("seed", DECISION_INSTRUCTIONS),
                    ("candidate", candidate),
                ):
                    reused = name == "candidate" and identical
                    if reused:
                        score, feedback = previous
                    else:
                        score, feedback = evaluate(prompt, example)
                        previous = (score, feedback)
                    scores[name].append(score)
                    stream.write(
                        json.dumps(
                            {
                                "id": example.id,
                                "prompt": name,
                                "score": score,
                                "reused_identical_prompt": reused,
                                **feedback,
                            }
                        )
                        + "\n"
                    )
        print(
            json.dumps(
                {name: sum(values) / len(values) for name, values in scores.items()}
            )
        )
    record_status("completed")
    print(f"Artifacts: {output}")


if __name__ == "__main__":
    main()
