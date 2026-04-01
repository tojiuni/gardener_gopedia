import math

from gardener_gopedia.eval.metrics import _finite_metric_float, compute_aggregate_metrics


def test_finite_metric_float_sanitizes_non_finite():
    assert _finite_metric_float(float("nan")) == 0.0
    assert _finite_metric_float(float("inf")) == 0.0
    assert _finite_metric_float(None) == 0.0
    assert _finite_metric_float(0.25) == 0.25


def test_compute_aggregate_empty_qrels_all_finite():
    m = compute_aggregate_metrics([], [("q1", "d1", 1.0)])
    assert set(m.keys()) == {"Recall@5", "MRR@10", "nDCG@10", "P@3"}
    for v in m.values():
        assert math.isfinite(v)
