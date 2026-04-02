"""Resolve qrels that only have target_data into target_id/l3_id or doc_id via Gopedia search."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.core.config import get_settings
from gardener_gopedia.ingest.client import GopediaClient, gopedia_json_search_failed
from gardener_gopedia.core.models import DatasetQuery, Qrel

logger = logging.getLogger(__name__)

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_SKIPPED = "skipped"


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return str(s).strip().lower()


def _build_search_query(query_text: str, target_data: dict[str, Any]) -> str:
    parts = [query_text.strip()]
    ex = target_data.get("excerpt")
    if isinstance(ex, str) and ex.strip():
        parts.append(ex.strip()[:400])
    th = target_data.get("title_hint")
    if isinstance(th, str) and th.strip():
        parts.append(th.strip())
    return " ".join(parts)[:1500]


def _bonus_for_hit(hit: dict[str, Any], target_data: dict[str, Any]) -> float:
    bonus = 0.0
    excerpt = _norm(target_data.get("excerpt"))
    title_hint = _norm(target_data.get("title_hint"))
    path_hint = (target_data.get("source_path_hint") or "").replace("\\", "/")
    snip = _norm(hit.get("snippet"))
    title = _norm(hit.get("title"))
    sp = (hit.get("source_path") or "").replace("\\", "/").lower()

    if excerpt:
        if excerpt[:120] in snip or excerpt in snip:
            bonus += 0.25
        else:
            for tok in re.findall(r"[\w가-힣]{4,}", excerpt)[:6]:
                if tok in snip:
                    bonus += 0.04
    if title_hint and title_hint in title:
        bonus += 0.15
    if path_hint and path_hint.lower() in sp:
        bonus += 0.2
    return min(bonus, 0.45)


def _pick_id_from_hit(hit: dict[str, Any], prefer_doc_id: bool) -> tuple[str | None, str]:
    l3 = (hit.get("l3_id") or "").strip()
    doc = (hit.get("doc_id") or "").strip()
    if prefer_doc_id and doc:
        return doc, "doc_id"
    if l3:
        return l3, "l3_id"
    if doc:
        return doc, "doc_id"
    return None, "l3_id"


def score_hit_for_target_data(hit: dict[str, Any], target_data: dict[str, Any]) -> float:
    vec = float(hit.get("score") or 0.0)
    return vec + _bonus_for_hit(hit, target_data)


def resolve_single_qrel(
    client: GopediaClient,
    *,
    query_text: str,
    project_id: int | None,
    qrel: Qrel,
    settings: Any,
) -> dict[str, Any]:
    td = qrel.target_data or {}
    if not isinstance(td, dict):
        td = {}

    q = _build_search_query(query_text, td)
    data = client.search_json(
        q,
        project_id,
        detail=settings.qrel_resolve_search_detail,
        request_id=str(uuid.uuid4()),
    )
    if gopedia_json_search_failed(data):
        return {
            "ok": False,
            "status": STATUS_UNRESOLVED,
            "resolution_meta": {"error": "search_failed", "response_keys": list(data.keys())},
        }

    results = data.get("results") or []
    if not results:
        return {
            "ok": False,
            "status": STATUS_AMBIGUOUS,
            "resolution_meta": {"error": "no_results"},
        }

    prefer_doc = qrel.target_type == "doc_id"
    max_n = max(1, int(settings.qrel_resolve_max_hits_to_score))
    scored: list[tuple[float, dict[str, Any]]] = []
    for hit in results[:max_n]:
        if not isinstance(hit, dict):
            continue
        sc = score_hit_for_target_data(hit, td)
        scored.append((sc, hit))

    if not scored:
        return {
            "ok": False,
            "status": STATUS_AMBIGUOUS,
            "resolution_meta": {"error": "no_scorable_hits"},
        }

    scored.sort(key=lambda x: -x[0])
    best_score, best_hit = scored[0]
    vec = float(best_hit.get("score") or 0.0)

    if vec < float(settings.qrel_resolve_min_vector_score):
        return {
            "ok": False,
            "status": STATUS_AMBIGUOUS,
            "resolution_meta": {
                "reason": "below_min_vector_score",
                "best_vector_score": vec,
                "best_combined_score": best_score,
            },
        }

    if best_score < float(settings.qrel_resolve_min_combined_score):
        return {
            "ok": False,
            "status": STATUS_AMBIGUOUS,
            "resolution_meta": {
                "reason": "below_min_combined_score",
                "best_combined_score": best_score,
            },
        }

    tid, ttype = _pick_id_from_hit(best_hit, prefer_doc)
    if not tid:
        return {
            "ok": False,
            "status": STATUS_AMBIGUOUS,
            "resolution_meta": {"reason": "no_l3_or_doc_on_hit", "hit_keys": list(best_hit.keys())},
        }

    return {
        "ok": True,
        "status": STATUS_RESOLVED,
        "target_id": tid,
        "target_type": ttype,
        "resolution_meta": {
            "combined_score": best_score,
            "vector_score": vec,
            "chosen_title": best_hit.get("title"),
            "request_id": data.get("request_id"),
        },
    }


def resolve_dataset_qrels(
    db: Session,
    dataset_id: str,
    gopedia_base_url: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Resolve qrels with target_data (and optionally re-resolve when force=True)."""
    settings = get_settings()
    queries = (
        db.query(DatasetQuery).filter(DatasetQuery.dataset_id == dataset_id).all()
    )
    q_by_id = {q.id: q for q in queries}
    qrels = db.query(Qrel).filter(Qrel.dataset_id == dataset_id).all()

    to_resolve = []
    for qr in qrels:
        if force and qr.target_data:
            to_resolve.append(qr)
        elif (not (qr.target_id or "").strip()) and qr.target_data:
            to_resolve.append(qr)
        elif qr.resolution_status == STATUS_UNRESOLVED and qr.target_data:
            to_resolve.append(qr)

    if not to_resolve:
        return {
            "dataset_id": dataset_id,
            "attempted": 0,
            "resolved": 0,
            "ambiguous": 0,
            "failed": 0,
            "message": "no qrels to resolve",
        }

    client = GopediaClient(gopedia_base_url, timeout_s=max(settings.default_query_timeout_s, 120.0))
    resolved = ambiguous = failed = 0
    try:
        for qr in to_resolve:
            dq = q_by_id.get(qr.query_id)
            if not dq:
                failed += 1
                qr.resolution_status = STATUS_UNRESOLVED
                qr.resolution_meta = {"error": "missing_dataset_query"}
                continue

            out = resolve_single_qrel(
                client,
                query_text=dq.query_text,
                project_id=dq.project_id,
                qrel=qr,
                settings=settings,
            )
            meta = out.get("resolution_meta") or {}
            if out.get("ok"):
                qr.target_id = out["target_id"]
                qr.target_type = out.get("target_type") or qr.target_type
                qr.resolution_status = STATUS_RESOLVED
                qr.resolution_meta = meta
                resolved += 1
            else:
                st = out.get("status") or STATUS_AMBIGUOUS
                qr.resolution_status = st
                qr.resolution_meta = meta
                if st == STATUS_AMBIGUOUS:
                    ambiguous += 1
                else:
                    failed += 1
        db.commit()
    finally:
        client.close()

    return {
        "dataset_id": dataset_id,
        "attempted": len(to_resolve),
        "resolved": resolved,
        "ambiguous": ambiguous,
        "failed": failed,
    }


def dataset_has_unresolved_qrels(db: Session, dataset_id: str) -> bool:
    rows = db.query(Qrel).filter(Qrel.dataset_id == dataset_id).all()
    for qr in rows:
        if not (qr.target_id or "").strip():
            return True
    return False
