"""Unit tests: quality presets + EvalRunCreate (no external HTTP)."""

from __future__ import annotations

import pytest

from gardener_gopedia.dataset.presets import PRESET_JSON_PATHS, list_quality_preset_names, load_quality_preset
from gardener_gopedia.schemas import EvalRunCreate


def test_list_quality_preset_names():
    assert "osteon" in list_quality_preset_names()


def test_preset_osteon_file_exists():
    assert PRESET_JSON_PATHS["osteon"].is_file()


def test_load_osteon_dataset_create():
    dc = load_quality_preset("osteon")
    assert dc.name
    assert len(dc.queries) >= 1
    assert dc.qrels


def test_load_osteon_case_insensitive():
    dc = load_quality_preset("OSTEON")
    assert len(dc.queries) >= 1


def test_eval_run_create_preset_only():
    m = EvalRunCreate(quality_preset="osteon", top_k=10, search_detail="summary")
    assert m.dataset_id is None
    assert m.quality_preset == "osteon"


def test_eval_run_create_xor_both():
    with pytest.raises(ValueError, match="exactly one"):
        EvalRunCreate(
            dataset_id="550e8400-e29b-41d4-a716-446655440000",
            quality_preset="osteon",
        )


def test_eval_run_create_xor_neither():
    with pytest.raises(ValueError, match="exactly one"):
        EvalRunCreate(top_k=10)


@pytest.mark.integration
def test_persist_osteon_dataset(memory_session):
    """Register osteon preset via same path as POST /datasets (needs Postgres)."""
    from gardener_gopedia.dataset.persist import persist_dataset_create

    dc = load_quality_preset("osteon")
    ds = persist_dataset_create(memory_session, dc)
    assert ds.id
    assert ds.name


@pytest.mark.integration
def test_post_runs_quality_preset_end_to_end(gardener_client, gopedia_client):
    """POST /runs with quality_preset only (server loads osteon v2 JSON). Requires live Gardener + Gopedia."""
    r = gopedia_client.get("/api/health/deps")
    assert r.status_code == 200

    r = gardener_client.post(
        "/runs",
        json={
            "quality_preset": "osteon",
            "top_k": 10,
            "search_detail": "summary",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("id")
    assert out.get("dataset_id")

    run_id = out["id"]
    wr = gardener_client.post(f"/runs/{run_id}/wait", timeout=400.0)
    assert wr.status_code == 200, wr.text
    assert wr.json().get("status") == "completed"

    mr = gardener_client.get(f"/runs/{run_id}/metrics")
    assert mr.status_code == 200
    names = {m["metric_name"] for m in mr.json() if m.get("scope") == "aggregate"}
    assert "Recall@5" in names
