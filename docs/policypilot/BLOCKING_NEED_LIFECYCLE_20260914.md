# Blocking Need Lifecycle V1

## Scope

This checkpoint incrementally refines the existing Observation -> State Update
-> Semantic Planner -> NeedManager -> acquisition -> Decision -> Guard flow. It
does not change tau2 orchestration, environment execution, evaluator behavior,
hidden task criteria, or benchmark data.

## Implementation

- Semantic Planner is an event-triggered semantic-delta extractor. Structured
  Tool and Retrieval results use deterministic updates and do not call it.
- Planner receives compact Goal, relevant Facts, OPEN/RESOLVED Need summaries,
  at most two relevant Evidence summaries, bounded Memory/Skill hints, and the
  latest semantic observation. Output is capped at 400 tokens, temperature 0.1,
  with DeepSeek thinking disabled.
- All deterministic and semantic producers emit `NeedCandidate`. The single
  `NeedManager` performs normalization, canonicalization, stable semantic-key
  deduplication, resolved reuse, evidence coverage, criticality validation, and
  registration.
- Formal lifecycle is `OPEN/RESOLVED`. `blocking`, `actionable`, and `exhausted`
  are orthogonal routing properties; only an actionable, blocking, unresolved
  Need can route acquisition.
- Dynamic aspects are retained with provenance. Broad dynamic categories cannot
  become blockers; concrete Goal-relevant dynamic aspects can.
- Formal Needs and Planner NeedCandidates are no longer truncated. Retrieval
  attaches Evidence and updates coverage without generating background policy
  Needs.
- Semantic progress, selection, acquisition, coverage, and Planner token traces
  are recorded. Repeated equivalent evidence is not progress, and stalled or
  retrieval-exhausted blockers are released without deleting their audit state.

## Verification

- Focused Ruff: passed.
- `python -m compileall -q src/policypilot`: passed.
- Full PolicyPilot tests: `76 passed`, two unrelated host warnings, 4.01s.
- Final real evaluation: `task_010`, seed 0, DeepSeek agent/user, BM25, 40 max
  steps, 10 max errors.
- Artifact: `data/simulations/blocking_need_lifecycle_task010_seed0_final_20260914`.
- Source DB SHA-256 was unchanged.

## Final Metrics

| Metric | Result |
|---|---:|
| Reward | 0.0 |
| DB Check | false |
| Required Actions | 1/2 |
| Termination | user_stop |
| Steps | 28 |
| Tool calls | 7 |
| Retrieval calls | 2 |
| Guard blocks | 6 |
| Planner calls | 3 |
| Planner tokens | 6,007 input / 878 output |
| Main Decision calls | 8 |
| Main Decision tokens | 57,089 input / 9,053 output |
| Agent tokens | 63,683 input / 9,953 output |
| Total tokens | 77,238 input / 10,175 output |
| Agent cost | $0.086752 |
| Total cost | $0.087472 |
| End-to-end latency | 95.787s |
| Agent LLM latency | 89.626s |
| Mean Decision context | 18,191.5 chars |
| Decision context range | 17,982-18,373 chars |

## Need Audit

| Semantic key | Source | Criticality | Final | Selected | Acquisitions | Coverage |
|---|---|---|---|---:|---:|---|
| `POLICY|referral|eligibility_rule|referral` | POLICY | CRITICAL | RESOLVED | yes | 1 | MATCH |
| `TOOL|referral|current_referral_records|current_user` | TOOL | CRITICAL | RESOLVED | yes | 1 | n/a |
| `TOOL|user|credit_card_accounts|user` | TOOL | OPTIONAL | OPEN | no | 0 | n/a |
| `POLICY|referral|reward_limit|referral` | POLICY | CRITICAL | RESOLVED | no | 0 | MATCH |
| `USER|user|customer_identifier|*` | USER | CRITICAL | RESOLVED | yes | 1 | n/a |
| `TOOL|user|customer_identifier|user` | TOOL | CRITICAL | RESOLVED | yes | 1 | n/a |
| `POLICY|referral|resubmission_rule|referral` | POLICY | CRITICAL | RESOLVED | yes | 1 | MATCH |
| `TOOL|user|escalation_path|user` | TOOL | OPTIONAL | OPEN | no | 0 | n/a |
| `POLICY|referral|bonus_discrepancy_explanation|current_user` | POLICY | OPTIONAL | OPEN | no | 0 | n/a |

The reward-limit Need was resolved by compatible Evidence from the eligibility
retrieval, demonstrating multi-Need evidence reuse without an extra acquisition.
No duplicate formal Need was created and no optional Need blocked Decision.

## Retrieval Audit

1. `POLICY|referral|eligibility_rule|referral`
   Query: `referral eligibility requirements conditions referral bonus eligibility qualifying referral bonus payout conditions`.
   Result: MATCH, resolved eligibility and reward-limit Needs.
2. `POLICY|referral|resubmission_rule|referral`
   Query: `referral resubmission retry waiting rule rejected referral resubmission retry`.
   Result: MATCH, resolved the resubmission Need.

## Required Answers

- Planner still performs full planning: no. It emits only semantic deltas.
- Unnecessary Planner calls for ToolResult: no. Planner calls occurred only on
  semantic UserMessage events.
- Duplicate formal Needs remain: no duplicate was observed.
- Any-OPEN-Need acquisition loop remains: no. OPEN optional Needs did not route.
- OPTIONAL Needs incorrectly block: no.
- Retrieval expands background POLICY Needs: no.
- `task_010` recovered: no. Reward remained 0.

## Failure Attribution

**Failure:** verification logging completed, but the user-side referral
resubmission did not occur. The DB check therefore failed and Reward was 0.

**Root Cause:** after all blocking Needs resolved, Main Decision repeatedly
proposed ad-hoc `KB_search` calls that were not bound to a registered POLICY
Need. Guard correctly rejected them, but validation converted the typed failure
into a generic refusal. The Decision received no structured recovery signal and
the user received no concrete diagnosis/remediation path, so the conversation
drifted to escalation.

**Evidence:** the final run has two registered Retrieval calls with MATCH
coverage, eight Main Decision calls, and six blocked ad-hoc KB calls. The
verification action matched; the referral submission action did not. There were
zero duplicate calls, zero max-step terminations, and zero blocking Needs after
the second Retrieval.

**General Fix:** add one bounded, typed Guard-to-Need recovery path. When Decision
requests policy information without a registered Need, deterministically
classify the missing proposition, submit a `NeedCandidate` to NeedManager, and
route at most one validated blocking acquisition before re-entering Decision.
Preserve the Guard failure reason in context instead of emitting a generic
refusal. This should be based on semantic Goal/action relevance and must not use
task IDs, product answers, required documents, or evaluator criteria.
