"""Provision, probe, migrate and explicitly activate local storage services."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def init_environment() -> Path:
    path = ROOT / ".env.services"
    if not path.exists():
        # Exclusive creation preserves credentials of already initialized volumes.
        values = {
            key: secrets.token_hex(24)
            for key in (
                "POSTGRES_PASSWORD",
                "REDIS_PASSWORD",
                "QDRANT_API_KEY",
                "MINIO_ROOT_PASSWORD",
            )
        }
        values["MINIO_ROOT_USER"] = "policypilot-admin"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
    return path


def service_environment() -> dict[str, str]:
    from dotenv import dotenv_values
    from sqlalchemy import URL

    values = dotenv_values(ROOT / ".env.services")
    required = (
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "QDRANT_API_KEY",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    )
    if any(not values.get(key) for key in required):
        raise RuntimeError("Service credentials missing; run init first")
    return {
        "POLICYPILOT_STORAGE_BACKEND": "postgres",
        "POLICYPILOT_DATABASE_URL": URL.create(
            "postgresql+psycopg",
            username="policypilot",
            password=values["POSTGRES_PASSWORD"],
            host="127.0.0.1",
            port=15432,
            database="policypilot",
        ).render_as_string(hide_password=False),
        "POLICYPILOT_REDIS_URL": f"redis://:{values['REDIS_PASSWORD']}@127.0.0.1:16379/0",
        "POLICYPILOT_QDRANT_URL": "http://127.0.0.1:16333",
        "POLICYPILOT_QDRANT_API_KEY": values["QDRANT_API_KEY"],
        "POLICYPILOT_S3_ENDPOINT": "http://127.0.0.1:19000",
        "POLICYPILOT_S3_BUCKET": "policypilot-artifacts",
        "POLICYPILOT_S3_ACCESS_KEY": values["MINIO_ROOT_USER"],
        "POLICYPILOT_S3_SECRET_KEY": values["MINIO_ROOT_PASSWORD"],
    }


def safe_error(exc: Exception) -> str:
    """Keep diagnostics actionable without exposing credentials or full DSNs."""
    from dotenv import dotenv_values

    message = str(exc)
    credentials = dict(os.environ)
    credentials.update(dotenv_values(ROOT / ".env.services"))
    for key, value in credentials.items():
        if value and any(
            word in key
            for word in (
                "PASSWORD",
                "SECRET",
                "API_KEY",
                "ACCESS_KEY",
                "DATABASE_URL",
                "REDIS_URL",
            )
        ):
            message = message.replace(value, "[REDACTED]")
    return f"{type(exc).__name__}: {message[:1500]}"


def probe() -> None:
    from botocore.exceptions import ClientError
    from qdrant_client import QdrantClient
    from redis import Redis
    from sqlalchemy import create_engine, text

    from policypilot.storage.database import S3ArtifactStore

    stage = "PostgreSQL"
    try:
        engine = create_engine(
            os.environ["POLICYPILOT_DATABASE_URL"],
            hide_parameters=True,
            connect_args={"connect_timeout": 3},
        )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        stage = "Redis"
        with Redis.from_url(
            os.environ["POLICYPILOT_REDIS_URL"],
            socket_timeout=3,
            socket_connect_timeout=3,
        ) as client:
            client.ping()
        stage = "Qdrant"
        # QdrantClient exposes close(), but does not implement __enter__/__exit__.
        client = QdrantClient(
            url=os.environ["POLICYPILOT_QDRANT_URL"],
            api_key=os.environ["POLICYPILOT_QDRANT_API_KEY"],
            timeout=3,
            check_compatibility=False,
        )
        try:
            client.get_collections()
        finally:
            client.close()
        stage = "MinIO"
        store = S3ArtifactStore()
        try:
            store.client.head_bucket(Bucket=store.bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            store.client.create_bucket(Bucket=store.bucket)
        sample = b"PolicyPilot storage readiness v1"
        if store.get(store.put(sample)) != sample:
            raise RuntimeError("Artifact read/write verification failed")
    except Exception as exc:
        raise RuntimeError(f"{stage} preflight failed: {safe_error(exc)}") from None


def archive(database, directories: list[Path]) -> int:
    """Archive immutable files; original benchmark paths remain available."""
    count = 0
    for directory in directories:
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(ROOT).as_posix()
            key = hashlib.sha256(relative.encode()).hexdigest()
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            existing = database.get("artifact_catalog", key)
            if existing and existing["sha256"] == digest:
                continue
            database.artifacts.put(content)
            database.put(
                "artifact_catalog",
                key,
                {"path": relative, "sha256": digest, "bytes": len(content)},
            )
            count += 1
    return count


def connect_services() -> dict:
    from migrate_storage import migrate

    from policypilot.storage.database import Database
    from tau2.domains.banking_knowledge.qdrant_index import (
        DEFAULT_COLLECTION,
        configure_hnsw,
        create_qdrant_client,
        migrate_numpy_index,
    )

    deadline = time.monotonic() + 120
    while True:
        try:
            probe()
            break
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Service preflight failed; backend unchanged. {safe_error(exc)}"
                ) from None
            time.sleep(3)
    database = Database()
    counts = migrate(
        database,
        ROOT / "data/policypilot_memory",
        ROOT / "data/policypilot_checkpoints",
    )
    vectors = ROOT / "data/tau2/domains/banking_knowledge/vector_index"
    # No re-embedding or paid LLM calls: import the existing verified vectors.
    migrate_numpy_index(
        chunks_path=vectors / "chunks.jsonl",
        index_dir=vectors / "qwen3-embedding-0.6b",
        collection=DEFAULT_COLLECTION,
        qdrant_path=None,
        qdrant_url=os.environ["POLICYPILOT_QDRANT_URL"],
        api_key=os.environ["POLICYPILOT_QDRANT_API_KEY"],
        batch_size=128,
        recreate=False,
        reuse_existing=True,
    )
    client = create_qdrant_client(
        url=os.environ["POLICYPILOT_QDRANT_URL"],
        api_key=os.environ["POLICYPILOT_QDRANT_API_KEY"],
    )
    try:
        configure_hnsw(client, DEFAULT_COLLECTION)
    finally:
        client.close()
    database.verify()
    config = ROOT / ".env.storage"
    temporary = ROOT / ".env.storage.pending"
    try:
        temporary.write_text(
            "\n".join(f"{key}={value}" for key, value in service_environment().items())
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, config)
    finally:
        temporary.unlink(missing_ok=True)
        database.engine.dispose()
    return {"activated": True, "migrated": counts, "policy_vectors": "verified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "check", "connect", "archive"))
    args = parser.parse_args()
    if args.command == "init":
        print(f"Credentials file ready: {init_environment().name} (values hidden)")
        return 0
    os.environ.update(service_environment())
    if args.command == "connect":
        print(json.dumps(connect_services(), indent=2))
    elif args.command == "check":
        probe()
        print("PostgreSQL, Redis, Qdrant and MinIO: ready")
    else:
        from policypilot.storage.database import Database

        database = Database()
        try:
            print(
                json.dumps({"archived": archive(database, [ROOT / "data/simulations"])})
            )
        finally:
            database.engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Driver errors can contain DSNs; never print credentials on failure.
        print(
            f"Storage operation failed: {safe_error(exc)}. No source data was deleted.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
