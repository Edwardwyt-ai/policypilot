# PolicyPilot Baseline

## Source Pin

- Base repository: `https://github.com/sierra-research/tau2-bench`
- Local path: `C:\Users\王瑜涛\Desktop\policypilot`
- Repository release/tag: `v1.0.1`
- Tag object SHA: `b711c1ead46f55111bf765cf44d5da8bacc2d28c`
- Source commit SHA: `fc0055dc4e0a316c3f83133267fbd6faaa770992`
- Source acquisition note: direct `git clone` was blocked in this Windows sandbox because the available Git installation could not spawn the HTTPS helper. The v1.0.1 source archive was downloaded from GitHub and the tag/commit SHAs above were verified with `git ls-remote`.

## Runtime

- Python version: `3.12.2`
- uv version: `0.12.9`
- Installed extras: `dev`, `knowledge`
- Install command used:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path 'work').Path + '\uv-cache'
.\.venv-bootstrap\Scripts\uv.exe sync --extra dev --extra knowledge
```

Notes:

- `uv` was not installed on PATH. A local bootstrap venv at `.venv-bootstrap` was used to install and run `uv`.
- The default uv cache path under `AppData\Local` was not writable in the sandbox, so `UV_CACHE_DIR` was set to `work\uv-cache`.
- This Windows environment does not provide `make`; the Makefile-equivalent `uv run pytest ...` commands were used.
- `PYTHONPATH=src` was required for pytest in this sandbox.

## Upstream Baseline Tests

### `make test`

Equivalent command:

```powershell
$env:PYTHONPATH = 'src'
$env:UV_CACHE_DIR = (Resolve-Path 'work').Path + '\uv-cache'
.\.venv-bootstrap\Scripts\uv.exe run pytest tests/ --ignore=tests/test_voice --ignore=tests/test_streaming --ignore=tests/test_gym --ignore=tests/test_domains/test_banking_knowledge
```

Result:

- `182 passed`
- `17 failed`
- `1 xfailed`
- `14 warnings`

Primary failure cause:

- The failing tests invoke real LiteLLM/OpenAI calls and no `OPENAI_API_KEY` is configured in this environment.
- One `test_run_tasks_base` assertion failed after the LLM-backed run produced no successful simulation result.

No upstream tests were changed or skipped to hide these failures.

### `make test-knowledge`

Equivalent command:

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
$env:UV_CACHE_DIR = (Resolve-Path 'work').Path + '\uv-cache'
.\.venv-bootstrap\Scripts\uv.exe run pytest tests/test_domains/test_banking_knowledge
```

Result with UTF-8 mode:

- `482 passed`
- `1 failed`
- `81 skipped`
- `11 warnings`

Remaining upstream failure:

- `TestAllVariantsToolPresence.test_all_variants_table_matches_registry`
- Cause: `_ALL_VARIANTS` in the upstream test does not include registered retrieval variant `alltools-qwen`.

Without `PYTHONUTF8=1`, many knowledge tests fail earlier with `UnicodeDecodeError` because Windows defaults to `cp936/GBK` while production KB JSON documents contain UTF-8 characters.

## PolicyPilot Verification

Command:

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest tests/policypilot -q
```

V0 result before the V1 change:

- `14 passed`
- `1 skipped`

V1 LangGraph offline result on 2026-09-03:

- PolicyPilot suite: `45 passed`, `1 skipped`, `2 warnings`. The skip is the
  real-model case, which now requires `POLICYPILOT_RUN_INTEGRATION=1` so an
  ordinary unit-test run cannot accidentally incur API usage.
- The graph tests cover required nodes, observation/state propagation, text
  finalization, tool-call handoff without execution, non-terminal empty
  questions, and bounded invalid-action recovery.
- Ruff on PolicyPilot source, tests, and the PolicyPilot runner: passed.
- Combined non-voice/non-gym/non-knowledge suite after the graph change:
  `227 passed`, `1 skipped`,
  `1 xfailed`, `17 failed`, `14 warnings`. The same 17 upstream online failures
  remain because no OpenAI credentials are configured; PolicyPilot added no new
  failure in this run.
- Banking knowledge suite: `482 passed`, `81 skipped`, `1 failed`, `11 warnings`.
  The sole failure remains the upstream `_ALL_VARIANTS`/`alltools-qwen` mismatch.
- Offline assembly: `PolicyPilotAgent` built successfully against the real
  `KnowledgeToolsWithKBSearch` BM25 environment with `KB_search` present.

## DeepSeek Integration And Comparison

DeepSeek was configured locally through the ignored `.env` file, using
`deepseek/deepseek-chat` for both the agent and user simulator. A minimal model
call succeeded before benchmark execution.

- Real integration pytest: `task_010`, `1 passed` in 39.58 seconds.
- First formal V1 run: reward `0.0`, 8 tool calls, 4 retrieval calls, no errors
  or retries. The required agent-side verification action passed, but the user
  simulator did not complete its required follow-up action.
- That run exposed a context-size defect: recent raw retrieval messages produced
  an 88,736-character context. V1 now passes compact ToolMessage copies to the
  model while preserving raw payloads in state/trajectory.
- Post-fix bounded comparison used the same `task_010`, models, BM25 retrieval,
  seed 300, `max_steps=20`, and `max_errors=10` for both agents. Baseline and V1
  both terminated at the step limit with reward `0.0`; the run is therefore not
  a task-success comparison. V1 made 8 tool calls with 0 duplicates, 0 errors,
  and 0 retries. Its final context size was 20,760 characters, 76.6% below the
  pre-fix V1 run.

One unbounded post-fix V1 comparison trajectory was manually stopped after 180
seconds to prevent uncontrolled API usage. This indicates that DeepSeek can
enter a long conversation on this task; the bounded result above is the current
reproducible comparison.

The final LangGraph implementation was also exercised through the real tau2
runtime on `task_010` with DeepSeek for both roles, BM25, seed 300, and
`max_steps=20`. The simulation completed normally at the configured step limit
in 12.99 seconds: reward `0.0`, 23 messages, 10 tool calls, 6 retrieval calls,
0 tool errors, 1 goal change, 0 retries, and a final estimated context size of
26,124 characters. This verifies real integration and tool handoff, but it is
not a successful benchmark trajectory. A separate opt-in run with the test's
default `max_steps=200` was stopped after three minutes because the simulated
conversation remained active.

## Task 010 Debugging Closure (2026-09-05)

The zero reward was not caused by DeepSeek response latency. `task_010` uses a
binary database reward: both the agent-side `log_verification` write and the
user-side `submit_referral` write must match. Earlier trajectories completed
only the verification write, so the DB hash did not match even when the spoken
explanation was partially correct.

The final guarded run used DeepSeek for both roles, BM25 retrieval, seed 0, and
`max_steps=40`:

- reward: `1.0`
- DB check: `1.0`
- required actions: `2/2`
- termination: `USER_STOP`
- duration: `47.07s`
- messages: `35`
- agent cost: `$0.0515`
- user cost: `$0.0025`
- saved trajectory: `data/simulations/policypilot_task010_guarded_final/results.json`

The successful action path was: retrieve and match the customer record, read
the environment time, log verification with that exact timestamp, retrieve all
four referral records, ground the status/rolling-window explanation in policy,
ask the customer to submit the now-eligible Platinum referral, observe the
customer-side `submit_referral`, and verify the new `NO_PROGRESS` record with a
read call.

Final PolicyPilot verification after the fixes:

- PolicyPilot suite: `58 passed`, `1 skipped`, `2 warnings`
- Ruff on `src/policypilot` and `tests/policypilot`: passed

The two warnings are unchanged environment warnings: Python's deprecated
`audioop` import and an unavailable pytest asyncio configuration option.
