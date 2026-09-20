---
id: transaction-readiness
description: Decide when evidence is sufficient to propose a mutation.
phases: decision
trigger-tags: transaction, prerequisite, pre-mutation
priority: 95
---

# Transaction Readiness

A transaction is ready only when the intended target and parameters are clear, all critical policy conditions are known, required live Facts are authoritative and fresh enough for pre-mutation use, and no material conflict or pending uncertain mutation remains.

Advisory information may remain optional. A found policy document, successful read call, or plausible assumption alone does not establish readiness. The Guard remains the final deterministic gate.

