"""No external models, Collector or platform needed for telemetry contracts."""

from contextlib import ExitStack
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tau2.utils import telemetry as t

ROOT = Path(__file__).resolve().parents[2]


class FakeSpan:
    def __init__(self, name, parent, kind, metadata):
        self.name, self.parent, self.kind = name, parent, kind
        self.metadata = metadata
        self.updates = []

    def update(self, **values):
        self.updates.append(values)


class FakeBackend:
    def __init__(self):
        self.active = ContextVar("test_span", default=None)
        self.spans = []

    def start(self, name, kind, metadata, model, session_id):
        span = FakeSpan(name, self.active.get(), kind, metadata)
        self.spans.append(span)
        token = self.active.set(span)
        stack = ExitStack()
        stack.callback(self.active.reset, token)
        return stack, span


@pytest.fixture
def backend(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(t, "_backend", backend)
    monkeypatch.setattr(t, "_initialized", True)
    return backend


def test_nested_spans_and_exception_do_not_change_business_behavior(backend):
    error = RuntimeError("SECRET banking data")
    with pytest.raises(RuntimeError) as caught:
        with t.observe("request"):
            with t.observe("tool"):
                raise error
    assert caught.value is error
    root, child = backend.spans
    assert child.parent is root
    assert backend.active.get() is None
    assert "SECRET" not in repr(root.updates + child.updates)
    assert child.updates[-1]["level"] == "ERROR"


def test_span_creation_failure_does_not_skip_or_repeat_business(backend, monkeypatch):
    def fail(*args):
        raise RuntimeError("export failure")

    monkeypatch.setattr(backend, "start", fail)
    count = 0
    with t.observe("request"):
        count += 1
    assert count == 1


def test_span_completion_failure_cannot_replace_result(backend, monkeypatch):
    class BrokenStack:
        def close(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        backend, "start", lambda *args: (BrokenStack(), FakeSpan("x", None, "span", {}))
    )
    with t.observe("request"):
        result = "business result"
    assert result == "business result"


def test_metadata_does_not_export_content_or_raw_identifiers():
    cleaned = t.safe_metadata(
        {
            "input": "secret",
            "password": "secret",
            "query": "secret",
            "run_id": "user-sensitive-run",
            "need_id": "user-sensitive-need",
            "status": "contains an email",
            "coverage": "MATCH",
            "need_count": 3,
        }
    )
    assert set(cleaned) == {"run_id", "need_id", "coverage", "need_count"}
    assert "secret" not in repr(cleaned)
    assert "user-sensitive" not in repr(cleaned)


def test_update_preserves_initial_metadata(backend):
    with t.observe("test", metadata={"node": "decision"}) as span:
        span.update(metadata={"cost_available": False})
    assert backend.spans[-1].updates[-1]["metadata"] == {
        "node": "decision",
        "cost_available": False,
    }


def test_evaluator_suppression(backend):
    with t.observe("episode"):
        with t.suppress():
            with t.observe("hidden-evaluator-operation"):
                assert t.current_ids() == {}
    assert [span.name for span in backend.spans] == ["episode"]


@pytest.mark.parametrize(
    "url",
    [
        "http://external-host:4318",
        "https://user:secret@host",
        "https://host?key=secret",
    ],
)
def test_unsafe_destination_rejected(url):
    settings = t.TelemetrySettings(
        endpoint=url,
        token="local",
        public_key="public",
        secret_key="private",
        base_url="https://platform",
    )
    with pytest.raises(ValueError):
        settings.validate()


def test_disabled_mode_never_imports_sdk(monkeypatch):
    monkeypatch.setattr(t, "_initialized", False)
    monkeypatch.setattr(t, "_backend", None)
    monkeypatch.setenv("POLICYPILOT_OBSERVABILITY_ENABLED", "0")
    monkeypatch.setattr(
        t, "_LangfuseBackend", lambda _: pytest.fail("SDK must not initialize")
    )
    with t.observe("disabled"):
        pass
    assert t.current_ids() == {}


def test_unavailable_sdk_fails_open_once(monkeypatch):
    calls = []

    def unavailable(_):
        calls.append(1)
        raise ImportError("SDK unavailable")

    monkeypatch.setattr(t, "_initialized", False)
    monkeypatch.setattr(t, "_backend", None)
    monkeypatch.setenv("POLICYPILOT_OBSERVABILITY_ENABLED", "1")
    monkeypatch.setattr(t, "_LangfuseBackend", unavailable)
    with t.observe("one"):
        pass
    with t.observe("two"):
        pass
    assert len(calls) == 1


def test_llm_span_usage_and_payload_boundary(backend):
    from policypilot.llm_runtime import LLMRuntime
    from policypilot.model_routing import ModelRouting
    from tau2.data_model.message import AssistantMessage, UserMessage

    runtime = LLMRuntime(
        ModelRouting(light_model="fake/light", main_model="fake/main"),
        generate_fn=lambda **_: AssistantMessage(
            role="assistant",
            content="PRIVATE OUTPUT",
            usage={"prompt_tokens": 10, "completion_tokens": 4},
            cost=0.01,
        ),
    )
    result = runtime.call_message("decision", [UserMessage.text("PRIVATE INPUT")])
    assert result.content == "PRIVATE OUTPUT"
    span = backend.spans[-1]
    assert span.kind == "generation"
    assert span.updates[-1]["usage_details"] == {"input": 10, "output": 4}
    assert span.updates[-1]["cost_details"] == {"total": 0.01}
    assert "PRIVATE" not in repr(span.__dict__)


def test_node_wrapper_preserves_output(backend):
    state = SimpleNamespace(
        control=SimpleNamespace(
            need_registry_events=[],
            retrieval_events=[],
            acquisition_events=[],
            progress_events=[],
        ),
        information_needs=[],
        evidence=[],
        mutations=[],
        tool_history=[],
    )
    expected = {"policy_state": state}
    result = t.instrument_node(lambda gs: expected, "route_need")(
        {"policy_state": state}
    )
    assert result is expected
    assert backend.spans[-1].updates[-1]["metadata"]["need_count"] == 0


def test_node_metadata_failure_does_not_repeat_or_replace_business(backend):
    calls = []
    expected = {"policy_state": object()}

    def node(gs):
        calls.append(gs)
        return expected

    assert t.instrument_node(node, "test")({"policy_state": object()}) is expected
    assert len(calls) == 1


def test_disabled_node_wrapper_does_not_inspect_business_state(monkeypatch):
    monkeypatch.setattr(t, "_get_backend", lambda: None)
    expected = {"unrelated": "result"}
    assert t.instrument_node(lambda _: expected, "test")({}) is expected


def test_http_parent_survives_threadpool_and_streaming(backend):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    from policypilot.observability.http import TelemetryMiddleware

    app = FastAPI()
    app.add_middleware(TelemetryMiddleware)

    @app.get("/conversations/{conversation_id}")
    def endpoint(conversation_id: str):
        with t.observe("worker"):
            pass

        async def body():
            with t.observe("stream"):
                yield b"private response"

        return StreamingResponse(body())

    with TestClient(app) as client:
        response = client.get(
            "/conversations/private-user-id?secret=private-query",
            headers={"Authorization": "private-token"},
        )
    assert response.content == b"private response"
    root, worker, stream = backend.spans
    assert worker.parent is root and stream.parent is root
    assert backend.active.get() is None
    assert "private" not in repr(root.__dict__)
    assert root.updates[-1]["metadata"]["route"] == "/conversations/{conversation_id}"


def test_collector_has_authenticated_persistent_queue():
    config = yaml.safe_load((ROOT / "deploy/observability/collector.yaml").read_text())
    exporter = config["exporters"]["otlphttp/langfuse"]
    assert exporter["sending_queue"]["storage"] == "file_storage"
    assert config["extensions"]["file_storage"]["fsync"] is True
    assert exporter["retry_on_failure"]["max_elapsed_time"] == "0s"
    assert (
        config["receivers"]["otlp"]["protocols"]["http"]["auth"]["authenticator"]
        == "bearertokenauth/receiver"
    )
    compose = yaml.safe_load((ROOT / "compose.observability.yaml").read_text())
    collector = compose["services"]["collector"]
    assert all(port.startswith("127.0.0.1:") for port in collector["ports"])
    assert "collector-queue:/var/lib/otelcol" in collector["volumes"]
    assert collector["image"].endswith(":0.162.0")


def test_launcher_credential_derivation_and_host_loopback():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "observability_script", ROOT / "scripts/observability.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = module.collector_environment(
        {
            "POLICYPILOT_OTEL_ENDPOINT": "http://127.0.0.1:14318/v1/traces",
            "POLICYPILOT_OTEL_TOKEN": "receiver-token",
            "LANGFUSE_BASE_URL": "http://localhost:3000",
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        }
    )
    assert (
        env["LANGFUSE_OTLP_ENDPOINT"]
        == "http://host.docker.internal:3000/api/public/otel/v1/traces"
    )
    assert env["LANGFUSE_AUTHORIZATION"].startswith("Basic ")


def _launcher():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "observability_script", ROOT / "scripts/observability.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_initialization_is_disabled_and_never_rotates_credentials(tmp_path):
    from dotenv import dotenv_values

    module = _launcher()
    path = tmp_path / ".env.observability"
    assert module.initialize(path)
    original = path.read_bytes()
    values = dotenv_values(path)
    assert values["POLICYPILOT_OBSERVABILITY_ENABLED"] == "0"
    assert len(bytes.fromhex(values["LANGFUSE_ENCRYPTION_KEY"])) == 32
    assert "replace-with" not in original.decode()
    assert not module.initialize(path)
    assert path.read_bytes() == original
    env = module.collector_environment(values)
    assert (
        env["LANGFUSE_OTLP_ENDPOINT"]
        == "http://langfuse-web:3000/api/public/otel/v1/traces"
    )
    assert env["LANGFUSE_DB_PASSWORD"] == values["LANGFUSE_DB_PASSWORD"]


def test_local_stack_is_separate_and_loopback_only():
    services = yaml.safe_load((ROOT / "compose.observability.yaml").read_text())[
        "services"
    ]
    assert set(services) == {
        "collector",
        "langfuse-web",
        "langfuse-worker",
        "postgres",
        "redis",
        "clickhouse",
        "minio",
    }
    for service in services.values():
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
    assert not services["postgres"].get("ports")
    assert not services["redis"].get("ports")
    assert services["langfuse-web"]["environment"]["TELEMETRY_ENABLED"] == "false"
    assert "--appendonly yes" in services["redis"]["command"][-1]
    assert "--maxmemory-policy noeviction" in services["redis"]["command"][-1]
    assert services["postgres"]["volumes"] == [
        "langfuse-postgres:/var/lib/postgresql/data"
    ]


def _smoke_rows(trace_id):
    return [
        {
            "id": "root",
            "traceId": trace_id,
            "name": "policypilot.telemetry_smoke",
            "parentObservationId": None,
        },
        {
            "id": "generation",
            "traceId": trace_id,
            "name": "llm.synthetic",
            "parentObservationId": "root",
        },
        {
            "id": "tool",
            "traceId": trace_id,
            "name": "tool.synthetic",
            "parentObservationId": "root",
        },
    ]


@pytest.mark.parametrize("invalid", [None, "partial", "wrong_trace", "wrong_parent"])
def test_v4_readback_checks_trace_and_hierarchy(monkeypatch, invalid):
    import httpx

    module = _launcher()
    rows = _smoke_rows("test-trace")
    if invalid == "partial":
        rows.pop()
    elif invalid == "wrong_trace":
        rows[-1]["traceId"] = "other-trace"
    elif invalid == "wrong_parent":
        rows[-1]["parentObservationId"] = "other-root"
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": rows, "meta": {"cursor": None}})

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    values = {
        "LANGFUSE_BASE_URL": "http://127.0.0.1:13000",
        "LANGFUSE_PUBLIC_KEY": "public",
        "LANGFUSE_SECRET_KEY": "secret",
    }
    assert module.verify_trace(values, "test-trace") is (invalid is None)
    assert requests[0].url.path == "/api/public/v2/observations"
    assert requests[0].url.params["traceId"] == "test-trace"
    assert "fromStartTime" in requests[0].url.params
    assert "toStartTime" in requests[0].url.params
    assert requests[0].url.params["fields"] == "core,basic"


def test_v4_readback_retries_partial_ingestion(monkeypatch):
    import httpx

    module = _launcher()
    responses = iter(
        [
            httpx.Response(503),
            httpx.Response(200, json={"data": []}),
            httpx.Response(200, json={"data": _smoke_rows("test-trace")}),
        ]
    )
    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(lambda _: next(responses)), **kwargs
        ),
    )
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.verify_trace(
        {
            "LANGFUSE_BASE_URL": "http://127.0.0.1:13000",
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        },
        "test-trace",
    )


@pytest.mark.parametrize("verified", [False, True])
def test_enable_requires_platform_readback(tmp_path, monkeypatch, verified):
    from dotenv import dotenv_values

    module = _launcher()
    original_root = module.ROOT
    path = tmp_path / ".env.observability"
    module.initialize(path)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "check_services", lambda _: None)
    monkeypatch.setattr(module, "verify_trace", lambda *args: verified)
    monkeypatch.setattr(t, "current_ids", lambda: {"trace_id": "a" * 32})
    monkeypatch.setattr(t, "flush", lambda: True)
    monkeypatch.setattr(t, "diagnostics", lambda: {"status": "test"})
    monkeypatch.setattr(t, "_get_backend", lambda: None)
    for key in dotenv_values(path):
        monkeypatch.delenv(key, raising=False)
    # dotenv and smoke modify os.environ; let monkeypatch restore those mutations.
    monkeypatch.setenv("POLICYPILOT_OBSERVABILITY_ENABLED", "0")
    if verified:
        assert module.main(["enable"]) == 0
    else:
        with pytest.raises(
            module.OperationError, match="end-to-end verification failed"
        ):
            module.main(["enable"])
    assert dotenv_values(path)["POLICYPILOT_OBSERVABILITY_ENABLED"] == str(
        int(verified)
    )
    assert (tmp_path / "data/storage/observability-smoke.json").exists() is verified
    assert original_root == ROOT


def test_real_sdk_exports_nested_spans_to_memory_without_network(monkeypatch):
    pytest.importorskip("langfuse")
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from tau2.utils.telemetry import _LangfuseBackend

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    backend = object.__new__(_LangfuseBackend)
    backend.provider = provider
    backend.client = Langfuse(
        public_key="pk-memory-contract",
        secret_key="sk-memory-contract",
        base_url="http://127.0.0.1:9",
        tracer_provider=provider,
        span_exporter=exporter,
    )
    monkeypatch.setattr(t, "_backend", backend)
    monkeypatch.setattr(t, "_initialized", True)
    try:
        with t.observe("parent"):
            with t.observe("child", "generation", model="fake") as span:
                span.update(usage_details={"input": 2, "output": 1})
        assert t.flush()
        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert spans["child"].parent.span_id == spans["parent"].context.span_id
        assert spans["child"].context.trace_id == spans["parent"].context.trace_id
    finally:
        provider.shutdown()
