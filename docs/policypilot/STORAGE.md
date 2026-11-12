# Storage Services V1

| Data | Service |
| --- | --- |
| User profiles, bounded per-user episodes and embedding metadata | PostgreSQL |
| Checkpoints, API conversations, events, pending actions, request receipts | PostgreSQL |
| Large snapshots and immutable experiment archives | MinIO, SHA-256 keys; PostgreSQL retains references |
| Banking policy vectors | Qdrant Server |
| Hybrid policy response cache | Redis, 900-second TTL, versioned keys |
| Source documents, benchmark/gold fixtures, Skill definitions | Version-controlled files |
| Downloaded models and reproducible embedding caches | Local cache directories |

## Start And Connect

Run in your own Windows PowerShell from the project root:

```powershell
.\scripts\start-storage-services.ps1 -InstallDocker
```

If Docker installation requests WSL2 setup or a restart, finish that first.
Then start Docker Desktop and run:

```powershell
.\scripts\start-storage-services.ps1
```

The script installs Python storage dependencies, creates random credentials in
ignored `.env.services`, starts `compose.storage.yaml`, probes all four services,
copies legacy memory/checkpoints and imports existing policy vectors without
re-embedding. Only after success does it atomically activate `.env.storage`.
Restart the API/evaluation process to load it. Failure preserves the previous
configuration and all source files. There is no automatic PostgreSQL-to-SQLite
fallback. Explicit temporary SQLite paths are only an offline test adapter.

Local ports: PostgreSQL `15432`, Redis `16379`, Qdrant `16333`, MinIO S3 `19000`,
MinIO console `19001`. Published ports bind to `127.0.0.1`; services have
credentials. PostgreSQL, Qdrant and MinIO use Docker named volumes. Do not run
`docker compose down -v` unless intentionally deleting persisted data. Local HTTP
is development-only; remote deployment requires TLS and managed credentials.
Existing environment variables override `.env.storage`.

### MinIO Image Availability

The withdrawn Docker Hub MinIO image is no longer used. The launcher pulls the
other three services, then builds `policypilot/minio:source-7aac2a2c5b7c` locally
from upstream MinIO commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` using the
Go module proxy/checksum database. Builder/runtime base images are digest-pinned.
The build context contains only `deploy/minio`, not project secrets or data.
First build needs internet access to Docker Hub and Go module infrastructure and
may take several minutes; subsequent builds reuse Docker's build cache.
The local image is never pulled from a third-party MinIO publisher. Existing
MinIO volume, credentials, ports and S3 integration are unchanged. Source build
is not a claim of security maintenance: upstream community MinIO is archived.
This configuration is for local development, not production deployment.

Reference: [upstream source distribution notice](https://github.com/minio/minio#source-only-distribution).

## Policy HNSW Index

Qdrant Server uses HNSW with `m=16`, `ef_construct=100` and query
`hnsw_ef=128` (or the requested limit if larger). Both the indexing and full-scan
thresholds are set to 1 KB so the small policy corpus is eligible for indexing.
Queries no longer force exact search; explicit exact queries remain available
for comparison. Qdrant can still choose a scan for individual segments/filters.
Embedded Qdrant local mode remains exact and does not build an HNSW graph.

With services running, upgrade an existing compatible collection in place:

```powershell
.\.venv\Scripts\python.exe scripts/storage_services.py connect
```

The command validates the embedding manifest and point count, preserves existing
vectors, updates index settings, and waits up to 120 seconds for green status
and indexed-vector count to reach point count before activating configuration.
A timeout preserves data and reports failure; it does not claim indexing is
complete. The Redis retrieval-cache namespace changes to avoid old exact-search
responses. No re-embedding or benchmark is required by this upgrade.

Reference: [Qdrant indexing documentation](https://qdrant.tech/documentation/manage-data/indexing/).

## Migration And Archives

Legacy JSON is validated, imported idempotently and retained. Existing in-memory
API sessions cannot be recovered retrospectively. New API sessions persist task
state and their simulated banking DB together; this is not a real shared bank DB.

Historical experiment files can be archived separately:

```powershell
python scripts/storage_services.py archive
python scripts/storage_services.py check
```

PostgreSQL `artifact_catalog` indexes MinIO SHA-256 objects. Source experiment
paths remain available for replay. New experiment files still initially land in
`data/simulations`; archival is explicit, not a replacement of the benchmark
writer. Archive catalog data never becomes Agent memory. Episode embeddings
remain in bounded per-user PostgreSQL records with existing model-version-aware
retrieval; no additional Memory Qdrant index is introduced.

## Consistency And Recovery

API operations reserve conversations with short PostgreSQL advisory locks and
durable busy flags. No SQL transaction stays open during model/tool execution.
Other workers cannot execute that conversation concurrently. Completed responses
and request receipts commit with snapshots. Reusing a request ID with different
arguments is rejected. Interrupted operations remain blocked across restarts;
reconcile possible tool effects before manual recovery. There is no automatic
expiry/replay of uncertain writes or distributed exactly-once guarantee.

Profiles reject stale revisions; episodes enforce per-user retention. Snapshots
over 16,384 serialized characters are offloaded to MinIO and checksum-verified.
Redis stores policy responses only, never balances or mutation results; outages
are cache misses. Keys include both queries, corpus/index versions and retrieval
configuration. Back up PostgreSQL, MinIO and Qdrant consistently; Redis needs no
backup. Artifact garbage collection and automated reconciliation are not yet
implemented.

## Deployment Status

In the Codex Windows account, `winget.exe` cannot launch and WSL reports access
denied. Docker installation and real-service migration must be completed from
the user's Windows session. Offline tests do not establish service readiness.
