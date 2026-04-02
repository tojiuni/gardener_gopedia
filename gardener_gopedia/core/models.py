import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gardener_gopedia.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class TargetType(str, enum.Enum):
    l3_id = "l3_id"
    doc_id = "doc_id"


class IngestMode(str, enum.Enum):
    sync = "sync"
    async_ = "async"


class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(64), default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Bronze (queries only / draft) → Silver (AI proposals) → Gold (promoted qrels).
    curation_tier: Mapped[str] = mapped_column(String(32), default="bronze", nullable=False)
    parent_dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id"), nullable=True
    )
    # Batch that produced this promoted dataset (no FK — avoids create_all order vs LabelingBatch).
    promoted_from_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    promotion_provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    queries: Mapped[list["DatasetQuery"]] = relationship(back_populates="dataset")
    qrels: Mapped[list["Qrel"]] = relationship(back_populates="dataset")
    eval_runs: Mapped[list["EvalRun"]] = relationship(back_populates="dataset")
    labeling_batches: Mapped[list["LabelingBatch"]] = relationship(back_populates="dataset")


class DatasetQuery(Base):
    __tablename__ = "dataset_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional tier tag for dashboards (easy/medium/hard).
    tier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Ground-truth short answer for Ragas context recall (phase 2).
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped["Dataset"] = relationship(back_populates="queries")
    qrels: Mapped[list["Qrel"]] = relationship(back_populates="query")

    __table_args__ = (UniqueConstraint("dataset_id", "external_id", name="uq_dataset_ext_query"),)


class Qrel(Base):
    __tablename__ = "qrels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    query_id: Mapped[str] = mapped_column(String(36), ForeignKey("dataset_queries.id"), nullable=False)
    # Nullable until POST /datasets/{id}/resolve-qrels fills id (agent-authored target_data-only qrels).
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_type: Mapped[str] = mapped_column(String(16), default=TargetType.l3_id.value)
    relevance: Mapped[int] = mapped_column(Integer, default=1)
    target_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(32), default="resolved", nullable=False)
    resolution_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    dataset: Mapped["Dataset"] = relationship(back_populates="qrels")
    query: Mapped["DatasetQuery"] = relationship(back_populates="qrels")


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    target_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    ingest_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gopedia_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gopedia_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.pending.value)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    eval_runs: Mapped[list["EvalRun"]] = relationship(back_populates="ingest_run")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    target_url: Mapped[str] = mapped_column(String(512), nullable=False)
    ingest_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ingest_runs.id"), nullable=True)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.pending.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped["Dataset"] = relationship(back_populates="eval_runs")
    ingest_run: Mapped["IngestRun | None"] = relationship(back_populates="eval_runs")
    hits: Mapped[list["RunHit"]] = relationship(back_populates="eval_run")
    metrics: Mapped[list["RunMetric"]] = relationship(back_populates="eval_run")


class RunHit(Base):
    __tablename__ = "run_hits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    eval_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False)
    dataset_query_id: Mapped[str] = mapped_column(String(36), ForeignKey("dataset_queries.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), default=TargetType.l3_id.value)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    eval_run: Mapped["EvalRun"] = relationship(back_populates="hits")


class RunMetric(Base):
    __tablename__ = "run_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    eval_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="aggregate")
    dataset_query_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("dataset_queries.id"), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    eval_run: Mapped["EvalRun"] = relationship(back_populates="metrics")


class RunRagasSample(Base):
    """Per-query Ragas phase-2 generated response (and future extras)."""

    __tablename__ = "run_ragas_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    eval_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False)
    dataset_query_id: Mapped[str] = mapped_column(String(36), ForeignKey("dataset_queries.id"), nullable=False)
    generated_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("eval_run_id", "dataset_query_id", name="uq_run_ragas_sample_query"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    eval_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False)
    dataset_query_id: Mapped[str] = mapped_column(String(36), ForeignKey("dataset_queries.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LabelingBatch(Base):
    """Groups AI proposals and human decisions for one dataset + optional source eval run."""

    __tablename__ = "labeling_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    source_eval_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("eval_runs.id"), nullable=True
    )
    external_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dataset: Mapped["Dataset"] = relationship(back_populates="labeling_batches")
    candidates: Mapped[list["LabelCandidate"]] = relationship(back_populates="labeling_batch")
    decisions: Mapped[list["LabelDecision"]] = relationship(back_populates="labeling_batch")

    __table_args__ = (
        UniqueConstraint("dataset_id", "external_key", name="uq_labeling_batch_dataset_external"),
    )


class LabelCandidate(Base):
    """AI-proposed target for a query (Silver); not used for metrics until promoted to qrels."""

    __tablename__ = "label_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    labeling_batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("labeling_batches.id"), nullable=False
    )
    dataset_query_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_queries.id"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), default=TargetType.l3_id.value)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    candidate_rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    labeling_batch: Mapped["LabelingBatch"] = relationship(back_populates="candidates")


class LabelDecision(Base):
    """Per-query resolution within a batch: unresolved, auto-accepted, or human-reviewed."""

    __tablename__ = "label_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    labeling_batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("labeling_batches.id"), nullable=False
    )
    dataset_query_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_queries.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    chosen_target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chosen_target_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    relevance: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    labeling_batch: Mapped["LabelingBatch"] = relationship(back_populates="decisions")

    __table_args__ = (
        UniqueConstraint("labeling_batch_id", "dataset_query_id", name="uq_label_decision_batch_query"),
    )
