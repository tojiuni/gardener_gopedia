#!/usr/bin/env bash
# Start Arize Phoenix for Gardener OTLP traces. Uses a minimal Docker config so
# pulls work when ~/.docker points at a missing credential helper (e.g. docker-credential-desktop).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=phoenix-docker-env.sh
source "${ROOT}/scripts/phoenix-docker-env.sh"
set_docker_env_for_phoenix "${ROOT}"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "error: need 'docker compose' (plugin) or docker-compose on PATH" >&2
    exit 1
  fi
}

compose -f "${ROOT}/docker-compose.phoenix.yml" up -d "$@"
echo "Phoenix UI: http://127.0.0.1:6006"
echo "OTLP HTTP:  http://127.0.0.1:6006/v1/traces"
