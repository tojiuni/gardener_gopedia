"""Lazy Langfuse SDK client (optional dependency)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gardener_gopedia.config import get_settings

if TYPE_CHECKING:
    from langfuse import Langfuse


def get_langfuse() -> "Langfuse | None":
    """Return configured Langfuse client, or None if keys/host are missing."""
    s = get_settings()
    pk = (s.langfuse_public_key or "").strip()
    sk = (s.langfuse_secret_key or "").strip()
    host = (s.langfuse_host or "").strip()
    if not pk or not sk or not host:
        return None
    from langfuse import Langfuse

    return Langfuse(public_key=pk, secret_key=sk, host=host.rstrip("/"))


def langfuse_trace_url(*, host: str, trace_id: str) -> str:
    """Best-effort UI URL (avoids server round-trip to resolve project id)."""
    base = host.rstrip("/")
    return f"{base}/trace/{trace_id}"
