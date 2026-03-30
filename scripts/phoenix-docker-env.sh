# Sourced by phoenix-up.sh / phoenix-down.sh.
# Minimal DOCKER_CONFIG drops cred helpers but also omits context → CLI may default to
# unix:///var/run/docker.sock (missing on macOS + Colima). Set DOCKER_HOST when needed.
set_docker_env_for_phoenix() {
  local root="$1"
  export DOCKER_CONFIG="${root}/scripts/docker/phoenix-minimal-docker-config"

  if [[ -n "${DOCKER_HOST:-}" ]]; then
    return 0
  fi
  if [[ -S /var/run/docker.sock ]]; then
    return 0
  fi

  local sock
  for sock in \
    "${HOME}/.colima/default/docker.sock" \
    "${HOME}/.colima/docker.sock" \
    "${HOME}/.rd/docker.sock"; do
    if [[ -S "$sock" ]]; then
      export DOCKER_HOST="unix://${sock}"
      return 0
    fi
  done

  echo "error: no Docker socket found (set DOCKER_HOST or start Colima / Docker Desktop)" >&2
  return 1
}
