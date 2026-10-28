# Backup, Recovery, Rollback

## What is backed up (`scripts/backup/backup.sh`)

| Item | How | Why it must be preserved |
|---|---|---|
| `control-plane.db` (runs, verdicts, evidence manifests, reports, sealed hashes) | SQLite online backup API via transient container (consistent while running) | verdict↔evidence hash chain is only verifiable against this exact DB; `TRUST_BOUNDARY.md`: whole-record rewrites are undetectable without protected copies |
| `control-plane-work` volume (uploaded COBOL, generated Java, per-app files) | `tar.gz` of the volume | source/candidate bytes the hashes refer to |
| Release identity (`api-image.json`, `docker-image-provenance.production.json`, `STAMP.txt`) | `docker image inspect` + best-effort copy of the provenance file `scripts/deploy/build-production.sh` writes (skipped silently when absent; CI writes the untagged `docker-image-provenance.json` name instead) | proves which code/images produced the data; needed for rollback compatibility |

The workspace row only holds because production writes into the volume it
tars: `docker-compose.production.yml` and `Dockerfile.production` pin
`CONTROL_PLANE_WORKSPACE_DIR=/app/workspaces` (the `control-plane-work`
volume), `api/paths.py` creates every durable workspace under that root,
and `GET /ready` answers 503 if it is not writable. Left unset (the
development default) durable artifacts land in the platform temp
directory and the volume stays empty — the defect recorded in
`docs/RELEASE_GATE_WS4.md` §7.2 ("nothing ever writes workspaces to
`/app/workspaces`").

## Self-verification (step 4 of `backup.sh`)

A backup that exists is not a backup that works, so `backup.sh` ends by
running `scripts/backup/verify_backup.py` against the directory it just
wrote — inside the same pinned `python:3.11-slim-bookworm` image used for
the SQLite copy, with the backup mounted read-only. `set -e` is on: a
failed verification fails the whole backup, so `OK: backup written to …`
never prints on a bad one.

`verify_backup.py` is stdlib-only (exit 0 = verified, 1 = failed, 2 =
usage) and checks:

* `control-plane.db` exists, is non-empty, opens read-only, passes
  `PRAGMA integrity_check`, contains the `applications` and `runs`
  tables, and has `PRAGMA user_version` ≤ 6 (this build's
  `DB_SCHEMA_VERSION`; a newer schema would be refused by `Store` at
  restore anyway);
* `workspaces.tar.gz` exists and is a readable gzip tar with **at least
  one member** — an archive of an empty volume is the exact historic
  failure this check exists to catch;
* missing `STAMP.txt` / `api-image.json` are **WARN** only: you lose
  provenance, not the restore.

It also runs standalone against any backup directory:

```bash
python3 scripts/backup/verify_backup.py backups/<stamp>
```

## What can be reconstructed (not backed up)

Sandbox images (`gnucobol-ocesql`, `maven-offline-springboot`,
`eclipse-temurin:21-jdk`) — rebuild/repull via
`scripts/deploy/build-production.sh`. Frontend `dist/` — `npm run build`.
`/app/tmp` and per-run sandbox containers — ephemeral by design.

## What must be preserved

The DB + workspaces + release identity together. Restoring a DB with
mismatched workspace files breaks artifact-hash verifiability; restoring
a newer-schema DB under an older image is refused fail-closed (by design)
— match the image tag recorded in the backup.

## Procedures

- **Backup:** `./scripts/backup/backup.sh [DEST]` → timestamped dir with
  `control-plane.db`, `workspaces.tar.gz`, `api-image.json`, `STAMP.txt`,
  self-verified by step 4 (above) before it reports `OK`.
- **Restore (downtime):** `./scripts/backup/restore.sh <BACKUP_DIR>` —
  refuses a directory missing `control-plane.db` or `workspaces.tar.gz`
  before touching anything, stops the stack, snapshots current volumes to
  `./backups/pre-restore-*`, recreates both volumes, restores (files
  chowned to uid/gid `10001`, the user the API runs as), restarts via
  `start-production.sh`, which ends in `verify-production.sh`.
- **Rollback (code only):** `./scripts/deploy/rollback.sh <PREVIOUS_TAG>` —
  swaps the API image, leaves data untouched, re-verifies (incl. 401 check).
- **Failed deploy:** see `docs/operations/RUNBOOK.md` (rollback → if data
  involved, restore from backup, never hand-edit SQLite rows).

## Honest automation status

**NOT IMPLEMENTED:** no scheduler, no off-host replication, no
immutability/WORM, no restore drills in CI — and `backup.sh` itself is not
run by CI either (`.github/workflows/ci.yml` has no backup step);
verification runs *inside* a manual backup, not as a pipeline gate.
Scheduling stays with the operator: `backup.sh` is manual until someone
adds a cron/systemd timer, e.g.

```cron
# daily 03:15, copy off-host immediately afterwards
15 3 * * * cd /opt/systemaops/Cobol-Java-Transformation && ./scripts/backup/backup.sh && rsync -a ./backups/ backup-host:/backups/systemaops/
```

(the only step that makes recovery real — a backup on the same disk as
production is not a backup). Recommended: daily `backup.sh` + off-host
copy + monthly `restore.sh` drill on a spare host. Authenticated DB seals
are future hardening per `docs/TRUST_BOUNDARY.md`, not a current claim.
