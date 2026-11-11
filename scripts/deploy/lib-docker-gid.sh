#!/usr/bin/env bash
# Sourced (not executed) by every script that runs `docker compose` on the
# production file: start-production.sh, verify-production.sh, rollback.sh,
# scripts/backup/restore.sh.
#
# docker-compose.production.yml requires DOCKER_GID (the group owning
# /var/run/docker.sock; no silent root-group default). Compose interpolates
# it on EVERY command (config, ps, up, down), so each entry point must
# resolve it the same way:
#   1. DOCKER_GID already in the environment;
#   2. else a DOCKER_GID= line in the env file;
#   3. else the socket's group (stat -c %g /var/run/docker.sock).
# Usage: resolve_docker_gid <env-file>   (exports DOCKER_GID or exits 1)

resolve_docker_gid() {
  local env_file="${1:-}"
  if [ -z "${DOCKER_GID:-}" ] && [ -n "$env_file" ] && [ -f "$env_file" ]; then
    DOCKER_GID="$(sed -n 's/^DOCKER_GID=\([0-9][0-9]*\)[[:space:]]*$/\1/p' "$env_file" | tail -n 1)"
  fi
  if [ -z "${DOCKER_GID:-}" ]; then
    if ! DOCKER_GID="$(stat -c %g /var/run/docker.sock 2>/dev/null)"; then
      echo "FATAL: DOCKER_GID unset and /var/run/docker.sock not found — set DOCKER_GID in ${env_file:-the env file}." >&2
      exit 1
    fi
  fi
  if [ "$DOCKER_GID" = "0" ]; then
    echo "WARN: DOCKER_GID=0 — the API process joins the root group (socket is root:root)." >&2
  fi
  export DOCKER_GID
}
