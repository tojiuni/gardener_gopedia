# Gardener Gopedia

MVP service to evaluate [Gopedia](https://github.com/) search quality: datasets/qrels, optional ingest orchestration, batch search runs, IR metrics, baseline comparison, and a small Streamlit review UI.

## Quick start

```bash
cd /path/to/gardener_gopedia
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

**AI + human dataset curation:** agent proposals and Gold promotion — [doc/agent-label-contract.md](doc/agent-label-contract.md), `POST /curation/batches`, Streamlit tab **Curation queue**.

**Agent qrels (`target_data`):** [doc/agent-dataset-qrel.md](doc/agent-dataset-qrel.md), `POST /datasets/{id}/resolve-qrels`, optional `resolve_before_eval` on `POST /runs`.

## Gopedia upstream docs

Contract and local stack are documented in the Gopedia repo under `doc/guide/`. With a typical sibling checkout, paths are `../gopedia/doc/guide/README.md`, `../gopedia/doc/guide/agent-interop.md`, and `../gopedia/doc/guide/run.md`.

## 설치/시나리오 가이드 (Korean)

사전 요구 사항 : 설치에 필요한 최소 환경 (K8s 버전, CPU/Memory, 필수 도구 등)

- K8s `v1.28+` 또는 Python + Postgres 로컬 환경
- 최소 `2 vCPU / 4GB RAM` (Gopedia 동시 구동 시 권장 `8 vCPU / 16GB RAM`)
- 필수 도구: `git`, `python 3.11+`, `pip`/`uv`, Postgres

설치 (5분 이내)

- 복사-붙여넣기 가능한 설치 명령어 (현재 가이드는 Python 실행 기준)
- 빠른 로컬 설치 명령은 가이드 문서에 포함
- 상세: [`doc/guide/install-guide.md`](./doc/guide/install-guide.md)
- 요약: [`doc/guide/quick-install-guide.md`](./doc/guide/quick-install-guide.md)

설치 확인 방법 ("이 화면이 뜨면 성공")

- `curl http://127.0.0.1:18880/health` 응답 JSON이 오면 성공
- `gardener-smoke` 실행 시 run id 생성되면 정상

삭제 방법

- `pkill -f "uvicorn gardener_gopedia.main:app" || true`

첫 번째 시나리오 (10분 이내)

- 설치 직후 바로 실행할 수 있는 데모 시나리오 1개
- Obsidian 문서를 Gopedia에 ingest 후 Gardener smoke 평가 실행
- Streamlit에서 결과를 확인하고 오답 라벨링

다음 단계 안내 : 프로덕션 적용을 원하시면 [contact@cloudbro.ai](mailto:contact@cloudbro.ai)로 문의 - 컨택 채널은 꼭 cloudbro로 부탁드립니다!

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
