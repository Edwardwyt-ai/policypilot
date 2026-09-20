"""Deterministic filtering, projection, range selection, and aggregation."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolProjection:
    content: str
    filtered_fields: int
    total_fields: int
    range_selected: bool
    aggregation: dict[str, Any]


_PRIORITY_FIELD = re.compile(
    r"(^|\.)(id|status|state|type|amount|balance|date|time|name|reason|result)$",
    re.I,
)


def _flatten(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def project_tool_result(
    raw_content: str,
    *,
    focus: str = "",
    max_fields: int = 40,
    max_chars: int = 1200,
) -> ToolProjection:
    """Create a bounded loss-aware view while raw payload remains externalized."""
    try:
        payload = json.loads(raw_content)
    except (TypeError, ValueError):
        compact = " ".join((raw_content or "").split())
        return ToolProjection(
            content=compact[:max_chars],
            filtered_fields=1,
            total_fields=1,
            range_selected=len(compact) > max_chars,
            aggregation={},
        )

    flattened = list(_flatten(payload))
    focus_tokens = set(re.findall(r"[a-z0-9]{3,}", focus.lower()))
    relevant = [
        item
        for item in flattened
        if _PRIORITY_FIELD.search(item[0])
        or focus_tokens.intersection(re.findall(r"[a-z0-9]{3,}", item[0].lower()))
    ]
    selected = relevant or flattened
    range_selected = len(selected) > max_fields
    if range_selected:
        head = max_fields // 2
        selected = [*selected[:head], *selected[-(max_fields - head) :]]

    status_counts = Counter(
        str(value)
        for path, value in flattened
        if re.search(r"(?:^|\.)(?:status|state)$", path, re.I)
    )
    aggregation: dict[str, Any] = {}
    if status_counts:
        aggregation["status_counts"] = dict(sorted(status_counts.items()))
    list_sizes = {
        path or "root": len(value)
        for path, value in _walk_lists(payload)
        if len(value) > 1
    }
    if list_sizes:
        aggregation["list_sizes"] = list_sizes

    projection = {
        "fields": {path: value for path, value in selected},
        "aggregation": aggregation,
    }
    rendered = json.dumps(projection, ensure_ascii=False, default=str)
    if len(rendered) > max_chars:
        rendered = rendered[: max_chars - 3] + "..."
    return ToolProjection(
        content=rendered,
        filtered_fields=len(selected),
        total_fields=len(flattened),
        range_selected=range_selected,
        aggregation=aggregation,
    )


def _walk_lists(value: Any, prefix: str = ""):
    if isinstance(value, list):
        yield prefix, value
        for index, item in enumerate(value):
            yield from _walk_lists(item, f"{prefix}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_lists(item, f"{prefix}.{key}" if prefix else str(key))
