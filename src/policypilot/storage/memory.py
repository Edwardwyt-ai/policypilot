"""Transactional profiles and per-user episode records."""

from policypilot.memory.models import EpisodeMemory, UserProfile, utc_now
from policypilot.memory.store import JsonMemoryStore
from policypilot.storage.database import Database, StorageConflictError


class SqlMemoryStore:
    subject_key = staticmethod(JsonMemoryStore.subject_key)

    def __init__(self, database: Database, *, max_episodes_per_user: int = 100):
        self.database = database
        self.max_episodes_per_user = max_episodes_per_user

    def load_profile(self, user_id: str) -> UserProfile:
        key = self.subject_key(user_id)
        value = self.database.get("profiles", key)
        return (
            UserProfile.model_validate(value) if value else UserProfile(subject_key=key)
        )

    def save_profile(self, profile: UserProfile) -> None:
        db = self.database
        table = db.objects
        with db.connect(lock=f"profile:{profile.subject_key}") as conn:
            row = conn.execute(
                db.sa.select(table.c.payload).where(
                    table.c.namespace == "profiles", table.c.key == profile.subject_key
                )
            ).first()
            if row and db.decode(row[0])["revision"] >= profile.revision:
                raise StorageConflictError(
                    "Profile changed concurrently; reload before merging"
                )
            profile.updated_at = utc_now()
            db.write(
                conn,
                "profiles",
                profile.subject_key,
                db.encode(profile.model_dump(mode="json")),
            )

    def load_episodes(self, user_id: str) -> list[EpisodeMemory]:
        return self.load_subject_episodes(self.subject_key(user_id))

    def load_subject_episodes(self, subject_key: str) -> list[EpisodeMemory]:
        return sorted(
            [
                EpisodeMemory.model_validate(value)
                for _, value in self.database.list_objects(f"episodes:{subject_key}")
            ],
            key=lambda e: e.updated_at,
        )

    def upsert_episode(self, episode: EpisodeMemory) -> None:
        namespace = f"episodes:{episode.subject_key}"
        db = self.database
        table = db.objects
        with db.connect(lock=namespace) as conn:
            rows = conn.execute(
                db.sa.select(table.c.key, table.c.payload).where(
                    table.c.namespace == namespace
                )
            ).all()
            existing = {
                key: EpisodeMemory.model_validate(db.decode(payload))
                for key, payload in rows
            }
            if episode.episode_id in existing:
                episode.created_at = existing[episode.episode_id].created_at
            existing[episode.episode_id] = episode
            db.write(
                conn,
                namespace,
                episode.episode_id,
                db.encode(episode.model_dump(mode="json")),
            )
            ordered = sorted(
                existing.values(), key=lambda item: item.updated_at, reverse=True
            )
            for item in ordered[self.max_episodes_per_user :]:
                conn.execute(
                    table.delete().where(
                        table.c.namespace == namespace, table.c.key == item.episode_id
                    )
                )
