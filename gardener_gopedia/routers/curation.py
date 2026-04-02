from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from gardener_gopedia.agent_contract import AgentQueryProposal
from gardener_gopedia.curation_service import (
    apply_human_decision,
    create_batch_with_proposals,
    list_queue,
    promote_batch_to_gold,
)
from gardener_gopedia.core.db import get_session
from gardener_gopedia.core.models import DatasetQuery, LabelDecision, LabelingBatch
from gardener_gopedia.schemas import (
    DatasetOut,
    HumanLabelDecisionBody,
    LabelDecisionOut,
    LabelingBatchCreate,
    LabelingBatchOut,
    PromoteGoldBody,
)

router = APIRouter()


def _batch_out(row: LabelingBatch) -> LabelingBatchOut:
    return LabelingBatchOut(
        id=row.id,
        dataset_id=row.dataset_id,
        source_eval_run_id=row.source_eval_run_id,
        external_key=row.external_key,
        provenance_json=row.provenance_json,
        created_at=row.created_at,
    )


@router.post("/batches", response_model=LabelingBatchOut)
def post_labeling_batch(body: LabelingBatchCreate, db: Session = Depends(get_session)):
    try:
        proposals = [AgentQueryProposal.model_validate(p) for p in body.proposals]
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors()) from e

    try:
        batch = create_batch_with_proposals(
            db,
            dataset_id=body.dataset_id,
            source_eval_run_id=body.source_eval_run_id,
            external_key=body.external_key,
            provenance_json=body.provenance_json,
            proposals=proposals,
            include_unlisted_queries=body.include_unlisted_queries,
        )
    except ValueError as e:
        msg = str(e)
        code = 409 if "external_key" in msg.lower() and "already exists" in msg.lower() else 400
        raise HTTPException(code, detail=msg) from e
    return _batch_out(batch)


@router.get("/batches/{batch_id}", response_model=LabelingBatchOut)
def get_labeling_batch(batch_id: str, db: Session = Depends(get_session)):
    row = db.get(LabelingBatch, batch_id)
    if not row:
        raise HTTPException(404, "batch not found")
    return _batch_out(row)


@router.get("/batches/{batch_id}/queue")
def get_review_queue(
    batch_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
):
    try:
        return list_queue(db, batch_id, limit=limit, offset=offset)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e


@router.post("/batches/{batch_id}/decisions", response_model=LabelDecisionOut)
def post_human_decision(batch_id: str, body: HumanLabelDecisionBody, db: Session = Depends(get_session)):
    try:
        row = apply_human_decision(
            db,
            batch_id,
            dataset_query_id=body.dataset_query_id,
            action=body.action,
            candidate_id=body.candidate_id,
            target_id=body.target_id,
            target_type=body.target_type,
            relevance=body.relevance,
            reviewer=body.reviewer,
            notes=body.notes,
            mirror_review_eval_run_id=body.mirror_review_eval_run_id,
            review_label=body.review_label,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    return LabelDecisionOut(
        id=row.id,
        labeling_batch_id=row.labeling_batch_id,
        dataset_query_id=row.dataset_query_id,
        status=row.status,
        chosen_target_id=row.chosen_target_id,
        chosen_target_type=row.chosen_target_type,
        relevance=row.relevance,
        reviewer=row.reviewer,
        notes=row.notes,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


@router.post("/batches/{batch_id}/promote", response_model=DatasetOut)
def post_promote_gold(batch_id: str, body: PromoteGoldBody, db: Session = Depends(get_session)):
    try:
        gold = promote_batch_to_gold(
            db,
            batch_id,
            new_version=body.new_version,
            name=body.name,
            copy_parent_qrels_when_no_decision_target=body.copy_parent_qrels_when_no_decision_target,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    n = db.query(DatasetQuery).filter(DatasetQuery.dataset_id == gold.id).count()
    return DatasetOut(
        id=gold.id,
        name=gold.name,
        version=gold.version,
        created_at=gold.created_at,
        query_count=n,
        curation_tier=gold.curation_tier,
        parent_dataset_id=gold.parent_dataset_id,
        promoted_from_batch_id=gold.promoted_from_batch_id,
    )


@router.get("/batches/{batch_id}/decisions", response_model=list[LabelDecisionOut])
def list_batch_decisions(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(LabelingBatch, batch_id):
        raise HTTPException(404, "batch not found")
    rows = (
        db.query(LabelDecision)
        .filter(LabelDecision.labeling_batch_id == batch_id)
        .order_by(LabelDecision.created_at)
        .all()
    )
    return [
        LabelDecisionOut(
            id=r.id,
            labeling_batch_id=r.labeling_batch_id,
            dataset_query_id=r.dataset_query_id,
            status=r.status,
            chosen_target_id=r.chosen_target_id,
            chosen_target_type=r.chosen_target_type,
            relevance=r.relevance,
            reviewer=r.reviewer,
            notes=r.notes,
            decided_at=r.decided_at,
            created_at=r.created_at,
        )
        for r in rows
    ]
