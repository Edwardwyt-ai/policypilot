---
name: retrieval-investigation
description: Plan focused multi-concept policy retrieval around unresolved InformationNeeds; use for complex, partial, empty, or repetitive retrieval, not simple lookups.
metadata:
  version: "1.0"
  purpose: "Improve policy evidence acquisition while enforcing clear retrieval stop conditions."
  tags: "retrieval, policy-need, decomposition, refinement, evidence"
  phases: "planning, recovery"
  priority: "78"
  required-state-fields: "goal, information_needs, evidence, control"
---

# Metadata

This Skill guides retrieval planning. It is not a retriever, does not execute tools, and does not cache or rank final answers.

# Applicability

Use for multiple constraints or policy concepts, partial/empty results, transaction prerequisites, or repeated similar queries. Do not use for a simple single-fact lookup.

# Assumptions

The active InformationNeed is the retrieval objective; Goal and known scope provide anchors; Evidence determines coverage.

# Core Method

Build a focused query from active Need, entity, policy scope, and preserved hard constraints. Decompose only independent questions. After each result, identify the remaining gap and refine that gap rather than mechanically paraphrasing the same query. Promote only relevant evidence into compact context.

# Planning Guidance

Start from the exact POLICY Need, not the whole conversation. Add missing entity, concept, product/account, time, or version anchors. Split a compound Need only when parts require independent evidence. Stop when critical coverage is reliable or the missing source is actually USER/TOOL.

# Decision Guidance

Not normally injected into Decision. Once retrieval is complete, Decision should consume Evidence rather than retrieval tutorials.

# Recovery Guidance

For empty, partial, noisy, or duplicate results, diagnose the missing anchor or mixed concepts and issue one materially changed query. Respect retrieval budget and stop on repeated evidence or source mismatch.

# Safety Constraints

Do not drop hard constraints, copy full documents into Decision context, access required_documents, or encourage unbounded search.

# Inputs

Goal, active POLICY InformationNeed, Evidence coverage, retrieval history, and budget state.

# Expected Outputs

Focused query objective, optional decomposition, refinement reason, evidence selection criteria, and stop decision.

# Failure / Stop Conditions

Stop on reliable Need coverage, duplicate-only results, exhausted budget, source mismatch, or a conflict requiring separate resolution.

# Reference Index

- `query-decomposition`
- `retrieval-refinement`
- `evidence-selection`
- `retrieval-stop-conditions`
