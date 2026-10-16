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

# Host-visible sandbox staging (R1 production execution topology).
# The engine stages Docker bind-mount sources under /app/sandbox-staging in
# the API container; the host daemon resolves the same directory at
# HOST_SANDBOX_STAGING_DIR, so it MUST be an absolute host path writable by
# uid/gid 10001 (the non-root API user). Named volumes and the /app/tmp
# tmpfs are invisible to the host daemon and MUST NOT be used here.
HOST_SANDBOX_STAGING_DIR="${HOST_SANDBOX_STAGING_DIR:-/opt/systemaops/sandbox-staging}"
export HOST_SANDBOX_STAGING_DIR
case "$HOST_SANDBOX_STAGING_DIR" in
  /*) ;;
  *) echo "FATAL: HOST_SANDBOX_STAGING_DIR must be an absolute host path, got '$HOST_SANDBOX_STAGING_DIR'." >&2; exit 1 ;;
esac
mkdir -p "$HOST_SANDBOX_STAGING_DIR"
if ! chown 10001:10001 "$HOST_SANDBOX_STAGING_DIR" 2>/dev/null; then
  echo "WARN: could not chown $HOST_SANDBOX_STAGING_DIR to 10001:10001 (run as root once: chown 10001:10001 '$HOST_SANDBOX_STAGING_DIR')." >&2
  echo "WARN: continuing — verify-production.sh will fail closed if the API user cannot write there." >&2
fi
chmod 0755 "$HOST_SANDBOX_STAGING_DIR"

docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" up -d --remove-orphans
exec ./scripts/deploy/verify-production.sh "$ENV_FILE"
