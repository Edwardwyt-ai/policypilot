---
id: completion-verification
description: Distinguish action lifecycle stages and business completion evidence.
phases: decision, recovery
trigger-tags: transaction, verification, mutation-uncertain
priority: 100
---

# Completion Verification

Keep four observable stages separate:

- **proposed:** an AssistantMessage contains the mutation ToolCall;
- **sent:** tau2 Environment received the call;
- **confirmed:** a non-ambiguous ToolMessage reports completion;
- **business completion:** authoritative external state reflects the intended result.

An uncertain response cannot advance directly to confirmed. Use authoritative read-back when deterministic recovery requires it; do not derive live Facts from mutation prose.

