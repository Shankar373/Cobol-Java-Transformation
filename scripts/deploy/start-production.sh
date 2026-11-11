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
# App-level fail-closed switch: the API process itself verifies this pair
# (CONTROL_PLANE_ENV=production requires a token at import time).
export CONTROL_PLANE_ENV="${CONTROL_PLANE_ENV:-production}"
if [ -z "${CONTROL_PLANE_API_TOKEN:-}" ]; then
  echo "FATAL: CONTROL_PLANE_API_TOKEN is empty — refusing to start an unauthenticated production API." >&2
  exit 1
fi
if [ ! -f "${TLS_CERT_PATH:-./deployment/tls/fullchain.pem}" ] || [ ! -f "${TLS_KEY_PATH:-./deployment/tls/privkey.pem}" ]; then
  echo "FATAL: TLS cert/key not found (TLS_CERT_PATH/TLS_KEY_PATH) — refusing plaintext production." >&2
  exit 1
fi

# Image provenance record written by build-production.sh for this IMAGE_TAG (mounted into the api container, which
# verifies the Maven build image against it). Without it the candidate adapter is UNAVAILABLE and every run errors.
PROVENANCE="${IMAGE_PROVENANCE_PATH:-./test-artifacts/docker-image-provenance.${IMAGE_TAG}.json}"
if [ ! -f "$PROVENANCE" ]; then
  echo "FATAL: image provenance record $PROVENANCE not found - run scripts/deploy/build-production.sh ${IMAGE_TAG} first." >&2
  exit 1
fi

# Group owning the daemon socket (compose requires DOCKER_GID; no silent
# fallback to the root group). Shared with every compose entry point.
# shellcheck source=scripts/deploy/lib-docker-gid.sh
source ./scripts/deploy/lib-docker-gid.sh
resolve_docker_gid "$ENV_FILE"

# GnuCOBOL oracle pin (audit V5): the digest of the oracle image being
# deployed, unless the env file already declares one. The API refuses to
# start without it and the engine refuses to run any other oracle image.
if [ -z "${SYSTEMAOPS_ORACLE_DIGEST:-}" ]; then
  SYSTEMAOPS_ORACLE_DIGEST="$(python3 -c 'from engine.oracle.docker_adapter import oracle_image_digest; print(oracle_image_digest())' 2>/dev/null || true)"
fi
case "${SYSTEMAOPS_ORACLE_DIGEST:-}" in
  sha256:*) ;;
  *) echo "FATAL: could not resolve the GnuCOBOL oracle image digest (build it: scripts/deploy/build-production.sh)." >&2; exit 1 ;;
esac
export SYSTEMAOPS_ORACLE_DIGEST
echo "Oracle image pinned: $SYSTEMAOPS_ORACLE_DIGEST"

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
# Not fatal: a re-run as a non-root user finds the directory already owned by 10001 (chmod then fails, harmlessly).
chmod 0755 "$HOST_SANDBOX_STAGING_DIR" 2>/dev/null || [ "$(stat -c %a "$HOST_SANDBOX_STAGING_DIR")" = "755" ]

# Preflight: validate daemon reachability and the rendered stack BEFORE
# mutating anything. Without this, a stopped daemon or an unrenderable
# compose/env file surfaced as a partial `up` (half the services started)
# with an error that looked like an app failure rather than a config one.
if ! docker info >/dev/null 2>&1; then
  echo "FATAL: docker daemon not reachable — is Docker running (check 'docker context ls' for the right daemon)?" >&2
  exit 1
fi
if ! docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" config --quiet; then
  echo "FATAL: docker compose config does not render — fix the compose/env-file errors above; nothing was started." >&2
  exit 1
fi

docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" up -d --remove-orphans
exec ./scripts/deploy/verify-production.sh "$ENV_FILE"
