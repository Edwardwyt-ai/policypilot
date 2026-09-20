---
id: diagnostic-evidence
description: Minimum evidence chain for an auditable failure diagnosis.
phases: decision, recovery
trigger-tags: failure, mutation-uncertain
priority: 90
---

# Diagnostic Evidence

Inspect only the smallest relevant chain:

- error category and latest observation;
- Goal, Facts, and open InformationNeeds immediately before failure;
- proposed action and Guard result;
- ToolCall and ToolMessage;
- recovery attempt and final observable outcome.

Distinguish event facts from interpretation. A root-cause statement should name supporting event or payload references and identify missing evidence. Never persist or expose hidden chain-of-thought.

