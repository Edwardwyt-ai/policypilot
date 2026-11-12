# GEPA Decision Prompt Pilot - 2026-10-23

## Outcome

**Installation succeeded; the paid optimization run aborted on output truncation.**
No optimized prompt was selected, published or deployed. The held-out test set
was not called. This is a partial experiment, not an improvement result.

## Reproduction Identity

- GEPA 0.1.4, LiteLLM 1.81.11, project Python 3.12 virtual environment.
- Optional dependency: `prompt-optimization`; pyproject and uv.lock updated.
  No existing model SDK was upgraded. PyPI wheel SHA256:
  `12b971039599625c156d2231f6d72a29c31a22e9c237689459b5f1a3c353f532`.
- All three routes: `deepseek/deepseek-v4-pro`. Agent and reflector thinking
  enabled; judge non-thinking JSON. Target/reflector output budget 8192,
  judge budget 1200. No explicit reasoning-effort setting. Serial execution,
  seed 0, requested evaluation budget 32, proposal cap 3, no hidden retries.
- Frozen synthetic dataset: train 24 / validation 8 / test 8; document/family
  disjoint. Only train/validation passed to GEPA. Not human-reviewed gold.
- Data hash: `e8f313588660d0cf846474fb8af6fdcb740d1a6993abf47cbb21daa474556aa4`.
- Seed hash: `87d39248c416ac8749e910c5f30470f99baede4bdc30fed505a27085181bc8e9`.
- Start 2026-10-23 00:21:08 +08:00; last response 00:26:42 +08:00.
  Approximately 334.69 seconds elapsed.
- Command: `python -B scripts/optimize_decision_prompt.py --mode optimize --max-evals 32 --output data/storage/decision-gepa/pilot_20261023_run1`.
- Agent runtime, environment, tools and deployed instructions unchanged.
  No bank tools were executed; no benchmark task reward was evaluated.

## Quality Results

| Candidate | Split | Scored cases | Mean score | Interpretation |
| --- | --- | ---: | ---: | --- |
| Original seed | Validation | 8 | 1.000 | All eight cases passed |
| Original seed | Sampled training | 6 distinct | 1.000 | Only six of 24 training cases visited |
| Proposal 1 | Same first training minibatch | 3 | 1.000 | Equal to seed; rejected by strict improvement |
| Proposal 2 | Next training minibatch | 0 completed | unavailable | First candidate call truncated |
| Any candidate | Held-out test | 0 | unavailable | Test remains untouched |

The 17 completed evaluations cover 14 distinct cases; three are repeated under
proposal 1. The failed 18th target call is not assigned an artificial zero and is
not included in the 17 quality scores. There is no completed proposal-2 score.
Proposal 1 was never promoted to full validation. Baseline validation already
hit the ceiling, so this small synthetic set provides little optimization signal.
Do not infer that GEPA cannot improve the actual agent or that this proves 100%
real-world accuracy. Target and judge are also the same model, not independent
ground truth.

## Earliest Failure

The first target call for proposal 2 returned:

- `finish_reason: length`;
- input 3170 tokens, completion 8192 tokens;
- `completion_tokens_details.reasoning_tokens: 8192`;
- latency 87.377 seconds;
- no final answer/tool action available for semantic scoring.

The exception was `Model output truncated; increase output budget before comparing prompts`.
It was raised after persisting usage, before calling the judge. This is a
Decision-generation/output-budget failure, not a GEPA installation error,
network timeout, input context overflow, business-tool error or database failure.

Thinking consumes the completion allowance. The original seed had already
produced a long call on `checking_credit-03`: 7077 output tokens, of which 6987
were reasoning tokens, with 71.79 seconds latency. Thus the 8192-token ceiling
was already tight before the second proposal. The failed sample's ID was not
persisted before its exception, so this report does not assert that it was the
same credit case. The final API usage and GEPA logs establish the truncation
without requiring exposure of private reasoning text.

The run stopped rather than increasing only the failing candidate's allowance,
changing thinking mode mid-comparison, treating infrastructure failure as poor
answer quality, or spending further calls. There was no automatic paid rerun.

## Usage, Latency and Estimated Cost

All 37 completed API responses, including the truncated response, are counted.
Reasoning tokens are a subset of output tokens, not added a second time.
Latency quantiles use nearest rank; reflection has only two samples.

| Route | Calls | Input tokens | Output tokens | Reasoning tokens | API time sum (s) | P50 (s) | P95 (s) | Est. USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Agent | 18 | 47692 | 18445 | 16705 | 205.923 | 2.943 | 87.377 | 0.063588 |
| Judge | 17 | 49140 | 1260 | 0 | 28.779 | 1.662 | 2.455 | 0.029374 |
| Reflection | 2 | 15325 | 7957 | 6581 | 99.890 | 35.664 | 64.226 | 0.025869 |
| Total | 37 | 112157 | 27662 | 23286 | 334.592 | - | - | 0.118831 |

Cached input: Agent 6912, judge 8704, reflection 0; total 15616 tokens.
Agent/judge/reflection account for approximately 61.54% / 8.60% / 29.85% of
summed API latency, and 53.51% / 24.72% / 21.77% of estimated cost.

LiteLLM returned unavailable prices for this model, so raw `cost` fields remain
null, not zero. The separate estimate uses the
[official DeepSeek price table](https://api-docs.deepseek.com/quick_start/pricing/)
checked on 2026-10-23 and this run's off-peak time: per million tokens,
USD 0.022 cached input, 0.66 uncached input, 1.98 output. Formula:
`(cached_input * .022 + uncached_input * .66 + output * 1.98) / 1_000_000`.
Estimated total is about USD 0.119; it is not a provider billing receipt.

## Artifacts and Verification

Local run directory: `data/storage/decision-gepa/pilot_20261023_run1/`.
Contains settings/version/data hashes, all-route calls.jsonl, 17 scored
evaluations, GEPA candidate/state and run logs. The directory is ignored by Git.
There is no best_prompt.txt, result.json or heldout.jsonl from a completed run.
Do not treat a saved GEPA checkpoint as a deployed or validated prompt.

- 29 focused tests passed, including an installed-GEPA offline smoke test;
  two existing environment warnings.
- Ruff checks passed; pip check reports no broken requirements.
- `uv lock --check --offline` passed, resolving 232 packages.
- Python/test and optimization processes exited; the paid run's exit code was 1.
- No commit or push performed.

Next experiment should first freeze a consistent reasoning/output-budget policy
for both seed and candidates, then start a new run. Lower reasoning effort or
a larger completion allowance are distinct configuration choices; do not change
only the failed candidate. Build harder reviewed training/validation cases from
real frozen Decision failures before claiming optimization gains. Do not alter
this run's labels retrospectively. The eight test examples remain reserved.
