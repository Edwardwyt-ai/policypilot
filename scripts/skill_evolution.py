"""Explicit offline commands for PolicyPilot Skill evolution."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

from policypilot.config import PolicyPilotConfig
from policypilot.llm_runtime import LLMRuntime
from policypilot.memory.embeddings import OllamaEpisodeEmbedder
from policypilot.memory.models import EpisodeMemory
from policypilot.model_routing import resolve_model_routing
from policypilot.skills.evolution import (
    Evolution,
    declining_groups,
    detect_signals,
    extract_experience,
)
from policypilot.skills.evolution_models import EvolutionConfig
from policypilot.skills.experience import (
    Discovery,
    ExperienceStore,
    episode_source,
    trajectory_source,
)
from policypilot.skills.library import SkillLibrary, preview
from policypilot.skills.loader import SkillLoader
from policypilot.skills.skill_evaluation import (
    EvaluationPlan,
    PromotionPolicy,
    evaluate,
    from_simulation,
    run_configuration_id,
)
from tau2.data_model.simulation import SimulationRun


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def simulations(path):
    if path.is_dir():
        paths = sorted(path.glob("tasks/*/results.json"))
    else:
        paths = [path]
    for file in paths:
        for item in read(file).get("simulations", []):
            yield file, SimulationRun.model_validate(item)


def configured_runtime():
    load_dotenv(ROOT / ".env")
    model = os.getenv("POLICYPILOT_LIGHT_MODEL") or os.getenv("MODEL")
    if not model:
        raise ValueError(
            "Configure POLICYPILOT_LIGHT_MODEL before requesting model operations"
        )
    return LLMRuntime(resolve_model_routing(model, PolicyPilotConfig()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=ROOT / "data/storage/skill-evolution"
    )
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    inputs = ingest.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--episodes", type=Path)
    inputs.add_argument("--postgres-user")
    inputs.add_argument("--trajectories", type=Path)
    ingest.add_argument("--task-type", help="Required for trajectory input")
    ingest.add_argument("--offset", type=int, default=0)
    ingest.add_argument(
        "--dense", action="store_true", help="Use the configured local Ollama embedder"
    )
    ingest.add_argument(
        "--reviews", type=Path, help="Reviewed annotations keyed by trace or episode ID"
    )
    discover = sub.add_parser("discover")
    discover.add_argument("--after-rowid", type=int, default=0)
    discover.add_argument("--cluster", action="append", default=[])
    discover.add_argument("--windows", type=Path)
    discover.add_argument("--review-cluster", action="append", default=[])
    propose = sub.add_parser("propose")
    propose.add_argument("--after-rowid", type=int, default=0)
    propose.add_argument("--cluster", action="append", default=[])
    propose.add_argument("--windows", type=Path)
    propose.add_argument(
        "--trace-index", type=Path, help="JSON mapping trace IDs to saved results files"
    )
    propose.add_argument("--review-cluster", action="append", default=[])
    for name in ("evaluate", "promote"):
        command = sub.add_parser(name)
        command.add_argument("candidate")
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--baseline", type=Path, required=True)
        command.add_argument("--candidate-results", type=Path, required=True)
        command.add_argument("--policy", type=Path)
    sub.add_parser("configuration-id").add_argument("run_dir", type=Path)
    sub.add_parser("active")
    sub.add_parser("rollback").add_argument("release_id")
    args = parser.parse_args()

    library = SkillLibrary(args.root / "library.sqlite3")
    config = (
        EvolutionConfig.model_validate(read(args.config))
        if args.config
        else EvolutionConfig()
    )
    if args.command == "configuration-id":
        print(run_configuration_id(read(args.run_dir / "config.json")))
        return
    if args.command == "active":
        release = library.active()
        print(json.dumps({"id": release.id, **release.model_dump(mode="json")}))
        return
    if args.command == "rollback":
        print(library.rollback(args.release_id).id)
        return
    if args.command in {"evaluate", "promote"}:
        base = library.active()
        candidate = library.candidate(args.candidate)
        plan = EvaluationPlan.model_validate(read(args.plan))
        builtin_ids = {item.name for item in SkillLoader(release=base).base_metadata()}
        if set(plan.builtin_ids) != builtin_ids:
            raise ValueError(
                "Evaluation plan must identify the current built-in skills"
            )
        policy = (
            PromotionPolicy.model_validate(read(args.policy))
            if args.policy
            else PromotionPolicy()
        )
        observations = []
        for arm, source in (
            ("baseline", args.baseline),
            ("candidate", args.candidate_results),
        ):
            if not source.is_dir():
                parser.error(
                    "Evaluation requires evaluate_v1 run directories with config.json"
                )
            configuration_id = run_configuration_id(read(source / "config.json"))
            observations.extend(
                from_simulation(
                    simulation, path, arm=arm, configuration_id=configuration_id
                )
                for path, simulation in simulations(source)
            )
        if args.command == "promote":
            print(
                library.promote(candidate.candidate_id, plan, observations, policy).id
            )
        else:
            report = evaluate(
                candidate,
                base,
                preview(base, candidate, builtin_ids),
                plan,
                observations,
                policy,
            )
            print(report.model_dump_json(indent=2))
        return

    store = ExperienceStore(args.root / "experience.sqlite3")
    if args.command == "ingest":
        reviews = read(args.reviews) if args.reviews else {}
        if args.episodes or args.postgres_user:
            if args.episodes:
                episodes = (
                    EpisodeMemory.model_validate(item) for item in read(args.episodes)
                )
            else:
                from policypilot.storage.database import (
                    get_service_database,
                    load_storage_environment,
                )
                from policypilot.storage.memory import SqlMemoryStore

                load_storage_environment()
                episodes = SqlMemoryStore(get_service_database()).load_episodes(
                    args.postgres_user
                )
            sources = (
                episode_source(episode, **reviews.get(episode.episode_id, {}))
                for episode in episodes
            )
        else:
            if not args.task_type:
                parser.error("--task-type is required for trajectories")
            sources = (
                trajectory_source(
                    simulation,
                    task_type=args.task_type,
                    source_path=str(path.resolve()),
                    **reviews.get(simulation.id, {}),
                )
                for path, simulation in simulations(args.trajectories)
            )
        runtime = configured_runtime()
        discovery = Discovery(
            store,
            lambda source: extract_experience(runtime, source),
            config=config,
            embedder=OllamaEpisodeEmbedder() if args.dense else None,
            extractor_version="procedural-v1:" + runtime.routing.light_model,
        )
        consumed = discovery.ingest(islice(sources, args.offset, None))
        print(
            json.dumps(
                {
                    "consumed": consumed,
                    "next_offset": args.offset + consumed,
                    "changed_clusters": sorted(discovery.changed_clusters),
                }
            )
        )
        return

    alerts = None
    if args.windows:
        windows = read(args.windows)
        alerts = declining_groups(windows["previous"], windows["recent"], config)
    page = store.cluster_page(args.after_rowid, config.cluster_scan_limit)
    signals = list(
        detect_signals(
            store,
            config,
            cluster_ids=args.cluster or [row["id"] for row in page],
            rate_alerts=alerts,
            redundancy_review_ids=args.review_cluster,
        )
    )
    if args.command == "discover":
        print(
            json.dumps(
                {
                    "signals": [vars(signal) for signal in signals],
                    "next_rowid": page[-1]["rowid"] if page else args.after_rowid,
                }
            )
        )
    elif signals:
        loader = SkillLoader(release=library.active())
        evolution = Evolution(
            store, library, loader, configured_runtime(), config=config
        )
        trace_index = read(args.trace_index) if args.trace_index else {}

        def trace_excerpt(trace_id):
            path = trace_index.get(trace_id)
            if not path:
                return ""
            for _, simulation in simulations(Path(path)):
                projected = trajectory_source(simulation, task_type="unclassified")
                if projected.trace_id == trace_id or simulation.id == trace_id:
                    return " | ".join(projected.observations)
            return ""

        for candidate in evolution.propose(
            signals, trace_reader=trace_excerpt if trace_index else None
        ):
            print(candidate.model_dump_json(exclude={"evidence_snapshot"}))


if __name__ == "__main__":
    main()
