"""Execute eval runs: search Gopedia, persist hits, compute metrics."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from gardener_gopedia.config import get_settings
from gardener_gopedia.gopedia_client import GopediaClient, gopedia_json_search_failed
from gardener_gopedia.metrics_engine import compute_aggregate_metrics, per_query_recall_at_5
from gardener_gopedia.models import DatasetQuery, EvalRun, Qrel, RunHit, RunMetric, RunStatus
from gardener_gopedia.qrel_resolve_service import (
    dataset_has_unresolved_qrels,
    resolve_dataset_qrels,
)

logger = logging.getLogger(__name__)


def _strip_opt(s: str | None) -> str | None:
    if s is None:
        return None
    t = str(s).strip()
    return t or None


def _search_with_retry(
    client: GopediaClient,
    *,
    q: str,
    project_id: int | None,
    detail: str | None,
    fields: str | None,
    max_attempts: int,
) -> dict:
    max_attempts = max(1, max_attempts)
    data: dict = {}
    for attempt in range(max_attempts):
        req_id = str(uuid.uuid4())
        data = client.search_json(
            q,
            project_id,
            detail=detail,
            fields=fields,
            request_id=req_id,
        )
        if not gopedia_json_search_failed(data):
            break
        failure = data.get("failure")
        if (
            isinstance(failure, dict)
            and failure.get("retryable")
            and attempt < max_attempts - 1
        ):
            time.sleep(min(8.0, 0.5 * (2**attempt)))
            continue
        break
    return data


def execute_eval_run(db: Session, eval_run_id: str) -> None:
    row = (
        db.query(EvalRun)
        .options(selectinload(EvalRun.dataset))  # type: ignore[arg-type]
        .filter(EvalRun.id == eval_run_id)
        .first()
    )
    if not row:
        return
    db.refresh(row)
    if row.status in (RunStatus.completed.value, RunStatus.failed.value):
        return

    skip_on_ingest = True
    if row.params_json is not None:
        skip_on_ingest = row.params_json.get("skip_if_ingest_failed", True)

    if row.ingest_run_id and skip_on_ingest:
        from gardener_gopedia.models import IngestRun

        ing = db.get(IngestRun, row.ingest_run_id)
        if ing and ing.status != RunStatus.completed.value:
            row.status = RunStatus.failed.value
            row.error_message = f"ingest_run not completed: status={ing.status}"
            row.ended_at = datetime.utcnow()
            db.commit()
            return

    settings = get_settings()
    params = row.params_json or {}
    top_k = int(params.get("top_k", settings.default_top_k))
    timeout_s = float(params.get("query_timeout_s", settings.default_query_timeout_s))
    detail = _strip_opt(params.get("search_detail")) or _strip_opt(settings.gopedia_search_detail)
    fields = _strip_opt(params.get("search_fields")) or _strip_opt(settings.gopedia_search_fields)
    max_attempts = int(
        params.get("search_retryable_max_attempts", settings.gopedia_search_retryable_max_attempts)
    )

    dataset = row.dataset
    queries = (
        db.query(DatasetQuery).filter(DatasetQuery.dataset_id == dataset.id).order_by(DatasetQuery.external_id).all()
    )
    base = row.target_url or settings.gopedia_base_url
    if params.get("resolve_before_eval"):
        resolve_dataset_qrels(db, dataset.id, base, force=False)

    qrels_rows = db.query(Qrel).filter(Qrel.dataset_id == dataset.id).all()
    if dataset_has_unresolved_qrels(db, dataset.id):
        row.status = RunStatus.failed.value
        row.error_message = (
            "dataset has qrels without target_id (unresolved target_data). "
            "POST /datasets/{id}/resolve-qrels or pass resolve_before_eval=true on the eval run."
        )
        row.ended_at = datetime.utcnow()
        db.commit()
        return

    qrels_by_query: dict[str, list[Qrel]] = {}
    for q in qrels_rows:
        qrels_by_query.setdefault(q.query_id, []).append(q)

    row.status = RunStatus.running.value
    row.started_at = datetime.utcnow()
    db.commit()

    client = GopediaClient(base, timeout_s=max(timeout_s, 60.0))

    qrels_tuples: list[tuple[str, str, int]] = []
    runs_tuples: list[tuple[str, str, float]] = []

    failures = 0
    try:
        for dq in queries:
            for qr in qrels_by_query.get(dq.id, []):
                tid = (qr.target_id or "").strip()
                if tid:
                    qrels_tuples.append((dq.id, tid, qr.relevance))

            data = _search_with_retry(
                client,
                q=dq.query_text,
                project_id=dq.project_id,
                detail=detail,
                fields=fields,
                max_attempts=max_attempts,
            )
            latency = data.pop("_latency_ms", None)
            req_id = data.get("request_id")

            if gopedia_json_search_failed(data):
                failures += 1
                continue

            results = data["results"]
            for rank, hit in enumerate(results[:top_k], start=1):
                prefer = "l3_id"
                qrs = qrels_by_query.get(dq.id, [])
                if qrs and all(q.target_type == "doc_id" for q in qrs):
                    prefer = "doc_id"
                tid = hit.get("l3_id") or ""
                if prefer == "doc_id":
                    tid = hit.get("doc_id") or tid
                if not tid:
                    continue
                rh = RunHit(
                    eval_run_id=row.id,
                    dataset_query_id=dq.id,
                    rank=rank,
                    target_id=tid,
                    target_type="doc_id" if prefer == "doc_id" else "l3_id",
                    score=float(hit.get("score", 0.0)),
                    title=hit.get("title"),
                    snippet=hit.get("snippet"),
                    latency_ms=latency,
                    request_id=req_id,
                )
                db.add(rh)
                runs_tuples.append((dq.id, tid, float(hit.get("score", 0.0))))

        db.commit()

        agg = compute_aggregate_metrics(qrels_tuples, runs_tuples)
        for name, val in agg.items():
            db.add(RunMetric(eval_run_id=row.id, metric_name=name, value=float(val), scope="aggregate"))

        per_q = per_query_recall_at_5(qrels_tuples, runs_tuples)
        for qid, val in per_q.items():
            db.add(
                RunMetric(
                    eval_run_id=row.id,
                    metric_name="Recall@5",
                    value=float(val),
                    scope="per_query",
                    dataset_query_id=qid,
                )
            )

        ragas_extra: dict = {}
        try:
            from gardener_gopedia.ragas_service import maybe_run_ragas_after_eval

            ragas_extra = maybe_run_ragas_after_eval(db, row)
        except Exception:
            logger.exception("Ragas/Phoenix post-eval hook failed")
            ragas_extra = {"ragas_hook_error": "exception_logged"}

        row.params_json = {
            **(row.params_json or {}),
            "failure_count": failures,
            "query_count": len(queries),
            **ragas_extra,
        }
        # End timestamps for Phoenix experiment runs / OTLP (before Phoenix export).
        row.ended_at = datetime.utcnow()
        try:
            from gardener_gopedia.phoenix_export import run_phoenix_post_eval

            phoenix_extra = run_phoenix_post_eval(db, row, dataset)
            row.params_json = {**(row.params_json or {}), **phoenix_extra}
        except Exception:
            logger.exception("Phoenix post-eval failed")
            row.params_json = {
                **(row.params_json or {}),
                "phoenix_post_eval_error": "exception_logged",
            }
        row.status = RunStatus.completed.value
    except Exception as e:
        row.status = RunStatus.failed.value
        row.error_message = str(e)[:4000]
    finally:
        if row.ended_at is None:
            row.ended_at = datetime.utcnow()
        client.close()
        db.commit()
