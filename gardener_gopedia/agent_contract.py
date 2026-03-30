"""
Structured JSON contract for external AI agents submitting label proposals.

See doc/agent-label-contract.md for field semantics and examples.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentCandidateItem(BaseModel):
    target_id: str = Field(..., min_length=1)
    target_type: Literal["l3_id", "doc_id"] = "l3_id"
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_name: str = Field(..., min_length=1, max_length=128)
    rationale: str | None = Field(default=None, max_length=8000)
    evidence: dict[str, Any] | None = Field(
        default=None,
        description="Optional evidence (snippet, title, hit_rank, or arbitrary JSON).",
    )
    candidate_rank: int = Field(default=0, ge=0)


class AgentQueryProposal(BaseModel):
    """Proposals for one dataset_query (by internal id)."""

    dataset_query_id: str = Field(..., min_length=1)
    candidates: list[AgentCandidateItem] = Field(default_factory=list)


class AgentBatchPayload(BaseModel):
    """Top-level body for POST /curation/batches (proposals array)."""

    proposals: list[AgentQueryProposal] = Field(..., min_length=1)


def pick_auto_accept_candidate(
    candidates: list[AgentCandidateItem],
    *,
    single_min_conf: float,
    consensus_min_models: int,
    consensus_min_conf: float,
) -> AgentCandidateItem | None:
    """
    Routing policy: consensus on same target wins if enough models agree above floor;
    else single top confidence if >= single_min_conf.
    """
    if not candidates:
        return None
    key_to_items: dict[tuple[str, str], list[AgentCandidateItem]] = {}
    for c in candidates:
        k = (c.target_id, c.target_type)
        key_to_items.setdefault(k, []).append(c)
    best_key = max(
        key_to_items,
        key=lambda k: (len(key_to_items[k]), max(x.confidence for x in key_to_items[k])),
    )
    group = key_to_items[best_key]
    if len(group) >= consensus_min_models and all(c.confidence >= consensus_min_conf for c in group):
        return max(group, key=lambda c: c.confidence)
    top = max(candidates, key=lambda c: c.confidence)
    if top.confidence >= single_min_conf:
        return top
    return None
