---
name: evidence-conflict-resolution
description: Analyze conflicts across USER, TOOL, POLICY, and MEMORY using authority, freshness, scope, provenance, and mutation history.
metadata:
  version: "1.0"
  purpose: "Prevent unresolved evidence conflicts from becoming false certainty."
  tags: "conflict, evidence, authority, freshness, provenance"
  phases: "planning, decision, recovery"
  priority: "90"
  required-state-fields: "facts, evidence, information_needs, tool_history"
---

# Metadata

This Skill supplies semantic conflict analysis. Existing deterministic source-authority and stale-fact rules remain code-owned.

# Applicability

Use for conflicting source claims, stale pre-mutation facts, explicit current preference versus Memory, identity mismatches, or apparently inconsistent policy scopes.

# Assumptions

Evidence provenance and entity/aspect scope are preserved. Different fields or entities are not automatically conflicts.

# Core Method

First verify the claims concern the same entity, aspect, time, and policy scope. Then compare source authority and freshness separately, account for mutation history and current user instruction, and create the smallest USER, TOOL, or POLICY Need required to resolve a material conflict.

# Planning Guidance

Do not pick a side by recency alone. Classify stale data, authority mismatch, semantic mismatch, entity mismatch, or policy-scope mismatch. Ignore conflicts immaterial to the active Goal; keep material conflicts unresolved.

# Decision Guidance

Do not state a definitive result while a critical conflict remains. Current explicit user preference supersedes profile preference, while authoritative tools remain required for live banking state. Explain uncertainty without exposing hidden reasoning.

# Recovery Guidance

After mutation, distrust stale read facts and use authoritative read-back where required. For policy conflicts, retrieve scope/version evidence rather than blending incompatible passages.

# Safety Constraints

Skill guidance cannot override Guard, deterministic authority rules, fact freshness, or verification enforcement.

# Inputs

Facts, Evidence provenance, Memory hints, InformationNeeds, mutation history, and current Goal scope.

# Expected Outputs

Conflict classification, materiality, missing authority, and a bounded resolution Need.

# Failure / Stop Conditions

Stop with explicit uncertainty when authoritative evidence is unavailable or budget is exhausted. Stop refreshing when the conflict is immaterial or reliably resolved.

# Reference Index

- `source-semantics`
- `conflict-analysis`
- `freshness-and-authority`
- `resolution-checklist`
