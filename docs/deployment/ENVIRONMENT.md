# Production Environment Reference

Most variables live in `.env.production` (copy `.env.production.example`,
whose token line ships empty). The table below lists the control-plane
variables read by `api/`, `engine/`, `scripts/`, `docker-compose.production.yml`
and `Dockerfile.production`. `CONTROL_PLANE_DB` and `TMPDIR` are fixed by
the compose file and must not be overridden.

Numeric limits are parsed by `api/limits.py` `env_int_limit`: unset,
blank, non-numeric or non-positive values fall back to the code default
(one warning for a non-numeric value). `CONTROL_PLANE_MAX_CONCURRENT_JOBS`
and `CONTROL_PLANE_MAX_UPLOAD_FILES` are read in `api/service.py` instead
(unset/invalid → default, parsed values clamped to ≥ 1).

| Variable | Required | Default (app) | Production guidance |
|---|---|---|---|
| `CONTROL_PLANE_API_TOKEN` | **Yes** (enforced by the app in production, by `start-production.sh`, and by compose) | unset = auth OFF (dev default) | production requires **≥ 32 characters** (fail-closed at startup, `verify_production_auth_configuration`); `python -c "import secrets; print(secrets.token_urlsafe(48))"` yields 64; rotate by redeploy |
| `CONTROL_PLANE_ENV` | **Yes** in production (`production`) | unset = development | Fail-closed production gate: `production` refuses to start without `CONTROL_PLANE_API_TOKEN` and answers 401 on every non-`/health`, non-`/ready` route even if startup was bypassed; an unrecognised value aborts startup; `development`/`dev`/`test` keep dev parity |
| `TLS_CERT_PATH` / `TLS_KEY_PATH` | **Yes** | — | host paths; certbot/ACME or org CA; never commit |
| `HTTPS_PORT` | No | 443 | host bind for :443 |
| `FRONTEND_DIST_PATH` | No | `./frontend/dist` (compose default) | `npm run build` output mounted into nginx; no built dist = API-only mode |
| `CONTROL_PLANE_MAX_REQUEST_BYTES` | No | 52428800 (50m) | must stay ≤ nginx `client_max_body_size` |
| `CONTROL_PLANE_MAX_FILE_BYTES` | No | 10485760 | per-file cap |
| `CONTROL_PLANE_MAX_UPLOAD_FILES` | No | 1000 | per-request file count cap |
| `CONTROL_PLANE_MAX_ZIP_ARCHIVE_BYTES` | No | 52428800 (50m) | ZIP ingestion budget (`api/ingestion.py`); above ⇒ `IngestionError` (zip-bomb defence) |
| `CONTROL_PLANE_MAX_ZIP_ENTRIES` | No | 1000 | ZIP entry-count cap |
| `CONTROL_PLANE_MAX_TOTAL_EXTRACTED_BYTES` | No | 209715200 (200m) | total extracted bytes cap |
| `CONTROL_PLANE_MAX_ZIP_COMPRESSION_RATIO` | No | 100 | per-entry uncompressed:compressed ratio cap |
| `CONTROL_PLANE_MAX_DOWNLOAD_BYTES` | No | 52428800 (50m) | `GET /runs/{id}/download` archive cap (built in memory) |
| `CONTROL_PLANE_MAX_DOWNLOAD_FILES` | No | 5000 | download entry-count cap |
| `CONTROL_PLANE_MAX_CONCURRENT_JOBS` | No | 4 | 429 when full; slots released on crash; raising adds throughput, not HA |
| `CONTROL_PLANE_ALLOWED_ORIGINS` | No | empty = same-origin only | comma-separated allowlist only if cross-origin UI is required |
| `CONTROL_PLANE_DB` | No (compose pins it) | `<repo>/data/control-plane.db`; `:memory:` = non-persistent (tests) | compose pins `/app/data/control-plane.db` (volume `control-plane-data`); do not override in production |
| `CONTROL_PLANE_WORKSPACE_DIR` | **Yes** in production (compose and `Dockerfile.production` pin it) | unset = `tempfile.mkdtemp()` in the platform temp directory (historical dev/test behaviour) | `/app/workspaces` (volume `control-plane-work`): uploads, generated apps and `scripts/backup/backup.sh` depend on it; `/ready` checks that it is creatable and writable |
| `CONTROL_PLANE_LOG_LEVEL` | No | `INFO` | standard level names (`DEBUG`, `INFO`, …); an unrecognised value falls back to `INFO` and is reported once on stderr |
| `CONTROL_PLANE_LOG_FORMAT` | No | unset ⇒ `json` when `CONTROL_PLANE_ENV=production`, else `text` | `json` = one object per line (`ts`, `level`, `logger`, `message`, `request_id` + extras); `text` = one human-readable line |
| `IMAGE_TAG` | No | `production` | release pin for rollback |
| `ENV_FILE` | No | `.env.production` | alternate env file path |
| `TMPDIR` | fixed by compose (`/app/tmp`) | platform temp directory | scratch only (1g `noexec,nosuid` tmpfs); durable artifacts belong in `CONTROL_PLANE_WORKSPACE_DIR` |
| `SANDBOX_STAGING_DIR` | **Yes** in production (compose sets it) | unset = not configured → per-execution staging in the platform temp directory | `/app/sandbox-staging` (container view of the host bind); `/ready` checks it |
| `SANDBOX_HOST_STAGING_DIR` | **Yes** in production (compose sets it from `HOST_SANDBOX_STAGING_DIR`) | unset ⇒ identity path mapping (container path passed through unchanged) | host view the engine maps bind sources to before `docker run -v` |
| `HOST_SANDBOX_STAGING_DIR` | **Yes** in production | compose default `/opt/systemaops/sandbox-staging` | absolute host path writable by uid/gid 10001; `start-production.sh` exits FATAL on a relative path |
| `DOCKER_GID` | No | compose default `0` | group owning `/var/run/docker.sock` on the host, added via `group_add` so the non-root API can reach the daemon |
| `DOCKER_CLI_VERSION` / `DOCKER_CLI_SHA256` | No (build-time `Dockerfile.production` `ARG`s) | `27.3.1` / `9b4f6fe406e50f9085ee474c451e2bb5adb119a03591f467922d3b4e2ddf31d3` | static docker CLI downloaded during the image build; `build-production.sh` passes no `--build-arg`, so the pinned defaults apply and the SHA-256 must match or the build fails |
| `SYSTEMAOPS_ORACLE_IMAGE` | No | `gnucobol-ocesql:latest` (`engine/pipeline.py`) | oracle-lane image resolved on the host daemon |
| `SYSTEMAOPS_ORACLE_DIGEST` | No | empty = auto-pin at execution time | declared immutable pin; a mismatch fails closed |

Test-only: `RUN_DOCKER_TESTS` gates the Docker-dependent tests; `FRONTEND_DIST_DIR`
retargets the bundle scan described below.

## Frontend bearer-token integration

The SPA attaches `Authorization: Bearer <token>` to every API call
(`frontend/src/api/client.ts`) so it works against a backend with
`CONTROL_PLANE_API_TOKEN` set. The token is resolved in priority order:

1. **Runtime override** — `localStorage.systemaops.apiToken` (set via the
   browser devtools console or `setApiToken()`); no rebuild needed, and
   the token never appears in the shipped bundle. Recommended when the
   frontend dist is built by a pipeline that must not handle the token.
2. **Build-time env** — `VITE_CONTROL_PLANE_API_TOKEN` passed to
   `npm run build` (Vite inlines `VITE_*` vars into `dist/assets/*.js`,
   which anyone can download). **The build refuses to ship this by
   default:** `npm run build` ends with
   `node scripts/verify-bundle-secrets.mjs`, which fails the build when
   the variable is set *or* when any built asset already contains an
   inlined token value (stale/poisoned `dist/`), and prints
   `bundle-secret-guard: OK (N asset(s) checked in dist)` when clean.
   A closed internal deployment can acknowledge the risk with
   `ALLOW_BUNDLED_API_TOKEN=1 npm run build`, which downgrades both
   failures to a loud warning — the token is then readable by anyone who
   can fetch the bundle, and rotating it does not remove the old value
   from already-cached assets. Prefer (1).
3. **Unset** — auth is off (dev default) and the client sends no
   Authorization header, byte-identical to the pre-auth client.

There is no login UI and no per-user identity: the token is the same
deployment-level control documented for the backend (no RBAC — carried
limitation D-5).

CORS methods are restricted to `GET,POST` and only when the allowlist is
non-empty (`api/app.py`). Security headers (HSTS, `nosniff`, `DENY`
framing, restrictive CSP, `no-store` on API responses) are set by the app
and re-asserted at the proxy.
