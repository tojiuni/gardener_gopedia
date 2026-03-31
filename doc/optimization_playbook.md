# Optimization playbook (quality + token cost)

Use Langfuse traces and Gardener KPI endpoints to iterate on Gopedia search and optional LLM judging.

## Measure

1. Run a baseline eval with stable `dataset_id`, `top_k`, `search_detail` / `search_fields`, and record `git_sha` / `index_version` on `POST /runs`.
2. Open `langfuse_trace_url` from `GET /runs/{id}` when `GARDENER_LANGFUSE_ENABLED=true`.
3. Pull rollups: `GET /runs/{id}/kpi-summary`.
4. Rank expensive low-quality queries: `GET /runs/{id}/kpi-roi-queries?sort=worst_roi`.

## Interpret KPIs

- **Quality:** `Recall@5` (per query + mean in summary), Ragas metrics when enabled (`ragas/*`).
- **Efficiency:** `efficiency/*` token metrics, `cost/*` USD estimates (OpenAI pricing table in `gardener_gopedia/cost_tokens.py` — extend for your models).
- **Latency:** `latency/search_ms` (Gopedia), `latency/llm_ms` (answer generation for Ragas phase 2).

Ragas judge calls inside `ragas.evaluate()` do not expose per-call usage; Gardener records a **rough** `efficiency/ragas_estimated_tokens` and `cost/ragas_estimated_usd` budget per query. Phase-2 `_generate_answer` uses **measured** OpenAI usage.

## Tune (retrieval)

- Adjust `top_k`, `search_detail`, `search_fields`, and Gopedia-side index settings.
- Re-run eval with the same dataset; compare `GET /compare` and KPI summaries.

## Tune (LLM / Ragas)

- Change `GARDENER_RAGAS_OPENAI_MODEL` or disable phase-2 answer metrics if cost dominates.
- Trim context: reduce snippets shown to the judge by changing Gopedia `detail` / `fields` so Ragas sees shorter `retrieved_contexts`.

## Tune (prompts)

- Keep system instructions stable across A/B runs so `langfuse` score deltas are attributable to retrieval or model changes.
- When you change prompts in Gopedia or local Ragas code, bump `index_version` or `git_sha` on runs for traceability.
