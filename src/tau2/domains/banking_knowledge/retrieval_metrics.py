"""Deterministic information-retrieval metrics used by offline evaluation."""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import mean


def evaluate_rankings(
    rankings: Sequence[Sequence[str]],
    gold_sets: Sequence[set[str]],
    *,
    cutoffs: Sequence[int] = (1, 3, 5),
) -> dict[str, float]:
    """Compute macro/micro recall, hit rate, MRR, and binary nDCG."""
    if len(rankings) != len(gold_sets):
        raise ValueError("rankings and gold_sets must have the same length")
    if not rankings:
        raise ValueError("At least one ranking is required")
    if any(not gold for gold in gold_sets):
        raise ValueError("Every query must have at least one gold document")

    metrics: dict[str, float] = {"query_count": float(len(rankings))}
    for cutoff in cutoffs:
        if cutoff <= 0:
            raise ValueError("Metric cutoffs must be positive")
        hits_per_query = [
            len(set(ranking[:cutoff]).intersection(gold))
            for ranking, gold in zip(rankings, gold_sets, strict=True)
        ]
        metrics[f"macro_recall@{cutoff}"] = mean(
            hits / len(gold) for hits, gold in zip(hits_per_query, gold_sets, strict=True)
        )
        metrics[f"micro_recall@{cutoff}"] = sum(hits_per_query) / sum(
            len(gold) for gold in gold_sets
        )
        metrics[f"hit_rate@{cutoff}"] = mean(hits > 0 for hits in hits_per_query)

        reciprocal_ranks = []
        ndcgs = []
        for ranking, gold in zip(rankings, gold_sets, strict=True):
            first = next(
                (rank for rank, doc_id in enumerate(ranking[:cutoff], start=1) if doc_id in gold),
                None,
            )
            reciprocal_ranks.append(1.0 / first if first else 0.0)
            dcg = sum(
                1.0 / math.log2(rank + 1)
                for rank, doc_id in enumerate(ranking[:cutoff], start=1)
                if doc_id in gold
            )
            ideal_count = min(len(gold), cutoff)
            ideal_dcg = sum(
                1.0 / math.log2(rank + 1)
                for rank in range(1, ideal_count + 1)
            )
            ndcgs.append(dcg / ideal_dcg)
        metrics[f"mrr@{cutoff}"] = mean(reciprocal_ranks)
        metrics[f"ndcg@{cutoff}"] = mean(ndcgs)
    return metrics

