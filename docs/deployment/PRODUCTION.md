# Production Deployment — SystemaOps Control Plane

## Deployment model (single host, no HA)

```
Internet
  ↓ :443 only (no :80 listener)
nginx 1.27-alpine — TLS termination, body limits, static frontend (/app/)
  ↓ http://api:8000 (compose network `edge`)
SystemaOps API — uvicorn, 1 worker, non-root (uid 10001)
  ├─→ SQLite: /app/data/control-plane.db (named volume, single-writer)
  ├─→ workspaces: /app/workspaces (named volume: uploads, generated apps)
  ├─→ sandbox staging: /app/sandbox-staging (HOST BIND mount — see below)
  └─→ host docker via /var/run/docker.sock → sandbox containers
        (--network none, --memory/--cpus/--pids-limit, read-only mounts;
         enforced by engine code, NOT by this deployment — do not weaken it)
```

**No high availability is claimed or implemented.** SQLite is
single-node/single-writer, background jobs are in-process daemon threads,
and the compose file runs exactly one API replica. A restart fails
interrupted runs at startup (`Store.mark_interrupted_runs`) instead of
re-queueing them — that is the documented durability trade-off
(see `docs/ARCHITECTURE.md`, "Remaining production gaps").

## What is production-ready vs development-only

| Area | Status | Evidence / location |
|---|---|---|
| API image (non-root, pinned base, 1 worker) | Ready | `Dockerfile.production` |
| Sandbox isolation (`--network none`, caps, ro mounts, tmpfs) | Ready (engine-enforced) | `engine/execution/docker_runner.py`, `engine/candidate/docker_*_adapter.py`, `engine/oracle/docker_adapter.py` |
| Reverse proxy + TLS termination | Ready (config) — certs provisioned out of band | `deployment/nginx/systemaops.conf` |
| Bearer auth (32-char production token floor), security headers, CORS deny-by-default, upload budgets | Ready (app-enforced) | `api/app.py` |
| Liveness probe (`/health`, no auth) | Ready | nginx `healthcheck` → TLS `/health`, nginx `location = /health` |
| Readiness probe (`/ready`: DB read-write? workspace? staging?) | Ready — 200 vs 503, gating checks | `api/app.py`, compose `healthcheck` → `/ready`, `Dockerfile.production` `HEALTHCHECK`, nginx `location = /ready`, `verify-production.sh` |
| Structured logging (level/format, `X-Request-Id`, lifecycle events) | Ready | `api/logging_config.py`, `api/app.py` |
| Secrets manager integration | **Gap — env-file only** | `docs/security/PRODUCTION_SECURITY.md` |
| Durable job queue with resume | **Gap (upstream)** | `docs/ARCHITECTURE.md` |
| Automated backup scheduling | **Gap — scripts provided, scheduling manual** | `docs/operations/BACKUP_RECOVERY.md` |
| Multi-node / horizontal scale | **Not supported (SQLite)** | this file |

## Containers

1. **Production API** (`systemaops-api:<tag>`) — control plane only.
   No JDK/Maven/GnuCOBOL inside; sandbox images live on the host daemon.
2. **Modernization sandbox** — not a standing container: one `docker run`
   per execution, created and removed by the engine with hard timeout,
   `--network none`, memory/cpu/pids caps, read-only source mounts.
3. **Build/runtime images** — `gnucobol-ocesql:latest`,
   `maven-offline-springboot:latest`, pinned `eclipse-temurin:21-jdk`
   (digest pinned in engine code; provenance recorded by
   `scripts/record_docker_image_provenance.py`).
4. **Persistent evidence/data** — named volumes
   `systemaops-control-plane-data` (SQLite) and
   `systemaops-control-plane-work` (workspaces). `/app/tmp` is an
   ephemeral `tmpfs` (1g, `noexec,nosuid`).

## Probes: `/health` (liveness) vs `/ready` (readiness)

Both probes are exempt from bearer auth: the auth middleware passes
`/health` and `/ready` through before any token check, because
orchestrator probes cannot carry a token. Together with CORS `OPTIONS`
preflights, they are the only requests answered without a token when
`CONTROL_PLANE_API_TOKEN` is set.

| | `GET /health` | `GET /ready` |
|---|---|---|
| Answers | the process is up | this control plane can persist writes |
| Status | always `200 {"status":"ok"}` while the process runs | `200 {"status":"ready"}` when every gating check passes, `503 {"status":"not_ready"}` otherwise |
| Payload | no dependency state | `checks` object — dependency state only, never secrets |

`/ready` checks (`api/app.py`, `ready()`):

* **gating** (any failure ⇒ 503): `database` — a separate SQLite
  connection opens the file read-write (`Store.probe_database`; a
  read-only or missing file is not ready); `workspace` — the durable
  root (`CONTROL_PLANE_WORKSPACE_DIR`) is creatable and writable (unset
  = the development temp directory, reported healthy); `staging` — the
  sandbox staging root (`SANDBOX_STAGING_DIR`) is usable when configured;
* **reported but non-gating**: `docker` — the host daemon is probed and
  reported only (a host daemon outage cannot be fixed by restarting this
  container, so runs fail closed at the execution stage rather than the
  container flapping); `jobs` — active/limit worker slots, informational.

Wiring:

* `docker-compose.production.yml` — api `healthcheck`:
  `curl -fsS http://127.0.0.1:8000/ready`, `interval: 30s`,
  `timeout: 5s`, `start_period: 20s`, `retries: 3`; `nginx` waits on
  `depends_on: api: condition: service_healthy`.
* `Dockerfile.production` — `HEALTHCHECK`: `curl -fsS http://127.0.0.1:8000/ready || exit 1`
  with `--interval=30s --timeout=5s --start-period=20s --retries=3`.
* `deployment/nginx/systemaops.conf` — `location = /ready` (and
  `location = /health`): unauthenticated `proxy_pass` to the API,
  `access_log off`.
* `scripts/deploy/verify-production.sh` — post-deploy checks
  `TLS /health via nginx` and `TLS /ready via nginx (readiness)`.

## Structured logging

| Variable | Default (app) | Behaviour |
|---|---|---|
| `CONTROL_PLANE_LOG_LEVEL` | `INFO` | standard level names (`DEBUG`, `INFO`, ...); an unrecognised value falls back to `INFO` and is reported once on stderr |
| `CONTROL_PLANE_LOG_FORMAT` | `json` when `CONTROL_PLANE_ENV=production`, else `text` | `json` = one object per line (`ts`, `level`, `logger`, `message`, `request_id` + structured extras); `text` = one human-readable line |

Every request gets an `X-Request-Id`: echoed when it matches
`[A-Za-z0-9._-]{1,64}` (never reflected raw, so it cannot inject response
headers), otherwise minted; it is returned as a response header and
injected into every record emitted while handling that request. Exactly
one access line per request (`event=http.request`) carries `method`,
`path`, `status` and `duration_ms` only — headers and tokens are never
logged. Lifecycle records carry structured extras (`event`, `run_id`,
...), e.g. `startup.reconciled`, `run.started`, `run.revalidating`,
`run.failed`, `run.terminal`.

## Sandbox staging topology (host-visible workspace)

The API reaches the Docker daemon through the mounted daemon socket, so
`docker run -v <path>:...` bind sources are resolved by the **host**
daemon on the **host** filesystem. Staging sandbox inputs under the
container-private `/app/tmp` tmpfs or under a named volume is invisible
to the host daemon: oracle/candidate execution then fails closed and the
stack can never produce a verdict.

Production therefore binds a host directory into the API container at the
same deployment:

- container view: `/app/sandbox-staging` (`SANDBOX_STAGING_DIR`)
- host view: `HOST_SANDBOX_STAGING_DIR` (absolute host path, default
  `/opt/systemaops/sandbox-staging`)

The engine (`engine/execution/sandbox_paths.py`) stages every Docker
bind-mount source under the container view and translates it to the host
view before building `docker run -v` arguments; file I/O keeps using the
container path. Translation is strictly prefix-scoped: paths outside the
staging root pass through unchanged, so dev/host runs without the bind
behave exactly as before.

Operator requirements (enforced by `start-production.sh` /
`verify-production.sh`, fail closed):

1. `HOST_SANDBOX_STAGING_DIR` MUST be an absolute host path.
2. The host directory MUST exist and be writable by uid/gid 10001 (the
   non-root API user): `mkdir -p <dir> && chown 10001:10001 <dir>`.
3. Sandbox staging MUST NOT live on the `/app/tmp` tmpfs (ephemeral,
   container-local) or on a named volume (host-invisible path).
4. Sandbox containers still run with `--network none`, memory/cpu/pids
   caps, read-only source mounts, `no-new-privileges` and pinned image
   digests — the staging bind grants no additional Docker privileges.

## Frontend routing contract (nginx + Vite)

The SPA is served under `/app/` (Vite `base: '/app/'`, so built assets
are `/app/assets/*` and the logo resolves via `import.meta.env.BASE_URL`):

| Request | Result |
|---|---|
| `GET /` | 302 to `/app/` |
| `GET /app/` | `index.html` |
| `GET /app/assets/*` | immutable long-cache static file |
| `GET /app/<anything-else>` | SPA fallback to `/app/index.html` |
| `GET /assets/*` (legacy) | 302 to the `/app/` counterpart |
| `GET /health`, `/ready`, `/applications`, `/runs`, ... | proxied to the API |

Static locations use `^~` longest-prefix matches with trailing-slash
`alias` pairs, so API routes and static files can never shadow each
other. The routing contract is pinned by config-level assertions in
`tests/deployment/test_production_topology.py` (Phase E-A: nginx config,
compose topology, Vite `base`).

## Deploy / verify / roll back

```bash
cp .env.production.example .env.production   # fill secrets; never commit
./scripts/deploy/build-production.sh production
ENV_FILE=.env.production ./scripts/deploy/start-production.sh
./scripts/deploy/rollback.sh <PREVIOUS_TAG>   # data volumes untouched
```

`start-production.sh` refuses to start when `CONTROL_PLANE_API_TOKEN`
or the TLS cert/key is missing, and the control plane itself fails
closed in production: with `CONTROL_PLANE_ENV=production` (set by the
start script, compose, and `.env.production.example`) the process
refuses to start without `CONTROL_PLANE_API_TOKEN` **or with a token
shorter than 32 characters** — `verify_production_auth_configuration()`
runs at import time and aborts the process; generate one with
`python -c "import secrets; print(secrets.token_urlsafe(48))"` — and
answers 401 on every route except `/health` and `/ready` (and CORS
`OPTIONS` preflights, which carry no payload) even if
startup checks were bypassed. The start script also runs a preflight
**before** `docker compose ... up` and exits `FATAL` (nothing started)
when `docker info` cannot reach the daemon or when
`docker compose -f docker-compose.production.yml --env-file "$ENV_FILE" config --quiet`
does not render.

`verify-production.sh` checks compose
rendering, container health (the api container id is derived with
`docker compose ... ps -q --all api`, never hardcoded), TLS `/health`
and TLS `/ready` via nginx, sandbox image presence,
`--network none` execution, sandbox staging topology, and that
`/applications` returns 401 unauthenticated.

## Files

- `Dockerfile.production` — API image (`HEALTHCHECK` → `/ready`)
- `docker-compose.production.yml` — full stack (volumes, caps, healthchecks)
- `deployment/nginx/systemaops.conf` — TLS proxy (`location = /health`, `location = /ready`)
- `.env.production.example` — starter values for the common variables; the
  token line ships **empty** (fill it, never commit) and it does **not**
  list every variable the code reads — `docs/deployment/ENVIRONMENT.md` does
- `scripts/deploy/*` — build / start (preflight) / verify (derived container
  id, TLS `/health` + `/ready`) / rollback
- `scripts/backup/*` — backup / restore; `backup.sh` step 4 re-verifies each
  backup with `scripts/backup/verify_backup.py` (see
  `docs/operations/BACKUP_RECOVERY.md`)
- `frontend/scripts/verify-bundle-secrets.mjs` — `npm run build` fails if
  `VITE_CONTROL_PLANE_API_TOKEN` is set or a built asset contains an
  inlined token (see `docs/deployment/ENVIRONMENT.md`)
