from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from policypilot.api.app import BackendSettings, create_app
from policypilot.api.authorization import ToolAuthorizationError
from policypilot.api.runtime import RuntimeTurn, TauConversationRuntime
from policypilot.api.schemas import PendingActionView, utc_now
from tau2.data_model.message import (
    AssistantMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)

API_KEY = "test-backend-key"


class FakeRuntime:
    def __init__(self):
        self.pending_action = None
        self.send_count = 0

    def send(self, content: str) -> RuntimeTurn:
        self.send_count += 1
        if content == "perform a write":
            self.pending_action = PendingActionView(
                action_id="action-1",
                tool_name="update_account",
                arguments={"value": "new"},
                created_at=utc_now(),
            )
            return RuntimeTurn("Please confirm.", self.pending_action)
        return RuntimeTurn(f"reply:{content}", tool_calls_executed=1)

    def confirm(self, action_id: str) -> RuntimeTurn:
        assert self.pending_action is not None
        assert self.pending_action.action_id == action_id
        self.pending_action = None
        return RuntimeTurn("Write confirmed.", tool_calls_executed=1)

    def cancel(self, action_id: str) -> RuntimeTurn:
        assert self.pending_action is not None
        assert self.pending_action.action_id == action_id
        self.pending_action = None
        return RuntimeTurn("Write cancelled.")


class FakeRuntimeFactory:
    def __init__(self):
        self.runtimes: dict[str, FakeRuntime] = {}

    def __call__(self, user_id: str, conversation_id: str) -> FakeRuntime:
        runtime = FakeRuntime()
        self.runtimes[conversation_id] = runtime
        return runtime

    @staticmethod
    def readiness():
        return True, {"runtime": "fake"}


def _headers(user_id: str = "user-1") -> dict[str, str]:
    token = API_KEY if user_id == "user-1" else f"test-key-{user_id}"
    return {"Authorization": f"Bearer {token}", "X-User-ID": user_id}


def _client() -> tuple[TestClient, FakeRuntimeFactory]:
    factory = FakeRuntimeFactory()
    app = create_app(
        settings=BackendSettings(
            api_key=API_KEY,
            user_id="user-1",
            user_tokens={
                "test-key-owner": "owner",
                "test-key-other-user": "other-user",
            },
        ),
        runtime_factory=factory,
    )
    return TestClient(app), factory


def _conversation(client: TestClient, user_id: str = "user-1") -> str:
    response = client.post(
        "/v1/conversations",
        headers=_headers(user_id),
        json={"metadata": {"channel": "test"}},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_health_and_authentication_boundary():
    client, _ = _client()

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").json()["status"] == "ready"
    assert client.post("/v1/conversations", json={}).status_code == 401
    assert (
        client.post(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={},
        ).status_code
        == 201
    )
    assert client.get("/v1/me", headers=_headers()).json() == {"user_id": "user-1"}
    assert (
        client.post(
            "/v1/conversations",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "X-User-ID": "victim",
            },
            json={},
        ).status_code
        == 403
    )


def test_chat_ui_and_static_assets_are_served_without_api_authentication():
    client, _ = _client()

    page = client.get("/")
    script = client.get("/ui-assets/app.js")
    stylesheet = client.get("/ui-assets/styles.css")

    assert page.status_code == 200
    assert "PolicyPilot" in page.text
    assert "政策与账户助手" in page.text
    assert script.status_code == 200
    assert "sendMessage" in script.text
    assert stylesheet.status_code == 200
    assert ".chat-workspace" in stylesheet.text


def test_conversations_are_owned_by_authenticated_user():
    client, _ = _client()
    conversation_id = _conversation(client, "owner")

    response = client.get(
        f"/v1/conversations/{conversation_id}", headers=_headers("other-user")
    )

    assert response.status_code == 404


def test_message_request_is_idempotent_and_events_are_available():
    client, factory = _client()
    conversation_id = _conversation(client)
    payload = {"content": "hello", "request_id": "message-1"}

    first = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_headers(),
        json=payload,
    )
    second = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_headers(),
        json=payload,
    )
    events = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers=_headers(),
    )

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["assistant_message"] == "reply:hello"
    assert factory.runtimes[conversation_id].send_count == 1
    assert "event: message.completed" in events.text


def test_mutation_requires_explicit_confirmation():
    client, _ = _client()
    conversation_id = _conversation(client)

    proposed = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_headers(),
        json={"content": "perform a write"},
    )
    action_id = proposed.json()["pending_action"]["action_id"]
    blocked = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_headers(),
        json={"content": "another message"},
    )
    confirmed = client.post(
        f"/v1/conversations/{conversation_id}/actions/{action_id}/confirm",
        headers=_headers(),
        json={"request_id": "confirm-1"},
    )

    assert proposed.json()["conversation"]["status"] == "AWAITING_CONFIRMATION"
    assert blocked.status_code == 409
    assert confirmed.status_code == 200
    assert confirmed.json()["conversation"]["status"] == "ACTIVE"
    assert confirmed.json()["assistant_message"] == "Write confirmed."


def test_mutation_can_be_cancelled():
    client, _ = _client()
    conversation_id = _conversation(client)
    proposed = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=_headers(),
        json={"content": "perform a write"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation_id}/actions/"
        f"{proposed['pending_action']['action_id']}/cancel",
        headers=_headers(),
        json={},
    )

    assert response.status_code == 200
    assert response.json()["conversation"]["status"] == "ACTIVE"


class DummyState(BaseModel):
    steps: int = 0


class DummyGuard:
    @staticmethod
    def classify(name: str) -> str:
        return "mutation" if name == "write_tool" else "transaction_read"


class DummyAgent:
    guard = DummyGuard()

    @staticmethod
    def get_init_state() -> DummyState:
        return DummyState()

    @staticmethod
    def generate_next_message(message, state: DummyState):
        state.steps += 1
        if isinstance(message, UserMessage) and message.content == "write":
            return (
                AssistantMessage.text(
                    "Confirm write.",
                    tool_calls=[
                        ToolCall(id="write-1", name="write_tool", arguments={"x": 1})
                    ],
                ),
                state,
            )
        if isinstance(message, UserMessage):
            return (
                AssistantMessage.text(
                    "",
                    tool_calls=[ToolCall(id="read-1", name="read_tool", arguments={})],
                ),
                state,
            )
        return AssistantMessage.text("done"), state


@dataclass
class DummyEnvironment:
    calls: list[str]

    def get_response(self, call: ToolCall) -> ToolMessage:
        self.calls.append(call.name)
        return ToolMessage(
            id=call.id,
            role="tool",
            content="ok",
            requestor="assistant",
        )


def test_tau_runtime_executes_reads_but_stages_mutations():
    environment = DummyEnvironment([])
    runtime = TauConversationRuntime(DummyAgent(), environment)

    read_turn = runtime.send("read")
    write_turn = runtime.send("write")

    assert read_turn.assistant_message == "done"
    assert environment.calls == ["read_tool"]
    assert write_turn.pending_action is not None
    assert environment.calls == ["read_tool"]

    completed = runtime.confirm(write_turn.pending_action.action_id)

    assert environment.calls == ["read_tool", "write_tool"]
    assert completed.assistant_message == "done"
    assert runtime.state.steps == 4


def test_runtime_denies_entire_batch_before_any_execution():
    class BatchAgent(DummyAgent):
        @staticmethod
        def generate_next_message(message, state):
            return AssistantMessage.text(
                "",
                tool_calls=[
                    ToolCall(id="own", name="read_tool", arguments={}),
                    ToolCall(id="foreign", name="read_tool", arguments={}),
                ],
            ), state

    class Authorizer:
        def authorize(self, call):
            if call.id == "foreign":
                raise ToolAuthorizationError("foreign resource")

    environment = DummyEnvironment([])
    runtime = TauConversationRuntime(BatchAgent(), environment, authorizer=Authorizer())
    with pytest.raises(ToolAuthorizationError):
        runtime.send("read")
    assert not environment.calls


def test_confirmation_rechecks_authorization_and_retains_pending_on_denial():
    class Authorizer:
        allowed = True

        def authorize(self, call):
            if not self.allowed:
                raise ToolAuthorizationError("ownership changed")

    environment, authorizer = DummyEnvironment([]), Authorizer()
    runtime = TauConversationRuntime(DummyAgent(), environment, authorizer=authorizer)
    turn = runtime.send("write")
    authorizer.allowed = False
    with pytest.raises(ToolAuthorizationError):
        runtime.confirm(turn.pending_action.action_id)
    assert not environment.calls
    assert runtime.pending_action == turn.pending_action
