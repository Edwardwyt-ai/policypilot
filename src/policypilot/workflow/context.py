"""Compact decision context built from canonical semantic state."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from policypilot.config import PolicyPilotConfig
from policypilot.context_budget import CHANNEL_BUDGETS, bound_channel, budget_manifest
from policypilot.provenance import ContextManifest
from policypilot.requirements import render_requirement_gap_context
from policypilot.state import PolicyPilotState
from tau2.data_model.message import (
    APICompatibleMessage,
    AssistantMessage,
    SystemMessage,
    ToolMessage,
)
from tau2.environment.tool import Tool

if TYPE_CHECKING:
    from policypilot.compression import ToolContextCompressor

@dataclass(frozen=True)
class AgentContext:
    messages: list[APICompatibleMessage]
    recent_messages: list[APICompatibleMessage]
    structured_summary: str
    estimated_size: int
    context_id: str

def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{3,}", text.lower()))

def _recent(messages, limit):
    start = max(len(messages) - limit, 0)
    while start > 0 and isinstance(messages[start], ToolMessage):
        start -= 1
    return list(messages[start:])


def _compact(value, limit: int) -> str:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    rendered = " ".join(rendered.split())
    return rendered if len(rendered) <= limit else f"{rendered[: limit - 3]}..."


def _bound_recent(messages: list[APICompatibleMessage]) -> list[APICompatibleMessage]:
    maximum = CHANNEL_BUDGETS["recent_messages"].maximum
    bounded = list(messages)
    size = sum(len(item.content or "") for item in bounded)
    while size > maximum and len(bounded) > 2:
        remove = 2 if len(bounded) > 1 and isinstance(bounded[1], ToolMessage) else 1
        del bounded[:remove]
        size = sum(len(item.content or "") for item in bounded)
    if size > maximum and bounded:
        first = bounded[0]
        content = first.content or ""
        overflow = size - maximum
        bounded[0] = first.model_copy(
            update={"content": content[min(len(content), overflow) :]}
        )
    return bounded

def _selected_records(
    state: PolicyPilotState,
    config: PolicyPilotConfig,
    tools: list[Tool] | None = None,
):
    goal = state.goal
    focus = _tokens(" ".join([goal.objective or "", goal.target or "", *(c.value for c in goal.criteria), *(n.reason for n in state.open_needs())]))
    required_fields = {
        name
        for tool in (tools or [])
        for name, field in tool.params.model_fields.items()
        if field.is_required()
    }
    relevant = [
        fact
        for fact in state.facts
        if fact.aspect in required_fields
        or not focus
        or focus & _tokens(f"{fact.entity} {fact.aspect} {fact.value}")
    ]
    facts = relevant[-min(config.max_context_facts, 16):]
    evidence = [e for e in state.evidence if not focus or focus & _tokens(e.summary)][-min(config.max_context_evidence, 2):]
    needs = state.open_needs()[:10]
    return facts, evidence, needs


def _summary(
    state: PolicyPilotState,
    tools: list[Tool],
    config: PolicyPilotConfig,
    memory_context: str = "",
    rehydrated_context: str = "",
) -> str:
    goal = state.goal
    facts, evidence, selected_needs = _selected_records(state, config, tools)
    criteria = "\n".join(
        f"- {c.kind} {c.aspect}: {_compact(c.value, 180)}"
        for c in goal.criteria
    ) or "None"
    needs = "\n".join(
        f"- {n.id} source={n.source} critical={n.critical}: "
        f"{_compact(n.reason, 160)}"
        for n in selected_needs
    ) or "None"
    fact_text = "\n".join(
        f"- {f.entity}.{f.aspect}={_compact(f.value, 320)} "
        f"[{f.source}; evidence={f.evidence_ref or 'none'}]"
        for f in facts
    ) or "None"
    evidence_text = "\n".join(
        f"- evidence_id={e.evidence_id}; payload_ref={e.payload_ref or 'none'}; "
        f"source={e.source_type}:{e.tool_name or 'user'}; "
        f"documents={','.join(ref.document_id for ref in e.policy_refs) or 'none'} "
        f"{_compact(e.summary, 500)}"
        for e in evidence
    ) or "None"
    errors = "\n".join(
        f"- {e.category.value}: {_compact(e.message, 320)}"
        for e in state.control.error_records
        if not e.resolved
    ) or "None"
    criteria = bound_channel("goal", criteria)
    needs = bound_channel("needs", needs)
    fact_text = bound_channel("facts", fact_text)
    evidence_text = bound_channel("evidence", evidence_text)
    memory_context = bound_channel("memory", memory_context) if memory_context else ""
    rehydrated_context = (
        bound_channel("rehydrated", rehydrated_context)
        if rehydrated_context
        else ""
    )
    sections = [
        "<policypilot_context>",
        f"GOAL\nobjective={goal.objective or 'None'}\ntarget={goal.target or 'None'}\ncomparative={goal.comparative}\n{criteria}",
        bound_channel("needs", render_requirement_gap_context(state)),
        f"INTENT\n{state.intent}",
        f"OPEN INFORMATION NEEDS\n{needs}",
        f"RELEVANT FACTS\n{fact_text}",
        f"RELEVANT EVIDENCE\n{evidence_text}",
    ]
    if rehydrated_context:
        sections.append(rehydrated_context)
    sections.extend(
        [
            f"CONTROL\nretrievals={state.control.goal_retrieval_call_count}/{config.max_goal_retrieval_calls}; mutation_verification={state.control.mutation_verification_required}\nerrors={errors}",
            "AVAILABLE TOOLS\n" + ", ".join(tool.name for tool in tools),
        ]
    )
    if memory_context:
        sections.append(memory_context)
    sections.append("</policypilot_context>")
    return "\n\n".join(sections)

def _estimated_size(messages: list[APICompatibleMessage]) -> int:
    size = sum(len(message.content or "") for message in messages)
    size += sum(
        len(json.dumps(call.arguments, default=str))
        for message in messages
        if isinstance(message, AssistantMessage)
        for call in (message.tool_calls or [])
    )
    return size


def build_agent_context(
    state: PolicyPilotState,
    tools: list[Tool],
    config: PolicyPilotConfig | None = None,
    *,
    memory_context: str = "",
    memory_ids: list[str] | None = None,
    rehydrated_context: str = "",
    rehydrated_refs: list[str] | None = None,
    rehydrated_evidence_ids: list[str] | None = None,
    rehydrated_need_ids: list[str] | None = None,
    skill_guidance: str = "",
    skills: list[str] | None = None,
    model: str = "unknown",
    prompt_version: str = "unknown",
    compressor: "ToolContextCompressor | None" = None,
) -> AgentContext:
    config = config or PolicyPilotConfig()
    recent = _recent(state.messages, config.max_recent_messages)
    compacted = []
    evidence_by_id = {e.tool_call_id: e for e in state.evidence if e.tool_call_id}
    for message in recent:
        if isinstance(message, ToolMessage) and message.id in evidence_by_id:
            content = evidence_by_id[message.id].summary[:config.max_context_tool_message_chars]
            compacted.append(message.model_copy(update={"content": content}))
        else:
            compacted.append(message)
    compacted = _bound_recent(compacted)
    summary = _summary(
        state,
        tools,
        config,
        memory_context,
        rehydrated_context,
    )
    skill_messages = (
        [SystemMessage(role="system", content=f"<decision_skill_guidance>\n{bound_channel('skills', skill_guidance)}\n</decision_skill_guidance>")]
        if skill_guidance
        else []
    )
    messages = [*state.system_messages, *skill_messages, SystemMessage(role="system", content=summary), *compacted]
    size = _estimated_size(messages)
    estimated_tokens = (size + 3) // 4
    over_budget = (
        size > config.max_decision_context_chars
        or estimated_tokens > config.max_decision_context_tokens
    )
    compressed = False
    if compressor is not None and over_budget:
        query_focus = " ".join(
            [
                state.goal.objective or "",
                *(criterion.value for criterion in state.goal.criteria),
                *(need.reason for need in state.open_needs()),
            ]
        )
        serialized = "\n\n".join(
            f"{message.role}: {message.content or ''}"
            for message in messages[1:]
        )
        try:
            content = compressor.compress_context(
                content=serialized,
                query_focus=query_focus,
                target_tokens=config.context_compressor_target_tokens,
            )
            latest_user = next(
                (message for message in reversed(compacted) if message.role == "user"),
                None,
            )
            messages = [
                *state.system_messages,
                SystemMessage(role="system", content=f"<compressed_context>{content}</compressed_context>"),
                *([latest_user] if latest_user is not None else []),
            ]
            size = _estimated_size(messages)
            compressed = True
            state.control.context_compressor_events.append(
                {"before_chars": len(serialized), "after_chars": size, "calls": 1}
            )
        except Exception as exc:
            state.control.context_compressor_events.append(
                {"before_chars": len(serialized), "after_chars": size, "calls": 1, "error": str(exc)[:200]}
            )
    selected_facts, selected_evidence, selected_needs = _selected_records(
        state, config, tools
    )
    manifest = ContextManifest(
        run_id=state.run_id,
        turn_id=len(state.messages),
        fact_ids=[item.id for item in selected_facts],
        evidence_ids=list(
            dict.fromkeys(
                [
                    *(item.evidence_id for item in selected_evidence),
                    *(rehydrated_evidence_ids or []),
                ]
            )
        ),
        need_ids=list(
            dict.fromkeys(
                [
                    *(item.id for item in selected_needs),
                    *(rehydrated_need_ids or []),
                ]
            )
        ),
        memory_ids=list(memory_ids or []),
        skills=list(skills or []),
        exposed_tools=[tool.name for tool in tools],
        model=model,
        prompt_version=prompt_version,
        metadata={
            "estimated_chars": size,
            "compressed": compressed,
            "rehydrated_refs": list(rehydrated_refs or []),
            "rehydrated_evidence_ids": list(rehydrated_evidence_ids or []),
            "rehydrated_need_ids": list(rehydrated_need_ids or []),
        },
    )
    manifest.metadata.update(
        {
            "channel_budgets": budget_manifest(),
            "channel_sizes": {
                "state_view": len(summary),
                "recent_messages": sum(len(item.content or "") for item in compacted),
                "skills": min(len(skill_guidance), CHANNEL_BUDGETS["skills"].maximum),
                "memory": min(len(memory_context), CHANNEL_BUDGETS["memory"].maximum),
                "rehydrated": min(
                    len(rehydrated_context),
                    CHANNEL_BUDGETS["rehydrated"].maximum,
                ),
            },
        }
    )
    state.context_manifests.append(manifest)
    return AgentContext(
        messages=messages,
        recent_messages=compacted,
        structured_summary=summary,
        estimated_size=size,
        context_id=manifest.context_id,
    )
