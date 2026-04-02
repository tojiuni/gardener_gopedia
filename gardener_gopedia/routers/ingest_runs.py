from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from gardener_gopedia.core.config import get_settings
from gardener_gopedia.core.db import get_session
from gardener_gopedia.ingest_service import execute_ingest_run
from gardener_gopedia.core.models import IngestRun, RunStatus
from gardener_gopedia.schemas import IngestRunCreate, IngestRunOut

router = APIRouter()


@router.post("", response_model=IngestRunOut)
def start_ingest(
    body: IngestRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    settings = get_settings()
    row = IngestRun(
        target_url=body.target_url or settings.gopedia_base_url,
        source_path=body.source_path,
        ingest_mode=body.mode,
        idempotency_key=body.idempotency_key,
        project_id=body.project_id,
        status=RunStatus.pending.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    background_tasks.add_task(_run_ingest, row.id)
    return row


def _run_ingest(ingest_run_id: str) -> None:
    from gardener_gopedia.core.db import get_engine
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=get_engine())
    s = SessionLocal()
    try:
        execute_ingest_run(s, ingest_run_id)
    finally:
        s.close()


@router.get("", response_model=list[IngestRunOut])
def list_ingest(limit: int = 50, db: Session = Depends(get_session)):
    rows = db.query(IngestRun).order_by(IngestRun.id.desc()).limit(min(limit, 200)).all()
    return rows


@router.get("/{ingest_run_id}", response_model=IngestRunOut)
def get_ingest(ingest_run_id: str, db: Session = Depends(get_session)):
    row = db.get(IngestRun, ingest_run_id)
    if not row:
        raise HTTPException(404, "ingest run not found")
    return row


@router.post("/{ingest_run_id}/wait", response_model=IngestRunOut)
def wait_ingest(ingest_run_id: str, db: Session = Depends(get_session)):
    """Blocking wait for background ingest (for tests); prefer async poll via GET."""
    row = db.get(IngestRun, ingest_run_id)
    if not row:
        raise HTTPException(404, "ingest run not found")
    if row.status == RunStatus.pending.value:
        execute_ingest_run(db, ingest_run_id)
        db.refresh(row)
    return row
