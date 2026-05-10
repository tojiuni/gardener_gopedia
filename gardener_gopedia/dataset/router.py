from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from gardener_gopedia.core.db import get_session
from gardener_gopedia.core.models import Dataset, DatasetQuery
from gardener_gopedia.dataset.persist import persist_dataset_create
from gardener_gopedia.eval.qrel_resolve import resolve_dataset_qrels
from gardener_gopedia.schemas import (
    DatasetCreate,
    DatasetOut,
    IngestCompletePayload,
    QrelInput,
    QueryInput,
    ResolveQrelsResult,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _dataset_out(db: Session, ds: Dataset) -> DatasetOut:
    n = db.query(DatasetQuery).filter(DatasetQuery.dataset_id == ds.id).count()
    return DatasetOut(
        id=ds.id,
        name=ds.name,
        version=ds.version,
        created_at=ds.created_at,
        query_count=n,
        curation_tier=getattr(ds, "curation_tier", None) or "bronze",
        parent_dataset_id=getattr(ds, "parent_dataset_id", None),
        promoted_from_batch_id=getattr(ds, "promoted_from_batch_id", None),
    )


@router.post("", response_model=DatasetOut)
def create_dataset(body: DatasetCreate, db: Session = Depends(get_session)):
    ds = persist_dataset_create(db, body)
    return _dataset_out(db, ds)


@router.post("/upload-jsonl", response_model=DatasetOut)
async def upload_jsonl(
    name: str,
    version: str = "1",
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    """
    Each line is either a query or a qrel:
    - Query: {"external_id":"q1","text":"...","project_id":2}
    - Qrel: {"query_external_id":"q1","target_id":"uuid","target_type":"l3_id","relevance":1}
    - Qrel (agent): {"query_external_id":"q1","target_data":{"excerpt":"...","source_path_hint":"..."},"relevance":1}
    """
    raw = (await file.read()).decode("utf-8")
    query_rows: list[QueryInput] = []
    qrel_rows: list[QrelInput] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if "text" in row and "external_id" in row:
            query_rows.append(
                QueryInput(
                    external_id=row["external_id"],
                    text=row["text"],
                    project_id=row.get("project_id"),
                    tier=row.get("tier"),
                    reference_answer=row.get("reference_answer"),
                )
            )
        elif "query_external_id" in row and (
            "target_id" in row or row.get("target_data")
        ):
            qrel_rows.append(
                QrelInput(
                    query_external_id=row["query_external_id"],
                    target_id=row.get("target_id"),
                    target_type=row.get("target_type", "l3_id"),
                    relevance=row.get("relevance", 1),
                    target_data=row.get("target_data"),
                )
            )
        else:
            raise HTTPException(400, f"unrecognized jsonl row: {row!r}")

    body = DatasetCreate(name=name, version=version, queries=query_rows, qrels=qrel_rows)
    return create_dataset(body, db)


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_session)):
    return [_dataset_out(db, ds) for ds in db.query(Dataset).order_by(Dataset.created_at.desc()).all()]


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, db: Session = Depends(get_session)):
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "dataset not found")
    return _dataset_out(db, ds)


@router.post("/{dataset_id}/resolve-qrels", response_model=ResolveQrelsResult)
def post_resolve_qrels(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-resolve all qrels that have target_data"),
    target_url: str | None = Query(None, description="Override Gopedia base URL"),
    background: bool = Query(
        False,
        description=(
            "Return immediately (202) and resolve in the background. "
            "Poll dataset qrel counts to check completion."
        ),
    ),
    db: Session = Depends(get_session),
):
    from gardener_gopedia.core.config import get_settings

    if not db.get(Dataset, dataset_id):
        raise HTTPException(404, "dataset not found")
    settings = get_settings()
    base = (target_url or "").strip() or settings.gopedia_base_url

    if background:
        background_tasks.add_task(_resolve_qrels_bg, dataset_id, base, force)
        return ResolveQrelsResult(
            dataset_id=dataset_id,
            attempted=0,
            resolved=0,
            ambiguous=0,
            failed=0,
            message="resolve-qrels started in background",
            background=True,
        )

    out = resolve_dataset_qrels(db, dataset_id, base, force=force)
    return ResolveQrelsResult(**out)


def _resolve_qrels_bg(dataset_id: str, base_url: str, force: bool) -> None:
    """Background task: resolve qrels without holding an HTTP connection."""
    from gardener_gopedia.core.db import get_engine
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=get_engine())
    s = SessionLocal()
    try:
        result = resolve_dataset_qrels(s, dataset_id, base_url, force=force)
        logger.info(
            "resolve-qrels bg completed dataset_id=%s resolved=%d ambiguous=%d failed=%d",
            dataset_id,
            result.get("resolved", 0),
            result.get("ambiguous", 0),
            result.get("failed", 0),
        )
    except Exception:
        logger.exception("resolve-qrels bg failed dataset_id=%s", dataset_id)
    finally:
        s.close()


@router.post("/ingest-complete", status_code=202)
def ingest_complete_webhook(
    body: IngestCompletePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    """
    Webhook called by gopedia when an ingest job completes.

    Automatically triggers background resolve-qrels for all datasets that have
    unresolved qrels (target_data entries without a target_id).  Only datasets
    whose qrels target the same gopedia URL are resolved; others are skipped.

    gopedia sets GARDENER_WEBHOOK_URL to point here.  The endpoint returns 202
    immediately — resolution happens in the background.
    """
    from gardener_gopedia.core.config import get_settings
    from gardener_gopedia.eval.qrel_resolve import dataset_has_unresolved_qrels

    if body.status != "completed":
        logger.info(
            "ingest-complete webhook: status=%s job=%s — skipping resolve",
            body.status,
            body.ingest_job_id,
        )
        return {"queued": 0, "message": f"skipped (status={body.status})"}

    settings = get_settings()
    base = body.target_url.strip() or settings.gopedia_base_url
    logger.info(
        "ingest-complete webhook: job=%s target_url=%s — scanning datasets",
        body.ingest_job_id,
        base,
    )

    datasets = db.query(Dataset).all()
    queued: list[str] = []
    for ds in datasets:
        if dataset_has_unresolved_qrels(db, ds.id):
            background_tasks.add_task(_resolve_qrels_bg, ds.id, base, False)
            queued.append(ds.id)
            logger.info("queued resolve-qrels for dataset_id=%s", ds.id)

    return {"queued": len(queued), "dataset_ids": queued, "target_url": base}
