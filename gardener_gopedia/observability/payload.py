"""Build per-query observability payloads (DB -> Langfuse / KPI) from committed rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.eval.metrics import per_query_recall_at_5
from gardener_gopedia.core.models import DatasetQuery, EvalRun, Qrel, RunHit, RunMetric
from gardener_gopedia.observability.contract import (
    COST_ANSWER_TOTAL_USD,
    COST_INPUT_USD,
    COST_OUTPUT_USD,
    COST_RAGAS_ESTIMATED_USD,
    COST_TOTAL_USD,
    EFF_ANSWER_INPUT_TOKENS,
    EFF_ANSWER_OUTPUT_TOKENS,
    EFF_INPUT_TOKENS,
    EFF_OUTPUT_TOKENS,
    EFF_RAGAS_ESTIMATED_TOKENS,
    EFF_TOTAL_TOKENS,
    LATENCY_LLM_MS,
    LATENCY_SEARCH_MS,
)


def build_per_query_observability_payload(
    db: Session,
    *,
    eval_run: EvalRun,
    queries: list[DatasetQuery],
) -> list[dict[str, Any]]:
    """
    One row per dataset query: IR + RunMetric (Ragas, efficiency, latency), hits, usage/cost hints.
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

        usage: dict[str, int] = {}
        cost: dict[str, float] = {}
        lat: dict[str, float | None] = {"search": None, "llm": None}

        inp = int(mets.get(EFF_INPUT_TOKENS, 0) or 0)
        out_t = int(mets.get(EFF_OUTPUT_TOKENS, 0) or 0)
        tot = int(mets.get(EFF_TOTAL_TOKENS, 0) or 0)
        rag_est = int(mets.get(EFF_RAGAS_ESTIMATED_TOKENS, 0) or 0)
        ain = int(mets.get(EFF_ANSWER_INPUT_TOKENS, 0) or 0)
        aout = int(mets.get(EFF_ANSWER_OUTPUT_TOKENS, 0) or 0)
        if inp or out_t or tot:
            usage["input_tokens"] = inp
            usage["output_tokens"] = out_t
            usage["total_tokens"] = tot or (inp + out_t)
        elif rag_est or ain or aout:
            # Composite view for Langfuse: split estimated judge work 70/30 prompt/completion.
            usage["input_tokens"] = int(rag_est * 0.7) + ain
            usage["output_tokens"] = int(rag_est * 0.3) + aout
            usage["total_tokens"] = rag_est + ain + aout

        ci = float(mets.get(COST_INPUT_USD, 0) or 0)
        co = float(mets.get(COST_OUTPUT_USD, 0) or 0)
        ct = float(mets.get(COST_TOTAL_USD, 0) or 0)
        crag = float(mets.get(COST_RAGAS_ESTIMATED_USD, 0) or 0)
        cans = float(mets.get(COST_ANSWER_TOTAL_USD, 0) or 0)
        if crag or cans:
            ct = max(ct, crag + cans)
        if ci or co or ct:
            cost["input_usd"] = ci
            cost["output_usd"] = co
            cost["total_usd"] = ct or (ci + co)

        if LATENCY_SEARCH_MS in mets:
            lat["search"] = float(mets[LATENCY_SEARCH_MS])
        elif qhits and qhits[0].latency_ms is not None:
            lat["search"] = float(qhits[0].latency_ms)
        if LATENCY_LLM_MS in mets:
            lat["llm"] = float(mets[LATENCY_LLM_MS])

        out.append(
            {
                "dataset_query_id": dq.id,
                "external_id": dq.external_id,
                "tier": dq.tier or "",
                "query_text": dq.query_text,
                "metrics": mets,
                "error": err,
                "usage": usage or None,
                "cost_usd": cost or None,
                "latency_ms": lat,
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
