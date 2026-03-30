#!/usr/bin/env bash
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

compose -f "${ROOT}/docker-compose.phoenix.yml" down "$@"
