"""Streamlit review UI for Gardener Gopedia."""

from __future__ import annotations

import os

import httpx
import streamlit as st

GARDENER = os.environ.get("GARDENER_API_URL", "http://127.0.0.1:18880").rstrip("/")

st.set_page_config(page_title="Gardener Review", layout="wide")
st.title("Gardener Gopedia — review")

run_id = st.text_input("Eval run ID", value="")

if st.button("Load run") and run_id:
    with httpx.Client(timeout=60.0) as c:
        r = c.get(f"{GARDENER}/runs/{run_id}")
        r.raise_for_status()
        st.json(r.json())

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
st.subheader("Submit review")
if run_id:
    dq = st.text_input("dataset_query_id", key="dq")
    label = st.selectbox(
        "label",
        ["ranking_issue", "missing_context", "ingest_gap", "query_mismatch", "other"],
        key="lbl",
    )
    notes = st.text_area("notes", key="notes")
    reviewer = st.text_input("reviewer", value="local", key="rev")
    if st.button("Save review") and dq:
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
    st.info("Enter a run ID above to submit reviews.")
