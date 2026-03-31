"""Integration test: dataset → resolve → eval → metrics."""
import time

import pytest


@pytest.mark.integration
def test_eval_pipeline_core_path(gardener_client, gopedia_client):
    """End-to-end: register a mini dataset, resolve qrels, run eval, check metrics."""

    # Step 1: Verify Gopedia has data
    r = gopedia_client.get(
        "/api/search", params={"q": "traefik", "format": "json", "detail": "summary"}
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data.get("results", [])) > 0, "Gopedia has no indexed data — run ingest first"

    # Step 2: Register a mini dataset (2 queries)
    mini_dataset = {
        "name": f"test_pipeline_{int(time.time())}",
        "version": "1",
        "curation_tier": "bronze",
        "queries": [
            {
                "external_id": "t_traefik",
                "text": "What is the Traefik dynamic config path?",
                "tier": "easy",
            },
            {
                "external_id": "t_docker_net",
                "text": "What is the neunexus Docker network driver and subnet?",
                "tier": "easy",
            },
        ],
        "qrels": [
            {
                "query_external_id": "t_traefik",
                "target_type": "l3_id",
                "relevance": 1,
                "target_data": {
                    "excerpt": "dynamic config",
                    "title_hint": "Traefik",
                    "source_path_hint": "traefik",
                },
            },
            {
                "query_external_id": "t_docker_net",
                "target_type": "l3_id",
                "relevance": 1,
                "target_data": {
                    "excerpt": "macvlan",
                    "title_hint": "Docker Network",
                    "source_path_hint": "docker-network",
                },
            },
        ],
    }

    r = gardener_client.post("/datasets", json=mini_dataset)
    assert r.status_code == 200, f"Dataset creation failed: {r.text}"
    ds = r.json()
    dataset_id = ds["id"]
    assert dataset_id

    # Step 3: Resolve qrels
    r = gardener_client.post(f"/datasets/{dataset_id}/resolve-qrels")
    assert r.status_code == 200, f"Resolve failed: {r.text}"

    # Step 4: Run eval
    r = gardener_client.post(
        "/runs",
        json={
            "dataset_id": dataset_id,
            "top_k": 10,
            "search_detail": "summary",
            "resolve_before_eval": True,
        },
    )
    assert r.status_code == 200, f"Run creation failed: {r.text}"
    run_id = r.json()["id"]

    # Wait for completion
    r = gardener_client.post(f"/runs/{run_id}/wait", timeout=120.0)
    assert r.status_code == 200
    run_data = r.json()
    assert run_data["status"] == "completed", f"Run status: {run_data['status']}"

    # Step 5: Get metrics
    r = gardener_client.get(f"/runs/{run_id}/metrics")
    assert r.status_code == 200
    metrics = r.json()

    # Verify standard IR metrics
    metric_names = {m["metric_name"] for m in metrics if m["scope"] == "aggregate"}
    assert "Recall@5" in metric_names, f"Missing Recall@5 in {metric_names}"
    assert "MRR@10" in metric_names, f"Missing MRR@10 in {metric_names}"
    assert "nDCG@10" in metric_names, f"Missing nDCG@10 in {metric_names}"
    assert "P@3" in metric_names, f"Missing P@3 in {metric_names}"

    # Recall@5 should be a valid number in [0, 1]
    recall = next(
        m["value"]
        for m in metrics
        if m["metric_name"] == "Recall@5" and m["scope"] == "aggregate"
    )
    assert isinstance(recall, (int, float))
    assert 0.0 <= recall <= 1.0
