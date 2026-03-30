"""FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from gardener_gopedia.config import get_settings
from gardener_gopedia.db import init_db
from gardener_gopedia.routers import compare, curation, datasets, ingest_runs, reviews, runs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Gardener Gopedia", version="0.1.0", lifespan=lifespan)

app.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
app.include_router(ingest_runs.router, prefix="/ingest-runs", tags=["ingest-runs"])
app.include_router(runs.router, prefix="/runs", tags=["runs"])
app.include_router(compare.router, prefix="/compare", tags=["compare"])
app.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
app.include_router(curation.router, prefix="/curation", tags=["curation"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "gardener_gopedia"}


@app.get("/config/defaults")
def config_defaults():
    s = get_settings()
    url = s.database_url or ""
    return {
        "gopedia_base_url": s.gopedia_base_url,
        "default_top_k": s.default_top_k,
        "default_query_timeout_s": s.default_query_timeout_s,
        "ragas_enabled_default": s.ragas_enabled,
        "ragas_answer_metrics_default": s.ragas_answer_metrics,
        "phoenix_otlp_configured": bool(s.phoenix_otlp_endpoint),
        "phoenix_api_base_url": s.phoenix_api_base_url,
        "phoenix_sync_enabled": s.phoenix_sync_enabled,
        "database_driver": "postgresql",
        "postgres_schema": s.postgres_schema,
    }
