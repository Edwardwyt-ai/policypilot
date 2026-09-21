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

## Entry Template

Each future entry must use these sections:

- Heading: version/checkpoint and short name.
- Metadata: date, status, parent.
- Architecture.
- Behavior.
- Compatibility.
- Verification Evidence, including commands, tests, task metrics, and artifacts.
- Known Issues And Next Decision.
