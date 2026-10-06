"""Thread-safe in-process conversation service for the HTTP layer."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from uuid import uuid4

from policypilot.api.runtime import (
    ConversationRuntime,
    RuntimeConflictError,
    RuntimeFactory,
    RuntimeTurn,
)
from policypilot.api.schemas import (
    ConversationView,
    EventView,
    TurnResponse,
    utc_now,
)


class ConversationNotFoundError(LookupError):
    pass


class ConversationAccessError(PermissionError):
    pass


@dataclass
class _ConversationRecord:
    id: str
    user_id: str
    runtime: ConversationRuntime
    metadata: dict[str, str]
    created_at: Any
    updated_at: Any
    version: int = 1
    events: list[EventView] = field(default_factory=list)
    idempotency: dict[str, TurnResponse] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)


class ConversationService:
    def __init__(self, runtime_factory: RuntimeFactory):
        self.runtime_factory = runtime_factory
        self._records: dict[str, _ConversationRecord] = {}
        self._lock = RLock()

    def create(self, user_id: str, metadata: dict[str, str]) -> ConversationView:
        conversation_id = str(uuid4())
        runtime = self.runtime_factory(user_id, conversation_id)
        now = utc_now()
        record = _ConversationRecord(
            id=conversation_id,
            user_id=user_id,
            runtime=runtime,
            metadata=deepcopy(metadata),
            created_at=now,
            updated_at=now,
        )
        self._append_event(record, "conversation.created", {})
        with self._lock:
            self._records[conversation_id] = record
        return self._view(record)

    def get(self, user_id: str, conversation_id: str) -> ConversationView:
        return self._view(self._owned_record(user_id, conversation_id))

    def send(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        request_id: str | None,
    ) -> TurnResponse:
        record = self._owned_record(user_id, conversation_id)
        with record.lock:
            cached = self._cached(record, "message", request_id)
            if cached is not None:
                return cached
            if record.runtime.pending_action is not None:
                raise RuntimeConflictError("Confirm or cancel the pending action first.")
            self._append_event(record, "message.accepted", {"request_id": request_id})
            turn = record.runtime.send(content)
            response = self._finish_turn(record, turn, "message.completed")
            self._cache(record, "message", request_id, response)
            return response

    def confirm(
        self,
        user_id: str,
        conversation_id: str,
        action_id: str,
        request_id: str | None,
    ) -> TurnResponse:
        record = self._owned_record(user_id, conversation_id)
        with record.lock:
            cached = self._cached(record, "confirm", request_id)
            if cached is not None:
                return cached
            self._append_event(record, "action.confirmed", {"action_id": action_id})
            turn = record.runtime.confirm(action_id)
            response = self._finish_turn(record, turn, "action.completed")
            self._cache(record, "confirm", request_id, response)
            return response

    def cancel(
        self,
        user_id: str,
        conversation_id: str,
        action_id: str,
        request_id: str | None,
    ) -> TurnResponse:
        record = self._owned_record(user_id, conversation_id)
        with record.lock:
            cached = self._cached(record, "cancel", request_id)
            if cached is not None:
                return cached
            turn = record.runtime.cancel(action_id)
            response = self._finish_turn(record, turn, "action.cancelled")
            self._cache(record, "cancel", request_id, response)
            return response

    def events(
        self, user_id: str, conversation_id: str, after: int = 0
    ) -> list[EventView]:
        record = self._owned_record(user_id, conversation_id)
        with record.lock:
            return [event.model_copy(deep=True) for event in record.events if event.sequence > after]

    def _owned_record(self, user_id: str, conversation_id: str) -> _ConversationRecord:
        with self._lock:
            record = self._records.get(conversation_id)
        if record is None:
            raise ConversationNotFoundError(conversation_id)
        if record.user_id != user_id:
            raise ConversationAccessError(conversation_id)
        return record

    def _finish_turn(
        self, record: _ConversationRecord, turn: RuntimeTurn, event_type: str
    ) -> TurnResponse:
        record.version += 1
        record.updated_at = utc_now()
        event = self._append_event(
            record,
            event_type,
            {
                "has_pending_action": turn.pending_action is not None,
                "tool_calls_executed": turn.tool_calls_executed,
            },
        )
        return TurnResponse(
            conversation=self._view(record),
            assistant_message=turn.assistant_message,
            pending_action=turn.pending_action,
            tool_calls_executed=turn.tool_calls_executed,
            event_sequence=event.sequence,
        )

    @staticmethod
    def _view(record: _ConversationRecord) -> ConversationView:
        pending = record.runtime.pending_action
        return ConversationView(
            id=record.id,
            status="AWAITING_CONFIRMATION" if pending else "ACTIVE",
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=deepcopy(record.metadata),
            pending_action=pending,
        )

    @staticmethod
    def _append_event(
        record: _ConversationRecord, event_type: str, payload: dict[str, Any]
    ) -> EventView:
        event = EventView(
            sequence=len(record.events) + 1,
            type=event_type,
            created_at=utc_now(),
            payload=payload,
        )
        record.events.append(event)
        return event

    @staticmethod
    def _key(operation: str, request_id: str) -> str:
        return f"{operation}:{request_id}"

    def _cached(
        self, record: _ConversationRecord, operation: str, request_id: str | None
    ) -> TurnResponse | None:
        if request_id is None:
            return None
        cached = record.idempotency.get(self._key(operation, request_id))
        return cached.model_copy(deep=True) if cached is not None else None

    def _cache(
        self,
        record: _ConversationRecord,
        operation: str,
        request_id: str | None,
        response: TurnResponse,
    ) -> None:
        if request_id is not None:
            record.idempotency[self._key(operation, request_id)] = response.model_copy(
                deep=True
            )
