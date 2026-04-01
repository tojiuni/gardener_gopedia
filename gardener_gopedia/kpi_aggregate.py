"""Persist aggregate quality/cost/token KPIs for `GET /runs/{id}/kpi-summary`."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.core.models import DatasetQuery, EvalRun, RunMetric
from gardener_gopedia.observability_contract import (
    IR_RECALL_AT_5,
    SUMMARY_COST_TOTAL_USD,
    SUMMARY_QUALITY_SCORE,
    SUMMARY_TOTAL_TOKENS,
)
from gardener_gopedia.observability_payload import build_per_query_observability_payload


def _numeric(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return float(v)
    return None


def persist_run_summary_kpis(db: Session, eval_run: EvalRun, dataset_id: str) -> None:
    """Replace summary/* aggregate metrics for this run from committed per-query data."""
    queries = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == dataset_id)
        .order_by(DatasetQuery.external_id)
        .all()
    )
    per_query = build_per_query_observability_payload(db, eval_run=eval_run, queries=queries)

    for name in (SUMMARY_TOTAL_TOKENS, SUMMARY_COST_TOTAL_USD, SUMMARY_QUALITY_SCORE):
        db.query(RunMetric).filter(
            RunMetric.eval_run_id == eval_run.id,
            RunMetric.metric_name == name,
            RunMetric.scope == "aggregate",
        ).delete(synchronize_session=False)

    total_tokens = 0
    total_cost = 0.0
    recalls: list[float] = []
    for row in per_query:
        u = row.get("usage") or {}
        if isinstance(u, dict):
            total_tokens += int(u.get("total_tokens") or 0)
        c = row.get("cost_usd") or {}
        if isinstance(c, dict):
            total_cost += float(c.get("total_usd") or 0.0)
        m = row.get("metrics") or {}
        rv = _numeric(m.get(IR_RECALL_AT_5))
        if rv is not None:
            recalls.append(rv)

    def _add_agg(name: str, value: float) -> None:
        db.add(
            RunMetric(
                eval_run_id=eval_run.id,
                metric_name=name,
                value=float(value),
                scope="aggregate",
            )
        )

    _add_agg(SUMMARY_TOTAL_TOKENS, float(total_tokens))
    _add_agg(SUMMARY_COST_TOTAL_USD, float(total_cost))
    if recalls:
        _add_agg(SUMMARY_QUALITY_SCORE, sum(recalls) / len(recalls))
    db.flush()
