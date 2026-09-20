---
id: mutation-uncertainty
description: Safe state model and authoritative read-back requirements for unknown mutation outcomes.
phases: recovery
trigger-tags: mutation-uncertain, verification
priority: 100
---

# Mutation Uncertainty

Track the distinction between `PLANNED`, `SENT`, `CONFIRMED`, `UNKNOWN`, and `FAILED`. A timeout or error after sending may mean the external mutation applied even when no confirmation arrived.

For `UNKNOWN`: block blind retry, invalidate related cached/read Facts, perform authoritative read-back, and compare external state with intended state. If already applied, treat it as confirmed; if not applied, retry only when deterministic safety checks permit it.

Mutation response text is not a new live Fact. Verification must bypass stale task-local reuse. These guarantees belong to Guard/Recovery and fact-freshness code, not this Markdown.

