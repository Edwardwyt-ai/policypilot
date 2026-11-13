
# Skill evolution

SkillRuntime continues to route the repository Skills. Set
`POLICYPILOT_SKILL_LIBRARY` to the offline library database to include explicitly
promoted versions. Each Agent pins one release when it starts. Routing reacts to
goal and state changes, recovery and Planner requests. A typed trigger and
preconditions constrain evolved Skills. The runtime writes retrieval, activation
and version evidence to the existing trajectory metadata. Skill guidance is text.
The tool exposure policy, authorization checks and mutation guard remain owned
by the runtime. Evolved guidance includes runtime-owned safety constraints.

The workflow borrows evidence accumulation, behavior clusters and representative
sampling from [Cognitive Memory Manager](https://openreview.net/pdf?id=yCsHQnvvWY).

## Offline workflow

`scripts/skill_evolution.py` exposes the following commands. Use the existing
project Python environment. The default working directory for artifacts is
`data/storage/skill-evolution`, containing `experience.sqlite3` and
`library.sqlite3`. `--root` can select a separate directory.

1. **ingest** consumes a page from an Episode JSON array, an explicitly selected
   PostgreSQL user's Episodes, or saved `evaluate_v1` trajectories. Use
   `--task-type` with trajectories. Each source has a stable ID and a revision
   hash. A repeated source is skipped, and a changed source replaces its current
   extracted experience. On a stable input list, continue with `next_offset`.
   Start at zero again to detect earlier edits. The output also lists changed
   cluster IDs. Profile preferences do not enter this pipeline.
2. **discover** reports triggers for changed clusters supplied with repeatable
   `--cluster`, or a bounded cluster page with `--after-rowid`. Provide reviewed
   annotations with `ingest --reviews` to label Episode success, scenario groups,
   failure modes and attribution. A trajectory derives its outcome from the
   existing evaluator. Optional `--windows` takes earlier and recent outcome
   windows as JSON maps from Skill ID or task type to boolean arrays.
   `--review-cluster` adds a redundancy or retirement review signal for a
   cluster with evidence.
3. **propose** takes the same cluster and signal arguments. The optimizer receives
   a bounded sample of successful and failed experiences, relevant existing Skills,
   and optionally a bounded projection of referenced saved traces via
   `--trace-index`. It may choose CREATE, UPDATE, MERGE, RETIRE or NO_OP. CREATE
   needs repeated success across task IDs. Content repair needs evidence of a
   content defect, a successful extension, or an explicit redundancy review.
   Candidate versions and their evidence are kept separately from the active release.
4. **evaluate** consumes two existing benchmark run directories and a labeled
   evaluation plan. **promote** uses the same input, writes the computed report,
   and atomically updates the active release only when the report passes.
   **rollback** selects a previous release, including the built-in-only release.

The extraction and optimizer commands use the project's LLM runtime when invoked.
`ingest --dense` uses the local Ollama embedding adapter. Its default uses the
existing local hash embedder. The cluster search uses task-type filtering, prefers
matching behavior and failure mode, then compares behavior-step vectors within
a bounded shortlist. Online Skill ranking uses BM25 with optional dense fusion
via `POLICYPILOT_SKILL_DENSE=1`. No background optimizer or new service is needed.

## Evaluation contract

Use two separate invocations of the existing `evaluate_v1.py` runner with
`POLICYPILOT_SKILL_LIBRARY` set to the same absolute library path,
`POLICYPILOT_SKILL_EVAL=1`, and the same fixed `PYTHONHASHSEED`. The baseline
has no `POLICYPILOT_SKILL_EVAL_CANDIDATE`. Set it to the candidate ID in the
candidate arm. Both arms disable long-term Memory so that the trial runs do not
change each other's Memory input. Use a fixed benchmark task list and seed.

The plan supplies `configuration_id` (obtain with the `configuration-id`
command on a run directory), `builtin_ids`, and `trials`. Each trial specifies
`task_id`, `seed`, expected activated IDs in both arms and optionally the
expected ordered tool sequence. An explicit empty tool sequence expects zero
successful tool calls. Scenario groups are required in evaluation when
source evidence declares groups. CREATE also requires a reviewed
`reviewed_non_redundant` label, a positive case and a negative activation case.
The evaluator checks release IDs, config hashes, task and seed coverage, trace
reuse, extraction-task overlap, selection, execution, success and resource
deltas. Task metrics come from PolicyPilot's existing benchmark adapter.
The failure attribution helper uses expected retrieval, activation and
execution labels. Skill content defects require reviewed evidence.

Execution checks use tool sequences with non-error tool responses, so
procedure quality beyond those checks needs additional evaluator labels.
Local tests exercise contracts with synthetic records. Actual discovery quality,
runtime gains and promotion thresholds need held-out trials.
