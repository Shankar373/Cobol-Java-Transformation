#!/usr/bin/env bash
# Restore production state from a backup directory created by backup.sh.
# Downtime is required: the stack is stopped first so no worker writes
# mid-restore. The previous volumes are snapshotted (not deleted) before
# the restore, so a bad restore can itself be rolled back.
# Usage: ./scripts/backup/restore.sh <BACKUP_DIR> [.env.production]
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC="${1:?Usage: restore.sh <BACKUP_DIR> [.env.production]}"
ENV_FILE="${2:-.env.production}"
if [ ! -f "$SRC/control-plane.db" ] || [ ! -f "$SRC/workspaces.tar.gz" ]; then
  echo "FATAL: $SRC is not a complete backup (need control-plane.db + workspaces.tar.gz)." >&2
  exit 1
fi

docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" down

# Snapshot current (possibly broken) state before overwriting.
SNAP="./backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$SNAP"
docker run --rm -v systemaops-control-plane-data:/data:ro -v "$PWD/$SNAP:/out" \
  alpine:3.20 tar -czf /out/data-vol.tar.gz -C /data . || true
echo "Pre-restore snapshot: $SNAP"

# Restore DB + workspaces into fresh volumes.
docker volume rm systemaops-control-plane-data systemaops-control-plane-work 2>/dev/null || true
docker volume create systemaops-control-plane-data >/dev/null
docker volume create systemaops-control-plane-work >/dev/null
docker run --rm -v systemaops-control-plane-data:/data -v "$PWD/$SRC:/in" \
  alpine:3.20 sh -c "cp /in/control-plane.db /data/control-plane.db"
docker run --rm -v systemaops-control-plane-work:/work -v "$PWD/$SRC:/in" \
  alpine:3.20 tar -xzf /in/workspaces.tar.gz -C /work

ENV_FILE="$ENV_FILE" ./scripts/deploy/start-production.sh
