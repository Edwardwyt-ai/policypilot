"""Fail-fast checks for local services required by PolicyPilot evaluation."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class OllamaPreflightResult:
    endpoint: str
    model: str
    embedding_dimensions: int
    started: bool


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, json=payload)
        response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return body


def _discover_start_script(repo_root: Path) -> Path | None:
    configured = os.getenv("POLICYPILOT_OLLAMA_START_SCRIPT")
    candidates = [
        Path(configured).expanduser() if configured else None,
        repo_root.parent / "qwen-api" / "start-qwen-api.ps1",
        Path.home() / "Desktop" / "qwen-api" / "start-qwen-api.ps1",
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _start_ollama(repo_root: Path) -> str:
    script = _discover_start_script(repo_root)
    if script is not None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell is None:
            raise RuntimeError("PowerShell is required to run the Ollama start script")
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            cwd=script.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                f"Ollama start script failed ({script}): {detail or 'unknown error'}"
            )
        return str(script)

    executable = shutil.which("ollama")
    if executable is None:
        raise RuntimeError(
            "Ollama is not reachable and no start command was found. Set "
            "POLICYPILOT_OLLAMA_START_SCRIPT to your start-qwen-api.ps1 path."
        )
    subprocess.Popen(
        [executable, "serve"],
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return executable


def _available_models(endpoint: str) -> set[str]:
    payload = _request_json("GET", f"{endpoint}/api/tags")
    return {
        str(item.get("name") or item.get("model"))
        for item in payload.get("models", [])
        if isinstance(item, dict) and (item.get("name") or item.get("model"))
    }


def ensure_ollama_embedding_runtime(
    repo_root: Path,
    *,
    endpoint: str | None = None,
    model: str | None = None,
    auto_start: bool = True,
    startup_timeout_seconds: float = 30.0,
) -> OllamaPreflightResult:
    """Ensure Ollama is ready and the configured embedding model works."""

    endpoint = (
        endpoint
        or os.getenv("POLICYPILOT_MEMORY_EMBEDDING_ENDPOINT")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    model = (
        model
        or os.getenv("POLICYPILOT_MEMORY_EMBEDDING_MODEL")
        or "qwen3-embedding:0.6b"
    )
    started = False
    try:
        models = _available_models(endpoint)
    except (httpx.HTTPError, RuntimeError, ValueError):
        if not auto_start:
            raise RuntimeError(
                f"Ollama is not reachable at {endpoint}; automatic startup is disabled"
            ) from None
        _start_ollama(repo_root)
        started = True
        deadline = time.monotonic() + startup_timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                models = _available_models(endpoint)
                break
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                last_error = exc
                time.sleep(0.5)
        else:
            raise RuntimeError(
                f"Ollama did not become ready at {endpoint} within "
                f"{startup_timeout_seconds:.0f}s"
            ) from last_error

    if model not in models:
        available = ", ".join(sorted(models)) or "none"
        raise RuntimeError(
            f"Required Ollama embedding model '{model}' is not installed. "
            f"Available models: {available}. Run: ollama pull {model}"
        )

    try:
        payload = _request_json(
            "POST",
            f"{endpoint}/api/embed",
            payload={
                "model": model,
                "input": "PolicyPilot runtime preflight",
                "truncate": True,
                "keep_alive": "10m",
            },
            timeout=60.0,
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"Ollama embedding health check failed for '{model}' at {endpoint}: {exc}"
        ) from exc
    embeddings = payload.get("embeddings")
    if (
        not isinstance(embeddings, list)
        or not embeddings
        or not isinstance(embeddings[0], list)
        or not embeddings[0]
    ):
        raise RuntimeError("Ollama embedding health check returned no vector")
    return OllamaPreflightResult(
        endpoint=endpoint,
        model=model,
        embedding_dimensions=len(embeddings[0]),
        started=started,
    )
