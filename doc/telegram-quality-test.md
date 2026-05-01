# Telegram으로 Gopedia 품질 테스트 실행하기

neunexus 클러스터에서 Telegram을 통해 gardener-gopedia 평가 파이프라인을 실행하는 방법을 설명합니다.

---

## 아키텍처 개요

```
Telegram 메시지
  └─ OpenClaw (ai-assistant ns)        ← 메시지 수신 / intent 분류
       └─ cogito (cogito ns)           ← 자연어 → plan 생성 (BOT_REGISTRY 기반)
            └─ gardener-gopedia bot    ← /execute 호출
                 └─ gardener-gopedia-svc  ← 실제 평가 실행
                      └─ gopedia-svc   ← 검색 대상
```

OpenClaw는 `plan.workflow`를 cogito에 전달하고, cogito가 `gardener-gopedia` + capability를 선택하면 `/execute`를 호출합니다. 플랜을 실행하기 전 **사용자 확인** 단계가 있습니다.

---

## 사전 조건

- Telegram 그룹에 `toji-agent-manager-bot`이 참여해 있을 것
- `ai-assistant/bot-registry` ConfigMap에 `gardener-gopedia` 등록 완료
- cogito `BOT_REGISTRY`에 `gardener-gopedia` 포함 (neunexus PR #80 이후)
- gopedia 인덱스에 `gardener-gopedia` SOUL.md 인덱싱 완료

등록 상태 확인:

```bash
# bot-registry 확인
kubectl get configmap -n ai-assistant bot-registry -o jsonpath='{.data.gardener-gopedia}'

# cogito BOT_REGISTRY 확인
kubectl exec -n cogito deployment/cogito -- \
  python3 -c "from src.bot_registry import BOT_REGISTRY; print(list(BOT_REGISTRY.keys()))"
```

---

## 지원 명령어

| 의도 | 예시 메시지 | capability |
|------|------------|------------|
| 서비스 상태 확인 | "gardener gopedia 상태 확인해줘" | `gardener.health` |
| 품질 테스트 실행 | "gopedia 품질 테스트 해줘" | `gardener.quality.run` |
| osteon 프리셋으로 평가 | "osteon 평가 실행해줘" | `gardener.quality.run` |
| 이전 결과 조회 | "gardener 리포트 보여줘 run_id=<uuid>" | `gardener.run.report` |

---

## 사용 절차

### 1단계: 요청 전송

Telegram 그룹에 자연어로 메시지를 보냅니다:

```
gopedia 품질 테스트 해줘
```

### 2단계: 플랜 확인

cogito가 요청을 분석해 실행 계획을 생성합니다. OpenClaw가 플랜 내용과 함께 확인 요청을 보냅니다:

```
[bot] 다음 플랜을 실행할까요?
  Step 1: gardener-gopedia.gardener.quality.run
  payload: { ... }

실행하려면 "예" 또는 "네"를 입력하세요.
취소하려면 "취소" 또는 "아니"를 입력하세요.
```

### 3단계: 실행 확인

```
예
```

확인 응답 키워드: `yes`, `y`, `네`, `예`, `응`, `ㅇ`, `진행`, `실행`, `ok`, `okay`  
취소 키워드: `cancel`, `no`, `n`, `취소`, `아니`, `ㄴ`, `그만`

### 4단계: 결과 확인

실행이 완료되면 bot이 결과를 응답합니다:

```
✅ Step 1 (gardener-gopedia.gardener.quality.run):
{
  "grade": "A",
  "metrics": { "Recall@5": 0.947, "MRR@10": 0.620, "nDCG@10": 0.739 },
  "run_id": "7188c425-...",
  "recommended_action": "No action required — schedule next cycle"
}
```

---

## 평가 등급 기준

| 등급 | Recall@5 | 권장 조치 |
|------|---------|----------|
| **A** | ≥ 0.90 | 다음 사이클 예약 |
| **B** | ≥ 0.75 | 결과 로그, 다음 사이클 리뷰 |
| **C** | ≥ 0.60 | gopedia-qa human reranking 요청 |
| **D** | < 0.60 | re-ingest 제안 + human reranking |

---

## 시나리오별 예시

### 시나리오 1: 헬스 체크

```
[User] gardener gopedia 상태 확인해줘
[Bot]  플랜: gardener-gopedia.gardener.health — 실행할까요?
[User] 예
[Bot]  ✅ Step 1: { "gardener_svc": "ok", "gopedia_svc": "ok" }
```

### 시나리오 2: osteon 프리셋 품질 평가

```
[User] osteon 평가 실행해줘
[Bot]  플랜: gardener-gopedia.gardener.quality.run (quality_preset: osteon) — 실행할까요?
[User] 예
[Bot]  ⏳ 플랜을 실행합니다...
       [약 2~10분 후]
       ✅ Step 1: { "grade": "A", "metrics": { "Recall@5": 0.947, ... }, "run_id": "..." }
```

> 평가 run은 쿼리 수 × 검색 지연에 따라 최대 10분 소요될 수 있습니다.

### 시나리오 3: 이전 run 결과 조회

```
[User] gardener 리포트 보여줘 run_id=7188c425-e09e-447a-96c4-4f1195697ba3
[Bot]  플랜: gardener-gopedia.gardener.run.report — 실행할까요?
[User] 예
[Bot]  ✅ Step 1: { "grade": "A", "metrics": { ... }, "failure_samples": [...] }
```

---

## 트러블슈팅

### 플랜이 생성되지 않거나 steps=0 반환

cogito가 gardener-gopedia를 인식하지 못하는 경우입니다.

```bash
# cogito BOT_REGISTRY 확인
kubectl exec -n cogito deployment/cogito -- \
  python3 -c "from src.bot_registry import BOT_REGISTRY; print(list(BOT_REGISTRY.keys()))"

# 없으면 최신 cogito 이미지 배포 → doc/ci-troubleshooting.md TG-02 참조
```

### 잘못된 bot 호출 (예: osteon.infra.deployment.status)

OpenClaw에 이전 플랜이 Redis에 남아 있어 수정 요청으로 처리됐을 가능성이 있습니다.  
`취소`를 전송해 pending plan을 비운 다음 다시 시도합니다.

### 응답이 없거나 오래 걸림

```bash
# cogito 로그 확인
kubectl logs -n cogito deployment/cogito --since=5m | grep -v healthz

# gardener-gopedia 로그 확인
kubectl logs -n gardener-gopedia -l app=gardener-gopedia --since=5m | grep -v healthz
```

상세 이슈는 [doc/ci-troubleshooting.md](ci-troubleshooting.md) 참조.

---

## 관련 문서

| 문서 | 내용 |
|------|------|
| [SOUL.md](../services/bots/gardener-gopedia/SOUL.md) (neunexus) | capability 스펙, payload 구조 |
| [doc/ci-troubleshooting.md](ci-troubleshooting.md) | Telegram 라우팅 이슈 (TG-01~03) |
| [doc/k8s-deployment.md](k8s-deployment.md) | K8s 배포 구조, 사전 조건 |
| [doc/rag-test-reports/](rag-test-reports/) | 과거 품질 테스트 결과 리포트 |
