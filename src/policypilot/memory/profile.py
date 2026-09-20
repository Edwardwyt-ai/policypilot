"""User profile extraction, deterministic safety gate, and merge."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, Field

from policypilot.llm_runtime import LLMRuntime
from policypilot.memory.models import (
    PreferenceCandidate,
    ProfilePreference,
    UserProfile,
    utc_now,
)
from policypilot.memory.store import JsonMemoryStore
from tau2.data_model.message import SystemMessage, UserMessage

PROFILE_EXTRACTION_PROMPT = """
Extract only an explicit stable cross-task preference from the latest message.
Never store identity, contact, authentication, balance, transaction, referral,
eligibility, status, current-policy, or one-task facts. Return preferences=[]
when no durable preference is stated. Do not restate task context.
""".strip()

class PreferenceExtractor(Protocol):
    def extract(self, message: str, task_context: str) -> list[PreferenceCandidate]: ...

class PreferenceExtraction(BaseModel):
    preferences: list[PreferenceCandidate] = Field(default_factory=list, max_length=2)


class LLMPreferenceExtractor:
    def __init__(
        self,
        model: str | None = None,
        llm_args: dict | None = None,
        generate_fn: Callable | None = None,
        runtime: LLMRuntime | None = None,
    ):
        self.model = model
        self.llm_args = dict(llm_args or {})
        self.runtime = runtime
        if generate_fn is None:
            from tau2.utils.llm_utils import generate
            generate_fn = generate
        self.generate_fn = generate_fn

    def extract(self, message: str, task_context: str) -> list[PreferenceCandidate]:
        messages = [
            SystemMessage(role="system", content=PROFILE_EXTRACTION_PROMPT),
            UserMessage.text(f"CONTEXT={task_context[:300]}\nMESSAGE={message[:500]}"),
        ]
        if self.runtime is not None:
            return self.runtime.call_structured(
                "profile_extractor", messages, PreferenceExtraction
            ).preferences
        if not self.model:
            raise ValueError("A model or shared LLMRuntime is required.")
        result = self.generate_fn(
            model=self.model,
            tools=[],
            messages=messages,
            call_name="policypilot_profile_memory",
            **self.llm_args,
        )
        content = (result.content or "").strip()
        if content.startswith(chr(96) * 3):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1])
        payload = json.loads(content)
        if isinstance(payload, dict):
            payload = payload.get("preferences", [])
        return [PreferenceCandidate.model_validate(item) for item in payload]

class DeterministicPreferenceExtractor:
    """Failure fallback; intentionally conservative."""
    marker = re.compile(r"\b(i prefer|i want|i avoid|i dislike|always|never|important to me)\b|我偏好|我希望|我不喜欢|我总是|我从不", re.I)
    aspects = (
        ("annual_fee", r"annual fee|fee-free|年费"),
        ("rewards", r"cash.?back|reward|points|返现|奖励|积分"),
        ("product_type", r"card|account|loan|mortgage|银行卡|账户|贷款"),
        ("communication_style", r"concise|detailed|explain|简洁|详细|解释"),
    )

    def extract(self, message: str, task_context: str) -> list[PreferenceCandidate]:
        if not self.marker.search(message):
            return []
        aspect = next((name for name, pattern in self.aspects if re.search(pattern, message, re.I)), "general_preference")
        polarity = "AVOID" if re.search(r"\b(avoid|dislike|never|no)\b|不喜欢|避免|不要|从不", message, re.I) else "PREFER"
        return [PreferenceCandidate(aspect=aspect, value=" ".join(message.split())[:240], polarity=polarity, confidence=0.75, explicit=True, source_excerpt=message[:240])]

class ProfileMemoryGate:
    allowed_aspects = {
        "annual_fee", "rewards", "product_type", "product_category",
        "risk_tolerance", "communication_style", "service_channel",
        "optimization_priority", "general_preference",
    }
    blocked = re.compile(
        r"\b(balance|transaction|referral|eligib|status|verification|otp|code|password|pin|account.?id|user.?id|card.?id|email|phone|address|date.?of.?birth|ssn|policy version|current policy)\b|余额|交易状态|推荐状态|资格|验证码|密码|账户号|卡号|邮箱|电话|地址|生日|当前政策",
        re.I,
    )
    pii = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{6,}\b")

    def __init__(self, min_confidence: float = 0.7):
        self.min_confidence = min_confidence

    def accept(self, candidate: PreferenceCandidate) -> bool:
        text = f"{candidate.aspect} {candidate.value} {candidate.source_excerpt}"
        return candidate.explicit and candidate.confidence >= self.min_confidence and candidate.aspect.strip().lower() in self.allowed_aspects and len(candidate.value.strip()) <= 300 and not self.blocked.search(text) and not self.pii.search(text)

class ProfileMerger:
    @staticmethod
    def merge(profile: UserProfile, candidates: list[PreferenceCandidate]) -> bool:
        changed = False
        for candidate in candidates:
            aspect = candidate.aspect.strip().lower()
            scope = candidate.scope.strip().lower() or "general"
            key = f"{scope}:{aspect}"
            digest = hashlib.sha256(candidate.source_excerpt.encode("utf-8")).hexdigest()
            current = next((item for item in reversed(profile.preferences) if item.key == key and item.active), None)
            if current and current.value == candidate.value and current.polarity == candidate.polarity:
                if candidate.confidence > current.confidence:
                    current.confidence = candidate.confidence
                    current.updated_at = utc_now()
                    current.source_digest = digest
                    changed = True
                continue
            if current:
                current.active = False
                current.superseded_at = utc_now()
            profile.preferences.append(ProfilePreference(key=key, aspect=aspect, value=candidate.value.strip(), scope=scope, polarity=candidate.polarity, confidence=candidate.confidence, source_digest=digest))
            changed = True
        if changed:
            profile.revision += 1
            profile.updated_at = utc_now()
        return changed

class ProfileMemoryManager:
    preference_signal = DeterministicPreferenceExtractor.marker

    def __init__(self, store: JsonMemoryStore, extractor: PreferenceExtractor, gate: ProfileMemoryGate | None = None, merger: ProfileMerger | None = None):
        self.store = store
        self.extractor = extractor
        self.fallback = DeterministicPreferenceExtractor()
        self.gate = gate or ProfileMemoryGate()
        self.merger = merger or ProfileMerger()

    def form_candidates(self, message: str, task_context: str) -> tuple[list[PreferenceCandidate], bool, bool]:
        if not self.preference_signal.search(message):
            return [], False, False
        try:
            return self.extractor.extract(message, task_context), True, False
        except Exception:
            return self.fallback.extract(message, task_context), True, True

    def apply(self, user_id: str, candidates: list[PreferenceCandidate]) -> tuple[UserProfile, int, int, bool]:
        profile = self.store.load_profile(user_id)
        accepted = [item for item in candidates if self.gate.accept(item)]
        rejected = len(candidates) - len(accepted)
        changed = self.merger.merge(profile, accepted)
        if changed:
            self.store.save_profile(profile)
        return profile, len(accepted), rejected, changed
