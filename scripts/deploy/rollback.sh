#!/usr/bin/env bash
# Roll back the API to a previous image tag (data volumes are untouched —
# SQLite schema is fail-closed: a newer-schema DB refuses an older build,
# so verify /health after rollback and restore from backup if needed).
# Usage: ./scripts/deploy/rollback.sh <PREVIOUS_TAG> [.env.production]
set -euo pipefail
cd "$(dirname "$0")/../.."

TAG="${1:?Usage: rollback.sh <PREVIOUS_TAG> [.env.production]}"
ENV_FILE="${2:-.env.production}"
export ENV_FILE IMAGE_TAG="$TAG"

docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" up -d --remove-orphans api
exec ./scripts/deploy/verify-production.sh "$ENV_FILE"
