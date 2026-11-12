"""Optional fail-open Langfuse tracing with metadata-only banking telemetry.

This module deliberately imports no agent, registry, model client or evaluator.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)
_suppressed = ContextVar("policypilot_telemetry_suppressed", default=False)
_lock = threading.RLock()
_backend = None
_initialized = False
_diagnostic = "disabled"


@dataclass(frozen=True)
class TelemetrySettings:
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:14318/v1/traces"
    token: str = field(default="", repr=False)
    public_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    base_url: str = ""
    sample_rate: float = 1.0

    @classmethod
    def from_env(cls):
        """Tracing is opt-in; no credentials or destination are invented."""
        return cls(
            enabled=os.getenv("POLICYPILOT_OBSERVABILITY_ENABLED", "0").lower()
            in {"1", "true", "yes"},
            endpoint=os.getenv("POLICYPILOT_OTEL_ENDPOINT", cls.endpoint),
            token=os.getenv("POLICYPILOT_OTEL_TOKEN", ""),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            base_url=os.getenv("LANGFUSE_BASE_URL", ""),
            sample_rate=float(os.getenv("POLICYPILOT_TRACE_SAMPLE_RATE", "1")),
        )

    def validate(self):
        for url in (self.endpoint, self.base_url):
            parsed = urlsplit(url)
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.scheme not in {"http", "https"}
                or (
                    parsed.scheme != "https"
                    and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                )
            ):
                raise ValueError(
                    "Telemetry URLs require HTTPS or explicit loopback HTTP"
                )
        if not all((self.token, self.public_key, self.secret_key)):
            raise ValueError(
                "Telemetry requires collector token and explicit Langfuse project keys"
            )
        if not 0 <= self.sample_rate <= 1:
            raise ValueError("Invalid telemetry sampling rate")


def opaque_id(value: str) -> str:
    """Stable correlation ID, not an authentication primitive."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def safe_metadata(values: dict | None) -> dict:
    """Accept only fixed diagnostic fields; never export arbitrary state dictionaries."""
    allowed = {
        "node",
        "run_id",
        "task_id",
        "turn",
        "need_count",
        "evidence_count",
        "mutation_count",
        "tool_count",
        "error_count",
        "retry_count",
        "http_status",
        "method",
        "route",
        "tool_name",
        "requestor",
        "error_type",
        "failed",
        "structured_valid",
        "cost_available",
        "guard_blocks",
        "need_id",
        "mutation_id",
        "source",
        "status",
        "coverage",
        "event_count",
        "input_tokens",
        "output_tokens",
    }
    result = {}
    for key, value in (values or {}).items():
        if key not in allowed or not isinstance(value, (str, int, float, bool)):
            continue
        if key in {"run_id", "task_id", "need_id", "mutation_id"}:
            value = opaque_id(str(value))
        if key in {"source", "status", "coverage"} and value not in {
            "USER",
            "POLICY",
            "TOOL",
            "UNKNOWN",
            "OPEN",
            "PARTIALLY_COVERED",
            "REOPENED",
            "RESOLVED",
            "NOT_APPLICABLE",
            "EXHAUSTED",
            "REQUESTED",
            "MATCH",
            "PARTIAL",
            "NO_MATCH",
            "PLANNED",
            "SENT",
            "CONFIRMED",
            "FAILED",
        }:
            continue
        result[key] = value[:160] if isinstance(value, str) else value
    return result


class _LangfuseBackend:
    def __init__(self, settings: TelemetrySettings):
        from langfuse import Langfuse
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        settings.validate()
        self.provider = TracerProvider(
            resource=Resource.create({"service.name": "policypilot"}),
            sampler=ParentBased(TraceIdRatioBased(settings.sample_rate)),
        )
        exporter = OTLPSpanExporter(
            endpoint=settings.endpoint,
            headers={"Authorization": "Bearer " + settings.token},
            timeout=3,
        )
        self.client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            base_url=settings.base_url,
            tracer_provider=self.provider,
            span_exporter=exporter,
            flush_at=64,
            flush_interval=1,
            mask=lambda data=None, **_: "[content omitted]",
        )

    def start(self, name, kind, metadata, model, session_id):
        from contextlib import ExitStack

        from langfuse import propagate_attributes

        stack = ExitStack()
        try:
            if session_id:
                stack.enter_context(
                    propagate_attributes(session_id=opaque_id(session_id))
                )
            span = stack.enter_context(
                self.client.start_as_current_observation(
                    name=name,
                    as_type=kind,
                    metadata=metadata,
                    **({"model": model} if kind == "generation" and model else {}),
                )
            )
            return stack, span
        except Exception:
            stack.close()
            raise

    def flush(self):
        return self.provider.force_flush(timeout_millis=5000)

    def shutdown(self):
        self.provider.shutdown()


def _get_backend():
    global _backend, _initialized, _diagnostic
    if _suppressed.get():
        return None
    with _lock:
        if _initialized:
            return _backend
        _initialized = True
        try:
            from dotenv import load_dotenv

            load_dotenv(
                Path(__file__).resolve().parents[3] / ".env.observability",
                override=False,
            )
            settings = TelemetrySettings.from_env()
            if settings.enabled:
                _backend = _LangfuseBackend(settings)
                _diagnostic = "configured_not_delivery_verified"
                atexit.register(shutdown)
        except Exception as exc:
            _diagnostic = "unavailable:" + type(exc).__name__
            logger.warning(
                "Telemetry disabled: %s (business execution continues)",
                type(exc).__name__,
            )
        return _backend


def diagnostics():
    """Do not confuse client configuration with collector/platform delivery."""
    _get_backend()
    return {"status": _diagnostic}


class Observation:
    def __init__(self, span=None, metadata=None):
        self.span = span
        self.metadata = safe_metadata(metadata)

    def update(
        self, *, metadata=None, usage_details=None, cost_details=None, failed=False
    ):
        if self.span is None:
            return
        try:
            self.metadata.update(safe_metadata(metadata))
            values: dict[str, Any] = {"metadata": dict(self.metadata)}
            if usage_details is not None:
                values["usage_details"] = usage_details
            if cost_details is not None:
                values["cost_details"] = cost_details
            if failed:
                values.update(
                    level="ERROR",
                    status_message="Operation failed; details retained locally",
                )
            self.span.update(**values)
        except Exception:
            logger.warning("Telemetry observation update failed")

    def event(self, name, attributes):
        if self.span is None:
            return
        try:
            from opentelemetry import trace

            trace.get_current_span().add_event(name, safe_metadata(attributes))
        except Exception:
            logger.warning("Telemetry event update failed")


@contextmanager
def observe(name: str, kind="span", *, metadata=None, model=None, session_id=None):
    """Instrumentation failures never swallow, replace or repeat business work."""
    stack = None
    observation = Observation()
    backend = _get_backend()
    if backend is not None:
        try:
            stack, span = backend.start(
                name, kind, safe_metadata(metadata), model, session_id
            )
            observation = Observation(span, metadata)
        except Exception:
            logger.warning("Telemetry span creation failed")
    try:
        yield observation
    except BaseException as exc:
        observation.update(metadata={"error_type": type(exc).__name__}, failed=True)
        raise
    finally:
        if stack is not None:
            try:
                # Do not let SDK auto-record raw exception messages or stack locals.
                stack.close()
            except Exception:
                logger.warning("Telemetry span completion failed")


@contextmanager
def suppress():
    """Keep hidden evaluator operations out of the agent trace."""
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


def current_ids():
    if _get_backend() is None:
        return {}
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        return (
            {
                "trace_id": f"{context.trace_id:032x}",
                "span_id": f"{context.span_id:016x}",
            }
            if context.is_valid
            else {}
        )
    except Exception:
        return {}


@contextmanager
def remote_parent(headers):
    """Accept W3C traceparent only; never propagate caller baggage or headers."""
    token = None
    context = None
    try:
        from opentelemetry import context
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        carrier = {
            k.decode("ascii", errors="ignore").lower(): v.decode(
                "ascii", errors="ignore"
            )
            for k, v in headers
            if k.lower() == b"traceparent"
        }
        token = context.attach(TraceContextTextMapPropagator().extract(carrier))
    except Exception:
        logger.warning("Telemetry context extraction failed")
    try:
        yield
    finally:
        if token is not None:
            try:
                context.detach(token)
            except Exception:
                logger.warning("Telemetry context detach failed")


def flush():
    """Call at lifecycle boundaries, not synchronously on every request."""
    if _backend is not None:
        try:
            return _backend.flush()
        except Exception:
            logger.warning("Telemetry flush failed")
    return False


def shutdown():
    if _backend is not None:
        try:
            _backend.shutdown()
        except Exception:
            logger.warning("Telemetry shutdown failed")


def instrument_node(function, name):
    """Attach compact state counts and new business events, never state payloads."""

    def invoke(gs):
        if _get_backend() is None:
            return function(gs)
        with observe("workflow." + name, "chain", metadata={"node": name}) as span:
            try:
                snapshot = _node_snapshot(gs["policy_state"])
            except Exception:
                snapshot = None
                logger.warning("Telemetry node snapshot failed")
            result = function(gs)
            if snapshot is not None:
                try:
                    _record_node_result(
                        span,
                        result.get("policy_state", gs["policy_state"]),
                        snapshot,
                        name,
                    )
                except Exception:
                    logger.warning("Telemetry node metadata failed")
            return result

    return invoke


def _node_snapshot(state):
    event_fields = (
        "need_registry_events",
        "retrieval_events",
        "acquisition_events",
        "progress_events",
    )
    return (
        {key: len(getattr(state.control, key)) for key in event_fields},
        {need.id: (need.status, need.coverage) for need in state.information_needs},
        {item.mutation_id: len(item.status_history) for item in state.mutations},
    )


def _record_node_result(span, state, snapshot, name):
    offsets, needs_before, mutations_before = snapshot
    span.update(
        metadata={
            "node": name,
            "need_count": len(state.information_needs),
            "evidence_count": len(state.evidence),
            "mutation_count": len(state.mutations),
            "guard_blocks": sum(r.blocked for r in state.tool_history),
        }
    )
    for key, offset in offsets.items():
        entries = getattr(state.control, key)[offset:]
        for item in entries[:20]:
            span.event(key, item)
        if len(entries) > 20:
            span.event("events_truncated", {"event_count": len(entries)})
    for need in state.information_needs:
        if needs_before.get(need.id) != (need.status, need.coverage):
            span.event(
                "need.state",
                {"need_id": need.id, "status": need.status, "coverage": need.coverage},
            )
    for item in state.mutations:
        for transition in item.status_history[
            mutations_before.get(item.mutation_id, 0) :
        ]:
            span.event(
                "mutation.transition",
                {"mutation_id": item.mutation_id, "status": transition.status},
            )
