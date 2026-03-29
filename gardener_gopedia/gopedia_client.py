"""HTTP client for Gopedia API."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

DEFAULT_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def gopedia_json_search_failed(data: dict[str, Any]) -> bool:
    """True when JSON search response indicates failure (Gopedia agent-interop contract)."""
    if data.get("_parse_error"):
        return True
    if data.get("failure"):
        return True
    if data.get("ok") is False:
        return True
    results = data.get("results")
    if not isinstance(results, list):
        return True
    return False


class GopediaClient:
    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def health_deps(self) -> dict[str, Any]:
        r = self._client.get("/api/health/deps")
        r.raise_for_status()
        return r.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=8))
    def search_json(
        self,
        q: str,
        project_id: int | None = None,
        *,
        detail: str | None = None,
        fields: str | Sequence[str] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"q": q, "format": "json"}
        if project_id is not None:
            params["project_id"] = str(project_id)
        if detail:
            params["detail"] = detail
        if fields:
            if isinstance(fields, str):
                params["fields"] = fields
            else:
                params["fields"] = ",".join(fields)
        headers: dict[str, str] = {}
        if request_id:
            headers["X-Request-ID"] = request_id
        t0 = time.perf_counter()
        r = self._client.get("/api/search", params=params, headers=headers or None)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        data: dict[str, Any] = {}
        try:
            data = r.json()
        except Exception:
            data = {"_parse_error": True, "raw": r.text[:2000]}
        data["_http_status"] = r.status_code
        data["_latency_ms"] = latency_ms
        return data

    def ingest_sync(self, path: str, project_id: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"path": path}
        if project_id is not None:
            body["project_id"] = project_id
        r = self._client.post("/api/ingest", json=body, headers=DEFAULT_HEADERS)
        # Gopedia may return 200 with failure body
        try:
            return {**r.json(), "_http_status": r.status_code}
        except Exception:
            return {"ok": False, "error": r.text[:2000], "_http_status": r.status_code}

    def ingest_job_create(
        self,
        path: str,
        project_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"path": path}
        if project_id is not None:
            body["project_id"] = project_id
        headers = dict(DEFAULT_HEADERS)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        r = self._client.post("/api/ingest/jobs", json=body, headers=headers)
        try:
            return {**r.json(), "_http_status": r.status_code}
        except Exception:
            return {"error": r.text[:2000], "_http_status": r.status_code}

    def ingest_job_status(self, job_id: str) -> dict[str, Any]:
        r = self._client.get(f"/api/jobs/{job_id}")
        try:
            return {**r.json(), "_http_status": r.status_code}
        except Exception:
            return {"error": r.text[:2000], "_http_status": r.status_code}
