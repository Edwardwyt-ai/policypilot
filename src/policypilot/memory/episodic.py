"""Privacy-bounded episodic formation and lexical retrieval."""
from __future__ import annotations

import hashlib
import json
import math
import re

from pydantic import BaseModel, Field

from policypilot.llm_runtime import LLMRuntime
from policypilot.memory.models import EpisodeMemory
from policypilot.state import PolicyPilotState
from tau2.data_model.message import AssistantMessage, SystemMessage, UserMessage

EPISODE_EXTRACTION_PROMPT = """
At evaluator finalization only, extract one privacy-safe reusable episode from
the compact event summary. Do not copy identifiers, contact data, live state,
timestamps, or policy text. critical_actions must be a subset of tool_pattern.
Keep every field terse.
""".strip()


class EpisodeExtraction(BaseModel):
    situation: str = Field(max_length=240)
    goal_pattern: str = Field(max_length=240)
    salient_state: list[str] = Field(default_factory=list, max_length=4)
    critical_actions: list[str] = Field(default_factory=list, max_length=6)
    outcome: str = Field(max_length=120)
    failure_recovery: str = Field(default="", max_length=240)
    lesson: str = Field(max_length=320)


class LLMEpisodeExtractor:
    def __init__(self, runtime: LLMRuntime):
        self.runtime = runtime

    def extract(self, source: dict) -> EpisodeExtraction:
        return self.runtime.call_structured(
            "episode_extractor",
            [
                SystemMessage(role="system", content=EPISODE_EXTRACTION_PROMPT),
                UserMessage.text(json.dumps(source, ensure_ascii=False, default=str)),
            ],
            EpisodeExtraction,
        )

_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_IDENTIFIER = re.compile(r"\b(?:user|account|card|transaction|referral)[ _-]?id\s*[:=]?\s*\S+", re.I)
_LONG_NUMBER = re.compile(r"\b\d{5,}\b")
_NUMBER = re.compile(r"(?:[$€£]\s*)?\b\d+(?:[.,]\d+)?%?\b")
_LIVE = re.compile(
    r"\b(balance|current status|transaction status|referral status|"
    r"verification code|eligibility result|rejected|denied|pending|completed|"
    r"failed|in_progress)\b|余额|当前状态|交易状态|推荐状态|验证码|资格结果|"
    r"拒绝|待处理|已完成|失败",
    re.I,
)

def sanitize_episode_text(value: str, limit: int = 320) -> str:
    text = _EMAIL.sub("[redacted]", value)
    text = _IDENTIFIER.sub("[redacted]", text)
    text = _LONG_NUMBER.sub("[redacted]", text)
    text = _NUMBER.sub("[number-omitted]", text)
    text = _LIVE.sub("[live-state-omitted]", text)
    return " ".join(text.split())[:limit]

class EpisodeFormer:
    def source(
        self,
        *,
        state: PolicyPilotState,
        final_message: AssistantMessage,
        evaluation: dict | None = None,
    ) -> dict:
        outcome = (
            "TOOL_PENDING"
            if final_message.tool_calls
            else "ACTION_REQUESTED"
            if state.open_needs()
            else "ANSWERED"
            if final_message.content
            else "INCOMPLETE"
        )
        return {
            "objective": sanitize_episode_text(state.goal.objective or ""),
            "target": state.goal.target,
            "intent": state.intent,
            "preference_aspects": sorted({item.aspect for item in state.goal.criteria}),
            "information_sources": sorted({need.source for need in state.information_needs}),
            "tool_pattern": [record.name for record in state.tool_history if not record.blocked][-12:],
            "outcome": outcome,
            "errors": sorted({item.category.value for item in state.control.error_records}),
            "evaluation": evaluation or {},
        }

    def form(self, *, episode_id: str, subject_key: str, state: PolicyPilotState, final_message: AssistantMessage, extracted: EpisodeExtraction | None = None, evaluation: dict | None = None) -> EpisodeMemory | None:
        if not state.goal.objective:
            return None
        if final_message.tool_calls:
            outcome = "TOOL_PENDING"
        elif state.open_needs():
            outcome = "ACTION_REQUESTED"
        elif final_message.content:
            outcome = "ANSWERED"
        else:
            outcome = "INCOMPLETE"
        source = self.source(state=state, final_message=final_message, evaluation=evaluation)
        sources = source["information_sources"]
        tool_pattern = [record.name for record in state.tool_history if not record.blocked][-12:]
        aspects = sorted({item.aspect for item in state.goal.criteria})
        lesson_parts = [
            f"goal target={state.goal.target or 'unspecified'}",
            f"used sources={','.join(sources) or 'none'}",
            f"tool sequence={','.join(tool_pattern) or 'none'}",
            f"outcome={outcome}",
        ]
        if extracted is not None and not set(extracted.critical_actions).issubset(set(tool_pattern)):
            raise ValueError("Episode critical actions are not grounded in observed tools.")
        return EpisodeMemory(
            episode_id=episode_id,
            subject_key=subject_key,
            objective=sanitize_episode_text(state.goal.objective),
            target=state.goal.target,
            intent=state.intent,
            preference_aspects=aspects,
            information_sources=sources,
            tool_pattern=tool_pattern,
            outcome=outcome,
            lesson=sanitize_episode_text(extracted.lesson, 400) if extracted else "; ".join(lesson_parts),
            situation=sanitize_episode_text(extracted.situation) if extracted else "",
            goal_pattern=sanitize_episode_text(extracted.goal_pattern) if extracted else "",
            salient_state=[sanitize_episode_text(item, 160) for item in extracted.salient_state] if extracted else [],
            critical_actions=list(extracted.critical_actions) if extracted else tool_pattern,
            failure_recovery=sanitize_episode_text(extracted.failure_recovery) if extracted else "",
            trajectory_ref=(
                f"{state.run_id}:{state.task_id or 'unknown-task'}"
            ),
        )


class EpisodeValueGate:
    """Keep successful or diagnostically useful evaluator-backed episodes."""

    @staticmethod
    def accept(state: PolicyPilotState, evaluation: dict | None) -> bool:
        if evaluation is None:
            return True
        reward = evaluation.get("reward")
        db_check = evaluation.get("db_check")
        required_total = int(evaluation.get("required_actions_total") or 0)
        required_done = int(evaluation.get("required_actions_completed") or 0)
        successful = reward is not None and float(reward) > 0
        diagnostic = bool(
            state.control.error_records
            or state.control.recovery_success_count
            or state.control.recovery_failure_count
            or db_check is False
            or required_total and required_done < required_total
        )
        return successful or diagnostic


class LocalEpisodeEmbedder:
    """Dependency-free hashed embedding with stable version metadata."""

    model = "local-hashed-token"
    version = "v1"

    @staticmethod
    def embed(text: str, dimensions: int = 64) -> list[float]:
        vector = [0.0] * dimensions
        for token in re.findall(r"[a-z0-9_]{3,}", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += -1.0 if digest[4] & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

class EpisodeRetriever:
    stop_words = {"the", "and", "for", "with", "that", "this", "user", "want", "need"}

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9_]{3,}", value.lower()) if token not in cls.stop_words}

    def retrieve(self, episodes: list[EpisodeMemory], query: str, *, limit: int = 3) -> list[EpisodeMemory]:
        query_tokens = self._tokens(query)
        query_target = next(
            (token for token in query_tokens if any(token == (item.target or "").lower() for item in episodes)),
            None,
        )
        query_embedding = LocalEpisodeEmbedder.embed(query)
        ranked = []
        for episode in episodes:
            if query_target and episode.target and episode.target.lower() != query_target:
                continue
            text = " ".join([episode.objective, episode.target or "", episode.intent, *episode.preference_aspects])
            overlap = len(query_tokens.intersection(self._tokens(text)))
            target_bonus = 2 if episode.target and episode.target.lower() in query.lower() else 0
            vector = episode.embedding or LocalEpisodeEmbedder.embed(text)
            semantic_score = sum(a * b for a, b in zip(query_embedding, vector))
            if overlap or target_bonus or semantic_score > 0.1:
                ranked.append((overlap + target_bonus + semantic_score, episode.updated_at, episode))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = []
        seen = set()
        for _, _, episode in ranked:
            signature = (episode.goal_pattern or episode.objective, episode.lesson)
            if signature in seen:
                continue
            selected.append(episode)
            seen.add(signature)
            if len(selected) >= limit:
                break
        return selected
