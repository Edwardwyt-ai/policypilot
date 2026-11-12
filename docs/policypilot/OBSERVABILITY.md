# Local Langfuse Observability

## Scope

PolicyPilot retains its JSON trajectories, evaluation outputs and business
snapshots. Optional Langfuse tracing adds a live hierarchy for HTTP requests,
Agent turns, LangGraph nodes, PolicyPilot model calls and Environment tools.
Need/coverage changes and mutation transitions appear as bounded OTel events.
The model wrapper reports usage and known cost, not an invented zero for unknown
cost. Benchmark user-simulator calls are not covered by this model wrapper.
Hidden evaluator operations are suppressed; evaluator criteria are never sent.

The path is: application SDK batch buffer -> local authenticated OTel Collector
-> local Langfuse Web ingestion -> Worker -> platform storage. The Collector
uses a bounded disk-backed export queue and retries transient upstream failures.
SDK and Collector batch buffers before that queue are still memory-resident;
process crashes, queue/disk exhaustion and permanent rejection can lose events.
This is best-effort telemetry, not a replacement for durable business auditing.

## Start

Open Docker Desktop in your Windows session and wait for Engine running.
Use the project virtual environment from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[observability]"
.\.venv\Scripts\python.exe scripts/observability.py setup
```

`setup` creates `.env.observability` only if absent, starts the isolated platform,
emits a synthetic root with generation/tool children, queries it back through
the Langfuse API, and only then enables tracing in local configuration. No real
model or banking tool is invoked. Existing Agent/API processes need restarting.
Initialization never rotates existing credentials; keep this ignored file safe.
Shell environment variables take precedence over the file.

The first startup pulls images and can build the source-pinned MinIO image from
`deploy/minio`; it needs network access and can take several minutes. It does not
change or migrate existing business storage. All platform databases use dedicated
Compose volumes under the `policypilot-observability` project.

Open http://127.0.0.1:13000 . The initialized login is
`admin@policypilot.local`; its generated password is `LANGFUSE_ADMIN_PASSWORD` in
`.env.observability`. The initialized project is PolicyPilot. Only loopback ports
are published: Web 13000, MinIO 13900/13901, Collector 14318/14333. PostgreSQL,
Redis and ClickHouse have no published host ports. Langfuse platform telemetry
and in-app AI features are disabled. This configuration is local development,
not an internet-exposed production deployment or an OS-level egress sandbox.

## Operate And Verify

```powershell
.\.venv\Scripts\python.exe scripts/observability.py init
.\.venv\Scripts\python.exe scripts/observability.py start
.\.venv\Scripts\python.exe scripts/observability.py check
.\.venv\Scripts\python.exe scripts/observability.py smoke
.\.venv\Scripts\python.exe scripts/observability.py enable
.\.venv\Scripts\python.exe scripts/observability.py disable
.\.venv\Scripts\python.exe scripts/observability.py stop
```

- `check` verifies receiver authentication and platform/project readiness. It
  does not prove that a real trace was ingested.
- `smoke` requires root and both child observations to be readable in Langfuse.
  It uses `/api/public/v2/observations` with a trace ID and bounded time range,
  and validates parent/child IDs. The removed legacy `/api/public/traces/{id}`
  endpoint must not be used with this v4 deployment.
  On success, `data/storage/observability-smoke.json` records the trace ID and
  verification time. It does not persistently enable tracing.
- `enable` performs smoke verification before changing the setting. Failed
  verification does not write a new enabled value or claim successful delivery.
- `disable` needs no reachable services; restart running application processes.
- `stop` stops only this observability stack and retains volumes and settings.
  Do not use volume deletion to troubleshoot connectivity.

Instrumentation is fail-open: SDK/export failures must not repeat business work,
change tool results or replace business exceptions. API shutdown flushes queued
spans; process exit also shuts down the provider. Export is not awaited per turn.
API responses include `X-Trace-ID` when tracing is active; local PolicyPilot
message metadata contains `telemetry.trace_id` and `telemetry.span_id`.

## Privacy And Evaluation Boundary

By default only allowlisted metadata, model names, counts, timings and usage/cost
are exported. Raw prompts, responses, queries, tool arguments/results, banking
identities and exception messages are omitted. Correlation identifiers are
hashed. Hashing is pseudonymization, not a guarantee of anonymity. Full private
source material remains in existing local artifacts for authorized debugging.

This change does not add an asynchronous evaluation Worker or enable model-based
judging. A future evaluator should read a finalized evaluation package from our
durable storage, then associate scores with the trace ID; it must not assume an
asynchronously exported trace is complete as soon as the Agent finishes.

## Deployment Status

2026-10-20: SDK contract and regression tests were executed; the Compose model
was validated. The user then started the stack in their own Windows terminal,
and reported successful Collector/platform/project readiness. The old read-back
check failed because it queried the legacy trace endpoint; it has been replaced
with Observations API v2. Ingestion is not yet verified with the corrected check.
Run `enable` in that same terminal; it does not rebuild containers and only
enables tracing after successful root/child read-back. The agent execution
session cannot access the Docker named pipe or local platform ports; that does
not establish that services are down in the user's session.

## References

- [Langfuse SDK advanced configuration](https://langfuse.com/docs/observability/sdk/advanced-features)
- [Pinned upstream platform Compose](https://github.com/langfuse/langfuse/blob/v4.63.0/docker-compose.yml)
