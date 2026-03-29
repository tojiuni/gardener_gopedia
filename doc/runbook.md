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
cp .env.local.example .env
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

## Start API

```bash
export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880
```

Optional defaults for eval search (see `.env.example`): `GARDENER_GOPEDIA_SEARCH_DETAIL`, `GARDENER_GOPEDIA_SEARCH_FIELDS`, `GARDENER_GOPEDIA_SEARCH_RETRYABLE_MAX_ATTEMPTS`.

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
