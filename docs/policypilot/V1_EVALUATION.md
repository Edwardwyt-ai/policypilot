# PolicyPilot V1 Evaluation Runner

`scripts/evaluate_v1.py` evaluates the unchanged PolicyPilot V1 agent against
`banking_knowledge`. It runs tasks sequentially with a fresh tau2 simulation for
each task. A failed task is recorded and the batch continues; derived JSONL,
JSON, and CSV outputs are atomically replaced after every task attempt.

## Usage

Explicit task IDs:

```bash
uv run python scripts/evaluate_v1.py \
  --task-ids task_001 task_010 \
  --agent-model deepseek/deepseek-chat \
  --user-model deepseek/deepseek-chat \
  --seed 0 \
  --max-steps 40 \
  --max-errors 10 \
  --save-to v1_eval_seed0
```

Reproducible random sample or deterministic first N tasks:

```bash
uv run python scripts/evaluate_v1.py --num-tasks 3 --selection random \
  --agent-model <model> --user-model <model> --seed 0 --save-to v1_random3

uv run python scripts/evaluate_v1.py --num-tasks 3 --selection first \
  --agent-model <model> --user-model <model> --seed 0 --save-to v1_first3
```

`--task-file` accepts newline-separated or comma-separated task IDs. Existing
evaluation output is never overwritten; use a new `--save-to` name.

## Output

```text
data/simulations/<run-name>/
  config.json
  task_results.jsonl
  summary.json
  summary.csv
  failures.jsonl
  tasks/<task-id>/results.json
  tasks/<task-id>/artifacts/...
```

`results.json` and `artifacts` are the native tau2 trajectory outputs.
`task_results.jsonl` contains one structured metric record per selected task.
`summary.csv` contains the same task-level rows for spreadsheet analysis.
`failures.jsonl` contains only failed tasks and compact trajectory evidence for
later human analysis. It performs no LLM-based failure analysis.

## Metric Definitions

- `success` means `reward == 1.0`.
- A runner exception counts as an unsuccessful task with reward `0` in batch
  averages, while its unavailable task metrics remain `null` or zero.
- `episode_latency_seconds` is tau2's `SimulationRun.duration`; Python startup,
  imports, registry setup, and knowledge-base warmup are outside this value.
- Tool-call counts come from structured `ToolCall` objects. Tool errors come
  from trajectory `ToolMessage` and existing PolicyPilot metrics.
- Guard and recovery categories come from read-only `policypilot_v1` metadata
  attached after decisions. This metadata is not included in model context.
- Context size is measured in characters per real assistant LLM call because
  PolicyPilot currently records bounded-context character estimates.
- Input/output tokens, message generation latency, and costs are read from
  structured tau2/LiteLLM message and simulation fields when present. If tau2's
  episode-level cost is `null`, the runner sums the available real LLM message
  costs; synthetic and Guard-generated messages are excluded.
- Percentiles use linear interpolation over all available values.
- Source `db.json` SHA-256 is recorded before and after the batch. Each task
  still uses tau2's isolated environment state.

The current trajectory schema does not expose reliable context section sizes,
retrieval latency, or tool latency. These fields are `null` and listed under
`unavailable_metrics`; the runner does not infer them from log strings.

## Hidden Evaluation Data

Task selection uses task IDs only. Metric and failure extraction accepts a
completed `SimulationRun`, not a benchmark `Task`, so `evaluation_criteria`,
reference actions, and required documents cannot enter PolicyPilot runtime
context through this evaluation layer. Native tau2 evaluates the episode after
execution as before.

## Smoke Verification (2026-09-05)

The first real smoke batch used DeepSeek for both roles, BM25 retrieval, seed 0,
and `max_steps=40`. It is saved under
`data/simulations/v1_eval_smoke_seed0`.

| Task | Reward | DB | Actions | Termination | Steps | Cost |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| `task_010` | 1.0 | 1.0 | 2/2 | `user_stop` | 35 | $0.053507 |
| `task_001` | 0.0 | 0.0 | 0/1 | `user_stop` | 30 | $0.031009 |

The batch success rate and average reward were both 0.5. Total input/output
tokens were 270,190/7,011, total cost was $0.084516, and average episode latency
was 35.43 seconds. Both native tau2 result files, both JSONL files, the summary
JSON, and the CSV were reloaded successfully. The source database SHA-256 was
`e692feb797c659f0e21ff7380aa87beb4e95a0694d7bb7945f073102f0293d28`
before and after the batch.
