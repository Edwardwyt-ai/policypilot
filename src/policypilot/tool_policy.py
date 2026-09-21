"""Tool-call classification, signatures, duplicate detection, and budgets."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from tau2.data_model.message import ToolCall
from tau2.environment.tool import Tool

KNOWLEDGE_TOOL_NAMES = {"KB_search", "KB_search_bm25", "KB_search_dense", "grep", "shell"}
DECISION_RETRIEVAL_TOOL_NAMES = {"KB_search", "KB_search_bm25", "KB_search_dense"}


def canonicalize_arguments(arguments: dict[str, Any]) -> str:
    """Create a stable JSON representation for deterministic signatures."""
    return json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"), default=str)


def tool_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return a deterministic signature for a tool name and canonical arguments."""
    return f"{tool_name}:{canonicalize_arguments(arguments)}"


def is_knowledge_tool(tool_name: str) -> bool:
    """Return whether a tool is one of tau2's knowledge retrieval tools."""
    return tool_name in KNOWLEDGE_TOOL_NAMES


def is_decision_retrieval_tool(tool_name: str) -> bool:
    """Return whether Decision may directly request this read-only KB tool."""
    return tool_name in DECISION_RETRIEVAL_TOOL_NAMES


def classify_tool(tool: Tool) -> str:
    """Classify a tau2 Tool for prompts and process metrics."""
    if is_knowledge_tool(tool.name):
        return "knowledge"
    func = getattr(tool, "_func", None)
    mutates = getattr(func, "__mutates_state__", None)
    tool_type = getattr(func, "__tool_type__", None)
    if mutates is True:
        return "mutation"
    if str(tool_type) == "ToolType.READ" or str(tool_type) == "read":
        return "transaction_read"
    if str(tool_type) == "ToolType.WRITE" or str(tool_type) == "write":
        return "mutation"
    return "transaction_other"


@dataclass(frozen=True)
class ToolRuntimeMetadata:
    classification: str
    resource_tags: frozenset[str]
    invalidates: frozenset[str]


_RESOURCE_STOP_WORDS = {
    "get", "list", "read", "fetch", "find", "check", "search", "create",
    "update", "set", "change", "close", "cancel", "delete", "submit",
    "apply", "request", "activate", "freeze", "tool", "kb", "by", "for",
}


def tool_runtime_metadata(tool: Tool) -> ToolRuntimeMetadata:
    """Read optional tool metadata, with a generic name-based fallback."""
    declared = tool.info.get("policypilot", {}) if isinstance(tool.info, dict) else {}
    classification = str(declared.get("classification") or classify_tool(tool))
    tokens = {
        token
        for token in re.findall(r"[a-z][a-z0-9]+", tool.name.lower())
        if token not in _RESOURCE_STOP_WORDS and not token.isdigit()
    }
    for field in tool.params.model_fields:
        tokens.update(
            token for token in field.lower().split("_")
            if token not in _RESOURCE_STOP_WORDS and token not in {"id", "ids"}
        )
    resource_tags = frozenset(declared.get("resource_tags", tokens))
    invalidates = frozenset(
        declared.get("invalidates", resource_tags if classification == "mutation" else ())
    )
    return ToolRuntimeMetadata(
        classification=classification,
        resource_tags=resource_tags,
        invalidates=invalidates,
    )


@dataclass(frozen=True)
class ToolBudget:
    """Runtime budgets enforced inside PolicyPilot before returning tool calls."""

    max_agent_steps: int = 200
    max_tool_calls: int = 80
    max_consecutive_errors: int = 10


class ToolCallGuard:
    """Evaluate budget and duplicate conditions for proposed tool calls."""

    def __init__(self, tools: list[Tool], budget: ToolBudget | None = None):
        for tool in tools:
            metadata = tool_runtime_metadata(tool)
            tool.info.setdefault(
                "policypilot",
                {
                    "classification": metadata.classification,
                    "resource_tags": sorted(metadata.resource_tags),
                    "invalidates": sorted(metadata.invalidates),
                },
            )
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.budget = budget or ToolBudget()

    def validate_tool_call(self, tool_call: ToolCall) -> str | None:
        """Return an error message when the tool call is malformed."""
        if not tool_call.name:
            return "Tool call is missing a tool name."
        tool = self.tools_by_name.get(tool_call.name)
        if tool is None:
            return f"Unknown tool '{tool_call.name}'."
        if not isinstance(tool_call.arguments, dict):
            return f"Tool '{tool_call.name}' arguments must be a JSON object."
        unexpected = set(tool_call.arguments) - set(tool.params.model_fields)
        if unexpected:
            return (
                f"Tool '{tool_call.name}' received unexpected arguments: "
                f"{', '.join(sorted(unexpected))}."
            )
        try:
            tool.params.model_validate(tool_call.arguments)
        except ValidationError as exc:
            return f"Tool '{tool_call.name}' arguments failed validation: {exc}"
        return None

    def classify(self, tool_name: str) -> str:
        """Classify a known tool by name."""
        tool = self.tools_by_name.get(tool_name)
        if tool is None:
            return "unknown"
        return classify_tool(tool)

    def metadata(self, tool_name: str) -> ToolRuntimeMetadata:
        tool = self.tools_by_name.get(tool_name)
        if tool is None:
            return ToolRuntimeMetadata("unknown", frozenset(), frozenset())
        return tool_runtime_metadata(tool)


class ToolExposureResolver:
    """Select the bounded tool surface visible to the main Decision model."""

    def __init__(self, tools: list[Tool], *, expose_knowledge: bool = True):
        self.tools = tuple(tools)
        self.expose_knowledge = expose_knowledge

    def for_decision(self, state: Any) -> list[Tool]:
        exposed: list[Tool] = []
        for tool in self.tools:
            classification = classify_tool(tool)
            if classification == "knowledge":
                if self.expose_knowledge and is_decision_retrieval_tool(tool.name):
                    exposed.append(tool)
                continue
            if classification == "transaction_read":
                continue
            if (
                classification == "mutation"
                and (
                    not self._mutation_preconditions_satisfied(tool, state)
                    or state.control.mutation_verification_required
                    or any(
                        need.status == "OPEN" and need.critical and need.blocking
                        for need in state.information_needs
                    )
                )
            ):
                continue
            exposed.append(tool)
        return exposed

    @staticmethod
    def _mutation_preconditions_satisfied(tool: Tool, state: Any) -> bool:
        if state.intent == "TRANSACTIONAL":
            return True
        required = {
            name
            for name, field_info in tool.params.model_fields.items()
            if field_info.is_required()
        }
        known = {fact.aspect for fact in state.facts if fact.authoritative}
        covered = required.intersection(known)
        if not required or len(covered) < max(1, math.ceil(len(required) * 0.6)):
            return False
        missing = required - known
        if len(missing) > 1:
            return False
        action_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", tool.name.lower())
            if token not in _RESOURCE_STOP_WORDS and len(token) >= 4
        }
        recent_text = " ".join(
            message.content or "" for message in state.messages[-4:]
        ).lower()
        return bool(
            action_tokens.intersection(re.findall(r"[a-z0-9]+", recent_text))
        )

    def for_need(self, need: Any) -> list[Tool]:
        if need is None:
            return []
        if need.source == "POLICY":
            return [tool for tool in self.tools if is_knowledge_tool(tool.name)]
        if need.source == "TOOL" and need.capability:
            return [tool for tool in self.tools if tool.name == need.capability]
        return []
