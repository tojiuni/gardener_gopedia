"""After eval: Phoenix REST (dataset + experiment + runs) and OTLP traces."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.config import get_settings
from gardener_gopedia.models import Dataset, DatasetQuery, EvalRun
from gardener_gopedia.phoenix_adapter import export_eval_run_to_phoenix
from gardener_gopedia.phoenix_payload import build_per_query_phoenix_payload
from gardener_gopedia.phoenix_rest import PhoenixRestClient, PhoenixRestError

logger = logging.getLogger(__name__)


def _slug_version(v: str) -> str:
    s = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (v or ""))
    return (s[:48] or "v").strip("_") or "v"


def _iso_utc(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def _json_safe_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        elif isinstance(v, dict):
            out[str(k)] = _json_safe_metadata(v)
        else:
            out[str(k)] = str(v)[:2000]
    return out


def _sync_phoenix_rest(
    db: Session,
    *,
    dataset: Dataset,
    eval_run: EvalRun,
    per_query: list[dict[str, Any]],
    base_url: str,
    api_key: str | None,
) -> dict[str, str]:
    client = PhoenixRestClient(base_url, api_key=api_key)
    name = f"gardener-ds-{dataset.id}-{_slug_version(dataset.version)}"

    inputs: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []
    for row in per_query:
        inputs.append(
            {
                "gardener_dataset_query_id": row["dataset_query_id"],
                "external_id": row["external_id"],
                "query_text": row["query_text"],
                "tier": row.get("tier") or "",
            }
        )
        meta_rows.append(
            {
                "gardener_dataset_id": dataset.id,
                "gardener_dataset_name": dataset.name,
                "gardener_dataset_version": dataset.version,
            }
        )

    dataset_id: str | None = dataset.phoenix_dataset_id
    version_id: str | None = dataset.phoenix_dataset_version_id
    examples: list[dict[str, Any]] = []

    can_reuse = bool(
        dataset_id
        and version_id
        and dataset.phoenix_dataset_for_version == dataset.version
    )
    if can_reuse:
        try:
            ex_data = client.get_dataset_examples(dataset_id, version_id=version_id)
            examples = list((ex_data.get("data") or {}).get("examples") or [])
        except Exception:
            logger.exception("Phoenix: failed to load cached dataset examples; will re-upload")
            can_reuse = False
            examples = []

    need_upload = (not examples) or (len(examples) != len(per_query))
    if not can_reuse or need_upload:
        try:
            resp = client.upload_dataset_sync(
                {
                    "action": "create",
                    "name": name,
                    "description": f"Gardener {dataset.name} v{dataset.version} (id={dataset.id})",
                    "inputs": inputs,
                    "metadata": meta_rows,
                }
            )
            d = resp.get("data") or {}
            dataset_id = str(d.get("dataset_id") or "")
            version_id = str(d.get("version_id") or "")
        except PhoenixRestError:
            found = client.list_datasets(name=name, limit=20)
            if not found:
                raise
            dataset_id = str(found[0].get("id") or "")
            ex_data = client.get_dataset_examples(dataset_id)
            block = ex_data.get("data") or {}
            examples = list(block.get("examples") or [])
            version_id = str(block.get("version_id") or version_id or "")
        else:
            ex_data = client.get_dataset_examples(dataset_id, version_id=version_id or None)
            block = ex_data.get("data") or {}
            examples = list(block.get("examples") or [])
            version_id = str(block.get("version_id") or version_id or "")

        if dataset_id and version_id:
            dataset.phoenix_dataset_id = dataset_id
            dataset.phoenix_dataset_version_id = version_id
            dataset.phoenix_dataset_for_version = dataset.version

    exmap: dict[str, str] = {}
    for ex in examples:
        inp = ex.get("input") or {}
        raw_id = inp.get("gardener_dataset_query_id")
        if raw_id is not None and str(raw_id):
            exmap[str(raw_id)] = str(ex.get("id") or "")
        ext = inp.get("external_id")
        if isinstance(ext, str) and ext:
            for row in per_query:
                if row["external_id"] == ext:
                    exmap.setdefault(str(row["dataset_query_id"]), str(ex.get("id") or ""))
                    break

    if not dataset_id:
        raise RuntimeError("Phoenix REST sync failed: missing dataset_id")

    params = eval_run.params_json or {}
    exp_meta = _json_safe_metadata(
        {
            "gardener_eval_run_id": eval_run.id,
            "gardener_dataset_id": dataset.id,
            "gardener_target_url": eval_run.target_url,
            "gardener_ingest_run_id": eval_run.ingest_run_id,
            "gardener_git_sha": eval_run.git_sha,
            "gardener_index_version": eval_run.index_version,
            "top_k": params.get("top_k"),
            "ragas_enabled": params.get("ragas_enabled"),
            "search_detail": params.get("search_detail"),
            "search_fields": params.get("search_fields"),
        }
    )
    exp_body: dict[str, Any] = {
        "name": f"gardener-eval-{eval_run.id[:8]}",
        "description": f"Gardener eval run {eval_run.id}",
        "metadata": exp_meta,
    }
    if version_id:
        exp_body["version_id"] = version_id
    exp_resp = client.create_experiment(dataset_id, exp_body)
    exp_id = str((exp_resp.get("data") or {}).get("id") or "")

    start_t = _iso_utc(eval_run.started_at)
    end_t = _iso_utc(eval_run.ended_at)
    for row in per_query:
        ex_id = exmap.get(row["dataset_query_id"])
        if not ex_id:
            logger.warning(
                "Phoenix: no dataset example for query %s; skip experiment run",
                row["dataset_query_id"],
            )
            continue
        output: dict[str, Any] = {
            "gardener_eval_run_id": eval_run.id,
            "metrics": row.get("metrics") or {},
            "hits": row.get("hits") or [],
            "external_id": row["external_id"],
        }
        body: dict[str, Any] = {
            "dataset_example_id": ex_id,
            "output": output,
            "repetition_number": 1,
            "start_time": start_t,
            "end_time": end_t,
        }
        if row.get("error"):
            body["error"] = str(row["error"])[:4000]
        try:
            client.create_experiment_run(exp_id, body)
        except Exception:
            logger.exception("Phoenix: experiment run failed for query %s", row["dataset_query_id"])

    return {
        "phoenix_dataset_id": dataset_id or "",
        "phoenix_dataset_version_id": version_id or "",
        "phoenix_experiment_id": exp_id,
        "phoenix_ui_base_url": base_url,
        "phoenix_dataset_name": name,
    }


def run_phoenix_post_eval(db: Session, eval_run: EvalRun, dataset: Dataset) -> dict[str, Any]:
    """
    Build per-query payload, optionally sync REST, then OTLP traces.
    Returns dict merged into EvalRun.params_json (may include error keys).
    """
    settings = get_settings()
    queries = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == dataset.id)
        .order_by(DatasetQuery.external_id)
        .all()
    )
    per_query = build_per_query_phoenix_payload(db, eval_run=eval_run, queries=queries)
    out: dict[str, Any] = {}

    base = (settings.phoenix_api_base_url or "").strip()
    if settings.phoenix_sync_enabled and base:
        try:
            rest = _sync_phoenix_rest(
                db,
                dataset=dataset,
                eval_run=eval_run,
                per_query=per_query,
                base_url=base,
                api_key=settings.phoenix_api_key,
            )
            out.update({k: v for k, v in rest.items() if v})
        except Exception as e:
            logger.exception("Phoenix REST sync failed")
            out["phoenix_sync_error"] = str(e)[:2000]

    ep = (settings.phoenix_otlp_endpoint or "").strip()
    if ep:
        try:
            export_eval_run_to_phoenix(
                eval_run_id=eval_run.id,
                dataset_name=dataset.name,
                dataset_version=dataset.version,
                git_sha=eval_run.git_sha,
                index_version=eval_run.index_version,
                per_query=per_query,
                extra_root_attributes={
                    k: v
                    for k, v in out.items()
                    if k.startswith("phoenix_") and isinstance(v, str) and v
                },
            )
        except Exception:
            logger.exception("Phoenix OTLP export failed")
            out.setdefault("phoenix_otlp_error", "export_failed")

    return out
