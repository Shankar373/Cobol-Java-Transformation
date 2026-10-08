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

# 1. SQLite online backup through a transient container (same image family).
docker run --rm \
  -v systemaops-control-plane-data:/data:ro \
  -v "$PWD/$DEST:/out" \
  python:3.11-slim-bookworm \
  python3 -c "import sqlite3; src=sqlite3.connect('file:/data/control-plane.db?mode=ro', uri=True); dst=sqlite3.connect('/out/control-plane.db'); src.backup(dst); dst.close(); src.close()"

# 2. Workspaces (uploaded COBOL, generated Java apps, per-app files).
docker run --rm \
  -v systemaops-control-plane-work:/work:ro \
  -v "$PWD/$DEST:/out" \
  alpine:3.20 tar -czf /out/workspaces.tar.gz -C /work .

# 3. Release identity: what code produced this data.
docker image inspect systemaops-api:production > "$DEST/api-image.json" 2>/dev/null || echo '{"warning":"api image tag not found"}' > "$DEST/api-image.json"
cp test-artifacts/docker-image-provenance.production.json "$DEST/" 2>/dev/null || true
echo "$STAMP" > "$DEST/STAMP.txt"

echo "OK: backup written to $DEST"
ls -la "$DEST"
