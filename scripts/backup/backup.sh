#!/usr/bin/env bash
# Online backup of production state (no downtime).
# Captures: SQLite DB (via SQLite online backup API — crash-consistent even
# while the API is running), workspace files, and the release identity
# (image tag + provenance file) needed to restore/roll back.
# Automated scheduling (cron/systemd) is NOT installed by this script —
# see docs/operations/BACKUP_RECOVERY.md.
# Usage: ./scripts/backup/backup.sh [BACKUP_DIR]  (default: ./backups/<timestamp>)
set -euo pipefail
cd "$(dirname "$0")/../.."

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${1:-./backups/${STAMP}}"
mkdir -p "$DEST"

# Bind sources passed to `docker run -v` must be valid HOST paths. Under
# WSL (Git bash / WSL distro) the PWD is a /mnt/<drive>/... path that the
# Windows Docker daemon does not resolve, so translate it to a Windows
# path before mounting. On a native Linux host wslpath is unavailable and
# the path is already a valid host path.
host_path() { # host_path <path>
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$1"
  else
    echo "$1"
  fi
}
DEST_HOST="$(host_path "$PWD/$DEST")"

# 1. SQLite online backup through a transient container (same image family).
docker run --rm \
  -v systemaops-control-plane-data:/data:ro \
  -v "$DEST_HOST:/out" \
  python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 \
  python3 -c "import sqlite3; src=sqlite3.connect('file:/data/control-plane.db?mode=ro', uri=True); dst=sqlite3.connect('/out/control-plane.db'); src.backup(dst); dst.close(); src.close()"

# 2. Workspaces (uploaded COBOL, generated Java apps, per-app files).
docker run --rm \
  -v systemaops-control-plane-work:/work:ro \
  -v "$DEST_HOST:/out" \
  alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc tar -czf /out/workspaces.tar.gz -C /work .

# 3. Release identity: what code produced this data.
docker image inspect systemaops-api:production > "$DEST/api-image.json" 2>/dev/null || echo '{"warning":"api image tag not found"}' > "$DEST/api-image.json"
cp test-artifacts/docker-image-provenance.production.json "$DEST/" 2>/dev/null || true
echo "$STAMP" > "$DEST/STAMP.txt"

echo "OK: backup written to $DEST"
ls -la "$DEST"
