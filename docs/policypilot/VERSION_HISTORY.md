# PolicyPilot Version History

This is the canonical PolicyPilot version ledger. The repository CHANGELOG
continues to track tau2 itself.

## Recording Rules

Update this ledger whenever PolicyPilot reaches an implementation or evaluation
checkpoint. Every entry must record:

1. Version/checkpoint name, date, status, and parent version.
2. Core architecture and state-schema changes.
3. User-visible and agent-behavior changes.
4. Compatibility, migration, dependency, and configuration changes.
5. Verification commands and test results.
6. Task IDs, Reward, DB Check, Required Actions, retrieval count and queries,
   tool calls, context chars, tokens/cost, and latency.
7. Artifact paths.
8. Known issues, failures, and the next decision.

Never mark a version verified or evaluated unless the commands were actually run
and their results were recorded.

## Unreleased - Judge Semantic Repair, Calibration and Incomplete GEPA Reruns

- Date: 2026-10-23. Parent: GEPA Preflight Hardening and Failed Judge Calibration.
- Removed candidate instructions from Judge context. Added independent narrow
  completion review, completion polarity, explicit JSON schemas and corrective
  retries with prior validation error. Unsupported success is a score veto;
  plans, in-progress notices and non-execution statements are not success claims.
- Quote validation now compares words in visible CommonMark text, preserving
  negation while accepting Markdown/whitespace differences. Declared already
  installed markdown-it-py as a prompt-optimization extra; no package upgrade.
- Separated categorical diagnostics from GEPA's numeric side_info.scores;
  added actual installed-SDK regression coverage and checked baseline-score reuse.
- Verification: 73 focused tests passed, 2 existing warnings, exit 0; Ruff and
  offline lock check pass (232 packages). Final paid development calibration
  48/48, 88 Judge responses. Final-parser offline replay 48/48 and historical
  quote replay 4/4, zero provider calls. This is NOT held-out Judge accuracy.
- Multiple failures are preserved, including premature-success false positives,
  numeric objective TypeError, enum/quote validation failures and ineffective
  unchanged schema retries. No completed GEPA candidate-quality comparison.
- Final run7 completed 3 seed examples before a remote disconnect on target
  request 4 (RemoteProtocolError surfaced as InternalServerError); recorded
  request_error, no additional retry. No final best prompt or deploy. Held-out
  test untouched; no banking tools, Reward/DB/Required Actions evaluation, commit
  or push. Existing production instructions and dataset labels unchanged.
- Across calibration3 through run7: 478 successful response records, 1649182
  input / 58607 output tokens; summed API time 1058.636 seconds. Price-map costs
  unavailable, not free; disconnected request billing unknown. Full accounting,
  failure sequence and limitations in
  [repair report](experiments/GEPA_JUDGE_REPAIR_20261023.md).
- Artifacts: data/storage/decision-gepa/v2_20261023_calibration7/ and run3-run7
  plus intervening calibration directories. Next paid search remains outstanding;
  do not treat intermediate candidate files/checkpoints as completed optimization.

## Unreleased - GEPA Preflight Hardening and Failed Judge Calibration

- Date: 2026-10-23. Parent: GEPA Judge Recovery and Audit Fix.
- Unified exact/flexible tool argument schema validation; rejected falsey
  malformed tool-call fields and cross-split scenario_group reuse. Recorded
  request/truncation/optimization status, public model messages and scorer/Judge
  hashes. Added TRAIN-only positive/safety calibration mode and regression tests.
- Verification: 57 focused tests passed, 2 existing warnings; pytest exited 0.
  Ruff lint/format pass for four touched Python files. No full regression run.
- Paid calibration: 8 Judge calls on 4 TRAIN pairs, v4-pro non-thinking;
  expected-score match 5/8. Judge accepted a false refund-success claim, rejected
  a correct constraints-preserving query and gave a false-success query partial
  credit. Schema recovery is fixed, semantic grading reliability is not.
- Calibration intentionally exited 1 with calibration_failed status. Did NOT
  launch GEPA search or use held-out test after failure; no final candidate,
  production prompt change, banking-tool calls, benchmark Reward/DB evaluation,
  dataset edits, commit or push. No post-failure executable-code changes.
- Usage: 27514 input / 995 output tokens, 3840 cached input included; API time
  sum 22.268 seconds; price-map cost unavailable. Artifacts:
  data/storage/decision-gepa/v2_20261023_calibration2/ and
  [Judge calibration report](experiments/GEPA_JUDGE_CALIBRATION_20261023.md).
  Next: reviewed Judge specification/model calibration before prompt search.

## Unreleased - GEPA Judge Recovery and Audit Fix

- Date: 2026-10-23. Parent: V2 GEPA Pilot Aborted by Judge Schema Error.
- Fixed blank Judge explanations without changing validated boolean scores;
  missing explanations are flagged explicitly, never presented as model reasons.
  Strict boolean and safety validation remains unchanged.
- Invalid JSON/verdict schemas retry Judge once with the same frozen Agent
  prediction. No target regeneration. Exhaustion raises JudgeEvaluationError
  without a numeric score; CLI persists evaluator_error, case/candidate identity
  and score=null in run_status.json. Transport exceptions still propagate.
- Added raw per-attempt Judge audit records and recorded retry policy in run
  settings. All additional model calls still pass through usage/cost logging.
  Wrong-tool errors now report the expected tool before testing its argument
  schema, correcting misleading feedback without changing rejection scores.
- Verification: 51 focused tests passed with 2 existing warnings in the pytest
  summary; Ruff lint/format passed. Test process remained alive after the summary
  and was interrupted, exiting 1; clean interpreter shutdown is NOT verified.
  No paid calls, GEPA rerun, benchmark, production prompt change, commit or push.
- Artifacts: decision_prompt_eval.py, optimize_decision_prompt.py,
  test_decision_prompt_eval.py and DECISION_GEPA.md. Existing paid-run artifacts
  and dataset labels were not edited. Semantic Judge calibration remains pending.

## Unreleased - V2 GEPA Pilot Aborted by Judge Schema Error

- Date: 2026-10-23. Parent: Decision Dataset V2 Counterfactual Draft.
- Ran the draft V2 Decision-only GEPA pilot with explicit unreviewed-data
  override, all routes deepseek/deepseek-v4-pro, thinking disabled, seed 0,
  serial evaluation, requested metric budget 64 and proposal cap 3.
- Exit 1: Judge returned an empty feedback string; SemanticVerdict validation
  aborted proposal 2's full validation. No code repair or automatic retry.
  Completed 72 scores, 73 target calls, 68 Judge calls and 2 reflections.
  Batch-boundary budget overshoot is recorded, not hidden.
- Original full validation mean 0.953125 (32 cases). On the same 28 scored
  validation cases, original 0.946429 versus proposal 2 0.857143. Proposal 2
  repaired one training query but did not establish overall improvement.
  Candidate validation is incomplete; no final prompt, held-out test or deploy.
- Usage: 513758 input / 15313 output tokens, 92032 cached input included;
  API time sum 327.052 seconds. Model price-map costs unavailable, not zero.
- Judge calibration remains undone. Recorded suspected semantic grading noise,
  misleading wrong-tool Schema feedback and strict answer-only label limits.
  Banking tools, source data, runtime and production prompt unchanged. Reward,
  DB Check and Required Actions not measured. No tests rerun, commit or push.
- Artifacts: data/storage/decision-gepa/v2_20261023_run1/ and
  [V2 pilot report](experiments/GEPA_V2_20261023.md). Next proposed step is
  evaluator robustness/calibration, not further uncalibrated prompt search.

## Unreleased - Decision Dataset V2 Counterfactual Draft

- Date: 2026-10-23. Parent: Completed Non-Thinking GEPA Pilot.
- Preserved V1 data and completed experiments. Added 96 new synthetic I/O rows:
  train/validation/test 32 each, 24 independent scenario templates, 48 contrast
  pairs with two ID/order variants. All eight capabilities appear in each split;
  scenario groups and pair members do not cross splits. Shared policy documents
  are intentional, so this is scenario hold-out, not unseen-policy evaluation.
- Coverage: known arguments, entity binding, source/freshness, authorization,
  policy boundaries/exceptions, information acquisition/context references,
  mutation verification, multi-turn revisions. Uses native context construction,
  source-qualified facts and tool schemas. Positive mutation outcomes are tool
  messages, not trusted memory; observed excerpts are verbatim visible-source text.
- Historical references are explicitly symptoms or observed frozen-I/O errors,
  not imported exact runtime snapshots. Zero exact historical requests imported.
  No hidden task criteria used. Draft labels and difficulty are not calibrated.
- Added positive/opposite/safety Judge probes, source findings, frozen input and
  label hashes, output-contract validation, schema-checked flexible query/page
  arguments and runtime-compatible missing-information envelopes. V1 remains
  supported. Explicit jsonschema prompt-optimization dependency already installed
  at 4.25.1; offline lock refresh, no package installation or SDK upgrade.
- CLI defaults to V2 inspect; paid modes refuse its unreviewed draft unless
  explicitly overridden. No paid baseline, Judge calibration, GEPA optimization,
  benchmark, production prompt change, commit or push was performed this turn.
- Verification: 41 focused assertions passed, 2 existing warnings; Ruff/format,
  pip check and offline lock check pass. Builder and pytest processes remained
  alive after completed summaries and were interrupted; clean interpreter
  shutdown remains unverified and was not attributed to a specific subsystem.
- Artifacts: data/policypilot/evaluation/decision_gepa_v2/ (7 files),
  scripts/build_decision_gepa_v2.py, docs/policypilot/DECISION_DATASET_V2.md.
  Next: template/label review and TRAIN-probe Judge calibration, then measure
  baseline train/validation difficulty before spending on optimization.

## Unreleased - Completed Non-Thinking GEPA Pilot

- Date: 2026-10-23. Parent: GEPA Installation and First Paid Pilot.
- At the user's request, added experiment-only --thinking disabled for target
  and reflector; production Decision still defaults to thinking enabled. Started
  a fresh run with the same frozen data/model/seed, not a mixed-settings resume.
- Optimization and held-out evaluation both exited 0. Three proposals, 34
  actual evaluations (requested 32; GEPA batch-boundary overshoot), two accepted
  pool members including seed. One paired training minibatch improved 2/3 to
  3/3 by reusing an already-known account ID instead of asking again.
- Seed and accepted child both validation 8/8. SDK tie-breaking retained seed.
  Selected best_prompt.txt is unchanged; no overall prompt gain demonstrated.
  Held-out eight unique cases passed 8/8; identical candidate/seed rows reused,
  not two trials. The accepted non-seed child was not tested on held-out data.
- Optimization 70 API responses, approximately 139.96s, estimated USD 0.128888;
  held-out 16 responses, 27.66s, USD 0.025976. Total 86 responses, 254206 input /
  10348 output tokens, estimated USD 0.154864 using official off-peak prices.
  Including the preceding aborted run, estimated USD 0.273696; not billed cost.
- 30 focused tests and Ruff passed; 2 existing warnings. No truncations, banking
  tool execution, benchmark, deployment, commit or push. Complete report:
  docs/policypilot/experiments/GEPA_NONTHINKING_20261023.md.
- Artifacts: data/storage/decision-gepa/pilot_20261023_nothinking_run1/ and
  pilot_20261023_nothinking_test1/. Next: improve reviewed train/validation
  difficulty and predeclare tie-breaking; do not tune using these test results.

## Unreleased - GEPA Installation and First Paid Pilot

- Date: 2026-10-23. Parent: Frozen Decision Prompt GEPA Pilot.
- Installed and pinned GEPA 0.1.4 in the project venv and prompt-optimization
  extra; uv.lock refreshed without upgrading existing SDKs. SHA256-verified
  official PyPI wheel. Updated CLI for the actual released GEPA configuration
  API, bounded serial search and metered reflection calls. Identical held-out
  candidate/seed results can be explicitly reused without duplicate API spend.
- Verification: 29 focused tests passed, including a real installed-GEPA mock
  evaluation; 2 existing warnings. Ruff, pip check and offline lock check pass.
- Paid run pilot_20261023_run1 used Pro for target/judge/reflection, thinking on
  for target/reflector, seed 0, 32 requested evaluations and 3 proposals maximum.
  Baseline validation 8/8; proposal 1 tied baseline on three training cases and
  was rejected. Proposal 2 aborted when target completion consumed all 8192
  tokens as reasoning (87.377s, finish_reason=length), with no final output.
- 37 API responses, 17 completed evaluations, 112157 input and 27662 output
  tokens. Approximately 334.69s elapsed. Model prices unavailable in LiteLLM;
  separate official off-peak rate estimate USD 0.118831, not billed cost.
  No held-out run, selected prompt, deployment, benchmark, commit or push.
- Full metrics, failure analysis and caveats:
  docs/policypilot/experiments/GEPA_PILOT_20261023.md.
  Raw artifacts: data/storage/decision-gepa/pilot_20261023_run1/ (ignored).
- No automatic token-budget increase or paid rerun after failure. Next decision:
  choose a fixed reasoning/output-budget policy and improve reviewed train/val
  difficulty; preserve the untouched test set.

## Unreleased - Frozen Decision Prompt GEPA Pilot

- Date: 2026-10-22. Parent: Explicit Decision Thinking.
- Added 40 agent-authored synthetic Decision I/O cases grounded in 10 existing
  visible policy documents: train 24, validation 8, test 8; 33 answers and 7 tool
  proposals. Split by document/scenario family. No hidden tasks or evaluator
  criteria are read; labels are not human-reviewed or actual rollout gold.
- Reuses build_agent_context and real tool schemas with synthetic verified
  observations, minimal fixture domain policy and a fixed tool subset. Only
  DECISION_INSTRUCTIONS is evolved; graph, retrieval and live runtime unchanged.
- Added deterministic next-action checks plus injected semantic judge feedback,
  a safety score veto, held-out exclusion, reproducible source/hash manifest,
  optional GEPA optimize/test CLI and documentation. Default CLI only inspects;
  no prompt is auto-deployed. Real-model modes require explicit invocation and
  compatible optional GEPA SDK. Target/judge usage is separate from reflection
  cost; max_evals is not a dollar cap.
- Verification: generated all 40 cases; 28 focused assertions passed (2 existing
  environment warnings); Ruff checks and formatting passed for four new Python
  files. Python processes remained alive after successful output/test summaries
  and were interrupted; clean interpreter shutdown remains unverified.
- No GEPA SDK installation, real optimization, model inference, benchmark,
  reward/cost/latency comparison, commit or push. Real SDK/provider compatibility
  and label review remain prerequisites for an actual optimization experiment.
- Artifacts: data/policypilot/evaluation/decision_gepa_v1/ and
  docs/policypilot/DECISION_GEPA.md. New run outputs default to ignored
  data/storage/decision-gepa/. The tiny synthetic set does not establish
  production or end-to-end gains.

## Unreleased - Explicit Decision Thinking

- Date: 2026-10-22. Parent: current PolicyPilot runtime.
- DeepSeek Decision calls default to thinking enabled; auxiliary nodes retain
  their non-thinking defaults. Explicit call configuration can override defaults.
  Other providers, safety guards and evaluator semantics are unchanged.
- DeepSeek requests carrying tools now preserve reasoning_content on all retained
  assistant messages, including non-tool messages and the Flash model alias.
  Reasoning is not added to user-facing answer content.
- Focused model-routing tests: 14 passed, including defaults, overrides and
  history serialization. The initial broader command also selected two existing
  OpenAI integration tests; both failed for missing API credentials. Local trace
  export was permission-denied; focused rerun disables tracing in its process.
  Rerun assertions completed (14 passed, 2 warnings), but the process did not
  exit promptly after its summary and was interrupted; clean shutdown is not
  verified.
- No benchmark, reward/cost/latency comparison, Git commit or push performed.
  Git status currently reports that this directory is not a work tree.

## Unreleased - Local Langfuse Observability V1

- Date: 2026-10-20. Parent: existing local metrics and trajectory recording.
  Status: instrumentation and local configuration implemented; platform read-back
  pending the corrected verification in the user's Windows session.
- Added optional isolated Langfuse/OTel tracing for API requests, Agent turns,
  workflow nodes, PolicyPilot model usage/cost and external Environment tools.
  Bounded Need/coverage/mutation events and local trace IDs support correlation.
  Export errors do not repeat business execution or replace business exceptions.
  Disabled tracing bypasses node-state inspection. No Agent state-schema or
  hidden evaluator changes; no business authorization is granted by telemetry.
- Added dedicated local Compose services and volumes, authenticated Collector
  disk queue, generated ignored credentials, readiness checks, synthetic smoke,
  explicit enable/disable/stop and setup commands. Raw banking content and
  exception messages are omitted; allowlisted identifiers are hashed. Existing
  private trajectories and DB snapshots remain independent audit artifacts.
- Added observability dependency group and refreshed uv.lock while retaining
  existing storage changes. Installed/tested Langfuse 4.15.6 with OTel 1.39.1;
  pip check passes. SDK 4.18.0/OTel 1.45.1 were also tested before alignment.
- Initial regression: 267 passed, 1 skipped, 3 environment warnings. Compose
  config --quiet and focused Ruff checks pass. Real SDK in-memory exporter
  validates parent/child propagation; this is not platform ingestion evidence.
- User reported successful platform/Collector/project readiness followed by
  failed smoke for e269958bd0e923c9ce876e9cd6e7e972. Root cause in verification:
  legacy GET /api/public/traces/{id} used against v4. Replaced it with bounded
  GET /api/public/v2/observations filtered by traceId; validate root/child IDs,
  reject mismatched traces/parents and retry incomplete asynchronous ingestion.
  Focused tests after this fix: 28 passed, including real SDK and v4 contracts.
- Full rerun after API fix hit a Windows access violation in the existing Memory
  test loading Laya through Torch/Safetensors; it is not recorded as a passing
  full regression. No changes to Laya were made to hide that failure.
  Rerun with only that case deselected: 271 passed, 1 skipped, 1 deselected,
  2 environment warnings. Successful runs cleaned their temporary directories;
  crash artifact data/storage/telemetry-v4-37v9ymg8 remains because cleanup was
  rejected by the execution policy. Pytest cache generation was disabled.
- Docker named-pipe access and local platform HTTP are denied/unreachable from
  the agent session. User-side deployment success does not establish corrected
  trace read-back; run scripts/observability.py enable without rebuilding or
  deleting platform data. Tracing remains disabled until successful verification.
- No paid model calls, benchmark or asynchronous evaluation Worker added. Task
  Reward/DB Check/Required Actions and task-level cost/latency are not measured.
  No commit/push. Usage and limitations: docs/policypilot/OBSERVABILITY.md.

## Unreleased - Open User Simulation Environment V1

- Date: 2026-10-16. Parent: existing API Runtime / service storage / HNSW work.
- Added simulation/users.py and rollout.py plus scripts/simulate_users.py.
  Seeded initialization samples actual synthetic users and private objective,
  preferences, style, disclosure and consent policy without loading task gold.
  Saved scenarios and DB snapshots can be supplied explicitly for reuse.
- Default CLI mode initializes only; paid user/Agent calls require --run and
  --user-model. Rollouts reuse TauConversationRuntime, authorization and pending
  confirmation semantics, with isolated DB copies and Memory/Laya disabled.
  No changes to Agent architecture, tau runtime or hidden evaluator criteria.
- Private artifacts retain initial/per-turn/final snapshots, dialogue, simulator
  usage/cost and runtime traces. Unknown cost remains null; user stopping does
  not imply success. Invalid simulator output/provider errors/runtime errors and
  turn exhaustion have distinct statuses. No Judge or business score added.
- Verification: focused simulation/API tests 33 passed. PolicyPilot regression
  with POLICYPILOT_STORAGE_BACKEND=json in the test child process: 234 passed,
  1 skipped, 2 environment warnings. Ruff passed. Test-only backend selection
  does not edit deployment config or introduce an automatic fallback.
- Unmodified active storage configuration blocks regression at PostgreSQL
  connection timeout (55 passed, 1 skipped before first failure). Windows
  loopback permissions also required a rerun; neither is Agent quality evidence.
- Initialization artifact: data/simulations/user_init_seed42_20261016. CLI help
  checked. No paid rollout or benchmark; Reward/DB Check/Required Actions and
  task-level retrieval/tokens/cost/latency comparisons are not measured.
- Limits: starter scenario coverage only; semantic simulator fidelity and consent
  require later independent review. Direct Runtime harness, not an HTTP load test.
  User profiles/artifacts are private synthetic data, not sanitized exports.
- Tests disable pytest cache and use data/storage TemporaryDirectory. Three
  interrupted-run directories remained; their cleanup was denied by tool policy.
  No commit or push. Usage: docs/policypilot/USER_SIMULATION.md.

## Unreleased - Policy Server HNSW Index

- Date: 2026-10-11. Parent: Service-Backed Persistence V1 / startup repair.
- Server collection: HNSW m=16, ef_construct=100, indexing/full-scan thresholds
  1 KB; ANN queries use hnsw_ef=128 and retain an explicit exact baseline option.
  Embedded local Qdrant remains exact. Agent state/runtime/evaluator unchanged.
- Existing compatible collections are validated and updated in place without
  deleting or re-embedding points. Service connect waits for green/indexed state
  before activation; timeouts preserve points. Retrieval cache keys are versioned.
- Verification: 21 tests passed across Qdrant index, hybrid retrieval and storage
  deployment, using auto-cleaned data/storage temporary paths with pytest cache
  disabled. Tests cover reuse, ANN/exact query options, configuration readiness
  and non-destructive timeout. Two pre-existing environment warnings remain.
- Live Qdrant HTTP connection timed out in this session. Actual server graph
  construction is NOT confirmed; run storage_services.py connect from the user's
  terminal after starting services. No benchmark, recall/speed claim or paid LLM
  run. Reward/DB/actions/tokens/cost/latency are not measured for this checkpoint.
- Artifacts: qdrant_index.py, migrate_policy_vectors_to_qdrant.py,
  storage_services.py, test_qdrant_index.py and STORAGE.md.

## Unreleased - Storage Image Startup Repair

- Date: 2026-10-11
- Follow-up: Qdrant client 1.19.1 does not support context-manager syntax. Fixed
  service preflight to use explicit try/finally close. Diagnostics now retain the
  failing service and sanitized exception text instead of only RuntimeError.
  Six deployment/probe tests passed, including close on success/failure and
  credential redaction; Ruff passed.
  Live connectivity from the Codex account remains limited (PostgreSQL timeout);
  this fix is not evidence that migration completed.
- Failure: Docker Hub rejected the configured MinIO image; concurrent pulls were
  interrupted before migration. An anonymous authenticated Quay probe also failed
  with HTTP 401, so no unverified registry substitution was made.
- Replaced the withdrawn image with a local build from official MinIO commit
  `7aac2a2c5b7c882e68c1ce017d8256be2feea27f`. Go and Debian base images are pinned
  by verified registry digests. No third-party MinIO binary/image is used.
- Launcher validates Compose, pulls three upstream images, builds MinIO and then
  starts services. Every failure stops before configuration activation; volumes,
  credentials, ports and S3 adapters are unchanged.
- Verification: PostgreSQL/Redis/Qdrant tags and both build-image manifests
  returned HTTP 200; upstream commit resolves in GitHub and the Go module proxy.
  Compose `config --quiet` and PowerShell syntax passed; three new offline
  deployment-configuration tests and Ruff passed. No paid benchmark was run.
- Upstream community MinIO is archived: local-development use only, not a claim
  of production security support. Real build/start remains unverified because
  the Codex account cannot access the Docker Engine named pipe.

## Unreleased - Service-Backed Persistence V1

- Date: 2026-10-11
- Scope: PostgreSQL conversations/memory/checkpoints, MinIO snapshot artifacts,
  Qdrant Server policy-vector migration, Redis hybrid-policy response caching.
- Added authenticated loopback-only Compose services and a Windows installation /
  startup script. Credentials live in ignored `.env.services`; `.env.storage`
  activates only after connectivity, memory/checkpoint import and vector checks.
- SQL engines are pooled per worker. Conversation execution uses a durable
  reservation and short transactional lock, with response/snapshot/idempotency
  receipt committed together. Interrupted writes never auto-replay. Profile
  stale revisions are rejected; per-user episodes preserve bounded retention.
- Large snapshots use checksum-verified immutable MinIO objects. Historical
  experiments have an explicit archive command and PostgreSQL catalog; original
  benchmark paths and all legacy source data remain intact. Episode embeddings
  stay with bounded PostgreSQL records, not a new vector index.
- Redis caches policy responses only, keyed by queries, corpus/index versions and
  retrieval parameters. It fails open as a cache miss; SQL/artifact failures do
  not silently fall back to SQLite. SQLite is an explicit offline test adapter.
- Verification: `tests/policypilot`: 215 passed, 1 skipped; focused hybrid retrieval
  and Qdrant tests: 10 passed. The 13 new storage contract tests use temporary
  SQLite, a fake Redis client and botocore S3 stubs, not live services. Ruff passed;
  Compose YAML parsed and PowerShell launcher syntax checked. `uv.lock` updated.
- Installed Python storage drivers. Real-service connectivity check failed with
  OperationalError; Docker is absent and this Codex Windows account cannot launch
  winget / access WSL. `.env.storage` was not created. Docker/server installation
  and production-data migration remain pending in the user's Windows session.
- No paid LLM/benchmark run and no Git commit/push were performed. Remaining
  limitations: no automatic interrupted-operation reconciliation, artifact GC,
  or managed remote TLS/backups. See `STORAGE.md` for the actual deployment status.

## Unreleased - Explicit Context Loading And User-Bound Tool Authorization V1

- Date: 2026-10-09
- Status: implemented; local unit regression verified (no benchmark)
- Parent: Unreleased - FastAPI Delivery Layer V1
- Task state schema: unchanged. Reuses raw payload records, Context Manifest,
  compressor events and context-rehydration events rather than adding parallel
  Facts, Evidence or long-term memory fields.
- Context behavior: retain complete observed dialogue below the configured
  window; overflow archives exact dialogue plus observed payload references,
  keeps pinned semantic state and bounded recent messages, and optionally asks
  the existing light-model compressor for a short historical summary.
- The main Decision model explicitly requests `load_context_ref(ref, offset,
  length)`. LangGraph handles the read internally and returns to Decision,
  without repeating compression or dispatching a banking tool. References must
  belong to this run and current manifest; unknown/stale references, arbitrary
  paths, repeated pages and exhausted budgets are rejected. Loading does not
  promote snapshot content into Facts or Evidence.
- Default limits: three attempts, 1,200 chars per page, 2,400 loaded content chars
  per Decision; full messages, tool arguments and schemas are counted toward
  the estimated context window. Impossible mandatory windows stop before LLM.
  Token counts are estimates, not provider-tokenizer guarantees.
- API identity: credentials bind to server-configured banking user IDs. Browser
  `X-User-ID` cannot choose a principal; incompatible legacy headers return
  403. Added `GET /v1/me`; UI displays server-derived identity read-only.
- API tool authorization: strict argument schemas, current DB resource ownership,
  recursive discoverable-agent/user-tool delegation, preauthorization of whole
  batches and authorization recheck on mutation confirmation. Unknown resource
  policies and broad database/shell access fail closed. No benchmark/evaluator,
  hidden criteria, user simulator or external tau2 execution semantics changed.
- Configuration migration: set `POLICYPILOT_BACKEND_USER_ID` alongside the
  backend key, or configure `POLICYPILOT_BACKEND_USER_TOKENS` (JSON token-to-user
  mapping). Existing arbitrary caller-chosen user headers are intentionally no
  longer supported. README and `.env.example` document the migration.
- Verification: `pytest tests/policypilot -q --tb=short -p no:langsmith`:
  202 passed, 1 skipped in 23.31s; 3 existing warnings (audioop, pytest asyncio
  option, Laya checkpoint calibration). Hugging Face offline flags used for unit tests.
  API TestClient initially blocked in Windows socketpair under network sandbox;
  rerun after permission was granted passed. No paid model calls or benchmarks.
- Additional checks: Ruff lint/import checks and Node JavaScript syntax check.
- Benchmark Task IDs / Reward / DB Check / Required Actions / retrieval queries /
  tool counts / tokens / cost / latency: not measured in this checkpoint.
- Artifacts: `src/policypilot/context_loading.py`,
  `src/policypilot/api/authorization.py`,
  `tests/policypilot/test_context_loading.py`,
  `tests/policypilot/test_api_authorization.py`, and `tests/policypilot/test_api.py`.
- Limits: opaque server-managed credentials are not OAuth/OIDC. Conversation and
  snapshots remain process-local. API ownership policies cover declared resource
  relationships only; unsupported workflows fail closed. Prompt delimiters are
  defense in depth, not a complete prompt-injection or OS sandbox solution.
- Git commit/push: not requested and not performed for this checkpoint.

## Unreleased - FastAPI Delivery Layer V1

- Date: 2026-10-06
- Status: implemented and unit-verified
- Parent: Unreleased - Local Runtime Preflight V1

### Architecture And Behavior

- Added an authenticated FastAPI application around the existing
  `PolicyPilotAgent` and banking environment without changing the LangGraph,
  tau2 tool-execution, or evaluator contracts.
- Added user-owned conversations, idempotent message and action requests,
  event streaming, liveness/readiness endpoints, and generated OpenAPI docs.
- Read tools still execute through the tau2 environment. Mutation calls are
  staged as `AWAITING_CONFIRMATION` and execute only after the API receives an
  explicit confirmation; cancellation discards the staged action.
- The `policypilot-api` entry point loads the repository `.env` and runs the
  existing Ollama preflight before serving `local_hybrid` retrieval.

### Compatibility

- Laya remains disabled by default for API conversations. Memory remains bound
  to the authenticated `X-User-ID` and does not replace live tool verification.
- Conversation records and idempotency responses are process-local in V1, so a
  server restart clears active conversations. Durable database and distributed
  worker adapters remain future backend work.

### Verification Evidence

- Ruff passed for the API source, API tests, and project configuration.
- API and runtime-preflight tests: `11 passed`.
- Full non-integration PolicyPilot regression: `174 passed, 1 deselected`.
- No paid model request or benchmark task was run.

### Known Issues And Next Decision

- Replace the in-memory conversation repository with a durable store before
  multi-process deployment, and replace the shared backend key with the
  application's production identity provider before exposing the service.

## Unreleased - Local Runtime Preflight V1

- Date: 2026-10-02
- Status: implemented, unit-verified, and local-service-smoke-verified
- Parent: Unreleased - Lightweight Coverage Manager V1

### Architecture And Behavior

- The V1 evaluation runner now checks the local Ollama embedding runtime before
  any `local_hybrid` benchmark task begins. A healthy service must expose the
  configured model and return a non-empty embedding vector.
- When Ollama is unavailable, the preflight first uses
  `POLICYPILOT_OLLAMA_START_SCRIPT`, then searches for the sibling
  `qwen-api/start-qwen-api.ps1`, and finally falls back to `ollama serve` when
  the executable is on PATH.
- Missing services, models, and invalid embedding responses fail before the
  tau2 simulation loop, preventing repeated retrieval infrastructure failures.
  `--skip-runtime-preflight` remains available for externally managed runtimes.
- Qdrant local persistence and the Laya reranker are in-process components and
  therefore do not receive separate service launchers.

### Verification Evidence

- Runtime preflight tests: `5 passed`.
- A real local health check found `qwen3-embedding:0.6b` and returned a
  1,024-dimensional vector. A runner-entry smoke confirmed preflight executes
  before task selection without invoking a paid model.
- Full PolicyPilot regression: `160 passed, 1 skipped`; Ruff passed. No paid
  benchmark was rerun because task behavior and evaluator semantics did not
  change.

## Unreleased - Lightweight Coverage Manager V1

- Date: 2026-10-02
- Status: implemented and unit-verified
- Parent: Unreleased - Repository Directory Organization V1

### Architecture And Behavior

- Added one batched `coverage_manager` call on the light-model route for each
  successful policy retrieval. It judges semantic evidence coverage without
  creating Needs, choosing tools, changing the Goal, or emitting user actions.
- The manager receives at most eight candidate policy Needs. Its compact context
  contains only Need identity fields, matching hard constraints, document
  references, and the bounded latest evidence summary; dialogue history, tool
  catalogs, Memory, Skills, Facts, and the full coverage matrix are excluded.
- Structured output contains only `need_id` and `MATCH`/`PARTIAL`. Omitted Needs
  mean `NO_MATCH`; invented IDs are ignored. The light-node output budget is 180
  tokens and the default input-character budget is 2,400.
- Deterministic validation still rejects entity/scope conflicts and downgrades a
  semantic `MATCH` that fails an explicit hard constraint. The main Decision LLM
  retains final response and tool-call authority.
- On timeout, invalid output, or provider failure, the trigger Need remains
  conservatively `PARTIAL` instead of being falsely resolved or exhausted.
- Existing deterministic coverage remains available when the semantic manager
  is disabled, preserving offline and unit-test behavior.

### Verification Evidence

- Added tests for compact context construction, one-call batching, semantic
  paraphrases, entity and hard-constraint vetoes, invented IDs, and provider
  failure fallback.
- Focused Coverage, Requirement, Need Registry, and model-routing tests:
  `46 passed`.
- Full PolicyPilot regression: `155 passed, 1 skipped`.
- Ruff passed for all PolicyPilot source and tests.
- Real `task_001`, seed 0 benchmark completed after starting the configured local
  Ollama embedding service. Reward `0.0`; DB Check `false`; Required Actions
  `0/1`; 16 steps; 4 tool calls, all policy retrievals; termination `user_stop`.
- The four `coverage_manager` calls used `deepseek/deepseek-flash`, were `4/4`
  structurally valid, consumed 3,487 input and 82 output tokens, cost
  `0.00095634`, and added 2.999 seconds of model latency. Total run usage was
  17,430 input and 1,236 output tokens, cost `0.00351348`, with 26.682 seconds
  end-to-end latency. The source DB was unchanged.
- The run exposed two unresolved semantic failures. Generic rewards-redemption
  evidence was incorrectly accepted as full coverage for the comparative
  `best cashback` Need, while candidate-product evidence remained partial. A
  later goal-correction plan replaced the original comparative goal with the
  user's complaint and dropped the cashback criterion. Broad repeated product
  queries consequently retrieved irrelevant policy and the agent refused the
  request without making the required recommendation/action.
- Valid-run artifact:
  `data/simulations/coverage_manager_task001_seed0_20261002_170500`.
- Environment diagnostics are retained separately: the first attempt could not
  create the run directory, and the second stopped after ten embedding failures
  because the local Ollama service was not running. Neither diagnostic attempt
  exercised semantic coverage successfully.

## Unreleased - Repository Directory Organization V1

- Date: 2026-10-01
- Status: implemented and regression-verified
- Parent: Unreleased - Retrieval Failure Semantics V1

### Scope

- Removed the legacy tau2 `airline`, `retail`, and `telecom` domain source,
  datasets, workflow media, and domain-specific tests.
- Removed the legacy domain README, the obsolete three-domain per-task summary
  script, and the legacy hyperparameter experiment package that imported
  Telecom internals.
- Replaced the root tau2-oriented README with a PolicyPilot-focused project
  README and updated contributor/test documentation and CLI examples.
- Kept the generic tau2 orchestrator, environment, evaluator, voice/gym
  framework code, and the `mock` domain used by framework unit tests.
- The runtime registry now exposes only `banking_knowledge` and `mock` as
  domains and task sets.

### Repository Impact

- Deleted 78 tracked files totaling 137,661,596 bytes (131.28 MiB) from the
  current Git baseline.
- No PolicyPilot state schema, decision behavior, evaluator semantics, hidden
  criteria, or banking task data changed as part of this cleanup.

### Verification Evidence

- Registry import confirmed domains/task sets: `mock`, `banking_knowledge`.
- PolicyPilot + banking knowledge + mock suite: `653 passed, 86 skipped`.
- Generic core suite: `253 passed, 1 skipped, 1 xfailed`; 17 tests attempted
  unconfigured live OpenAI calls and failed authentication. No deleted-domain
  import or registration failure occurred.
- No benchmark task was run because this change only removes unregistered
  legacy domains and repository documentation/assets.

## Unreleased - Retrieval Failure Semantics V1

- Date: 2026-09-30
- Status: implemented, full-unit-verified, and post-fix task-smoke-evaluated
- Parent: Unreleased - Final Response Judge V1

### Architecture And Behavior

- Added `infrastructure_failure` as a distinct error category for knowledge-tool
  execution failures. A failed transport or embedding call is no longer treated
  as a successful retrieval with missing policy coverage.
- Retrieval events now have a pending phase. They enter the durable trajectory
  only after Guard validation succeeds and the tool call is actually emitted,
  eliminating events for blocked calls that never reached the environment.
- Per-Need retrieval attempts are committed only after a knowledge lookup
  executes successfully. Successful empty results still consume an attempt;
  execution failures do not update Coverage or exhaust the business Need.
- Infrastructure failures reopen the active acquisition, preserve the existing
  Need, release the failed query signature for recovery, and do not consume the
  Goal-level successful-retrieval budget.
- Infrastructure-only observations are excluded from business no-progress
  accounting. Actual tool calls and structured errors remain recorded, and the
  existing consecutive-error budget still bounds persistent outages.

### Failure Evidence

- Pre-fix `task_001` with Laya disabled produced Reward `0.0`, DB Check `0.0`,
  Required Action `0.0`, three `KB_search` calls, 14 messages, 47.41 seconds,
  and total reported cost `$0.003322`.
- All three retrievals failed with `Embedding request failed after 3 attempts`
  because `127.0.0.1:11434` was unavailable. The old lifecycle incorrectly
  exhausted policy Needs and recorded five retrieval events for three emitted
  calls.
- Artifact:
  `data/simulations/diagnostic_task001_no_laya_seed0_20260930/tasks/task_001/results.json`.

### Verification Evidence

- Added a regression that reproduces the embedding failure, verifies zero Need
  attempt consumption, confirms explicit infrastructure-failure telemetry, and
  proves the same query can run after recovery.
- Focused Guard, Need, and architecture regression: `58 passed`.
- Full PolicyPilot regression: `148 passed, 1 skipped`.
- Ruff passed for PolicyPilot source, tests, and scripts.
- Post-fix `task_001`, with Laya disabled and seed 0, produced Reward `0.0`, DB
  Check `0.0`, Required Action `0.0`, seven actual tool calls, and seven durable
  retrieval events. The run used 63,652 traced input tokens and 9,226 output
  tokens, cost `$0.099216`, took 127.65 seconds, and ended with `user_stop`.
- The first retrieval failed with Windows `os error 1455` and was correctly
  recorded as an uncommitted `INFRA_FAILURE`; the same query then succeeded.
  This verified the repaired failure lifecycle in a real trajectory.
- The remaining task failure is retrieval-planning related: evidence for Bronze,
  Silver, Platinum, and Diamond prematurely closed comparative coverage without
  retrieving the Gold Rewards Card terms. Repeated anchored lookups exhausted
  the Goal retrieval budget before the later no-fee correction could run.
- Post-fix artifact:
  `data/simulations/diagnostic_task001_no_laya_infra_fix_20260930/tasks/task_001/results.json`.

## Unreleased - Final Response Judge V1

- Date: 2026-09-27
- Status: implemented, unit-verified, and one-call API-smoke-verified
- Parent: current PolicyPilot working tree

### Evaluation Architecture

- Added an evaluator-only Final Response Judge for saved `results.json` files.
- The judge uses three structured dimensions only: correctness, completeness,
  and grounded safety. `semantic_score` is their mean and `semantic_pass`
  requires all three dimensions with no critical error.
- Added sidecar Gold for the existing 67-task Need evaluation set. Criteria are
  derived from reviewed Need descriptions and completion conditions and are
  never exposed to the PolicyPilot runtime.
- Added bounded evidence-packet extraction that labels user messages, agent
  responses, tool calls, tool results, and tau3 DB outcomes separately.
- The default judge route is `deepseek/deepseek-chat`, reusing the existing
  `DEEPSEEK_API_KEY`; `POLICYPILOT_JUDGE_MODEL` can override it.
- A one-call `deepseek-reasoner` smoke produced truncated JSON after exhausting
  its output budget. The structured Judge therefore defaults to `deepseek-chat`
  and retries one malformed response with a compact repair request.
- Original tau3 DB/Action rewards remain unchanged and are reported separately.

### Verification Evidence

- Final-response Judge unit tests: `3 passed`.
- Observability/Gold regression selection: `15 passed`.
- Ruff passed for the Judge module, Gold builder, evaluator CLI, and tests.
- Generated and schema-validated evaluator-only criteria for all 67 selected
  tasks.
- A real `deepseek-chat` smoke on a saved failed `task_001` trajectory returned
  valid JSON in 2.05 seconds with 4,669 input tokens, 283 output tokens, and
  reported cost 0.0017403. All three semantic dimensions failed, consistently
  with the saved tau3 Reward 0 and DB Check false.
- No benchmark task was rerun and no original task/evaluator criterion changed.

## Unreleased - Bounded Context Reference Rehydration V1

- Date: 2026-09-26
- Status: implemented and full-unit-verified; benchmark not run
- Parent: Unreleased - Qdrant Policy Index V1

### Architecture

- Added an explicit deterministic `hydrate_context` graph node between
  decision-ready Need routing and `build_context`.
- Reused existing `payload_ref`, `evidence_refs`, `policy_refs`, raw payloads,
  and Context Manifest provenance instead of introducing a parallel memory or
  evidence state tree.
- Context summaries now expose resolvable Evidence, payload, and policy-document
  references. Rehydrated Evidence and Need IDs are included in the canonical
  Context Manifest surface.
- Rehydration is restricted to lossy task-local Tool Evidence that is linked to
  a Need or textually relevant to the current Goal. Raw user payloads are never
  automatically rehydrated.

### Behavior And Budgets

- Policy references are re-extracted against the current Goal/Need focus;
  transaction payloads are re-projected through the existing deterministic tool
  projection rather than copied into the prompt verbatim.
- A decision context may load at most two references, 1,200 content characters
  per reference, and 2,400 content characters in total. Duplicate payload
  references are loaded once per context.
- Rehydrated content is a separately bounded context channel and remains subject
  to the existing total-context compressor threshold.
- Each hydration event records payload refs, Evidence IDs, Need IDs, character
  count, and reference count for trajectory attribution.

### Verification Evidence

- Context reference, provenance, model-routing regression: `17 passed`.
- Full PolicyPilot regression: `137 passed`.
- Full banking knowledge regression: `502 passed, 85 skipped`.
- Ruff and Python compilation checks passed. Warnings were limited to existing
  host/deprecation configuration warnings.
- No API-backed benchmark or task evaluation was run.

## Unreleased - Qdrant Policy Index V1

- Date: 2026-09-26
- Status: implemented and banking-knowledge-unit-verified; benchmark not run
- Parent: Unreleased - Decision-Closed Need Lifecycle V1

### Architecture

- Migrated the `local_hybrid` dense retrieval backend from direct NumPy matrix
  search to a Qdrant collection while preserving BM25 fusion, reranking, source
  aggregation, and the external `KB_search` contract.
- Added embedded local persistence as the default and URL/API-key configuration
  for Qdrant Server or Cloud. NumPy remains an explicit rollback backend and the
  source artifact used by the deterministic migration command.
- Collection metadata validates model, chunk hash, row count, dimensions, and
  distance before serving queries. Point payloads preserve row/chunk/document
  identity and source metadata.
- Local Qdrant clients are reference-counted per resolved path so concurrent
  Environment objects in one evaluation process do not compete for the same
  storage lock.

### Migration Evidence

- Imported 1,029 normalized 1,024-dimensional vectors from the existing
  `qwen3-embedding:0.6b` NumPy index into `banking_policy_chunks_v1`.
- Source chunk hash: `444e68b383ac18dbc6f522c4572e0ecc476f7833a0aec1b2e95a124dbeffa5fb`.
- Verified payload/vector alignment for rows 0, 514, and 1,028.
- Compared five source-row queries against NumPy exact Top-30: every query had
  30/30 overlap and identical rank order; maximum score difference was below
  `1.4e-7`.
- Local Qdrant storage size after migration was approximately 12.7 MB.

### Verification Evidence

- Qdrant and hybrid retrieval regression: `9 passed`.
- Full banking knowledge regression: `502 passed, 85 skipped`; only existing
  host/deprecation warnings were emitted.
- Runtime construction confirmed that `local_hybrid` loaded
  `QdrantDenseIndex`, collection `banking_policy_chunks_v1`, with 1,029 points.
- A live local query for a personal no-annual-fee cashback card completed through
  Ollama query embedding, Qdrant retrieval, and local reranking, returning the
  relevant no-annual-fee personal-card policy.
- Ruff checks and Python compilation passed for the changed Python modules.

### Compatibility And Operations

- Added the `qdrant-client` knowledge dependency and environment variables
  `POLICYPILOT_QDRANT_PATH`, `POLICYPILOT_QDRANT_COLLECTION`,
  `POLICYPILOT_QDRANT_URL`, and `POLICYPILOT_QDRANT_API_KEY`.
- Run `python scripts/migrate_policy_vectors_to_qdrant.py` after rebuilding or
  changing the chunk/embedding index. Existing collections require the explicit
  `--recreate` flag.
- No tau2/tau3 Orchestrator, Environment tool execution, hidden task criteria,
  or Evaluator semantics changed. No API-backed benchmark was run.

## Unreleased - Decision-Closed Need Lifecycle V1

- Date: 2026-09-21
- Status: implemented and full-unit-verified; benchmark rerun pending
- Parent: Unreleased - Bounded Decision Retrieval Authority V1

### Architecture

- Kept the single Need Registry and upgraded Need lifecycle semantics with
  `PARTIALLY_COVERED`, `REOPENED`, `NOT_APPLICABLE`, and `EXHAUSTED` states.
- Added derived Requirement, candidate/aspect Coverage, and Retrieval Gap views.
  They are computed from `StructuredGoal` and `InformationNeed`; no parallel
  mutable coverage matrix was added to `PolicyPilotState`.
- Stabilized Goal target updates and separated action mentions/questions from
  explicit transactional authorization.
- Replaced query-scoped business-scope mutation with dedicated `query_id` and
  `query_objective` fields. Internal lifecycle IDs are excluded from KB queries.
- Bounded Semantic Planner output to six Need deltas per call. Its compact input
  remains bounded to eight active Needs, six resolved Needs, two evidence
  summaries, and truncated user/skill context.

### Behavior

- A new or changed hard constraint can reopen matching resolved Policy Needs.
- Partial evidence remains an active Retrieval Gap rather than completing a Need.
- A non-applicable customer identifier can be closed without inventing a user ID
  when the user explicitly says they are new or have no account and no live
  status/mutation is requested.
- Decision-authored corrective retrieval retains the business scope, receives a
  one-attempt query lifecycle, and cannot leak query hashes into later searches.
- Decision context receives a bounded Requirement/Gap summary; the lightweight
  planner does not receive the full derived Coverage view.

### Verification Evidence

- Targeted Requirement/Need/Guard regression: `56 passed`.
- Full PolicyPilot regression: `105 passed`, with two unrelated host warnings.
- Ruff and PolicyPilot compile checks passed.
- No API-backed benchmark was run.

### Known Issues And Next Decision

- Candidate-level coverage quality still depends on specific candidate entities
  being present in registered Needs; this change does not introduce a new entity
  extraction model or Hybrid RAG layer.
- After unit verification, rerun `task_001` only with explicit approval and compare
  intent stability, target stability, query text, Need growth, and action outcome.

## Unreleased - Bounded Decision Retrieval Authority V1

- Date: 2026-09-21
- Status: implemented and full-unit-verified; benchmark rerun pending
- Parent: Unreleased - Layered Agent Package Structure V1

### Architecture

- Relaxed the read-only Decision retrieval gate: a valid, non-duplicate KB
  query no longer requires a pre-existing OPEN Policy Need. Canonical Needs are
  still reused when possible; distinct corrective queries receive a bounded
  query-scoped Need after the canonical attempt limit is reached.
- Kept transactional reads and mutations under their existing strict authority
  checks. Task-wide retrieval budgets, one-query-per-turn normalization, tool
  schema validation, and cross-turn normalized-query deduplication remain in
  force.
- Exposed only the read-only `KB_search`, `KB_search_bm25`, and
  `KB_search_dense` capabilities to the main Decision LLM. Transactional reads,
  mutations, `grep`, and `shell` retain their existing authority boundaries.
- Added deterministic binding for Decision-authored retrieval calls. A direct
  lookup reuses and reopens the canonical Policy Need when prior evidence is
  insufficient, rather than creating parallel state.
- Direct retrieval remains subject to tool-schema validation, duplicate checks,
  per-goal retrieval budgets, per-Need attempt limits, and the existing tau2
  external tool-execution boundary.
- Added `decision_knowledge_tools_enabled` as a strict-mode compatibility switch.

### Behavior

- Added `scripts/test_policypilot.sh` with explicit `unit` and `eval` modes.
  The free verification path is the default; API-backed evaluation must be
  requested explicitly and receives a timestamped output directory.
- Decision may now request a fresh KB lookup when supplied evidence is missing,
  off-scope, or insufficient for a recommendation or negative conclusion.
- Decision-authored retrievals carry `origin=decision`, a canonical Need ID,
  query history, acquisition history, and normal evidence/coverage processing.
- Multiple Decision-authored KB calls in one response are normalized to the
  first call. Later retrievals are reconsidered on the next turn using the new
  evidence, keeping authority and cost bounded.
- Live banking facts and transactional reads still require registered TOOL
  Needs. Mutation preconditions and mutation verification behavior are unchanged.

### Triggering Evaluation

- Artifact: `data/simulations/vscode_task001_seed0_20260921_133718`.
- Task: `task_001`; Reward `0`; DB Check `false`; Required Actions `0/1`;
  retrieval count `1`; tool calls `1`; termination `user_stop`.
- Initial query: `card cashback rewards points rate cash back rewards rate`.
- Two Decision-authored corrective KB queries were blocked as `KB_UNBOUND`
  after broad coverage incorrectly resolved the critical Policy Needs.
- Average context: `16,831.5` chars; total tokens: `21,156` input and `24,504`
  output; total cost: `$0.108666224`; end-to-end latency: `313.196805s`.

### Verification Evidence

- Relaxed Decision retrieval Guard targeted tests: `14 passed`, including
  query-scoped corrective binding and cross-turn duplicate-query blocking.
- Full regression after the Guard relaxation: `99 passed`; Ruff and PolicyPilot
  compile checks passed. No API-backed benchmark was run.
- Bash helper help output and missing-task guard: passed.
- Bash helper `unit` mode: `97 passed`, two unrelated host warnings; Ruff and
  PolicyPilot compile checks passed.
- Final targeted Guard tests: `12 passed`, two unrelated host warnings, 0.15s.
- Full PolicyPilot regression: `97 passed`, two unrelated host warnings, 5.21s.
- Ruff for `src/policypilot` and `tests/policypilot`: passed.
- PolicyPilot compile check: passed.
- API-backed task rerun: not run.

### Known Issues And Next Decision

- Coverage matching remains broad and can still mark mixed retrieval results as
  complete. Direct Decision retrieval provides a bounded escape hatch but does
  not replace the planned coverage-quality correction.
- Rerun `task_001` only after explicit approval because it incurs external-model
  cost; compare retrieval count, queries, Guard blocks, action completion,
  context, tokens/cost, and latency against the triggering artifact.

## Unreleased - Layered Agent Package Structure V1

- Date: 2026-09-14
- Status: implemented and unit-verified; benchmark not run
- Parent: Unreleased - Blocking Need Lifecycle V1

### Architecture

- Reduced `agent.py` from 1,014 to 329 lines. It now owns the tau2 adapter,
  dependency composition, and compatibility delegates instead of observation,
  action validation, recovery, and metrics algorithms.
- Added `workflow/` for LangGraph topology and compact context construction;
  added `runtime/` for observation, action, and recovery mechanics; expanded
  `observability/` to own metadata, metrics, and offline evaluation.
- Runtime modules use narrow host protocols and stateless functions. This keeps
  the existing dependency injection surface without introducing manager layers
  or a second Agent framework.
- Kept top-level `graph`, `context`, `metrics`, and `evaluation` modules as
  backward-compatible re-export shims. tau2 Orchestrator, Environment, tool
  execution, Evaluator, state schema, prompts, and policy behavior are unchanged.
- Added `docs/policypilot/PROJECT_STRUCTURE.md` with package ownership,
  dependency direction, and extension rules.

### Verification Evidence

- Focused Ruff and import checks for `agent`, `workflow`, `runtime`, and
  `observability`: passed.
- Full PolicyPilot unit suite after the first extraction stage: `76 passed`, two
  unrelated host warnings, 3.79s.
- Final source Ruff check and `compileall`: passed. Final PolicyPilot unit suite:
  `76 passed`, two unrelated host warnings, 3.12s.
- A repository-wide Ruff invocation also reported one pre-existing import-order
  issue in `tests/policypilot/test_tool_policy.py`; this refactor did not modify
  that test file.
- No API-backed benchmark was run because this checkpoint changes package
  ownership rather than agent behavior.

## Unreleased - Blocking Need Lifecycle V1

- Date: 2026-09-14
- Status: implemented, unit-verified, and real task_010 evaluated; benchmark failed
- Parent: Unreleased - Canonical Need Registry And Lightweight Runtime V1

### Architecture

- Replaced the operational `OPEN/ACQUIRING/RESOLVED` lifecycle with formal
  `OPEN/RESOLVED` state plus explicit `blocking`, `actionable`, and `exhausted`
  semantics. Only unresolved, blocking, actionable Needs can route acquisition.
- Renamed the single lifecycle owner to `NeedManager` while preserving
  `NeedRegistry` as a compatibility alias. It now owns canonicalization,
  goal-relative generic entity normalization, stable semantic identity,
  evidence reuse, deduplication, resolved reuse, criticality validation, and
  registration.
- Removed formal Need truncation and Planner NeedCandidate truncation. Unknown
  aspects are retained as normalized dynamic aspects with provenance instead of
  being dropped or coerced to a broad policy category.
- Added one deterministic blocking-Need selector, retrieval exhaustion release,
  semantic no-progress detection, and bounded blocker release. Open optional or
  exhausted Needs remain visible for audit but cannot hold the Decision route.
- Structured Tool and Retrieval results remain deterministic state updates and
  never invoke the Semantic Planner. Read retries retain the original Need ID.
- Added per-turn Planner token data, Need selection counts, acquisition result
  traces, coverage, and semantic progress events.

### Verification Evidence

- Focused Ruff checks for all changed runtime modules and tests: passed.
- `python -m compileall -q src/policypilot`: passed.
- Full PolicyPilot unit suite with a project-local pytest temp directory:
  `76 passed`, two unrelated host warnings, 4.01s.
- Added coverage for duplicate/resolved reuse, evidence MATCH/PARTIAL behavior,
  optional and exhausted non-blocking behavior, one-Need selection, deterministic
  ToolResult handling, Retrieval non-proliferation, dynamic aspects, source
  routing, no open-Need loop, no-truncation, and no-progress finalization.

### Compatibility And Real Evaluation

- tau2 Orchestrator, Environment, tool execution, evaluator, hidden criteria,
  memory boundary, and external message/tool-call semantics are unchanged.
- No new dependency or Agent framework was introduced. Semantic Planner output
  is capped at 400 tokens with temperature 0.1 and DeepSeek thinking disabled.
- Final `task_010` seed-0 result: Reward 0, DB false, Required Actions 1/2,
  `user_stop`, 28 steps, 7 tools, 2 Retrievals, 3 Planner calls, and 8 Decision
  calls. Planner used 6,007/878 tokens; Decision used 57,089/9,053; total cost
  was $0.087472 and end-to-end latency was 95.787s. Source DB was unchanged.
- Every blocking Need resolved; open optional Needs did not route. Failure moved
  to Decision/Guard recovery: Decision proposed six unregistered KB calls, Guard
  blocked them, generic refusal text hid the recovery reason, and the user-side
  referral submission did not occur after verification succeeded.
- Full report and artifact:
  `docs/policypilot/BLOCKING_NEED_LIFECYCLE_20260914.md` and
  `data/simulations/blocking_need_lifecycle_task010_seed0_final_20260914`.

## Unreleased - Canonical Need Registry And Lightweight Runtime V1

- Date: 2026-09-13
- Status: implemented and unit-verified; real task_010 evaluated and failed
- Parent: Unreleased - Managed Skills V2

### Architecture

- Added a finite banking aspect taxonomy, `NeedCandidate`, one canonical
  `NeedRegistry`, stable semantic keys, strict evidence coverage
  (`MATCH/PARTIAL/NO_MATCH`), resolved-Need no-reopen behavior, and per-Need plus
  per-task retrieval budgets.
- Deterministic and LLM planners now emit candidates rather than writing formal
  `InformationNeed` objects. Only registered read capabilities may become TOOL
  information needs; mutations and transfer actions remain Decision actions.
- Retrieval queries are built from canonical entity, aspect, scope, confirmed
  constraints, and gap terms. Raw user utterances are excluded.
- Lightweight calls share a compact base prompt and bounded output. DeepSeek
  thinking is disabled through `extra_body` because the installed LiteLLM
  adapter drops `thinking={type: disabled}`. Context compression is a one-call
  fallback after deterministic filtering and did not run in the final task.
- Added planner, registry, retrieval, compressor, and tool-history trace data.

### Verification Evidence

- Full PolicyPilot tests: `65 passed`, two unrelated host warnings, 3.05s.
- Focused Ruff checks for all changed modules and tests: passed.
- Final real command: `scripts/evaluate_v1.py --task-ids task_010` with
  DeepSeek, seed 0, max steps 40, max errors 10.
- Final task_010: Reward 0; DB Check false; Required Actions 0/2; 20 steps;
  4 tools; 2 retrievals; 0 duplicates; 0 guard blocks; user_stop.
- Final LLM use: Planner 4 calls, 7,759/1,666 tokens, 8.088s, $0.004289;
  Skill matcher 1 call, 308/11 tokens, 0.800s, $0.000068; Decision and
  Compressor 0 calls. Total agent cost $0.004357; end-to-end cost $0.005070;
  latency 15.915s.
- Final retrievals both targeted
  `POLICY|banking_product|eligibility_rule|banking_product`; both were PARTIAL.
  The second was allowed because the first left the same gap partially covered.

### Outcome And Known Failure

- Relative to `semantic_routing_task010_final`, steps fell 52.4%, tools 73.3%,
  retrievals 84.6%, end-to-end latency 91.5%, agent input tokens 91.2%, agent
  output tokens 95.2%, and measured agent cost 95.7%.
- These are not task-quality gains: Reward remained 0 and required actions
  regressed to 0/2. A Planner candidate used generic entity/scope
  `banking_product` for a referral eligibility proposition. Retrieval returned
  relevant referral documents, but strict coverage correctly kept the generic
  Need PARTIAL. After two attempts the critical Need blocked Decision, so
  `log_verification` and `submit_referral` were never called.
- Detailed report and artifacts:
  `docs/policypilot/NEED_REGISTRY_LIGHTWEIGHT_20260913.md` and
  `data/simulations/need_registry_lightweight_task010_seed0_final_20260913_v2`.

## Unreleased - Managed Skills V2

- Date: 2026-09-11
- Status: verified (unit/static only; benchmark pending)
- Parent: Unreleased - Skills And Cache Foundations V1

### Architecture

- Expanded the existing Skill loader, matcher, and runtime rather than creating
  a parallel subsystem.
- Added metadata-only discovery, lazy main-artifact loading, path-safe reference
  loading, deterministic phase/tag selection, whole-block context budgeting,
  bounded multi-Skill activation, and structured usage trace events.
- The managed set now contains six Skills: constraint-aware recommendation,
  failure diagnosis, policy-grounded transaction, ambiguity resolution,
  evidence conflict resolution, and retrieval investigation.
- Added deterministic authoritative read-back Need creation for uncertain
  mutations. The Guard, task Fact invalidation, and verification route retain
  enforcement ownership; Markdown does not provide this guarantee.

### Behavior And Compatibility

- Decision receives only phase-applicable guidance and selected references.
  Retrieval planning material is excluded from Decision by phase metadata.
- Current Planner and Recovery remain deterministic and do not consume Skill
  prose. Their guidance artifacts are ready for future consumers without adding
  an LLM call now.
- Skill matching remains limited to new goals, major subgoal changes, and
  recovery-mode changes. At most three relevant Skills are active by default.
- tau2 ToolCall, Environment execution, ToolMessage return, and evaluator
  semantics are unchanged. No ToolNode, Agent, Policy Engine, or State schema
  parallel was introduced.

### Verification Evidence

- Six Skill artifacts passed the standard `quick_validate.py` validator.
- New Skill/runtime/safety tests: 8 passed in 0.08 seconds.
- Full PolicyPilot test suite: 41 passed in 0.29 seconds.
- Focused Ruff check for changed Python modules and tests: passed.
- The first full-suite attempt used pytest's default user temp directory and
  encountered 13 setup permission errors caused by the host's Unicode username
  path. Re-running with a repository-local `--basetemp` produced 41 passes and
  no assertion failures.
- Warnings: Python `audioop` deprecation and an unavailable pytest-asyncio
  configuration option; neither caused a test failure.
- Benchmark and smoke evaluation are out of scope for this checkpoint.

### Known Issues And Next Decision

- Runtime behavior is unit-verified but has not been benchmarked with real LLM
  trajectories. Measure context size and selection quality in a later explicit
  evaluation task.
- The repository-local `.pytest-tmp-skillv2` directory was generated by the
  full-suite workaround. Automated recursive cleanup was blocked by the host
  sandbox even after a path-specific permission grant.

## Unreleased - Skills And Cache Foundations V1

- Date: 2026-09-10
- Status: implemented-unverified
- Parent: Unreleased - Memory V1

### Architecture

- Added repository Skill artifacts plus a deterministic metadata matcher,
  section loader, and event-driven runtime. Matching occurs only for a new goal,
  a major subgoal change, or a recovery-mode change.
- Added phase-scoped planning, decision, and recovery guidance. Full Skill files
  are never inserted into each model request.
- Added a process-local retrieval candidate cache at the RetrievalPipeline
  boundary and extended the existing embedding cache instead of creating a
  parallel embedding subsystem.
- Added task-local authoritative read-fact freshness, purpose-specific TTLs,
  resource-tag invalidation, and forced verification refresh behavior.

### Behavior

- Constraint-aware recommendation guidance preserves candidate-specific hard
  constraints before preference ranking.
- Failure-diagnosis guidance covers bounded read recovery, retrieval rewrite,
  validation failure, duplicate actions, and uncertain mutation verification.
- Mutation responses no longer create live facts. Successful or uncertain
  mutations invalidate related read facts; uncertain mutations remain unsafe to
  retry directly.
- DeepSeek/provider prompt-cache token fields are observed when present. No
  prompt or model response cache is simulated by PolicyPilot.

### Compatibility

- tau2 Orchestrator, external Environment tool execution, ToolMessage return,
  and Evaluator ownership are unchanged.
- All features have compact PolicyPilotConfig switches. Retrieval and embedding
  caches use in-process backends and add no Redis dependency.
- Retrieval cache values contain candidate document IDs, scores, versions, and
  timing only. Postprocessing/reranking still runs outside the cached value.
- No hidden task criteria, required_documents, task-specific branch, benchmark
  answer, or new Agent framework was added.

### Verification Evidence

- Tests executed: no.
- Static/import/compile checks executed: no.
- Benchmark tasks and smoke evaluation executed: no.
- Reason: the task explicitly required implementation to stop before all forms
  of validation.

### Known Issues And Next Decision

- Runtime and migration behavior remain intentionally unverified.
- Embedding document indexing is created by the environment before the Agent is
  constructed, so an Agent-level cache switch governs query embeddings but
  cannot retroactively disable document vectors already loaded by that
  environment instance.
- Prompt-cache observations depend on the provider and LiteLLM exposing usage
  fields; absent fields are reported as unavailable rather than simulated hits.
- Run focused tests and evaluation only in a later, explicitly requested
  verification task.

## Unreleased - Memory V1

- Date: 2026-09-08
- Status: verified (unit/static only; benchmark pending)
- Parent: Unreleased Need-Driven Core Architecture

### Architecture

- Added external User Profile Memory and Episodic Memory without adding fields
  to PolicyPilotState.
- Added privacy-gated profile extraction, deterministic merge, hashed
  user-scoped JSON persistence, privacy-bounded episode formation, lexical
  episode retrieval, and bounded non-authoritative context rendering.
- Added explicit and observation-derived user binding. Anonymous tasks never
  access shared memory.
- Added memory metrics to existing PolicyPilot assistant metadata.

### Behavior And Compatibility

- Stable explicit preferences may assist later Planner/Decision context.
- Memory never resolves Facts or InformationNeeds and cannot replace Tool/Policy
  evidence for current banking state.
- tau2 Orchestrator, Environment, Tool execution, and Evaluator behavior are
  unchanged.
- No new dependency, model provider, Agent framework, benchmark-specific rule,
  or hidden evaluator access was added.

### Verification Evidence

- Unit tests added for profile privacy gate, merge/supersession, hashed
  persistence, episode privacy/retrieval, cross-task loading, context separation,
  Planner hint isolation, and Agent integration.
- PolicyPilot test suite: 33 passed in 0.23 seconds.
- Memory-scoped Ruff: all checks passed.
- PolicyPilot E9/F static check: all checks passed.
- PolicyPilot import and compile checks: passed.
- Warnings: Python audioop deprecation and an unavailable pytest-asyncio config
  option; neither caused a test failure.
- Benchmark/task/smoke evaluation: intentionally not run for this change.

### Known Issues And Next Decision

- A trusted user binding is required; anonymous sessions intentionally receive no
  long-term memory.
- The file store uses atomic replacement and in-process locking. A future
  deployment with multiple writer processes should provide a transactional store
  through the same interface.

## Unreleased - Need-Driven Core Architecture

- Date: 2026-09-07
- Status: implemented-unverified
- Parent: PolicyPilot V1 Requirement Modeling + Retrieval Planning
- Version decision: assign a release number after regression and benchmark
  validation.

### Architecture

- Replaced parallel persistent requirement, retrieval-coverage, retrieval-gap,
  and open-question objects with one canonical semantic state.
- Persistent state now centers on structured goal, intent, namespaced facts,
  unified information_needs, evidence, tool_history, and operational control.
- Added a SemanticPlan delta contract, deterministic LIGHT_PLACEHOLDER route,
  planner merger, NeedResolver, and capability-based SourceResolver.
- Added need-driven USER, POLICY, TOOL, and UNKNOWN graph branches.
- Decision LLM is entered only when no critical information need remains open.
- Tool execution remains outside LangGraph through tau2-compatible ToolCall
  messages and next-invocation observations.
- Added a placeholder PolicyEngine interface without implementing that engine.

### Retrieval And Context

- Policy retrieval is triggered by a POLICY information need.
- Queries preserve target, candidate, missing aspect, query terms, and hard
  constraints before optional semantic expansion.
- Retrieval evidence becomes authoritative, evidence-linked policy facts; a
  search call alone does not count as coverage.
- Decision context contains structured goal, intent, relevant facts, open needs,
  relevant evidence, and compact control status.

### Compatibility

- tau2 orchestrator, environment execution, and evaluator ownership are
  unchanged.
- Evaluation metadata still projects current_goal, known_facts, and
  open_questions for existing readers; they are no longer persistent models.
- No model provider or dependency was added.
- No benchmark answer, hidden criterion, required document, product name, or
  task-specific branch was added.

### Verification Evidence

- Test code updated for semantic goal merge, corrections, raw tool parsing,
  strict need resolution, source routing, query anchoring, readiness, compact
  context, and tool guards.
- Tests executed: no.
- Static/import checks executed: no.
- Benchmark tasks executed: no.
- Smoke evaluation executed: no.
- Reason: implementation was explicitly requested to stop before validation.

### Known Issues And Next Decision

- Runtime correctness, migration compatibility, and benchmark behavior remain
  unverified.
- Before assigning a release number, run the full suite, focused architecture
  tests, task_001, task_010, and the current V1 smoke evaluation.
- Record metrics here or link immutable result artifacts from this entry.

## Unreleased - Local Policy Chunking V1

- Date: 2026-09-22
- Status: verified (offline chunking and retrieval regression)
- Parent: PolicyPilot V1 local vector retrieval preparation

### Architecture

- Added deterministic, Markdown-aware policy document chunking with stable IDs,
  source lineage, heading-path metadata, hashes, and bounded overlap.
- Added an offline CLI that exports retrieval-ready JSONL plus a build manifest.
- The derived local vector-index directory is excluded from Git.

### Behavior And Compatibility

- Existing KnowledgeBase loading, BM25/dense retrieval, tau2/tau3 execution, and
  evaluator behavior are unchanged.
- No embedding API is called by the chunking step. The output is preparation for
  a later local Qwen embedding/indexing step.

### Verification Evidence

- Chunking unit tests: 5 passed.
- Existing banking retrieval system tests: 142 passed.
- Ruff and Python compile checks: passed.
- Generated 1,029 unique chunks from all 698 source documents.
- Chunk character distribution: minimum 262, median 887, maximum 1,426;
  zero empty chunks, zero chunks above the 1,600-character hard limit, and
  zero chunks ending with an orphan Markdown heading.
- Embedding generation and benchmark evaluation were intentionally not run.

### Known Issues And Next Decision

- The runtime still retrieves whole source documents until the chunk index is
  explicitly integrated.
- Next step: embed `chunks.jsonl` with the local Qwen embedding model and add a
  chunk-to-source aggregation policy before enabling it in evaluation.

## Unreleased - Local Qwen Policy Embeddings V1

- Date: 2026-09-22
- Status: verified (local full-index generation)
- Parent: Unreleased - Local Policy Chunking V1

### Architecture

- Added a resumable Ollama embedding pipeline backed by NumPy memmap storage.
- Document embedding input contains the source title, compact section paths,
  and chunk text; full metadata is not injected into model input.
- Added row-aligned chunk metadata and content/file hashes for reproducibility.

### Behavior And Compatibility

- Uses local `qwen3-embedding:0.6b` through Ollama's `/api/embed` endpoint.
- Existing retrieval and Agent runtime remain unchanged until this index is
  explicitly wired into a retrieval variant.
- No paid API is called.

### Verification Evidence

- Local endpoint probe returned 1,024 dimensions.
- Vectorization tests: 2 passed; chunking and vectorization combined: 7 passed.
- Ruff and Python compile checks: passed.
- Embedded all 1,029 chunks as a 1,029 x 1,024 float32 matrix in 58.693
  seconds using 225,370 model input tokens.
- Final vector file size: 4,214,912 bytes; metadata size: 510,854 bytes.
- Independent verification confirmed finite values, unique row alignment, and
  matching chunk IDs. Vector norms ranged from 0.9999993 to 1.0000007.
- Basic semantic probes retrieved relevant policy documents at rank one for
  personal savings opening requirements and no-annual-fee card handling.
- No benchmark evaluation or paid API was used.

### Known Issues And Next Decision

- A runtime query embedder, hybrid lexical/vector fusion, and chunk-to-document
  result aggregation policy are still required before this index can serve
  PolicyPilot retrieval. Pure dense Top-K showed occasional semantically close
  but operationally imprecise candidates.

## Unreleased - Local Hybrid Retrieval V1

- Date: 2026-09-22
- Status: verified (unit, regression, and real local-index retrieval)
- Parent: Unreleased - Local Qwen Policy Embeddings V1

### Architecture

- Added a two-stage constraint-preserving query path: PolicyPilot's existing
  Need-derived query skeleton followed by provider-specific sparse/dense forms.
- Added chunk-level BM25 and local Qwen dense candidate retrieval, reciprocal
  rank signals, feature reranking, and chunk-to-source-document aggregation.
- Added a `local_hybrid` retrieval variant that exposes the existing
  `KB_search` tool contract, so PolicyPilot Evidence and Need handling remain
  unchanged.
- Added a standalone local-search CLI for retrieval diagnosis without running a
  benchmark task.

### Behavior And Compatibility

- Query rewrite retains original text, negated/comparative phrases, numbers,
  and significant anchor terms.
- Reranking combines dense similarity, normalized BM25, anchor coverage, title
  coverage, exact-phrase coverage, and reciprocal-rank evidence.
- Existing BM25 and cloud embedding variants remain available. Evaluation
  scripts accept `--retrieval-config`; their default is now `local_hybrid`.
- tau2/tau3 orchestration, tool execution boundaries, PolicyPilot state, and
  evaluator behavior are unchanged.

### Verification Evidence

- Hybrid/chunk/vector unit tests plus existing retrieval regression: 153 passed.
- Ruff and Python compile checks: passed.
- Real 1,029-chunk index queries verified constraint-preserving rewrite, local
  query embedding, BM25+dense candidate fusion, reranking, source aggregation,
  and compatibility with the tau2 `KB_search` tool output contract.
- Personal-card scope conflict was detected during verification and fixed with
  a generic mutually-exclusive-scope penalty. The corrected personal card query
  ranked a personal card first instead of a business card.
- A debit-card PIN fraud/unlock query ranked the dedicated internal PIN Lock
  Investigation Protocol first after title coverage and aggregation tuning.
- Warm local query latency was approximately 0.38-0.43 seconds; dense query
  embedding dominated latency, while sparse retrieval and reranking each took
  roughly 1-3 milliseconds.
- No benchmark task or paid API was run.

### Known Issues And Next Decision

- The reranker is a deterministic feature reranker, not a cross-encoder model.
- Benchmark evaluation is required before comparing task reward, retrieval
  count, latency, or cost against the BM25 baseline.

## Unreleased - Local Qwen Reranker V1

- Date: 2026-09-23
- Status: implemented and locally evaluated
- Parent: Unreleased - Local Hybrid Retrieval V1

### Architecture

- Added a lazy-loaded `Qwen3-Reranker-0.6B` adapter using the official
  yes/no next-token relevance probability.
- The local hybrid retriever now reranks its first 20 chunk candidates and
  combines model relevance (35%) with the existing retrieval feature score
  (65%) before document aggregation.
- Added deterministic retrieval metrics and an offline evaluation script that
  keeps benchmark `required_documents` strictly evaluator-only.

### Behavior And Compatibility

- The model loads only when reranking is requested; unit tests use a fake
  reranker and do not allocate GPU memory.
- Default inference uses batch size 2 and a 1,536-token limit. Batch size 8 at
  2,048 tokens exceeded the RTX 3070 Laptop GPU's 8 GB memory on long task
  scenarios.
- `local_hybrid` retains the existing `KB_search` tool contract. No tau2/tau3
  orchestration or evaluator semantics changed.

### Verification Evidence

- Deterministic reranker and metric unit tests: 7 passed; Ruff passed.
- Final PolicyPilot tests: 105 passed. Final banking knowledge tests: 498
  passed and 85 skipped. The registry table now includes `local_hybrid` and
  the pre-existing `alltools-qwen` test cases.
- Local evaluation report:
  `data/analyses/retrieval_quality_20260923_145751.json`.
- Evaluation used seed 0, 10 sampled required-document titles, the same 10
  documents' first 20 content words, and 10 sampled task scenarios: 30 queries
  total. Corpus labels came from 218 unique required documents across 97 task
  files; labels were read only after retrieval.
- Feature-only Recall@5 was 1.000 for title and content queries and 0.1606
  macro / 0.1058 micro for task scenarios. Conservative Qwen fusion retained
  1.000 title/content Recall@5 and produced 0.1587 macro / 0.1058 micro task
  Recall@5.
- Task-scenario mean latency increased from 0.704 seconds to 6.368 seconds;
  Qwen model reranking accounted for 5.560 seconds on average.
- An earlier 90% model-weight experiment degraded title Recall@5 to 0.900 and
  task HitRate@5 from 1.000 to 0.600, so that weight was rejected.
- All inference was local; no paid API and no Agent benchmark run was used.

### Known Issues And Next Decision

- Raw task scenarios are long simulator scripts rather than the concise
  Need-derived queries used by PolicyPilot, so task-scenario retrieval is a
  stress proxy and not an Agent reward estimate.
- This small deterministic sample shows no task-level Recall@5 gain and a large
  latency cost. Before making reranking mandatory in broad evaluations, test
  recorded real retrieval queries and consider reducing rerank candidate count
  or enabling reranking only for ambiguous candidate sets.

## Unreleased - Retrieval Mode Comparison

- Date: 2026-09-23
- Status: offline evaluation complete
- Parent: Unreleased - Local Qwen Reranker V1

### Architecture

- Added an evaluator-only comparison of BM25 keyword retrieval, local Qwen
  dense retrieval, and the existing feature-hybrid retrieval.
- All modes share the same queries, chunk index, candidate limit, document
  deduplication, Top-5 cutoff, and evaluator-only gold labels. Model reranking
  is disabled for all three modes.

### Verification Evidence

- Report: `data/analyses/retrieval_modes_20260923_154028.json`.
- Sample: seed 0; 10 document titles, 10 first-20-word content snippets, and
  10 task scenarios; 104 task-scenario gold references in total.
- Task-scenario Macro Recall@5: BM25 0.0143, dense 0.2800, hybrid 0.1606.
- Task-scenario Micro Recall@5: BM25 0.0096 (1/104), dense 0.1923
  (20/104), hybrid 0.1058 (11/104).
- Task-scenario HitRate@5: BM25 0.10, dense 1.00, hybrid 1.00.
- Task-scenario mean latency: BM25 475.5 ms, dense 2,414.9 ms, hybrid
  2,911.9 ms. Long task text makes BM25 query scoring much slower than its
  6-14 ms title/snippet latency.
- Title/content Recall@5 was 1.00/1.00 for BM25, 1.00/0.90 for dense, and
  1.00/1.00 for hybrid.

### Known Issues And Next Decision

- Raw task scenarios contain simulator instructions and are not the concise
  Need-derived queries used by the running Agent. They are useful as a stress
  comparison but do not estimate end-to-end task reward.
- Dense retrieval preserved task-scenario semantic relevance better than the
  current hybrid feature reranker. Evaluate recorded real Agent queries before
  retuning hybrid weights; anchor and lexical coverage should not dominate on
  long, instruction-heavy queries.

## Superseded - Jev Acquisition Planning Prototype

- Date: 2026-09-27
- Status: superseded before benchmark execution
- Parent: current PolicyPilot Need-routing baseline

### Architecture

- Made semantic Need identity independent of evidence source and represented
  policy, live-tool, and user acquisitions as bounded child plans.
- Added an optional Jev System One adapter for semantic source ambiguity. Hard
  capability validation, required tool arguments, lifecycle transitions, and
  tool execution remain deterministic and local.
- Jev receives only canonical Need fields, hard-criterion field names,
  available fact field names, and eligible read-tool descriptions. User
  messages, fact values, account identifiers, and hard-criterion values are
  excluded from its request state.

### Behavior

- One semantic Need can require multiple authoritative acquisitions, such as a
  policy rule followed by current account state, without creating duplicate
  Needs.
- Jev is called only for bounded semantic-planner candidates. Deterministic
  candidates bypass it, and missing credentials, errors, or low-confidence
  answers fall back to the planner's existing source hint.
- Jev may select only read capabilities whose required arguments are already
  available and locally schema-valid. It cannot call tools or authorize writes.

### Compatibility

- tau2/tau3 orchestration, environment tool execution, evaluator behavior, and
  the public `KB_search` contract are unchanged.
- Legacy source-prefixed checkpoint keys remain structurally matchable during
  guard recovery.
- At this checkpoint Laya was not retained. The following version replaces
  this cloud adapter with a local Laya runtime.

### Verification Evidence

- Acquisition unit tests cover multi-source compilation, sequential
  completion, cloud-payload redaction, HTTP endpoint/auth construction,
  no-key fallback, and source-free Need merging.
- Final PolicyPilot regression: 143 passed, with two pre-existing warnings
  (`audioop` deprecation and an unknown asyncio pytest option). Ruff also
  passed for the Jev acquisition and lifecycle changes.
- No live Jev request, paid API call, or benchmark task was run because no
  TypeSafe API key was configured.

### Known Issues And Next Decision

- This prototype was superseded because Jev requires paid, early-access cloud
  credentials that were not immediately available to the project.
- Thresholds are configuration defaults, not benchmark-tuned constants. Keep
  deterministic fallback telemetry and compare route accuracy before changing
  them.

## Unreleased - Local Laya Acquisition Routing V1

- Date: 2026-09-27
- Status: local runtime integrated; unit and local smoke verification complete
- Parent: Superseded - Jev Acquisition Planning Prototype

### Architecture

- Replaced the TypeSafe/Jev cloud adapter with `laya==0.3.20` running directly
  inside the PolicyPilot Python process. No API key, HTTP service, or background
  model process is required.
- Uses `convaiinnovations/laya` on CUDA when configured, loads lazily, and keeps
  one model resident for subsequent routing calls. Model files are cached under
  `.cache/huggingface`, which is ignored by Git.
- Laya chooses one bounded acquisition plan: policy, tool, user, or a supported
  two-source combination. It separately chooses from locally enumerated read
  capabilities; deterministic code still validates tool type, arguments, and
  schema before creating an acquisition.

### Behavior

- Only semantic-planner candidates are sent to Laya. Deterministic candidates
  bypass it, and at most three semantic candidates are reviewed per turn.
- A Laya plan must reach 0.75 confidence, and a selected tool must independently
  reach 0.75 confidence. Otherwise the existing planner hint is retained.
- Tool choice is capped at nine read tools plus `NONE`. This remains below the
  checkpoint's warned 11-plus-choice calibration range and keeps the compact
  request close to its 512-token input budget.
- User messages and fact values are excluded; Laya receives canonical Need
  fields, available fact field names, hard-criterion field names, and bounded
  tool descriptions.

### Compatibility

- tau2/tau3 orchestration, environment execution, evaluator behavior, main-LLM
  tool permissions, and the `KB_search` contract are unchanged.
- Loading or inference failure is recorded and falls back without blocking the
  outer Agent turn.
- The Laya dependency is an optional `laya` project extra and is pinned to
  `0.3.20`; the current virtual environment has that package installed.

### Verification Evidence

- Hardware detected: NVIDIA GeForce RTX 3070 Laptop GPU, 8 GB VRAM; CUDA was
  available through Torch 2.14.0+cu126.
- First model download and load took 164.817 seconds; the first measured
  inference took 797.828 ms. After caching, three sequential decision calls in
  one process took 487.37 ms total.
- A real local CUDA pytest smoke passed with zero output tokens and no API key.
- Unit coverage includes multi-source compilation, sequential completion,
  redaction, lazy single-load behavior, low-confidence fallback, no-backend
  fallback, and source-free Need merging.
- Final PolicyPilot regression: 144 passed and one opt-in local-model test was
  skipped; the explicit local-model smoke passed separately. Ruff passed.

### Known Issues And Next Decision

- Offline evaluation report:
  `data/analyses/laya_need_routing_20260927_152242.json`.
- Source-plan evaluation used all 267 Gold Needs from 67 tasks. Only the Need
  description was model-visible; ids, completion conditions, and labels were
  withheld. Raw exact accuracy was 1.12%, source macro-F1 was 0.3952, and no
  task had every Need routed correctly. The model predicted
  `POLICY_AND_TOOL` for 264/267 examples and never predicted a USER source.
- At the 0.75 gate, plan coverage was 4.12% (11/267) and selective accuracy was
  0%. ECE was 0.5542. The current acquisition-plan formulation must not be
  treated as authoritative or have its threshold lowered.
- In a separate bounded capability proxy, each of 171 transaction-tool Needs
  received its Gold capability plus deterministic distractors, capped at nine.
  Overall Hit@1 was 75.44%; the 106 read/verification Needs reached 73.58%
  Hit@1 and 81.36% selective accuracy at 55.66% coverage. Mean capability
  latency was 29.11 ms on CUDA.
- The capability proxy uses semantic capability families, not the actual
  runtime-ready tool set and arguments. Its positive result supports testing
  Laya as a reranker after deterministic candidate generation, not as the
  authority that decides POLICY/TOOL/USER source.

## Entry Template

Each future entry must use these sections:

- Heading: version/checkpoint and short name.
- Metadata: date, status, parent.
- Architecture.
- Behavior.
- Compatibility.
- Verification Evidence, including commands, tests, task metrics, and artifacts.
- Known Issues And Next Decision.
