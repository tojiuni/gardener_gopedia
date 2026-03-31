#!/usr/bin/env bash
# Download upstream Langfuse Docker Compose and start the stack (dev / low-scale).
# See https://langfuse.com/self-hosting/deployment/docker-compose
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=langfuse-docker-env.sh
source "${ROOT}/scripts/langfuse-docker-env.sh"
set_docker_env_for_langfuse "${ROOT}"

STACK_DIR="${ROOT}/.langfuse-docker"
COMPOSE_URL="https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml"
mkdir -p "${STACK_DIR}"
echo "Fetching ${COMPOSE_URL}"
curl -fsSL -o "${STACK_DIR}/docker-compose.yml" "${COMPOSE_URL}"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "${STACK_DIR}/docker-compose.yml" "$@"
  else
    docker-compose -f "${STACK_DIR}/docker-compose.yml" "$@"
  fi
}

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gardener-langfuse}"
cd "${STACK_DIR}"
compose up -d "$@"
echo ""
echo "Langfuse web UI (default): http://127.0.0.1:3000"
echo "WARNING: upstream compose publishes Postgres on 127.0.0.1:5432 — change the host port in"
echo "  ${STACK_DIR}/docker-compose.yml if that collides with Gopedia or other Postgres."
