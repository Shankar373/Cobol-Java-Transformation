# Operations Runbook

## Health and lifecycle

| Probe | What | Where |
|---|---|---|
| Liveness | `GET /health` → `{"status":"ok"}` (no auth) — the process answers, nothing more | `api/app.py`, nginx `location = /health` passthrough |
| Readiness | `GET /ready` (no auth) → `200` `{"status":"ready","checks":{...}}` when database + workspace + staging are usable; `503` `{"status":"not_ready","checks":{...}}` when a gating dependency is down | `api/app.py`, compose `healthcheck`, `Dockerfile.production` `HEALTHCHECK`, nginx `location = /ready`, `verify-production.sh` |
| Startup | `Store.mark_interrupted_runs()`: any run left non-terminal by a restart is failed once (its daemon worker died with the old process); logged as `startup.reconciled`, or `startup.reconcile_failed` if the reconciliation itself throws | `api/app.py` |
| Shutdown | SIGTERM → uvicorn graceful stop; in-flight daemon workers are killed, their runs fail at next startup | exec-form CMD (PID 1 = uvicorn) |
| Worker accounting | bounded by `CONTROL_PLANE_MAX_CONCURRENT_JOBS`; 429 when full; slots released even on crash; `checks.jobs` in `/ready` reports active/limit (informational) | `api/app.py` + store |

**`/ready` semantics (`api/app.py`):** every check appears under
`checks` with `ok`/`detail`. Three are **gating** — `database` must open
read-write (uploads and run updates are writes; a read-only or missing
file is not ready), `workspace` (`CONTROL_PLANE_WORKSPACE_DIR` creatable
and writable; unset = development temp dir, reported healthy, not a
fault), `staging` (`SANDBOX_STAGING_DIR` usable; unset = development
temp staging). A `503` therefore means "this control plane cannot
persist anything", where `/health` would still answer `200`. `docker` is
probed and **reported but never gating**: a host daemon outage cannot be
fixed by restarting this container (restarting on it would loop); runs
fail closed at the execution stage instead. `jobs` is informational.
Both probes are exempt from bearer auth because an orchestrator probe
cannot carry a token; with a token configured (always, in production)
every other route requires it — CORS preflight `OPTIONS` excepted, since
a preflight never carries credentials (see `docs/security/PRODUCTION_SECURITY.md`).

**Earlier audit items — status in this tree:**

1. Split readiness from liveness — **implemented**: `GET /ready` above,
   wired into the compose `healthcheck`, the image `HEALTHCHECK`, the
   nginx `location = /ready` passthrough and the `TLS /ready` check in
   `scripts/deploy/verify-production.sh`.
2. Structured operational logging — **implemented**: `api/logging_config.py`
   (next section).
3. Duplicate `GET /runs/{id}/report` registration noted in the earlier
   audit — **gone**: the route is registered exactly once in `api/app.py`.

## Structured operational logging

Configured once at import by `api/logging_config.py` (stdlib only, one
idempotent root handler — importing the app twice cannot duplicate
lines):

- **Level:** `CONTROL_PLANE_LOG_LEVEL` (default `INFO`; an unknown value
  falls back to `INFO` with a one-line notice on stderr instead of
  silencing logging).
- **Format:** `CONTROL_PLANE_LOG_FORMAT` = `json` | `text`; defaults to
  `json` when `CONTROL_PLANE_ENV=production`, `text` otherwise. JSON
  records carry `ts`, `level`, `logger`, `message`, `request_id` plus any
  structured extras (`run_id`, `stage`, `event`, ...).

**Request correlation.** Every response carries `X-Request-Id`: an
incoming id is echoed only when it matches `[A-Za-z0-9._-]{1,64}`
(never reflected raw, so it cannot inject response headers), otherwise a
fresh `uuid4().hex` is minted. That id is attached to every record
emitted while handling the request — including a 401. Exactly one access
line per request:

```json
{"ts": "2026-10-26T09:15:04.123Z", "level": "INFO", "logger": "api.app", "message": "request", "request_id": "a1b2c3...", "event": "http.request", "method": "GET", "path": "/runs/abc", "status": 200, "duration_ms": 12.3}
```

(Verbatim shape of the JSON formatter's output: `json.dumps` default
separators, one object per line.)

Method, path, status, duration — never headers, never tokens.

**Run lifecycle events.** Every `run.*` event carries `run_id`; most
also carry `application_id` (`run.missing` carries only `run_id`), and
the terminal ones carry `stage` (`run.terminal_persist_failed` also
carries `attempts`):

| Event | Emitted at |
|---|---|
| `run.started` | background modernize worker launched (`api/service.py`) |
| `run.revalidating` | background revalidation worker launched |
| `run.failed` | background worker caught an exception |
| `run.missing` | worker could not find its run in the store |
| `run.terminal` | terminal state written to SQLite |
| `run.terminal_persist_failed` | terminal write still failing after the bounded retries |
| `startup.reconciled` / `startup.reconcile_failed` | restart reconciliation of interrupted runs (`api/app.py`) |

Log lines to grep (JSON lines — the production default of
`CONTROL_PLANE_LOG_FORMAT`; the keys are emitted by `json.dumps` with a
space after the colon, so the pattern must include it. Event names below
all exist in the code; `<api>` is the container id — see failed-deployment
recovery for deriving it):

```bash
docker logs <api> | grep '"event": "run.started"'
docker logs <api> | grep '"event": "run.terminal"'
docker logs <api> | grep '"event": "run.terminal_persist_failed"'
docker logs <api> | grep '"event": "startup.reconciled"'
docker logs <api> | grep '"event": "http.request"'
```

Correlate one request end-to-end via `request_id`; one run end-to-end
via `run_id` (falling back to `GET /runs/{id}` / `/runs/{id}/detail`
polling for state, since the DB, not the log, is the source of truth).

## Failed runs and cleanup

- Failed runs stay queryable (`GET /runs/{id}/detail`); only terminal
  runs can be revalidated (`POST /runs/{id}/validate`, 409 on in-flight).
- Sandbox containers are `--rm` with hard timeouts; no manual container
  GC is expected. If the daemon fills with orphans after a host crash,
  `docker container prune -f` on the host is safe (no sandbox container
  holds state — all evidence is copied out before removal).
- `/app/tmp` (tmpfs) and Maven `target/` tmpfs vanish with the container —
  they hold scratch only. Durable artifacts (uploaded COBOL, generated
  bundle) live under `CONTROL_PLANE_WORKSPACE_DIR` (`/app/workspaces`,
  named volume) and are captured by `scripts/backup/backup.sh`.
  No retention/TTL policy exists for old runs in SQLite (documented gap)
  — do not delete rows by hand; the evidence seal chains assume stable
  history (see `docs/TRUST_BOUNDARY.md`).

## Production start: preflight and configuration floors

`./scripts/deploy/start-production.sh` fails with `FATAL` **before**
`docker compose up -d` mutates anything when:

- `$ENV_FILE` (default `.env.production`) does not exist;
- `CONTROL_PLANE_API_TOKEN` is empty;
- `TLS_CERT_PATH` / `TLS_KEY_PATH` file is missing (no plaintext start);
- `HOST_SANDBOX_STAGING_DIR` is not an absolute host path;
- `docker info` cannot reach the daemon (wrong context / daemon down);
- `docker compose ... config --quiet` does not render (compose or
  env-file errors) — nothing is started, so a config error can no longer
  surface as a half-started stack.

Token floor: with `CONTROL_PLANE_ENV=production`,
`verify_production_auth_configuration()` runs at import and refuses to
start when `CONTROL_PLANE_API_TOKEN` is shorter than **32 characters**
(the error prints the generator
`python -c "import secrets; print(secrets.token_urlsafe(48))"`). An
unrecognised `CONTROL_PLANE_ENV` also fails closed; development/test
accept any length. The shell preflight only rejects an *empty* token —
a 5-character token gets as far as the API process, which dies at import
and leaves the container restarting.

Backups: `./scripts/backup/backup.sh` self-verifies every backup
(`scripts/backup/verify_backup.py` runs as step 4 under `set -e`, so a
failed verification fails the whole backup). It is manual — no schedule
in this repo, and CI does not run it. See
`docs/operations/BACKUP_RECOVERY.md`.

## Failed-deployment recovery

1. `verify-production.sh` failing after `up -d` → run
   `./scripts/deploy/rollback.sh <PREVIOUS_TAG>` (image tags from
   `docker images systemaops-api`). Data volumes are untouched.
2. API unhealthy but nginx healthy → read the API log with the
   compose-derived container id, never a hardcoded name:
   `docker compose -f docker-compose.production.yml --env-file .env.production ps -q --all api`
   then `docker logs <id>` (or `... logs api`); common cause:
   `.env.production` token missing (start script + compose refuse it) or
   too short (the import-time guard kills the API at startup), or a
   newer-schema DB file mounted into an
   older image (fail closed by design) → restore from backup instead.
3. DB or volume corruption → `./scripts/backup/restore.sh <BACKUP_DIR>`
   (refuses an incomplete backup up front, stops the stack, snapshots
   current volumes under `./backups/pre-restore-*`, restores into fresh
   volumes, restarts → `verify-production.sh`). See
   `docs/operations/BACKUP_RECOVERY.md`.
