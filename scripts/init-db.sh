#!/usr/bin/env bash
# Create Postgres schema (if GARDENER_POSTGRES_SCHEMA) and Gardener tables.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "error: expected venv at $PY" >&2
  exit 1
fi
exec "$PY" -m gardener_gopedia.db_bootstrap
