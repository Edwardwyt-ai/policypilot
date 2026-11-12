"""Copy legacy memories/checkpoints into configured SQL storage, preserving sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policypilot.memory.models import EpisodeMemory, UserProfile  # noqa: E402
from policypilot.state import PolicyPilotState  # noqa: E402
from policypilot.storage.database import (  # noqa: E402
    Database,
    load_storage_environment,
)
from policypilot.storage.memory import SqlMemoryStore  # noqa: E402


def migrate(database: Database, memory_dir: Path, checkpoint_dir: Path) -> dict:
    counts = {"profiles": 0, "episodes": 0, "checkpoints": 0, "skipped": 0}
    store = SqlMemoryStore(database)
    for path in sorted((memory_dir / "profiles").glob("*.json")):
        profile = UserProfile.model_validate_json(path.read_text(encoding="utf-8"))
        if database.get("profiles", profile.subject_key) is not None:
            counts["skipped"] += 1
            continue
        store.save_profile(profile)
        counts["profiles"] += 1
    for path in sorted((memory_dir / "episodes").glob("*.json")):
        for value in json.loads(path.read_text(encoding="utf-8")):
            episode = EpisodeMemory.model_validate(value)
            namespace = f"episodes:{episode.subject_key}"
            if database.get(namespace, episode.episode_id) is not None:
                counts["skipped"] += 1
                continue
            store.upsert_episode(episode)
            counts["episodes"] += 1
    for path in sorted(checkpoint_dir.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or "state" not in value:
            raise ValueError(f"Unsupported checkpoint: {path}")
        PolicyPilotState.model_validate(value["state"])
        if database.get("checkpoints", value["task_id"]) is not None:
            counts["skipped"] += 1
            continue
        database.put("checkpoints", value["task_id"], value)
        counts["checkpoints"] += 1
    # Verify every imported object and its artifact before reporting success.
    database.verify()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument(
        "--memory-dir", type=Path, default=ROOT / "data/policypilot_memory"
    )
    parser.add_argument(
        "--checkpoint-dir", type=Path, default=ROOT / "data/policypilot_checkpoints"
    )
    args = parser.parse_args()
    load_storage_environment()
    print(
        json.dumps(
            migrate(Database(args.storage_root), args.memory_dir, args.checkpoint_dir),
            indent=2,
        )
    )
