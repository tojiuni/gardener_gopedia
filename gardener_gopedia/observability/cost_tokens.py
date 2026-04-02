"""Rough token estimates and OpenAI-style cost helpers for eval KPIs."""

from __future__ import annotations

from typing import Any

# USD per 1M tokens (input / output). Extend as needed; unknown models -> None cost.
_OPENAI_PRICE_PER_1M: dict[str, tuple[float | None, float | None]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "text-embedding-3-small": (0.02, None),
    "text-embedding-3-large": (0.13, None),
}


def estimate_tokens(text: str | None) -> int:
    """Heuristic token count when the provider does not return usage."""
    if not text:
        return 0
    # ~4 chars/token for English-ish text; clamp so empty strings stay 0
    return max(0, len(text) // 4)


def openai_usage_tokens(usage: Any) -> tuple[int, int, int]:
    """Extract (prompt, completion, total) from OpenAI completion.usage-like object."""
    if usage is None:
        return 0, 0, 0
    try:
        if isinstance(usage, dict):
            inp = int(usage.get("prompt_tokens") or 0)
            out = int(usage.get("completion_tokens") or 0)
            tot = int(usage.get("total_tokens") or 0) or (inp + out)
            return inp, out, tot
        inp = int(getattr(usage, "prompt_tokens", None) or 0)
        out = int(getattr(usage, "completion_tokens", None) or 0)
        tot = int(getattr(usage, "total_tokens", None) or 0) or (inp + out)
        return inp, out, tot
    except Exception:
        return 0, 0, 0


def compute_cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> tuple[float, float, float]:
    """Return (input_usd, output_usd, total_usd). Missing pricing -> 0 for that component."""
    key = (model or "").strip().lower()
    prices = _OPENAI_PRICE_PER_1M.get(key)
    if not prices:
        return 0.0, 0.0, 0.0
    pin, pout = prices
    cin = (input_tokens / 1_000_000.0) * float(pin or 0.0)
    cout = (output_tokens / 1_000_000.0) * float(pout or 0.0)
    return cin, cout, cin + cout


def estimate_ragas_judge_tokens(*, user_text: str, contexts: list[str], calls: int = 2) -> int:
    """Very rough budget for hidden Ragas LLM judge calls (no provider usage hook)."""
    base = estimate_tokens(user_text) + sum(estimate_tokens(c) for c in contexts)
    return base * max(1, calls)
