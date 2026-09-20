# PolicyPilot V1 Architecture

PolicyPilot V1 uses tau2 as the outer runtime and LangGraph as a bounded inner
decision workflow. It does not replace tau2 orchestration, banking state,
retrieval, tool execution, trajectory capture, or evaluation.

## Runtime Boundary

```text
tau2 Orchestrator
  -> PolicyPilotAgent.generate_next_message(observation, state)
  -> LangGraph internal invocation
  -> tau2-compatible AssistantMessage (text or ToolCall)
  -> tau2 Environment executes any ToolCall
  -> ToolMessage enters the next PolicyPilot invocation
```

There is deliberately no LangGraph `ToolNode`. A valid tool proposal finalizes
the current graph invocation. Only the tau2 Environment may execute banking or
`KB_search` tools, preserving the benchmark's message, trajectory, and evaluator
semantics.

## Graph State

`PolicyPilotGraphState` wraps the existing persistent `PolicyPilotState`; it does
not duplicate its goal, fact, evidence, history, error, or budget fields. The
wrapper carries invocation-local values: `latest_observation`, observation
outcomes, constructed context, proposed/final action, validation status and
category, recovery kind/attempts/route, node trace, and finalization status.

`PolicyPilotState` remains the task-local state returned to tau2 across calls. It
contains active/pending/completed goals, lightweight intent, sourced facts, open
questions, evidence, raw message history, compact tool history, structured
errors, observation versions, and process counters.

## Nodes And Edges

The compiled `StateGraph` has seven nodes:

1. `ingest_observation`: accepts the current tau2 observation and checks existing
   stop budgets without LLM reasoning.
2. `update_state`: applies deterministic observation, goal, intent, fact,
   question, evidence, tool-result, and error updates.
3. `build_context`: creates bounded model input with `build_agent_context()`.
4. `decision`: calls the main LLM for text or a tool proposal.
5. `validate_action`: applies the deterministic `ToolCallGuard`, duplicate
   checks, mutation constraints, and tool-call budget.
6. `recover`: performs only the selected bounded read, retrieval, or action
   recovery.
7. `finalize`: attaches metrics, appends the assistant message to task state,
   and returns a tau2-compatible `AssistantMessage`.

The normal route is `START -> ingest_observation -> update_state ->
build_context -> decision -> validate_action -> finalize -> END`.
Pre-existing or newly exhausted budgets route to `finalize`. Observation errors
route from `update_state` to `recover`. Invalid proposals route from
`validate_action` to `recover` when their category has attempts remaining,
otherwise to `finalize`. Recovery returns to `build_context`, `validate_action`,
or `finalize` according to error type. `max_graph_steps` provides a final graph
recursion bound in addition to category-specific retry limits.

## Goal And Intent Lifecycle

The first substantive user request starts the active runtime goal. Ordinary
follow-ups continue it; explicit correction replaces it; additional work becomes
pending; explicit completion moves it to completed goals and may activate the
next pending goal. Each transition stores a short `GoalUpdate`, never
chain-of-thought. These goals are not benchmark `Task` objects.

Intent is a small deterministic label: `INFORMATIONAL`, `STATUS_CHECK`,
`ELIGIBILITY_CHECK`, `TRANSACTIONAL`, `CORRECTION`, or `OTHER`. Regex/marker
classification supports goal and action selection without introducing a large
customer-service taxonomy.

## Facts And Questions

Python regexes extract stable user identifiers, contact data, amounts, and
explicit confirmation. Deterministic parsers extract flattened banking-tool
fields and policy document references. Facts keep key, compact value,
source type/reference, turn, and verification status. Equal facts are deduplicated;
a verified banking-tool value can replace an unverified user value. V1 does not
make a second LLM call for fact or intent extraction.

Identity matching records only matched/mismatched field names, not another copy
of sensitive values. The environment's `get_current_time` result is retained as
a verified critical fact. `log_verification` is blocked unless its timestamp
exactly matches that fact, preventing model-invented verification times.

Open questions are deterministic information gaps tied to the current goal and
accepted answer fact keys. New relevant facts resolve matching questions. Policy
requirements may add condition questions. An empty list never marks the task
successful: the decision LLM still chooses text or a tool call, while only the
tau2 evaluator determines benchmark success.

## Evidence And Context

Evidence provenance is recorded programmatically: source type, turn, tool name,
arguments, call ID, retrieval query, document ID/title/score, error flag, and a
bounded summary. The model cannot invent provenance.

Decision context contains the domain/system prompt, current goal, intent,
pending goals, selected known facts, open questions, relevant evidence, compact
recent tool history, unresolved recovery state, safety/retrieval constraints,
available tool names, and a coherent recent conversation suffix. Full schemas
are still passed through tau2's model wrapper. Configured windows bound raw
history; tool payloads are compacted in model-only copies, while raw state and
trajectory messages remain unchanged. Critical IDs, amounts, confirmations,
policy conditions, and mutation results survive pruning as structured state.

Multi-record transactional responses are parsed from the raw tool payload, so
later records are not lost when the display summary is truncated. Retrieval
summaries allocate space to every ranked document, preserve actionable
wait/retry guidance, and keep the first relevant policy search as a foundational
anchor alongside recent evidence. A per-goal retrieval budget prevents repeated
narrow searches after sufficient policy evidence is available.

## Error Recovery

- LLM transient/API failure: bounded exponential-backoff retries, then a
  structured terminal error and clean response.
- Tool validation or malformed proposal: validation feedback is supplied for a
  bounded model repair, then blocked.
- Tool execution failure: recorded deterministically; a failed read may emit one
  new tau2 tool call, while other failures return to contextual decision-making.
- Empty retrieval: one rewritten query is permitted; a second miss exhausts the
  recovery route for the current goal.
- Duplicate proposal: deterministic block plus at most one feedback repair.
- Exhausted step/tool/error/graph budget: clean final response with no loop.
- Uncertain mutation: never replayed blindly; state requires a later read
  verification before another mutation.

For eligible customer-side retry/resubmission flows, finalization includes a
narrow completion guard. If the model has told the customer that they can act
but leaves the response as future intent, the guard asks the customer to perform
the exact verified product action now and waits for its result. It does not
execute the customer tool or alter evaluator state.

## tau2 Adapter

`PolicyPilotAgent` still implements the real half-duplex interface:
`get_init_state(history)` and `generate_next_message(observation, state)`. The
second method invokes the compiled graph once and returns `(AssistantMessage,
PolicyPilotState)`. Tool execution remains outside this adapter and outside the
graph.
