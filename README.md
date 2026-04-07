# Gardener Gopedia

MVP service to evaluate [Gopedia](https://github.com/) search quality: datasets/qrels, optional ingest orchestration, batch search runs, IR metrics, baseline comparison, and a small Streamlit review UI.

## Quick start

```bash
cd /Users/dong-hoshin/Documents/dev/gardener_gopedia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# Optional: Ragas + Langfuse observability
# pip install -e ".[eval]"

# PostgreSQL: set GARDENER_DATABASE_URL or POSTGRES_* in .env (see .env.example), then:
# ./scripts/init-db.sh
# or: gardener-init-db

export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880

# Optional: Langfuse (self-host) — see doc/runbook.md and ./scripts/langfuse-up.sh

# Smoke evaluation (needs Gopedia up)
gardener-smoke

# Review UI

streamlit run streamlit_app/app.py
# gardener-smoke -> gardener-smoke_id 
# eval run ID = gardener-smoke_id 
## load run
```

See [doc/runbook.md](doc/runbook.md) for API flow, Gopedia stack alignment, and CI smoke details.

## Service test guide

Use [doc/reproducible_eval.md](doc/reproducible_eval.md) for an end-to-end service test runbook.
It includes copy-paste commands to reset the index, ingest documents, register/resolve a dataset, run evaluation, and verify metrics.
Follow it when you need reproducible validation of both Gopedia (`:18787`) and Gardener (`:18880`) integration.

**AI + human dataset curation:** agent proposals and Gold promotion — [doc/agent-label-contract.md](doc/agent-label-contract.md), `POST /curation/batches`, Streamlit tab **Curation queue**.

**Agent qrels (`target_data`):** [doc/agent-dataset-qrel.md](doc/agent-dataset-qrel.md), `POST /datasets/{id}/resolve-qrels`, optional `resolve_before_eval` on `POST /runs`.

## Gopedia upstream docs

Contract and local stack are documented in the Gopedia repo under `doc/guide/`. With a typical sibling checkout, paths are `../gopedia/doc/guide/README.md`, `../gopedia/doc/guide/agent-interop.md`, and `../gopedia/doc/guide/run.md`.

## Environment

| Variable | Default |
|----------|---------|
| `GARDENER_DATABASE_URL` | (empty until set) `postgresql+psycopg://…` — **required** unless `POSTGRES_*` below builds the URL |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_DB`, … | When `GARDENER_DATABASE_URL` is empty, these **must** be set to build `postgresql+psycopg://…` |
| `GARDENER_TEST_DATABASE_URL` | (tests only) PostgreSQL URL for `pytest`; DB tests skip if unset |
| `GARDENER_GOPEDIA_BASE_URL` | `http://127.0.0.1:18787` |
| `GARDENER_GOPEDIA_SEARCH_DETAIL` | (unset → Gopedia default full JSON) |
| `GARDENER_GOPEDIA_SEARCH_FIELDS` | (unset) |
| `GARDENER_GOPEDIA_SEARCH_RETRYABLE_MAX_ATTEMPTS` | `3` |
| `GARDENER_QREL_RESOLVE_SEARCH_DETAIL` | `standard` (used by `resolve-qrels`) |
| `GARDENER_QREL_RESOLVE_MIN_VECTOR_SCORE` | `0.25` |
| `GARDENER_QREL_RESOLVE_MIN_COMBINED_SCORE` | `0.35` |
| `GARDENER_QREL_RESOLVE_MAX_HITS_TO_SCORE` | `20` |
| `GARDENER_DEFAULT_TOP_K` | `10` |
| `GARDENER_DEFAULT_QUERY_TIMEOUT_S` | `15` |
| `GARDENER_POSTGRES_SCHEMA` | (unset; use with Postgres to isolate tables) |
| `GARDENER_RAGAS_ENABLED` | `false` |
| `GARDENER_RAGAS_ANSWER_METRICS` | `false` |
| `GARDENER_LANGFUSE_ENABLED` | `false` — set `true` to export traces after each eval |
| `GARDENER_LANGFUSE_HOST` | (unset; SDK base URL, e.g. `http://127.0.0.1:3000`) |
| `GARDENER_LANGFUSE_PUBLIC_KEY` / `GARDENER_LANGFUSE_SECRET_KEY` | Langfuse project API keys |

Ragas + Langfuse + KPI APIs: see [doc/runbook.md](doc/runbook.md), `./scripts/langfuse-up.sh`, and [doc/optimization_playbook.md](doc/optimization_playbook.md). Completed runs may include `langfuse_trace_url` on `GET /runs/{id}` when export succeeds.
