# Sourced by langfuse-up.sh / langfuse-down.sh.
# Minimal Docker config (no credsStore) for pulls when desktop credential helpers break PATH.

set_docker_env_for_langfuse() {
  local root="${1:?}"
  export DOCKER_CONFIG="${root}/scripts/docker/langfuse-minimal-docker-config"
  if [[ ! -S /var/run/docker.sock ]] && [[ -z "${DOCKER_HOST:-}" ]]; then
    if [[ -S "${HOME}/.colima/default/docker.sock" ]]; then
      export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
    elif docker context ls 2>/dev/null | grep -q colima; then
      export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
    fi
  fi
}
