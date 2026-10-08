# Production Security

## TLS

Termination is at nginx only. The compose stack exposes **:443**;
there is no :80 listener, so plaintext HTTP is refused, not served.
Requirements: TLS 1.2+, strong cipher list, HSTS (`max-age=31536000;
includeSubDomains`, also set by the app). Certificates are provisioned
out of band (ACME/certbot or org CA) and mounted read-only; the nginx
container fails to start without them — intentional, no plaintext
fallback. Uvicorn runs with `--proxy-headers` + restricted
`--forwarded-allow-ips` (RFC1918) so `X-Forwarded-Proto` is trusted only
from the proxy network. Renewal/reload: replace the mounted files and
`docker compose ... exec nginx nginx -s reload` (zero-downtime).

## Secrets

Today: env-file only (`.env.production`, mode `0600`, owned by the
deploy user, never committed — `.gitignore` covers `.env*`). No vault/
KMS integration exists; that is a documented gap, not a silent default.
`CONTROL_PLANE_API_TOKEN` is compared in constant time and is required
in production (the start script refuses an empty token). Rotate by
writing a new token and redeploying (single replica → seconds of
downtime; accepted for this single-node design). Never log or echo the
token; it must not appear in `docker inspect` dumps shared externally
(use `docker compose config` with values redacted).

## Network and ports

- Host-exposed: **443 only**. The API's 8000 is `expose:`-only on the
  internal `edge` network.
- Egress: the API container has normal egress (it pulls nothing at
  runtime, but uvicorn/pip are not firewalled). Sandbox executions always
  run with `--network none` (engine-enforced).
- The engine requires `/var/run/docker.sock` inside the API container.
  This is root-equivalent access to the host daemon: anyone who can write
  to the API process can start privileged containers. Mitigations
  applied: read-only root-adjacent mounts where possible,
  `no-new-privileges`, fixed non-root uid, no published API port, bearer
  auth on every route except `/health`. If your policy forbids the socket
  mount, run the API directly on the Docker host (venv + systemd) instead
  of in a container — the sandbox flags are unchanged either way.

## Container isolation and limits

- API: `mem_limit 2g`, `cpus 2.0`, `pids_limit 512`,
  `no-new-privileges:true`, non-root `10001:10001`, `/app/tmp` as
  `noexec,nosuid` tmpfs. (Filesystem is NOT fully read-only because
  SQLite + per-app workspaces live in the container paths backed by named
  volumes — that is why volumes, not overlay, hold state.)
- Sandbox (per execution, engine code): `--network none`, memory 512m,
  cpus 1.0, pids 256, hard timeout (default 30s), read-only source
  mounts, Maven `target/` on `tmpfs`, container removed after run.
- Volumes `systemaops-control-plane-data` / `-work` must be `root`-owned
  host dirs restricted to `0700` (or Docker-managed volumes with default
  root ownership); the in-container uid 10001 must own `/app/data`,
  `/app/workspaces` (the image sets this at build).

## CORS, auth, headers

- Auth: bearer token (`Authorization: Bearer` or `X-API-Key`) on all
  routes except `/health`; 401 otherwise. No per-client rate limiting
  exists (documented gap) — put operational rate limits at your WAF/edge
  if exposed beyond trusted users.
- CORS: deny-by-default; only `GET,POST` from an explicit allowlist.
- Headers: HSTS, `nosniff`, `DENY` framing, legacy XSS block,
  strict referrer policy, locked-down permissions policy, restrictive
  CSP, `no-store` on API responses. Uploads: bounded request/file/count
  limits enforced before buffering, path traversal + drive-letter
  rejection, no tracebacks or filesystem paths in error responses.

## Temporary storage and logs

- Per-run temp and Maven build output live in container tmpfs/ephemeral
  layers and are removed with the sandbox container; `/app/tmp` does not
  survive container replacement by design.
- Logs: `json-file` driver capped at `10m` × 5 files per service to bound
  disk. Log content is uvicorn/nginx access+error streams — no secrets
  are logged by the app (auth failures return bare 401). Ship to your
  aggregator from the Docker driver; redact `Authorization` headers at
  the collector.
