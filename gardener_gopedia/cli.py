"""CLI entrypoints."""

from __future__ import annotations

import uvicorn

from gardener_gopedia.config import get_settings


def run_api() -> None:
    s = get_settings()
    uvicorn.run(
        "gardener_gopedia.main:app",
        host=s.api_host,
        port=s.api_port,
        reload=False,
    )
