"""Offline deployment configuration checks, not live Docker integration tests."""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[2]


def test_minio_build_has_isolated_context_and_preserves_data_volume():
    compose = yaml.safe_load(
        (ROOT / "compose.storage.yaml").read_text(encoding="utf-8")
    )
    minio = compose["services"]["minio"]
    assert minio["image"] == "policypilot/minio:source-7aac2a2c5b7c"
    assert minio["pull_policy"] == "never"
    assert minio["build"]["context"] == "./deploy/minio"
    assert minio["volumes"] == ["minio:/data"]
    assert minio["ports"] == ["127.0.0.1:19000:9000", "127.0.0.1:19001:9001"]


def test_source_build_uses_pinned_upstream_and_digest_pinned_bases():
    dockerfile = (ROOT / "deploy/minio/Dockerfile").read_text(encoding="utf-8")
    bases = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert len(bases) == 2
    assert all("@sha256:" in line for line in bases)
    assert "github.com/minio/minio@v0.0.0-20260212201848-7aac2a2c5b7c" in dockerfile
    assert (
        'org.opencontainers.image.revision="7aac2a2c5b7c882e68c1ce017d8256be2feea27f"'
        in dockerfile
    )
    assert "FROM minio/minio" not in dockerfile
    assert "COPY . " not in dockerfile


def test_launcher_finishes_images_before_start_and_activation():
    script = (ROOT / "scripts/start-storage-services.ps1").read_text(encoding="utf-8")
    pull = script.index("@ComposeArgs pull postgres redis qdrant")
    build = script.index("@ComposeArgs build minio")
    start = script.index("@ComposeArgs up -d --no-build --pull never")
    activate = script.index("'storage_services.py') connect")
    assert pull < build < start < activate
    assert "if ($LASTEXITCODE -ne 0)" in script[pull:build]
    assert "if ($LASTEXITCODE -ne 0)" in script[build:start]
    assert "down -v" not in script


@pytest.mark.parametrize("fails", [False, True])
def test_qdrant_probe_without_context_manager_always_closes(monkeypatch, fails):
    import importlib.util
    from unittest.mock import MagicMock

    pytest.importorskip("sqlalchemy")
    pytest.importorskip("redis")
    pytest.importorskip("qdrant_client")
    pytest.importorskip("boto3")
    spec = importlib.util.spec_from_file_location(
        "storage_probe_test", ROOT / "scripts/storage_services.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL", "QDRANT_API_KEY"):
        monkeypatch.setenv(f"POLICYPILOT_{key}", "test-only")
    monkeypatch.setattr("sqlalchemy.create_engine", MagicMock())
    monkeypatch.setattr("redis.Redis.from_url", MagicMock())
    store = MagicMock()
    store.get.return_value = b"PolicyPilot storage readiness v1"
    monkeypatch.setattr("policypilot.storage.database.S3ArtifactStore", lambda: store)

    class PlainClient:
        closed = False

        def get_collections(self):
            if fails:
                raise ValueError("test-failure")
            return []

        def close(self):
            self.closed = True

    client = PlainClient()
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **kwargs: client)
    if fails:
        with pytest.raises(
            RuntimeError, match="Qdrant preflight failed: ValueError: test-failure"
        ):
            module.probe()
    else:
        module.probe()
    assert client.closed


def test_service_diagnostics_redact_credentials(monkeypatch, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "storage_error_test", ROOT / "scripts/storage_services.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("POLICYPILOT_QDRANT_API_KEY", "secret-for-test")
    message = module.safe_error(ValueError("rejected key secret-for-test"))
    assert "secret-for-test" not in message
    assert "ValueError: rejected key [REDACTED]" == message
