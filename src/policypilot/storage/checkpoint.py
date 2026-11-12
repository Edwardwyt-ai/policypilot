"""Versioned task checkpoints with immutable snapshot artifacts."""

from policypilot.state import PolicyPilotState
from policypilot.storage.database import Database


class SqlCheckpointStore:
    def __init__(self, database: Database):
        self.database = database

    def save(self, task_id: str, state: PolicyPilotState):
        self.database.put(
            "checkpoints",
            task_id,
            {
                "schema_version": 1,
                "task_id": task_id,
                "state": state.model_dump(mode="json"),
            },
        )
        return f"{self.database.engine.dialect.name}:checkpoints:{task_id}"

    def load(self, task_id: str) -> PolicyPilotState | None:
        payload = self.database.get("checkpoints", task_id)
        if payload is None:
            return None
        if payload.get("schema_version") != 1 or payload.get("task_id") != task_id:
            raise ValueError("Checkpoint identity or schema mismatch")
        return PolicyPilotState.model_validate(payload["state"])

    def delete(self, task_id: str) -> None:
        self.database.delete("checkpoints", task_id)
