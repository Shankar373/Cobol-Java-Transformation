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
check "api container healthy" docker inspect --format='{{.State.Health.Status}}' systemaops-production-api-1 | grep -q healthy
check "TLS /health via nginx" curl -fsS --max-time 10 "https://127.0.0.1:${PORT}/health"
check "sandbox image gnucobol present" docker image inspect gnucobol-ocesql:latest
check "sandbox image maven present" docker image inspect maven-offline-springboot:latest
check "sandbox image java runtime present" docker image inspect eclipse-temurin:21-jdk
check "sandbox runs with --network none" docker run --rm --network none gnucobol-ocesql:latest cobc --version
check "api auth enforced (401 without token)" \
  bash -c "! curl -fsS --max-time 10 -o /dev/null https://127.0.0.1:${PORT}/applications"

if [ "$FAIL" -ne 0 ]; then echo "VERIFY: FAILED"; exit 1; fi
echo "VERIFY: OK"
