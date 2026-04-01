#!/usr/bin/env bash
# ingest_universitas.sh — Ingest all universitas/ markdown files into Gopedia via REST API
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────
GOPEDIA_API="${GOPEDIA_API:-http://127.0.0.1:18787}"
HOST_BASE="${UNIVERSITAS_PATH:-/Users/dong-hoshin/Documents/dev/geneso/universitas}"
CONTAINER_PREFIX="${UNIVERSITAS_CONTAINER_PREFIX:-/universitas}"
DELAY="${DELAY:-0.5}"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "=== DRY RUN MODE — no files will be ingested ==="
fi

# ── Discover files ──────────────────────────────────────────────────────
mapfile -t FILES < <(find "$HOST_BASE" -name "*.md" -type f | sort)
TOTAL=${#FILES[@]}
echo "Found $TOTAL .md files in $HOST_BASE"
echo ""

if [[ "$DRY_RUN" == true ]]; then
  for f in "${FILES[@]}"; do
    container_path="${f/$HOST_BASE/$CONTAINER_PREFIX}"
    echo "  [dry-run] $container_path"
  done
  echo ""
  echo "Total: $TOTAL files (dry-run, nothing ingested)"
  exit 0
fi

# ── Ingest loop ─────────────────────────────────────────────────────────
SUCCESS=0
FAILED=0
FAILED_FILES=()
i=0

for f in "${FILES[@]}"; do
  i=$((i + 1))
  container_path="${f/$HOST_BASE/$CONTAINER_PREFIX}"
  printf "[%2d/%d] Ingesting %-70s ... " "$i" "$TOTAL" "$container_path"

  # Call Gopedia ingest API — capture response, don't let failure kill the script
  HTTP_CODE=""
  RESPONSE=""
  if RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${GOPEDIA_API}/api/ingest" \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"${container_path}\"}" 2>&1); then
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')
  else
    HTTP_CODE="000"
    BODY="$RESPONSE"
  fi

  # Check result
  if [[ "$HTTP_CODE" == "200" ]]; then
    # Extract doc_id from response if available
    DOC_ID=$(echo "$BODY" | sed -n 's/.*doc_id=\([^ "\\]*\).*/\1/p' | head -1)
    DOC_ID="${DOC_ID:-?}"
    echo "OK (doc_id=$DOC_ID)"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "FAIL (HTTP $HTTP_CODE)"
    echo "    Response: $BODY" | head -2
    FAILED=$((FAILED + 1))
    FAILED_FILES+=("$container_path")
  fi

  # Delay between calls
  sleep "$DELAY"
done

# ── Summary ─────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════"
echo "  Ingest Complete"
echo "  Total:   $TOTAL"
echo "  Success: $SUCCESS"
echo "  Failed:  $FAILED"
echo "════════════════════════════════════════════════════"

if [[ $FAILED -gt 0 ]]; then
  echo ""
  echo "Failed files:"
  for ff in "${FAILED_FILES[@]}"; do
    echo "  - $ff"
  done
  exit 1
fi
