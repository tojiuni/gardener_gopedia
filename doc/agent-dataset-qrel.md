# Agent dataset & qrel contract (`target_data`)

Gardener accepts **either** explicit `target_id` **or** structured `target_data` per qrel.  
IR metrics (Recall@5, MRR, nDCG) still use resolved **`l3_id` / `doc_id`** after `POST /datasets/{id}/resolve-qrels` or `resolve_before_eval=true` on an eval run.

## Where to put dataset files (`dataset/`)

Author **curated dataset JSON** under the repo’s **`dataset/`** directory. Each file should match the `POST /datasets` body shape (name, version, optional `curation_tier`, `queries`, `qrels` with `target_data` and/or `target_id`). Treat `dataset/` as the canonical place to version-control evaluation sets; registering them in Gardener is a separate step.

Upload from the project root, for example:

```bash
curl -s -X POST "http://127.0.0.1:18880/datasets" \
  -H "Content-Type: application/json" \
  -d @dataset/your_dataset.json | jq .
```

See [runbook.md](runbook.md) for resolve → eval flow after creation.

## `POST /datasets` body (excerpt)

```json
{
  "name": "bronze_agent",
  "version": "1",
  "curation_tier": "bronze",
  "queries": [
    {
      "external_id": "q1",
      "text": "What does the Traefik skill say about labels?",
      "tier": "medium",
      "reference_answer": "optional short gold answer for Ragas"
    }
  ],
  "qrels": [
    {
      "query_external_id": "q1",
      "target_data": {
        "excerpt": "Use only the `traefik` label (e.g. `traefik.enable=true`).",
        "title_hint": "Skill",
        "source_path_hint": "skills/traefik/SKILL.md"
      },
      "target_type": "l3_id",
      "relevance": 1
    }
  ]
}
```

### `target_data` fields (all optional except at least one useful signal)

| Field | Purpose |
|-------|---------|
| `excerpt` | Phrase or sentence that should appear in the retrieved chunk (strong signal). |
| `title_hint` | Substring match against hit `title`. |
| `source_path_hint` | Substring match against hit `source_path` (when API returns it). |

If you already know the id, set `target_id` and omit `target_data` (or keep both; `target_id` wins for eval).

## Resolve to ids

```bash
curl -s -X POST "http://127.0.0.1:18880/datasets/<DATASET_ID>/resolve-qrels" | jq .
```

Optional query params:

- `force=true` — re-resolve every qrel that has `target_data` (overwrites `target_id`).
- `target_url=...` — Gopedia base URL override.

Then start eval as usual (`POST /runs`). If any qrel still lacks `target_id`, eval **fails** with a clear error unless you set:

```json
{ "dataset_id": "...", "resolve_before_eval": true, "top_k": 10 }
```

## Tier convention

Use `queries[].tier` for difficulty buckets, e.g. `easy`, `medium`, `hard` (string; no enum enforced).

## JSONL upload

Qrel line example:

```json
{"query_external_id":"q1","target_data":{"excerpt":"..."},"target_type":"l3_id","relevance":1}
```

## Tuning (env `GARDENER_` prefix)

- `QREL_RESOLVE_SEARCH_DETAIL` — default `standard`
- `QREL_RESOLVE_MIN_VECTOR_SCORE`
- `QREL_RESOLVE_MIN_COMBINED_SCORE`
- `QREL_RESOLVE_MAX_HITS_TO_SCORE`

See [runbook.md](runbook.md) for PostgreSQL schema setup and migrations.
