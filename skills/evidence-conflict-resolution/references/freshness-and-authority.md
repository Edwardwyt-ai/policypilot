---
id: freshness-and-authority
description: Treat freshness and authority as independent evidence dimensions.
phases: decision, recovery
trigger-tags: freshness, stale-fact, mutation-uncertain
priority: 100
---

# Freshness and Authority

An authoritative Fact can become stale; a recent claim can still be non-authoritative for its aspect. Evaluate both dimensions.

Use observation time, purpose-specific TTL, mutation history, and resource invalidation for live Facts. A mutation can invalidate an older read even when its value was originally correct. Verification must obtain a post-event authoritative observation rather than reuse stale state.

