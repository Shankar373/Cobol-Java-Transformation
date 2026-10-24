# Operations Runbook

## Health and lifecycle

| Probe | What | Where |
|---|---|---|
| Liveness | `GET /health` → `{"status":"ok"}` (no auth) | app, compose `healthcheck`, nginx passthrough |
| Readiness | **NOT IMPLEMENTED** — liveness only proves the process answers, not that SQLite is writable or workers have capacity | gap, see below |
| Startup | `Store.mark_interrupted_runs()`: any run left non-terminal by a restart is failed once (its daemon worker died with the old process) | `api/app.py` |
| Shutdown | SIGTERM → uvicorn graceful stop; in-flight daemon workers are killed, their runs fail at next startup | exec-form CMD (PID 1 = uvicorn) |
| Worker accounting | bounded by `CONTROL_PLANE_MAX_CONCURRENT_JOBS`; 429 when full; slots released even on crash | `api/app.py` + store |

**Required application changes (out of scope for this workstream —
reported, not implemented, because `api/` is owned by parallel agents):**

1. Split readiness from liveness: add an authenticated `GET /ready`
   that opens the SQLite DB and reports worker-slot pressure, so the
   proxy/orchestrator can drain an unready-but-alive node.
2. Structured operational logging: today's logging is ad-hoc
   (`logging` calls in `api/app.py`); emit one JSON line per run
   lifecycle event with the fields below.
3. Note (pre-existing, found during audit): `GET /runs/{id}/report` is
   registered **twice** in `api/app.py` (identical duplicate decorator).
   Harmless today (second registration wins) but should be deduped by the
   owning agent.

## Recommended operational log fields

Every run-lifecycle event should carry: `run_id`, `workload_id`,
`application_id`, `phase`, `event`, `status`, `duration`,
`error_code`, `correlation_id`, `timestamp`. Until the app emits these,
correlate via `docker logs` timestamps + `GET /runs/{id}` /
`/runs/{id}/detail` polling.

## Failed runs and cleanup

- Failed runs stay queryable (`GET /runs/{id}/detail`); only terminal
  runs can be revalidated (`POST /runs/{id}/validate`, 409 on in-flight).
- Sandbox containers are `--rm` with hard timeouts; no manual container
  GC is expected. If the daemon fills with orphans after a host crash,
  `docker container prune -f` on the host is safe (no sandbox container
  holds state — all evidence is copied out before removal).
- `/app/tmp` (tmpfs) and Maven `target/` tmpfs vanish with the container.
  No retention/TTL policy exists for old runs in SQLite (documented gap)
  — do not delete rows by hand; the evidence seal chains assume stable
  history (see `docs/TRUST_BOUNDARY.md`).

## Failed-deployment recovery

1. `verify-production.sh` failing after `up -d` → run
   `./scripts/deploy/rollback.sh <PREVIOUS_TAG>` (image tags from
   `docker images systemaops-api`). Data volumes are untouched.
2. API unhealthy but nginx healthy → `docker logs systemaops-production-api-1`;
   common cause: `.env.production` missing token (start script guards
   this) or a newer-schema DB file mounted into an older image (fail
   closed by design) → restore from backup instead.
3. DB or volume corruption → `./scripts/backup/restore.sh <BACKUP_DIR>`
   (stops stack, snapshots current volumes under `./backups/pre-restore-*`,
   restores, re-verifies). See `docs/operations/BACKUP_RECOVERY.md`.
