"""Offline LLM judge for the agent's user-facing response.

Gold criteria and judge inputs stay outside the agent runtime. This module is
only used to rescore saved simulations and never exposes evaluator labels to the
PolicyPilot decision graph.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tau2.data_model.message import AssistantMessage, SystemMessage, UserMessage
from tau2.utils.llm_utils import generate


class FinalResponseCriteria(BaseModel):
    correctness: str = Field(min_length=1)
    completeness: str = Field(min_length=1)
    grounded_safety: str = Field(min_length=1)


class TaskFinalResponseGold(BaseModel):
    criteria: FinalResponseCriteria


class FinalResponseGoldDataset(BaseModel):
    schema_version: Literal["final-response-gold-v1"]
    domain: Literal["banking_knowledge"]
    selected_task_count: int = Field(ge=1)
    tasks: dict[str, TaskFinalResponseGold]

    @model_validator(mode="after")
    def selected_count_matches(self) -> "FinalResponseGoldDataset":
        if self.selected_task_count != len(self.tasks):
            raise ValueError("selected_task_count does not match tasks")
        return self


class CriterionVerdict(BaseModel):
    passed: bool
    reason: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class FinalResponseVerdict(BaseModel):
    correctness: CriterionVerdict
    completeness: CriterionVerdict
    grounded_safety: CriterionVerdict
    critical_error: Literal[
        "UNSUPPORTED_CLAIM",
        "FALSE_SUCCESS_CLAIM",
        "MISSED_REQUIREMENT",
        "POLICY_CONTRADICTION",
        "TOOL_RESULT_CONTRADICTION",
        "MEMORY_AS_LIVE_FACT",
        "UNSAFE_ACTION_GUIDANCE",
    ] | None = None


class JudgeUsage(BaseModel):
    model: str
    latency_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    cost_available: bool = True


class FinalResponseJudgeRecord(BaseModel):
    task_id: str
    semantic_score: float = Field(ge=0.0, le=1.0)
    semantic_pass: bool
    verdict: FinalResponseVerdict
    usage: JudgeUsage
    result_path: str | None = None


def default_final_response_gold_path() -> Path:
    return (
        Path(__file__).absolute().parents[3]
        / "data"
        / "policypilot"
        / "evaluation"
        / "final_response_gold_v1.json"
    )


def load_final_response_gold(
    path: Path | None = None,
) -> FinalResponseGoldDataset:
    gold_path = path or default_final_response_gold_path()
    return FinalResponseGoldDataset.model_validate_json(
        gold_path.read_text(encoding="utf-8")
    )


def _compact(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def build_judge_packet(payload: dict[str, Any], task_id: str | None = None) -> dict:
    """Extract bounded, source-labelled evidence from one saved results file."""

    simulations = payload.get("simulations") or []
    if task_id is None:
        if len(simulations) != 1:
            raise ValueError("task_id is required when results contain multiple simulations")
        task_id = simulations[0].get("task_id")
    simulation = next(
        (item for item in simulations if item.get("task_id") == task_id), None
    )
    if simulation is None:
        raise ValueError(f"No simulation found for {task_id}")

    user_messages: list[dict[str, str]] = []
    assistant_messages: list[dict[str, str]] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    for index, message in enumerate(simulation.get("messages") or []):
        role = message.get("role")
        content = message.get("content")
        evidence_id = f"message:{index}"
        if role == "user" and content:
            user_messages.append(
                {"id": evidence_id, "content": _compact(content, 1200)}
            )
        elif role == "assistant" and content:
            assistant_messages.append(
                {"id": evidence_id, "content": _compact(content, 1800)}
            )
        for call in message.get("tool_calls") or []:
            tool_calls.append(
                {
                    "id": call.get("id") or f"tool_call:{len(tool_calls)}",
                    "requestor": role,
                    "name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                }
            )
        if role == "tool":
            tool_results.append(
                {
                    "id": message.get("id") or evidence_id,
                    "content": _compact(content, 2500),
                    "error": bool(message.get("error")),
                }
            )

    reward = simulation.get("reward_info") or {}
    db_check = reward.get("db_check") or {}
    return {
        "task_id": task_id,
        "final_response": (
            assistant_messages[-1]["content"] if assistant_messages else ""
        ),
        "recent_agent_responses": assistant_messages[-6:],
        "user_messages": user_messages[-8:],
        "executed_tool_calls": tool_calls[-16:],
        "authoritative_tool_results": tool_results[-12:],
        "tau3_result": {
            "reward": reward.get("reward"),
            "db_match": db_check.get("db_match"),
            "termination_reason": simulation.get("termination_reason"),
        },
    }


JUDGE_SYSTEM_PROMPT = """
You are an offline evaluator for a banking support agent. Evaluate only the
agent's user-facing response against the supplied task-specific criteria and
the source-labelled evidence packet.

Rules:
- Tool results and the tau3 database check are authoritative for live state and
  whether an action completed.
- User statements are authoritative only for the user's own preferences and
  supplied identity details, not for whether a banking operation completed.
- A policy or live-state claim unsupported by supplied evidence must fail
  correctness or grounded_safety as appropriate.
- Do not reward an answer for matching an expected conclusion when its evidence
  does not support that conclusion.
- Evaluate completeness for the decision-bearing response in the context of the
  recent agent responses. Do not require a redundant final message after the
  user has already completed an action and stopped.
- Memory may guide preferences but cannot prove balance, eligibility, current
  status, current policy, or action completion.
- Return JSON only. Keep each reason short and cite supplied evidence IDs when
  possible.
""".strip()


def _json_content(content: str | None) -> Any:
    value = (content or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    return json.loads(value)


class FinalResponseJudge:
    """Structured DeepSeek judge using the same provider credentials as the agent."""

    def __init__(
        self,
        model: str | None = None,
        *,
        generate_fn: Callable[..., AssistantMessage] = generate,
        structured_repair_attempts: int = 1,
    ):
        self.model = (
            model
            or os.getenv("POLICYPILOT_JUDGE_MODEL")
            or "deepseek/deepseek-chat"
        )
        self.generate_fn = generate_fn
        self.structured_repair_attempts = structured_repair_attempts

    def judge(
        self,
        *,
        task_id: str,
        criteria: FinalResponseCriteria,
        packet: dict[str, Any],
        result_path: str | None = None,
    ) -> FinalResponseJudgeRecord:
        request = {
            "criteria": criteria.model_dump(mode="json"),
            "evidence_packet": packet,
            "output_schema": FinalResponseVerdict.model_json_schema(),
        }
        started = time.perf_counter()
        messages = [
            SystemMessage(role="system", content=JUDGE_SYSTEM_PROMPT),
            UserMessage.text(json.dumps(request, ensure_ascii=False)),
        ]
        responses: list[AssistantMessage] = []
        last_error: Exception | None = None
        verdict = None
        for attempt in range(self.structured_repair_attempts + 1):
            current = messages
            if attempt and last_error is not None:
                current = [
                    *messages,
                    UserMessage.text(
                        "The previous output was invalid or incomplete. Return a compact "
                        "JSON object only, with all three verdicts. Validation error: "
                        f"{str(last_error)[:300]}"
                    ),
                ]
            response = self.generate_fn(
                model=self.model,
                messages=current,
                tools=[],
                call_name="policypilot_final_response_judge",
                temperature=0.0,
                max_tokens=1800,
                num_retries=1,
                response_format={"type": "json_object"},
            )
            responses.append(response)
            try:
                verdict = FinalResponseVerdict.model_validate(
                    _json_content(response.content)
                )
                break
            except (ValueError, TypeError) as exc:
                last_error = exc
        if verdict is None:
            assert last_error is not None
            raise last_error
        passed = [
            verdict.correctness.passed,
            verdict.completeness.passed,
            verdict.grounded_safety.passed,
        ]
        input_tokens = sum(
            int((item.usage or {}).get("prompt_tokens", 0)) for item in responses
        )
        output_tokens = sum(
            int((item.usage or {}).get("completion_tokens", 0)) for item in responses
        )
        cost = sum(float(item.cost or 0.0) for item in responses)
        total_tokens = input_tokens + output_tokens
        return FinalResponseJudgeRecord(
            task_id=task_id,
            semantic_score=sum(passed) / len(passed),
            semantic_pass=all(passed) and verdict.critical_error is None,
            verdict=verdict,
            usage=JudgeUsage(
                model=self.model,
                latency_seconds=time.perf_counter() - started,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                cost_available=not (cost == 0.0 and total_tokens > 0),
            ),
            result_path=result_path,
        )


__all__ = [
    "FinalResponseCriteria",
    "FinalResponseGoldDataset",
    "FinalResponseJudge",
    "FinalResponseJudgeRecord",
    "TaskFinalResponseGold",
    "build_judge_packet",
    "default_final_response_gold_path",
    "load_final_response_gold",
]
