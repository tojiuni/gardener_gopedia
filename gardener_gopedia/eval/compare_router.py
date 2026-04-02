from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from gardener_gopedia.core.db import get_session
from gardener_gopedia.eval.metrics import per_query_recall_at_5
from gardener_gopedia.core.models import DatasetQuery, EvalRun, Qrel, RunHit, RunMetric, RunStatus
from gardener_gopedia.schemas import FailureItem

# `ranx` is installed for follow-up statistical comparisons between full ranked lists.

router = APIRouter()


@router.get("")
def compare_runs(
    baseline: str = Query(..., description="eval_run id"),
    candidate: str = Query(..., description="eval_run id"),
    metric: str = Query("Recall@5", description="per-query metric to compare"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_session),
):
    b = db.get(EvalRun, baseline)
    c = db.get(EvalRun, candidate)
    if not b or not c:
        raise HTTPException(404, "baseline or candidate run not found")
    if b.dataset_id != c.dataset_id:
        raise HTTPException(400, "runs must share the same dataset")

    if b.status != RunStatus.completed.value or c.status != RunStatus.completed.value:
        raise HTTPException(400, "both runs must be completed")

    # Aggregate deltas from stored metrics
    def agg_metrics(run_id: str) -> dict[str, float]:
        rows = (
            db.query(RunMetric)
            .filter(RunMetric.eval_run_id == run_id, RunMetric.scope == "aggregate")
            .all()
        )
        return {m.metric_name: m.value for m in rows}

    agg_b = agg_metrics(baseline)
    agg_c = agg_metrics(candidate)
    agg_delta = {k: agg_c.get(k, 0.0) - agg_b.get(k, 0.0) for k in set(agg_b) | set(agg_c)}

    # Rebuild per-query recall from hits + qrels for regression list
    qrels_rows = db.query(Qrel).filter(Qrel.dataset_id == b.dataset_id).all()
    qrels_tuples = [
        (q.query_id, q.target_id, q.relevance)
        for q in qrels_rows
        if q.target_id and str(q.target_id).strip()
    ]

    def run_tuples(run_id: str) -> list[tuple[str, str, float]]:
        hits = (
            db.query(RunHit)
            .filter(RunHit.eval_run_id == run_id)
            .order_by(RunHit.dataset_query_id, RunHit.rank)
            .all()
        )
        return [(h.dataset_query_id, h.target_id, h.score) for h in hits]

    per_b = per_query_recall_at_5(qrels_tuples, run_tuples(baseline), preserve_input_order=True)
    per_c = per_query_recall_at_5(qrels_tuples, run_tuples(candidate), preserve_input_order=True)

    regressions: list[FailureItem] = []
    for qid in per_b:
        vb = per_b.get(qid, 0.0)
        vc = per_c.get(qid, 0.0)
        delta = vc - vb
        if delta < 0:
            dq = db.get(DatasetQuery, qid)
            regressions.append(
                FailureItem(
                    dataset_query_id=qid,
                    external_id=dq.external_id if dq else qid,
                    query_text=dq.query_text if dq else "",
                    baseline_metric=vb,
                    candidate_metric=vc,
                    delta=delta,
                )
            )

    regressions.sort(key=lambda x: x.delta or 0.0)
    regressions = regressions[:limit]

    ranx_note = "optional: use ranx.compare for statistical tests in a follow-up"

    return {
        "baseline": baseline,
        "candidate": candidate,
        "aggregate_baseline": agg_b,
        "aggregate_candidate": agg_c,
        "aggregate_delta": agg_delta,
        "worst_regressions": [r.model_dump() for r in regressions],
        "note": ranx_note,
    }
