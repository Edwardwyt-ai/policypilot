"""Offline storage contract tests; SQLite is an explicit test adapter only."""

from __future__ import annotations

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from policypilot.api.persistence import PersistentConversationService
from policypilot.api.runtime import (
    RuntimeConflictError,
    RuntimeTurn,
    TauConversationRuntime,
)
from policypilot.api.schemas import PendingActionView, utc_now
from policypilot.api.service import ConversationAccessError
from policypilot.state import PolicyPilotState
from policypilot.storage.checkpoint import SqlCheckpointStore
from policypilot.storage.database import (
    ArtifactStore,
    Database,
    S3ArtifactStore,
    StorageConflictError,
)
from policypilot.storage.memory import SqlMemoryStore
from tau2.data_model.message import ToolCall
from tau2.knowledge.cache_backend import RedisCacheBackend

pytest.importorskip("sqlalchemy")
pytest.importorskip("boto3")
RedisConnectionError = pytest.importorskip("redis.exceptions").ConnectionError


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path)
    yield db
    db.engine.dispose()


def test_no_implicit_sqlite_fallback(monkeypatch):
    monkeypatch.delenv("POLICYPILOT_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="start services"):
        Database()


def test_large_snapshot_artifact_and_checksum(database):
    value = {"text": "x" * 20000}
    database.put("snapshots", "one", value)
    assert database.get("snapshots", "one") == value
    with database.connect() as conn:
        payload = conn.execute(
            database.sa.select(database.objects.c.payload)
        ).scalar_one()
    digest = json.loads(payload)["artifact_sha256"]
    (database.artifacts.root / digest[:2] / digest).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        database.get("snapshots", "one")


def test_artifact_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError, match="digest"):
        ArtifactStore(tmp_path).get("../secret")


def test_memory_revision_isolation_and_restart(database):
    store = SqlMemoryStore(database)
    profile = store.load_profile("alice")
    profile.revision = 1
    store.save_profile(profile)
    with pytest.raises(StorageConflictError):
        store.save_profile(profile.model_copy(deep=True))
    restarted = Database(database.root)
    try:
        assert SqlMemoryStore(restarted).load_profile("alice").revision == 1
        assert SqlMemoryStore(restarted).load_profile("bob").revision == 0
    finally:
        restarted.engine.dispose()


def test_checkpoints_roundtrip(database):
    store = SqlCheckpointStore(database)
    state = PolicyPilotState(system_messages=[])
    store.save("task-x", state)
    assert store.load("task-x") == state
    assert store.load("missing") is None
    store.delete("task-x")
    assert store.load("task-x") is None


class DurableFakeRuntime:
    pending_action = None
    calls = 0
    entered = None
    release = None
    fail = False

    def export_snapshot(self):
        return {"pending": None, "calls": self.calls}

    def restore_snapshot(self, snapshot):
        self.calls = snapshot["calls"]

    def send(self, content):
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        if self.fail:
            raise RuntimeError("uncertain write")
        self.calls += 1
        return RuntimeTurn(f"{content}:{self.calls}")


def factory(_user, _conversation):
    return DurableFakeRuntime()


def test_conversation_restart_receipt_and_ownership(database):
    service = PersistentConversationService(factory, database)
    conv = service.create("alice", {})
    first = service.send("alice", conv.id, "hello", "request-1")
    restarted = PersistentConversationService(factory, database)
    assert restarted.send("alice", conv.id, "hello", "request-1") == first
    assert (
        restarted.send("alice", conv.id, "again", "request-2").assistant_message
        == "again:2"
    )
    assert restarted.events("alice", conv.id)[-1].type == "message.completed"
    with pytest.raises(RuntimeConflictError, match="different arguments"):
        restarted.send("alice", conv.id, "changed", "request-1")
    with pytest.raises(ConversationAccessError):
        restarted.get("bob", conv.id)


def test_interrupted_execution_is_not_replayed(database):
    def fail_factory(_user, _id):
        runtime = DurableFakeRuntime()
        runtime.fail = True
        return runtime

    service = PersistentConversationService(fail_factory, database)
    conv = service.create("alice", {})
    with pytest.raises(RuntimeError, match="uncertain"):
        service.send("alice", conv.id, "write", "request-1")
    restarted = PersistentConversationService(factory, database)
    with pytest.raises(RuntimeConflictError, match="interrupted"):
        restarted.send("alice", conv.id, "write", "request-1")


def test_concurrent_workers_cannot_execute_same_conversation(database):
    entered, release = Event(), Event()

    def blocking_factory(_user, _id):
        runtime = DurableFakeRuntime()
        runtime.entered, runtime.release = entered, release
        return runtime

    service = PersistentConversationService(blocking_factory, database)
    conv = service.create("alice", {})
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.send, "alice", conv.id, "hello", "r1")
        try:
            assert entered.wait(5)
            with pytest.raises(RuntimeConflictError, match="running"):
                PersistentConversationService(factory, database).send(
                    "alice", conv.id, "hello", "r1"
                )
        finally:
            release.set()
        assert future.result().assistant_message == "hello:1"


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttl = None

    def set(self, key, value, ex):
        self.values[key] = value
        self.ttl = ex

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


def test_redis_json_ttl_and_invalid_entries():
    client = FakeRedis()
    cache = RedisCacheBackend(url="redis://unused", client=client, ttl_seconds=12)
    cache.set("query", {"ids": ["doc-1"]})
    assert cache.get("query") == {"ids": ["doc-1"]}
    assert client.ttl == 12
    client.values[cache.prefix + "query"] = "not JSON"
    assert cache.get("query") is None
    cache.delete("query")


def test_redis_outage_is_only_cache_miss():
    class Unavailable(FakeRedis):
        def get(self, key):
            raise RedisConnectionError("offline")

        def set(self, key, value, ex):
            raise RedisConnectionError("offline")

    cache = RedisCacheBackend(url="redis://unused", client=Unavailable())
    assert cache.get("query") is None
    cache.set("query", "answer")


def test_s3_artifact_roundtrip_without_live_server(monkeypatch):
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    for key, value in {
        "ENDPOINT": "http://127.0.0.1:19000",
        "BUCKET": "test-bucket",
        "ACCESS_KEY": "test-access",
        "SECRET_KEY": "test-secret",
    }.items():
        monkeypatch.setenv(f"POLICYPILOT_S3_{key}", value)
    store = S3ArtifactStore()
    content = b"snapshot"
    digest = hashlib.sha256(content).hexdigest()
    with Stubber(store.client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": store.bucket,
                "Key": f"sha256/{digest}",
                "Body": content,
                "ContentType": "application/octet-stream",
                "Metadata": {"sha256": digest},
            },
        )
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(content), len(content))},
            {"Bucket": store.bucket, "Key": f"sha256/{digest}"},
        )
        assert store.get(store.put(content)) == content
        stub.assert_no_pending_responses()


def test_runtime_restores_simulated_db_and_pending_confirmation():
    from policypilot.api.runtime import _PendingExecution

    class TestDB(BaseModel):
        value: int = 0

    def runtime(value):
        db = TestDB(value=value)
        environment = SimpleNamespace(
            tools=SimpleNamespace(db=db),
            user_tools=SimpleNamespace(db=db),
            sync_tools=lambda: None,
        )
        agent = SimpleNamespace(
            get_init_state=lambda: PolicyPilotState(system_messages=[]),
            llm_runtime=SimpleNamespace(snapshot=lambda: [], traces=[]),
        )
        return TauConversationRuntime(agent, environment)

    original = runtime(42)
    view = PendingActionView(
        action_id="pending-id",
        tool_name="update_account",
        arguments={},
        created_at=utc_now(),
    )
    original._pending = _PendingExecution(
        view,
        ToolCall(id="call-id", name="update_account", arguments={}),
        original.state.model_copy(deep=True),
    )
    restarted = runtime(0)
    restarted.restore_snapshot(original.export_snapshot())
    assert restarted.environment.tools.db.value == 42
    assert restarted.environment.tools.db is restarted.environment.user_tools.db
    assert restarted.pending_action == view
    assert restarted.cancel("pending-id").assistant_message
    assert restarted.pending_action is None


def test_legacy_import_is_idempotent_and_preserves_source(database, tmp_path):
    import importlib.util
    from pathlib import Path

    from policypilot.memory.models import UserProfile

    path = Path(__file__).resolve().parents[2] / "scripts/migrate_storage.py"
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    memory_dir = tmp_path / "legacy"
    (memory_dir / "profiles").mkdir(parents=True)
    profile = UserProfile(subject_key=SqlMemoryStore.subject_key("alice"), revision=1)
    source = memory_dir / "profiles/alice.json"
    source.write_text(profile.model_dump_json(), encoding="utf-8")
    original = source.read_bytes()
    first = module.migrate(database, memory_dir, tmp_path / "checkpoints")
    second = module.migrate(database, memory_dir, tmp_path / "checkpoints")
    assert first["profiles"] == 1
    assert second["profiles"] == 0 and second["skipped"] == 1
    assert source.read_bytes() == original
