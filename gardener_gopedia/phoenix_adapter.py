"""Export eval traces to self-hosted Phoenix via OTLP HTTP."""

from __future__ import annotations

import logging
from typing import Any

from gardener_gopedia.config import get_settings

logger = logging.getLogger(__name__)


def export_eval_run_to_phoenix(
    *,
    eval_run_id: str,
    dataset_name: str,
    dataset_version: str,
    git_sha: str | None,
    index_version: str | None,
    per_query: list[dict[str, Any]],
) -> None:
    """
    Emit one root span per eval run and child spans per query with Ragas / IR attributes.

    per_query items should include: external_id, tier, query_text, metrics (dict str->float), error (optional str).
    """
    settings = get_settings()
    endpoint = settings.phoenix_otlp_endpoint
    if not endpoint or not endpoint.strip():
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    except ImportError:
        logger.warning("opentelemetry packages missing; pip install -e '.[eval]' for Phoenix export")
        return

    resource = Resource.create(
        {
            "service.name": settings.phoenix_service_name,
            "gardener.eval_run_id": eval_run_id,
            "gardener.dataset_name": dataset_name,
            "gardener.dataset_version": dataset_version,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint.strip())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("gardener_gopedia.eval")

    attrs: dict[str, Any] = {
        "gardener.eval_run_id": eval_run_id,
        "gardener.dataset": f"{dataset_name}@{dataset_version}",
    }
    if git_sha:
        attrs["gardener.git_sha"] = git_sha
    if index_version:
        attrs["gardener.index_version"] = index_version

    with tracer.start_as_current_span("gardener_eval_run", attributes=attrs) as root:
        root.set_attribute("gardener.per_query_count", len(per_query))
        for row in per_query:
            ext = str(row.get("external_id", ""))
            tier = row.get("tier") or ""
            qtext = (row.get("query_text") or "")[:500]
            child_attrs: dict[str, Any] = {
                "gardener.query_external_id": ext,
                "gardener.tier": tier,
                "gardener.query_text": qtext,
            }
            metrics = row.get("metrics") or {}
            if isinstance(metrics, dict):
                for k, v in metrics.items():
                    if isinstance(v, float):
                        child_attrs[f"gardener.metric.{k}"] = v
                    elif isinstance(v, int) and not isinstance(v, bool):
                        child_attrs[f"gardener.metric.{k}"] = float(v)
            err = row.get("error")
            if err:
                child_attrs["gardener.error"] = str(err)[:2000]
            with tracer.start_as_current_span(f"query:{ext or 'unknown'}", attributes=child_attrs):
                pass

    provider.shutdown()
