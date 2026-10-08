#!/usr/bin/env bash
# Start (or upgrade) the production stack.
# Usage: ENV_FILE=.env.production IMAGE_TAG=production ./scripts/deploy/start-production.sh
# Preconditions: .env.production filled in (see .env.production.example),
# TLS files present at TLS_CERT_PATH / TLS_KEY_PATH.
set -euo pipefail
cd "$(dirname "$0")/../.."

ENV_FILE="${ENV_FILE:-.env.production}"
export ENV_FILE
export IMAGE_TAG="${IMAGE_TAG:-production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "FATAL: $ENV_FILE not found. Copy .env.production.example and fill in secrets." >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
if [ -z "${CONTROL_PLANE_API_TOKEN:-}" ]; then
  echo "FATAL: CONTROL_PLANE_API_TOKEN is empty — refusing to start an unauthenticated production API." >&2
  exit 1
fi
if [ ! -f "${TLS_CERT_PATH:-./deployment/tls/fullchain.pem}" ] || [ ! -f "${TLS_KEY_PATH:-./deployment/tls/privkey.pem}" ]; then
  echo "FATAL: TLS cert/key not found (TLS_CERT_PATH/TLS_KEY_PATH) — refusing plaintext production." >&2
  exit 1
fi

docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" up -d --remove-orphans
exec ./scripts/deploy/verify-production.sh "$ENV_FILE"
