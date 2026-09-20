# Canonical Need Registry + Lightweight Runtime Report

Date: 2026-09-13

## Scope

This checkpoint changes only InformationNeed normalization, evidence coverage,
retrieval planning/budgets, lightweight LLM calls, and observability. The tau2
Orchestrator, Environment, external tool execution, hidden criteria, and
Evaluator remain unchanged.

## Verification

- Tests: 65 passed.
- Focused Ruff: passed.
- Source DB SHA-256 before/after: identical.
- Final artifact:
  `data/simulations/need_registry_lightweight_task010_seed0_final_20260913_v2`.

## Baseline vs Final task_010

| Metric | Baseline | Final | Change |
|---|---:|---:|---:|
| Reward | 0 | 0 | no improvement |
| DB Check | unavailable | false | not comparable |
| Required Actions | unavailable | 0/2 | not comparable |
| Steps | 42 | 20 | -52.4% |
| Tool calls | 15 | 4 | -73.3% |
| Retrieval calls | 13 | 2 | -84.6% |
| Agent input tokens | 91,168 | 8,067 | -91.2% |
| Agent output tokens | 35,192 | 1,677 | -95.2% |
| Agent LLM latency | 182.891s | 8.888s | -95.1% |
| End-to-end latency | 187.599s | 15.915s | -91.5% |
| Measured agent cost | $0.101328 lower bound | $0.004357 | -95.7% |
| Total cost | $0.101328 lower bound | $0.005070 | -95.0% |
| Context chars | avg 37,846.8 | unavailable (no Decision) | not comparable |

The efficiency reductions are real accounting results, but they are not a
quality improvement: the final run never reached Decision and completed no
required action.

## Final Component Distribution

| Component | Calls | Input / output tokens | Agent token share | Latency | Agent latency share | Cost | Agent cost share |
|---|---:|---:|---:|---:|---:|---:|---:|
| Semantic Planner | 4 | 7,759 / 1,666 | 96.7% | 8.088s | 91.0% | $0.004289 | 98.4% |
| Skill Matcher | 1 | 308 / 11 | 3.3% | 0.800s | 9.0% | $0.000068 | 1.6% |
| Decision | 0 | 0 / 0 | 0% | 0s | 0% | $0 | 0% |
| Context Compressor | 0 | 0 / 0 | 0% | 0s | 0% | $0 | 0% |

## Retrieval Trace

### Retrieval 1

- Need ID: `need:40c8f4572910`
- Semantic key: `POLICY|banking_product|eligibility_rule|banking_product`
- Entity / aspect / source / status: `banking_product / eligibility_rule / POLICY / OPEN`
- Query: `banking product eligibility requirements conditions referral bonus eligibility qualifying signup`
- Evidence: 10 candidates, including credit-card general referral restrictions,
  Platinum Rewards referral terms, and checking-account referral FAQs.
- Coverage: PARTIAL for the triggering Need. The same evidence MATCH-resolved
  `referral.reward_limit` and `referral.payout_timeline`.
- Why retrieval occurred: initial unresolved critical policy gap.

### Retrieval 2

- Need ID: `need:40c8f4572910`
- Semantic key: `POLICY|banking_product|eligibility_rule|banking_product`
- Entity / aspect / source / status: `banking_product / eligibility_rule / POLICY / OPEN`
- Query: identical to Retrieval 1.
- Evidence: the same 10 candidate IDs were returned from cache/retrieval.
- Coverage: PARTIAL; no additional Need was resolved.
- Why retrieved again: first evidence remained partial and the semantic Need had
  one retry remaining. This reveals a remaining query-rewrite weakness because
  attempt 2 did not change the query.

## Failure Attribution

Retrieval found the relevant credit-card referral policy. The failure occurred
at Need normalization and terminal routing: the Planner emitted a generic
`banking_product` entity/scope instead of `referral`. Strict coverage therefore
did not incorrectly mark it resolved. After two attempts the critical Need
remained open, and the graph repeatedly returned the retrieval-budget message.
Decision never ran, so neither required action was attempted:
`log_verification` and `submit_referral(user_id, Platinum Rewards Card)`.

## Diagnostic Runs

| Run | Steps | Tools | Retrievals | Cost | Main finding |
|---|---:|---:|---:|---:|---|
| initial | 36 | 13 | 7 | $0.175813 | LiteLLM dropped disabled thinking; Planner JSON truncated |
| thinking fixed | 20 | 0 | 0 | $0.005503 | malformed TOOL Need caused identity deadlock |
| serialization diagnostic | 22 | 0 | 0 | $0.004079 | metrics datetime required JSON-mode dump |
| pre-boundary verification | 32 | 5 | 1 | $0.043797 | 1/2 actions; escalation action became TOOL Need |
| final v2 | 20 | 4 | 2 | $0.005070 | generic critical Need remained PARTIAL |
