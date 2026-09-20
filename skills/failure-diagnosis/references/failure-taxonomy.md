---
id: failure-taxonomy
description: Separate runtime-observable errors from semantic failures requiring cross-event analysis.
phases: decision, recovery
trigger-tags: failure
priority: 75
---

# Failure Taxonomy

Deterministic categories include `LLM_TRANSIENT`, `TOOL_VALIDATION`, `TOOL_EXECUTION_ERROR`, `RETRIEVAL_EMPTY`, `DUPLICATE_TOOL_CALL`, `BUDGET_EXHAUSTED`, and `MUTATION_UNCERTAIN`. Their routing remains code-owned.

Semantic failures include goal misinterpretation, Need omission, wrong source routing, policy misretrieval, context omission, and decision error. Diagnose these only by correlating multiple observable events. Do not relabel a clear runtime error merely to invoke an LLM.

