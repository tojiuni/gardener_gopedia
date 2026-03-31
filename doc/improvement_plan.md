# Gopedia Improvement Plan

## Decision: No Gopedia Code Improvement Needed

**Date**: 2026-03-31
**Baseline Run**: `6640abbe-0d58-4eea-b8d7-5aba0b0c9567`
**Recall@5**: 0.5714 (≥ 0.5 threshold ✅)

## Rationale

The baseline evaluation shows Gopedia's search engine is working correctly. Of 6 failed queries:
- **3** are qrel target_id mismatches (search found the right content, wrong chunk ID assigned in dataset)
- **1** is a content gap (Infisical API docs not in corpus)
- **1** is a cross-lingual embedding mismatch (edge case)
- **1** is a ranking issue (likely resolves with dedup)

**None of these require Gopedia code changes.**

## Recommended Non-Gopedia Actions

### P0: Fix Dataset Qrel Targets
- Reassign qrel target_ids for q_gopedia_l1_l2_l3, q_gopedia_smart_sink_routing, q_traefik_resolved_path
- Expected impact: Recall@5 → 0.786

### P1: Deduplicate Qdrant Index
- Investigate dual ingestion creating duplicate chunks (11/14 queries affected)
- Add dedup step in ingestion pipeline or post-processing
- Expected impact: MRR@10 and P@3 significant improvement

### P2: Expand Knowledge Base Content
- Add Infisical API documentation (endpoint, body schema)
- Expected impact: +1 query recall

### P3: Future Consideration
- Bilingual embedding or query expansion for conceptual Korean queries
- Affects 1 query (q_universitas_bio_groups)
- Low priority — edge case

## Next Steps

If the evaluation pipeline iteration continues:
1. Apply P0 fixes to the dataset (via Gardener curation)
2. Re-run evaluation to confirm projected improvement
3. Address P1 (dedup) in next ingestion cycle
