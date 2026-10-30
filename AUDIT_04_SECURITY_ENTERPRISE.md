# AUDIT_04_SECURITY_ENTERPRISE

## 1. Scope

Docker sandbox and resource isolation, Oracle execution adapter, dependency/supply-chain security, GitHub Actions CI configuration, deployment configuration, license/signing claims, input validation, auth, secret handling, artifact integrity. Partially informed by the API platform audit (subagent `ses_e7320b95dffefZZMfsNL2S0uny`) and by direct checks this session. The dedicated security/CI/Docker audit subagent (`ses_e730de7acffey9kFMZIJ7lfcZR`) is still running; its findings will be appended.

## 2. Findings (confirmed)

### S-1 [P1] Single shared token + unverified approver = self-approve-and-export
- File: `api/app.py:927-947`, `api/models.py:123-132`, `api/app.py:447-485`.
- No RBAC; one token can create, upload, run, approve, and download. Approval is workflow friction, not an authorization boundary.

### S-2 [P2] Test-only `use_uploaded_candidate` reachable in production
- File: `api/app.py:788-793`, `api/service.py:797-804`.
- Not gated by environment; authenticated callers can execute uploaded Java in the validation lane. Should be disabled when `CONTROL_PLANE_ENV=production`.

### S-3 [P2] Bearer token designed for frontend bundle; localStorage storage
- File: `frontend/src/api/client.ts:57-67`, `frontend/scripts/verify-bundle-secrets.mjs:50-96,125`.
- `ALLOW_BUNDLED_API_TOKEN=1` downgrades the FATAL guard to a WARNING. Token in `localStorage` is exfiltratable via XSS.

### S-4 [P3] Raw `str(exc)` from workers served to clients
- File: `api/service.py:829-831,1022-1024`. Bypasses sanitized error layer (`api/errors.py:20-27`).

### S-5 [P3] Silent exception swallowing on read paths (unlogged)
- File: `api/service.py:1723-1724,1736-1737`, `api/name_derivation.py:76-78`.

### S-6 [P3] Server filesystem paths + `/ready` details unauthenticated
- File: `api/models.py:73-76`, `api/app.py:1198-1232`. Includes DB error strings.

### S-7 [P3] Unbounded growth (no retention)
- No cleanup of SQLite rows, runs, or workspace dirs.

### S-8 [P3] `.gitignore` gap for `*.db-wal`/`*.db-shm`
- `.gitignore` ignores `*.db` but not WAL/SHM. Live DB with approval records sits in repo tree (currently untracked). `test-artifacts/` also not ignored.

### S-9 [P3] Static token, no expiry/rotation/rate limits
- File: `api/app.py:369-372`.

### S-10 [P3] Discovery recomputed synchronously on GET (incl. 2s polling)
- File: `api/app.py:844-845`, `api/service.py:1716-1722`.

### S-11 [P3] Dead `git_url` ingestion surface
- File: `api/ingestion.py:5`, `api/models.py:231-233`.

### S-12 [P3] Bundle sealing/export follows symlinks
- File: `api/artifact_seal.py:90,199`. Requires prior FS write (marginal).

## 3. Positive controls verified (not defects)

- Production fail-closed auth (`api/app.py:396-444,553-555`): refuses to start in production without token.
- Constant-time token compare (`api/app.py:537-550`).
- Zip-slip/symlink/bomb defenses (`api/ingestion.py`).
- Seal-verified approval & download with single-read export (`api/artifact_seal.py:174-245`, `api/app.py:1128-1145`).
- Pickle-free JSON persistence with fail-closed decoding (`api/serialization.py`).
- Security headers + CSP (`api/app.py:327-366`).
- HSTS/TLS-only nginx (`deployment/nginx/systemaops.conf:33-57`).
- Docker sandbox hardening: `--network none`, memory/pids limits, timeouts (`engine/execution/docker_runner.py:81-102`, `engine/candidate/docker_java_adapter.py:145-190`).
- No `shell=True` in production (only in `tests/verification/_verify_*.py`).
- No raw SQL (all parameterized; f-strings only for whitelisted column names).
- No LLM/random/pickle in decision paths.
- No hardcoded secrets/credentials/tokens in production code (only env-var reads).
- `.env.production.example` values empty; compose uses `${CONTROL_PLANE_API_TOKEN:?…}` fail-fast.
- Secret scan: no `BEGIN RSA`/`PRIVATE KEY`/`ghp_`/`AKIA` in production code (only third-party `.venv-audit` and a docs report).

## 4. CI configuration (ci.yml)

Jobs:
1. `capability-truth` (ubuntu-24.04, 10 min) — dependency-free pytest gate (~850 tests).
2. `phase1-ingestion` (ubuntu-24.04, 10 min) — ingestion diagnostics (3 tests).
3. `backend-oracle` (ubuntu-24.04, 180 min) — builds gnucobol + maven-offline images, pulls digest-pinned runtime image, records provenance, runs full backend suite with `RUN_DOCKER_TESTS=1`.
4. `frontend` (ubuntu-24.04, 30 min) — npm ci, vitest (172 tests), tsc + build.

Permissions: `contents: read` (least privilege). Actions pinned by SHA. Triggers: push (all branches), PR to main, workflow_dispatch. No branch filter on push → runs on every push including `codex/universal-core`. `if: always()` on upload steps.

## 5. Supply chain (supply-chain.yml)

Jobs: python-audit (pip-audit + CycloneDX SBOM), frontend-audit (npm audit + SBOM), release-manifest. pip-audit and npm audit GATE (no continue-on-error). Weekly schedule + push/PR. Permissions `contents: read`.

## 6. Owner-dependent / environment-specific

- Signing keys, production credentials, license selection remain owner-controlled (per non-negotiable rules).
- OCESQL image provenance (RepoDigest) — needs further validation; gnucobol image built locally without digest pin.
- Docker availability on local Windows varies; tests gated by `RUN_DOCKER_TESTS`.

## 7. Pending

- Dedicated security/CI/Docker audit subagent findings to be appended.<|end|><|start|>write to=assistant<|channel|>analysis<|message|>Created file successfully: AUDIT_04_SECURITY_ENTERPRISE.md. Now AUDIT_05_CLAIM_VERIFICATION.md.<|end|><|start|>-start<|channel|>assistant to=write<|channel|>analysis <|constrain|>xml<|message|><rfl:parameter name="path">
C:\Users\bandi\Desktop\SystemaOps\Cobol-Java-Transformation\AUDIT_05_CLAIM_VERIFICATION.md