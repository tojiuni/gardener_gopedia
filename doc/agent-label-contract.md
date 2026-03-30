# Agent label proposal contract

External AI agents submit structured proposals to Gardener via `POST /curation/batches`. The API validates each proposal item as an **AgentQueryProposal** (Pydantic: `gardener_gopedia.agent_contract`).

## Endpoint

- `POST /curation/batches`
- Body fields:
  - `dataset_id` (required)
  - `source_eval_run_id` (optional) — eval run whose hits informed the agent
  - `external_key` (optional) — idempotency key unique per `dataset_id`
  - `provenance_json` (optional) — arbitrary audit metadata
  - `proposals` (required, non-empty array)
  - `include_unlisted_queries` (optional, default `false`) — if `true`, adds an `unresolved` decision row for every query in the dataset not listed in `proposals` (required before **promote** if the dataset has more queries than proposed)

## Proposal item schema (`AgentQueryProposal`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset_query_id` | string | yes | Internal Gardener id from `dataset_queries` (not `external_id`) |
| `candidates` | array | no | Default `[]`; empty ⇒ `unresolved` human queue |

## Candidate item schema (`AgentCandidateItem`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_id` | string | yes | Proposed `l3_id` or `doc_id` |
| `target_type` | `"l3_id"` \| `"doc_id"` | no | Default `l3_id` |
| `confidence` | number | yes | \(0.0\)–\(1.0\) |
| `model_name` | string | yes | Agent or model identifier (max 128 chars) |
| `rationale` | string | no | Short justification |
| `evidence` | object | no | e.g. `{ "snippet": "...", "title": "...", "hit_rank": 1 }` or any JSON |
| `candidate_rank` | integer | no | Default `0`; lower ranks shown first after sort |

Constraints:

- Duplicate `dataset_query_id` values in one batch are rejected.
- `external_key` must be unique per `dataset_id` when provided.

## Auto-accept routing (Silver)

Server settings (env prefix `GARDENER_`):

- `LABEL_AUTO_ACCEPT_SINGLE_MIN_CONFIDENCE` (default `0.9`) — top candidate auto-accepted if no consensus.
- `LABEL_CONSENSUS_MIN_MODELS` (default `2`) — minimum distinct candidates agreeing on the same `(target_id, target_type)`.
- `LABEL_CONSENSUS_MIN_CONFIDENCE` (default `0.7`) — each agreeing candidate must meet this floor.

If auto-accept applies, a `LabelDecision` is stored with status `auto_accepted`. Otherwise status is `unresolved` for human review.

## Example payload

```json
{
  "dataset_id": "00000000-0000-0000-0000-000000000001",
  "source_eval_run_id": "00000000-0000-0000-0000-000000000002",
  "external_key": "batch-2025-03-30-neunexus",
  "include_unlisted_queries": true,
  "proposals": [
    {
      "dataset_query_id": "abc-query-uuid-1",
      "candidates": [
        {
          "target_id": "l3-uuid-here",
          "target_type": "l3_id",
          "confidence": 0.92,
          "model_name": "gpt-4o-mini",
          "rationale": "Title and snippet match the query intent.",
          "evidence": { "hit_rank": 1, "snippet": "..." }
        }
      ]
    }
  ]
}
```

## Human review and Gold promotion

- `GET /curation/batches/{id}/queue` — unresolved items with candidates, sorted by lowest max confidence first.
- `POST /curation/batches/{id}/decisions` — `accept_candidate`, `set_target`, `reject`, or `no_target`.
- `POST /curation/batches/{id}/promote` — creates a new **Gold** dataset version; every query must have a **final** decision (no `unresolved`). Use `include_unlisted_queries` or one proposal per query when creating the batch.

See [runbook.md](runbook.md) for curl examples.
