from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from gardener_gopedia.core.config import get_settings
from gardener_gopedia.core.db import get_session
from gardener_gopedia.dataset.persist import persist_dataset_create
from gardener_gopedia.dataset.presets import load_quality_preset
from gardener_gopedia.eval.service import execute_eval_run
from gardener_gopedia.core.models import (
    Dataset,
    DatasetQuery,
    EvalRun,
    RunHit,
    RunMetric,
    RunStatus,
)
from gardener_gopedia.schemas import EvalRunCreate, EvalRunOut, QueryTopKOut, QrelRankOut, RunMetricOut, eval_run_to_out

router = APIRouter()


@router.post("", response_model=EvalRunOut)
def start_eval(
    body: EvalRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    settings = get_settings()
    preset_key = (body.quality_preset or "").strip()

    if preset_key:
        try:
            dataset_create = load_quality_preset(preset_key)
        except FileNotFoundError as e:
            raise HTTPException(400, str(e)) from e
        ds_row = persist_dataset_create(db, dataset_create)
        dataset_id = ds_row.id
        resolve_before_eval = True
    else:
        did = (body.dataset_id or "").strip()
        if not did or not db.get(Dataset, did):
            raise HTTPException(404, "dataset not found")
        dataset_id = did
        resolve_before_eval = body.resolve_before_eval

    params = {
        "top_k": body.top_k,
        "query_timeout_s": body.query_timeout_s or settings.default_query_timeout_s,
        "skip_if_ingest_failed": body.skip_if_ingest_failed,
        "search_detail": body.search_detail,
        "search_fields": body.search_fields,
        "search_retryable_max_attempts": (
            body.search_retryable_max_attempts
            if body.search_retryable_max_attempts is not None
            else settings.gopedia_search_retryable_max_attempts
        ),
        "ragas_enabled": body.ragas_enabled
        if body.ragas_enabled is not None
        else settings.ragas_enabled,
        "ragas_answer_metrics": body.ragas_answer_metrics
        if body.ragas_answer_metrics is not None
        else settings.ragas_answer_metrics,
        "resolve_before_eval": resolve_before_eval,
    }
    if preset_key:
        params["quality_preset"] = preset_key.lower()

    row = EvalRun(
        dataset_id=dataset_id,
        target_url=body.target_url or settings.gopedia_base_url,
        ingest_run_id=body.ingest_run_id,
        git_sha=body.git_sha,
        index_version=body.index_version,
        params_json=params,
        status=RunStatus.pending.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    background_tasks.add_task(_run_eval, row.id)
    return eval_run_to_out(row)


def _run_eval(eval_run_id: str) -> None:
    from gardener_gopedia.core.db import get_engine
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=get_engine())
    s = SessionLocal()
    try:
        execute_eval_run(s, eval_run_id)
    finally:
        s.close()


@router.get("/{run_id}", response_model=EvalRunOut)
def get_run(run_id: str, db: Session = Depends(get_session)):
    row = db.get(EvalRun, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    return eval_run_to_out(row)


@router.get("/{run_id}/metrics", response_model=list[RunMetricOut])
def get_metrics(run_id: str, db: Session = Depends(get_session)):
    if not db.get(EvalRun, run_id):
        raise HTTPException(404, "run not found")
    rows = db.query(RunMetric).filter(RunMetric.eval_run_id == run_id).all()
    return [
        RunMetricOut(
            metric_name=m.metric_name,
            value=m.value,
            scope=m.scope,
            dataset_query_id=m.dataset_query_id,
            details_json=m.details_json,
        )
        for m in rows
    ]


@router.get("/{run_id}/queries", response_model=list[QueryTopKOut])
def get_queries(run_id: str, db: Session = Depends(get_session)):
    """Return per-query top-k hit list with qrel ranks and per-query metrics."""
    from gardener_gopedia.core.models import Qrel

    er = db.get(EvalRun, run_id)
    if not er:
        raise HTTPException(404, "run not found")

    dqs = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == er.dataset_id)
        .order_by(DatasetQuery.external_id)
        .all()
    )

    # Index per-query metrics by (dataset_query_id, metric_name)
    per_query_metrics: dict[str, dict[str, float]] = {}
    for m in db.query(RunMetric).filter(
        RunMetric.eval_run_id == run_id, RunMetric.scope == "per_query"
    ).all():
        if m.dataset_query_id:
            per_query_metrics.setdefault(m.dataset_query_id, {})[m.metric_name] = float(m.value)

    # Index qrels: query_id → list of (target_id, relevance)
    qrels_by_query: dict[str, list[tuple[str, int]]] = {}
    for qr in db.query(Qrel).filter(Qrel.dataset_id == er.dataset_id).all():
        tid = (qr.target_id or "").strip()
        if tid:
            qrels_by_query.setdefault(qr.query_id, []).append((tid, int(qr.relevance)))

    out: list[QueryTopKOut] = []
    for dq in dqs:
        hits = (
            db.query(RunHit)
            .filter(RunHit.eval_run_id == run_id, RunHit.dataset_query_id == dq.id)
            .order_by(RunHit.rank)
            .all()
        )

        # Build ordered list of l3_ids from hits (1-based rank = index+1)
        top_k_hits: list[str] = [h.target_id for h in hits]
        hit_rank_map: dict[str, int] = {h.target_id: h.rank for h in hits}

        # Build qrel entries with rank in top_k_hits
        qrel_entries: list[QrelRankOut] = [
            QrelRankOut(
                l3_id=tid,
                relevance=rel,
                rank=hit_rank_map.get(tid),  # None if not in hits
            )
            for tid, rel in qrels_by_query.get(dq.id, [])
        ]

        qm = per_query_metrics.get(dq.id, {})
        out.append(
            QueryTopKOut(
                dataset_query_id=dq.id,
                query=dq.query_text,
                top_k_hits=top_k_hits,
                qrels=qrel_entries,
                recall_at_5=qm.get("Recall@5"),
                precision_at_3=qm.get("P@3"),
            )
        )
    return out


@router.get("/{run_id}/details")
def get_run_details(run_id: str, db: Session = Depends(get_session)):
    """
    Per-query summary for debugging: Recall@5 and top-1 hit id (l3 when applicable).
    Compatible with scripts that expect rows[].query_external_id, recall_at_5, top1_l3_id.
    """
    er = db.get(EvalRun, run_id)
    if not er:
        raise HTTPException(404, "run not found")

    recall_rows = (
        db.query(RunMetric)
        .filter(
            RunMetric.eval_run_id == run_id,
            RunMetric.scope == "per_query",
            RunMetric.metric_name == "Recall@5",
        )
        .all()
    )
    recall_by_q = {m.dataset_query_id: float(m.value) for m in recall_rows if m.dataset_query_id}

    dqs = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == er.dataset_id)
        .order_by(DatasetQuery.external_id)
        .all()
    )

    rows: list[dict] = []
    for dq in dqs:
        qhits = (
            db.query(RunHit)
            .filter(RunHit.eval_run_id == run_id, RunHit.dataset_query_id == dq.id)
            .order_by(RunHit.rank)
            .all()
        )
        top = qhits[0] if qhits else None
        top1_l3_id = None
        if top is not None:
            tt = (top.target_type or "l3_id").lower()
            if tt == "l3_id":
                top1_l3_id = top.target_id
        rows.append(
            {
                "query_external_id": dq.external_id,
                "query_text": dq.query_text,
                "recall_at_5": recall_by_q.get(dq.id),
                "top1_l3_id": top1_l3_id,
                "top1_target_id": top.target_id if top else None,
                "top1_target_type": top.target_type if top else None,
                "top1_title": top.title if top else None,
            }
        )

    return {"eval_run_id": run_id, "rows": rows}


@router.post("/{run_id}/wait", response_model=EvalRunOut)
def wait_run(run_id: str, db: Session = Depends(get_session)):
    row = db.get(EvalRun, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    # Poll only: POST /runs schedules BackgroundTasks; do not call execute_eval_run here (races duplicate metrics).
    deadline = time.monotonic() + 3600.0
    while (
        row.status not in (RunStatus.completed.value, RunStatus.failed.value)
        and time.monotonic() < deadline
    ):
        db.expire(row)
        row = db.get(EvalRun, run_id)
        if not row:
            raise HTTPException(404, "run not found")
        time.sleep(0.2)
    if row.status not in (RunStatus.completed.value, RunStatus.failed.value):
        raise HTTPException(504, "eval run did not finish before timeout")
    return eval_run_to_out(row)
