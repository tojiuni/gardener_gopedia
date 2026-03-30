"""Build per-query payloads for Phoenix OTLP + REST from committed DB rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.metrics_engine import per_query_recall_at_5
from gardener_gopedia.models import DatasetQuery, EvalRun, Qrel, RunHit, RunMetric


def build_per_query_phoenix_payload(
    db: Session,
    *,
    eval_run: EvalRun,
    queries: list[DatasetQuery],
) -> list[dict[str, Any]]:
    """
    One row per dataset query, with IR + any per-query RunMetric (incl. Ragas).

    Keys align with phoenix_adapter + phoenix_sync.
    """
    if not queries:
        return []

    qrels_rows = db.query(Qrel).filter(Qrel.dataset_id == queries[0].dataset_id).all()
    qrels_tuples = [(q.query_id, q.target_id, q.relevance) for q in qrels_rows]
    hits = (
        db.query(RunHit)
        .filter(RunHit.eval_run_id == eval_run.id)
        .order_by(RunHit.dataset_query_id, RunHit.rank)
        .all()
    )
    runs_tuples = [(h.dataset_query_id, h.target_id, h.score) for h in hits]
    per_r = per_query_recall_at_5(qrels_tuples, runs_tuples, preserve_input_order=True)

    metrics_rows = (
        db.query(RunMetric)
        .filter(RunMetric.eval_run_id == eval_run.id, RunMetric.scope == "per_query")
        .all()
    )
    metrics_by_q: dict[str, dict[str, float]] = {}
    for m in metrics_rows:
        if not m.dataset_query_id:
            continue
        metrics_by_q.setdefault(m.dataset_query_id, {})[m.metric_name] = float(m.value)

    hits_by_q: dict[str, list[RunHit]] = {}
    for h in hits:
        hits_by_q.setdefault(h.dataset_query_id, []).append(h)

    out: list[dict[str, Any]] = []
    for dq in queries:
        mets = dict(metrics_by_q.get(dq.id, {}))
        if dq.id in per_r:
            mets.setdefault("Recall@5", float(per_r[dq.id]))
        qhits = hits_by_q.get(dq.id, [])
        err = None
        if not qhits:
            err = "no_hits"
        out.append(
            {
                "dataset_query_id": dq.id,
                "external_id": dq.external_id,
                "tier": dq.tier or "",
                "query_text": dq.query_text,
                "metrics": mets,
                "error": err,
                "hits": [
                    {
                        "rank": h.rank,
                        "target_id": h.target_id,
                        "target_type": h.target_type,
                        "score": h.score,
                        "title": h.title,
                        "snippet": (h.snippet or "")[:500] if h.snippet else None,
                    }
                    for h in qhits
                ],
            }
        )
    return out
