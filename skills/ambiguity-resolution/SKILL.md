---
name: ambiguity-resolution
description: Resolve only decision-blocking ambiguity through existing state, TOOL/POLICY evidence, or one minimum sufficient user clarification.
metadata:
  version: "1.0"
  purpose: "Reduce ambiguity without over-questioning or collecting unnecessary user data."
  tags: "ambiguity, clarification, user-need, unknown-need"
  phases: "planning, decision"
  priority: "75"
  required-state-fields: "goal, facts, information_needs"
---

# Metadata

This Skill guides interpretation and clarification; it does not create a separate ambiguity state model.

# Applicability

Use for unclear target, intent, constraint, reference, identity, time scope, or conflict between current instruction and remembered preference.

# Assumptions

Existing Goal, Facts, InformationNeeds, and source routing remain canonical.

# Core Method

Classify ambiguity as blocking or non-blocking, then determine whether existing State, TOOL, POLICY, or only USER can resolve it. Ask one minimum sufficient question only when no authoritative non-user route exists.

# Planning Guidance

Resolve from existing State first. Route live facts to TOOL and policy meaning to POLICY. Create a USER Need only for user-only ambiguity. Prefer the question that most reduces the decision space and avoid asking for unrelated fields.

# Decision Guidance

Do not silently select among materially different interpretations. A non-blocking ambiguity may be disclosed without stopping; a blocking ambiguity must remain an open critical Need.

# Recovery Guidance

Not used in the current runtime. Recovery-specific ambiguity should be handled through failure diagnosis while preserving the original Need.

# Safety Constraints

Do not over-collect identity or sensitive data, repeat resolved questions, or replace source-routing rules.

# Inputs

Goal, current user message, Facts, open InformationNeeds, and available source capabilities.

# Expected Outputs

Ambiguity classification, source route, and at most one focused clarification prompt.

# Failure / Stop Conditions

Stop asking when the blocking interpretation is resolved, when another source can resolve it, or when the user declines optional detail.

# Reference Index

- `ambiguity-types`
- `clarification-strategy`
- `minimum-questioning`
