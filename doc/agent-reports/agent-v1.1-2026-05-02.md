# Agent-v1.1 평가 리포트

| 항목 | 값 |
|------|-----|
| **날짜** | 2026-05-02 |
| **Agent 버전** | agent-v1.1 |
| **gopedia-svc 이미지** | `artifacts.toji.homes/neunexus/gopedia-svc:latest` |
| **gardener-gopedia-svc 이미지** | `artifacts.toji.homes/neunexus/gardener-gopedia-svc:eb438a8` |
| **배포 환경** | K8s (neunexus cluster, gardener-gopedia namespace) |
| **평가 도구** | gardener-gopedia eval pipeline (gardener_gopedia PR #20) |

---

## agent-v1.1 개선 사항 (IMP-09~11)

| 개선 ID | 내용 | 상태 |
|---------|------|------|
| IMP-09 | snippet 확장 + l2_summary / surrounding_context 전달 | ✅ 완료 |
| IMP-10 | dedup 기준 l1_id → l2_id 변경 | ✅ 완료 |
| IMP-11 | 시스템 프롬프트 튜닝 | ✅ 완료 |

---

## 품질 평가 결과 요약

**데이터셋**: `sample_osteon_guide_30_v2` (osteon 가이드 30문항)  
**평가 쿼리**: 19개 (11개 qrel 미해결 스킵)

| KPI | 값 | 판정 |
|-----|----|------|
| **Recall@5 (aggregate)** | **0.947** | ✅ 우수 |
| **Recall@5 (mean, 전체 30q)** | 0.600 | ⚠️ 미해결 qrel 11개 포함 기준 |
| MRR@10 | 0.620 | ✅ 양호 |
| nDCG@10 | 0.739 | ✅ 양호 |
| P@3 | 0.298 | — |
| 평균 검색 지연 | ~4.1s | K8s 클러스터 내부 기준 |

**결론**: 평가 가능한 19개 쿼리 기준 Recall@5 = 0.947 (18/19 hit). IMP-09~11 적용 후 검색 품질 양호.

---

## 잔여 이슈

### 미스 (1건)
- `osteon_29_hosts_ost_deploy`: `/etc/hosts` 내용이 있는 챕터가 Ubuntu Setup인데, 상위 랭킹 문서는 Current State. 섹션 구조 또는 청크 분리 방식 개선 여지 있음.

### 미해결 qrel (11건)
- osteon 가이드 일부 챕터가 현재 gopedia 인덱스에 없거나 청크 매칭 실패.
- 재인덱싱 또는 데이터셋 qrel 재조정 후 재평가 필요.

---

## 배포 이력 (이번 사이클)

| PR | 내용 | 리포 |
|----|------|------|
| gardener_gopedia #15 | K8s 배포 가이드 문서 수정 | gardener_gopedia |
| gardener_gopedia #16 | Dockerfile gcc 추가, [eval] 제거 | gardener_gopedia |
| gardener_gopedia #17–19 | CI path filter + clone 블록 이슈 해결 | gardener_gopedia |
| gardener_gopedia #20 | eval: 미해결 qrel skip 처리 + dataset 번들링 | gardener_gopedia |
| neunexus #83 | ci/run.py BOT_SERVICES에 gardener-gopedia 추가 | neunexus |
| neunexus #84 | Vault DB 패스워드 urlquery 인코딩 | neunexus |
| neunexus #85 | ArgoCD 배포 가이드 신규 작성 | neunexus |
| neunexus #86 | ArgoCD 가이드 VSO 전환 반영 | neunexus |

---

## 다음 단계

- [ ] osteon 가이드 미인덱스 챕터 재인덱싱 후 30q 전체 평가
- [ ] `osteon_29_hosts_ost_deploy` miss 원인 분석 (청크 구조 또는 임베딩 개선)
- [ ] gardener_gopedia `ci/run.py` include 필터 추가 (빌드 컨텍스트 최적화)
