"""Persist DatasetCreate to DB (shared by POST /datasets and POST /runs quality_preset)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from gardener_gopedia.core.models import Dataset, DatasetQuery, Qrel
from gardener_gopedia.schemas import DatasetCreate


def persist_dataset_create(db: Session, body: DatasetCreate) -> Dataset:
    """Insert dataset, queries, and qrels — same rows as POST /datasets."""
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
    return ds
