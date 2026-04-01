from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from gardener_gopedia.config import get_settings
from gardener_gopedia.db import get_session
from gardener_gopedia.evaluation_service import execute_eval_run
from gardener_gopedia.models import (
    Dataset,
    DatasetQuery,
    EvalRun,
    RunHit,
    RunMetric,
    RunRagasSample,
    RunStatus,
)
from gardener_gopedia.schemas import EvalRunCreate, EvalRunOut, QueryResultOut, RunMetricOut, eval_run_to_out

router = APIRouter()


@router.post("", response_model=EvalRunOut)
def start_eval(
    body: EvalRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    if not db.get(Dataset, body.dataset_id):
        raise HTTPException(404, "dataset not found")

    settings = get_settings()
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
        "resolve_before_eval": body.resolve_before_eval,
    }
    row = EvalRun(
        dataset_id=body.dataset_id,
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
    from gardener_gopedia.db import get_engine
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


@router.get("/{run_id}/queries", response_model=list[QueryResultOut])
def get_queries(run_id: str, db: Session = Depends(get_session)):
    er = db.get(EvalRun, run_id)
    if not er:
        raise HTTPException(404, "run not found")

    dqs = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == er.dataset_id)
        .order_by(DatasetQuery.external_id)
        .all()
    )
    metrics = db.query(RunMetric).filter(RunMetric.eval_run_id == run_id, RunMetric.scope == "per_query").all()
    m_by_q: dict[str, list[RunMetricOut]] = {}
    for m in metrics:
        if m.dataset_query_id:
            m_by_q.setdefault(m.dataset_query_id, []).append(
                RunMetricOut(
                    metric_name=m.metric_name,
                    value=m.value,
                    scope=m.scope,
                    dataset_query_id=m.dataset_query_id,
                    details_json=m.details_json,
                )
            )

    ragas_by_q: dict[str, str | None] = {}
    for rs in (
        db.query(RunRagasSample)
        .filter(RunRagasSample.eval_run_id == run_id)
        .all()
    ):
        ragas_by_q[rs.dataset_query_id] = rs.generated_response

    from gardener_gopedia.models import Qrel

    qrels_by_query: dict[str, set[str]] = {}
    for qr in db.query(Qrel).filter(Qrel.dataset_id == er.dataset_id).all():
        tid = (qr.target_id or "").strip()
        if tid:
            qrels_by_query.setdefault(qr.query_id, set()).add(tid)

    out: list[QueryResultOut] = []
    for dq in dqs:
        relevant_ids = qrels_by_query.get(dq.id, set())
        hits = (
            db.query(RunHit)
            .filter(RunHit.eval_run_id == run_id, RunHit.dataset_query_id == dq.id)
            .order_by(RunHit.rank)
            .all()
        )
        hit_dicts = [
            {
                "rank": h.rank,
                "target_id": h.target_id,
                "target_type": h.target_type,
                "score": h.score,
                "title": h.title,
                "snippet": h.snippet,
                "is_relevant": h.target_id in relevant_ids,
            }
            for h in hits
        ]
        out.append(
            QueryResultOut(
                dataset_query_id=dq.id,
                external_id=dq.external_id,
                query_text=dq.query_text,
                tier=dq.tier,
                reference_answer=dq.reference_answer,
                metrics=m_by_q.get(dq.id, []),
                hits=hit_dicts,
                ragas_generated_response=ragas_by_q.get(dq.id),
            )
        )
    return out


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
