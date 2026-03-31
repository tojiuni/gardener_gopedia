#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=langfuse-docker-env.sh
source "${ROOT}/scripts/langfuse-docker-env.sh"
set_docker_env_for_langfuse "${ROOT}"

STACK_DIR="${ROOT}/.langfuse-docker"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gardener-langfuse}"
if [[ ! -f "${STACK_DIR}/docker-compose.yml" ]]; then
  echo "No ${STACK_DIR}/docker-compose.yml — run ./scripts/langfuse-up.sh first." >&2
  exit 1
fi
cd "${STACK_DIR}"
if docker compose version >/dev/null 2>&1; then
  docker compose -f "${STACK_DIR}/docker-compose.yml" down "$@"
else
  docker-compose -f "${STACK_DIR}/docker-compose.yml" down "$@"
fi
