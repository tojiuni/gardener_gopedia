from unittest.mock import patch

import pytest

from gardener_gopedia.eval.service import execute_eval_run
from gardener_gopedia.core.models import Dataset, DatasetQuery, EvalRun, RunStatus


def _seed_eval(sess):
    ds = Dataset(name="t", version="1")
    sess.add(ds)
    sess.flush()
    dq = DatasetQuery(dataset_id=ds.id, external_id="q1", query_text="hello")
    sess.add(dq)
    sess.commit()
    er = EvalRun(
        dataset_id=ds.id,
        target_url="http://gopedia.test",
        params_json={
            "top_k": 5,
            "query_timeout_s": 10.0,
            "skip_if_ingest_failed": True,
            "search_retryable_max_attempts": 2,
        },
        status=RunStatus.pending.value,
    )
    sess.add(er)
    sess.commit()
    sess.refresh(er)
    return er.id


@patch("gardener_gopedia.evaluation_service.GopediaClient")
def test_execute_eval_ok_false_counts_failure(mock_client_cls, memory_session):
    run_id = _seed_eval(memory_session)
    inst = mock_client_cls.return_value
    inst.search_json.return_value = {"ok": False, "results": [], "_latency_ms": 1}

    execute_eval_run(memory_session, run_id)

    memory_session.refresh(memory_session.get(EvalRun, run_id))
    er = memory_session.get(EvalRun, run_id)
    assert er.status == RunStatus.completed.value
    assert er.params_json.get("failure_count") == 1
    inst.search_json.assert_called_once()


@patch("gardener_gopedia.evaluation_service.GopediaClient")
@patch("gardener_gopedia.evaluation_service.time.sleep", return_value=None)
def test_execute_eval_retryable_then_success(mock_sleep, mock_client_cls, memory_session):
    run_id = _seed_eval(memory_session)
    inst = mock_client_cls.return_value
    inst.search_json.side_effect = [
        {"failure": {"retryable": True}, "results": [], "_latency_ms": 1},
        {"results": [{"l3_id": "doc1", "score": 0.9}], "_latency_ms": 1},
    ]

    execute_eval_run(memory_session, run_id)

    er = memory_session.get(EvalRun, run_id)
    assert er.status == RunStatus.completed.value
    assert er.params_json.get("failure_count") == 0
    assert inst.search_json.call_count == 2
    mock_sleep.assert_called()
