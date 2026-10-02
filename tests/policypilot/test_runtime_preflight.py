from pathlib import Path

import httpx
import pytest

from policypilot.runtime import preflight


def test_preflight_uses_running_ollama_without_starting(monkeypatch, tmp_path):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3-embedding:0.6b"}]}
        return {"embeddings": [[0.1, 0.2, 0.3]]}

    monkeypatch.setattr(preflight, "_request_json", request)
    monkeypatch.setattr(
        preflight,
        "_start_ollama",
        lambda _: pytest.fail("healthy Ollama must not be restarted"),
    )

    result = preflight.ensure_ollama_embedding_runtime(tmp_path)

    assert result.started is False
    assert result.embedding_dimensions == 3
    assert calls == [
        ("GET", "http://127.0.0.1:11434/api/tags"),
        ("POST", "http://127.0.0.1:11434/api/embed"),
    ]


def test_preflight_starts_unavailable_ollama_then_checks_model(
    monkeypatch, tmp_path
):
    attempts = iter(
        [
            httpx.ConnectError("offline"),
            {"models": [{"name": "qwen3-embedding:0.6b"}]},
            {"embeddings": [[0.1, 0.2]]},
        ]
    )
    started = []

    def request(*args, **kwargs):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(preflight, "_request_json", request)
    monkeypatch.setattr(preflight, "_start_ollama", lambda root: started.append(root))

    result = preflight.ensure_ollama_embedding_runtime(tmp_path)

    assert started == [tmp_path]
    assert result.started is True
    assert result.embedding_dimensions == 2


def test_preflight_reports_missing_embedding_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        preflight,
        "_request_json",
        lambda *args, **kwargs: {"models": [{"name": "qwen3:0.6b"}]},
    )

    with pytest.raises(RuntimeError, match="ollama pull qwen3-embedding:0.6b"):
        preflight.ensure_ollama_embedding_runtime(tmp_path)


def test_preflight_reports_embedding_health_failure(monkeypatch, tmp_path):
    responses = iter(
        [
            {"models": [{"name": "qwen3-embedding:0.6b"}]},
            httpx.ReadTimeout("model load timed out"),
        ]
    )

    def request(*args, **kwargs):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(preflight, "_request_json", request)

    with pytest.raises(RuntimeError, match="embedding health check failed"):
        preflight.ensure_ollama_embedding_runtime(tmp_path)


def test_start_script_discovery_prefers_explicit_path(monkeypatch, tmp_path):
    script = tmp_path / "start.ps1"
    script.write_text("Write-Host ready", encoding="utf-8")
    monkeypatch.setenv("POLICYPILOT_OLLAMA_START_SCRIPT", str(script))

    assert preflight._discover_start_script(Path("unused")) == script
