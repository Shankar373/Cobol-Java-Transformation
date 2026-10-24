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
| Bearer auth, security headers, CORS deny-by-default, upload budgets | Ready (app-enforced) | `api/app.py` |
| Liveness probe (`/health`, no auth) | Ready | compose `healthcheck`, nginx passthrough |
| Readiness probe (DB writable? queue depth?) | **Gap — documented, not implemented** | `docs/operations/RUNBOOK.md` |
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
| `GET /health`, `/applications`, `/runs`, ... | proxied to the API |

Static locations use `^~` longest-prefix matches with trailing-slash
`alias` pairs, so API routes and static files can never shadow each
other. Verified production-style with the pinned nginx image against a
stub upstream (see Phase E-A report).

## Deploy / verify / roll back

```bash
cp .env.production.example .env.production   # fill secrets; never commit
./scripts/deploy/build-production.sh production
ENV_FILE=.env.production ./scripts/deploy/start-production.sh
./scripts/deploy/rollback.sh <PREVIOUS_TAG>   # data volumes untouched
```

`start-production.sh` refuses to start when `CONTROL_PLANE_API_TOKEN`
or the TLS cert/key is missing. `verify-production.sh` checks compose
rendering, container health, TLS `/health`, sandbox image presence,
`--network none` execution, and that `/applications` returns 401
unauthenticated.

## Files

- `Dockerfile.production` — API image
- `docker-compose.production.yml` — full stack (volumes, caps, healthchecks)
- `deployment/nginx/systemaops.conf` — TLS proxy
- `.env.production.example` — every supported variable
- `scripts/deploy/*` — build / start / verify / rollback
- `scripts/backup/*` — backup / restore
