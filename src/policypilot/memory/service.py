"""Agent-instance lifecycle facade for external long-term memory."""
from __future__ import annotations

import uuid

from policypilot.memory.context import render_memory_context
from policypilot.memory.episodic import (
    EpisodeFormer,
    EpisodeRetriever,
    EpisodeValueGate,
    LLMEpisodeExtractor,
    LocalEpisodeEmbedder,
)
from policypilot.memory.models import MemoryMetrics, MemorySnapshot, PreferenceCandidate
from policypilot.memory.profile import ProfileMemoryManager
from policypilot.memory.store import JsonMemoryStore
from policypilot.state import PolicyPilotState
from tau2.data_model.message import AssistantMessage


class MemoryService:
    def __init__(self, store: JsonMemoryStore, profile_manager: ProfileMemoryManager, *, max_recalled_episodes: int = 3, max_context_chars: int = 1800, episode_extractor: LLMEpisodeExtractor | None = None):
        self.store = store
        self.profile_manager = profile_manager
        self.retriever = EpisodeRetriever()
        self.former = EpisodeFormer()
        self.episode_extractor = episode_extractor
        self.max_recalled_episodes = max_recalled_episodes
        self.max_context_chars = max_context_chars
        self.metrics = MemoryMetrics()
        self.user_id: str | None = None
        self.subject_key: str | None = None
        self.episode_id = f"episode_{uuid.uuid4().hex}"
        self.snapshot = MemorySnapshot()
        self.pending_candidates: list[PreferenceCandidate] = []
        self.episode_finalized = False

    def bind(self, user_id: str, *, query: str = "") -> None:
        if self.user_id == user_id:
            self.refresh(query)
            return
        if self.user_id is not None:
            return
        self.user_id = user_id
        try:
            self.subject_key = self.store.subject_key(user_id)
            profile = self.store.load_profile(user_id)
            episodes = self.store.load_episodes(user_id)
        except (OSError, ValueError):
            self.metrics.storage_failures += 1
            self.user_id = None
            self.subject_key = None
            return
        self.metrics.profile_reads += 1
        self.metrics.episode_reads += 1
        self.snapshot = MemorySnapshot(profile=profile, episodes=self.retriever.retrieve(episodes, query, limit=self.max_recalled_episodes))
        self.metrics.episode_retrievals += len(self.snapshot.episodes)
        if self.pending_candidates:
            self._apply(self.pending_candidates)
            self.pending_candidates = []

    def observe_user(self, message: str, task_context: str) -> None:
        candidates, called, failed = self.profile_manager.form_candidates(message, task_context)
        self.metrics.profile_candidates += len(candidates)
        self.metrics.extraction_calls += int(called)
        self.metrics.extraction_failures += int(failed)
        if not candidates:
            return
        if self.user_id is None:
            self.pending_candidates.extend(candidates)
            return
        self._apply(candidates)

    def _apply(self, candidates: list[PreferenceCandidate]) -> None:
        if self.user_id is None:
            return
        try:
            profile, accepted, rejected, changed = self.profile_manager.apply(
                self.user_id, candidates
            )
        except (OSError, ValueError):
            self.metrics.storage_failures += 1
            return
        self.metrics.profile_accepted += accepted
        self.metrics.profile_rejected += rejected
        self.metrics.profile_writes += int(changed)
        self.snapshot.profile = profile

    def refresh(self, query: str) -> None:
        if self.user_id is None:
            return
        try:
            episodes = self.store.load_episodes(self.user_id)
        except (OSError, ValueError):
            self.metrics.storage_failures += 1
            return
        self.snapshot.episodes = self.retriever.retrieve(episodes, query, limit=self.max_recalled_episodes)
        self.metrics.episode_retrievals += len(self.snapshot.episodes)

    def recall(self, query: str, *, trigger: str) -> None:
        if trigger not in {"NEW_GOAL", "MAJOR_SUBGOAL_CHANGE", "RECOVERY_ENTERED"}:
            return
        self.metrics.recall_events.append(trigger)
        self.refresh(query)

    def context(self) -> str:
        rendered = render_memory_context(self.snapshot, max_chars=self.max_context_chars)
        self.metrics.context_chars = len(rendered)
        return rendered

    def planner_hints(self) -> list[str]:
        hints: list[str] = []
        if self.snapshot.profile is not None:
            hints.extend(
                f"{item.scope}.{item.aspect}: {item.polarity} {item.value}"
                for item in self.snapshot.profile.active_preferences()
            )
        hints.extend(
            f"prior episode: {item.objective}; {item.lesson}"
            for item in self.snapshot.episodes
        )
        return hints

    def record_episode(self, state: PolicyPilotState, final_message: AssistantMessage, *, evaluation: dict | None = None) -> None:
        if self.subject_key is None or self.episode_finalized:
            return
        if not EpisodeValueGate.accept(state, evaluation):
            self.metrics.episode_value_rejected += 1
            return
        extracted = None
        if self.episode_extractor is not None:
            source = self.former.source(
                state=state, final_message=final_message, evaluation=evaluation
            )
            try:
                extracted = self.episode_extractor.extract(source)
                self.metrics.extraction_calls += 1
            except Exception:
                self.metrics.extraction_calls += 1
                self.metrics.extraction_failures += 1
        try:
            episode = self.former.form(
                episode_id=self.episode_id,
                subject_key=self.subject_key,
                state=state,
                final_message=final_message,
                extracted=extracted,
                evaluation=evaluation,
            )
        except ValueError:
            self.metrics.extraction_failures += 1
            episode = self.former.form(
                episode_id=self.episode_id,
                subject_key=self.subject_key,
                state=state,
                final_message=final_message,
                evaluation=evaluation,
            )
        if episode is None:
            return
        episode.embedding = LocalEpisodeEmbedder.embed(
            " ".join(
                [
                    episode.situation,
                    episode.goal_pattern,
                    episode.objective,
                    episode.target or "",
                    episode.lesson,
                ]
            )
        )
        episode.embedding_model = LocalEpisodeEmbedder.model
        episode.embedding_version = LocalEpisodeEmbedder.version
        try:
            self.store.upsert_episode(episode)
        except (OSError, ValueError):
            self.metrics.storage_failures += 1
            return
        self.metrics.episode_writes += 1
        self.episode_finalized = True
