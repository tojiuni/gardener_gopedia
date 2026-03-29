from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gardener_gopedia.db import get_session
from gardener_gopedia.models import EvalRun, Review
from gardener_gopedia.schemas import ReviewCreate, ReviewOut

router = APIRouter()


@router.post("", response_model=ReviewOut)
def create_review(body: ReviewCreate, db: Session = Depends(get_session)):
    if not db.get(EvalRun, body.eval_run_id):
        raise HTTPException(404, "eval run not found")
    row = Review(
        eval_run_id=body.eval_run_id,
        dataset_query_id=body.dataset_query_id,
        label=body.label,
        notes=body.notes,
        reviewer=body.reviewer,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[ReviewOut])
def list_reviews(eval_run_id: str | None = None, db: Session = Depends(get_session)):
    q = db.query(Review)
    if eval_run_id:
        q = q.filter(Review.eval_run_id == eval_run_id)
    rows = q.order_by(Review.created_at.desc()).limit(500).all()
    return rows
