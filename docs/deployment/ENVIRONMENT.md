# Production Environment Reference

All variables live in `.env.production` (see `.env.production.example`).
`CONTROL_PLANE_DB` and `TMPDIR` are fixed by the compose file and must
not be overridden.

| Variable | Required | Default (app) | Production guidance |
|---|---|---|---|
| `CONTROL_PLANE_API_TOKEN` | **Yes** (enforced by start script) | unset = auth OFF (dev default) | 48+ random bytes; rotate by redeploy |
| `TLS_CERT_PATH` / `TLS_KEY_PATH` | **Yes** | — | host paths; certbot/ACME or org CA; never commit |
| `HTTPS_PORT` | No | 443 | host bind for :443 |
| `FRONTEND_DIST_PATH` | No | `./frontend/dist` | `npm run build` output; absent = API-only mode |
| `CONTROL_PLANE_MAX_REQUEST_BYTES` | No | 52428800 (50m) | must stay ≤ nginx `client_max_body_size` |
| `CONTROL_PLANE_MAX_FILE_BYTES` | No | 10485760 | per-file cap |
| `CONTROL_PLANE_MAX_UPLOAD_FILES` | No | 1000 | per-request file count cap |
| `CONTROL_PLANE_MAX_CONCURRENT_JOBS` | No | (code default) | 429 when full; slots released on crash; raising adds throughput, not HA |
| `CONTROL_PLANE_ALLOWED_ORIGINS` | No | empty = same-origin only | comma-separated allowlist only if cross-origin UI is required |
| `IMAGE_TAG` | No | `production` | release pin for rollback |
| `ENV_FILE` | No | `.env.production` | alternate env file path |

CORS methods are restricted to `GET,POST` and only when the allowlist is
non-empty (`api/app.py`). Security headers (HSTS, `nosniff`, `DENY`
framing, restrictive CSP, `no-store` on API responses) are set by the app
and re-asserted at the proxy.
