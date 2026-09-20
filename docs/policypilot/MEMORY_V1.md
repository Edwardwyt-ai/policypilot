# PolicyPilot Memory V1

## Scope

Memory V1 implements only:

- User Profile Memory for explicit, stable preferences.
- Episodic Memory for privacy-bounded task experience.

It does not implement procedural memory, generated skills, prompt mutation,
graph memory, multi-agent memory, reinforcement learning, or evaluator-aware
memory.

## Boundary

PolicyPilotState remains task-local and authoritative only according to its
existing source rules. Long-term memory lives on PolicyPilotAgent through a
MemoryService and a separate JsonMemoryStore.

Memory is always labeled non-authoritative. It cannot resolve an
InformationNeed, satisfy identity verification, or become a Fact. Current
balances, statuses, eligibility, referral state, transactions, and policy must
still come from transactional tools or policy retrieval.

## Profile Flow

UserMessage
-> explicit-preference signal
-> lightweight model extractor
-> deterministic safety gate
-> deterministic merger
-> profile JSON store
-> deterministic user-scoped load
-> bounded Planner/Decision context

The configured memory model defaults to the current agent model, so no provider
or dependency is added. Extraction failures use a conservative deterministic
fallback and do not block the active task.

The gate accepts only approved preference aspects with sufficient confidence.
It rejects inferred preferences, identifiers, contact details, authentication
data, live state, eligibility, referrals, transactions, and current policy.

## Episodic Flow

Each PolicyPilotAgent instance owns one episode ID. Non-tool assistant outputs
upsert a privacy-bounded episode for the bound user. A later task retrieves
episodes by deterministic lexical relevance to its current objective.

Episodes contain only a sanitized objective, target, intent, preference aspects,
source classes, tool names without arguments, a coarse outcome, and a generated
structural lesson. Raw messages, Facts, Evidence, tool arguments, evaluator
criteria, and live values are excluded.

## Identity And Storage

Use memory_user_id when the caller already has a trusted user binding.
Otherwise, PolicyPilot binds after a user_id becomes visible in normal agent
observations. Anonymous tasks do not read or write long-term memory.

The store hashes normalized user IDs with SHA-256. File names and payloads do
not contain the original user ID. Writes use a temporary file plus atomic
replacement.

Store and parse failures are isolated inside MemoryService, counted in memory
metrics, and never abort the current banking task.

Default location:

    data/policypilot_memory

Important configuration:

- memory_enabled
- memory_dir
- memory_model
- memory_min_profile_confidence
- memory_max_episodes_per_user
- memory_max_recalled_episodes
- memory_max_context_chars

## Metrics

Assistant metadata records profile reads/writes, candidate acceptance/rejection,
episode reads/writes/retrievals, extraction calls/failures, and injected memory
context characters under policypilot_v1.memory.
