# PolicyPilot Project Structure

PolicyPilot uses a layered, feature-oriented package layout. The structure follows
the LangGraph application model of explicit state, node/workflow code, tools, and
runtime configuration while retaining the tau2 adapter contract.

## Package Layout

```text
src/policypilot/
|-- agent.py                 # tau2 adapter and dependency composition only
|-- config.py                # runtime configuration
|-- state.py                 # canonical task-scoped semantic state
|-- state_updates.py         # deterministic domain state transitions
|-- planning.py              # semantic planning policy
|-- needs.py                 # need resolution and selection
|-- need_registry.py         # canonical need lifecycle owner
|-- retrieval.py             # retrieval query and tool-call construction
|-- requirements.py          # requirement extraction and normalization
|-- coverage.py              # evidence-to-need coverage resolution
|-- evidence.py              # evidence parsing and representation
|-- tool_policy.py           # tool classification, budgets, and guard rules
|-- policy_engine.py         # final decision policy boundary
|-- workflow/
|   |-- graph.py             # LangGraph state, nodes, edges, and routing
|   `-- context.py           # compact Decision LLM context construction
|-- runtime/
|   |-- observation.py       # message ingestion and state evolution
|   |-- actions.py           # LLM calls, proposals, and tool-call audit
|   `-- recovery.py          # bounded retry and budget behavior
|-- memory/                  # long-term profile and episodic memory
|-- skills/                  # skill artifacts, matching, and runtime guidance
`-- observability/
    |-- metadata.py          # runtime trace serialization
    |-- metrics.py           # process metrics
    `-- evaluation.py        # offline evaluation reports and aggregation
```

The top-level `graph.py`, `context.py`, `metrics.py`, and `evaluation.py` modules
are compatibility shims. Existing scripts and downstream imports can migrate to
the canonical package paths without a flag day.

## Dependency Direction

```text
tau2 -> agent -> workflow -> runtime/domain services -> state
                    |
                    `-> observability (write-only reporting)
memory/skills ------^ (bounded context inputs; never task truth owners)
```

1. `agent.py` composes dependencies and implements the external tau2 interface.
   Domain algorithms do not belong in this file.
2. `workflow/graph.py` owns graph topology and routing. Nodes delegate substantive
   state changes to runtime or domain functions.
3. `runtime/` owns one-turn execution mechanics. Its functions receive a narrow
   host protocol instead of importing the concrete agent.
4. `PolicyPilotState` remains the canonical task state. Long-term memory cannot
   become an authoritative source for live banking facts.
5. `observability/` reads completed runtime state but cannot mutate planning or
   evaluator semantics.

## Extension Rules

- Add a graph node or route in `workflow/`.
- Add message/tool execution behavior in `runtime/`.
- Add requirement, need, evidence, or policy logic to the corresponding domain
  module, not to the adapter.
- Add cross-task persistence under `memory/` and reusable guidance under `skills/`.
- Add metrics and report formats under `observability/`.
- Preserve the tau2 Orchestrator, Environment, tool execution, and Evaluator
  boundaries unless a separately scoped version explicitly changes them.
