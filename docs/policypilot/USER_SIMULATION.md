# Open User Simulation V1

This is a task-independent simulation harness, not real-user traffic or a new
benchmark evaluator. It reuses TauConversationRuntime and the existing banking
tools without reading task files, gold actions or required_documents.

## Initialize Without Model Calls

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/simulate_users.py --seed 42 --output data/simulations/user_seed42
```

This saves scenario.private.json and database.private.json. The user ID is
sampled from the actual synthetic database; --user-id selects an existing one.
The scenario combines an objective, preference, expression style, disclosure
style and mutation policy. It specifies no expected product or tool sequence.
Edit the objective/preferences in the private scenario to explore other needs.

The seed controls Python initialization only, not exact LLM reproducibility.
Preserve both files, model identifiers and generated transcripts for analysis.
The initial objective sampler is intentionally small and does not establish
real-world representativeness.

## Explicitly Opt In To A Paid Rollout

Configure the existing Agent/model credentials in .env. Then:

```powershell
.\.venv\Scripts\python.exe scripts/simulate_users.py --scenario data/simulations/user_seed42/scenario.private.json --database data/simulations/user_seed42/database.private.json --user-model deepseek/deepseek-chat --max-turns 12 --run --output data/simulations/user_seed42_run1
```

--run and an explicit --user-model are required for model calls. Agent routing
continues to use existing environment configuration. The existing embedding
preflight runs before Agent creation. Long-term memory and Laya are disabled
for this harness to avoid polluting persistent profiles/episodes or changing
the established routing baseline. Each run owns its copied synthetic database.
No live banking database or shared API conversation is modified.

The simulator sees private identity facts and preferences, public conversation,
and pending confirmations only. It does not see Agent state, database snapshots,
retrieved evidence or evaluation answers. It has no tools and must not invent
verification codes or live facts. If verification requires unavailable information,
it should say so or stop; this version does not simulate external SMS delivery.
Confirm/cancel moves call existing Runtime methods with the current action ID.
Refusal-policy violations, invalid JSON and illegal action types are rejected.
Semantic persona fidelity/consent is prompt-constrained, NOT proven by these
structural validators. It requires independent judging/manual review later.

## Artifacts And Limits

- scenario.private.json: complete initialized customer scenario.
- initial.private.json: Agent/runtime and synthetic DB initial snapshot.
- turns.private.jsonl: completed turns, actions, pending confirmations, tool-call
  counts, runtime latency and post-turn snapshots (including Agent LLM traces).
- result.private.json: transcript, final snapshot, simulator model/calls/usage/
  cost and wall time. Unknown costs remain null, not zero.

Termination distinguishes user_stopped, turn_limit, simulator_invalid,
simulator_error and runtime_error. business_success stays null: user satisfaction
or termination is not correctness. Invalid structured moves are separate from
simulator provider/network failures; inspect error_type for diagnosis.
Exception text is not copied into reports to avoid credential leakage.
Snapshots support subsequent diff/evidence inspection; no automatic business
invariant grader, semantic Judge or gold test-set promotion is implemented here.
This harness invokes the conversation Runtime directly, not HTTP: it does not
measure API concurrency, authentication, transport errors or HTTP latency.

Outputs contain synthetic identity details, full snapshots and tool data. They
are private local artifacts under ignored data/simulations, not sanitized exports.
Do not point --database at real customer records or publish these artifacts.
Existing output directories are rejected instead of overwritten. Turn limits
bound iterations, not money or total wall-clock duration. Simulator calls use
a 60-second timeout; Agent requests retain their existing client timeout policy.
