"""Labeling batch lifecycle: ingest AI proposals, route auto-accept, human decisions, Gold promotion."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gardener_gopedia.curation.agent_contract import AgentQueryProposal, pick_auto_accept_candidate
from gardener_gopedia.core.config import get_settings
from gardener_gopedia.core.models import (
    Dataset,
    DatasetQuery,
    LabelCandidate,
    LabelDecision,
    LabelingBatch,
    Qrel,
    Review,
)

DECISION_UNRESOLVED = "unresolved"
DECISION_AUTO_ACCEPTED = "auto_accepted"
DECISION_HUMAN_ACCEPTED = "human_accepted"
DECISION_HUMAN_REJECTED = "human_rejected"
DECISION_NO_TARGET = "no_target"


def _evidence_to_json(ev: Any) -> dict | None:
    if ev is None:
        return None
    if isinstance(ev, dict):
        return ev
    return {"raw": str(ev)}


def create_batch_with_proposals(
    db: Session,
    *,
    dataset_id: str,
    source_eval_run_id: str | None,
    external_key: str | None,
    provenance_json: dict | None,
    proposals: list[AgentQueryProposal],
    include_unlisted_queries: bool = False,
) -> LabelingBatch:
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise ValueError("dataset not found")

    ek = (external_key or "").strip() or None
    if ek:
        existing = (
            db.query(LabelingBatch)
            .filter(LabelingBatch.dataset_id == dataset_id, LabelingBatch.external_key == ek)
            .first()
        )
        if existing:
            raise ValueError("labeling batch with this external_key already exists for dataset")

    batch = LabelingBatch(
        dataset_id=dataset_id,
        source_eval_run_id=source_eval_run_id,
        external_key=ek,
        provenance_json=provenance_json,
    )
    db.add(batch)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise ValueError("could not create labeling batch") from e

    settings = get_settings()
    proposal_query_ids = [p.dataset_query_id for p in proposals]
    if len(proposal_query_ids) != len(set(proposal_query_ids)):
        db.rollback()
        raise ValueError("duplicate dataset_query_id in proposals")

    for prop in proposals:
        dq = db.get(DatasetQuery, prop.dataset_query_id)
        if not dq or dq.dataset_id != dataset_id:
            db.rollback()
            raise ValueError(f"unknown or foreign dataset_query_id: {prop.dataset_query_id}")
        rank = 0
        for item in sorted(prop.candidates, key=lambda x: (-x.confidence, x.candidate_rank)):
            db.add(
                LabelCandidate(
                    labeling_batch_id=batch.id,
                    dataset_query_id=prop.dataset_query_id,
                    target_id=item.target_id,
                    target_type=item.target_type,
                    confidence=float(item.confidence),
                    model_name=item.model_name,
                    rationale=item.rationale,
                    evidence_json=_evidence_to_json(item.evidence),
                    candidate_rank=rank,
                )
            )
            rank += 1

        chosen = pick_auto_accept_candidate(
            prop.candidates,
            single_min_conf=settings.label_auto_accept_single_min_confidence,
            consensus_min_models=settings.label_consensus_min_models,
            consensus_min_conf=settings.label_consensus_min_confidence,
        )
        if chosen:
            db.add(
                LabelDecision(
                    labeling_batch_id=batch.id,
                    dataset_query_id=prop.dataset_query_id,
                    status=DECISION_AUTO_ACCEPTED,
                    chosen_target_id=chosen.target_id,
                    chosen_target_type=chosen.target_type,
                    relevance=1,
                    decided_at=datetime.utcnow(),
                )
            )
        else:
            db.add(
                LabelDecision(
                    labeling_batch_id=batch.id,
                    dataset_query_id=prop.dataset_query_id,
                    status=DECISION_UNRESOLVED,
                )
            )

    if include_unlisted_queries:
        all_q = db.query(DatasetQuery).filter(DatasetQuery.dataset_id == dataset_id).all()
        prop_set = set(proposal_query_ids)
        for dq in all_q:
            if dq.id in prop_set:
                continue
            db.add(
                LabelDecision(
                    labeling_batch_id=batch.id,
                    dataset_query_id=dq.id,
                    status=DECISION_UNRESOLVED,
                )
            )

    if ds.curation_tier == "bronze":
        ds.curation_tier = "silver"
    db.commit()
    db.refresh(batch)
    return batch


def list_queue(
    db: Session,
    batch_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    batch = db.get(LabelingBatch, batch_id)
    if not batch:
        raise ValueError("batch not found")

    q = (
        db.query(LabelDecision)
        .filter(
            LabelDecision.labeling_batch_id == batch_id,
            LabelDecision.status == DECISION_UNRESOLVED,
        )
        .order_by(LabelDecision.created_at)
        .offset(offset)
        .limit(limit)
    )
    out: list[dict[str, Any]] = []
    for dec in q.all():
        dq = db.get(DatasetQuery, dec.dataset_query_id)
        cands = (
            db.query(LabelCandidate)
            .filter(
                LabelCandidate.labeling_batch_id == batch_id,
                LabelCandidate.dataset_query_id == dec.dataset_query_id,
            )
            .order_by(LabelCandidate.candidate_rank, LabelCandidate.confidence.desc())
            .all()
        )
        min_conf = min((c.confidence for c in cands), default=1.0)
        out.append(
            {
                "decision_id": dec.id,
                "dataset_query_id": dec.dataset_query_id,
                "external_id": dq.external_id if dq else None,
                "query_text": dq.query_text if dq else "",
                "priority_score": float(min_conf),
                "candidates": [
                    {
                        "id": c.id,
                        "target_id": c.target_id,
                        "target_type": c.target_type,
                        "confidence": c.confidence,
                        "model_name": c.model_name,
                        "rationale": c.rationale,
                        "evidence_json": c.evidence_json,
                        "candidate_rank": c.candidate_rank,
                    }
                    for c in cands
                ],
            }
        )
    out.sort(key=lambda x: x["priority_score"])
    return out


def apply_human_decision(
    db: Session,
    batch_id: str,
    *,
    dataset_query_id: str,
    action: str,
    candidate_id: str | None = None,
    target_id: str | None = None,
    target_type: str | None = None,
    relevance: int = 1,
    reviewer: str | None = None,
    notes: str | None = None,
    mirror_review_eval_run_id: str | None = None,
    review_label: str | None = None,
) -> LabelDecision:
    batch = db.get(LabelingBatch, batch_id)
    if not batch:
        raise ValueError("batch not found")

    dec = (
        db.query(LabelDecision)
        .filter(
            LabelDecision.labeling_batch_id == batch_id,
            LabelDecision.dataset_query_id == dataset_query_id,
        )
        .first()
    )
    if not dec:
        raise ValueError("decision row not found for query in this batch")

    if dec.status not in (DECISION_UNRESOLVED,):
        raise ValueError(f"decision already finalized: {dec.status}")

    now = datetime.utcnow()
    if action == "accept_candidate":
        if not candidate_id:
            raise ValueError("candidate_id required")
        cand = db.get(LabelCandidate, candidate_id)
        if not cand or cand.labeling_batch_id != batch_id or cand.dataset_query_id != dataset_query_id:
            raise ValueError("invalid candidate_id")
        dec.status = DECISION_HUMAN_ACCEPTED
        dec.chosen_target_id = cand.target_id
        dec.chosen_target_type = cand.target_type
        dec.relevance = relevance
        dec.reviewer = reviewer
        dec.notes = notes
        dec.decided_at = now
    elif action == "set_target":
        if not target_id or not target_type:
            raise ValueError("target_id and target_type required")
        dec.status = DECISION_HUMAN_ACCEPTED
        dec.chosen_target_id = target_id
        dec.chosen_target_type = target_type
        dec.relevance = relevance
        dec.reviewer = reviewer
        dec.notes = notes
        dec.decided_at = now
    elif action == "reject":
        dec.status = DECISION_HUMAN_REJECTED
        dec.chosen_target_id = None
        dec.chosen_target_type = None
        dec.reviewer = reviewer
        dec.notes = notes
        dec.decided_at = now
    elif action == "no_target":
        dec.status = DECISION_NO_TARGET
        dec.chosen_target_id = None
        dec.chosen_target_type = None
        dec.reviewer = reviewer
        dec.notes = notes
        dec.decided_at = now
    else:
        raise ValueError(f"unknown action: {action}")

    if mirror_review_eval_run_id:
        from gardener_gopedia.core.models import EvalRun

        if not db.get(EvalRun, mirror_review_eval_run_id):
            raise ValueError("mirror_review_eval_run_id not found")
        lbl = review_label or f"curation_{action}"
        db.add(
            Review(
                eval_run_id=mirror_review_eval_run_id,
                dataset_query_id=dataset_query_id,
                label=lbl,
                notes=notes,
                reviewer=reviewer,
            )
        )

    db.commit()
    db.refresh(dec)
    return dec


def promote_batch_to_gold(
    db: Session,
    batch_id: str,
    *,
    new_version: str,
    name: str | None = None,
    copy_parent_qrels_when_no_decision_target: bool = True,
) -> Dataset:
    batch = db.get(LabelingBatch, batch_id)
    if not batch:
        raise ValueError("batch not found")

    source = db.get(Dataset, batch.dataset_id)
    if not source:
        raise ValueError("source dataset missing")

    decisions = (
        db.query(LabelDecision).filter(LabelDecision.labeling_batch_id == batch_id).all()
    )
    dec_by_q: dict[str, LabelDecision] = {d.dataset_query_id: d for d in decisions}

    all_old_qids = {q.id for q in db.query(DatasetQuery).filter(DatasetQuery.dataset_id == source.id).all()}
    if all_old_qids != set(dec_by_q.keys()):
        raise ValueError(
            "batch does not include a decision for every query in the dataset; "
            "recreate batch with include_unlisted_queries=true or add proposals per query"
        )

    unresolved = [d for d in decisions if d.status == DECISION_UNRESOLVED]
    if unresolved:
        raise ValueError(
            f"cannot promote: {len(unresolved)} queries still unresolved; resolve or use reject/no_target"
        )

    new_name = name.strip() if name and name.strip() else source.name
    prov = {
        "source_dataset_id": source.id,
        "source_dataset_version": source.version,
        "labeling_batch_id": batch_id,
        "source_eval_run_id": batch.source_eval_run_id,
        "promoted_at_utc": datetime.utcnow().isoformat() + "Z",
    }

    gold = Dataset(
        name=new_name,
        version=new_version.strip(),
        curation_tier="gold",
        parent_dataset_id=source.id,
        promoted_from_batch_id=batch_id,
        promotion_provenance_json=prov,
    )
    db.add(gold)
    db.flush()

    old_queries = (
        db.query(DatasetQuery).filter(DatasetQuery.dataset_id == source.id).order_by(DatasetQuery.external_id).all()
    )
    old_id_to_new: dict[str, str] = {}
    for oq in old_queries:
        nq = DatasetQuery(
            dataset_id=gold.id,
            external_id=oq.external_id,
            query_text=oq.query_text,
            project_id=oq.project_id,
            tier=oq.tier,
            reference_answer=oq.reference_answer,
        )
        db.add(nq)
        db.flush()
        old_id_to_new[oq.id] = nq.id

    for oq in old_queries:
        new_qid = old_id_to_new[oq.id]
        dec = dec_by_q.get(oq.id)

        if dec and dec.status in (DECISION_AUTO_ACCEPTED, DECISION_HUMAN_ACCEPTED) and dec.chosen_target_id:
            db.add(
                Qrel(
                    dataset_id=gold.id,
                    query_id=new_qid,
                    target_id=dec.chosen_target_id,
                    target_type=dec.chosen_target_type or "l3_id",
                    relevance=dec.relevance or 1,
                    target_data=None,
                    resolution_status="resolved",
                    resolution_meta=None,
                )
            )
        elif copy_parent_qrels_when_no_decision_target:
            for qr in db.query(Qrel).filter(Qrel.query_id == oq.id).all():
                db.add(
                    Qrel(
                        dataset_id=gold.id,
                        query_id=new_qid,
                        target_id=qr.target_id,
                        target_type=qr.target_type,
                        relevance=qr.relevance,
                        target_data=qr.target_data,
                        resolution_status=qr.resolution_status,
                        resolution_meta=qr.resolution_meta,
                    )
                )

    db.commit()
    db.refresh(gold)
    return gold
