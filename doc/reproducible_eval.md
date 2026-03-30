# Reproducible Evaluation Pipeline

Copy-paste these commands to run a full evaluation cycle: reset the index,
ingest documents, register a dataset, resolve qrels, run eval, and pull metrics.

Every command uses environment variables so you can point at any Gopedia/Gardener
deployment without editing the doc.

## Prerequisites

| Service    | Default address               | Required |
|------------|-------------------------------|----------|
| Gopedia    | `http://127.0.0.1:18787`     | yes      |
| Gardener   | `http://127.0.0.1:18880`     | yes      |
| PostgreSQL | `127.0.0.1:5432`             | yes      |
| Qdrant     | `http://127.0.0.1:6333`      | yes      |

Tools: `curl`, `jq`, `psql`, `bash`.

## Environment Setup

```bash
# Core service URLs
export GOPEDIA_API=http://127.0.0.1:18787
export GARDENER=http://127.0.0.1:18880
export QDRANT_URL=http://127.0.0.1:6333

# PostgreSQL (Gopedia DB, public schema)
export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=admin_gopedia
export PGPASSWORD=changeme_local_only
export PGDATABASE=gopedia
```

## Quick Start

Full pipeline in one block. Each line depends on the previous one, so run them
sequentially.

```bash
# 1. Reset index (Postgres tables + Qdrant collections)
./scripts/reset_gopedia_index.sh --confirm

# 2. Ingest universitas/ documents into Gopedia
./scripts/ingest_universitas.sh

# 3. Register the bronze evaluation dataset
DS_ID=$(curl -s -X POST "$GARDENER/datasets" \
  -H 'Content-Type: application/json' \
  -d @dataset/universitas_eval_bronze.json | jq -r .id)
echo "dataset_id=$DS_ID"

# 4. Resolve qrels (match target_data hints to actual Gopedia L3 IDs)
curl -s -X POST "$GARDENER/datasets/$DS_ID/resolve-qrels" | jq .

# 5. Launch eval run
RUN_ID=$(curl -s -X POST "$GARDENER/runs" \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"'"$DS_ID"'","top_k":10,"search_detail":"summary"}' | jq -r .id)
echo "run_id=$RUN_ID"

# 6. Wait for completion
curl -s -X POST "$GARDENER/runs/$RUN_ID/wait" | jq '{status, id}'

# 7. Pull metrics
curl -s "$GARDENER/runs/$RUN_ID/metrics" | jq .
```

---

## Detailed Steps

### Step 1: Reset Gopedia Index

Wipe all documents and embeddings so you start from a known-empty state.
The script truncates 7 PostgreSQL tables (`CASCADE`) and recreates both
Qdrant collections with the same schema (1536-dim, Cosine).

**Dry run first** (shows current row/point counts, changes nothing):

```bash
./scripts/reset_gopedia_index.sh --dry-run
```

Expected output:

```
=== Gopedia Index Reset (mode: dry-run) ===

--- PostgreSQL tables (public schema) ---
  keyword_so: 672 rows
  knowledge_l3: 1050 rows
  ...

--- Qdrant collections ---
  gopedia_markdown: 1756 points
  gopedia_document: 0 points

Would TRUNCATE: keyword_so knowledge_l3 knowledge_l2 knowledge_l1 documents projects pipeline_version (CASCADE)
Would DELETE & RECREATE: gopedia_markdown gopedia_document
```

**Execute the reset:**

```bash
./scripts/reset_gopedia_index.sh --confirm
```

**Verify manually** (optional):

```bash
# Postgres: all tables should show 0 rows
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A \
  -c "SELECT 'documents', count(*) FROM documents
      UNION ALL SELECT 'knowledge_l3', count(*) FROM knowledge_l3;"

# Qdrant: both collections should show 0 points
curl -s "$QDRANT_URL/collections/gopedia_markdown" | jq '.result.points_count'
curl -s "$QDRANT_URL/collections/gopedia_document" | jq '.result.points_count'
```

### Step 2: Ingest universitas/ Documents

The ingest script discovers all `.md` files under the host `universitas/`
directory and POSTs each one to Gopedia's `/api/ingest` endpoint using the
container-internal path prefix `/universitas/`.

Gopedia runs in Docker. The `universitas/` folder is mounted read-only at
`/universitas` inside the container. The script handles the path translation
automatically.

**Dry run** (lists files, ingests nothing):

```bash
./scripts/ingest_universitas.sh --dry-run
```

**Run ingestion:**

```bash
./scripts/ingest_universitas.sh
```

Each file takes roughly 3 to 6 seconds (embedding generation). Expect ~67 files,
~5 minutes total. The script prints progress and a summary at the end:

```
[67/67] Ingesting /universitas/osteon/skills/server-os/SKILL.md           ... OK (doc_id=abcd1234-...)

════════════════════════════════════════════════════
  Ingest Complete
  Total:   67
  Success: 67
  Failed:  0
════════════════════════════════════════════════════
```

**Verify ingestion** (optional):

```bash
# Document count in Postgres
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A \
  -c "SELECT count(*) FROM documents;"
# Expected: ~67-68

# Qdrant point count
curl -s "$QDRANT_URL/collections/gopedia_markdown" | jq '.result.points_count'
# Expected: ~1700-1800

# Quick search sanity check
curl -s "$GOPEDIA_API/api/search?q=Traefik&format=json&detail=summary" \
  | jq '.results | length'
# Expected: >0
```

### Step 3: Register Bronze Dataset

The bronze dataset file contains 14 queries covering neunexus, gopedia, taxon,
and osteon topics. Qrels use `target_data` (excerpt + title hint + path hint)
instead of hard-coded UUIDs, so they work across fresh indexes.

```bash
DS_ID=$(curl -s -X POST "$GARDENER/datasets" \
  -H 'Content-Type: application/json' \
  -d @dataset/universitas_eval_bronze.json | jq -r .id)
echo "dataset_id=$DS_ID"
```

Expected response (abbreviated):

```json
{
  "id": "9f326934-de5b-4f1f-bf1f-81c672150811",
  "name": "universitas_eval_bronze",
  "version": "1",
  "curation_tier": "bronze",
  "query_count": 14,
  "qrel_count": 14
}
```

**Verify:**

```bash
curl -s "$GARDENER/datasets/$DS_ID" | jq '{id, name, query_count, qrel_count, curation_tier}'
```

### Step 4: Resolve Qrels

This step searches Gopedia for each qrel's `target_data` hints and fills in
the actual `target_id` (L3 chunk UUID). Without this step, the eval run
won't know which search results count as relevant.

```bash
curl -s -X POST "$GARDENER/datasets/$DS_ID/resolve-qrels" | jq .
```

Expected response:

```json
{
  "resolved": 14,
  "ambiguous": 0,
  "failed": 0,
  "total": 14
}
```

If any qrels fail to resolve, try with `force=true` to re-resolve all:

```bash
curl -s -X POST "$GARDENER/datasets/$DS_ID/resolve-qrels?force=true" | jq .
```

You can also point resolution at a different Gopedia instance:

```bash
curl -s -X POST "$GARDENER/datasets/$DS_ID/resolve-qrels?target_url=http://other-gopedia:18787" | jq .
```

### Step 5: Run Evaluation

Start a search-and-measure run against the resolved dataset. The eval worker
issues each query to Gopedia, collects ranked results, and computes IR metrics.

```bash
RUN_ID=$(curl -s -X POST "$GARDENER/runs" \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"'"$DS_ID"'","top_k":10,"search_detail":"summary"}' | jq -r .id)
echo "run_id=$RUN_ID"
```

Optional fields you can include in the run body:

| Field              | Purpose                                         |
|--------------------|--------------------------------------------------|
| `search_detail`    | Gopedia detail level (`summary`, `standard`, etc.) |
| `search_fields`    | Gopedia field filter                              |
| `git_sha`          | Tag this run with a commit hash for bookkeeping    |
| `index_version`    | Label like `"before"` or `"after"` for comparisons |
| `resolve_before_eval` | `true` to auto-resolve qrels inside the worker  |

**Wait for the run to finish:**

```bash
curl -s -X POST "$GARDENER/runs/$RUN_ID/wait" | jq '{status, id}'
```

Expected:

```json
{
  "status": "completed",
  "id": "6640abbe-0d58-4eea-b8d7-5aba0b0c9567"
}
```

Or poll instead of blocking:

```bash
curl -s "$GARDENER/runs/$RUN_ID" | jq '{status, id, started_at, finished_at}'
```

### Step 6: Get Metrics

Once the run status is `completed`, pull the aggregate IR metrics:

```bash
curl -s "$GARDENER/runs/$RUN_ID/metrics" | jq .
```

Expected output (baseline reference values):

```json
{
  "Recall@5": 0.571,
  "Recall@10": 0.571,
  "MRR@10": 0.282,
  "nDCG@10": 0.317,
  "Precision@3": 0.095,
  "MAP@10": 0.282
}
```

**Per-query breakdown:**

```bash
curl -s "$GARDENER/runs/$RUN_ID/queries" | jq '.[0] | {external_id, metrics, hits: (.hits | length)}'
```

### Step 7: Compare Runs (optional)

After making changes (re-ingest with different settings, model swap, etc.),
run a second eval on the same dataset, then compare:

```bash
# Run candidate eval
CAND_ID=$(curl -s -X POST "$GARDENER/runs" \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id":"'"$DS_ID"'","top_k":10,"search_detail":"summary","index_version":"after"}' \
  | jq -r .id)
curl -s -X POST "$GARDENER/runs/$CAND_ID/wait" | jq '{status}'

# Compare baseline vs candidate
curl -s "$GARDENER/compare?baseline=$RUN_ID&candidate=$CAND_ID" | jq .
```

Compare with a specific metric:

```bash
curl -s "$GARDENER/compare?baseline=$RUN_ID&candidate=$CAND_ID&metric=Recall@5" | jq .
```

Both runs must reference the same `dataset_id`.

---

## Advanced: Curation Flow (Bronze to Gold)

After running an eval, you can curate the results into a Gold dataset through
agent proposals and human review.

### Submit agent proposals

```bash
BATCH_ID=$(curl -s -X POST "$GARDENER/curation/batches" \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id":"'"$DS_ID"'",
    "source_eval_run_id":"'"$RUN_ID"'",
    "include_unlisted_queries": true,
    "proposals": [
      {
        "dataset_query_id": "<QUERY_UUID>",
        "candidates": [
          {
            "target_id": "<L3_UUID>",
            "target_type": "l3_id",
            "confidence": 0.85,
            "model_name": "agent-v1"
          }
        ]
      }
    ]
  }' | jq -r .id)
echo "batch_id=$BATCH_ID"
```

Get `dataset_query_id` values from the run's query list:

```bash
curl -s "$GARDENER/runs/$RUN_ID/queries" \
  | jq '.[] | {dataset_query_id: .dataset_query_id, external_id: .external_id}'
```

### Review queue

```bash
curl -s "$GARDENER/curation/batches/$BATCH_ID/queue" | jq .
```

### Accept proposals

```bash
curl -s -X POST "$GARDENER/curation/batches/$BATCH_ID/decisions" \
  -H 'Content-Type: application/json' \
  -d '{
    "decisions": [
      {"dataset_query_id": "<QUERY_UUID>", "action": "accept_candidate"}
    ]
  }' | jq .
```

Other actions: `set_target` (provide your own target), `reject`, `no_target`.

### Promote to Gold

Requires every query in the dataset to have a decision.

```bash
curl -s -X POST "$GARDENER/curation/batches/$BATCH_ID/promote" \
  -H 'Content-Type: application/json' \
  -d '{"new_version": "2", "copy_parent_qrels_when_no_decision_target": true}' | jq .
```

This creates a new dataset with `curation_tier: "gold"` and a `parent_dataset_id`
pointing back to the bronze original.

---

## Error Handling and Troubleshooting

### Connection refused

```
curl: (7) Failed to connect to 127.0.0.1 port 18787: Connection refused
```

Check that the target service is running:

```bash
# Gopedia (Docker)
docker ps | grep gopedia

# Gardener (host process)
curl -s "$GARDENER/health" | jq .

# Qdrant
curl -s "$QDRANT_URL/collections" | jq '.result.collections | length'

# PostgreSQL
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c "SELECT 1;"
```

### Empty search results after ingest

Qdrant indexes vectors asynchronously. Right after a large ingest, the
`indexed_vectors_count` may lag behind `points_count`. Wait a few seconds
and retry:

```bash
curl -s "$QDRANT_URL/collections/gopedia_markdown" \
  | jq '{points: .result.points_count, indexed: .result.indexed_vectors_count}'
```

Also confirm you're searching the right collection. Check the Gopedia
`.env` value for `QDRANT_COLLECTION`.

### Resolve qrels returns 0 resolved

This usually means the index is empty or the Gopedia base URL is wrong.
Verify ingestion happened and the search works:

```bash
curl -s "$GOPEDIA_API/api/search?q=test&format=json" | jq '.results | length'
```

If it returns 0 results, re-run ingestion (Step 2).

### Eval run stuck in "running" state

Poll the run status and check for timeout:

```bash
curl -s "$GARDENER/runs/$RUN_ID" | jq '{status, error, started_at}'
```

If Gopedia is slow or unreachable, individual query timeouts
(default 15s, configurable via `GARDENER_DEFAULT_QUERY_TIMEOUT_S`) will
cause query-level failures but the run still completes.

### Metrics all zero

Check that qrels have resolved `target_id` values:

```bash
curl -s "$GARDENER/datasets/$DS_ID" | jq '.qrels[:2]'
```

If `target_id` is null, run resolve-qrels again (Step 4). Also confirm
`target_type` matches what Gopedia search returns. For `detail=summary`
responses, use `l3_id` (not `doc_id`).

### Compare returns error

Both runs must use the same `dataset_id`. Verify:

```bash
curl -s "$GARDENER/runs/$RUN_ID" | jq .dataset_id
curl -s "$GARDENER/runs/$CAND_ID" | jq .dataset_id
```

---

## Reference: Baseline Run IDs

These IDs are from the initial pipeline execution on the universitas corpus.
They won't exist on a fresh Gardener database but serve as a reference for
expected metric ranges.

| Artifact         | ID                                     |
|------------------|----------------------------------------|
| Bronze dataset   | `9f326934-de5b-4f1f-bf1f-81c672150811` |
| Baseline eval run| `6640abbe-0d58-4eea-b8d7-5aba0b0c9567` |
| Gold dataset     | `3c4dfeb6-891d-4f77-88ed-29c787c56f0e` |
| Curation batch   | `93e191ec-a5bd-45a3-bd79-8203c2ef2be5` |

**Baseline metrics** (14 queries, top_k=10, detail=summary):

| Metric       | Value |
|--------------|-------|
| Recall@5     | 0.571 |
| MRR@10       | 0.282 |
| nDCG@10      | 0.317 |
| Precision@3  | 0.095 |

Known issues in the baseline: 3/14 queries have qrel target_id mismatches
(search finds the right content but a different L3 chunk ID lands in the
dataset). Fixing those would push Recall@5 to ~0.786.

---

## Reference: Key Files

| File | Purpose |
|------|---------|
| `scripts/reset_gopedia_index.sh` | Truncate Postgres + recreate Qdrant collections |
| `scripts/ingest_universitas.sh` | Ingest all universitas/ markdown into Gopedia |
| `dataset/universitas_eval_bronze.json` | 14-query bronze evaluation dataset |
| `doc/runbook.md` | Full Gardener operational runbook |
| `doc/agent-dataset-qrel.md` | Dataset and qrel contract reference |
| `doc/agent-label-contract.md` | Curation/labeling contract |
