#!/usr/bin/env bash
# Post-deploy verification: containers healthy, TLS serves, /health OK,
# sandbox isolation flags intact. Non-zero exit = deployment FAILED.
# Usage: ./scripts/deploy/verify-production.sh [.env.production]
set -euo pipefail
cd "$(dirname "$0")/../.."

ENV_FILE="${1:-.env.production}"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi
PORT="${HTTPS_PORT:-443}"
FAIL=0

check() { # check <label> <command...>
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS: $label"; else echo "FAIL: $label"; FAIL=1; fi
}

check "compose config renders" docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" config
# NOTE: not via check()|grep — the label text would satisfy the grep.
if [ "$(docker inspect --format='{{.State.Health.Status}}' systemaops-production-api-1 2>/dev/null)" = "healthy" ]; then
  echo "PASS: api container healthy"
else
  echo "FAIL: api container healthy"; FAIL=1
fi
check "TLS /health via nginx" curl -fsS --max-time 10 "https://127.0.0.1:${PORT}/health"
check "sandbox image gnucobol present" docker image inspect gnucobol-ocesql:latest
check "sandbox image maven present" docker image inspect maven-offline-springboot:latest
check "sandbox image java runtime present" docker image inspect eclipse-temurin:21-jdk
check "sandbox runs with --network none" docker run --rm --network none gnucobol-ocesql:latest cobc --version
check "api auth enforced (401 without token)" \
  bash -c "! curl -fsS --max-time 10 -o /dev/null https://127.0.0.1:${PORT}/applications"

# --- R1: host-visible sandbox staging --------------------------------------
# The engine stages Docker bind sources under /app/sandbox-staging and the
# host daemon resolves the same directory at HOST_SANDBOX_STAGING_DIR.
STAGING="${HOST_SANDBOX_STAGING_DIR:-/opt/systemaops/sandbox-staging}"
TAG="${IMAGE_TAG:-production}"
case "$STAGING" in
  /*) echo "PASS: staging dir is absolute ($STAGING)" ;;
  *) echo "FAIL: staging dir is not absolute ($STAGING)"; FAIL=1 ;;
esac
check "staging dir exists on host" test -d "$STAGING"
check "api mounts /app/sandbox-staging" \
  bash -c "docker inspect systemaops-production-api-1 | grep -q /app/sandbox-staging"
check "staging writable as uid 10001" \
  docker run --rm --network none --user 10001:10001 -v "${STAGING}:/probe" "systemaops-api:${TAG}" \
    sh -c 'touch /probe/.writability-probe && rm /probe/.writability-probe'
check "host file visible through staging bind" \
  bash -c "echo probe > '${STAGING}/.visibility-probe' && docker run --rm --network none -v '${STAGING}:/probe' 'systemaops-api:${TAG}' cat /probe/.visibility-probe | grep -q probe; rm -f '${STAGING}/.visibility-probe'"

# --- R8: frontend production routing ----------------------------------------
check "frontend /app/ serves index" \
  bash -c "curl -fsS --max-time 10 'https://127.0.0.1:${PORT}/app/' | grep -q 'id=\"root\"'"
ASSET="$(ls frontend/dist/assets/* 2>/dev/null | head -n 1)"
if [ -n "${ASSET:-}" ]; then
  ASSET_NAME="$(basename "$ASSET")"
  check "frontend asset serves under /app/assets/" \
    bash -c "curl -fsS --max-time 10 -o /dev/null 'https://127.0.0.1:${PORT}/app/assets/${ASSET_NAME}'"
else
  echo "FAIL: no built frontend asset found in frontend/dist/assets/"; FAIL=1
fi
check "frontend SPA fallback serves index" \
  bash -c "curl -fsS --max-time 10 'https://127.0.0.1:${PORT}/app/runs/does-not-exist' | grep -q 'id=\"root\"'"
check "frontend index references /app/ assets" \
  bash -c "curl -fsS --max-time 10 'https://127.0.0.1:${PORT}/app/' | grep -q '/app/assets/'"

if [ "$FAIL" -ne 0 ]; then echo "VERIFY: FAILED"; exit 1; fi
echo "VERIFY: OK"
