"""Curation: agent routing, batch lifecycle, Gold promotion."""

import pytest

from gardener_gopedia.curation.agent_contract import AgentCandidateItem, AgentQueryProposal, pick_auto_accept_candidate
from gardener_gopedia.curation.service import (
    DECISION_AUTO_ACCEPTED,
    DECISION_HUMAN_ACCEPTED,
    DECISION_UNRESOLVED,
    apply_human_decision,
    create_batch_with_proposals,
    list_queue,
    promote_batch_to_gold,
)
from gardener_gopedia.core.models import Dataset, DatasetQuery, LabelCandidate, LabelDecision, Qrel


def test_pick_auto_accept_single_high_confidence():
    cands = [
        AgentCandidateItem(
            target_id="a",
            confidence=0.95,
            model_name="m1",
        )
    ]
    got = pick_auto_accept_candidate(
        cands,
        single_min_conf=0.9,
        consensus_min_models=2,
        consensus_min_conf=0.7,
    )
    assert got is not None and got.target_id == "a"


def test_pick_auto_accept_consensus_two_models():
    cands = [
        AgentCandidateItem(target_id="x", confidence=0.8, model_name="m1"),
        AgentCandidateItem(target_id="x", confidence=0.75, model_name="m2"),
    ]
    got = pick_auto_accept_candidate(
        cands,
        single_min_conf=0.9,
        consensus_min_models=2,
        consensus_min_conf=0.7,
    )
    assert got is not None and got.target_id == "x"


def test_pick_auto_accept_none_when_low_confidence():
    cands = [
        AgentCandidateItem(target_id="a", confidence=0.5, model_name="m1"),
    ]
    got = pick_auto_accept_candidate(
        cands,
        single_min_conf=0.9,
        consensus_min_models=2,
        consensus_min_conf=0.7,
    )
    assert got is None


def _seed_dataset(sess, n_queries: int = 2):
    ds = Dataset(name="bronze", version="1", curation_tier="bronze")
    sess.add(ds)
    sess.flush()
    dqs = []
    for i in range(n_queries):
        dq = DatasetQuery(dataset_id=ds.id, external_id=f"q{i}", query_text=f"text {i}")
        sess.add(dq)
        sess.flush()
        dqs.append(dq)
    sess.commit()
    sess.refresh(ds)
    return ds, dqs


def test_create_batch_auto_and_unresolved(memory_session):
    ds, dqs = _seed_dataset(memory_session)
    props = [
        AgentQueryProposal(
            dataset_query_id=dqs[0].id,
            candidates=[
                AgentCandidateItem(target_id="t1", confidence=0.95, model_name="a"),
            ],
        ),
        AgentQueryProposal(
            dataset_query_id=dqs[1].id,
            candidates=[
                AgentCandidateItem(target_id="t2", confidence=0.5, model_name="a"),
            ],
        ),
    ]
    batch = create_batch_with_proposals(
        memory_session,
        dataset_id=ds.id,
        source_eval_run_id=None,
        external_key="k1",
        provenance_json=None,
        proposals=props,
        include_unlisted_queries=False,
    )

    memory_session.expire_all()
    decs = memory_session.query(LabelDecision).filter(LabelDecision.labeling_batch_id == batch.id).all()
    by_q = {d.dataset_query_id: d for d in decs}
    assert by_q[dqs[0].id].status == DECISION_AUTO_ACCEPTED
    assert by_q[dqs[1].id].status == DECISION_UNRESOLVED

    q = list_queue(memory_session, batch.id)
    assert len(q) == 1
    assert q[0]["dataset_query_id"] == dqs[1].id


def test_create_batch_include_unlisted(memory_session):
    ds, dqs = _seed_dataset(memory_session, n_queries=2)
    props = [
        AgentQueryProposal(
            dataset_query_id=dqs[0].id,
            candidates=[AgentCandidateItem(target_id="t1", confidence=0.95, model_name="a")],
        ),
    ]
    batch = create_batch_with_proposals(
        memory_session,
        dataset_id=ds.id,
        external_key=None,
        source_eval_run_id=None,
        provenance_json=None,
        proposals=props,
        include_unlisted_queries=True,
    )
    n = memory_session.query(LabelDecision).filter(LabelDecision.labeling_batch_id == batch.id).count()
    assert n == 2


def test_promote_gold_after_resolve(memory_session):
    ds, dqs = _seed_dataset(memory_session, n_queries=1)
    props = [
        AgentQueryProposal(
            dataset_query_id=dqs[0].id,
            candidates=[AgentCandidateItem(target_id="t1", confidence=0.5, model_name="a")],
        ),
    ]
    batch = create_batch_with_proposals(
        memory_session,
        dataset_id=ds.id,
        external_key=None,
        source_eval_run_id=None,
        provenance_json=None,
        proposals=props,
        include_unlisted_queries=False,
    )
    apply_human_decision(
        memory_session,
        batch.id,
        dataset_query_id=dqs[0].id,
        action="set_target",
        target_id="gold-t",
        target_type="l3_id",
        reviewer="tester",
    )
    gold = promote_batch_to_gold(memory_session, batch.id, new_version="2")
    assert gold.curation_tier == "gold"
    assert gold.parent_dataset_id == ds.id
    qrels = memory_session.query(Qrel).filter(Qrel.dataset_id == gold.id).all()
    assert len(qrels) == 1
    assert qrels[0].target_id == "gold-t"


def test_promote_copies_parent_qrel_on_reject(memory_session):
    ds, dqs = _seed_dataset(memory_session, n_queries=1)
    memory_session.add(
        Qrel(
            dataset_id=ds.id,
            query_id=dqs[0].id,
            target_id="parent-rel",
            target_type="l3_id",
            relevance=1,
        )
    )
    memory_session.commit()
    props = [
        AgentQueryProposal(dataset_query_id=dqs[0].id, candidates=[]),
    ]
    batch = create_batch_with_proposals(
        memory_session,
        dataset_id=ds.id,
        external_key=None,
        source_eval_run_id=None,
        provenance_json=None,
        proposals=props,
        include_unlisted_queries=False,
    )
    apply_human_decision(
        memory_session,
        batch.id,
        dataset_query_id=dqs[0].id,
        action="reject",
        reviewer="t",
    )
    gold = promote_batch_to_gold(
        memory_session,
        batch.id,
        new_version="g1",
        copy_parent_qrels_when_no_decision_target=True,
    )
    qrels = memory_session.query(Qrel).filter(Qrel.dataset_id == gold.id).all()
    assert len(qrels) == 1
    assert qrels[0].target_id == "parent-rel"


def test_human_accept_updates_decision(memory_session):
    ds, dqs = _seed_dataset(memory_session, n_queries=1)
    props = [
        AgentQueryProposal(
            dataset_query_id=dqs[0].id,
            candidates=[AgentCandidateItem(target_id="c1", confidence=0.5, model_name="m")],
        ),
    ]
    batch = create_batch_with_proposals(
        memory_session,
        dataset_id=ds.id,
        external_key=None,
        source_eval_run_id=None,
        provenance_json=None,
        proposals=props,
    )
    memory_session.expire_all()
    cand = (
        memory_session.query(LabelCandidate).filter_by(labeling_batch_id=batch.id).first()
    )
    dec = apply_human_decision(
        memory_session,
        batch.id,
        dataset_query_id=dqs[0].id,
        action="accept_candidate",
        candidate_id=cand.id,
        reviewer="h",
    )
    assert dec.status == DECISION_HUMAN_ACCEPTED
    assert dec.chosen_target_id == "c1"
