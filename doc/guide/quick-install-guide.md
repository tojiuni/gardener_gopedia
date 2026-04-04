# Gardener Gopedia Quick Install Guide

`gardener_gopedia`를 빠르게 설치해 Gopedia 품질 테스트를 시작하는 요약 가이드입니다.

## 사전 요구 사항 (최소)

- `python 3.11+`, `pip`
- Postgres 접근 정보
- 실행 중인 `gopedia` API (`http://127.0.0.1:18787`)

## 설치 (복사-붙여넣기)

```bash
cd /path/to/gardener_gopedia
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
export GARDENER_GOPEDIA_BASE_URL=http://127.0.0.1:18787
./scripts/init-db.sh
uvicorn gardener_gopedia.main:app --host 0.0.0.0 --port 18880
```

## 설치 확인

```bash
curl -s http://127.0.0.1:18880/health
gardener-smoke
```

- health 응답 + smoke run id 생성 시 성공

## 삭제

```bash
pkill -f "uvicorn gardener_gopedia.main:app" || true
```

## 10분 첫 시나리오 (Obsidian 권장)

1. Obsidian 문서를 Gopedia에 ingest
2. Gardener로 smoke 평가 실행
3. Streamlit에서 결과 검토

## 3개 조합 확장

- Agent 연동은 `gopedia_mcp` 설치 후 동일 질의 회귀 확인
- 전체 권장 순서: Gopedia -> Gardener -> MCP

상세는 [install-guide.md](./install-guide.md) 참고.
