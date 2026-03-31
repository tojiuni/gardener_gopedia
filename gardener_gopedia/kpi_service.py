"""Aggregate quality vs cost KPIs for eval runs (API + optimization loop)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.models import Dataset, DatasetQuery, EvalRun, RunMetric
from gardener_gopedia.observability_contract import (
    IR_RECALL_AT_5,
    SUMMARY_COST_TOTAL_USD,
    SUMMARY_QUALITY_SCORE,
    SUMMARY_TOTAL_TOKENS,
)
from gardener_gopedia.observability_payload import build_per_query_observability_payload


def _agg_metrics(db: Session, eval_run_id: str) -> dict[str, float]:
    rows = db.query(RunMetric).filter(RunMetric.eval_run_id == eval_run_id, RunMetric.scope == "aggregate").all()
    return {m.metric_name: float(m.value) for m in rows}


def build_run_kpi_summary(db: Session, eval_run: EvalRun) -> dict[str, Any]:
    """Quality + efficiency roll-up using aggregate RunMetrics when present."""
    agg = _agg_metrics(db, eval_run.id)
    pj = eval_run.params_json or {}
    return {
        "eval_run_id": eval_run.id,
        "quality": {
            "mean_recall_at_5": agg.get(SUMMARY_QUALITY_SCORE) or agg.get(IR_RECALL_AT_5),
            "aggregate_recall_at_5": agg.get(IR_RECALL_AT_5),
        },
        "efficiency": {
            "total_tokens": agg.get(SUMMARY_TOTAL_TOKENS),
            "cost_total_usd": agg.get(SUMMARY_COST_TOTAL_USD),
        },
        "langfuse_trace_url": pj.get("langfuse_trace_url"),
    }


def build_roi_query_rows(
    db: Session,
    eval_run: EvalRun,
    *,
    sort: str = "worst_roi",
    limit: int = 50,
) -> dict[str, Any]:
    """
    Per-query table for cost vs quality. roi_score = (1 - recall) * (1 + cost_usd) * (1 + tokens/10k).
    """
    dataset = db.get(Dataset, eval_run.dataset_id)
    if dataset is None:
        return {"eval_run_id": eval_run.id, "sort": sort, "rows": []}

    queries = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == dataset.id)
        .order_by(DatasetQuery.external_id)
        .all()
    )
    per_q = build_per_query_observability_payload(db, eval_run=eval_run, queries=queries)
    rows_out: list[dict[str, Any]] = []
    for row in per_q:
        mets = row.get("metrics") or {}
        recall = mets.get(IR_RECALL_AT_5)
        if recall is None:
            r = None
        else:
            try:
                r = float(recall)
            except (TypeError, ValueError):
                r = None
        usage = row.get("usage") or {}
        cost = row.get("cost_usd") or {}
        tok = int((usage or {}).get("total_tokens") or 0) if isinstance(usage, dict) else 0
        cusd = float((cost or {}).get("total_usd") or 0) if isinstance(cost, dict) else 0.0
        recall_f = r if r is not None else 0.0
        roi = (1.0 - recall_f) * (1.0 + cusd) * (1.0 + tok / 10_000.0)
        rows_out.append(
            {
                "dataset_query_id": row["dataset_query_id"],
                "external_id": row["external_id"],
                "query_text": row["query_text"],
                "tier": row.get("tier") or None,
                "recall_at_5": r,
                "cost_total_usd": cusd if cusd else None,
                "total_tokens": tok if tok else None,
                "roi_score": float(roi),
            }
        )

    if sort == "highest_cost":
        rows_out.sort(key=lambda x: (x["cost_total_usd"] or 0.0), reverse=True)
    elif sort == "lowest_quality":
        # Missing recall last; then lowest Recall@5 first.
        rows_out.sort(
            key=lambda x: (x["recall_at_5"] is None, x["recall_at_5"] if x["recall_at_5"] is not None else 1.0)
        )
    else:
        rows_out.sort(key=lambda x: x["roi_score"] or 0.0, reverse=True)

    lim = max(1, min(500, limit))
    return {"eval_run_id": eval_run.id, "sort": sort, "rows": rows_out[:lim]}
