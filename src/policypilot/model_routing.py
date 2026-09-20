"""Environment-compatible model routing for PolicyPilot LLM nodes."""

from __future__ import annotations

import os
from dataclasses import dataclass

from policypilot.config import PolicyPilotConfig


@dataclass(frozen=True)
class ModelRouting:
    """Resolved node routes sharing the provider credentials used by LiteLLM."""

    light_model: str
    main_model: str

    def model_for(self, node: str) -> str:
        if node == "decision":
            return self.main_model
        return self.light_model

    def as_dict(self) -> dict[str, str]:
        return {
            "semantic_planner": self.light_model,
            "profile_extractor": self.light_model,
            "episode_extractor": self.light_model,
            "skill_matcher": self.light_model,
            "context_compressor": self.light_model,
            "decision": self.main_model,
        }


def resolve_model_routing(
    configured_main_model: str,
    config: PolicyPilotConfig,
) -> ModelRouting:
    """Resolve new routes while preserving every existing single-model setup."""

    main_model = (
        config.main_decision_model
        or os.getenv("POLICYPILOT_MAIN_DECISION_MODEL")
        or os.getenv("MAIN_DECISION_MODEL")
        or configured_main_model
    )
    light_model = (
        config.light_model
        or os.getenv("POLICYPILOT_LIGHT_MODEL")
        or os.getenv("LIGHT_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("MODEL")
        or main_model
    )
    return ModelRouting(light_model=light_model, main_model=main_model)
