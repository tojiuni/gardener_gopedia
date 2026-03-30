# Universitas tiered eval samples (neunexus + gopedia)

Sources (clone paths):

- `/Users/dong-hoshin/Documents/dev/geneso/universitas/neunexus`
- `/Users/dong-hoshin/Documents/dev/geneso/universitas/gopedia`

Run `gopedia ingest [project_path]` on those trees (or a staged copy) so PostgreSQL / search index contain the chunks. **`target_id` values in these JSON files are placeholders** until you replace each with the real `l3_id` (or `doc_id` if you switch `target_type`) from `GET /api/search?format=json` for that query, choosing the chunk you judge correct.

| File | Tier | Intent |
|------|------|--------|
| `universitas_eval_easy.json` | Easy | Near-lexical / distinctive strings; one gold L3 per query. |
| `universitas_eval_medium.json` | Medium | Paraphrases and short natural questions. |
| `universitas_eval_hard.json` | Hard | Ambiguity, typo (`trafik`), mixed EN/KR, broader phrases. |
| `universitas_eval_token_efficiency.json` | Token efficiency | **Same queries and qrels as easy**; run eval twice and compare: default (full JSON) vs sparse payload. |

## Filling `REPLACE_L3_*` placeholders

1. Ingest universitas markdown into your Gopedia instance.
2. For each query string, call search (or run Gardener eval with empty qrels and pick from hits).
3. Replace `target_id` with the chosen hit’s `l3_id`.
4. `POST /datasets` with the edited JSON body (only `name`, `version`, `queries`, `qrels` are accepted by the API).

Expected source hints (for labeling, not stored in API):

- **nx_easy_traefik_minimal_label** → `neunexus/skills/traefik/references/labels.md`
- **nx_easy_macvlan_subnet** → `neunexus/skills/docker-network/references/overview.md`
- **gp_easy_l1_one_per_document** → `gopedia/reference/gopedia-feature-guide.md` (L1/L2/L3 table)
- Medium/hard rows map to traefik SKILL + labels, docker-network, gopedia SKILL + feature guide (overlap possible on hard).

## Token-efficiency tier (Gardener)

Use the **same** filled `universitas_eval_token_efficiency.json` (or easy file with identical qrels) and start two runs:

1. **Baseline:** omit `search_detail` / `search_fields` (full `results` from Gopedia).
2. **Sparse:** `POST /runs` with e.g. `"search_detail": "summary"` or `"search_fields": "title,snippet,l3_id,score"`.

Compare `GET /runs/{id}/metrics` and `GET /compare?baseline=...&candidate=...` to ensure small payloads do not regress ranking for the same gold IDs.

## Versioning

Bump `version` or `name` when you change queries or after re-ingest that assigns new chunk IDs.
