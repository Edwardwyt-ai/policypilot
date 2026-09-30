"""Compile source-free semantic Needs into bounded evidence acquisitions."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Protocol

from policypilot.state import (
    AcquisitionCandidate,
    NeedCandidate,
    PolicyPilotState,
)
from policypilot.tool_policy import classify_tool
from tau2.environment.tool import Tool

ACQUISITION_PLAN_CRITERIA = {
    "POLICY_ONLY": "General policy or product documentation is sufficient.",
    "TOOL_ONLY": "A supplied read tool for current customer-specific state is sufficient.",
    "USER_ONLY": "Only the user can provide the missing preference or fact.",
    "POLICY_AND_TOOL": "Both general policy and current tool state are independently required.",
    "POLICY_AND_USER": "Both general policy and a user-provided fact are required.",
    "TOOL_AND_USER": "Both current tool state and a user-provided fact are required.",
}

ACQUISITION_PLAN_INSTRUCTIONS = (
    "Classify which authoritative evidence must be acquired to resolve this missing "
    "banking proposition. Policy means general product rules, fees, limits, "
    "eligibility criteria, timing, or procedures. Tool means current "
    "customer-specific state. User means a preference or fact unavailable from "
    "policy and tools."
)


class TypedDecisionBackend(Protocol):
    def decide(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> dict[str, Any]: ...


class LocalLayaBackend:
    """Lazy, process-local Laya adapter with no API or background service."""

    def __init__(
        self,
        *,
        model: str = "convaiinnovations/laya",
        device: str | None = None,
        cache_dir: str | None = None,
        loader: Any | None = None,
    ):
        self.model = model
        self.device = None if device in {None, "", "auto"} else device
        self.cache_dir = cache_dir
        self._loader = loader
        self._agent = None
        self._load_error: Exception | None = None
        self._lock = threading.RLock()

    def _load(self):
        with self._lock:
            if self._agent is not None:
                return self._agent
            if self._load_error is not None:
                raise RuntimeError("Local Laya failed to load previously") from self._load_error
            try:
                if self.cache_dir:
                    os.environ.setdefault(
                        "HF_HOME", os.path.abspath(os.path.expanduser(self.cache_dir))
                    )
                if self._loader is None:
                    from laya import load

                    self._loader = load
                self._agent = self._loader(self.model, device=self.device)
            except Exception as exc:
                self._load_error = exc
                raise
            return self._agent

    def decide(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> dict[str, Any]:
        response = dict(self._load().system_one(state, questions))
        response["runtime_model"] = response.get("model")
        response["model"] = self.model
        return response


def build_laya_backend(
    *, model: str, device: str | None, cache_dir: str | None
) -> LocalLayaBackend:
    return LocalLayaBackend(
        model=os.getenv("POLICYPILOT_LAYA_MODEL", model),
        device=os.getenv("POLICYPILOT_LAYA_DEVICE", device or "auto"),
        cache_dir=os.getenv("POLICYPILOT_LAYA_CACHE_DIR", cache_dir or ""),
    )


class AcquisitionPlanner:
    """Use Laya for semantic ambiguity; hard capabilities stay deterministic."""

    def __init__(
        self,
        tools: list[Tool],
        backend: TypedDecisionBackend | None,
        *,
        plan_threshold: float = 0.75,
        tool_threshold: float = 0.75,
        max_candidates: int = 3,
        max_tool_options: int = 9,
    ):
        self.backend = backend
        self.plan_threshold = plan_threshold
        self.tool_threshold = tool_threshold
        self.max_candidates = max_candidates
        self.max_tool_options = max_tool_options
        self.read_tools = {
            tool.name: tool
            for tool in tools
            if classify_tool(tool) == "transaction_read"
        }

    @staticmethod
    def _known_arguments(
        candidate: NeedCandidate, tool: Tool, state: PolicyPilotState
    ) -> dict[str, Any] | None:
        arguments = {
            key: value
            for key, value in candidate.tool_arguments.items()
            if key in tool.params.model_fields
        }
        for name in tool.params.model_fields:
            if name in arguments:
                continue
            fact = state.get_fact(name, "user") or state.get_fact(name)
            if fact is not None:
                arguments[name] = fact.value
        required = {
            name
            for name, field in tool.params.model_fields.items()
            if field.is_required()
        }
        if not required.issubset(arguments):
            return None
        try:
            tool.params.model_validate(arguments)
        except Exception:
            return None
        return arguments

    def _eligible_tools(
        self, candidate: NeedCandidate, state: PolicyPilotState
    ) -> list[tuple[Tool, dict[str, Any]]]:
        eligible = []
        for tool in self.read_tools.values():
            arguments = self._known_arguments(candidate, tool, state)
            if arguments is not None:
                eligible.append((tool, arguments))
        return sorted(eligible, key=lambda item: item[0].name)[
            : self.max_tool_options
        ]

    @staticmethod
    def _fallback(candidate: NeedCandidate) -> NeedCandidate:
        if candidate.acquisitions:
            return candidate
        if candidate.source is None:
            return candidate
        acquisition = AcquisitionCandidate(
            source=candidate.source,
            capability=candidate.capability,
            tool_arguments=candidate.tool_arguments,
            origin=(
                "DETERMINISTIC"
                if candidate.provenance != "semantic_planner"
                else "PLANNER_FALLBACK"
            ),
        )
        return candidate.model_copy(update={"acquisitions": [acquisition]})

    @staticmethod
    def _choice(answers: dict[str, Any], key: str) -> tuple[str | None, float]:
        answer = answers.get(key) or {}
        selected = answer.get("choice")
        confidence = answer.get("answer_confidence", answer.get("confidence", 0.0))
        return (
            str(selected) if selected else None,
            float(confidence) if isinstance(confidence, (int, float)) else 0.0,
        )

    def plan(
        self,
        state: PolicyPilotState,
        candidates: list[NeedCandidate],
        *,
        turn: int,
    ) -> list[NeedCandidate]:
        result: list[NeedCandidate] = []
        reviewed = 0
        for candidate in candidates:
            if (
                self.backend is None
                or candidate.provenance != "semantic_planner"
                or reviewed >= self.max_candidates
            ):
                result.append(self._fallback(candidate))
                continue
            reviewed += 1
            eligible = self._eligible_tools(candidate, state)
            criteria = {
                tool.name: (
                    f"{' '.join(tool.short_desc.split())[:120]} Required input fields: "
                    f"{', '.join(sorted(tool.params.model_fields)) or 'none'}."
                )
                for tool, _ in eligible
            }
            criteria["NONE"] = "No supplied read tool can authoritatively answer this Need."
            compact_state = {
                "goal": {
                    "hard_aspects": [
                        item.aspect
                        for item in state.goal.criteria
                        if item.hard
                    ][:6],
                },
                "need": {
                    "entity": candidate.entity,
                    "aspect": candidate.aspect,
                    "scope": candidate.scope,
                    "reason": candidate.reason_code,
                    "planner_hint": candidate.source,
                },
                "missing_proposition": (
                    f"Determine {candidate.aspect} for {candidate.entity}"
                    f" within {candidate.scope or 'the relevant scope'}."
                ),
                # Values and raw messages are deliberately excluded. Only
                # field availability is relevant to acquisition routing.
                "available_fact_fields": sorted(
                    {fact.aspect for fact in state.facts if fact.aspect != "utterance"}
                )[:24],
            }
            questions: dict[str, Any] = {
                "acquisition_plan": {
                    "type": "choice",
                    "instructions": ACQUISITION_PLAN_INSTRUCTIONS,
                    "criteria": ACQUISITION_PLAN_CRITERIA,
                },
                "read_capability": {
                    "type": "choice",
                    "instructions": (
                        "Choose the exact supplied read capability for the current live-state part, "
                        "or NONE. Never choose a tool for general policy knowledge."
                    ),
                    "criteria": criteria,
                },
            }
            started = time.perf_counter()
            error = None
            raw_answers: dict[str, Any] = {}
            acquisitions: list[AcquisitionCandidate] = []
            model = None
            usage = None
            try:
                response = self.backend.decide(compact_state, questions)
                raw_answers = response.get("answers") or {}
                model = response.get("model")
                usage = response.get("usage")
                selected_plan, plan_confidence = self._choice(
                    raw_answers, "acquisition_plan"
                )
                selected_tool, tool_confidence = self._choice(
                    raw_answers, "read_capability"
                )
                plan_sources = {
                    "POLICY_ONLY": ("POLICY",),
                    "TOOL_ONLY": ("TOOL",),
                    "USER_ONLY": ("USER",),
                    "POLICY_AND_TOOL": ("POLICY", "TOOL"),
                    "POLICY_AND_USER": ("POLICY", "USER"),
                    "TOOL_AND_USER": ("TOOL", "USER"),
                }
                sources = (
                    plan_sources.get(selected_plan, ())
                    if plan_confidence >= self.plan_threshold
                    else ()
                )
                tool_acquisition = None
                if "TOOL" in sources and selected_tool not in {None, "NONE"}:
                    match = next(
                        (
                            (tool, arguments)
                            for tool, arguments in eligible
                            if tool.name == selected_tool
                        ),
                        None,
                    )
                    if match is not None and tool_confidence >= self.tool_threshold:
                        tool_acquisition = AcquisitionCandidate(
                            source="TOOL",
                            capability=match[0].name,
                            tool_arguments=match[1],
                            confidence=min(plan_confidence, tool_confidence),
                            origin="LAYA",
                        )
                if "TOOL" not in sources or tool_acquisition is not None:
                    if "POLICY" in sources:
                        acquisitions.append(
                            AcquisitionCandidate(
                                source="POLICY",
                                confidence=plan_confidence,
                                origin="LAYA",
                            )
                        )
                    if tool_acquisition is not None:
                        acquisitions.append(tool_acquisition)
                    if "USER" in sources:
                        acquisitions.append(
                            AcquisitionCandidate(
                                source="USER",
                                confidence=plan_confidence,
                                origin="LAYA",
                            )
                        )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if not acquisitions:
                planned = self._fallback(candidate)
                acquisitions = planned.acquisitions
                applied = False
            else:
                planned = candidate.model_copy(
                    update={
                        "source": acquisitions[0].source,
                        "capability": acquisitions[0].capability,
                        "tool_arguments": acquisitions[0].tool_arguments,
                        "acquisitions": acquisitions,
                    }
                )
                applied = True
            result.append(planned)
            state.control.acquisition_planning_events.append(
                {
                    "turn": turn,
                    "entity": candidate.entity,
                    "aspect": candidate.aspect,
                    "planner_hint": candidate.source,
                    "acquisitions": [
                        item.model_dump(mode="json") for item in acquisitions
                    ],
                    "applied": applied,
                    "model": model,
                    "usage": usage,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error": error,
                }
            )
        return result


__all__ = [
    "ACQUISITION_PLAN_CRITERIA",
    "ACQUISITION_PLAN_INSTRUCTIONS",
    "AcquisitionPlanner",
    "LocalLayaBackend",
    "TypedDecisionBackend",
    "build_laya_backend",
]
