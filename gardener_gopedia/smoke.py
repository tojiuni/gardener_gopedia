"""Smoke: create sample dataset, run eval (wait), print metrics."""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

DEFAULT_GARDENER = os.environ.get("GARDENER_API_URL", "http://127.0.0.1:18880")
DEFAULT_GOPEDIA = os.environ.get("GOPEDIA_API_URL", "http://127.0.0.1:18787")


def main() -> None:
    base = os.environ.get("GARDENER_API_URL", DEFAULT_GARDENER).rstrip("/")
    gopedia = os.environ.get("GOPEDIA_API_URL", DEFAULT_GOPEDIA).rstrip("/")

    # Preflight Gopedia
    try:
        r = httpx.get(f"{gopedia}/api/health/deps", timeout=10.0)
        r.raise_for_status()
    except Exception as e:
        print(f"Gopedia not reachable at {gopedia}: {e}", file=sys.stderr)
        print("Set GOPEDIA_API_URL or start Gopedia; continuing may fail.", file=sys.stderr)

    sample = [
        {"external_id": "q1", "text": "gRPC", "project_id": None},
        {"external_id": "q2", "text": "DefaultSink", "project_id": None},
        {"query_external_id": "q1", "target_id": "placeholder-l3", "target_type": "l3_id", "relevance": 1},
    ]

    with httpx.Client(timeout=120.0) as c:
        # Minimal dataset: queries only for contract smoke; qrel placeholder may not match
        ds_body = {
            "name": "smoke",
            "version": "1",
            "queries": [sample[0], sample[1]],
            "qrels": [],
        }
        r = c.post(f"{base}/datasets", json=ds_body)
        if r.status_code >= 400:
            print(r.text, file=sys.stderr)
            r.raise_for_status()
        ds = r.json()
        dataset_id = ds["id"]

        r = c.post(
            f"{base}/runs",
            json={
                "dataset_id": dataset_id,
                "target_url": gopedia,
                "top_k": 5,
                "skip_if_ingest_failed": True,
            },
        )
        r.raise_for_status()
        run = r.json()
        run_id = run["id"]

        for _ in range(120):
            r = c.get(f"{base}/runs/{run_id}")
            r.raise_for_status()
            st = r.json()["status"]
            if st in ("completed", "failed"):
                break
            time.sleep(1)

        r = c.get(f"{base}/runs/{run_id}")
        r.raise_for_status()
        print(json.dumps(r.json(), indent=2))

        r = c.get(f"{base}/runs/{run_id}/metrics")
        r.raise_for_status()
        print("metrics:", json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()
