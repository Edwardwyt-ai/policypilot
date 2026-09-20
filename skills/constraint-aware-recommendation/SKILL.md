---
name: constraint-aware-recommendation
description: Structure and compare multiple candidates against hard constraints, preferences, and optimization goals; do not use for simple FAQ or pure execution.
metadata:
  version: "2.0"
  purpose: "Produce evidence-grounded recommendations without losing candidate-specific requirements."
  tags: "recommendation, comparison, candidate, constraints, preference, optimization"
  phases: "planning, decision, recovery"
  priority: "80"
  required-state-fields: "goal, facts, information_needs, evidence"
---

# Metadata

This is a reusable decision method. It supplies guidance and never acts as a Fact, Tool, Policy Engine, Memory, Agent, or executable workflow.

# Applicability

Use for multiple candidates or goals combining hard constraints with preferences or optimization. Do not use for a single factual lookup, a unique policy answer, pure tool execution, or pure verification.

# Assumptions

Goal criteria retain user meaning; Facts and Evidence preserve entity and provenance; InformationNeeds identify unresolved authorities. Missing evidence remains unknown.

# Core Method

1. Separate hard constraints, preferences, optimization objectives, and explicitly permitted trade-offs.
2. Track required evidence by candidate and aspect.
3. Remove candidates that violate a hard constraint; do not remove candidates merely because optional evidence is absent.
4. Rank survivors by preference satisfaction, then optimization objective.
5. Explain the recommendation using supported criteria and acknowledged trade-offs, without exposing hidden reasoning.

# Planning Guidance

Create candidate-specific InformationNeeds from the existing Goal. Mark decision-blocking aspects critical and optional ranking details non-critical. A Fact for one candidate cannot resolve another candidate's Need. Stop acquiring information when every surviving candidate has enough evidence for hard-constraint filtering and meaningful ranking.

# Decision Guidance

Filter hard-constraint violations first, compare preference satisfaction second, and optimize only among eligible survivors. State which key requirements the selected candidate satisfies, why alternatives were excluded, and any user-permitted trade-off. If critical candidate evidence is unknown, do not pretend comparison is complete.

# Recovery Guidance

When candidate evidence is missing, conflicting, ambiguous, or stale, reopen the exact candidate-aspect Need and route it to USER, TOOL, or POLICY. Refine only the unresolved part and stop after reliable coverage or the configured budget.

# Safety Constraints

Do not override Policy Engine or Guard decisions, bypass authorization, infer absent banking facts, alter tool execution, access evaluator internals, or encode task-specific answers.

# Inputs

Structured Goal, candidate identity, Facts, InformationNeeds, Evidence, and retrieval state.

# Expected Outputs

Planning hints, a candidate evaluation method, phase guidance, and concise evidence-grounded explanation criteria. No database mutation.

# Failure / Stop Conditions

Stop or defer the recommendation when no candidate can be evaluated against a critical hard constraint, evidence conflicts remain material, or retrieval/tool budgets are exhausted. Stop gathering when further evidence is duplicate or non-decisive.

# Reference Index

- `constraint-modeling`: classify criteria and permitted trade-offs.
- `information-needs`: map candidate-aspect gaps to existing InformationNeed fields.
- `candidate-evaluation`: staged filtering and ranking.
- `decision-checklist`: compact final-decision check.
