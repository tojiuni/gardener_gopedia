# RAG 품질 테스트 — osteon / agent-v1.1

| 항목 | 값 |
|------|-----|
| **날짜** | 2026-05-02 |
| **Run ID** | `7188c425-e09e-447a-96c4-4f1195697ba3` |
| **Dataset** | `sample_osteon_guide_30_v2` (quality_preset: osteon) |
| **쿼리 수** | 30 (평가 19 / qrel 미해결 스킵 11) |
| **top_k** | 10 |
| **Gopedia 타겟** | `gopedia-svc.gopedia-svc.svc:18787` |
| **gardener-gopedia-svc 버전** | `eb438a8` (fix/skip-unresolved-qrels 반영) |

---

## 집계 메트릭

| 메트릭 | 값 | 비고 |
|--------|-----|------|
| **Recall@5 (aggregate)** | **0.947** | 19개 평가 쿼리 기준 (18/19 hit) |
| **Recall@5 (mean, 30q)** | 0.600 | 미해결 쿼리 포함 전체 기준 |
| **MRR@10** | 0.620 | |
| **nDCG@10** | 0.739 | |
| **P@3** | 0.298 | |
| **평균 검색 지연** | ~4.1s | per query, K8s 클러스터 내부 호출 |

---

## 평가 대상 쿼리 분류

| 분류 | 수 | 설명 |
|------|-----|------|
| Recall@5 = 1 (hit) | 18 | 정답 청크가 top-5 내 포함 |
| Recall@5 = 0 (miss) | 1 | 정답 청크가 top-5 밖 |
| Recall@5 = null (skip) | 11 | qrel resolve 실패 — 인덱스에 해당 청크 없음 |

---

## 미스 쿼리 분석 (1건)

| external_id | query_text | top1_title | 실패 유형 |
|-------------|-----------|------------|-----------|
| `osteon_29_hosts_ost_deploy` | Ubuntu 설정에서 /etc/hosts에 넣는 ost-deploy의 Management IP 예시는? | 08 Current State | 섹션 오귀속 — /etc/hosts 내용이 Ubuntu Setup 챕터에 있지만 Current State가 상위 랭크 |

---

## 미해결(스킵) 쿼리 목록 (11건)

qrel의 `target_data.excerpt`에 해당하는 L3 청크가 gopedia 인덱스에 없거나 매칭 실패.  
osteon 가이드의 일부 챕터(00 Overview 특정 섹션, 05 Kubernetes 일부 등)가 미인덱스 상태.

| external_id | 대상 챕터 |
|-------------|----------|
| osteon_01_base_os | 00 Overview |
| osteon_02_openstack_release | 00 Overview |
| osteon_04_controller_hostname | 00 Overview |
| osteon_06_cinder_disk | 00 Overview |
| osteon_07_k8s_install_method | 00 Overview |
| osteon_18_ram_controller | 01 Hardware Checklist |
| osteon_22_multinode_deployment | 04 Kolla Ansible |
| osteon_24_k8s_subnet_cidr | 05 Kubernetes |
| osteon_25_k8s_keypair_name | 05 Kubernetes |
| osteon_26_opentofu_install | 06 Opentofu |
| osteon_28_iac_root | 06 Opentofu |

> 해결 방향: 해당 챕터 재인덱싱 또는 qrel excerpt 재조정 필요.

---

## 이전 버전 대비

| 버전 | 데이터셋 | Recall@5 (agg) | MRR@10 | nDCG@10 |
|------|---------|----------------|--------|---------|
| v0.1.0 | universitas_eval_bronze (14q) | 0.571 | 0.282 | 0.317 |
| v0.2.0 | universitas_eval_bronze v2 (14q) | 0.786 | 0.389 | 0.489 |
| **agent-v1.1** | **osteon sample_30_v2 (19q 평가)** | **0.947** | **0.620** | **0.739** |

> 데이터셋이 다르므로 직접 비교는 참고 수준. osteon 가이드 도메인에서 agent-v1.1 Recall@5 0.947 달성.
