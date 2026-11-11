#!/usr/bin/env bash
# Roll back the API to a previous image tag (data volumes are untouched —
# SQLite schema is fail-closed: a newer-schema DB refuses an older build,
# so verify /health after rollback and restore from backup if needed).
# Usage: ./scripts/deploy/rollback.sh <PREVIOUS_TAG> [.env.production]
set -euo pipefail
cd "$(dirname "$0")/../.."

TAG="${1:?Usage: rollback.sh <PREVIOUS_TAG> [.env.production]}"
ENV_FILE="${2:-.env.production}"
# shellcheck source=scripts/deploy/lib-docker-gid.sh
source ./scripts/deploy/lib-docker-gid.sh
resolve_docker_gid "$ENV_FILE"

# Compose resolves `--env-file` entries over the shell environment, so an
# `export IMAGE_TAG=...` is silently overridden when the env file itself
# pins IMAGE_TAG (as .env.production does — found by the R10 rollback
# drill: the container never switched images). Derive a temporary env
# file with the requested tag and pass that instead. Removed on exit;
# it contains the API token. Kept relative to the repo root so both the
# POSIX shell and the Windows docker.exe resolve it to the same file.
# A shell-exported IMAGE_TAG (left over from start-production.sh, say) overrides the env file in compose and turned the
# rollback into a silent no-op (staging drill, 2026-11-11); the tag comes from the derived env file only.
unset IMAGE_TAG
ROLLBACK_ENV=".env.rollback.$$"
# Owner-only: the copy carries the API token.
( umask 077; sed "s/^IMAGE_TAG=.*/IMAGE_TAG=$TAG/" "$ENV_FILE" > "$ROLLBACK_ENV" )
trap 'rm -f "$ROLLBACK_ENV"' EXIT

# --wait: block until the recreated api container is healthy, otherwise
# verify-production.sh races the first healthcheck and reports a false
# "api container healthy" failure (found by the R10 rollback drill).
docker compose -f docker-compose.production.yml --env-file "$ROLLBACK_ENV" up -d --remove-orphans --wait api
export ENV_FILE IMAGE_TAG="$TAG"
# Not `exec`: the EXIT trap must run to delete ROLLBACK_ENV (token file).
./scripts/deploy/verify-production.sh "$ROLLBACK_ENV"
status=$?
exit $status
