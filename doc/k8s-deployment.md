# gardener-gopedia K8s 배포 가이드

neunexus 클러스터에서 gardener-gopedia 서비스를 운영하는 방법을 정리합니다.

---

## 구성 개요

```
Telegram
  └─ OpenClaw (ai-assistant ns)
       └─ gardener-gopedia bot (port 8080)          ← gardener-gopedia ns
            └─ gardener-gopedia-svc (port 18880)    ← gardener-gopedia ns
                 └─ gopedia-svc (gopedia-svc ns, port 18787)
                 └─ postgres-rw (taxon ns, port 5432)
```

두 컨테이너가 같은 네임스페이스(`gardener-gopedia`)에서 실행됩니다:

| 컴포넌트 | 이미지 | 포트 | 역할 |
|----------|--------|------|------|
| `gardener-gopedia-bot` | `artifacts.toji.homes/neunexus/gardener-gopedia-bot` | 8080 | OpenClaw `/execute` 프록시 봇 |
| `gardener-gopedia-svc` | `artifacts.toji.homes/neunexus/gardener-gopedia-svc` | 18880 | 평가 엔진 (FastAPI) |

---

## 사전 조건

### 1. Vault K8s auth role 생성

`gardener-gopedia-svc`는 Vault Agent Injector로 DB 패스워드를 주입받습니다. 배포 전에 아래 스크립트를 실행해야 합니다.

```bash
# neunexus 레포 루트에서
VAULT_TOKEN=$(cat ~/.vault-token-root) \
  ./scripts/vault/vault-setup-services.sh
```

스크립트 내부에서 실행되는 Vault 명령:

```bash
vault write auth/kubernetes/role/gardener-gopedia \
  bound_service_account_names=gardener-gopedia-svc \
  bound_service_account_namespaces=gardener-gopedia \
  policies=services-read \
  ttl=1h
```

`services-read` 정책은 `secret/data/neunexus/*` 읽기 전용 권한을 가집니다.

### 2. PostgreSQL schema

`gardener-gopedia-svc`는 gopedia DB(`taxon` ns의 `postgres-rw`)에 `gardener_eval` 스키마를 생성합니다. DB에 직접 접근해 초기화하거나 첫 기동 시 자동 생성됩니다.

```bash
# K8s master 접속 후 postgres pod exec
kubectl exec -n taxon postgres-rw-0 -- psql -U gopedia -d gopedia \
  -c "CREATE SCHEMA IF NOT EXISTS gardener_eval AUTHORIZATION gopedia;"
```

---

## CI/CD 파이프라인

### 이미지 빌드 경로

| 이미지 | 소스 레포 | 트리거 |
|--------|-----------|--------|
| `gardener-gopedia-svc` | `tojiuni/gardener_gopedia` | main 푸시 / tag / manual |
| `gardener-gopedia-bot` | `tojiuni/neunexus` | main 푸시 / manual |

#### gardener_gopedia (svc 이미지)

```
main push
  └─ .woodpecker/ci.yml → ci/run.py build --sha=$CI_COMMIT_SHA
       └─ Dagger → artifacts.toji.homes/neunexus/gardener-gopedia-svc:{sha7}
       └─ Dagger → artifacts.toji.homes/neunexus/gardener-gopedia-svc:latest
```

#### neunexus (bot 이미지)

```
main push
  └─ .woodpecker/ci.yml → dagger call build-bots --services=gardener-gopedia
       └─ Dagger → artifacts.toji.homes/neunexus/gardener-gopedia-bot:{sha7}
       └─ Dagger → artifacts.toji.homes/neunexus/gardener-gopedia-bot:latest
```

### Woodpecker secrets (tojiuni/gardener_gopedia)

| Secret | 내용 | Vault 경로 |
|--------|------|------------|
| `registry_token` | artifact-keeper push 토큰 | `secret/neunexus/woodpecker.artifacts-push-token` |

등록 방법:

```bash
export WOODPECKER_SERVER=https://ci.toji.homes
export WOODPECKER_TOKEN=<admin-api-token>   # secret/neunexus/woodpecker → admin-api-token

REGISTRY_TOKEN=$(vault kv get -field=token secret/neunexus/woodpecker.artifacts-push-token)
woodpecker-cli repo secret add \
  --repo tojiuni/gardener_gopedia \
  --name registry_token \
  --value "$REGISTRY_TOKEN" \
  --event push --event manual --event tag
```

수동 빌드 트리거:

```bash
# Woodpecker UI → tojiuni/gardener_gopedia → "New pipeline" (manual)
# 또는 CLI로 최신 파이프라인 재실행:
woodpecker-cli pipeline start tojiuni/gardener_gopedia <pipeline-number>
```

---

## ArgoCD 배포

`deploy/argocd-apps/gardener-gopedia.yaml` (neunexus 레포)이 ArgoCD Application을 정의합니다.

```yaml
spec:
  source:
    path: deploy/bots/gardener-gopedia   # kustomization.yaml + deployment.yaml
  destination:
    namespace: gardener-gopedia
```

ArgoCD Image Updater가 두 이미지 모두 digest 기준으로 자동 추적합니다:

```
bot=artifacts.toji.homes/neunexus/gardener-gopedia-bot:latest
svc=artifacts.toji.homes/neunexus/gardener-gopedia-svc:latest
```

새 이미지가 레지스트리에 push되면 ArgoCD가 자동으로 재배포합니다.

ArgoCD Application을 수동으로 등록해야 할 경우:

```bash
kubectl apply -f deploy/argocd-apps/gardener-gopedia.yaml -n metaflow
```

---

## 환경 변수

### gardener-gopedia-svc

| 변수 | 값 (K8s) | 설명 |
|------|-----------|------|
| `GARDENER_DATABASE_URL` | Vault 주입 | `postgresql+psycopg://gopedia:<pw>@postgres-rw.taxon.svc:5432/gopedia?sslmode=disable` |
| `GARDENER_GOPEDIA_BASE_URL` | `http://gopedia-svc.gopedia-svc.svc:18787` | Gopedia API 엔드포인트 |
| `GARDENER_POSTGRES_SCHEMA` | `gardener_eval` | DB 스키마 이름 |
| `GARDENER_DEFAULT_TOP_K` | `10` | 기본 검색 depth |
| `GARDENER_RAGAS_ENABLED` | `false` | Ragas LLM 평가 비활성화 |
| `GARDENER_API_HOST` | `0.0.0.0` | 바인딩 주소 |
| `GARDENER_API_PORT` | `18880` | 리스닝 포트 |

Vault 주입은 Vault Agent Injector가 `/vault/secrets/env` 파일로 전달합니다. 컨테이너 시작 시 `source /vault/secrets/env`로 로드됩니다.

### gardener-gopedia-bot

| 변수 | 값 (K8s) | 설명 |
|------|-----------|------|
| `GARDENER_SVC_URL` | `http://gardener-gopedia-svc.gardener-gopedia.svc:18880` | 평가 엔진 주소 |
| `GOPEDIA_SVC_URL` | `http://gopedia-svc.gopedia-svc.svc:18787` | Gopedia 직접 헬스 확인용 |
| `GARDENER_WAIT_TIMEOUT_MS` | `600000` | 평가 완료 대기 타임아웃 (10분) |

---

## 봇 Capability 사용법

OpenClaw(Telegram 봇)를 통해 `gardener-gopedia` 봇에 요청을 보냅니다.

### gardener.health

연결 상태 확인 (gardener-gopedia-svc + gopedia-svc).

```
사용자 → OpenClaw: "gardener 상태 확인해줘"
```

응답 예시:

```json
{
  "ok": true,
  "gardener": { "url": "...", "reachable": true },
  "gopedia":  { "url": "...", "ok": true }
}
```

### gardener.quality.run

IR 품질 평가 실행. Recall@5 기반으로 A/B/C/D 등급을 반환합니다.

```
사용자 → OpenClaw: "gopedia 품질 테스트 실행해줘"
```

**Mode A — 내장 프리셋** (preset 이름 지정):

```json
{
  "capability": "gardener.quality.run",
  "payload": { "quality_preset": "osteon", "top_k": 10 }
}
```

**Mode B — 직접 데이터셋** (dataset_path 지정):

```json
{
  "capability": "gardener.quality.run",
  "payload": {
    "dataset_path": "/datasets/universitas_gopedia_neunexus.json",
    "top_k": 10,
    "search_detail": "summary"
  }
}
```

응답 예시:

```json
{
  "ok": true,
  "run_id": "550e8400-...",
  "grade": "B",
  "metrics": { "Recall@5": 0.82, "MRR@10": 0.76, "nDCG@10": 0.79 },
  "recommended_action": "Log result, flag for next cycle review"
}
```

**등급 기준 (Recall@5)**:

| 등급 | 기준 | 권장 조치 |
|------|------|-----------|
| A | ≥ 90% | 다음 사이클까지 조치 불필요 |
| B | ≥ 75% | 결과 기록, 다음 사이클 검토 |
| C | ≥ 60% | Human reranking 세션 트리거 (gopedia-qa) |
| D | < 60% | Re-ingest 제안 + Human reranking |

### gardener.run.report

이전 평가 run의 상세 리포트 조회.

```json
{
  "capability": "gardener.run.report",
  "payload": { "run_id": "550e8400-...", "failure_sample_limit": 5 }
}
```

---

## 직접 API 접근 (SSH 터널)

K8s ClusterIP 서비스에 직접 접근이 필요한 경우 SSH 포트 포워딩을 사용합니다.

```bash
# K8s master 접속 정보: .env 참고
ssh -i secret/lymphhub_neunexus ubuntu@10.200.0.1 -p 22 \
  -L 18880:<gardener-gopedia-svc ClusterIP>:18880
```

ClusterIP 확인:

```bash
kubectl get svc -n gardener-gopedia
# NAME                    TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
# gardener-gopedia        ClusterIP   10.x.x.x        <none>        8080/TCP
# gardener-gopedia-svc    ClusterIP   10.x.x.x        <none>        18880/TCP
```

터널 연결 후:

```bash
# 헬스 체크
curl http://127.0.0.1:18880/health

# 평가 실행 (preset 사용)
curl -s -X POST http://127.0.0.1:18880/runs \
  -H 'Content-Type: application/json' \
  -d '{"quality_preset":"osteon","top_k":10}' | jq .

# 완료 대기
RUN_ID=<run-id>
curl -s -X POST "http://127.0.0.1:18880/runs/$RUN_ID/wait" | jq .

# 지표 조회
curl -s "http://127.0.0.1:18880/runs/$RUN_ID/metrics" | jq .
curl -s "http://127.0.0.1:18880/runs/$RUN_ID/kpi-summary" | jq .
```

---

## 상태 확인 및 트러블슈팅

### Pod 상태 확인

```bash
kubectl get pods -n gardener-gopedia
# NAME                                READY   STATUS    RESTARTS
# gardener-gopedia-xxx                2/2     Running   0   ← 2/2: app + vault-agent
# gardener-gopedia-svc-xxx            2/2     Running   0
```

Vault Agent Injector 때문에 각 Pod에 사이드카 컨테이너가 추가됩니다(`2/2`).

### 로그 확인

```bash
# svc 로그
kubectl logs -n gardener-gopedia deploy/gardener-gopedia-svc -c gardener-gopedia-svc

# bot 로그
kubectl logs -n gardener-gopedia deploy/gardener-gopedia -c gardener-gopedia

# vault-agent 로그 (secret 주입 실패 시)
kubectl logs -n gardener-gopedia deploy/gardener-gopedia-svc -c vault-agent
```

### Vault 주입 실패 (`0/2` 상태)

`gardener-gopedia-svc` Pod가 `0/2` 상태이면 Vault K8s auth role이 없는 것입니다.

```bash
# Vault role 확인
kubectl exec -n vault vault-0 -- vault read auth/kubernetes/role/gardener-gopedia

# role이 없으면 neunexus 레포에서:
VAULT_TOKEN=$(cat ~/.vault-token-root) ./scripts/vault/vault-setup-services.sh
```

### DB 연결 오류

```bash
# vault-agent가 주입한 env 파일 확인
kubectl exec -n gardener-gopedia deploy/gardener-gopedia-svc -c gardener-gopedia-svc \
  -- cat /vault/secrets/env

# postgres-rw 연결 확인
kubectl exec -n gardener-gopedia deploy/gardener-gopedia-svc -c gardener-gopedia-svc \
  -- python3 -c "
import os
url = os.environ.get('GARDENER_DATABASE_URL','not set')
print('DATABASE_URL set:', url[:50] if url != 'not set' else 'NOT SET')
"
```

### 이미지 업데이트가 반영 안 될 때

ArgoCD Image Updater가 digest 기반으로 추적합니다. 새 이미지가 push됐는데 재배포가 안 된다면:

```bash
# ArgoCD Image Updater 로그 확인
kubectl logs -n metaflow deploy/argocd-image-updater | grep gardener-gopedia | tail -20

# 수동 sync
argocd app sync gardener-gopedia
```

---

## 관련 파일 (neunexus 레포)

| 파일 | 설명 |
|------|------|
| `services/bots/gardener-gopedia/src/main.py` | 봇 FastAPI 서버 (capability 구현) |
| `services/bots/gardener-gopedia/capabilities.yaml` | OpenClaw capability 선언 |
| `services/bots/gardener-gopedia/Dockerfile` | 봇 이미지 빌드 |
| `deploy/bots/gardener-gopedia/deployment.yaml` | K8s 매니페스트 (namespace, SA, Deployment, Service) |
| `deploy/argocd-apps/gardener-gopedia.yaml` | ArgoCD Application |
| `scripts/vault/vault-setup-services.sh` | Vault K8s auth role 생성 스크립트 |
