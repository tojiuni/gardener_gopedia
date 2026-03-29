# Gardener Gopedia

MVP service to evaluate [Gopedia](https://github.com/) search quality: datasets/qrels, optional ingest orchestration, batch search runs, IR metrics, baseline comparison, and a small Streamlit review UI.

## Quick start

```bash
cd /Users/dong-hoshin/Documents/dev/gardener_gopedia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# API (default DB: sqlite:///./gardener.db)
export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880

# Smoke evaluation (needs Gopedia up)
gardener-smoke

# Review UI

streamlit run streamlit_app/app.py
# gardener-smoke -> gardener-smoke_id 
# eval run ID = gardener-smoke_id 
## load run
```

See [doc/runbook.md](doc/runbook.md) for API flow, Gopedia stack alignment, and CI smoke details.

## Gopedia upstream docs

Contract and local stack are documented in the Gopedia repo under `doc/guide/`. With a typical sibling checkout, paths are `../gopedia/doc/guide/README.md`, `../gopedia/doc/guide/agent-interop.md`, and `../gopedia/doc/guide/run.md`.

## Environment

| Variable | Default |
|----------|---------|
| `GARDENER_DATABASE_URL` | `sqlite:///./gardener.db` |
| `GARDENER_GOPEDIA_BASE_URL` | `http://127.0.0.1:18787` |
| `GARDENER_GOPEDIA_SEARCH_DETAIL` | (unset → Gopedia default full JSON) |
| `GARDENER_GOPEDIA_SEARCH_FIELDS` | (unset) |
| `GARDENER_GOPEDIA_SEARCH_RETRYABLE_MAX_ATTEMPTS` | `3` |
| `GARDENER_DEFAULT_TOP_K` | `10` |
| `GARDENER_DEFAULT_QUERY_TIMEOUT_S` | `15` |
