"""Minimal Phoenix REST client (datasets + experiments + runs)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PhoenixRestError(RuntimeError):
    pass


class PhoenixRestClient:
    def __init__(self, base_url: str, *, api_key: str | None = None, timeout_s: float = 120.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout_s
        self.headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key.strip()}"

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base, headers=self.headers, timeout=self.timeout)

    def upload_dataset_sync(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._client() as c:
            r = c.post("/v1/datasets/upload", params={"sync": "true"}, json=body)
            if r.status_code == 409:
                raise PhoenixRestError(r.text or "dataset name conflict")
            r.raise_for_status()
            return r.json()

    def list_datasets(self, *, name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if name:
            params["name"] = name
        with self._client() as c:
            r = c.get("/v1/datasets", params=params)
            r.raise_for_status()
            data = r.json()
            return list(data.get("data") or [])

    def get_dataset_examples(self, dataset_id: str, *, version_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if version_id:
            params["version_id"] = version_id
        with self._client() as c:
            r = c.get(f"/v1/datasets/{dataset_id}/examples", params=params)
            r.raise_for_status()
            return r.json()

    def create_experiment(self, dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._client() as c:
            r = c.post(f"/v1/datasets/{dataset_id}/experiments", json=body)
            r.raise_for_status()
            return r.json()

    def create_experiment_run(self, experiment_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._client() as c:
            r = c.post(f"/v1/experiments/{experiment_id}/runs", json=body)
            r.raise_for_status()
            return r.json()
