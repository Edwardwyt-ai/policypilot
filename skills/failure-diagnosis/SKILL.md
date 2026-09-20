---
name: failure-diagnosis
description: Diagnose ambiguous or multi-event failures using state and trajectory evidence; deterministic errors and safety routes remain owned by Python runtime and Guard.
metadata:
  version: "2.0"
  purpose: "Identify evidence-supported failure causes and bounded recovery options."
  tags: "failure, recovery, diagnosis, error, mutation-uncertain"
  phases: "decision, recovery"
  priority: "100"
  required-state-fields: "information_needs, evidence, tool_history, control"
---

# Metadata

This Skill explains diagnosis methodology. It does not execute retries and does not replace deterministic error classification, Guard checks, or recovery routing.

# Applicability

Use when the cause is semantically ambiguous, several events must be correlated, a tool technically succeeded but behavior is wrong, or deterministic routing cannot identify a sufficient recovery. Ordinary observable errors should stay on deterministic routes.

# Assumptions

State, Evidence, ToolHistory, errors, and trajectory references are available. A diagnosis without supporting event references is provisional.

# Core Method

1. Identify the failed boundary and observable symptom.
2. Separate deterministic runtime errors from semantic failures.
3. Reconstruct the smallest relevant event chain: state, proposal, guard, call, result, recovery, outcome.
4. Test plausible causes against evidence and identify missing authority.
5. Recommend one bounded next step or a safe stop/escalation.

# Planning Guidance

Preserve the active Goal and unresolved Need while locating the failure boundary. Request only evidence needed to distinguish likely causes; do not restart the task or collect unrelated fields.

# Decision Guidance

Do not claim a root cause unsupported by events. Distinguish action proposed, sent, confirmed, and externally completed. If the failure affects a critical prerequisite or mutation outcome, withhold a definitive success claim.

# Recovery Guidance

Follow deterministic recovery when a category already has a safe route. Use semantic diagnosis only for cross-event ambiguity. Change the failed input or source rather than repeating an ineffective call. For unknown mutation outcome, never blind retry: invalidate related read facts and obtain authoritative read-back before any controlled retry.

# Evidence Requirements

Use error category, relevant pre-failure State, InformationNeeds, proposal, Guard result, ToolCall, ToolMessage, recovery attempts, and final outcome. Record supporting event or payload references, not hidden reasoning.

# Safety Constraints

Markdown does not provide safety enforcement. Python Guard/Recovery owns mutation blocking, retry budgets, fact invalidation, and verification requirements. Do not expose chain-of-thought or evaluator internals.

# Inputs

Errors, latest observation, State, Evidence, ToolHistory, mutation verification flags, and trajectory references.

# Expected Outputs

A concise symptom, evidence-backed cause class, confidence/unknowns, and one bounded recovery or escalation recommendation.

# Failure / Stop Conditions

Stop on exhausted budget, unavailable authority, unsafe mutation uncertainty, or insufficient events to distinguish causes. Escalate instead of inventing certainty.

# Reference Index

- `failure-taxonomy`: deterministic and semantic categories.
- `diagnostic-evidence`: minimum supporting event chain.
- `recovery-strategies`: bounded category-specific guidance.
- `mutation-uncertainty`: mutation state and read-back semantics.
