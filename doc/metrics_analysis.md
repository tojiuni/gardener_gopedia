# Evaluation Metrics Analysis Report

## Summary

| Field | Value |
|-------|-------|
| **Dataset** | universitas_eval_bronze (14 queries) |
| **Dataset ID** | `9f326934-de5b-4f1f-bf1f-81c672150811` |
| **Run ID** | `6640abbe-0d58-4eea-b8d7-5aba0b0c9567` |
| **Date** | 2026-03-30 |
| **Index** | 68 docs, 1756 Qdrant points |
| **Embedding** | text-embedding-3-small (1536-dim, Cosine) |

## Aggregate Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Recall@5** | 0.5714 (8/14) | ≥ 0.5 | ✅ PASS |
| **MRR@10** | 0.2821 | — | ⚠️ Low |
| **nDCG@10** | 0.3172 | — | ⚠️ Low |
| **P@3** | 0.0952 | — | ⚠️ Low |

**Interpretation**: Recall@5 passes the minimum threshold. However, MRR@10 and nDCG@10 are low because even for HIT queries, the relevant chunk often ranks below position 1. P@3=0.095 indicates only ~1 relevant hit per 3 queries in top-3 positions — heavily impacted by the duplicate chunk problem (see §Systemic Issues).

---

## Per-Query Analysis

### Successful Queries (Recall@5 = 1.0)

| # | Query ID | Tier | Top Hit Score | Top Hit Title |
|---|----------|------|---------------|---------------|
| 1 | q_docker_registry_auth | medium | 0.660 | Config |
| 2 | q_gopedia_core_metaphor | easy | 0.561 | Readme |
| 3 | q_gopedia_envelope_strategy | medium | 0.474 | Gopedia Feature Guide |
| 4 | q_port_forward_case_ab | hard | 0.589 | Port Forward Trace 80 443 |
| 5 | q_sops_age_preparation | hard | 0.620 | Bio-Inspired System Architecture Blueprint |
| 6 | q_taxon_postgres_config | easy | 0.529 | Readme |
| 7 | q_traefik_domain_substitution | easy | 0.642 | Dynamic Config |
| 8 | q_traefik_topology_ips | easy | 0.669 | Internal Integration |

### Failed Queries (Recall@5 = 0.0)

| # | Query ID | Tier | Failure Type | Details |
|---|----------|------|-------------|---------|
| 1 | q_gopedia_l1_l2_l3 | medium | **Qrel mismatch** | Top-5 all from correct doc (Gopedia Feature Guide), contain L1/L2/L3 content, but chunk IDs don't match qrel target |
| 2 | q_gopedia_smart_sink_routing | hard | **Qrel mismatch** | Top-5 contain Smart Sink routing info including PostgreSQL/TypeDB/Qdrant/ClickHouse, but chunk IDs don't match qrel |
| 3 | q_traefik_resolved_path | medium | **Qrel mismatch** | Top-1 score 0.783 (highest in entire run!) with **exact answer** in snippet, but chunk ID doesn't match qrel |
| 4 | q_server_os_specs | easy | **Ranking + specificity** | Related "server OS" skill references found, but not the chunk with specific version numbers (Rocky 9.6, kernel 5.14.0, Docker 24.0.9) |
| 5 | q_infisical_secret_create | medium | **Content gap** | API endpoint details (POST /api/v1/secret/secrets) not present in any returned chunks; corpus may lack this specific documentation |
| 6 | q_universitas_bio_groups | hard | **Embedding mismatch** | Query about bio-inspired architecture analogy returned generic "neunexus" config mentions; conceptual/metaphorical query failed to match relevant "Bio-Inspired System Architecture Blueprint" chunks |

---

## Detailed Failure Analysis

### 1. q_gopedia_l1_l2_l3 — Qrel Mismatch

**Query**: Gopedia의 L1, L2, L3 계층은 각각 어떤 역할을 하며 나누는 기준은 무엇인가?

**Expected**: L1=Global Summary (1 doc = 1 L1), L2=Sectional Summary (구조 마커 기준), L3=Atomic Chunk (512-1024 토큰)

**What search returned**: All 5 hits from "Gopedia Feature Guide" — including ToC links to the L1/L2/L3 section and a hit explaining the 3단계 계층 concept. The content is topically correct but chunk IDs don't match the qrel target.

**Root cause**: Qrel target_id assigned to a specific chunk that details the per-level roles, but search returned adjacent/duplicate chunks from the same document with identical scores (ranks 1&2: 0.6467, ranks 3&4: 0.5765).

### 2. q_gopedia_smart_sink_routing — Qrel Mismatch

**Query**: Gopedia Smart Sink는 HierarchyLevel에 따라 어떤 저장소에 기록하나?

**Expected**: L1→PostgreSQL+Qdrant, L2→TypeDB+Qdrant, L3→Qdrant+ClickHouse

**What search returned**: Hit #1 (score 0.656): "Smart Sink(Stem)가 HierarchyLevel·SourceDomain에 따라 **동일 메시지를 서로 다른 DB에 서로 다른 형태로** 기록합니다". Hit #4 (score 0.528): explicitly lists "PostgreSQL/TypeDB/Qdrant/ClickHouse 등 Rhizome 저장소에 기록한다".

**Root cause**: The answer is distributed across multiple chunks. The qrel target likely points to a chunk with the detailed per-level routing table, while search returned the overview chunks instead.

### 3. q_traefik_resolved_path — Qrel Mismatch (Most Clear-Cut)

**Query**: TRAEFIK_DYNAMIC_RESOLVED_PATH는 어떤 역할이고, Traefik 컨테이너 내부에서 어디에 마운트되나?

**Expected**: DOMAIN 치환 후 resolved config 디렉터리, /etc/traefik/dynamic에 마운트

**What search returned**: Hit #1 (score **0.783**, highest in entire run): `TRAEFIK_DYNAMIC_RESOLVED_PATH | Resolved output dir (e.g. .../dynamic-resolved), mounted as /etc/traefik/dynamic`. This is the **verbatim answer**.

**Root cause**: Pure qrel target_id mismatch. The chunk with the exact answer exists and was found at rank 1, but its ID differs from the qrel target. Duplicate chunk (same score at ranks 1&2) compounds the issue.

### 4. q_server_os_specs — Ranking + Specificity

**Query**: osteon 서버의 OS 배포판, 커널 버전, Docker 버전, SELinux 상태는?

**Expected**: Rocky Linux 9.6 (Blue Onyx), kernel 5.14.0-570.58.1.el9_6.x86_64, Docker 24.0.9, SELinux Permissive

**What search returned**: General references to the server-os skill directory and that it contains Rocky Linux/kernel/Docker/SELinux info, but not the specific version numbers.

**Root cause**: The specific version numbers are likely in a "Skill" chunk that provides exact details, but the skill's description chunk was returned instead of the data chunk. May also be partially a content gap if version numbers aren't in a well-embedded chunk.

### 5. q_infisical_secret_create — Content Gap

**Query**: Infisical(Morphso)에서 시크릿을 생성하려면 어떤 API 엔드포인트와 body를 사용하나?

**Expected**: POST /api/v1/secret/secrets에 {secret_name, secret_value, project_id, environment_slug, secret_path}

**What search returned**: Only high-level mentions of Infisical as "기밀 정보 중앙 관리" with no API-level detail. Scores are low (max 0.524).

**Root cause**: The specific Infisical API documentation (endpoint + body schema) likely doesn't exist as a well-formed chunk in the corpus. This is a genuine content gap — the knowledge base doesn't contain this operational detail.

### 6. q_universitas_bio_groups — Embedding Mismatch

**Query**: Universitas 시스템 아키텍처에서 neunexus, taxon, osteon은 각각 인체의 어떤 체계를 모사하며 무엇을 담당하나?

**Expected**: neunexus=신경계 (Traefik/Tinode), taxon=소화·저장 (ClickHouse/Storages), osteon=골격계 (OpenTofu/Kubernetes)

**What search returned**: Config/compose fragments mentioning "neunexus" as a network name. Scores very low (max 0.511). The "Bio-Inspired System Architecture Blueprint" document IS in the corpus (found in other queries) but wasn't retrieved here.

**Root cause**: The query's semantic intent (bio-inspired analogy mapping) doesn't match well in embedding space with the actual document content. The query uses 인체/체계/모사 (human body/system/simulate) while the document uses "Anatomical Grouping" and specific system names. Cross-language semantic gap between Korean query phrasing and English document content.

---

## Systemic Issues

### Duplicate Chunks (Critical)

**11 of 14 queries** have duplicate score pairs in top-5 results — different chunk IDs with identical embeddings returning the same score. This indicates **dual ingestion**: the same content was chunked and embedded twice, creating duplicate Qdrant points.

| Impact | Detail |
|--------|--------|
| Wasted slots | 40-60% of top-K slots consumed by duplicates |
| P@3 deflation | Duplicates fill top-3 without adding relevance diversity |
| MRR@10 deflation | Relevant unique chunks pushed to lower ranks |
| Recall@5 unaffected | If a matching chunk exists, its duplicate also matches |

**Evidence**: q_infisical_secret_create has 4 duplicate pairs in just 5 results (triplet at ranks 3/4/5 with score 0.491).

### Low MRR Despite Hits

For the 8 HIT queries, MRR@10 = 0.282 implies the matching qrel chunk averages around rank 3-4. This is partially caused by duplicates pushing the matching chunk down. Without duplicates, MRR would likely improve to ~0.4-0.5.

---

## Bottleneck Classification Summary

| Bottleneck | Queries Affected | Severity | Fixable By |
|-----------|-----------------|----------|------------|
| **Qrel target mismatch** | 3 (l1_l2_l3, smart_sink, resolved_path) | High | Dataset curation — reassign qrel target_ids to match actual chunk IDs |
| **Duplicate chunks** | 11 (systemic) | Medium | Ingestion dedup — prevent same content from creating multiple Qdrant points |
| **Content gap** | 1 (infisical_secret_create) | Low | Add Infisical API documentation to knowledge base |
| **Embedding mismatch** | 1 (universitas_bio_groups) | Low | Could improve with query expansion or bilingual embedding |
| **Ranking/specificity** | 1 (server_os_specs) | Low | May resolve with dedup (frees slots for more specific chunks) |

---

## Decision: Gopedia Code Improvement

### Verdict: **No Gopedia code change needed**

### Justification

1. **Recall@5 = 0.571 ≥ 0.5 threshold** — PASSES the plan's Must Have requirement
2. **3/6 failures are dataset issues**, not search quality:
   - q_traefik_resolved_path: search returned the **exact answer** at rank 1 (score 0.783) but qrel target_id doesn't match
   - q_gopedia_l1_l2_l3: all 5 results from the correct document
   - q_gopedia_smart_sink_routing: results contain the answer content
3. **1/6 is a content gap** (missing Infisical API docs) — not a Gopedia search problem
4. **1/6 is an embedding mismatch** — could be improved but is an edge case for cross-lingual conceptual queries
5. **1/6 is ranking/specificity** — likely resolves if dedup is applied

### What SHOULD be improved (non-Gopedia)

| Priority | Action | Impact |
|----------|--------|--------|
| **P0** | Fix qrel target_ids in dataset (3 queries) | Recall@5 → 0.786 (+0.214) |
| **P1** | Deduplicate Qdrant index (ingestion pipeline) | MRR@10 ↑, P@3 ↑, nDCG@10 ↑ |
| **P2** | Add Infisical API docs to knowledge base | Recall@5 → 0.857 if combined with P0 |
| **P3** | Consider bilingual/hybrid search for conceptual queries | 1 query affected |

### Projected Metrics After P0+P1 Fixes

| Metric | Current | Projected | Change |
|--------|---------|-----------|--------|
| Recall@5 | 0.571 | ~0.786 | +37% |
| MRR@10 | 0.282 | ~0.45-0.55 | +60-95% |
| nDCG@10 | 0.317 | ~0.45-0.55 | +42-73% |
| P@3 | 0.095 | ~0.20-0.25 | +110-163% |
