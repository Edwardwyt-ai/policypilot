"""Transactional SQL storage and immutable artifacts for PolicyPilot."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path


class StorageConflictError(ValueError):
    """A stale revision or interrupted operation needs reconciliation."""


def load_storage_environment() -> None:
    """Load only the explicitly activated service configuration."""
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env.storage", override=False)


def storage_root() -> Path:
    default = Path(__file__).resolve().parents[3] / "data" / "storage"
    return Path(os.getenv("POLICYPILOT_STORAGE_ROOT", str(default))).resolve()


def validate_digest(digest: str) -> None:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid artifact digest")


class ArtifactStore:
    """Content-addressed local artifacts for isolated tests and development."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        target = self.root / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, temporary = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return digest

    def get(self, digest: str) -> bytes:
        validate_digest(digest)
        content = (self.root / digest[:2] / digest).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Artifact checksum mismatch")
        return content


class S3ArtifactStore:
    """Private MinIO/S3 bucket; keys and contents are verified by SHA-256."""

    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = os.environ["POLICYPILOT_S3_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["POLICYPILOT_S3_ENDPOINT"],
            aws_access_key_id=os.environ["POLICYPILOT_S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["POLICYPILOT_S3_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 2},
                s3={"addressing_style": "path"},
            ),
        )

    def put(self, content: bytes) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        digest = hashlib.sha256(content).hexdigest()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=f"sha256/{digest}",
                Body=content,
                ContentType="application/octet-stream",
                Metadata={"sha256": digest},
            )
        except (BotoCoreError, ClientError):
            raise OSError("Artifact storage unavailable") from None
        return digest

    def get(self, digest: str) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        validate_digest(digest)
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=f"sha256/{digest}"
            )
            try:
                content = response["Body"].read()
            finally:
                response["Body"].close()
        except (BotoCoreError, ClientError):
            raise OSError("Artifact storage unavailable") from None
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Artifact checksum mismatch")
        return content


class Database:
    """PostgreSQL in service mode; explicit SQLite path for offline tests."""

    def __init__(
        self, root: str | Path | None = None, *, url: str | None = None, artifacts=None
    ):
        import sqlalchemy as sa

        self.sa = sa
        self.root = Path(root).resolve() if root is not None else storage_root()
        self.path = self.root / "policypilot.sqlite3"
        url = url or (os.getenv("POLICYPILOT_DATABASE_URL") if root is None else None)
        if url is None:
            if root is None:
                raise RuntimeError(
                    "POLICYPILOT_DATABASE_URL is required; start services first"
                )
            self.root.mkdir(parents=True, exist_ok=True)
            url = sa.URL.create("sqlite", database=str(self.path))
        if root is None and sa.engine.make_url(url).get_backend_name() != "postgresql":
            raise ValueError(
                "Service mode requires PostgreSQL; SQLite is only an explicit test adapter"
            )
        if (
            root is None
            and artifacts is None
            and not os.getenv("POLICYPILOT_S3_ENDPOINT")
        ):
            raise RuntimeError("Service mode requires MinIO/S3 artifact configuration")
        self.engine = sa.create_engine(
            url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 30}
            if str(url).startswith("sqlite")
            else {"connect_timeout": 5},
        )
        self.artifacts = artifacts or (
            S3ArtifactStore()
            if os.getenv("POLICYPILOT_S3_ENDPOINT") and root is None
            else ArtifactStore(self.root / "artifacts")
        )
        metadata = sa.MetaData()
        self.objects = sa.Table(
            "objects",
            metadata,
            sa.Column("namespace", sa.String(256), primary_key=True),
            sa.Column("key", sa.String(256), primary_key=True),
            sa.Column("payload", sa.Text, nullable=False),
        )
        self.conversations = sa.Table(
            "conversations",
            metadata,
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("user_id", sa.String(256), nullable=False, index=True),
            sa.Column("payload", sa.Text, nullable=False),
            sa.Column("busy", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("inflight", sa.Text),
        )
        if self.engine.dialect.name == "sqlite":
            with self.engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        metadata.create_all(self.engine)

    @contextmanager
    def connect(self, *, lock: str | None = None):
        from sqlalchemy.exc import SQLAlchemyError

        try:
            with self.engine.connect() as conn:
                if lock and self.engine.dialect.name == "sqlite":
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                if lock and self.engine.dialect.name == "postgresql":
                    conn.execute(
                        self.sa.text(
                            "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
                        ),
                        {"key": lock},
                    )
                try:
                    yield conn
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
        except SQLAlchemyError:
            raise OSError("Transactional storage unavailable") from None

    def encode(self, value) -> str:
        content = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        if len(content) > 16384:
            return json.dumps({"artifact_sha256": self.artifacts.put(content.encode())})
        return content

    def decode(self, payload: str):
        value = json.loads(payload)
        if isinstance(value, dict) and set(value) == {"artifact_sha256"}:
            return json.loads(self.artifacts.get(value["artifact_sha256"]))
        return value

    def get(self, namespace: str, key: str):
        with self.connect() as conn:
            row = conn.execute(
                self.sa.select(self.objects.c.payload).where(
                    self.objects.c.namespace == namespace, self.objects.c.key == key
                )
            ).first()
        return self.decode(row[0]) if row else None

    def put(self, namespace: str, key: str, value) -> None:
        payload = self.encode(value)
        with self.connect() as conn:
            self.write(conn, namespace, key, payload)

    def write(self, conn, namespace: str, key: str, payload: str) -> None:
        if self.engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        statement = insert(self.objects).values(
            namespace=namespace, key=key, payload=payload
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=["namespace", "key"], set_={"payload": payload}
            )
        )

    def delete(self, namespace: str, key: str) -> None:
        with self.connect() as conn:
            conn.execute(
                self.objects.delete().where(
                    self.objects.c.namespace == namespace, self.objects.c.key == key
                )
            )

    def list_objects(self, namespace: str):
        with self.connect() as conn:
            rows = conn.execute(
                self.sa.select(self.objects.c.key, self.objects.c.payload).where(
                    self.objects.c.namespace == namespace
                )
            ).all()
        return [(key, self.decode(payload)) for key, payload in rows]

    def verify(self) -> int:
        with self.connect() as conn:
            rows = conn.execute(self.sa.select(self.objects.c.payload)).all()
        for row in rows:
            self.decode(row[0])
        return len(rows)


@lru_cache(maxsize=1)
def get_service_database() -> Database:
    """One pooled SQL engine per worker, not one engine per Agent turn."""
    return Database()
