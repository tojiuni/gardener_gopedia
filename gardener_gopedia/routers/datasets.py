from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from gardener_gopedia.db import get_session
from gardener_gopedia.models import Dataset, DatasetQuery, Qrel
from gardener_gopedia.schemas import DatasetCreate, DatasetOut, QrelInput, QueryInput

router = APIRouter()


@router.post("", response_model=DatasetOut)
def create_dataset(body: DatasetCreate, db: Session = Depends(get_session)):
    ds = Dataset(name=body.name, version=body.version)
    db.add(ds)
    db.flush()

    ext_to_id: dict[str, str] = {}
    for q in body.queries:
        dq = DatasetQuery(
            dataset_id=ds.id,
            external_id=q.external_id,
            query_text=q.text,
            project_id=q.project_id,
        )
        db.add(dq)
        db.flush()
        ext_to_id[q.external_id] = dq.id

    for qr in body.qrels:
        qid = ext_to_id.get(qr.query_external_id)
        if not qid:
            raise HTTPException(400, f"unknown query_external_id: {qr.query_external_id}")
        db.add(
            Qrel(
                dataset_id=ds.id,
                query_id=qid,
                target_id=qr.target_id,
                target_type=qr.target_type,
                relevance=qr.relevance,
            )
        )

    db.commit()
    db.refresh(ds)
    return DatasetOut(
        id=ds.id,
        name=ds.name,
        version=ds.version,
        created_at=ds.created_at,
        query_count=len(body.queries),
    )


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
                )
            )
        elif "query_external_id" in row and "target_id" in row:
            qrel_rows.append(
                QrelInput(
                    query_external_id=row["query_external_id"],
                    target_id=row["target_id"],
                    target_type=row.get("target_type", "l3_id"),
                    relevance=row.get("relevance", 1),
                )
            )
        else:
            raise HTTPException(400, f"unrecognized jsonl row: {row!r}")

    body = DatasetCreate(name=name, version=version, queries=query_rows, qrels=qrel_rows)
    return create_dataset(body, db)


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_session)):
    out = []
    for ds in db.query(Dataset).order_by(Dataset.created_at.desc()).all():
        n = db.query(DatasetQuery).filter(DatasetQuery.dataset_id == ds.id).count()
        out.append(
            DatasetOut(
                id=ds.id,
                name=ds.name,
                version=ds.version,
                created_at=ds.created_at,
                query_count=n,
            )
        )
    return out


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, db: Session = Depends(get_session)):
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "dataset not found")
    n = db.query(DatasetQuery).filter(DatasetQuery.dataset_id == ds.id).count()
    return DatasetOut(
        id=ds.id,
        name=ds.name,
        version=ds.version,
        created_at=ds.created_at,
        query_count=n,
    )
