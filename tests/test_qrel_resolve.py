"""Qrel target_data resolution and eval guards."""

import pytest

from gardener_gopedia.evaluation_service import execute_eval_run
from gardener_gopedia.core.models import Dataset, DatasetQuery, EvalRun, Qrel, RunStatus
from gardener_gopedia.qrel_resolve_service import (
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
