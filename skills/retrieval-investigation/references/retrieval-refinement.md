---
id: retrieval-refinement
description: Refine empty, partial, noisy, or repetitive retrieval around the actual missing anchor.
phases: planning, recovery
trigger-tags: retrieval-empty, retrieval-refinement, retrieval-repeat
priority: 100
---

# Retrieval Refinement

Compare returned Evidence with the active Need and name the uncovered aspect. Check whether the prior query omitted entity, policy concept, product/account scope, time/version scope, or mixed several questions.

The next query must materially change that weakness. Do not perform synonym-only rewrites, drop explicit hard constraints, or repeat a query whose evidence was already judged insufficient.

