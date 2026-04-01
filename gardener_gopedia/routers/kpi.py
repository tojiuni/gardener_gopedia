from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from gardener_gopedia.core.db import get_session
from gardener_gopedia.kpi_service import build_roi_query_rows, build_run_kpi_summary
from gardener_gopedia.core.models import EvalRun
from gardener_gopedia.schemas import RunKpiRoiOut, RunKpiSummaryOut

router = APIRouter()


@router.get("/{run_id}/kpi-summary", response_model=RunKpiSummaryOut)
def kpi_summary(run_id: str, db: Session = Depends(get_session)):
    row = db.get(EvalRun, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    data = build_run_kpi_summary(db, row)
    return RunKpiSummaryOut(**data)


@router.get("/{run_id}/kpi-roi-queries", response_model=RunKpiRoiOut)
def kpi_roi_queries(
    run_id: str,
    sort: str = Query("worst_roi", description="worst_roi | highest_cost | lowest_quality"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_session),
):
    row = db.get(EvalRun, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    data = build_roi_query_rows(db, row, sort=sort, limit=limit)
    return RunKpiRoiOut(**data)
