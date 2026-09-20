---
id: prerequisite-resolution
description: Connect policy conditions to Facts and existing InformationNeeds.
phases: planning, recovery
trigger-tags: information-needs, prerequisite, user-need, tool-need, policy-need
priority: 90
---

# Prerequisite Resolution

- Match a condition only to a Fact with the same entity, aspect, scope, and authoritative source.
- Missing policy meaning creates a POLICY Need.
- Missing live state creates a TOOL Need.
- User-only intent or choice creates a USER Need.
- Unclear source remains UNKNOWN until routed.
- `FALSE` is a known blocker; `UNKNOWN` is unresolved, never implicitly true.

Reuse the current InformationNeed schema and stop when every critical prerequisite is resolved.

