# Gardener Gopedia Install Guide (Detailed)

이 문서는 `gardener_gopedia`를 설치해 `gopedia` 검색 품질을 테스트/관리하는 절차를 설명합니다. `gopedia_mcp`와 함께 Agent 응답 품질 검증까지 이어지는 조합 시나리오를 포함합니다.

## 1) 사전 요구 사항

### 최소 환경

- Kubernetes: `v1.28+` (또는 로컬 Docker/venv)
- CPU/Memory(개발 최소): `2 vCPU / 4GB RAM`
- CPU/Memory(권장): `4 vCPU / 8GB RAM` (Gopedia 동시 구동 시 `8 vCPU / 16GB RAM`)

### 필수 도구

- `git`
- `python 3.11+`
- `pip` 또는 `uv`
- `postgresql` 접근 정보 (`GARDENER_DATABASE_URL` 또는 `POSTGRES_*`)
- (권장) 실행 중인 `gopedia` API

## 2) 설치 (5분 이내)

```bash
cd /path/to/gardener_gopedia
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
./scripts/init-db.sh
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880
```

## 3) 설치 확인 방법

```bash
curl -s http://127.0.0.1:18880/health
```

성공 기준:

- health 응답(JSON)이 반환되면 성공
- `gardener-smoke` 실행 시 run id가 생성되면 정상

## 4) 삭제 방법

```bash
pkill -f "uvicorn gardener_gopedia.main:app" || true
```

DB 데이터까지 삭제하려면 사용 중인 Postgres에서 Gardener 스키마/DB를 별도로 정리하세요.

## 5) 3개 조합 운영 시나리오

### A. Gopedia + Gardener (기본)

1. Gopedia를 먼저 기동
2. Gardener에서 smoke run 실행
3. IR metric/NDCG를 기준선과 비교

### B. Gardener + MCP (품질 관측)

1. MCP Agent 질의 결과를 Gardener 데이터셋에 반영
2. 동일 질문에 대한 정량 지표 추적

### C. Full Stack (Gopedia + Gardener + MCP)

1. Gopedia ingest 후 검색 API 안정화
2. Gardener로 품질 baseline 생성
3. MCP Agent 응답을 수집/비교해 회귀 감시

## 6) 첫 번째 시나리오 (10분 이내, Obsidian 권장)

1. Obsidian Vault 문서 3개를 Gopedia에 ingest
2. Gardener에서 간단 쿼리셋 생성 (`회의`, `정책`, `TODO`)
3. `gardener-smoke` 실행 후 상위 결과 확인
4. Streamlit UI에서 오답 후보를 라벨링
5. MCP Agent 동일 질의 응답과 비교

Obsidian을 권장하는 이유:

- 문서 링크 기반으로 질의-정답셋을 만들기 쉽고 반복 평가가 빠름

## 7) 관련 문서

- 요약 설치: [quick-install-guide.md](./quick-install-guide.md)
- 런북: [../runbook.md](../runbook.md)
