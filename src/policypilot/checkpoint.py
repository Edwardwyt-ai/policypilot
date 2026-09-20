"""Versioned local checkpoints for resuming one unfinished PolicyPilot task."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from policypilot.state import PolicyPilotState


class JsonCheckpointStore:
    schema_version = 1

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def _safe_key(task_id: str) -> str:
        key = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id).strip("._")
        if not key:
            raise ValueError("Checkpoint task_id must contain a safe character.")
        return key

    def path_for(self, task_id: str) -> Path:
        return self.root / f"{self._safe_key(task_id)}.json"

    def save(self, task_id: str, state: PolicyPilotState) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(task_id)
        temporary = target.with_suffix(".tmp")
        payload = {
            "schema_version": self.schema_version,
            "task_id": task_id,
            "state": state.model_dump(mode="json"),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, target)
        return target

    def load(self, task_id: str) -> PolicyPilotState | None:
        path = self.path_for(task_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != self.schema_version:
            raise ValueError("Unsupported checkpoint schema version.")
        if payload.get("task_id") != task_id:
            raise ValueError("Checkpoint task identity mismatch.")
        return PolicyPilotState.model_validate(payload["state"])

    def delete(self, task_id: str) -> None:
        self.path_for(task_id).unlink(missing_ok=True)
