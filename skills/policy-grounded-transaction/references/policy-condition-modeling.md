---
id: policy-condition-modeling
description: Translate policy evidence into scoped executable conditions.
phases: planning
trigger-tags: transaction, policy-need, prerequisite
priority: 95
---

# Policy Condition Modeling

For each prerequisite extract: condition, subject/entity, aspect, operator, expected value, scope, and Evidence reference. Evaluate against current Facts as `TRUE`, `FALSE`, or `UNKNOWN`.

Policy text establishes the rule, not the user's current status. Preserve conjunctions and exceptions; do not collapse several prerequisites into one vague eligibility flag. Distinguish mandatory conditions from advisory guidance and permission from obligation.

