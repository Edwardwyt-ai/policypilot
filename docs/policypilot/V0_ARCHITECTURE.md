# PolicyPilot V0 Architecture

PolicyPilot V0 is a custom single-agent policy-grounded banking agent built on top of the tau2 `banking_knowledge` environment.

```text
                 tau2 User Simulator
                        |
                        v
                PolicyPilot Agent
                        |
              +---------+---------+
              |         |         |
              v         v         v
           Ask User   BM25 KB   Transaction
                       Search      Tools
                         |           |
                         v           v
                    Policy KB    Banking DB
                         |           |
                         +-----+-----+
                               v
                       New Observation
                               |
                               v
                        PolicyPilot State
                               |
                               v
                         Next Decision
                               |
                               v
                         Final DB State
                               |
                               v
                         tau2 Evaluator
```

## State Boundaries

`tau2 State` is the benchmark runtime state: the orchestrator alternates between the user simulator, agent, environment, tools, and evaluator. It owns the simulation loop, tool execution, termination reasons, and trajectory output.

`Banking DB State` is the transactional source of truth inside the `banking_knowledge` environment. PolicyPilot never copies the full DB. It only asks tau2 tools for facts and trusts tool results over assumptions.

`PolicyPilotState` is task-local working state. It contains conversation messages, compact known facts, retrieved policy references, tool-call history, open questions, counters, and evidence records. It is not long-term memory and is discarded across tasks.

## Agent Loop

Each half-duplex turn follows the tau2 contract:

1. `get_init_state()` creates a system prompt and task-local `PolicyPilotState`.
2. `generate_next_message()` receives a `UserMessage`, `ToolMessage`, or `MultiToolMessage`.
3. PolicyPilot records the new observation as compact working state and evidence.
4. The LLM chooses exactly one next action: ask the user, call `KB_search`, call a transactional tool, or respond with final text.
5. PolicyPilot validates budgets, tool names, tool arguments, and duplicate-call risk before returning the `AssistantMessage`.
6. tau2 executes tool calls and returns new tool observations.
7. The evaluator scores final behavior using the unchanged tau2 task criteria.

This is an agent loop, not a fixed workflow: the LLM decides whether policy retrieval, DB reads, mutation, or user questioning is the next best action based on the current observation.

## BM25 Retrieval

V0 uses the existing tau2 retrieval configuration:

```text
domain = banking_knowledge
retrieval_config = bm25
```

The banking environment injects the `KB_search` tool. PolicyPilot does not create embeddings, a vector DB, dense retrieval, hybrid retrieval, or a reranker. Retrieval is agentic because the Agent decides when to call `KB_search` and what query to use; it is not run automatically for every user message.

## Evidence

PolicyPilot records an `EvidenceRecord` for user/tool observations:

- `source_type`
- `tool_name`
- `tool_args`
- `tool_call_id`
- `summary`
- `turn_index`
- `policy_refs`

For `KB_search`, the agent parses document IDs, titles, and scores only when tau2 returns those fields. It does not invent citations.

## Tool Policy

Tool calls are classified internally as:

- `knowledge`: `KB_search`, `KB_search_bm25`, `KB_search_dense`, `grep`, `shell`
- `transaction_read`: tau2 tools marked `ToolType.READ`
- `mutation`: tau2 tools that mutate state
- `transaction_other`: generic transactional helpers

Duplicate detection uses:

```text
tool_name + canonical JSON arguments
```

An identical call is blocked only when no new observation has arrived since the prior call. Re-query after new user/tool evidence is allowed. Verification reads after a mutation are also allowed.

## Budgets And Errors

Default V0 budgets mirror tau2 text-run defaults where applicable:

- `max_agent_steps = 200`
- `max_consecutive_errors = 10`
- `max_tool_calls = 80`

`max_agent_steps` and `max_consecutive_errors` align with tau2's default text run settings. `max_tool_calls=80` is intentionally below total step budget so a failed run cannot spend the entire trajectory on tools.

Tracked error categories:

- LLM API failure
- malformed tool call
- tool validation/execution error
- retrieval miss
- duplicate tool call
- step exhaustion
- tool-call exhaustion
- consecutive-error exhaustion

Mutation calls are not blindly retried by PolicyPilot. If a mutation result is uncertain or rejected, the next safe behavior is to observe/read state or ask the user rather than repeat the same mutation.

## Files

PolicyPilot code lives under `src/policypilot`. The only upstream-adjacent config change is `pyproject.toml`, where the build target includes both `src/tau2` and `src/policypilot` so the custom agent package is installable in the same project.
