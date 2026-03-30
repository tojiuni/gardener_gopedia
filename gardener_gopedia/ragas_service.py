"""Optional Ragas LLM evaluation (retrieval + phase-2 answer metrics)."""

from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from gardener_gopedia.config import get_settings
from gardener_gopedia.models import Dataset, DatasetQuery, EvalRun, RunHit, RunMetric, RunRagasSample

logger = logging.getLogger(__name__)


def _finite_float(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if not math.isfinite(v) else v


def _hits_by_query(db: Session, eval_run_id: str) -> dict[str, list[RunHit]]:
    hits = (
        db.query(RunHit)
        .filter(RunHit.eval_run_id == eval_run_id)
        .order_by(RunHit.dataset_query_id, RunHit.rank)
        .all()
    )
    by_q: dict[str, list[RunHit]] = defaultdict(list)
    for h in hits:
        by_q[h.dataset_query_id].append(h)
    return by_q


def _context_strings(hits: list[RunHit]) -> list[str]:
    out: list[str] = []
    for h in hits:
        parts: list[str] = []
        if h.title:
            parts.append(str(h.title))
        if h.snippet:
            parts.append(str(h.snippet))
        if not parts:
            parts.append(str(h.target_id))
        out.append("\n".join(parts))
    return out


def _build_openai_llm():
    from openai import OpenAI
    from ragas.llms import llm_factory

    settings = get_settings()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY not set"
    client = OpenAI(api_key=api_key)
    llm = llm_factory(settings.ragas_openai_model, client=client, temperature=0.01)
    return llm, None


def _generate_answer(*, question: str, contexts: list[str]) -> str:
    from openai import OpenAI

    settings = get_settings()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ""
    client = OpenAI(api_key=api_key)
    ctx_block = "\n\n---\n\n".join(contexts[:15])
    resp = client.chat.completions.create(
        model=settings.ragas_openai_model,
        temperature=0,
        max_tokens=512,
        messages=[
            {
                "role": "system",
                "content": "Answer the question using only the provided context. If the context is insufficient, say so briefly.",
            },
            {
                "role": "user",
                "content": f"Context:\n{ctx_block}\n\nQuestion: {question}\n\nAnswer:",
            },
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def maybe_run_ragas_after_eval(db: Session, eval_run: EvalRun) -> dict[str, Any]:
    """
    Run Ragas metrics after IR hits are committed. Never raises; returns stats for params_json.
    """
    params = dict(eval_run.params_json or {})
    if not params.get("ragas_enabled"):
        return {}

    summary: dict[str, Any] = {"ragas_ran": True}

    try:
        from datasets import Dataset as HFDataset
        from ragas import evaluate
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecisionWithoutReference,
            ContextRecall,
            ContextRelevance,
            Faithfulness,
        )
    except ImportError as e:
        logger.warning("Ragas not installed: %s", e)
        summary["ragas_error"] = "ragas_optional_dependency_missing"
        return summary

    llm, err = _build_openai_llm()
    if not llm:
        logger.warning("Ragas skipped: %s", err)
        summary["ragas_skipped"] = err or "no_llm"
        return summary

    settings = get_settings()
    dataset = db.get(Dataset, eval_run.dataset_id)
    if not dataset:
        return summary

    queries = (
        db.query(DatasetQuery)
        .filter(DatasetQuery.dataset_id == eval_run.dataset_id)
        .order_by(DatasetQuery.external_id)
        .all()
    )
    by_hits = _hits_by_query(db, eval_run.id)

    rows_retrieval: list[dict[str, Any]] = []
    q_order: list[str] = []  # dataset_query ids in row order
    for dq in queries:
        ctxs = _context_strings(by_hits.get(dq.id, []))
        if not ctxs:
            continue
        rows_retrieval.append({"user_input": dq.query_text, "retrieved_contexts": ctxs})
        q_order.append(dq.id)

    if not rows_retrieval:
        summary["ragas_skipped"] = "no_retrieved_contexts"
        db.add(
            RunMetric(
                eval_run_id=eval_run.id,
                metric_name="ragas/status",
                value=0.0,
                scope="aggregate",
                details_json={"message": "no contexts for any query"},
            )
        )
        db.flush()
        return summary

    hf_ds = HFDataset.from_list(rows_retrieval)
    metrics_p1 = [ContextRelevance(llm=llm)]
    try:
        res_p1 = evaluate(
            hf_ds,
            metrics=metrics_p1,
            llm=llm,
            show_progress=settings.ragas_show_progress,
            raise_exceptions=False,
            batch_size=settings.ragas_batch_size,
        )
    except Exception as e:
        logger.exception("Ragas phase-1 failed")
        summary["ragas_error"] = str(e)[:2000]
        db.add(
            RunMetric(
                eval_run_id=eval_run.id,
                metric_name="ragas/error",
                value=0.0,
                scope="aggregate",
                details_json={"phase": "retrieval", "error": str(e)[:2000]},
            )
        )
        db.flush()
        return summary

    # Map scores back to query ids
    p1_scores = res_p1.scores
    metric_keys = list(p1_scores[0].keys()) if p1_scores else []
    cr_key = "context_relevance" if "context_relevance" in (metric_keys or []) else (metric_keys[0] if metric_keys else "context_relevance")

    per_query_phoenix: list[dict[str, Any]] = []
    cr_vals: list[float] = []
    for i, qid in enumerate(q_order):
        row_score = p1_scores[i] if i < len(p1_scores) else {}
        raw = row_score.get(cr_key, float("nan"))
        val = _finite_float(raw)
        cr_vals.append(val)
        dq = next((q for q in queries if q.id == qid), None)
        ext = dq.external_id if dq else qid
        tier = dq.tier if dq else None
        qtext = dq.query_text if dq else ""
        details: dict[str, Any] = {}
        if isinstance(raw, float) and math.isnan(raw):
            details["note"] = "metric_nan"
        db.add(
            RunMetric(
                eval_run_id=eval_run.id,
                metric_name="ragas/context_relevance",
                value=val,
                scope="per_query",
                dataset_query_id=qid,
                details_json=details or None,
            )
        )
        per_query_phoenix.append(
            {
                "external_id": ext,
                "tier": tier or "",
                "query_text": qtext,
                "metrics": {"context_relevance": val},
            }
        )

    if cr_vals:
        mean_cr = sum(cr_vals) / len(cr_vals)
        db.add(
            RunMetric(
                eval_run_id=eval_run.id,
                metric_name="ragas/context_relevance",
                value=mean_cr,
                scope="aggregate",
            )
        )

    # Phase 2: answer metrics
    if params.get("ragas_answer_metrics"):
        emb = None
        try:
            from openai import OpenAI
            from ragas.embeddings.base import embedding_factory

            oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            emb = embedding_factory(
                "openai",
                model=settings.ragas_embedding_model,
                client=oai,
            )
        except Exception as e:
            logger.warning("Embedding factory failed (answer metrics may skip AnswerRelevancy): %s", e)

        ans_rows: list[dict[str, Any]] = []
        ans_qids: list[str] = []
        recall_rows: list[dict[str, Any]] = []
        recall_qids: list[str] = []

        for dq in queries:
            ctxs = _context_strings(by_hits.get(dq.id, []))
            if not ctxs:
                continue
            gen = _generate_answer(question=dq.query_text, contexts=ctxs)
            _upsert_ragas_sample(db, eval_run.id, dq.id, gen or None)
            if not gen:
                continue
            ans_rows.append(
                {
                    "user_input": dq.query_text,
                    "response": gen,
                    "retrieved_contexts": ctxs,
                }
            )
            ans_qids.append(dq.id)
            ref = (dq.reference_answer or "").strip()
            if ref:
                recall_rows.append(
                    {
                        "user_input": dq.query_text,
                        "retrieved_contexts": ctxs,
                        "reference": ref,
                    }
                )
                recall_qids.append(dq.id)

        metrics_p2: list[Any] = [
            Faithfulness(llm=llm),
            ContextPrecisionWithoutReference(llm=llm),
        ]
        if emb is not None:
            metrics_p2.append(AnswerRelevancy(llm=llm, embeddings=emb))

        if ans_rows:
            try:
                res_p2 = evaluate(
                    HFDataset.from_list(ans_rows),
                    metrics=metrics_p2,
                    llm=llm,
                    embeddings=emb if emb is not None else None,
                    show_progress=settings.ragas_show_progress,
                    raise_exceptions=False,
                    batch_size=settings.ragas_batch_size,
                )
                _store_phase2_scores(
                    db,
                    eval_run.id,
                    res_p2.scores,
                    ans_qids,
                    per_query_phoenix,
                    queries,
                )
            except Exception as e:
                logger.exception("Ragas phase-2 failed")
                summary["ragas_phase2_error"] = str(e)[:2000]

        if recall_rows:
            try:
                res_r = evaluate(
                    HFDataset.from_list(recall_rows),
                    metrics=[ContextRecall(llm=llm)],
                    llm=llm,
                    show_progress=settings.ragas_show_progress,
                    raise_exceptions=False,
                    batch_size=settings.ragas_batch_size,
                )
                _store_recall_scores(db, eval_run.id, res_r.scores, recall_qids, per_query_phoenix, queries)
            except Exception as e:
                logger.exception("Ragas context_recall failed")
                summary["ragas_recall_error"] = str(e)[:2000]

    db.flush()

    # Merge Phoenix metrics into per_query_phoenix (IR)
    _attach_ir_to_phoenix(db, eval_run.id, per_query_phoenix, queries)

    try:
        from gardener_gopedia.phoenix_adapter import export_eval_run_to_phoenix

        export_eval_run_to_phoenix(
            eval_run_id=eval_run.id,
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            git_sha=eval_run.git_sha,
            index_version=eval_run.index_version,
            per_query=per_query_phoenix,
        )
    except Exception:
        logger.exception("Phoenix export failed")

    return summary


def _upsert_ragas_sample(db: Session, eval_run_id: str, dq_id: str, text: str | None) -> None:
    existing = (
        db.query(RunRagasSample)
        .filter(
            RunRagasSample.eval_run_id == eval_run_id,
            RunRagasSample.dataset_query_id == dq_id,
        )
        .one_or_none()
    )
    if existing:
        existing.generated_response = text
    else:
        db.add(
            RunRagasSample(
                eval_run_id=eval_run_id,
                dataset_query_id=dq_id,
                generated_response=text,
            )
        )


def _store_phase2_scores(
    db: Session,
    eval_run_id: str,
    scores: list[dict[str, Any]],
    qids: list[str],
    per_query_phoenix: list[dict[str, Any]],
    queries: list[DatasetQuery],
) -> None:
    keys = list(scores[0].keys()) if scores else []
    for i, qid in enumerate(qids):
        row = scores[i] if i < len(scores) else {}
        merged: dict[str, float] = {}
        for mk in keys:
            val = _finite_float(row.get(mk))
            merged[mk] = val
            db.add(
                RunMetric(
                    eval_run_id=eval_run_id,
                    metric_name=f"ragas/{mk}",
                    value=val,
                    scope="per_query",
                    dataset_query_id=qid,
                )
            )
        _merge_phoenix_row(per_query_phoenix, queries, qid, merged)
    # Aggregate means for phase-2 metrics
    if keys and qids:
        for mk in keys:
            vals = []
            for i in range(min(len(scores), len(qids))):
                vals.append(_finite_float(scores[i].get(mk)))
            if vals:
                db.add(
                    RunMetric(
                        eval_run_id=eval_run_id,
                        metric_name=f"ragas/{mk}",
                        value=sum(vals) / len(vals),
                        scope="aggregate",
                    )
                )


def _store_recall_scores(
    db: Session,
    eval_run_id: str,
    scores: list[dict[str, Any]],
    qids: list[str],
    per_query_phoenix: list[dict[str, Any]],
    queries: list[DatasetQuery],
) -> None:
    key = "context_recall"
    recall_vals: list[float] = []
    for i, qid in enumerate(qids):
        row = scores[i] if i < len(scores) else {}
        val = _finite_float(row.get(key))
        recall_vals.append(val)
        db.add(
            RunMetric(
                eval_run_id=eval_run_id,
                metric_name="ragas/context_recall",
                value=val,
                scope="per_query",
                dataset_query_id=qid,
            )
        )
        _merge_phoenix_row(per_query_phoenix, queries, qid, {key: val})
    if recall_vals:
        db.add(
            RunMetric(
                eval_run_id=eval_run_id,
                metric_name="ragas/context_recall",
                value=sum(recall_vals) / len(recall_vals),
                scope="aggregate",
            )
        )


def _merge_phoenix_row(
    per_query_phoenix: list[dict[str, Any]],
    queries: list[DatasetQuery],
    qid: str,
    metrics: dict[str, float],
) -> None:
    dq = next((q for q in queries if q.id == qid), None)
    ext = dq.external_id if dq else ""
    for row in per_query_phoenix:
        if row.get("external_id") == ext:
            m = dict(row.get("metrics") or {})
            m.update(metrics)
            row["metrics"] = m
            return


def _attach_ir_to_phoenix(
    db: Session,
    eval_run_id: str,
    per_query_phoenix: list[dict[str, Any]],
    queries: list[DatasetQuery],
) -> None:
    from gardener_gopedia.metrics_engine import per_query_recall_at_5
    from gardener_gopedia.models import Qrel

    if not queries:
        return
    qrels_rows = db.query(Qrel).filter(Qrel.dataset_id == queries[0].dataset_id).all()
    qrels_tuples = [(q.query_id, q.target_id, q.relevance) for q in qrels_rows]
    hits = (
        db.query(RunHit)
        .filter(RunHit.eval_run_id == eval_run_id)
        .order_by(RunHit.dataset_query_id, RunHit.rank)
        .all()
    )
    runs_tuples = [(h.dataset_query_id, h.target_id, h.score) for h in hits]
    per_r = per_query_recall_at_5(qrels_tuples, runs_tuples, preserve_input_order=True)
    ext_by_id = {q.id: q.external_id for q in queries}
    for row in per_query_phoenix:
        ext = row.get("external_id")
        qid = next((i for i, e in ext_by_id.items() if e == ext), None)
        if qid and qid in per_r:
            m = dict(row.get("metrics") or {})
            m["ir_recall_at_5"] = float(per_r[qid])
            row["metrics"] = m
