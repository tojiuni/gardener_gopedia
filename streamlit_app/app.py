"""Streamlit review UI for Gardener Gopedia."""

from __future__ import annotations

import os

import httpx
import streamlit as st

GARDENER = os.environ.get("GARDENER_API_URL", "http://127.0.0.1:18880").rstrip("/")

st.set_page_config(page_title="Gardener Review", layout="wide")
st.title("Gardener Gopedia — review")

tab_eval, tab_curation = st.tabs(["Eval run", "Curation queue (AI + human)"])

with tab_eval:
    run_id = st.text_input("Eval run ID", value="", key="eval_run_id")

    if st.button("Load run", key="load_run") and run_id:
        with httpx.Client(timeout=60.0) as c:
            r = c.get(f"{GARDENER}/runs/{run_id}")
            r.raise_for_status()
            run_j = r.json()
            st.json(run_j)
            trace_url = (run_j or {}).get("langfuse_trace_url")
            if trace_url:
                st.markdown(f"[Open Langfuse trace]({trace_url})")

            r2 = c.get(f"{GARDENER}/runs/{run_id}/queries")
            r2.raise_for_status()
            rows = r2.json()

        st.subheader("Per-query hits")
        for row in rows:
            qpreview = row["query_text"][:80] if len(row["query_text"]) > 80 else row["query_text"]
            tier = row.get("tier") or ""
            label = f"{row['external_id']}: {qpreview}"
            if tier:
                label = f"[{tier}] {label}"
            with st.expander(label):
                if row.get("reference_answer"):
                    st.caption("reference_answer")
                    st.text(row["reference_answer"][:2000])
                if row.get("ragas_generated_response"):
                    st.caption("Ragas generated response (phase 2)")
                    st.text(row["ragas_generated_response"][:2000])
                st.write("metrics:", row.get("metrics"))
                for m in row.get("metrics") or []:
                    det = m.get("details_json")
                    if m.get("metric_name", "").startswith("ragas/") and det:
                        with st.popover(f"details: {m['metric_name']}"):
                            st.json(det)
                st.dataframe(row.get("hits", []))

    st.divider()
    st.subheader("Submit review (legacy)")
    if run_id:
        dq = st.text_input("dataset_query_id", key="dq")
        label = st.selectbox(
            "label",
            ["ranking_issue", "missing_context", "ingest_gap", "query_mismatch", "other"],
            key="lbl",
        )
        notes = st.text_area("notes", key="notes")
        reviewer = st.text_input("reviewer", value="local", key="rev")
        if st.button("Save review", key="save_rev") and dq:
            with httpx.Client(timeout=30.0) as c:
                r = c.post(
                    f"{GARDENER}/reviews",
                    json={
                        "eval_run_id": run_id,
                        "dataset_query_id": dq,
                        "label": label,
                        "notes": notes or None,
                        "reviewer": reviewer or None,
                    },
                )
                st.json(r.json())
    else:
        st.info("Enter an eval run ID above to submit reviews.")

with tab_curation:
    st.caption("Resolve AI proposals: queue from GET /curation/batches/{id}/queue")
    batch_id = st.text_input("Labeling batch ID", value="", key="batch_id")
    mirror_run = st.text_input(
        "Optional: mirror to eval_run_id (posts /reviews on decision)",
        value="",
        key="mirror_run",
    )

    if st.button("Load queue", key="load_queue") and batch_id:
        with httpx.Client(timeout=60.0) as c:
            r = c.get(f"{GARDENER}/curation/batches/{batch_id}/queue")
            if r.status_code >= 400:
                st.error(r.text)
            else:
                st.session_state["curation_queue"] = r.json()
                st.success(f"{len(st.session_state['curation_queue'])} unresolved item(s)")

    queue = st.session_state.get("curation_queue") or []
    reviewer_c = st.text_input("Reviewer (curation)", value="local", key="rev_c")

    for item in queue:
        qid = item.get("dataset_query_id", "")
        ext = item.get("external_id", "")
        qtext = item.get("query_text", "")
        st.subheader(f"{ext or qid[:8]}…")
        st.write(qtext[:500])
        st.caption(f"dataset_query_id: `{qid}` · priority_score: {item.get('priority_score')}")
        cands = item.get("candidates") or []
        if cands:
            labels = [
                f"#{c.get('candidate_rank')} {c.get('target_id')[:12]}… conf={c.get('confidence')} ({c.get('model_name')})"
                for c in cands
            ]
            pick = st.selectbox(
                "Pick candidate to accept",
                range(len(cands)),
                format_func=lambda i: labels[i],
                key=f"pick_{qid}",
            )
            if st.button("Accept selected candidate", key=f"acc_{qid}"):
                cid = cands[pick]["id"]
                body = {
                    "dataset_query_id": qid,
                    "action": "accept_candidate",
                    "candidate_id": cid,
                    "reviewer": reviewer_c or None,
                    "mirror_review_eval_run_id": mirror_run.strip() or None,
                    "review_label": "curation_accept_candidate",
                }
                with httpx.Client(timeout=30.0) as c:
                    r = c.post(f"{GARDENER}/curation/batches/{batch_id}/decisions", json=body)
                    st.json(r.json())
        col1, col2 = st.columns(2)
        with col1:
            manual_tid = st.text_input("Manual target_id", key=f"mt_{qid}", value="")
            manual_ttype = st.selectbox("target_type", ["l3_id", "doc_id"], key=f"mtt_{qid}")
            if st.button("Set manual target", key=f"set_{qid}") and manual_tid.strip():
                body = {
                    "dataset_query_id": qid,
                    "action": "set_target",
                    "target_id": manual_tid.strip(),
                    "target_type": manual_ttype,
                    "reviewer": reviewer_c or None,
                    "mirror_review_eval_run_id": mirror_run.strip() or None,
                    "review_label": "curation_set_target",
                }
                with httpx.Client(timeout=30.0) as c:
                    r = c.post(f"{GARDENER}/curation/batches/{batch_id}/decisions", json=body)
                    st.json(r.json())
        with col2:
            if st.button("Reject (no gold target)", key=f"rej_{qid}"):
                body = {
                    "dataset_query_id": qid,
                    "action": "reject",
                    "reviewer": reviewer_c or None,
                    "mirror_review_eval_run_id": mirror_run.strip() or None,
                    "review_label": "curation_reject",
                }
                with httpx.Client(timeout=30.0) as c:
                    r = c.post(f"{GARDENER}/curation/batches/{batch_id}/decisions", json=body)
                    st.json(r.json())
            if st.button("No target / cannot determine", key=f"nt_{qid}"):
                body = {
                    "dataset_query_id": qid,
                    "action": "no_target",
                    "reviewer": reviewer_c or None,
                    "mirror_review_eval_run_id": mirror_run.strip() or None,
                    "review_label": "curation_no_target",
                }
                with httpx.Client(timeout=30.0) as c:
                    r = c.post(f"{GARDENER}/curation/batches/{batch_id}/decisions", json=body)
                    st.json(r.json())
        with st.expander("Candidates JSON"):
            st.json(cands)
        st.divider()

    st.subheader("Promote batch to Gold dataset")
    new_ver = st.text_input("New dataset version", value="gold-1", key="new_ver")
    ds_name = st.text_input("Optional new name (default: same as parent)", value="", key="ds_name")
    if st.button("Promote", key="promote") and batch_id:
        body = {
            "new_version": new_ver.strip() or "gold-1",
            "name": ds_name.strip() or None,
            "copy_parent_qrels_when_no_decision_target": True,
        }
        with httpx.Client(timeout=60.0) as c:
            r = c.post(f"{GARDENER}/curation/batches/{batch_id}/promote", json=body)
            if r.status_code >= 400:
                st.error(r.text)
            else:
                st.success("Promoted")
                st.json(r.json())
