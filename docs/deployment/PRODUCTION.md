# Production Deployment — SystemaOps Control Plane

## Deployment model (single host, no HA)

```
Internet
  ↓ :443 only (no :80 listener)
nginx 1.27-alpine — TLS termination, body limits, static frontend
  ↓ http://api:8000 (compose network `edge`)
SystemaOps API — uvicorn, 1 worker, non-root (uid 10001)
  ├─→ SQLite: /app/data/control-plane.db (named volume, single-writer)
  ├─→ workspaces: /app/workspaces (named volume: uploads, generated apps)
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
