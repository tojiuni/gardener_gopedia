#!/usr/bin/env bash
# reset_gopedia_index.sh — Truncate all Gopedia PostgreSQL tables and reset Qdrant collections
# Usage: ./scripts/reset_gopedia_index.sh --dry-run | --confirm

set -euo pipefail

# --- Config ---
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-admin_gopedia}"
PGPASSWORD="${PGPASSWORD:-changeme_local_only}"
PGDATABASE="${PGDATABASE:-gopedia}"
export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE

QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"

TABLES=(keyword_so knowledge_l3 knowledge_l2 knowledge_l1 documents projects pipeline_version)
COLLECTIONS=(gopedia_markdown gopedia_document)

# --- Helpers ---
psql_cmd() {
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A "$@"
}

row_count() {
  psql_cmd -c "SELECT count(*) FROM public.${1};" 2>/dev/null || echo "N/A"
}

qdrant_point_count() {
  local resp
  resp=$(curl -sf "${QDRANT_URL}/collections/${1}" 2>/dev/null) || { echo "N/A (not found)"; return; }
  echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result']['points_count'])" 2>/dev/null || echo "N/A"
}

qdrant_delete_collection() {
  curl -sf -X DELETE "${QDRANT_URL}/collections/${1}" > /dev/null 2>&1 || true
}

qdrant_create_collection() {
  curl -sf -X PUT "${QDRANT_URL}/collections/${1}" \
    -H 'Content-Type: application/json' \
    -d '{
      "vectors": { "size": 1536, "distance": "Cosine" },
      "on_disk_payload": true
    }' > /dev/null 2>&1
}

usage() {
  echo "Usage: $0 --dry-run | --confirm"
  echo ""
  echo "  --dry-run   Show current state and what would be deleted"
  echo "  --confirm   Execute the reset (truncate tables, recreate collections)"
  exit 1
}

# --- Parse args ---
MODE=""
case "${1:-}" in
  --dry-run) MODE="dry-run" ;;
  --confirm) MODE="confirm" ;;
  *) usage ;;
esac

echo "=== Gopedia Index Reset (mode: ${MODE}) ==="
echo ""

# --- Dry-run ---
if [[ "$MODE" == "dry-run" ]]; then
  echo "--- PostgreSQL tables (public schema) ---"
  for t in "${TABLES[@]}"; do
    count=$(row_count "$t")
    echo "  ${t}: ${count} rows"
  done

  echo ""
  echo "--- Qdrant collections ---"
  for c in "${COLLECTIONS[@]}"; do
    count=$(qdrant_point_count "$c")
    echo "  ${c}: ${count} points"
  done

  echo ""
  echo "Would TRUNCATE: ${TABLES[*]} (CASCADE)"
  echo "Would DELETE & RECREATE: ${COLLECTIONS[*]}"
  echo ""
  echo "Run with --confirm to execute."
  exit 0
fi

# --- Confirm ---
echo ">>> Truncating PostgreSQL tables (public schema only)..."
TRUNCATE_LIST=$(IFS=', '; echo "${TABLES[*]}")
psql_cmd -c "TRUNCATE ${TRUNCATE_LIST} CASCADE;"
echo "    Done."

echo ""
echo ">>> Resetting Qdrant collections..."
for c in "${COLLECTIONS[@]}"; do
  echo "    Deleting collection: ${c}"
  qdrant_delete_collection "$c"
  echo "    Creating collection: ${c} (1536-dim, Cosine, on_disk_payload)"
  qdrant_create_collection "$c"
done
echo "    Done."

echo ""
echo ">>> Verification..."
echo "--- PostgreSQL row counts ---"
for t in "${TABLES[@]}"; do
  count=$(row_count "$t")
  echo "  ${t}: ${count} rows"
done

echo ""
echo "--- Qdrant point counts ---"
for c in "${COLLECTIONS[@]}"; do
  count=$(qdrant_point_count "$c")
  echo "  ${c}: ${count} points"
done

echo ""
echo "=== Reset complete ==="
