from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class QrelInput(BaseModel):
    query_external_id: str
    target_id: str
    target_type: Literal["l3_id", "doc_id"] = "l3_id"
    relevance: int = 1


class QueryInput(BaseModel):
    external_id: str
    text: str
    project_id: int | None = None


class DatasetCreate(BaseModel):
    name: str
    version: str = "1"
    queries: list[QueryInput]
    qrels: list[QrelInput]


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    created_at: datetime
    query_count: int


class IngestRunCreate(BaseModel):
    target_url: str | None = None
    source_path: str
    mode: Literal["sync", "async"] = "async"
    project_id: int | None = None
    idempotency_key: str | None = None


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_url: str
    source_path: str
    ingest_mode: str
    idempotency_key: str | None = None
    project_id: int | None
    gopedia_job_id: str | None
    gopedia_request_id: str | None
    status: str
    stdout: str | None
    stderr: str | None
    failure_json: dict[str, Any] | None
    started_at: datetime | None
    ended_at: datetime | None


class EvalRunCreate(BaseModel):
    dataset_id: str
    target_url: str | None = None
    ingest_run_id: str | None = None
    top_k: int = 10
    query_timeout_s: float | None = None
    git_sha: str | None = None
    index_version: str | None = None
    skip_if_ingest_failed: bool = True
    search_detail: str | None = None
    search_fields: str | None = None
    search_retryable_max_attempts: int | None = None


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    target_url: str
    ingest_run_id: str | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    error_message: str | None
    git_sha: str | None
    index_version: str | None


class RunMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    value: float
    scope: str
    dataset_query_id: str | None


class QueryResultOut(BaseModel):
    dataset_query_id: str
    external_id: str
    query_text: str
    metrics: list[RunMetricOut]
    hits: list[dict[str, Any]]


class ReviewCreate(BaseModel):
    eval_run_id: str
    dataset_query_id: str
    label: str
    notes: str | None = None
    reviewer: str | None = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    eval_run_id: str
    dataset_query_id: str
    label: str
    notes: str | None
    reviewer: str | None
    created_at: datetime


class CompareQuery(BaseModel):
    baseline: str
    candidate: str


class FailureItem(BaseModel):
    dataset_query_id: str
    external_id: str
    query_text: str
    baseline_metric: float | None
    candidate_metric: float | None
    delta: float | None
