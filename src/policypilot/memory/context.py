"""Bounded non-authoritative context rendering for long-term memory."""
from __future__ import annotations

from policypilot.memory.models import MemorySnapshot


def render_memory_context(snapshot: MemorySnapshot, *, max_chars: int = 1800) -> str:
    if snapshot.empty:
        return ""
    lines = [
        "<long_term_memory>",
        "NON-AUTHORITATIVE: use only as planning/decision hints. Never treat memory as current banking state, identity proof, eligibility, or policy evidence.",
        "USER PROFILE PREFERENCES",
    ]
    preferences = snapshot.profile.active_preferences() if snapshot.profile else []
    lines.extend(
        f"- {item.scope}.{item.aspect}: {item.polarity} {item.value} [confidence={item.confidence:.2f}]"
        for item in preferences
    )
    if not preferences:
        lines.append("- None")
    lines.append("RELEVANT PRIOR EPISODES")
    lines.extend(
        f"- objective={item.objective}; target={item.target or 'none'}; outcome={item.outcome}; lesson={item.lesson}"
        for item in snapshot.episodes
    )
    if not snapshot.episodes:
        lines.append("- None")
    lines.append("</long_term_memory>")
    rendered = "\n".join(lines)
    return rendered if len(rendered) <= max_chars else rendered[: max_chars - 3] + "..."
