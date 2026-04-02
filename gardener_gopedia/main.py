"""FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from gardener_gopedia.core.config import get_settings
from gardener_gopedia.core.db import init_db
from gardener_gopedia.curation.router import router as curation_router
from gardener_gopedia.curation.reviews_router import router as reviews_router
from gardener_gopedia.eval.router import router as runs_router
from gardener_gopedia.eval.compare_router import router as compare_router
from gardener_gopedia.observability.router import router as kpi_router
from gardener_gopedia.ingest.router import router as ingest_router
from gardener_gopedia.dataset.router import router as dataset_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Gardener Gopedia", version="0.1.0", lifespan=lifespan)

app.include_router(dataset_router, prefix="/datasets", tags=["datasets"])
app.include_router(ingest_router, prefix="/ingest-runs", tags=["ingest-runs"])
app.include_router(runs_router, prefix="/runs", tags=["runs"])
app.include_router(compare_router, prefix="/compare", tags=["compare"])
app.include_router(reviews_router, prefix="/reviews", tags=["reviews"])
app.include_router(curation_router, prefix="/curation", tags=["curation"])
app.include_router(kpi_router, prefix="/runs", tags=["kpi"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "gardener_gopedia"}


@app.get("/config/defaults")
def config_defaults():
    s = get_settings()
    return {
        "gopedia_base_url": s.gopedia_base_url,
        "default_top_k": s.default_top_k,
        "default_query_timeout_s": s.default_query_timeout_s,
        "ragas_enabled_default": s.ragas_enabled,
        "ragas_answer_metrics_default": s.ragas_answer_metrics,
        "langfuse_enabled": s.langfuse_enabled,
        "langfuse_configured": bool(
            s.langfuse_enabled
            and (s.langfuse_host or "").strip()
            and (s.langfuse_public_key or "").strip()
            and (s.langfuse_secret_key or "").strip()
        ),
        "langfuse_host": s.langfuse_host,
        "database_driver": "postgresql",
        "postgres_schema": s.postgres_schema,
    }
