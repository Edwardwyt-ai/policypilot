"""Explicit observability initialization, Collector startup and delivery preflight."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class OperationError(RuntimeError):
    """An intentionally sanitized diagnostic safe to print."""


def initialize(path: Path) -> bool:
    """Create once: rotating initialization secrets would break existing volumes."""
    if path.exists():
        return False
    content = (ROOT / ".env.observability.example").read_text(encoding="utf-8")
    replacements = {
        "replace-with-generated-local-token": secrets.token_hex(32),
        "replace-with-project-public-key": "pk-lf-" + secrets.token_hex(16),
        "replace-with-project-secret-key": "sk-lf-" + secrets.token_hex(32),
    }
    for name in (
        "db-password",
        "redis-password",
        "clickhouse-password",
        "minio-password",
        "salt",
        "encryption-key",
        "nextauth-secret",
        "admin-password",
    ):
        replacements["replace-with-" + name] = secrets.token_hex(32)
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    return True


def collector_environment(values: dict) -> dict:
    """Keep credentials out of argv, output, tracked files and inbound OTLP."""
    from tau2.utils.telemetry import TelemetrySettings

    settings = TelemetrySettings(
        enabled=True,
        endpoint=values.get("POLICYPILOT_OTEL_ENDPOINT", ""),
        token=values.get("POLICYPILOT_OTEL_TOKEN", ""),
        public_key=values.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=values.get("LANGFUSE_SECRET_KEY", ""),
        base_url=values.get("LANGFUSE_BASE_URL", ""),
    )
    settings.validate()
    if any(
        "replace-with" in item or "your-langfuse-host" in item
        for item in (
            settings.token,
            settings.public_key,
            settings.secret_key,
            settings.base_url,
        )
    ):
        raise ValueError("Replace the example credentials and destination first")
    # Host loopback refers to the container itself, not the Windows host.
    url = urlsplit(settings.base_url)
    if values.get("POLICYPILOT_LANGFUSE_LOCAL") == "1":
        if settings.base_url != "http://127.0.0.1:13000":
            raise ValueError("Local mode requires the local platform URL")
        upstream = "http://langfuse-web:3000"
    elif url.hostname in {"localhost", "127.0.0.1", "::1"}:
        host = "host.docker.internal" + (f":{url.port}" if url.port else "")
        upstream = url._replace(netloc=host).geturl()
    else:
        upstream = settings.base_url
    auth = base64.b64encode(
        f"{settings.public_key}:{settings.secret_key}".encode()
    ).decode()
    return {
        **os.environ,
        **{key: value for key, value in values.items() if isinstance(value, str)},
        "POLICYPILOT_OTEL_TOKEN": settings.token,
        "LANGFUSE_OTLP_ENDPOINT": upstream.rstrip("/") + "/api/public/otel/v1/traces",
        "LANGFUSE_AUTHORIZATION": "Basic " + auth,
    }


def check_services(values: dict) -> None:
    import httpx

    with httpx.Client(timeout=5, trust_env=False) as client:
        client.get("http://127.0.0.1:14333/").raise_for_status()
        client.post(
            values["POLICYPILOT_OTEL_ENDPOINT"],
            json={"resourceSpans": []},
            headers={"Authorization": "Bearer " + values["POLICYPILOT_OTEL_TOKEN"]},
        ).raise_for_status()
        base = values["LANGFUSE_BASE_URL"].rstrip("/")
        client.get(base + "/api/public/health").raise_for_status()
        client.get(
            base + "/api/public/projects",
            auth=(values["LANGFUSE_PUBLIC_KEY"], values["LANGFUSE_SECRET_KEY"]),
        ).raise_for_status()
        if values.get("POLICYPILOT_LANGFUSE_LOCAL") == "1":
            client.get("http://127.0.0.1:13900/minio/health/ready").raise_for_status()


def verify_trace(values: dict, trace_id: str) -> bool:
    """Read v4 observation rows, not the removed legacy trace object API."""
    import httpx

    now = datetime.now(timezone.utc)
    params = {
        "traceId": trace_id,
        "fields": "core,basic",
        "limit": 100,
        "fromStartTime": (now - timedelta(minutes=10)).isoformat(),
        "toStartTime": (now + timedelta(minutes=2)).isoformat(),
    }
    with httpx.Client(timeout=5, trust_env=False) as client:
        for _ in range(30):
            response = client.get(
                values["LANGFUSE_BASE_URL"].rstrip("/") + "/api/public/v2/observations",
                params=params,
                auth=(values["LANGFUSE_PUBLIC_KEY"], values["LANGFUSE_SECRET_KEY"]),
            )
            if response.status_code == 200:
                body = response.json()
                rows = body.get("data")
                if not isinstance(rows, list):
                    raise OperationError(
                        "Observations API v2 returned an unexpected response shape."
                    )
                rows = [row for row in rows if row.get("traceId") == trace_id]
                root = next(
                    (
                        row
                        for row in rows
                        if row.get("name") == "policypilot.telemetry_smoke"
                        and row.get("id")
                        and not row.get("parentObservationId")
                    ),
                    None,
                )
                if root:
                    child_names = {
                        row.get("name")
                        for row in rows
                        if row.get("parentObservationId") == root["id"]
                    }
                    if {"llm.synthetic", "tool.synthetic"} <= child_names:
                        return True
            if response.status_code in {404, 410}:
                raise OperationError(
                    "Observations API v2 is unavailable. Check the Langfuse server version, not the trace ID."
                )
            if response.status_code not in {429, 503}:
                response.raise_for_status()
            time.sleep(2)
    return False


def main(argv=None):
    """No platform is silently selected, no cloud account is provisioned."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "start",
            "check",
            "smoke",
            "enable",
            "disable",
            "setup",
            "stop",
        ],
    )
    args = parser.parse_args(argv)
    path = ROOT / ".env.observability"
    if args.command == "setup":
        for command in ("init", "start", "enable"):
            main([command])
        return 0
    if args.command == "init":
        created = initialize(path)
        print(
            "Created local credentials; tracing remains disabled."
            if created
            else "Existing credentials preserved; no changes."
        )
        return 0
    if not path.exists():
        raise OperationError("Missing .env.observability; run init first.")
    if args.command == "disable":
        set_key(str(path), "POLICYPILOT_OBSERVABILITY_ENABLED", "0")
        print(
            "Tracing disabled in local config. Restart existing Agent/API processes to apply."
        )
        return 0
    load_dotenv(path, override=False)
    values = {**dotenv_values(path), **os.environ}
    environment = collector_environment(values)
    if args.command in {"start", "stop"}:
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("Docker CLI is not installed")
        compose = [docker, "compose", "-f", str(ROOT / "compose.observability.yaml")]
        if args.command == "stop":
            result = subprocess.run(
                [*compose, "stop"],
                env=environment,
                capture_output=True,
                timeout=120,
                cwd=ROOT,
            )
            if result.returncode:
                raise OperationError("Container stop failed; inspect Docker Desktop.")
            print(
                "Observability containers stopped; persistent volumes and tracing setting preserved."
            )
            return 0
        commands = [
            (
                "Docker Engine preflight",
                [docker, "info", "--format", "{{.ServerVersion}}"],
                30,
            ),
            ("Compose configuration", [*compose, "config", "--quiet"], 30),
            ("MinIO image build", [*compose, "build", "minio"], 1200),
            (
                "Collector configuration",
                [
                    *compose,
                    "run",
                    "--rm",
                    "--no-deps",
                    "collector",
                    "validate",
                    "--config=/etc/otelcol/config.yaml",
                ],
                300,
            ),
            ("Local platform startup", [*compose, "up", "-d"], 1200),
        ]
        for stage, command, timeout in commands:
            print(stage + "...", flush=True)
            try:
                result = subprocess.run(
                    command,
                    env=environment,
                    capture_output=True,
                    timeout=timeout,
                    cwd=ROOT,
                )
            except subprocess.TimeoutExpired as exc:
                raise OperationError(
                    stage + " timed out; tracing was not enabled."
                ) from exc
            if result.returncode:
                detail = result.stderr.decode(errors="replace").lower()
                if stage == "Docker Engine preflight":
                    hint = (
                        " Docker pipe access was denied. Run this command in your own Windows terminal with Docker access."
                        if "permission denied" in detail or "access is denied" in detail
                        else " Open Docker Desktop in your own Windows session and wait for Engine running."
                    )
                else:
                    hint = " Inspect Docker Desktop and local container logs; do not share secrets."
                raise OperationError(stage + " failed; tracing was not enabled." + hint)
        for _ in range(60):
            try:
                check_services(values)
                print(
                    "Local platform ready: http://127.0.0.1:13000 . Tracing remains unchanged; run smoke before enabling."
                )
                return 0
            except Exception:
                time.sleep(3)
        raise OperationError(
            "Containers started but platform/project readiness timed out. Tracing was not enabled."
        )
    check_services(values)
    print(
        "Collector and platform/project authentication ready; trace delivery NOT yet verified."
    )
    if args.command in {"smoke", "enable"}:
        os.environ["POLICYPILOT_OBSERVABILITY_ENABLED"] = "1"
        from tau2.utils.telemetry import current_ids, diagnostics, flush, observe

        with observe("policypilot.telemetry_smoke"):
            ids = current_ids()
            with observe(
                "llm.synthetic", "generation", model="synthetic-no-provider-call"
            ) as span:
                span.update(
                    usage_details={"input": 2, "output": 1}, cost_details={"total": 0.0}
                )
            with observe(
                "tool.synthetic",
                "tool",
                metadata={"tool_name": "synthetic_no_execution"},
            ):
                pass
        if not ids or not flush():
            raise RuntimeError("SDK initialization or Collector export failed")
        print({"trace_id": ids["trace_id"], **diagnostics()})
        if not verify_trace(values, ids["trace_id"]):
            raise OperationError(
                "Synthetic trace was not readable in Langfuse within the deadline; end-to-end verification failed."
            )
        receipt = ROOT / "data/storage/observability-smoke.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "trace_id": ids["trace_id"],
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                    "status": "read_back_verified",
                    "model_calls": 0,
                    "business_tools_executed": 0,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            "Synthetic trace read back from local Langfuse; no model calls. Persistent tracing remains unchanged."
        )
        if args.command == "enable":
            set_key(str(path), "POLICYPILOT_OBSERVABILITY_ENABLED", "1")
            print(
                "Tracing enabled after successful read-back. Restart existing Agent/API processes to apply."
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Do not print SDK/HTTP exceptions that may contain DSNs or auth headers.
        print(
            str(exc)
            if isinstance(exc, OperationError)
            else f"Observability operation failed: {type(exc).__name__}. Check configuration, Docker, connectivity and credentials.",
            file=sys.stderr,
        )
        raise SystemExit(1)
