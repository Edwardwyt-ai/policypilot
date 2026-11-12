"""Durable conversations and request receipts with execution reservations."""

from __future__ import annotations

import hashlib
import json

from policypilot.api.runtime import RuntimeConflictError
from policypilot.api.schemas import (
    ConversationView,
    EventView,
    PendingActionView,
    TurnResponse,
    utc_now,
)
from policypilot.api.service import (
    ConversationAccessError,
    ConversationNotFoundError,
    ConversationService,
    _ConversationRecord,
)
from policypilot.storage.database import Database


class PersistentConversationService(ConversationService):
    def __init__(self, runtime_factory, database: Database):
        super().__init__(runtime_factory)
        self.database = database

    def create(self, user_id, metadata):
        view = super().create(user_id, metadata)
        record = self._records.pop(view.id)
        payload = self.database.encode(self._snapshot(record))
        with self.database.connect() as conn:
            conn.execute(
                self.database.conversations.insert().values(
                    id=record.id, user_id=user_id, payload=payload, busy=False
                )
            )
        return view

    @staticmethod
    def _snapshot(record):
        return {
            "schema_version": 1,
            "id": record.id,
            "user_id": record.user_id,
            "metadata": record.metadata,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "version": record.version,
            "events": [event.model_dump(mode="json") for event in record.events],
            "runtime": record.runtime.export_snapshot(),
        }

    def _row(self, conn, user_id, conversation_id):
        table = self.database.conversations
        row = (
            conn.execute(
                self.database.sa.select(table).where(table.c.id == conversation_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ConversationNotFoundError(conversation_id)
        if row["user_id"] != user_id:
            raise ConversationAccessError(conversation_id)
        return row

    def _payload(self, user_id, conversation_id):
        with self.database.connect() as conn:
            row = self._row(conn, user_id, conversation_id)
        return self.database.decode(row["payload"])

    def get(self, user_id, conversation_id):
        payload = self._payload(user_id, conversation_id)
        pending = payload["runtime"].get("pending")
        return ConversationView(
            id=payload["id"],
            status="AWAITING_CONFIRMATION" if pending else "ACTIVE",
            version=payload["version"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            metadata=payload["metadata"],
            pending_action=PendingActionView.model_validate(pending["view"])
            if pending
            else None,
        )

    def events(self, user_id, conversation_id, after=0):
        payload = self._payload(user_id, conversation_id)
        return [
            EventView.model_validate(event)
            for event in payload["events"]
            if event["sequence"] > after
        ]

    def _restore(self, payload):
        from datetime import datetime

        runtime = self.runtime_factory(payload["user_id"], payload["id"])
        runtime.restore_snapshot(payload["runtime"])
        return _ConversationRecord(
            id=payload["id"],
            user_id=payload["user_id"],
            runtime=runtime,
            metadata=payload["metadata"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            version=payload["version"],
            events=[EventView.model_validate(e) for e in payload["events"]],
        )

    def _execute(self, operation, user_id, conversation_id, value, request_id):
        db = self.database
        table = db.conversations
        fingerprint = hashlib.sha256(
            json.dumps([operation, value], ensure_ascii=True).encode()
        ).hexdigest()
        namespace = f"receipts:{conversation_id}"
        key = (
            hashlib.sha256(f"{operation}:{request_id}".encode()).hexdigest()
            if request_id
            else None
        )
        with db.connect(lock=f"conversation:{conversation_id}") as conn:
            row = self._row(conn, user_id, conversation_id)
            if key:
                receipt = conn.execute(
                    db.sa.select(db.objects.c.payload).where(
                        db.objects.c.namespace == namespace, db.objects.c.key == key
                    )
                ).first()
                if receipt:
                    receipt = db.decode(receipt[0])
                    if receipt["fingerprint"] != fingerprint:
                        raise RuntimeConflictError(
                            "request_id was already used with different arguments"
                        )
                    return TurnResponse.model_validate(receipt["response"])
            if row["busy"]:
                raise RuntimeConflictError(
                    "Conversation is running or interrupted; reconcile its last operation before retrying"
                )
            payload = db.decode(row["payload"])
            pending = payload["runtime"].get("pending")
            if (operation == "message" and pending) or (
                operation != "message"
                and (not pending or pending["view"]["action_id"] != value)
            ):
                raise RuntimeConflictError("Pending action does not match this request")
            inflight = json.dumps(
                {
                    "operation": operation,
                    "request_id": request_id,
                    "fingerprint": fingerprint,
                    "started_at": utc_now().isoformat(),
                }
            )
            conn.execute(
                table.update()
                .where(table.c.id == conversation_id)
                .values(busy=True, inflight=inflight)
            )
        # No database transaction is held while models/tools execute. Exceptions
        # keep the reservation durable; uncertain writes must never auto-replay.
        record = self._restore(payload)
        method = getattr(
            record.runtime,
            {"message": "send", "confirm": "confirm", "cancel": "cancel"}[operation],
        )
        self._append_event(record, f"{operation}.accepted", {"request_id": request_id})
        completion = {
            "message": "message.completed",
            "confirm": "action.completed",
            "cancel": "action.cancelled",
        }[operation]
        response = self._finish_turn(record, method(value), completion)
        encoded = db.encode(self._snapshot(record))
        with db.connect(lock=f"conversation:{conversation_id}") as conn:
            conn.execute(
                table.update()
                .where(table.c.id == conversation_id)
                .values(payload=encoded, busy=False, inflight=None)
            )
            if key:
                db.write(
                    conn,
                    namespace,
                    key,
                    db.encode(
                        {
                            "fingerprint": fingerprint,
                            "response": response.model_dump(mode="json"),
                        }
                    ),
                )
        return response

    def send(self, user_id, conversation_id, content, request_id):
        return self._execute("message", user_id, conversation_id, content, request_id)

    def confirm(self, user_id, conversation_id, action_id, request_id):
        return self._execute("confirm", user_id, conversation_id, action_id, request_id)

    def cancel(self, user_id, conversation_id, action_id, request_id):
        return self._execute("cancel", user_id, conversation_id, action_id, request_id)
