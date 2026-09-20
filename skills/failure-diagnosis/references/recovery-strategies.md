---
id: recovery-strategies
description: Bounded recovery principles by observable category.
phases: recovery
trigger-tags: tool-execution, retrieval-empty, duplicate-tool-call, budget-exhausted, failure
priority: 80
---

# Recovery Strategies

- Validation: repair only deterministically identifiable arguments; otherwise stop safely.
- Read execution: retry only retryable failures within budget.
- Empty retrieval: change the missing anchor or strategy, not just wording.
- Duplicate call: reuse valid State or change the information source; do not execute again.
- Budget exhaustion: terminate with a bounded, uncertainty-aware fallback.

These are diagnostic directions. Guard and Recovery Python code must continue enforcing retries, blocking, and budgets.

