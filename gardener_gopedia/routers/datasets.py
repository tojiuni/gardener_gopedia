from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from gardener_gopedia.db import get_session
from gardener_gopedia.models import Dataset, DatasetQuery, Qrel
from gardener_gopedia.qrel_resolve_service import resolve_dataset_qrels
from gardener_gopedia.schemas import DatasetCreate, DatasetOut, QrelInput, QueryInput, ResolveQrelsResult

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
    ds = Dataset(name=body.name, version=body.version, curation_tier=body.curation_tier)
    db.add(ds)
    db.flush()

    ext_to_id: dict[str, str] = {}
    for q in body.queries:
        dq = DatasetQuery(
            dataset_id=ds.id,
            external_id=q.external_id,
            query_text=q.text,
            project_id=q.project_id,
            tier=q.tier,
            reference_answer=q.reference_answer,
        )
        db.add(dq)
        db.flush()
        ext_to_id[q.external_id] = dq.id

    for qr in body.qrels:
        qid = ext_to_id.get(qr.query_external_id)
        if not qid:
            raise HTTPException(400, f"unknown query_external_id: {qr.query_external_id}")
        tid = (qr.target_id or "").strip() or None
        db.add(
            Qrel(
                dataset_id=ds.id,
                query_id=qid,
                target_id=tid,
                target_type=qr.target_type,
                relevance=qr.relevance,
                target_data=qr.target_data,
                resolution_status="resolved" if tid else "unresolved",
                resolution_meta=None,
            )
        )

    db.commit()
    db.refresh(ds)
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
    force: bool = Query(False, description="Re-resolve all qrels that have target_data"),
    target_url: str | None = Query(None, description="Override Gopedia base URL"),
    db: Session = Depends(get_session),
):
    from gardener_gopedia.config import get_settings

    if not db.get(Dataset, dataset_id):
        raise HTTPException(404, "dataset not found")
    settings = get_settings()
    base = (target_url or "").strip() or settings.gopedia_base_url
    out = resolve_dataset_qrels(db, dataset_id, base, force=force)
    return ResolveQrelsResult(**out)
