# Decision Prompt GEPA Pilot

This page describes the historical V1 pilot. The CLI now defaults to the draft
[Decision Dataset V2](DECISION_DATASET_V2.md); inspect it without model calls.
Use explicit `--data data/policypilot/evaluation/decision_gepa_v1` to reproduce
the older commands below. Do not rebuild or relabel already-used V1 test data
as a fresh hold-out set.

Actual installation and partial paid-run results:
[2026-10-23 pilot report](experiments/GEPA_PILOT_20261023.md).
The subsequent non-thinking run completed:
[non-thinking results](experiments/GEPA_NONTHINKING_20261023.md).

## Scope

Optimize only `DECISION_INSTRUCTIONS`, not the Agent graph, lightweight models,
retrieval, tools, memory, safety guards, user simulator or hidden evaluator.
Each evaluation is exactly one model input and its next assistant output.
Tool calls are evaluated as proposals; no business tool is executed. This is
offline component evaluation, not an end-to-end task success measurement.

GEPA evolves prompts, not model weights. The adapter follows the official
[`optimize_anything` evaluator contract](https://gepa-ai.github.io/gepa/api/optimize_anything/optimize_anything/):
`(candidate, example) -> (score, feedback)`. The optional dependency is pinned
to GEPA 0.1.4. This release uses GEPAConfig/EngineConfig/ReflectionConfig, not
the newer OptimizeAnythingConfig shown in the latest online documentation.

## Dataset

Files: `data/policypilot/evaluation/decision_gepa_v1/`.

- 40 synthetic examples across 10 policy-document/scenario families.
- Train 24 / validation 8 / held-out test 8; 33 answers and 7 tool proposals.
- Train: checking opening, savings opening, checking closure, transfers,
  checking credits, bank transaction history.
- Validation: card freeze/unfreeze and PIN procedures.
- Test: debit-card closure and card lookup.
- Policy text comes from 10 visible KB documents. User messages, verified-state
  fixtures and answer rubrics are agent-authored, not actual recorded dialogues,
  human-approved labels or benchmark task answers. No tasks.json,
  required_documents or hidden task criteria are read by the builder.
- Uses the real `build_agent_context`, current seed instructions, and seven
  real banking tool schemas. It uses a minimal fixture domain policy rather
  than the full runtime domain policy and a fixed tool subset. This intentionally
  isolates a pilot, but limits transfer claims.
- Tool observations are explicit synthetic assumptions; no database is queried.
  The full cited policy is retained in a simulated KB tool response.
- Same document/family never crosses splits. JSONL contains `input.messages`,
  `input.tools`, evaluator-only `expected` (output kind, tool/args, semantic
  rubric), IDs and provenance hashes. There is no exact-string answer target.
  Only `input` is sent to the target LLM, never `expected`.
- `scenarios.json` is the editable source; `seed_prompt.txt`, JSONL and manifest
  are reproducibly generated. Counts and hashes are in `manifest.json`.

This small, unreviewed set is suitable for testing the optimization pipeline,
not evidence of production improvement. It underrepresents retrieval-gap
envelopes, context loading, multi-entity corrections and recovery. Before making
claims, review labels and extend with frozen real Decision input snapshots,
not reconstructed full histories containing future observations. Keep entire
original tasks and their variants in a single split. Do not replace a historical
bad answer with an unreviewed automatic gold label.

## Scoring

1. Deterministic output contract: answer versus tool call, exact next-tool name,
   and verified fixture argument values. Wrong actions score zero; the judge is
   skipped. Different words in a valid answer are not rejected by keyword rules.
2. A semantic judge checks correctness, completeness and grounded safety against
   supplied inputs and an evaluator-only rubric. Each is a strict boolean, plus
   short diagnostic feedback for GEPA. Safety failure scores zero; otherwise the
   score is the mean of correctness and completeness (0, 0.5 or 1).
3. A tool proposal is not a completed operation. Correct execution proposals do
   not need a final customer answer. An unsupported success claim fails safety.
   All-reference refusals are not rewarded when action prerequisites are met.

Invalid judge JSON/schema, API failures and output truncation abort the run;
they are infrastructure/evaluation failures, not low-quality agent answers.
Using the same provider/model as target and judge is a practical starting point,
not independent ground truth. Human-audit representative passes and failures;
repeat final comparisons for uncertainty before reporting an improvement.

## Commands (PowerShell, Project Root)

Rebuild and inspect without model calls:

```powershell
& .\.venv\Scripts\python.exe scripts/build_decision_gepa_dataset.py
& .\.venv\Scripts\python.exe scripts/optimize_decision_prompt.py
```

The following commands are **paid API experiments**, not performed automatically.
They require the pinned optional dependency (`uv sync --extra prompt-optimization`).
The CLI fails before model calls if its GEPA import is unavailable.
It reuses `.env` credentials with no keys
printed and resolves `POLICYPILOT_MAIN_DECISION_MODEL` unless explicitly supplied.
Judge and reflection default to that same model; overrides are available.

```powershell
& .\.venv\Scripts\python.exe scripts/optimize_decision_prompt.py --mode optimize --max-evals 32
```

The DeepSeek target explicitly uses thinking mode, matching the current Decision
default. The judge uses non-thinking JSON output. The reflector follows its GEPA
provider through the same metered call function. Freeze these settings, input data and output budget
across baseline and candidate comparisons; thinking mode and prompt must not be
changed simultaneously. There is no automatic deployment of the best prompt.

For a non-thinking experiment use `--thinking disabled` on BOTH the optimize and
held-out test commands. This flag affects only the experiment's target and
reflection calls, not the production Decision runtime. Start a fresh run when
changing it; never compare candidates under different thinking settings.

After choosing exactly one candidate on validation, compare seed and candidate
on the held-out set (replace the path with the printed artifact path):

```powershell
& .\.venv\Scripts\python.exe scripts/optimize_decision_prompt.py --mode test --candidate "data/storage/decision-gepa/<run>/best_prompt.txt"
```

Test rows are rejected by the search evaluator and are never passed to GEPA.
When the selected prompt is identical to the seed, each test case is called only
once and the duplicate result is explicitly marked as reused, not an independent
trial. Test feedback must not be used to keep tuning and then advertised as held out.
For repeated development, reserve a new untouched test set.

Artifacts live in a new, ignored `data/storage/decision-gepa/<run>/` directory:
settings/data hashes, GEPA output/state, best prompt, target/judge call metrics,
or paired held-out scores and outputs. Existing output directories are refused.
Target/judge/reflection metrics all include token usage, latency, finish reason
and estimated cost (unknown prices remain null). Provider errors can incur costs
even when a response was not available to record. Provider billing is authoritative.
`max_evals` is an evaluation count, not a dollar cap: one evaluation may call both
target and judge, with additional reflection calls. Cost reductions and accuracy
gains must be reported from actual artifacts rather than assumed from the optimizer.
GEPA 0.1.4 checks this budget at batch/iteration boundaries: a requested 32
produced 34 evaluations in the pilot. Do not interpret it as a strict spending cap.

## Verification

### Judge Failure Handling

Before spending on another V2 prompt search, run the TRAIN-only calibration:

```powershell
.\.venv\Scripts\python.exe -B scripts/optimize_decision_prompt.py --mode calibrate --calibration-variants 2 --thinking disabled --allow-unreviewed-data
```

It checks eight TRAIN inputs under six conditions: original positive, planned
action, in-progress action, explicit non-execution, hypothetical outcome, and
unsupported completed-success claim (48 checks).
Without --calibration-variants 2 it uses four inputs (24 checks). No target-model
calls occur. A nonzero exit or calibration_failed status means do not launch
search. Passing these probes is only a smoke check, not proof of general Judge
accuracy or human approval. The four scenario templates and paraphrase conditions
are not independent real-world samples. Calibration is development data for the
Judge; repeated improvements on these probes do not establish held-out accuracy.
Keep its Judge settings identical to the planned search. The CLI offers this
as an explicit preflight; optimize does not automatically rerun calibration.
The first measured calibration matched only 5/8 expected scores and failed the gate; see the
[calibration report](experiments/GEPA_JUDGE_CALIBRATION_20261023.md).

The current evaluator removes candidate instructions before sending frozen
business context to Judge. Completion claims are reviewed by a separate narrow
call on assistant text and observations, with an exact quote required for a
nonempty claim (whitespace and CommonMark presentation differences are accepted,
not changed words or omitted negation). Explicit denials and
hypothetical outcomes are not affirmative completed-operation claims. Known
state descriptions still require ordinary business grounding, not proof that
the current assistant performed a mutation. This uses the SAME configured Judge model, not a second provider
or statistically independent ensemble. A confirmed completed outcome is allowed;
a planned/in-progress notice is not an unsupported success claim. Unsupported
completed outcomes veto the score even if the semantic Judge likes the tool.
Semantic review separately checks next-action correctness, completeness and
policy grounding. Queries are scored for semantic constraints, not literal words.
The additional completion review runs only for nonempty assistant text and adds
Judge cost/latency; its attempts are recorded with stage=completion, and ordinary
grading with stage=semantic. Private reasoning is not logged. Judge temperature
is zero; this reduces variation but does not guarantee deterministic inference.

GEPA reserves top-level side_info.scores for NUMERIC multi-objective values.
Our categorical Judge diagnostics are stored as judge_verdict in reflection
feedback instead; they remain scores in the local evaluation log for historical
compatibility. The optimizer uses the explicit primary scalar score, not string
classification metadata as additional objectives.

If a runner/SDK error occurs after a complete original validation, an explicit
--baseline-cache <run-directory> can reuse those seed rows. Reuse requires a
complete unique validation set and matching model, thinking, token allowance,
data/seed hashes, Judge/completion instruction hashes, scorer hash, Judge policy
and dependency versions. The cache is not used for candidates or training rows.
Reused baseline rows are marked reused_baseline=true and incur no new API calls;
their original usage remains in the source run and must not be counted twice.
This is frozen-score recovery, not an additional trial or renewed evidence of
stability. Only reuse trusted local artifacts, not externally supplied results.

Judge replies are now retained in `judge_attempts.jsonl` with example ID,
candidate hash, attempt number and raw response. An empty or whitespace-only
explanation is replaced with an explicit missing-explanation notice only when
the verdict still passes strict boolean/schema validation. The score is not
changed; `judge_missing_feedback=true` distinguishes the notice from a model
explanation. The original reply is preserved, not overwritten in the audit log.

Malformed JSON or invalid verdict fields permit one additional Judge call on
the identical frozen Agent output. Both Judge stages receive an explicit JSON
schema; retries also receive the previous invalid response and validation error,
not merely a repeated request at temperature zero. The Agent is not called again, and no invalid
verdict is assigned a numeric score. Retry calls use the same usage/cost logging
as initial calls; they may incur additional cost. Transport failures are not
silently retried by this policy.

After two invalid replies, `JudgeEvaluationError` stops the run with
`run_status.json` recording `status=evaluator_error`, the example/candidate and
`score=null`. Existing calls, evaluations and GEPA checkpoints remain available.
This is a recorded failed evaluation, not a zero-score Agent answer or a
completed optimization. Do not deploy intermediate candidates or silently omit
failed cases from aggregate comparisons. Historical runs remain unchanged.

Focused tests cover data integrity, disjoint splits, reproducibility without
executing tools, instruction-only replacement, action arguments, semantic score
aggregation, safety veto, invalid judge output, and held-out exclusion.
No real GEPA search, target-model inference or benchmark is implied by these tests.
