"""Push eval KPIs to Langfuse: trace, per-query spans, scores, usage/cost metadata."""

from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.core.config import get_settings
from gardener_gopedia.observability.langfuse_client import get_langfuse, langfuse_trace_url
from gardener_gopedia.core.models import Dataset, DatasetQuery, EvalRun
from gardener_gopedia.observability.contract import (
    PJ_LANGFUSE_HOST,
    PJ_LANGFUSE_SYNC_ERROR,
    PJ_LANGFUSE_TRACE_ID,
    PJ_LANGFUSE_TRACE_URL,
)
from gardener_gopedia.observability.payload import build_per_query_observability_payload
logger = logging.getLogger(__name__)


def _safe_score_name(name: str) -> str:
    s = name.replace("/", "_").replace("@", "_at_").replace(" ", "_")
    return s[:200] if len(s) > 200 else s


def _numeric_score_value(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return float(v)
    return None


def run_langfuse_post_eval(db: Session, eval_run: EvalRun, dataset: Dataset) -> dict[str, Any]:
    """
    Build per-query payload, emit Langfuse trace + observations, persist summary metrics.
    """
    settings = get_settings()
    if not settings.langfuse_enabled:
        return {}

    client = get_langfuse()
    if client is None:
        return {}

    queries = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == dataset.id)
        .order_by(DatasetQuery.external_id)
        .all()
    )
    per_query = build_per_query_observability_payload(db, eval_run=eval_run, queries=queries)

    trace_id = client.create_trace_id()
    host = (settings.langfuse_host or "").strip().rstrip("/")
    out: dict[str, Any] = {
        PJ_LANGFUSE_TRACE_ID: trace_id,
        PJ_LANGFUSE_HOST: host,
        PJ_LANGFUSE_TRACE_URL: langfuse_trace_url(host=host, trace_id=trace_id),
    }

    try:
        from langfuse.types import TraceContext

        ctx = TraceContext(trace_id=trace_id)
        meta = {
            "gardener_eval_run_id": eval_run.id,
            "gardener_dataset_id": dataset.id,
            "gardener_dataset_name": dataset.name,
            "gardener_dataset_version": dataset.version,
            "gardener_git_sha": eval_run.git_sha,
            "gardener_index_version": eval_run.index_version,
            "gardener_target_url": eval_run.target_url,
            "ragas_enabled": (eval_run.params_json or {}).get("ragas_enabled"),
            "ragas_openai_model": settings.ragas_openai_model,
        }
        with client.start_as_current_observation(
            trace_context=ctx,
            name="gardener_eval_run",
            as_type="span",
            metadata=meta,
            input={
                "dataset_id": dataset.id,
                "eval_run_id": eval_run.id,
                "query_count": len(queries),
            },
        ) as root:
            for row in per_query:
                ext = str(row.get("external_id", ""))
                qtext = (row.get("query_text") or "")[:2000]
                usage = row.get("usage") or {}
                cost = row.get("cost_usd") or {}
                lat = row.get("latency_ms") or {}
                usage_details: dict[str, int] | None = None
                if isinstance(usage, dict) and usage:
                    usage_details = {}
                    if usage.get("input_tokens"):
                        usage_details["input"] = int(usage["input_tokens"])
                    if usage.get("output_tokens"):
                        usage_details["output"] = int(usage["output_tokens"])
                    if usage.get("total_tokens"):
                        usage_details["total"] = int(usage["total_tokens"])
                    if not usage_details:
                        usage_details = None
                cost_details: dict[str, float] | None = None
                if isinstance(cost, dict) and cost:
                    cost_details = {}
                    if cost.get("input_usd") is not None:
                        cost_details["input"] = float(cost["input_usd"])
                    if cost.get("output_usd") is not None:
                        cost_details["output"] = float(cost["output_usd"])
                    if cost.get("total_usd") is not None:
                        cost_details["total"] = float(cost["total_usd"])
                    if not cost_details:
                        cost_details = None

                out_preview = {
                    "hit_count": len(row.get("hits") or []),
                    "top_titles": [
                        (h.get("title") or h.get("target_id"))[:120]
                        for h in (row.get("hits") or [])[:3]
                    ],
                }
                with client.start_as_current_observation(
                    trace_context=ctx,
                    name=f"query:{ext or row.get('dataset_query_id')}",
                    as_type="span",
                    input={"query": qtext, "external_id": ext, "tier": row.get("tier")},
                    output=out_preview,
                    metadata={
                        "dataset_query_id": row.get("dataset_query_id"),
                        "error": row.get("error"),
                        "latency_search_ms": lat.get("search") if isinstance(lat, dict) else None,
                        "latency_llm_ms": lat.get("llm") if isinstance(lat, dict) else None,
                    },
                ) as qspan:
                    if usage_details or cost_details:
                        qspan.update(usage_details=usage_details, cost_details=cost_details)
                    metrics = row.get("metrics") or {}
                    if isinstance(metrics, dict):
                        for mk, mv in metrics.items():
                            sv = _numeric_score_value(mv)
                            if sv is None:
                                continue
                            try:
                                qspan.score(name=_safe_score_name(str(mk)), value=sv)
                            except Exception:
                                logger.debug("langfuse score skip for %s", mk, exc_info=True)
            root.update(
                output={
                    "queries_exported": len(per_query),
                    "langfuse_trace_id": trace_id,
                }
            )

        client.flush()
    except Exception as e:
        logger.exception("Langfuse export failed")
        out[PJ_LANGFUSE_SYNC_ERROR] = str(e)[:2000]

    return out
