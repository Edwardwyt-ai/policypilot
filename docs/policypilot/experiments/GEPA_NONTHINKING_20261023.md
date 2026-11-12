# Non-Thinking GEPA Decision Pilot - 2026-10-23

## Outcome

**Optimization and held-out evaluation completed successfully, but no overall
prompt improvement was demonstrated.** All experimental target, judge and
reflection calls used non-thinking mode. Production Decision thinking remains
enabled; no production instructions, business tools or database were changed.

This is a fresh experiment after the
[thinking-mode run aborted](GEPA_PILOT_20261023.md). Its target/reflector settings
changed, so the two runs are not a controlled prompt-only quality comparison.
Within this new run, seed and all candidates used the same non-thinking setting.

## Configuration and Artifacts

- GEPA 0.1.4, LiteLLM 1.81.11; all routes deepseek/deepseek-v4-pro.
- Frozen 40-example synthetic dataset: train 24 / validation 8 / test 8.
  Same dataset and seed hashes as the preceding run; no labels changed.
- Serial execution, seed 0, three proposal limit. Requested metric budget 32;
  **actual evaluations 34** because GEPA checks stopping at iteration/batch
  boundaries. This parameter is not a strict per-call or dollar spending cap.
- Output allowance 8192 for target/reflector; 1200 for non-thinking JSON judge.
- Optimize: `python -B scripts/optimize_decision_prompt.py --mode optimize --max-evals 32 --thinking disabled --output data/storage/decision-gepa/pilot_20261023_nothinking_run1`.
- Test: `python -B scripts/optimize_decision_prompt.py --mode test --thinking disabled --candidate data/storage/decision-gepa/pilot_20261023_nothinking_run1/best_prompt.txt --output data/storage/decision-gepa/pilot_20261023_nothinking_test1`.
- Both commands exited 0; no truncations occurred. No retries or bank-tool
  executions were used. No end-to-end benchmark Reward or DB Check was measured.

## Candidate Selection

Three prompt mutations were proposed. Proposal 2 was accepted into GEPA's pool
after improving its paired training minibatch from 2/3 to 3/3. Both accepted
pool members then scored 8/8 on full validation:

| Prompt | Validation | Paired second training minibatch | Final selection |
| --- | --- | --- | --- |
| Original seed | 8/8, mean 1.0 | 2/3 | Selected |
| Accepted proposal 2 | 8/8, mean 1.0 | 3/3 | Validation tie, not selected |

The SDK selects the earliest candidate on equal aggregate validation scores.
Therefore `best_prompt.txt` contains the original seed, not proposal 2.
Do not describe that file as an improved or deployed prompt. The accepted
mutation remains available in result.json under candidates[1].current_candidate.

Training example `checking_credit-03` supplies a verified checking account
SYN-CHECK, a verified USD 12 overcharge and all action prerequisites. The seed
mentioned SYN-CHECK in its response but still asked for the missing account ID,
instead of proposing the specified credit tool. The deterministic action
contract scored it zero and did not invoke a semantic judge for that output.
The accepted candidate explicitly says not to ask for values already present
in verified context, and proposed the correct account_id/amount/credit_type.

This is one observed paired repair, not a statistically established success-rate
gain. Other training evaluations used different minibatches, so their aggregate
means must not be compared as if they were a paired full-training-set test.
The same seed case had succeeded in the preceding thinking-mode run, albeit
with 6987 reasoning tokens. Disabling thinking is not proven to preserve all
reasoning quality; the new run should be judged on its own measurements.

## Held-Out Result

The selected prompt and seed are identical. Eight unique held-out cases were
therefore evaluated once each: **8/8, mean 1.0**. The duplicate selected-candidate
row is explicitly marked `reused_identical_prompt=true`; it is not a second
trial or independent evidence of improvement. There are 16 heldout.jsonl rows
but only eight target calls and eight judge calls.

The accepted non-seed proposal was NOT tested on held-out data. No test labels
were given to GEPA, and test results did not influence candidate selection.
Do not use these test outcomes to continue tuning and still call the same set
untouched. It is a tiny, agent-authored, unreviewed synthetic set with a ceiling
effect and a same-model judge, not proof of real-world 100% accuracy.

## Usage and Latency

Optimization phase, 34 evaluations and 70 API responses:

| Route | Calls | Input tokens | Output tokens | Cached input | API time sum (s) | P50 (s) | P95 (s) | Est. USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Agent | 34 | 89142 | 4485 | 15744 | 67.785 | 1.865 | 3.209 | 0.057669 |
| Judge | 33 | 99249 | 2230 | 27392 | 52.172 | 1.516 | 2.485 | 0.052444 |
| Reflection | 3 | 22543 | 1968 | 0 | 19.807 | 5.930 | 8.209 | 0.018775 |
| Total | 70 | 210934 | 8683 | 43136 | 139.764 | - | - | 0.128888 |

Only 33 judge calls were required because one target output failed the action
contract. Quantiles use nearest rank; the reflection tail has only three samples.
Optimization elapsed approximately 139.96 seconds. No reasoning tokens were
reported in any route; completion details were null, consistent with disabled
thinking and the recorded request settings.

Held-out phase: target 8 calls, 20124 input / 1097 output tokens, 15.833s API
time, estimated USD 0.012841; judge 8 calls, 23148 input / 568 output tokens,
11.792s, estimated USD 0.013136. Elapsed approximately 27.66 seconds.

The completed non-thinking experiment totals **86 API responses, 254206 input
tokens, 10348 output tokens, and estimated USD 0.154864**. Including the previous
aborted thinking-mode experiment, recorded spend is approximately USD 0.273696.
These are separate price-table estimates, not provider billing receipts.

Raw LiteLLM costs remain null because its price map lacks this model. Estimates
use the [official DeepSeek price table](https://api-docs.deepseek.com/quick_start/pricing/),
checked 2026-10-23, for the recorded off-peak run window: per million tokens,
USD 0.022 cached input, 0.66 uncached input, 1.98 output. All target/judge/reflection
responses are included. The full thinking-mode run aborted earlier on different
sample counts; comparing aggregate totals does not establish a controlled
latency or cost improvement from changing thinking mode alone.

## Verification and Next Decision

- Added experiment-only `--thinking enabled|disabled`; default remains enabled.
- 30 focused tests passed with two existing environment warnings; Ruff passed.
- Existing dependency pin, pip check and offline lock validation remain valid.
- Both real commands completed, no processes left running, no automatic prompt
  deployment, Git commit or push.

The experiment now works. Its limiting factor is validation discrimination:
baseline is already perfect on eight simple validation cases. Expand reviewed
train/validation snapshots using real Decision failures, including already-known
argument reuse, entity binding, exceptions, incomplete evidence and unsupported
completion claims. Define tie-breaking before a new experiment rather than
changing selection after inspecting its test outcomes.
