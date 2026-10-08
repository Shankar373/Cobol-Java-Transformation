# Backup, Recovery, Rollback

## What is backed up (`scripts/backup/backup.sh`)

| Item | How | Why it must be preserved |
|---|---|---|
| `control-plane.db` (runs, verdicts, evidence manifests, reports, sealed hashes) | SQLite online backup API via transient container (consistent while running) | verdict↔evidence hash chain is only verifiable against this exact DB; `TRUST_BOUNDARY.md`: whole-record rewrites are undetectable without protected copies |
| `control-plane-work` volume (uploaded COBOL, generated Java, per-app files) | `tar.gz` of the volume | source/candidate bytes the hashes refer to |
| Release identity (`api-image.json`, `docker-image-provenance.*.json`) | `docker image inspect` + CI provenance file | proves which code/images produced the data; needed for rollback compatibility |

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
  `control-plane.db`, `workspaces.tar.gz`, `api-image.json`, `STAMP.txt`.
- **Restore (downtime):** `./scripts/backup/restore.sh <BACKUP_DIR>` —
  stops the stack, snapshots current volumes to `./backups/pre-restore-*`,
  recreates volumes, restores, restarts, re-verifies.
- **Rollback (code only):** `./scripts/deploy/rollback.sh <PREVIOUS_TAG>` —
  swaps the API image, leaves data untouched, re-verifies (incl. 401 check).
- **Failed deploy:** see `docs/operations/RUNBOOK.md` (rollback → if data
  involved, restore from backup, never hand-edit SQLite rows).

## Honest automation status

**NOT IMPLEMENTED:** no scheduler, no off-host replication, no
immutability/WORM, no restore drills in CI. `backup.sh` is manual until
an operator adds a cron/systemd timer and copies backup dirs off-host
(the only step that makes recovery real — a backup on the same disk as
production is not a backup). Recommended: daily `backup.sh` + off-host
copy + monthly `restore.sh` drill on a spare host. Authenticated DB seals
are future hardening per `docs/TRUST_BOUNDARY.md`, not a current claim.
