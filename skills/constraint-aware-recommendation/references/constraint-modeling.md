---
id: constraint-modeling
description: Map Structured Goal criteria to hard constraints, preferences, optimization, and permitted trade-offs.
phases: planning
trigger-tags: constraints, preference, optimization
priority: 90
---

# Constraint Modeling

- **Hard constraint:** failure makes a candidate ineligible. Preserve its entity, aspect, operator, value, condition, and source turn.
- **Preference:** affects ranking but does not make an otherwise eligible candidate invalid.
- **Optimization objective:** defines how to order surviving candidates, such as minimizing or maximizing an evidenced aspect.
- **Trade-off permission:** an explicit user allowance to relax a named criterion under stated conditions; never infer it from silence.

Map these concepts to the existing Goal criteria. Do not create a parallel requirement model. When wording is ambiguous between hard and soft, keep an InformationNeed rather than silently weakening it.

