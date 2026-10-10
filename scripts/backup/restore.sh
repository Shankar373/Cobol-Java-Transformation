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

# Bind sources for `docker run -v` must be valid host paths; WSL mounts
# (/mnt/<drive>/...) are not understood by the Windows Docker daemon, so
# translate through wslpath when available.
host_path() { # host_path <path>
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$1"
  else
    echo "$1"
  fi
}
SRC_HOST="$(host_path "$PWD/$SRC")"

docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" down

# Snapshot current (possibly broken) state before overwriting.
SNAP="./backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$SNAP"
docker run --rm -v systemaops-control-plane-data:/data:ro -v "$(host_path "$PWD/$SNAP"):/out" \
  alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc tar -czf /out/data-vol.tar.gz -C /data . || true
echo "Pre-restore snapshot: $SNAP"

# Restore DB + workspaces into fresh volumes. The restored files are
# chowned to uid/gid 10001 — the non-root user the production API runs
# as. Without this the SQLite DB stays root-owned and the API crashes
# with "attempt to write a readonly database" (found by the R10 drill).
docker volume rm systemaops-control-plane-data systemaops-control-plane-work 2>/dev/null || true
docker volume create systemaops-control-plane-data >/dev/null
docker volume create systemaops-control-plane-work >/dev/null
docker run --rm -v systemaops-control-plane-data:/data -v "$SRC_HOST:/in" \
  alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc sh -c "cp /in/control-plane.db /data/control-plane.db && chown -R 10001:10001 /data"
docker run --rm -v systemaops-control-plane-work:/work -v "$SRC_HOST:/in" \
  alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc sh -c "tar -xzf /in/workspaces.tar.gz -C /work && chown -R 10001:10001 /work"

ENV_FILE="$ENV_FILE" ./scripts/deploy/start-production.sh
