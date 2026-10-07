"""FastAPI application factory and local server entry point."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from policypilot.api.auth import ApiKeyAuthenticator, Identity
from policypilot.api.runtime import (
    BackendRuntimeSettings,
    DefaultRuntimeFactory,
    RuntimeConflictError,
    RuntimeLimitError,
)
from policypilot.api.schemas import (
    ActionRequest,
    ConversationView,
    CreateConversationRequest,
    HealthResponse,
    MessageRequest,
    TurnResponse,
)
from policypilot.api.service import (
    ConversationAccessError,
    ConversationNotFoundError,
    ConversationService,
)


@dataclass(frozen=True)
class BackendSettings:
    api_key: str
    host: str = "127.0.0.1"
    port: int = 8080

    @classmethod
    def from_env(cls) -> "BackendSettings":
        api_key = os.getenv("POLICYPILOT_BACKEND_API_KEY", "")
        if not api_key:
            raise RuntimeError("Set POLICYPILOT_BACKEND_API_KEY before starting the API.")
        return cls(
            api_key=api_key,
            host=os.getenv("POLICYPILOT_API_HOST", "127.0.0.1"),
            port=int(os.getenv("POLICYPILOT_API_PORT", "8080")),
        )


def create_app(
    *,
    settings: BackendSettings | None = None,
    service: ConversationService | None = None,
    runtime_factory: Any | None = None,
) -> FastAPI:
    settings = settings or BackendSettings.from_env()
    factory = runtime_factory or DefaultRuntimeFactory(
        BackendRuntimeSettings.from_env()
    )
    service = service or ConversationService(factory)
    authenticator = ApiKeyAuthenticator(settings.api_key)

    app = FastAPI(
        title="PolicyPilot API",
        version="1.0.0",
        description="Authenticated conversation API for PolicyPilot.",
    )
    app.state.conversation_service = service
    app.state.runtime_factory = factory

    static_dir = Path(__file__).with_name("static")
    app.mount("/ui-assets", StaticFiles(directory=static_dir), name="ui-assets")

    @app.get("/", include_in_schema=False)
    async def chat_ui() -> FileResponse:
        return FileResponse(static_dir / "ui.html")

    @app.exception_handler(ConversationNotFoundError)
    async def not_found_handler(_, __):
        return _json_error(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    @app.exception_handler(ConversationAccessError)
    async def access_handler(_, __):
        return _json_error(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    @app.exception_handler(RuntimeConflictError)
    async def conflict_handler(_, exc):
        return _json_error(status.HTTP_409_CONFLICT, str(exc))

    @app.exception_handler(RuntimeLimitError)
    async def limit_handler(_, exc):
        return _json_error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    identity_dependency = authenticator.dependency

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def ready() -> HealthResponse:
        readiness = getattr(factory, "readiness", None)
        ok, details = readiness() if readiness is not None else (True, {})
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "not_ready", "details": details},
            )
        return HealthResponse(status="ready", details=details)

    @app.post(
        "/v1/conversations",
        response_model=ConversationView,
        status_code=status.HTTP_201_CREATED,
        tags=["conversations"],
    )
    async def create_conversation(
        request: CreateConversationRequest,
        identity: Identity = Depends(identity_dependency),
    ) -> ConversationView:
        return await run_in_threadpool(service.create, identity.user_id, request.metadata)

    @app.get(
        "/v1/conversations/{conversation_id}",
        response_model=ConversationView,
        tags=["conversations"],
    )
    async def get_conversation(
        conversation_id: str,
        identity: Identity = Depends(identity_dependency),
    ) -> ConversationView:
        return service.get(identity.user_id, conversation_id)

    @app.post(
        "/v1/conversations/{conversation_id}/messages",
        response_model=TurnResponse,
        tags=["messages"],
    )
    async def send_message(
        conversation_id: str,
        request: MessageRequest,
        identity: Identity = Depends(identity_dependency),
    ) -> TurnResponse:
        return await run_in_threadpool(
            service.send,
            identity.user_id,
            conversation_id,
            request.content,
            request.request_id,
        )

    @app.post(
        "/v1/conversations/{conversation_id}/messages/stream",
        tags=["messages"],
    )
    async def stream_message(
        conversation_id: str,
        request: MessageRequest,
        identity: Identity = Depends(identity_dependency),
    ) -> StreamingResponse:
        async def stream():
            yield _sse("request.accepted", {"request_id": request.request_id})
            response = await run_in_threadpool(
                service.send,
                identity.user_id,
                conversation_id,
                request.content,
                request.request_id,
            )
            yield _sse("turn.completed", response.model_dump(mode="json"))

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post(
        "/v1/conversations/{conversation_id}/actions/{action_id}/confirm",
        response_model=TurnResponse,
        tags=["actions"],
    )
    async def confirm_action(
        conversation_id: str,
        action_id: str,
        request: ActionRequest,
        identity: Identity = Depends(identity_dependency),
    ) -> TurnResponse:
        return await run_in_threadpool(
            service.confirm,
            identity.user_id,
            conversation_id,
            action_id,
            request.request_id,
        )

    @app.post(
        "/v1/conversations/{conversation_id}/actions/{action_id}/cancel",
        response_model=TurnResponse,
        tags=["actions"],
    )
    async def cancel_action(
        conversation_id: str,
        action_id: str,
        request: ActionRequest,
        identity: Identity = Depends(identity_dependency),
    ) -> TurnResponse:
        return await run_in_threadpool(
            service.cancel,
            identity.user_id,
            conversation_id,
            action_id,
            request.request_id,
        )

    @app.get(
        "/v1/conversations/{conversation_id}/events",
        tags=["events"],
    )
    async def events(
        conversation_id: str,
        after: int = Query(default=0, ge=0),
        identity: Identity = Depends(identity_dependency),
    ) -> StreamingResponse:
        snapshot = service.events(identity.user_id, conversation_id, after)

        async def stream():
            for event in snapshot:
                yield _sse(event.type, event.model_dump(mode="json"))

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=True)}\n\n"


def _json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


def run() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    settings = BackendSettings.from_env()
    runtime_factory = DefaultRuntimeFactory(BackendRuntimeSettings.from_env())
    runtime_factory.prepare(repo_root)
    uvicorn.run(
        create_app(settings=settings, runtime_factory=runtime_factory),
        host=settings.host,
        port=settings.port,
    )
