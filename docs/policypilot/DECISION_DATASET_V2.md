# Decision Dataset V2

## What Changed

V1's eight validation questions were too easy and did not cover the known-ID
failure seen in training. V2 tests the same capabilities in every split, while
holding out complete business scenario templates. It is a component dataset for
one Decision input and its next output, not an end-to-end banking benchmark.

**Status: generated draft, not human-reviewed and not empirically calibrated.**
No V2 target/Judge API calls or GEPA search have been run. Greater structural
coverage does not itself prove the examples are hard or the labels correct.

## Composition

- 96 rows: train 32 / validation 32 / test 32.
- 24 independent scenario templates, eight per split.
- Each template has a two-branch counterfactual pair, exercised under two
  different entity-ID and fact/tool-order variants: 48 pairs overall.
- Thus 96 rows are NOT 96 independent business scenarios. Variants and both
  contrast branches stay in the same scenario group and split.
- Every split has four rows for each of the eight capabilities below.
- 68 next-tool proposals, 26 answers, two missing-information envelopes.
  Tool proposals include read-only verification and context loading, not just
  mutations. Business tools are never executed by this evaluation.

| Capability | Train scenario | Validation scenario | Test scenario |
| --- | --- | --- | --- |
| Known-value reuse | Refund account ID present vs genuinely unbound | Transfer destination bound vs lookup needed | Known card ID vs card lookup needed |
| Entity binding | Two savings destinations | Two checking accounts with different refund amounts | Two active debit cards |
| Authority/freshness | Historical memory vs current balance | Historical vs current card status | User-claimed vs verified fee discrepancy |
| Authorization | Transfer feasibility vs execution consent | Freeze feasibility vs execution consent | Refund feasibility vs execution consent |
| Policy boundaries/exceptions | Young stolen card vs ordinary cancellation | Entry-tier fee-window boundary | Premium-tier fee-window boundary |
| Information acquisition | Missing fee policy: KB available vs unavailable | Relevant vs off-scope refund evidence | Archived vs visible issue date |
| Mutation verification | Uncertain transfer vs confirmed posting | Uncertain freeze vs confirmed frozen state | Uncertain credit vs confirmed posting |
| Multi-turn revision | Revised transfer amount vs cancellation | Corrected verified refund total | Temporary freeze vs permanent stolen-card closure |

A contrast changes one decision-bearing condition, which may have several
derived JSON manifestations (for example, an unbound account has no ID or
entity-bound fields). This is not a claim that every pair differs by one literal
JSON field. Some pairs change the action; others change a required numeric or
temporal conclusion while retaining answer mode.

## Evidence and Source Honesty

`source_findings.json` records which real observations motivated the mechanisms.
The V1 GEPA known-ID failure is directly observable. Historical repeated-ID
requests and recommendations followed by missing fee evidence are transcript
symptoms: the inspected files did not preserve exact Decision requests, so they
do not prove whether the underlying fault was Decision, context or upstream
state/retrieval. No historical task is assigned a Decision-failure label merely
because its final reward was zero.

**Zero exact historical request snapshots were imported.** All V2 contexts are
explicit synthetic fixtures, not reconstructed histories passed off as original
LLM requests. Bank rules and observed policy excerpts come from visible KB
documents; partial excerpts are checked as verbatim substrings. IDs are synthetic
and scenario-specific. Hidden task criteria/required_documents are not read by
the builder or passed to the model.

Uses actual build_agent_context, existing FactRecord source/authority semantics,
real business/KB/context-tool schemas, and the current seed instructions. User
claims are not silently converted to verified tool facts. Confirmed mutation
outcomes are ToolMessages, not authoritative statements placed in memory.
Intent is not set from the gold output kind. The domain policy is a minimal
fixture and the tool set a fixed realistic subset, not an exact runtime replay.

## Split and Leakage Contract

The held-out unit is the full scenario group, not an individual paraphrase or
entity variant. Pair members never cross splits, and template groups do not
overlap. Scenario-specific IDs are not reused across groups. No V1 input is
copied into V2. V1 data, labels, test outcomes and experiment reports remain
unchanged; its already-used test set is not relabeled as unseen data.

**Policy documents may be shared across splits.** This deliberately fixes V1's
capability mismatch, but means V2 measures new-scenario use of known policies,
not generalization to unseen policies or products. Do not describe it as
document-disjoint or unseen-domain evaluation.

Target LLM receives only messages and tool schemas. Requirements for grading,
contrast labels, provenance, reference outputs and incorrect foils stay outside
that input. Input hashes and per-split hashes freeze labels as well as inputs.
Do not cherry-pick test cases after seeing target outputs.

## Output Labels and Judge Calibration

Each row labels the desired next action and a semantic rubric, not one mandatory
answer string. Exact argument matching is used for verified identifiers and
amounts. A retrieval query may be rewritten semantically: its schema is checked
deterministically and requirement preservation is judged semantically. Legitimate
context pagination values are schema-checked instead of demanding one page size.
Missing-information output must parse through the actual runtime protocol.

`judge_probes.jsonl` contains a reference positive, the opposite branch's output
as a negative, and (for tool proposals) a correct call accompanied by an
unsupported success claim. These are author-specified calibration labels, not
observed Judge scores. Some negatives are structurally valid and intentionally
need semantic assessment; offline schema tests cannot prove Judge reliability.

Before the next optimization:

1. Review all 24 underlying templates: input sufficiency, source/authority,
   business-rule correctness, whether an equally valid alternative action exists,
   and whether the contrast truly changes the required decision. Correct labels
   from evidence, not from a desire to make the baseline fail.
2. Use TRAIN probes to calibrate/audit the Judge. Measure correct-output pass rate
   and incorrect-output false acceptance, particularly premature-success claims.
   Do not tune the Judge using test probes. Same-model judging remains a potential
   bias; this dataset redesign does not resolve it by itself.
3. Run a small seed-only train/validation pilot to measure difficulty and locate
   ambiguous labels. This has NOT been done. If all cases still saturate, collect
   additional authentic frozen Decision failures rather than automatically making
   the Judge harsher or editing held-out labels.
4. Freeze the dataset/Judge/model/thinking settings. Predeclare tie-breaking and
   safety regression rules before optimization. Evaluate the test set only after
   candidate selection, and never use its feedback for more tuning while still
   claiming an untouched test set.

For future reporting, include macro score by capability and strict pair success
(both branches pass), not just overall mean. Aggregate at scenario-group level
when discussing sample size; ID/order variants are correlated. GEPA's current
reflection sampler still samples individual rows, not atomic pairs; do not claim
a pair-aware optimizer was implemented here. Full validation contains both
branches regardless of the reflection minibatch sampler.

## Files and Commands

Data: `data/policypilot/evaluation/decision_gepa_v2/`:
train.jsonl, validation.jsonl, test.jsonl, manifest.json, seed_prompt.txt,
judge_probes.jsonl, source_findings.json.

The experiment CLI now defaults to V2 inspection. Paid modes refuse the draft
before any model call unless `--allow-unreviewed-data` is explicitly supplied;
that override permits a pilot, not a claim that the labels have been reviewed.
V1 remains readable via explicit `--data data/policypilot/evaluation/decision_gepa_v1`.

```powershell
& .\.venv\Scripts\python.exe scripts/optimize_decision_prompt.py
```

Builder refuses to overwrite existing data. `--refresh-draft` can regenerate an
existing V2 draft only while its manifest is draft_unreviewed, without deleting
unrelated files. Human-reviewed/frozen datasets should receive a new version.
Manual edits to generated labels must be reflected in a newly reviewed source
version and hashes; otherwise the loader rejects changed frozen splits.

The JSON Schema validator is explicitly declared in the prompt-optimization
extra; the already-installed jsonschema 4.25.1 was used, with no package install
or SDK upgrade. Production Agent/runtime/evaluator behavior was not changed.

## Offline Verification

41 focused assertions passed, with two existing environment warnings. Checks
cover group/pair isolation, equal capability coverage, no exact V1 input reuse,
native schema/protocol compatibility, deterministic construction without tool
execution, label/probe hashes, flexible argument handling and the pre-call draft
guard. Ruff/format, pip check and offline lock check passed. Builder and pytest
processes remained alive after successful summaries and were interrupted; clean
interpreter shutdown was not verified. These checks do not establish semantic
gold validity, Judge calibration, baseline accuracy or an optimization gain.
