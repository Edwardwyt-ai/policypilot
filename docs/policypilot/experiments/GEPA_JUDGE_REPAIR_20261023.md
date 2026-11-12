# Judge Repair and Follow-up Runs - 2026-10-23

## Current Status

The evaluator and runner repairs pass 73 focused tests. The latest paid TRAIN
calibration passed 48/48, followed by 48/48 offline replay after the final
CommonMark quote-normalization fix. Four previously rejected quote responses
also pass offline validation without new provider calls.

**GEPA optimization has NOT completed.** The final attempt, run7, ended during
the fourth target request because the remote peer disconnected before returning
an HTTP response. LiteLLM surfaced InternalServerError; httpcore's underlying
error was RemoteProtocolError. The available trace does not identify whether
the service, a proxy or the connection caused the disconnect. No automatic
transport retry or further paid run followed it. Three completed seed scores
are insufficient for a validation mean or candidate-quality conclusion.

No production prompt was replaced, no bank tools executed, no held-out test used,
and no Git commit or push created. Reward, DB Check and Required Actions were
not measured. There is no newly selected best_prompt.txt.

## Implemented Changes

- Judge sees frozen business context and output, not the optimized candidate's
  instruction block. This prevents candidate instructions from being mistaken
  for facts or influencing their own grading.
- Semantic grading explicitly checks query meaning and constraints, not exact
  wording, and evaluates the NEXT action rather than a complete future task.
- An additional narrow completion-review call checks user-visible text against
  existing observations. It uses the SAME configured model, not an independent
  model ensemble. Correct tool arguments do not excuse unsupported success.
- Completion review distinguishes affirmative finished outcomes, plans or
  in-progress notices, explicit non-execution, and no completion assertion.
  Conditional/hypothetical outcomes and policy descriptions are not affirmative
  claims of executed operations. Ordinary business grounding remains required.
- Both Judge stages receive their actual JSON schema. One bounded retry includes
  the previous response and validation error; it no longer resends an identical
  request at temperature zero. Predictions stay frozen, and invalid evaluations
  are never converted into Agent zeros.
- Quote validation accepts whitespace and visible CommonMark formatting while
  retaining words and negation. markdown-it-py 4.0.0 was already installed via
  Rich; it is now an explicit prompt-optimization extra (>=4,<5). Offline lock
  refresh/check resolves the same 232 packages, without an SDK/package upgrade.
- GEPA side_info.scores is reserved for numeric objectives. String/category
  diagnostics now go in judge_verdict for reflection; local evaluation logs
  retain their historical schema. A real installed-SDK test catches this issue.
- Explicit baseline-score reuse verifies configuration/data/scorer hashes and
  complete unique seed validation rows. Only run5 reused run4's 32 completed
  seed scores; these are not additional model trials or API charges. Later Judge
  changes invalidate that cache and the final attempts did not reuse it.

## Calibration and Failure History

These are all development attempts, not independent A/B trials. Files remain
in data/storage/decision-gepa/<name>/. Earlier failures must not be discarded.

| Suffix | Result | Cause or interpretation |
| --- | --- | --- |
| calibration3 | 16/16 | Too narrow: no in-progress/negation controls |
| run3 | Stopped after 9 seed scores | In-progress transfer notice falsely treated as completed success |
| calibration4 | 31/32 | Explanation identified false success but verdict fields still awarded full credit |
| calibration5 | 32/32 | Independent completion review passed the expanded four-condition probes |
| run4 | 32 seed scores then TypeError | Category string entered GEPA's numeric scores objective aggregation |
| run5 | 63 completed callback scores, 32 reused | Third proposal's validation incomplete; a no-action denial was misclassified, then a whitespace-only quote difference exhausted Judge attempts |
| calibration6 | Aborted | Category returned as boolean false twice; unchanged retry request was ineffective |
| calibration7 | 48/48 | Explicit schema, corrective retry, and six-condition controls; no invalid Judge replies |
| run6 | 25 seed scores, then unscored error | Quote omitted **not** formatting markers; strict raw comparison rejected otherwise unchanged text |
| run7 | 3 seed scores, then request_error | Remote disconnected without response; no further run |

Run4's original validation was 29/32 (0.90625), but there is NO completed
candidate-validation comparison on that scoring version. Run5's third proposal
improved one training minibatch from 1/3 to 2/3, but its validation was incomplete
and included a known Judge false positive. Do not claim a prompt-quality gain
from that local repair or compare it to newer scoring versions.

The final calibration uses eight existing TRAIN inputs from four scenario
templates, each under six response conditions: original positive, planned,
in-progress, denial, hypothetical, and unsupported completed-success text.
Every condition matches 8/8 expected scores. It used 88 Judge responses: 48
semantic and 40 completion checks. Total input/output 304068/10188, cached input
235264 included; summed API time 173.141 seconds, with no schema retries.

These probes were used repeatedly to develop the evaluator, are agent-authored,
and are not a held-out accuracy estimate. Templates, IDs and rendering variants
are not independent business scenarios. Labels remain draft/unreviewed. Passing
does not guarantee performance on unfamiliar language, policy ambiguity or other
unobserved cases. Further genuine failures must be recorded, not hidden by retries.

## Verification

- Final focused pytest: 73 passed, 2 existing warnings, 2.70-second test summary;
  process exited 0. No full repository regression run.
- Ruff lint/format passed on all four touched Python files.
- Offline lock check passed, 232 packages. The first lock-check invocation used
  the sandbox default cache and failed permission checks; rerunning with the
  project's UV_CACHE_DIR succeeded without changing the environment.
- Final offline replay: 48 stored calibration outputs retain expected scores;
  4 historical invalid quotes now validate. This uses stored Judge responses,
  not fresh model inference or evidence of new Judge accuracy. Initial replay
  required explicit UTF-8 on Windows; corrected replay exited 0.
- Unit coverage includes candidate-blind grading, success-veto precedence,
  permitted confirmed success, plans/denials, quote word/negation preservation,
  Markdown rendering, corrective retries, malformed schema, no-target-regeneration,
  held-out exclusion, installed GEPA integration and baseline-cache mismatch.

## Recorded Usage Across This Repair Sequence

Successful response records only; a disconnected request has no usage response
and may still have been billed. Provider billing is authoritative. All logged
price-map costs are unavailable, NOT zero. Cached input is included in input.

| Suffix | Responses | Input tokens | Output tokens | API time sum (s) |
| --- | ---: | ---: | ---: | ---: |
| calibration3 | 16 | 51288 | 1866 | 39.190 |
| run3 | 19 | 63027 | 2301 | 43.199 |
| calibration4 | 32 | 107072 | 4192 | 67.603 |
| calibration5 | 56 | 179515 | 6242 | 113.587 |
| run4 | 86 | 294894 | 10376 | 171.248 |
| run5 | 91 | 330537 | 12723 | 217.693 |
| calibration6 | 9 | 31002 | 957 | 16.303 |
| calibration7 | 88 | 304068 | 10188 | 173.141 |
| run6 | 72 | 255262 | 8703 | 195.152 |
| run7 | 9 | 32517 | 1059 | 21.520 |
| Total | 478 | 1649182 | 58607 | 1058.636 |

Total recorded tokens: 1707789. This includes all failed, stopped and calibration
attempts listed above, but excludes the earlier calibration2 and V1 pilots.
API-time sums are not end-to-end wall time or per-task Agent latency. Intermediate
success reports and repeated runs are not proof of overall completed optimization.

## Main Artifacts

- calibration7/calibration.json: final paid probe scores and outputs.
- calibration7/judge_attempts.jsonl: raw per-stage Judge replies.
- run5/gepa-state/run_log.txt: actual reflection/selection activity before failure.
- run6/run_status.json: quote-validation evaluator_error with case identity.
- run7/run_status.json: final request_error on the target-model route.
- Each run's settings.json freezes models, budgets, data/seed/scorer/Prompt hashes.

Full paths share data/storage/decision-gepa/v2_20261023_ as the prefix.
Next paid optimization requires a fresh run and must not deploy an intermediate
candidate or report these partial values as an optimization result.
