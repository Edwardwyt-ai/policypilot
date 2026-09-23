import pytest

from tau2.domains.banking_knowledge.retrieval_metrics import evaluate_rankings


def test_evaluate_rankings_uses_standard_recall_mrr_and_ndcg():
    metrics = evaluate_rankings(
        rankings=[["a", "x", "b"], ["x", "c", "y"]],
        gold_sets=[{"a", "b"}, {"c"}],
        cutoffs=(1, 3),
    )

    assert metrics["macro_recall@1"] == pytest.approx(0.25)
    assert metrics["micro_recall@1"] == pytest.approx(1 / 3)
    assert metrics["hit_rate@1"] == pytest.approx(0.5)
    assert metrics["mrr@3"] == pytest.approx(0.75)
    assert metrics["macro_recall@3"] == pytest.approx(1.0)
    assert metrics["micro_recall@3"] == pytest.approx(1.0)
    assert metrics["ndcg@3"] == pytest.approx(
        ((1 + 1 / 2) / (1 + 1 / 1.584962500721156) + (1 / 1.584962500721156))
        / 2
    )


def test_evaluate_rankings_rejects_missing_gold_labels():
    with pytest.raises(ValueError, match="gold document"):
        evaluate_rankings([[]], [set()])
