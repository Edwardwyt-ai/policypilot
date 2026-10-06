"""Public API contracts for the PolicyPilot backend."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CreateConversationRequest(BaseModel):
    metadata: dict[str, str] = Field(default_factory=dict)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ActionRequest(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class PendingActionView(BaseModel):
    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    created_at: datetime


class ConversationView(BaseModel):
    id: str
    status: Literal["ACTIVE", "AWAITING_CONFIRMATION"]
    version: int
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, str] = Field(default_factory=dict)
    pending_action: PendingActionView | None = None


class EventView(BaseModel):
    sequence: int
    type: str
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class TurnResponse(BaseModel):
    conversation: ConversationView
    assistant_message: str | None = None
    pending_action: PendingActionView | None = None
    tool_calls_executed: int = 0
    event_sequence: int


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "not_ready"]
    service: str = "policypilot-api"
    details: dict[str, Any] = Field(default_factory=dict)
