# Gardener Gopedia runbook

## Prerequisites

- Python 3.11+ recommended (3.14 may work; IR libraries tested on 3.14 in development).
- Gopedia HTTP API reachable (default `http://127.0.0.1:18787`).

### Gopedia guides (upstream)

If the Gopedia repository is checked out alongside this project, see:

- `../gopedia/doc/guide/README.md` — index
- `../gopedia/doc/guide/agent-interop.md` — JSON search (`detail`, `fields`), structured `failure` / `ok`, `X-Request-ID`, ingest jobs
- `../gopedia/doc/guide/run.md` — local Docker stack and API bring-up

### Local Gopedia stack (summary)

From the Gopedia repo root:

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD, OPENAI_API_KEY, etc.
export DOCKER_NETWORK_EXTERNAL=gopedia-dev
docker compose -f docker-compose.dev.yml --env-file .env --profile app up -d --build
```

Databases-only mode and host-run API are described in Gopedia `run.md`. Default published HTTP port is **18787**. Use a single `QDRANT_COLLECTION` value consistently across `.env` and compose, as noted there.

## Install

```bash
cd /Users/dong-hoshin/Documents/dev/gardener_gopedia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

If you already have a local `gardener.db` from an older version, delete it or migrate. Example SQLite migration (ignore errors if columns already exist):

```bash
sqlite3 gardener.db <<'SQL'
ALTER TABLE dataset_queries ADD COLUMN tier VARCHAR(64);
ALTER TABLE dataset_queries ADD COLUMN reference_answer TEXT;
ALTER TABLE run_metrics ADD COLUMN details_json JSON;
CREATE TABLE IF NOT EXISTS run_ragas_samples (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  eval_run_id VARCHAR(36) NOT NULL,
  dataset_query_id VARCHAR(36) NOT NULL,
  generated_response TEXT,
  FOREIGN KEY(eval_run_id) REFERENCES eval_runs (id),
  FOREIGN KEY(dataset_query_id) REFERENCES dataset_queries (id),
  CONSTRAINT uq_run_ragas_sample_query UNIQUE (eval_run_id, dataset_query_id)
);
SQL
```

## Start API

```bash
export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880
```

Optional defaults for eval search (see `.env.example`): `GARDENER_GOPEDIA_SEARCH_DETAIL`, `GARDENER_GOPEDIA_SEARCH_FIELDS`, `GARDENER_GOPEDIA_SEARCH_RETRYABLE_MAX_ATTEMPTS`.

### PostgreSQL (shared with Gopedia)

Point Gardener at the same Postgres instance as Gopedia if you want one DB for app + eval data:

```bash
export GARDENER_DATABASE_URL=postgresql+psycopg://USER:PASS@127.0.0.1:5432/gopedia
```

Optional isolated schema (recommended):

```sql
CREATE SCHEMA IF NOT EXISTS gardener_eval AUTHORIZATION your_user;
```

```bash
export GARDENER_POSTGRES_SCHEMA=gardener_eval
```

On first start, `init_db()` creates tables in that schema. Existing SQLite `gardener.db` users are unchanged.

### Ragas + Phoenix (optional)

1. Install eval extras: `pip install -e ".[eval]"` (Ragas, OpenAI, OpenTelemetry OTLP).
2. Set `OPENAI_API_KEY` and enable Ragas in `.env` (see `.env.example`): `GARDENER_RAGAS_ENABLED=true`.
3. Phase-2 answer metrics (faithfulness, answer relevancy, context recall): `GARDENER_RAGAS_ANSWER_METRICS=true` and fill `reference_answer` on dataset queries where applicable.
4. **Phoenix (self-host)** — UI + OTLP traces for run/query drill-down:

```bash
docker compose -f docker-compose.phoenix.yml up -d
export GARDENER_PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

Open `http://127.0.0.1:6006`. Each eval run emits a root trace with per-query child spans and Ragas scores as attributes. See [Arize Phoenix](https://github.com/Arize-ai/phoenix).

**Note:** `arize-phoenix` Python wheels may not support Python 3.14 yet; use 3.11–3.13 for the full Phoenix SDK, or rely on OTLP from Gardener (supported here) + Phoenix container.

## Ingest then evaluate

1. **Trigger ingest** (async job by default). `source_path` must be valid **on the Gopedia server** (paths are resolved there). When Gopedia runs in Compose with the repo mounted at `/app`, use `/app/...` (example below). When Gopedia runs on the host, use a path relative to that Gopedia checkout.

```bash
curl -s -X POST http://127.0.0.1:18880/ingest-runs \
  -H 'Content-Type: application/json' \
  -d '{"source_path":"/app/doc/design/Rev2/references","mode":"async"}' | jq .
```

Poll:

```bash
curl -s http://127.0.0.1:18880/ingest-runs/<id> | jq .
```

Or block on the server worker (dev only):

```bash
curl -s -X POST http://127.0.0.1:18880/ingest-runs/<id>/wait | jq .
```

2. **Create dataset** (JSON) — see `sample_data/example.json` body shape.

3. **Start eval run** — optional `search_detail` / `search_fields` match Gopedia `GET /api/search` (see `agent-interop.md`). Omit them for full JSON hits; use `summary` for lighter responses.

```bash
curl -s -X POST http://127.0.0.1:18880/runs \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"<uuid>","ingest_run_id":"<optional>","top_k":10,"search_detail":"summary"}' | jq .
```

Poll `GET /runs/{id}` or `POST /runs/{id}/wait`.

4. **Metrics**: `GET /runs/{id}/metrics`

5. **Compare**: `GET /compare?baseline=<id>&candidate=<id>`

## Smoke command

With Gardener API on `18880` and Gopedia on `18787`:

```bash
export GARDENER_API_URL=http://127.0.0.1:18880
export GOPEDIA_API_URL=http://127.0.0.1:18787
gardener-smoke
```

## Streamlit review

```bash
export GARDENER_API_URL=http://127.0.0.1:18880
streamlit run streamlit_app/app.py
```

## CI

Run API in background and `gardener-smoke`, or call `httpx` against a staging Gardener URL. Keep timeouts generous for first retrieval cold start.
