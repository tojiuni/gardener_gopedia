"""IR metrics using ir_measures; fallback to manual if unavailable."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable


def _finite_metric_float(x: float | int | None) -> float:
    """SQLite/SQLAlchemy may map NaN to NULL; keep metrics persistable."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if not math.isfinite(v) else v

try:
    import ir_measures as im
    from ir_measures import Qrel, ScoredDoc, calc_aggregate

    _MEASURE_SPECS = [
        (im.R @ 5, "Recall@5"),
        (im.MRR @ 10, "MRR@10"),
        (im.nDCG @ 10, "nDCG@10"),
        (im.P @ 3, "P@3"),
    ]
    _HAS_IR = True
except ImportError:
    _HAS_IR = False
    im = None  # type: ignore[assignment]
    Qrel = None  # type: ignore[misc, assignment]
    ScoredDoc = None  # type: ignore[misc, assignment]
    calc_aggregate = None  # type: ignore[misc, assignment]
    _MEASURE_SPECS = []

METRIC_NAMES = ["Recall@5", "MRR@10", "nDCG@10", "P@3"]


def _manual_recall_at_k(
    relevant_by_q: dict[str, set[str]], ranked_by_q: dict[str, list[str]], k: int
) -> float:
    if not relevant_by_q:
        return 0.0
    total = 0.0
    for qid, rel in relevant_by_q.items():
        if not rel:
            continue
        ranked = ranked_by_q.get(qid, [])[:k]
        hit = len(rel.intersection(ranked))
        total += hit / len(rel)
    return total / len(relevant_by_q)


def _manual_mrr(relevant_by_q: dict[str, set[str]], ranked_by_q: dict[str, list[str]], k: int) -> float:
    if not relevant_by_q:
        return 0.0
    rr_sum = 0.0
    n = 0
    for qid, rel in relevant_by_q.items():
        if not rel:
            continue
        n += 1
        for i, doc in enumerate(ranked_by_q.get(qid, [])[:k], start=1):
            if doc in rel:
                rr_sum += 1.0 / i
                break
    return rr_sum / n if n else 0.0


def _manual_ndcg_at_k(
    relevant_by_q: dict[str, set[str]], ranked_by_q: dict[str, list[str]], k: int
) -> float:
    import math

    def dcg(ranks: list[str], rel: set[str]) -> float:
        s = 0.0
        for i, d in enumerate(ranks[:k], start=1):
            if d in rel:
                s += 1.0 / math.log2(i + 1)
        return s

    if not relevant_by_q:
        return 0.0
    total = 0.0
    for qid, rel in relevant_by_q.items():
        if not rel:
            continue
        ranked = ranked_by_q.get(qid, [])
        ideal_hits = min(len(rel), k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
        if idcg <= 0:
            continue
        total += dcg(ranked, rel) / idcg
    return total / len(relevant_by_q)


def _manual_p_at_k(
    relevant_by_q: dict[str, set[str]], ranked_by_q: dict[str, list[str]], k: int
) -> float:
    if not relevant_by_q:
        return 0.0
    total = 0.0
    for qid, rel in relevant_by_q.items():
        if not rel:
            continue
        ranked = ranked_by_q.get(qid, [])[:k]
        hit = 1.0 if rel.intersection(ranked) else 0.0
        total += hit
    return total / len(relevant_by_q)


def _build_ranked_by_q(
    runs_list: list[tuple[str, str, float]],
) -> dict[str, list[str]]:
    ranked_by_q: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for q, d, s in sorted(runs_list, key=lambda x: (-x[2], x[1])):
        if d not in seen[q]:
            ranked_by_q[q].append(d)
            seen[q].add(d)
    return ranked_by_q


def compute_aggregate_metrics(
    qrels: Iterable[tuple[str, str, int]],
    runs: Iterable[tuple[str, str, float]],
) -> dict[str, float]:
    """
    qrels: (query_id, doc_id, relevance)
    runs: (query_id, doc_id, score) ordered by score desc per query when built upstream
    """
    qrels_list = list(qrels)
    runs_list = list(runs)

    if _HAS_IR and calc_aggregate and Qrel and ScoredDoc and _MEASURE_SPECS:
        qrel_objs = [Qrel(query_id=q, doc_id=d, relevance=r) for q, d, r in qrels_list]
        run_objs = [ScoredDoc(query_id=q, doc_id=d, score=s) for q, d, s in runs_list]
        measures = [m for m, _ in _MEASURE_SPECS]
        try:
            raw = calc_aggregate(measures, qrel_objs, run_objs)
            out: dict[str, float] = {}
            for (meas, label) in _MEASURE_SPECS:
                if meas in raw:
                    out[label] = _finite_metric_float(raw[meas])
            if len(out) == len(_MEASURE_SPECS):
                return out
        except Exception:
            pass

    rel_by_q: dict[str, set[str]] = defaultdict(set)
    for q, d, r in qrels_list:
        if r > 0:
            rel_by_q[q].add(d)
    ranked_by_q = _build_ranked_by_q(runs_list)

    return {
        "Recall@5": _finite_metric_float(_manual_recall_at_k(rel_by_q, ranked_by_q, 5)),
        "MRR@10": _finite_metric_float(_manual_mrr(rel_by_q, ranked_by_q, 10)),
        "nDCG@10": _finite_metric_float(_manual_ndcg_at_k(rel_by_q, ranked_by_q, 10)),
        "P@3": _finite_metric_float(_manual_p_at_k(rel_by_q, ranked_by_q, 3)),
    }


def _ranked_by_explicit_order(runs_list: list[tuple[str, str, float]]) -> dict[str, list[str]]:
    ranked_by_q: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for q, d, _s in runs_list:
        if d not in seen[q]:
            ranked_by_q[q].append(d)
            seen[q].add(d)
    return ranked_by_q


def per_query_recall_at_5(
    qrels: Iterable[tuple[str, str, int]],
    runs: Iterable[tuple[str, str, float]],
    *,
    preserve_input_order: bool = False,
) -> dict[str, float]:
    rel_by_q: dict[str, set[str]] = defaultdict(set)
    for q, d, r in qrels:
        if r > 0:
            rel_by_q[q].add(d)
    runs_list = list(runs)
    ranked_by_q = (
        _ranked_by_explicit_order(runs_list)
        if preserve_input_order
        else _build_ranked_by_q(runs_list)
    )
    out: dict[str, float] = {}
    k = 5
    for qid, rel in rel_by_q.items():
        if not rel:
            out[qid] = 0.0
            continue
        ranked = ranked_by_q.get(qid, [])[:k]
        out[qid] = _finite_metric_float(len(rel.intersection(ranked)) / len(rel))
    return out
