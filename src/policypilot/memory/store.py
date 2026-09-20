"""Deterministic JSON persistence for Memory V1."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from policypilot.memory.models import EpisodeMemory, UserProfile, utc_now


class JsonMemoryStore:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, root: str | Path, *, max_episodes_per_user: int = 100):
        self.root = Path(root)
        self.max_episodes_per_user = max_episodes_per_user

    @staticmethod
    def subject_key(user_id: str) -> str:
        normalized = user_id.strip().lower()
        if not normalized:
            raise ValueError("user_id must not be empty")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _lock(cls, path: Path) -> threading.RLock:
        key = str(path.resolve())
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    def _profile_path(self, subject_key: str) -> Path:
        return self.root / "profiles" / f"{subject_key}.json"

    def _episodes_path(self, subject_key: str) -> Path:
        return self.root / "episodes" / f"{subject_key}.json"

    @staticmethod
    def _read(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _atomic_write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def load_profile(self, user_id: str) -> UserProfile:
        key = self.subject_key(user_id)
        path = self._profile_path(key)
        with self._lock(path):
            payload = self._read(path, None)
        return UserProfile(subject_key=key) if payload is None else UserProfile.model_validate(payload)

    def save_profile(self, profile: UserProfile) -> None:
        path = self._profile_path(profile.subject_key)
        profile.updated_at = utc_now()
        with self._lock(path):
            self._atomic_write(path, profile.model_dump(mode="json"))

    def load_episodes(self, user_id: str) -> list[EpisodeMemory]:
        key = self.subject_key(user_id)
        path = self._episodes_path(key)
        with self._lock(path):
            payload = self._read(path, [])
        return [EpisodeMemory.model_validate(item) for item in payload]

    def upsert_episode(self, episode: EpisodeMemory) -> None:
        path = self._episodes_path(episode.subject_key)
        with self._lock(path):
            items = [EpisodeMemory.model_validate(item) for item in self._read(path, [])]
            for index, existing in enumerate(items):
                if existing.episode_id == episode.episode_id:
                    episode.created_at = existing.created_at
                    episode.updated_at = utc_now()
                    items[index] = episode
                    break
            else:
                items.append(episode)
            items = sorted(items, key=lambda item: item.updated_at)[-self.max_episodes_per_user :]
            self._atomic_write(path, [item.model_dump(mode="json") for item in items])
