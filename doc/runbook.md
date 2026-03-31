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

### Datasets (authoring and API)

- **Contract** (queries, qrels, `target_data`, resolve → eval, JSONL): [doc/agent-dataset-qrel.md](agent-dataset-qrel.md).
- **Repo layout:** keep curated evaluation JSON under **`dataset/`** (see the “Where to put dataset files” section in that doc); register with `POST /datasets` or upload-jsonl as described there.
- **Examples:** [`sample_data/`](../sample_data/) for minimal shapes; gold `l3_id` example: `universitas_gold_micro.example.json`.

## Install

```bash
cd /Users/dong-hoshin/Documents/dev/gardener_gopedia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Initialize database (Postgres)

When using PostgreSQL, create the optional schema and tables **before** or **alongside** first API start:

```bash
./scripts/init-db.sh
# or: gardener-init-db
```

This runs `CREATE SCHEMA IF NOT EXISTS` for `GARDENER_POSTGRES_SCHEMA` (when set), then `create_all` for Gardener models.

Gardener **does not** support SQLite. Use PostgreSQL only; add missing columns with `ALTER TABLE … IF NOT EXISTS` or re-run `./scripts/init-db.sh` on a fresh schema.

## Start API

```bash
export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880
```

Optional defaults for eval search (see `.env.example`): `GARDENER_GOPEDIA_SEARCH_DETAIL`, `GARDENER_GOPEDIA_SEARCH_FIELDS`, `GARDENER_GOPEDIA_SEARCH_RETRYABLE_MAX_ATTEMPTS`.

### PostgreSQL (shared with Gopedia)

**Option A — explicit URL:**

```bash
export GARDENER_DATABASE_URL=postgresql+psycopg://USER:PASS@127.0.0.1:5432/gopedia
```

**Option B — compose-style `POSTGRES_*` (leave `GARDENER_DATABASE_URL` empty):**

Set `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_DB` (and optional `POSTGRES_PORT`, `POSTGRES_SSLMODE`). Gardener builds `postgresql+psycopg://…` automatically.

- API on the **host**, Postgres in Docker with published `5432`: use `POSTGRES_HOST=127.0.0.1`.
- API **inside** the same Compose network: use the DB service name (e.g. `postgres_db`).

Optional isolated schema (recommended):

```sql
CREATE SCHEMA IF NOT EXISTS gardener_eval AUTHORIZATION your_user;
```

```bash
export GARDENER_POSTGRES_SCHEMA=gardener_eval
```

Run `./scripts/init-db.sh` once so the schema exists before `search_path` connections. On first API start, `init_db()` also ensures tables exist.

### Ragas + Langfuse + cost/quality KPIs (optional)

1. Install eval extras: `pip install -e ".[eval]"` (Ragas, OpenAI, Langfuse SDK).
2. Set `OPENAI_API_KEY` and enable Ragas in `.env` (see `.env.example`): `GARDENER_RAGAS_ENABLED=true`.
3. Phase-2 answer metrics (faithfulness, answer relevancy, context recall): `GARDENER_RAGAS_ANSWER_METRICS=true` and fill `reference_answer` on dataset queries where applicable.
4. **Langfuse (self-host)** — traces, per-query spans, scores (IR + Ragas), and usage/cost metadata:

```bash
./scripts/langfuse-up.sh
# In Langfuse UI: create a project and copy API keys into .env (see .env.example).
export GARDENER_LANGFUSE_ENABLED=true
export GARDENER_LANGFUSE_HOST=http://127.0.0.1:3000
export GARDENER_LANGFUSE_PUBLIC_KEY=pk-lf-...
export GARDENER_LANGFUSE_SECRET_KEY=sk-lf-...
```

`langfuse-up.sh` downloads the [upstream Docker Compose](https://langfuse.com/self-hosting/deployment/docker-compose) into `.langfuse-docker/` and starts it. It uses a minimal `DOCKER_CONFIG` (no `credsStore`) for broken credential helpers; see `scripts/langfuse-docker-env.sh`. **Important:** the default upstream file publishes Postgres on `127.0.0.1:5432` — change that port in `.langfuse-docker/docker-compose.yml` if it collides with Gopedia’s Postgres.

To stop: `./scripts/langfuse-down.sh`.

**Tracing:** each completed eval (when Langfuse env is set) emits a root observation and per-query child observations with scores for `Recall@5`, Ragas metrics, and efficiency fields when present.

**KPI endpoints (optimization loop):**

- `GET /runs/{id}/kpi-summary` — run-level quality vs tokens/cost rollups.
- `GET /runs/{id}/kpi-roi-queries?sort=worst_roi&limit=50` — per-query cost vs quality table.

Tuning workflow: [optimization_playbook.md](optimization_playbook.md).

If Langfuse export fails, check `params_json.langfuse_sync_error` on the run (eval still completes).

**Postgres schema note (upgrading existing DBs):** older Gardener versions may have optional `datasets.phoenix_*` columns that are no longer mapped by the ORM. After backup, you may drop them:

```sql
ALTER TABLE datasets DROP COLUMN IF EXISTS phoenix_dataset_id;
ALTER TABLE datasets DROP COLUMN IF EXISTS phoenix_dataset_version_id;
ALTER TABLE datasets DROP COLUMN IF EXISTS phoenix_dataset_for_version;
```

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

2. **Create dataset** (JSON). Body shape and agent qrels (`target_data`, tiers, resolve): [doc/agent-dataset-qrel.md](agent-dataset-qrel.md). Prefer checking in files under **`dataset/`** and posting with `curl … -d @dataset/<name>.json`. Minimal example: `sample_data/example.json`.

3. **Start eval run** — optional `search_detail` / `search_fields` match Gopedia `GET /api/search` (see `agent-interop.md`). Omit them for full JSON hits; use `summary` for lighter responses.

```bash
curl -s -X POST http://127.0.0.1:18880/runs \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"<uuid>","ingest_run_id":"<optional>","top_k":10,"search_detail":"summary"}' | jq .
```

Poll `GET /runs/{id}` or `POST /runs/{id}/wait`.

4. **Metrics**: `GET /runs/{id}/metrics`

5. **Compare**: `GET /compare?baseline=<id>&candidate=<id>`

## Agent qrels: `target_data` → resolve → eval

Agents can submit qrels with **`target_data`** (excerpt / path / title hints) instead of UUID `target_id`.  
Author those datasets in **`dataset/`** and follow the full contract (fields, JSONL, tuning env vars): [doc/agent-dataset-qrel.md](agent-dataset-qrel.md).

1. `POST /datasets` with `qrels[].target_data` (and optional `queries[].tier` for difficulty).
2. Resolve against Gopedia search (fills `target_id`, `resolution_status`, `resolution_meta`):

```bash
curl -s -X POST "http://127.0.0.1:18880/datasets/<DATASET_ID>/resolve-qrels" | jq .
```

Optional: `?force=true` to re-resolve qrels that already have `target_id`; `target_url=` to override Gopedia base URL.

3. `POST /runs` with the same `dataset_id`. Eval **fails** if any qrel still has no `target_id`, unless the run sets **`resolve_before_eval`: true** (runs resolution inside the eval worker first).

## Small Gold dataset from Gopedia `doc_id` or `l3_id` → eval → compare

**Prefer `l3_id` in qrels** when your Gopedia search JSON leaves `doc_id` empty (common with `detail=summary`): Gardener then matches hits on `l3_id` and Recall@5 works.  
Use **`target_type: "doc_id"`** only when search results include the correct `doc_id` string.

Do **not** use `machine_id` from ingest lines as a qrel target — it is a different identifier.

**1) Pick gold targets from Gopedia search**:

```bash
export GOPEDIA=http://127.0.0.1:18787
curl -s "$GOPEDIA/api/search?q=Traefik&format=json&detail=summary" \
  | jq '.results[:5] | .[] | {doc_id, l3_id, title, source_path}'
```

For document-level IDs, copy `doc_id=…` from `./gopedia ingest` stdout (`OK /path -> doc_id=…`) when the API exposes them.

**2) Create a Gardener dataset with `qrels`** — set `target_type` to `"l3_id"` or `"doc_id"` to match what you label. For **hint-based** qrels without fixed UUIDs, use `target_data` and resolve first; see [doc/agent-dataset-qrel.md](agent-dataset-qrel.md) and files under **`dataset/`** (e.g. `universitas_gopedia_neunexus.json`).

Example body ( **`l3_id` gold** for universitas Neunexus / Gopedia verify): [`sample_data/universitas_gold_micro.example.json`](../sample_data/universitas_gold_micro.example.json). Re-pick `l3_id` values with the same query text if your index differs.

```bash
export GARDENER=http://127.0.0.1:18880

DS=$(curl -s -X POST "$GARDENER/datasets" \
  -H 'Content-Type: application/json' \
  -d @sample_data/universitas_gold_micro.example.json | jq -r .id)
echo "dataset_id=$DS"
```

To post a curated file from **`dataset/`**:

```bash
DS=$(curl -s -X POST "$GARDENER/datasets" \
  -H 'Content-Type: application/json' \
  -d @dataset/universitas_gopedia_neunexus.json | jq -r .id)
```

The top-level `meta` object is ignored by the API (documentation only). If metrics stay at zero, refresh `target_id` values from `GET /api/search?...&format=json&detail=summary` or ingest logs.

**3) Baseline eval run** (note `git_sha` / `index_version` for your own bookkeeping):

```bash
BASE=$(curl -s -X POST "$GARDENER/runs" \
  -H 'Content-Type: application/json' \
  -d "{\"dataset_id\":\"$DS\",\"top_k\":10,\"search_detail\":\"summary\",\"git_sha\":\"baseline\",\"index_version\":\"before\"}" \
  | jq -r .id)
curl -s -X POST "$GARDENER/runs/$BASE/wait" | jq '{status, id}'
curl -s "$GARDENER/runs/$BASE/metrics" | jq .
```

**4) Candidate eval run** — same `dataset_id`, same search params, after you change the index (re-ingest, different `QDRANT_COLLECTION`, model swap, etc.):

```bash
CAND=$(curl -s -X POST "$GARDENER/runs" \
  -H 'Content-Type: application/json' \
  -d "{\"dataset_id\":\"$DS\",\"top_k\":10,\"search_detail\":\"summary\",\"git_sha\":\"candidate\",\"index_version\":\"after\"}" \
  | jq -r .id)
curl -s -X POST "$GARDENER/runs/$CAND/wait" | jq '{status, id}'
curl -s "$GARDENER/runs/$CAND/metrics" | jq .
```

`compare` **requires** both runs to reference the **same** `dataset_id`.

**5) Compare** (per-query regression list uses `Recall@5` by default):

```bash
curl -s "$GARDENER/compare?baseline=$BASE&candidate=$CAND&metric=Recall@5" | jq .
```

**Optional — take `doc_id` from a finished Gardener eval** (top hit per query):

```bash
RUN=<eval_run_uuid>
curl -s "$GARDENER/runs/$RUN/queries" \
  | jq '.[] | select((.hits|length)>0) | {external_id, top_doc_id: .hits[0].target_id, top_type: .hits[0].target_type}'
```

Use those values only if they correspond to your intended gold target (often you still want the ingest `doc_id`, not merely rank-1 after a bad run).

## AI + human dataset curation (Silver → Gold)

Contract and field definitions: [doc/agent-label-contract.md](agent-label-contract.md).  
For Bronze dataset JSON shape, `target_data` qrels, and `dataset/` conventions, see [doc/agent-dataset-qrel.md](agent-dataset-qrel.md).

1. Create a **Bronze** dataset (queries; `qrels` optional). Run an eval to obtain `dataset_query_id` values and hit context for agents.
2. Submit agent proposals:

```bash
curl -s -X POST http://127.0.0.1:18880/curation/batches \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id":"<DATASET_UUID>",
    "source_eval_run_id":"<EVAL_RUN_UUID>",
    "include_unlisted_queries":true,
    "proposals":[
      {"dataset_query_id":"<DQ_UUID>","candidates":[
        {"target_id":"l3-uuid","target_type":"l3_id","confidence":0.85,"model_name":"agent-a"}
      ]}
    ]
  }' | jq .
```

3. Human queue: `GET http://127.0.0.1:18880/curation/batches/<BATCH_ID>/queue`
4. Resolve: `POST .../curation/batches/<BATCH_ID>/decisions` with `accept_candidate`, `set_target`, `reject`, or `no_target`.
5. Promote to **Gold** (requires every query in the dataset to have a non-`unresolved` decision):

```bash
curl -s -X POST http://127.0.0.1:18880/curation/batches/<BATCH_ID>/promote \
  -H 'Content-Type: application/json' \
  -d '{"new_version":"2","copy_parent_qrels_when_no_decision_target":true}' | jq .
```

6. Run baseline/candidate evals on the **same** Gold `dataset_id`, then `GET /compare?baseline=...&candidate=...`.

Optional env tuning: `GARDENER_LABEL_AUTO_ACCEPT_SINGLE_MIN_CONFIDENCE`, `GARDENER_LABEL_CONSENSUS_MIN_MODELS`, `GARDENER_LABEL_CONSENSUS_MIN_CONFIDENCE`.

### PostgreSQL schema upgrades

For older Gardener tables missing curation or `qrels.target_data` columns, use `ALTER TABLE … ADD COLUMN IF NOT EXISTS …` or re-run `./scripts/init-db.sh` on a fresh schema.

**`qrels`:** `target_id` nullable; `target_data` `JSONB`; `resolution_status` default `'resolved'`; `resolution_meta` `JSONB`.

### Tests (`pytest`)

Database integration tests require a dedicated PostgreSQL database (tables are created and dropped):

```bash
export GARDENER_TEST_DATABASE_URL=postgresql+psycopg://USER:PASS@127.0.0.1:5432/gardener_test?sslmode=disable
pytest tests/ -q
```

If `GARDENER_TEST_DATABASE_URL` is unset, DB-backed tests are skipped; pure unit tests still run.

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
