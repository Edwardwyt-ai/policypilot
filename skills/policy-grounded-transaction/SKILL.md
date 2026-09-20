---
name: policy-grounded-transaction
description: Convert policy prerequisites into resolvable conditions before proposing a transaction; use for transactional goals with eligibility, identity, state, timing, limit, or prerequisite requirements.
metadata:
  version: "1.0"
  purpose: "Connect policy evidence, live facts, and InformationNeeds to transaction readiness."
  tags: "transaction, policy, prerequisite, readiness, verification"
  phases: "planning, decision, recovery"
  priority: "85"
  required-state-fields: "goal, facts, information_needs, evidence, tool_history"
---

# Metadata

This Skill is a transaction decision method, not an authorization layer or executable workflow.

# Applicability

Use when a requested mutation depends on policy prerequisites. Do not activate for informational questions with no possible action.

# Assumptions

Policy Evidence defines conditions; USER or TOOL Facts establish current values; unknown values remain unresolved.

# Core Method

Map each prerequisite to `TRUE`, `FALSE`, or `UNKNOWN`, preserving subject, operator, value, scope, and evidence. Convert unknown critical prerequisites into existing InformationNeeds. Treat policy permission and policy requirement as different claims. Proceed to mutation proposal only when critical readiness is adequately established.

# Planning Guidance

Identify required prerequisites and separate them from advisory information. Link each condition to a known Fact or a USER, TOOL, POLICY, or UNKNOWN Need. Finding a policy document does not prove that the user's live condition is true. Stop once all critical prerequisites are resolved.

# Decision Guidance

Propose a mutation only after critical prerequisites are supported. Never default UNKNOWN to TRUE, invent live values, or confuse permission with obligation. If policy evidence is missing, reopen a POLICY Need.

# Recovery Guidance

Locate the prerequisite whose evidence failed or became stale. Re-read the authoritative source or clarify the minimum user-only fact. Separate action sent from business completion and verify uncertain outcomes.

# Safety Constraints

Policy Engine and Guard retain authorization and mutation safety. Tool execution remains external to LangGraph. This Skill cannot confirm business completion.

# Inputs

Transactional Goal, policy Evidence, Facts, InformationNeeds, ToolHistory, and mutation verification state.

# Expected Outputs

Condition mapping, prerequisite Needs, readiness guidance, and completion-verification guidance.

# Failure / Stop Conditions

Stop before mutation if any critical prerequisite is false, unknown, stale, conflicting, or unavailable. Stop collecting when readiness is established or budget is exhausted.

# Reference Index

- `policy-condition-modeling`
- `prerequisite-resolution`
- `transaction-readiness`
- `completion-verification`
