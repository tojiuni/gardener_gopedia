from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QrelInput(BaseModel):
    query_external_id: str
    target_id: str | None = None
    target_type: Literal["l3_id", "doc_id"] = "l3_id"
    relevance: int = 1
    """Structured hints for POST .../resolve-qrels when target_id is omitted."""
    target_data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_target_id_or_target_data(self) -> QrelInput:
        tid = (self.target_id or "").strip()
        td = self.target_data
        has_data = isinstance(td, dict) and len(td) > 0
        if not tid and not has_data:
            raise ValueError("each qrel requires non-empty target_id or non-empty target_data")
        return self


class QueryInput(BaseModel):
    external_id: str
    text: str
    project_id: int | None = None
    tier: str | None = None
    reference_answer: str | None = None


class DatasetCreate(BaseModel):
    name: str
    version: str = "1"
    queries: list[QueryInput]
    qrels: list[QrelInput]
    curation_tier: Literal["bronze", "silver", "gold"] = "bronze"


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    created_at: datetime
    query_count: int
    curation_tier: str = "bronze"
    parent_dataset_id: str | None = None
    promoted_from_batch_id: str | None = None


class ResolveQrelsResult(BaseModel):
    dataset_id: str
    attempted: int
    resolved: int
    ambiguous: int
    failed: int
    message: str | None = None


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
    ragas_enabled: bool | None = Field(
        default=None,
        description="Override settings: run Ragas retrieval metrics (needs OPENAI_API_KEY + pip install -e '.[eval]').",
    )
    ragas_answer_metrics: bool | None = Field(
        default=None,
        description="Phase-2: generate answers + faithfulness / answer relevancy / context recall.",
    )
    resolve_before_eval: bool = Field(
        default=False,
        description="If true, run qrel resolution (Gopedia search) for unresolved target_data qrels before eval.",
    )


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
    phoenix_dataset_id: str | None = None
    phoenix_dataset_version_id: str | None = None
    phoenix_experiment_id: str | None = None
    phoenix_ui_base_url: str | None = None
    phoenix_dataset_name: str | None = None


def _opt_str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def eval_run_to_out(row: Any) -> EvalRunOut:
    """Map ORM EvalRun + params_json Phoenix keys to API model."""
    pj = row.params_json or {}
    return EvalRunOut(
        id=row.id,
        dataset_id=row.dataset_id,
        target_url=row.target_url,
        ingest_run_id=row.ingest_run_id,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
        error_message=row.error_message,
        git_sha=row.git_sha,
        index_version=row.index_version,
        phoenix_dataset_id=_opt_str(pj.get("phoenix_dataset_id")),
        phoenix_dataset_version_id=_opt_str(pj.get("phoenix_dataset_version_id")),
        phoenix_experiment_id=_opt_str(pj.get("phoenix_experiment_id")),
        phoenix_ui_base_url=_opt_str(pj.get("phoenix_ui_base_url")),
        phoenix_dataset_name=_opt_str(pj.get("phoenix_dataset_name")),
    )


class RunMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    value: float
    scope: str
    dataset_query_id: str | None = None
    details_json: dict[str, Any] | None = None


class QueryResultOut(BaseModel):
    dataset_query_id: str
    external_id: str
    query_text: str
    tier: str | None = None
    reference_answer: str | None = None
    metrics: list[RunMetricOut]
    hits: list[dict[str, Any]]
    ragas_generated_response: str | None = None


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


# --- AI + human curation (Silver / Gold datasets) ---


class LabelingBatchCreate(BaseModel):
    dataset_id: str
    source_eval_run_id: str | None = None
    external_key: str | None = Field(default=None, max_length=256)
    provenance_json: dict[str, Any] | None = None
    proposals: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="Each item validated as AgentQueryProposal (see doc/agent-label-contract.md).",
    )
    include_unlisted_queries: bool = False


class LabelingBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    source_eval_run_id: str | None
    external_key: str | None
    provenance_json: dict[str, Any] | None
    created_at: datetime


class HumanLabelDecisionBody(BaseModel):
    dataset_query_id: str
    action: Literal["accept_candidate", "set_target", "reject", "no_target"]
    candidate_id: str | None = None
    target_id: str | None = None
    target_type: Literal["l3_id", "doc_id"] | None = None
    relevance: int = 1
    reviewer: str | None = None
    notes: str | None = None
    mirror_review_eval_run_id: str | None = None
    review_label: str | None = None


class PromoteGoldBody(BaseModel):
    new_version: str = Field(..., min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    copy_parent_qrels_when_no_decision_target: bool = True


class LabelDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    labeling_batch_id: str
    dataset_query_id: str
    status: str
    chosen_target_id: str | None
    chosen_target_type: str | None
    relevance: int
    reviewer: str | None
    notes: str | None
    decided_at: datetime | None
    created_at: datetime
