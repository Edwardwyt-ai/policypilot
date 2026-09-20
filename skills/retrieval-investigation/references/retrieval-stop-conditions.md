---
id: retrieval-stop-conditions
description: High-density conditions for ending policy retrieval.
phases: planning, recovery
trigger-tags: retrieval, policy-need, retrieval-repeat
priority: 90
---

# Retrieval Stop Conditions

Stop when:

- reliable Evidence covers the critical Need;
- further results repeat existing support;
- the configured retrieval budget is reached;
- the missing authority is USER or TOOL, not POLICY;
- an evidence conflict requires separate resolution;
- no materially different query remains.

More documents are not inherently better than sufficient, scoped evidence.
