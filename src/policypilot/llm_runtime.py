"""Unified, observable LLM calls for PolicyPilot nodes."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

from policypilot.model_routing import ModelRouting
from policypilot.prompts import LIGHTWEIGHT_BASE_PROMPT
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    SystemMessage,
    UserMessage,
)
from tau2.environment.tool import Tool
from tau2.utils.llm_utils import generate

LLMNode = Literal[
    "semantic_planner",
    "coverage_manager",
    "profile_extractor",
    "episode_extractor",
    "skill_matcher",
    "context_compressor",
    "decision",
]
T = TypeVar("T", bound=BaseModel)


class LLMCallTrace(BaseModel):
    run_id: str
    task_id: str | None = None
    node: LLMNode
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0
    cost_available: bool = True
    structured_output_valid: bool | None = None
    retry_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _provider(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else "configured"


def _json_content(content: str | None) -> Any:
    value = (content or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    return json.loads(value)


class LLMRuntime:
    """One provider-neutral gateway with per-node routing and trace capture."""

    def __init__(
        self,
        routing: ModelRouting,
        *,
        llm_args: dict[str, Any] | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        generate_fn: Callable[..., AssistantMessage] = generate,
        light_temperature: float = 0.1,
        structured_repair_attempts: int = 1,
        lightweight_max_tokens: dict[str, int] | None = None,
    ):
        self.routing = routing
        self.llm_args = dict(llm_args or {})
        self.run_id = run_id or f"policypilot_{uuid.uuid4().hex}"
        self.task_id = task_id
        self.generate_fn = generate_fn
        self.light_temperature = light_temperature
        self.structured_repair_attempts = structured_repair_attempts
        default_lightweight_max_tokens = {
            "semantic_planner": 400,
            "coverage_manager": 180,
            "profile_extractor": 300,
            "episode_extractor": 600,
            "skill_matcher": 120,
            "context_compressor": 600,
        }
        default_lightweight_max_tokens.update(lightweight_max_tokens or {})
        self.lightweight_max_tokens = default_lightweight_max_tokens
        self.traces: list[LLMCallTrace] = []

    def call_message(
        self,
        node: LLMNode,
        messages: list[Message],
        *,
        tools: list[Tool] | None = None,
        call_name: str | None = None,
        extra_args: dict[str, Any] | None = None,
        retry_count: int = 0,
    ) -> AssistantMessage:
        model = self.routing.model_for(node)
        args = dict(self.llm_args)
        args.update(extra_args or {})
        args.setdefault("num_retries", 0)
        if node != "decision":
            args.setdefault("temperature", self.light_temperature)
            args.setdefault("max_tokens", self.lightweight_max_tokens[node])
            if _provider(model).lower() == "deepseek":
                extra_body = dict(args.get("extra_body") or {})
                extra_body.setdefault("thinking", {"type": "disabled"})
                args["extra_body"] = extra_body
        started = time.perf_counter()
        try:
            response = self.generate_fn(
                model=model,
                tools=tools or [],
                messages=messages,
                call_name=call_name or f"policypilot_{node}",
                **args,
            )
        except Exception as exc:
            self.traces.append(
                LLMCallTrace(
                    run_id=self.run_id,
                    task_id=self.task_id,
                    node=node,
                    model=model,
                    provider=_provider(model),
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retry_count=retry_count,
                    error=f"{type(exc).__name__}: {exc}"[:500],
                )
            )
            raise
        usage = response.usage or {}
        cost = float(response.cost or 0.0)
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        self.traces.append(
            LLMCallTrace(
                run_id=self.run_id,
                task_id=self.task_id,
                node=node,
                model=model,
                provider=_provider(model),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=int(usage.get("prompt_cache_hit_tokens", 0)),
                latency_ms=(response.generation_time_seconds or (time.perf_counter() - started))
                * 1000,
                cost=cost,
                cost_available=not (cost == 0.0 and input_tokens + output_tokens > 0),
                retry_count=retry_count,
            )
        )
        return response

    def call_structured(
        self,
        node: LLMNode,
        messages: list[Message],
        schema: type[T],
        *,
        call_name: str | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> T:
        schema_prompt = json.dumps(schema.model_json_schema(), ensure_ascii=True)
        request = [
            SystemMessage(role="system", content=LIGHTWEIGHT_BASE_PROMPT),
            *messages,
            SystemMessage(
                role="system",
                content=(
                    "Return one JSON object matching this schema exactly. Do not use markdown.\n"
                    f"JSON SCHEMA:\n{schema_prompt}"
                ),
            ),
        ]
        last_error: Exception | None = None
        for attempt in range(self.structured_repair_attempts + 1):
            current = request
            if attempt and last_error is not None:
                current = [
                    *request,
                    UserMessage.text(
                        "The prior output failed validation. Return corrected JSON only. "
                        f"Validation error: {str(last_error)[:500]}"
                    ),
                ]
            response = self.call_message(
                node,
                current,
                call_name=call_name,
                extra_args={"response_format": {"type": "json_object"}},
                retry_count=attempt,
            )
            self.traces[-1].metadata.update(trace_metadata or {})
            try:
                result = schema.model_validate(_json_content(response.content))
            except (ValueError, TypeError, ValidationError) as exc:
                self.traces[-1].structured_output_valid = False
                self.traces[-1].error = f"{type(exc).__name__}: {exc}"[:500]
                last_error = exc
                continue
            self.traces[-1].structured_output_valid = True
            return result
        assert last_error is not None
        raise last_error

    def snapshot(self) -> list[dict[str, Any]]:
        return [trace.model_dump(mode="json") for trace in self.traces]
