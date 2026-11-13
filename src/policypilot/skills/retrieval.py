"""Bounded Skill retrieval using the policy tokenizer and optional episode embeddings."""

from rank_bm25 import BM25Okapi

from tau2.domains.banking_knowledge.hybrid_retrieval import tokenize


def rank_skills(query, metadata, limit, embedder=None):
    items = sorted(metadata, key=lambda item: (-item.priority, item.name))
    if not items:
        return []
    texts = [f"{item.name} {item.description} {' '.join(item.tags)}" for item in items]
    sparse = BM25Okapi([tokenize(text) or [""] for text in texts]).get_scores(
        tokenize(query)
    )
    lexical = sorted(range(len(items)), key=lambda i: (-sparse[i], i))
    if embedder is None:
        return [items[i] for i in lexical[:limit]]
    shortlist = lexical[: max(limit, 32)]
    vectors = embedder.embed([query, *(texts[i] for i in shortlist)]).vectors
    vector_index = {i: j for j, i in enumerate(shortlist, 1)}
    dense = sorted(
        shortlist,
        key=lambda i: -sum(
            a * b for a, b in zip(vectors[0], vectors[vector_index[i]], strict=True)
        ),
    )
    lexical_rank = {idx: rank for rank, idx in enumerate(lexical, 1)}
    dense_rank = {idx: rank for rank, idx in enumerate(dense, 1)}
    fused = sorted(
        shortlist,
        key=lambda i: -(1 / (60 + lexical_rank[i]) + 1 / (60 + dense_rank[i])),
    )
    return [items[i] for i in fused[:limit]]


def eligible(spec, state, recovery_mode):
    trigger = spec.trigger
    needs = state.open_needs()
    if trigger.intents and state.intent not in trigger.intents:
        return False
    if trigger.targets and (state.goal.target or "").casefold() not in {
        target.casefold() for target in trigger.targets
    }:
        return False
    if trigger.need_sources and not any(
        need.source in trigger.need_sources for need in needs
    ):
        return False
    if trigger.recovery_modes and recovery_mode not in trigger.recovery_modes:
        return False
    conditions = {
        "goal": bool(state.goal.objective),
        "evidence": bool(state.evidence),
        "open_need": bool(needs),
        "verified_tool_fact": any(
            fact.source == "TOOL" and fact.verified and fact.stale_at is None
            for fact in state.facts
        ),
        "no_uncertain_write": not state.control.mutation_verification_required,
    }
    return all(conditions[key] for key in spec.preconditions)
