"""Incremental procedural experience mining from episodes and saved simulations."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from policypilot.memory.episodic import LocalEpisodeEmbedder, sanitize_episode_text
from policypilot.skills.evolution_models import (
    EvidenceSource,
    EvolutionConfig,
    Extraction,
    digest,
)


def episode_source(
    episode,
    *,
    success=None,
    attribution="unknown",
    failure_mode="",
    scenario_group=None,
) -> EvidenceSource:
    trace_id, _, task_id = (episode.trajectory_ref or "").rpartition(":")
    observations = [
        episode.situation,
        *episode.salient_state,
        *episode.tool_pattern,
        *episode.critical_actions,
        episode.failure_recovery,
        episode.lesson,
    ]
    return EvidenceSource(
        kind="episode",
        source_id=episode.episode_id,
        trace_id=trace_id or episode.episode_id,
        task_id=task_id or "unknown-task",
        task_type=episode.target or episode.intent,
        success=success,
        attribution=attribution,
        failure_mode=failure_mode,
        scenario_group=scenario_group,
        observations=[sanitize_episode_text(x, 400) for x in observations if x.strip()][
            :24
        ],
    )


def latest_skill_trace(simulation) -> dict:
    from tau2.data_model.message import AssistantMessage

    for message in reversed(simulation.get_messages()):
        if isinstance(message, AssistantMessage):
            data = (message.raw_data or {}).get("policypilot_v1")
            if data:
                return data
    return {}


def trajectory_source(
    simulation,
    *,
    task_type: str,
    attribution="unknown",
    failure_mode: str = "",
    source_path: str | None = None,
    scenario_group: str | None = None,
) -> EvidenceSource:
    """Project observed behavior, excluding raw parameters, tool payloads and hidden labels."""
    from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolMessage

    data = latest_skill_trace(simulation)
    events = []
    call_names = {}
    for message in simulation.get_messages():
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls or []:
                call_names[call.id] = call.name
                events.append(f"Agent called {call.name}")
        elif isinstance(message, (ToolMessage, MultiToolMessage)):
            replies = (
                message.tool_messages
                if isinstance(message, MultiToolMessage)
                else [message]
            )
            for reply in replies:
                if reply.id in call_names:
                    result = "error" if reply.error else "returned"
                    events.append(f"{call_names[reply.id]}: {result}")
    events.extend(f"Route: {x}" for x in (data.get("route_trace") or [])[-6:])
    errors = data.get("error_category_counts") or {}
    if not failure_mode and errors:
        failure_mode = max(sorted(errors), key=errors.get)
    # Preserve the initial approach and the final recovery when the sequence is long.
    events = events if len(events) <= 24 else events[:8] + events[-16:]
    skills = data.get("skills") or {}
    trace_id = (data.get("provenance") or {}).get("run_id") or simulation.id
    return EvidenceSource(
        kind="trajectory",
        source_id=simulation.id,
        source_path=source_path,
        scenario_group=scenario_group,
        trace_id=trace_id,
        task_id=simulation.task_id,
        task_type=task_type,
        success=(
            simulation.reward_info.reward == 1.0 if simulation.reward_info else None
        ),
        active_skills=skills.get("activated_versions")
        or {
            x["skill_id"]: x["version"]
            for x in skills.get("events", [])
            if x["event"] == "phase_guidance_used"
        },
        attribution=attribution,
        failure_mode=failure_mode,
        observations=[sanitize_episode_text(x, 400) for x in events],
    )


class ExperienceStore:
    """Local SQLite catalog for the offline pipeline, using atomic batch item writes."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            for sql in (
                "CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, revision TEXT, payload TEXT)",
                "CREATE TABLE IF NOT EXISTS clusters (id TEXT PRIMARY KEY, task_type TEXT, behavior TEXT, failure TEXT, vector_space TEXT, vector TEXT)",
                "CREATE INDEX IF NOT EXISTS cluster_lookup ON clusters(task_type, behavior, failure, vector_space)",
                "CREATE TABLE IF NOT EXISTS experiences (id TEXT PRIMARY KEY, source_id TEXT, cluster_id TEXT, payload TEXT)",
                "CREATE INDEX IF NOT EXISTS experience_source ON experiences(source_id)",
                "CREATE INDEX IF NOT EXISTS experience_cluster ON experiences(cluster_id)",
            ):
                db.execute(sql)

    @contextmanager
    def transaction(self, *, write=True):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def attribution_sources(self, *, after: int = 0, limit: int = 100):
        with self.transaction(write=False) as db:
            rows = db.execute(
                "SELECT rowid, payload FROM sources WHERE rowid>? ORDER BY rowid LIMIT ?",
                (after, limit),
            ).fetchall()
        return [(row[0], EvidenceSource.model_validate_json(row[1])) for row in rows]

    def cluster_page(self, after: int, limit: int):
        with self.transaction(write=False) as db:
            return list(
                db.execute(
                    "SELECT rowid, id FROM clusters WHERE rowid>? ORDER BY rowid LIMIT ?",
                    (after, limit),
                )
            )

    def members(self, cluster_id: str):
        with self.transaction(write=False) as db:
            return [
                (
                    row["id"],
                    EvidenceSource.model_validate_json(row["source"]),
                    json.loads(row["payload"]),
                )
                for row in db.execute(
                    "SELECT e.id, s.payload AS source, e.payload FROM experiences e "
                    "JOIN sources s ON s.id=e.source_id WHERE e.cluster_id=? ORDER BY e.id",
                    (cluster_id,),
                )
            ]


class Discovery:
    def __init__(
        self, store, extract, *, embedder=None, config=None, extractor_version="1"
    ):
        self.store = store
        self.extract = extract
        self.embedder = embedder or LocalEpisodeEmbedder()
        self.config = config or EvolutionConfig()
        self.extractor_version = extractor_version
        self.changed_clusters: set[str] = set()

    def ingest(self, sources):
        """Consume a bounded source page. Return the count of inputs consumed."""
        self.changed_clusters.clear()
        consumed = 0
        calls = 0
        from itertools import islice

        for source in islice(sources, self.config.batch_size):
            if calls >= self.config.max_extraction_calls:
                break
            key = f"{source.kind}:{source.source_id}"
            revision = digest(
                [
                    self.extractor_version,
                    source.model_dump(mode="json", exclude={"source_path"}),
                ]
            )
            with self.store.transaction(write=False) as db:
                old = db.execute(
                    "SELECT revision FROM sources WHERE id=?", (key,)
                ).fetchone()
            if old and old[0] == revision:
                consumed += 1
                continue
            patterns = []
            if len(source.observations) >= 2:
                calls += 1
                extracted = Extraction.model_validate(self.extract(source))
                patterns = [
                    item
                    for item in extracted.patterns
                    if len(set(item.steps)) >= 2
                    and all(
                        0 <= i < len(source.observations) for i in item.evidence_indexes
                    )
                ]
            batch = (
                self.embedder.embed([" ".join(p.steps) for p in patterns])
                if patterns
                else None
            )
            if batch and len(batch.vectors) != len(patterns):
                raise ValueError("Embedding batch does not match extracted patterns")
            with self.store.transaction() as db:
                current = db.execute(
                    "SELECT revision FROM sources WHERE id=?", (key,)
                ).fetchone()
                if current != old:
                    if current and current[0] == revision:
                        consumed += 1
                        continue
                    raise RuntimeError(f"Source changed during extraction: {key}")
                self.changed_clusters.update(
                    row[0]
                    for row in db.execute(
                        "SELECT cluster_id FROM experiences WHERE source_id=?", (key,)
                    )
                )
                db.execute("DELETE FROM experiences WHERE source_id=?", (key,))
                db.execute(
                    "INSERT OR REPLACE INTO sources VALUES (?, ?, ?)",
                    (key, revision, source.model_dump_json()),
                )
                if batch:
                    for i, (pattern, vector) in enumerate(
                        zip(patterns, batch.vectors, strict=True)
                    ):
                        space = f"{batch.model}:{batch.version}:{len(vector)}"
                        cluster_id = self._cluster(db, source, pattern, vector, space)
                        self.changed_clusters.add(cluster_id)
                        db.execute(
                            "INSERT INTO experiences VALUES (?, ?, ?, ?)",
                            (
                                digest([key, revision, i]),
                                key,
                                cluster_id,
                                pattern.model_dump_json(),
                            ),
                        )
                db.execute(
                    "DELETE FROM clusters WHERE id NOT IN (SELECT cluster_id FROM experiences)"
                )
            consumed += 1
        return consumed

    def _cluster(self, db, source, pattern, vector, space):
        # A task bucket and a behavior key are required before semantic similarity.
        key = (source.task_type, pattern.behavior_key, source.failure_mode, space)
        rows = db.execute(
            "SELECT id, vector FROM clusters WHERE task_type=? AND vector_space=? "
            "ORDER BY (behavior=? AND failure=?) DESC, rowid DESC LIMIT ?",
            (key[0], space, key[1], key[2], self.config.cluster_candidates),
        )
        ranked = [
            (
                sum(
                    a * b
                    for a, b in zip(vector, json.loads(row["vector"]), strict=True)
                ),
                row["id"],
            )
            for row in rows
        ]
        score, match = max(ranked, default=(-1, None))
        if match is not None and score >= self.config.similarity_min:
            return match
        cluster_id = digest([*key, vector])
        db.execute(
            "INSERT OR IGNORE INTO clusters VALUES (?, ?, ?, ?, ?, ?)",
            (cluster_id, *key, json.dumps(vector)),
        )
        return cluster_id
