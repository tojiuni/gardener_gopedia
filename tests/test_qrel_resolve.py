"""Qrel target_data resolution and eval guards."""

import pytest

from gardener_gopedia.eval.service import execute_eval_run
from gardener_gopedia.core.models import Dataset, DatasetQuery, EvalRun, Qrel, RunStatus
from gardener_gopedia.eval.qrel_resolve import (
    dataset_has_unresolved_qrels,
    resolve_single_qrel,
    score_hit_for_target_data,
)
from gardener_gopedia.schemas import DatasetCreate, QrelInput, QueryInput


def test_qrel_input_requires_target_or_data():
    with pytest.raises(ValueError):
        QrelInput(query_external_id="q1", target_id=None, target_data=None)
    QrelInput(query_external_id="q1", target_id="uuid-here")
    QrelInput(query_external_id="q1", target_data={"excerpt": "hello"})


def test_score_hit_for_target_data_prefers_path_and_excerpt():
    hit = {
        "l3_id": "L3",
        "score": 0.5,
        "snippet": "Use only the traefik label for containers",
        "title": "Skill",
        "source_path": "/app/skills/traefik/SKILL.md",
    }
    td = {"excerpt": "traefik label", "source_path_hint": "traefik/SKILL.md"}
    s = score_hit_for_target_data(hit, td)
    assert s > 0.5


def test_execute_eval_fails_when_unresolved_qrel(memory_session):
    ds = Dataset(name="t", version="1")
    memory_session.add(ds)
    memory_session.flush()
    dq = DatasetQuery(dataset_id=ds.id, external_id="q1", query_text="hello")
    memory_session.add(dq)
    memory_session.flush()
    memory_session.add(
        Qrel(
            dataset_id=ds.id,
            query_id=dq.id,
            target_id=None,
            target_type="l3_id",
            relevance=1,
            target_data={"excerpt": "x"},
            resolution_status="unresolved",
        )
    )
    er = EvalRun(
        dataset_id=ds.id,
        target_url="http://gopedia.test",
        params_json={
            "top_k": 5,
            "query_timeout_s": 10.0,
            "skip_if_ingest_failed": True,
            "search_retryable_max_attempts": 2,
            "resolve_before_eval": False,
        },
        status=RunStatus.pending.value,
    )
    memory_session.add(er)
    memory_session.commit()
    memory_session.refresh(er)

    execute_eval_run(memory_session, er.id)
    memory_session.refresh(memory_session.get(EvalRun, er.id))
    assert er.status == RunStatus.failed.value
    assert "resolve" in (er.error_message or "").lower()


def test_dataset_has_unresolved_qrels(memory_session):
    ds = Dataset(name="t", version="1")
    memory_session.add(ds)
    memory_session.flush()
    dq = DatasetQuery(dataset_id=ds.id, external_id="q1", query_text="hello")
    memory_session.add(dq)
    memory_session.flush()
    memory_session.add(
        Qrel(
            dataset_id=ds.id,
            query_id=dq.id,
            target_id=None,
            target_data={"excerpt": "a"},
            resolution_status="unresolved",
        )
    )
    memory_session.commit()
    assert dataset_has_unresolved_qrels(memory_session, ds.id) is True


def test_resolve_single_qrel_picks_best_l3():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from gardener_gopedia.ingest.client import GopediaClient

    client = MagicMock(spec=GopediaClient)
    client.search_json.return_value = {
        "results": [
            {
                "l3_id": "wrong",
                "doc_id": "",
                "score": 0.45,
                "snippet": "unrelated content only",
                "title": "Other",
                "source_path": "/other.md",
            },
            {
                "l3_id": "expected-l3",
                "doc_id": "",
                "score": 0.42,
                "snippet": "magic excerpt phrase here for grounding",
                "title": "Skill",
                "source_path": "/skills/foo/SKILL.md",
            },
        ],
        "request_id": "r1",
    }
    settings = SimpleNamespace(
        qrel_resolve_search_detail="standard",
        qrel_resolve_max_hits_to_score=20,
        qrel_resolve_min_vector_score=0.25,
        qrel_resolve_min_combined_score=0.35,
    )
    qr = Qrel(
        dataset_id="d",
        query_id="q",
        target_id=None,
        target_type="l3_id",
        relevance=1,
        target_data={"excerpt": "magic excerpt phrase", "source_path_hint": "foo/SKILL.md"},
        resolution_status="unresolved",
    )
    out = resolve_single_qrel(
        client,
        query_text="find magic",
        project_id=None,
        qrel=qr,
        settings=settings,
    )
    assert out["ok"] is True
    assert out["target_id"] == "expected-l3"
    assert out["target_type"] == "l3_id"


def test_dataset_create_accepts_target_data_only():
    body = DatasetCreate(
        name="agent_ds",
        version="1",
        queries=[QueryInput(external_id="q1", text="hello world")],
        qrels=[
            QrelInput(
                query_external_id="q1",
                target_data={"excerpt": "ground truth snippet", "title_hint": "Readme"},
            )
        ],
    )
    assert body.qrels[0].target_id is None
    assert body.qrels[0].target_data["excerpt"]


# ─── Substring-override resolver (added 2026-05-12) ──────────────────────────

def test_has_excerpt_substring_match_min_length():
    from gardener_gopedia.eval.qrel_resolve import _has_excerpt_substring_match
    td = {"excerpt": "short"}
    hit = {"surrounding_context": "this paragraph contains short verbatim"}
    # excerpt below min_len (40) → false even if substring exists
    assert _has_excerpt_substring_match(hit, td, min_len=40) is False


def test_has_excerpt_substring_match_hits_full_context():
    from gardener_gopedia.eval.qrel_resolve import _has_excerpt_substring_match
    excerpt = "metaflow uses Windmill because ~287MB RAM vs ~832MB"
    td = {"excerpt": excerpt}
    hit_ok = {"surrounding_context": f"Section 7. Tooling: {excerpt}. End."}
    hit_no = {"surrounding_context": "completely unrelated text about kubectl and helm"}
    assert _has_excerpt_substring_match(hit_ok, td, min_len=40) is True
    assert _has_excerpt_substring_match(hit_no, td, min_len=40) is False


def test_has_excerpt_substring_match_requires_surrounding_context():
    from gardener_gopedia.eval.qrel_resolve import _has_excerpt_substring_match
    td = {"excerpt": "a long enough distinctive phrase to satisfy min_len" * 2}
    # No surrounding_context → cannot match (snippet alone is not enough)
    hit = {"snippet": "a long enough distinctive phrase to satisfy min_len"}
    assert _has_excerpt_substring_match(hit, td, min_len=40) is False


def test_substring_override_wins_against_higher_vector_score():
    """Mirrors the v0.22.x regression: a wrong-chunk question-text hit
    has higher vector score, but the correct chunk has the excerpt in
    its surrounding_context.  Override should pick the correct one."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from gardener_gopedia.ingest.client import GopediaClient
    from gardener_gopedia.eval.qrel_resolve import resolve_single_qrel

    excerpt = "Caller-Callee (누가 누구를 호출하는가) Inheritance Implementation"
    client = MagicMock(spec=GopediaClient)
    client.search_json.return_value = {
        "results": [
            # Wrong chunk: high vector score (question matched), but
            # surrounding_context (original) doesn't contain excerpt.
            {
                "l3_id": "wrong-question-hit",
                "score": 0.92,
                "snippet": "What three relationship mappings are performed in Day 3-4?",
                "surrounding_context": "Day 3-4 covers the Stem phase generally.",
                "title": "SKILL.md",
                "source_path": "/skills/x.md",
            },
            # Correct chunk: lower vector score but substring match.
            {
                "l3_id": "correct-l3",
                "score": 0.65,
                "snippet": "(question text irrelevant here)",
                "surrounding_context": f"Day 3-4 Stem: Logic-Xylem Flow — Relationship Mapping: {excerpt}.  More flow.",
                "title": "SKILL.md",
                "source_path": "/skills/code/expansion.md",
            },
        ],
        "request_id": "r-override",
    }
    settings = SimpleNamespace(
        qrel_resolve_search_detail="full",
        qrel_resolve_max_hits_to_score=20,
        qrel_resolve_min_vector_score=0.25,
        qrel_resolve_min_combined_score=0.35,
        qrel_resolve_substring_override=True,
        qrel_resolve_substring_min_len=40,
    )
    qr = Qrel(
        dataset_id="d", query_id="q",
        target_id=None, target_type="l3_id", relevance=1,
        target_data={"excerpt": excerpt},
        resolution_status="unresolved",
    )
    out = resolve_single_qrel(client, query_text="3가지 relationship", project_id=None, qrel=qr, settings=settings)
    assert out["ok"] is True
    assert out["target_id"] == "correct-l3"
    assert out["resolution_meta"]["resolution_method"] == "substring_override"


def test_substring_override_ambiguous_falls_through():
    """When >1 hit has substring match, override is skipped — vector
    scoring decides as before."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from gardener_gopedia.ingest.client import GopediaClient
    from gardener_gopedia.eval.qrel_resolve import resolve_single_qrel

    excerpt = "this phrase appears in two chunks one of which is wrong" * 2
    client = MagicMock(spec=GopediaClient)
    client.search_json.return_value = {
        "results": [
            {
                "l3_id": "chunk-a",
                "score": 0.50,
                "snippet": "s",
                "surrounding_context": f"...{excerpt}... in document A",
                "title": "A",
                "source_path": "/a.md",
            },
            {
                "l3_id": "chunk-b",
                "score": 0.70,
                "snippet": "s",
                "surrounding_context": f"document B copy: {excerpt}.",
                "title": "B",
                "source_path": "/b.md",
            },
        ],
        "request_id": "r",
    }
    settings = SimpleNamespace(
        qrel_resolve_search_detail="full",
        qrel_resolve_max_hits_to_score=20,
        qrel_resolve_min_vector_score=0.25,
        qrel_resolve_min_combined_score=0.35,
        qrel_resolve_substring_override=True,
        qrel_resolve_substring_min_len=40,
    )
    qr = Qrel(
        dataset_id="d", query_id="q",
        target_id=None, target_type="l3_id", relevance=1,
        target_data={"excerpt": excerpt},
        resolution_status="unresolved",
    )
    out = resolve_single_qrel(client, query_text="anything", project_id=None, qrel=qr, settings=settings)
    # Falls through to vector + bonus; chunk-b wins on vector
    assert out["ok"] is True
    assert out["target_id"] == "chunk-b"
    assert out["resolution_meta"]["resolution_method"] == "vector_plus_bonus"


def test_substring_override_disabled_demonstrates_vector_gap_loss():
    """When override is disabled and the vector score gap is large
    enough, the wrong chunk wins despite the right chunk having a
    substring match in surrounding_context.  This captures the
    v0.22.x failure mode the override fixes — guard against
    accidental disable in the future."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from gardener_gopedia.ingest.client import GopediaClient
    from gardener_gopedia.eval.qrel_resolve import resolve_single_qrel

    excerpt = "this excerpt only in chunk B" * 3
    client = MagicMock(spec=GopediaClient)
    client.search_json.return_value = {
        "results": [
            {
                "l3_id": "high-score-wrong",
                "score": 0.95,
                "snippet": "(no excerpt)",
                "surrounding_context": "completely different content",
                "title": "A",
                "source_path": "/a.md",
            },
            {
                "l3_id": "right-chunk",
                "score": 0.55,
                "snippet": "(no excerpt)",
                "surrounding_context": f"context here: {excerpt}",
                "title": "B",
                "source_path": "/b.md",
            },
        ],
        "request_id": "r",
    }
    settings = SimpleNamespace(
        qrel_resolve_search_detail="full",
        qrel_resolve_max_hits_to_score=20,
        qrel_resolve_min_vector_score=0.25,
        qrel_resolve_min_combined_score=0.35,
        qrel_resolve_substring_override=False,  # disabled
        qrel_resolve_substring_min_len=40,
    )
    qr = Qrel(
        dataset_id="d", query_id="q",
        target_id=None, target_type="l3_id", relevance=1,
        target_data={"excerpt": excerpt},
        resolution_status="unresolved",
    )
    out = resolve_single_qrel(client, query_text="q", project_id=None, qrel=qr, settings=settings)
    # right-chunk: 0.55 vec + 0.25 substring bonus = 0.80
    # high-score-wrong: 0.95 vec + 0.0 bonus = 0.95
    # → vector gap > combined bonus → wrong chunk wins (the v0.22.x bug)
    assert out["ok"] is True
    assert out["target_id"] == "high-score-wrong"  # demonstrates failure mode
    assert out["resolution_meta"]["resolution_method"] == "vector_plus_bonus"
