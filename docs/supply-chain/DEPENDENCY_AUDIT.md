# Dependency / Supply-Chain Audit — Workstream 5

Date: 2026-10-08. Branch: `codex/universal-core`. Baseline: `fedb7dd`.
Scope: dependencies and supply chain ONLY. No application features.
Out of scope (untouched): `engine/transformation/*`, `engine/modernization/*`,
`engine/evidence/*`, `engine/verdict/*`, `api/service.py`, `api/models.py`,
frontend application source. No LLMs added.

Policy: NO bulk upgrades. Every upgrade needs
CURRENT / TARGET / REASON / BENEFIT / BREAKING-CHANGE RISK / TEST RESULT.
Minimal safe upgrades preferred. Previous TypeScript compiler regressions
must not be repeated.

## 1. Dependency inventory (FACT)

Python (`requirements.txt`, no lockfile before this work):
`fastapi>=0.115,<1`, `python-multipart>=0.0.9,<1`,
`uvicorn[standard]>=0.30,<1`, `httpx>=0.27,<1`,
`pytest>=8,<9`, `pytest-asyncio>=0.23,<1`.
Resolved locally (Python 3.14): fastapi 0.141.1, starlette 1.2.1,
pydantic 2.13.4, uvicorn 0.52.3, httpx 0.28.1, multipart 0.0.32,
pytest 8.4.2, pytest-asyncio 0.26.0. Latest upstream is within 1–2
patch versions (fastapi 0.142.4, uvicorn 0.54.0, starlette 1.7.0,
pydantic 2.13.5). No `pyproject.toml`. CI installs via
`pip install -r requirements.txt` on Python 3.11.

Frontend (`frontend/package.json`, `package-lock.json` present, `npm ci`):
react/react-dom 18.3.1 (`^18.3.1`), react-router-dom 6.28 (`^6.28.0`,
resolved 6.30.6), typescript `^5.7.2` (resolved 5.9.3), vite `^6.0.3`
(resolved 6.4.3), vitest `^2.1.8` (resolved 2.1.9),
@vitejs/plugin-react 4.7.0, jsdom 25.0.1, testing-library 16.x.
Node: CI uses 20; local env has 24.15.0.

Java/Maven (generator-emitted, engine scope — NOT modified):
`spring-boot-starter-parent 3.2.5`, `java.version 21`,
`spring-boot-starter` (+ `spring-context`, `spring-boot-starter-batch`
in JCL paths). Build image `maven:3.9-eclipse-temurin-21`.
Runtime `eclipse-temurin:21-jdk` with code-enforced digest
`eclipse-temurin@sha256:4d06…7026`
(`engine/candidate/docker_spring_boot_adapter.py:72`).

CI (`.github/workflows/ci.yml`): `actions/checkout@v4`,
`actions/setup-python@v5`, `actions/setup-node@v4`,
`actions/upload-artifact@v4` — all floating tags before this work.

Containers: `python:3.11-slim-bookworm`, `maven:3.9-eclipse-temurin-21`,
`ubuntu:22.04`, `nginx:1.27-alpine` — all untagged digests before this work.

## 2. Security findings

Python: `pip-audit` installs cleanly (2.10.1) but the OSV lookup timed
out in this sandbox (120 s+, twice), so no local verdict is claimed:
NOT VERIFIED locally. The new `supply-chain.yml` workflow runs
`pip-audit -r requirements.lock` in CI on every push/PR plus weekly.
Direct deps are 0–2 patches behind latest; no advisory is asserted
without scan evidence.

Frontend (`npm audit`, 2026-10-08, FACT): 9 vulnerabilities —
5 moderate, 2 high, 2 critical:
- `tinypool <=2.1.1` — CRITICAL prototype-pollution → RCE (2 advisories).
- `source-map-js 1.0.0–1.2.1` — HIGH event-loop DoS.
- `esbuild <=0.24.2` via vite/vite-node — MODERATE dev-server request forgery.
- `@vitest/mocker <=4.1.10` via vitest — MODERATE path traversal / file read.
- `react-router 6.0.0–7.17.0` via react-router-dom — MODERATE open-redirect
  + SSR `deserializeErrors` constructor injection.
Fixing the critical/high set requires `vitest@5.0.3` (major, breaking)
and `react-router-dom@7.18.4` (major, breaking). Per upgrade policy:
STOP and REPORT — not applied (would need app-source/test changes and a
full TS/vite compat re-validation).

Java: Spring Boot 3.2.5 (Apr 2024; 3.2 line is past OSS support) is a
known-stale major-minor. Any bump (e.g. 3.2.x → 3.4.x) changes the POM
emitted by `engine/transformation/spring_boot_generator.py` and
`engine/modernization/application_assembler.py` and the Maven precache —
all engine scope. STOP and REPORT — not applied.
Runtime-digest drift (INFERENCE, needs registry confirmation):
code pins `sha256:4d06…` while `eclipse-temurin:21-jdk` currently
resolves to index `sha256:3e3c…`. The adapter correctly fails closed on
mismatch; rotating the digest is an engine-scope decision, not taken here.

## 3. Proposed upgrades (none applied — reasons)

| # | CURRENT | TARGET | REASON / BENEFIT | BREAKING-CHANGE RISK | TEST | DECISION |
|---|---------|--------|------------------|----------------------|------|----------|
| P1 | fastapi ~0.141, starlette 1.2.1 | latest patches | stay current | low but unrequested; wide ranges already float | n/a | DEFER — ranges float safely; lock records release set |
| F1 | vitest 2.1.9 / vite 5.4.21 nested | vitest 5.0.3 | fixes CRITICAL tinypool + esbuild/vite advisories | HIGH — major bump, plugin/config compat, TS history | n/a | STOP/REPORT — needs dedicated workstream + full matrix |
| F2 | react-router-dom 6.30.6 | 7.18.4 | fixes MODERATE router advisories | HIGH — v6→v7 API migration in app source | n/a | STOP/REPORT — out of scope (app source frozen) |
| F3 | typescript 5.9.3 (lock) / ^5.7.2 | 7.x | none — latest is a new major | VERY HIGH — known compiler-compat regression class | n/a | DO NOT UPGRADE |
| F4 | react 18.3.1 | 19.x | none requested | HIGH — types + concurrent behavior | n/a | DO NOT UPGRADE |
| J1 | spring-boot-starter-parent 3.2.5 | 3.4.x / supported | supported line + CVE coverage | HIGH — generator + precache + offline image + proof fixtures | n/a | STOP/REPORT — engine scope |
| J2 | runtime digest `4d06…` | current registry digest | track upstream rebuilds | MEDIUM — fail-closed provenance + evidence fixtures | n/a | STOP/REPORT — engine scope |

Upgrades APPLIED: NONE to resolved dependency content (deliberate).
Hardening applied instead: immutable pins (lockfile, digests, SHAs),
SBOM + scanning automation, release manifest.

## 4. SBOM

- Python: `cyclonedx-bom` over `requirements.lock` →
  `sbom-python.cyclonedx.json` (CI artifact `supply-chain-python`).
- Frontend: `npm sbom --sbom-format cyclonedx` →
  `sbom-frontend.cyclonedx.json` + `npm-ls.json` (artifact
  `supply-chain-frontend`).
- No new third-party GitHub Actions were introduced (first-party
  checkout/setup-*/upload-artifact only) to avoid widening the
  supply chain for the sake of SBOM tooling.

## 5. Vulnerability scanning

- New workflow `.github/workflows/supply-chain.yml`: `pip-audit`
  (requirements.lock), `npm audit --json`, SBOMs, and a manifest job;
  runs on push/PR/dispatch plus weekly cron. Scan steps are
  `continue-on-error` with 90-day artifacts so findings are visible
  without red-blocking parallel workstreams; gating is a follow-up.
- Local evidence 2026-10-08: `npm audit` completed (9 vulns above);
  `pip-audit` timed out on OSV network (NOT VERIFIED locally);
  `npm ls`/`npm outdated` and `pip index versions` cross-checks done.

## 6. Reproducibility

- NEW `requirements.lock` (`==` pins for 6 direct + 20 transitive deps,
  verified versions listed in §1). `requirements.txt` ranges unchanged
  so existing installs keep working; the lock is the release pin.
- NEW `.nvmrc` (`20`, matches CI). Python is pinned to 3.11 in CI
  (`setup-python`), `Dockerfile.production`, and the release manifest
  (a `.python-version` file was deliberately NOT added: it is in this
  repo's `.gitignore`).
- `frontend/package-lock.json` already exists; CI uses `npm ci`.
- NEW `scripts/supply-chain/build_release_manifest.py` (stdlib only):
  emits `test-artifacts/supply-chain/dependency-manifest.json`
  answering "what exact dependencies are in this release".
- Dockerfiles + compose nginx image now digest-pinned (§7).

## 7. Docker

Pinned 2026-10-08 via `docker buildx imagetools inspect` (same tag
content, now immutable):
- `Dockerfile.production`: `python:3.11-slim-bookworm@sha256:0a31…f5f89`
- `Dockerfile.maven-offline`: `maven:3.9-eclipse-temurin-21@sha256:99e6…8320`
- `Dockerfile.gnucobol`: `ubuntu:22.04@sha256:5ec0…86401`
- `docker-compose.production.yml`: `nginx:1.27-alpine@sha256:6564…2a10`
Verified: `docker compose config` exits 0 with the example env file.
`Dockerfile.*` builds not re-run here (heavy); CI backend-oracle job
builds both sandbox images with `--pull`.

## 8. CI

- `ci.yml`: `checkout@v4`, `setup-python@v5`, `setup-node@v4`,
  `upload-artifact@v4` → SHA pins (`11d5960a…`, `a26af69b…`,
  `49933ea5…`, `ea165f8d…`) with `# vX` comments. Same versions,
  stronger supply chain; no behavior change.
- NEW `supply-chain.yml` (all actions SHA-pinned, first-party only).

## 9. Files changed (this workstream only)

- `requirements.lock` (new) — release pin.
- `.nvmrc` (new) — Node runtime pin.
- `Dockerfile.production`, `Dockerfile.maven-offline`,
  `Dockerfile.gnucobol`, `docker-compose.production.yml` — digest pins + comments.
- `.github/workflows/ci.yml` — action SHA pins (same versions).
- `.github/workflows/supply-chain.yml` (new) — audit + SBOM + manifest.
- `scripts/supply-chain/build_release_manifest.py` (new).
- `docs/supply-chain/DEPENDENCY_AUDIT.md` (this file).

## 10. Files NOT changed

`engine/transformation/*`, `engine/modernization/*`,
`engine/evidence/*`, `engine/verdict/*`, `api/service.py`,
`api/models.py`, frontend `src/*`, `requirements.txt`,
`frontend/package.json`, `frontend/package-lock.json`,
Spring Boot versions, Java runtime digest, DOCKER_CLI_VERSION.

## 11. Conflicts with parallel work

Working tree already contains uncommitted parallel-work edits
(`api/app.py`, `api/models.py`, `api/service.py`, frontend `src/*`,
tests). This workstream does not touch those files and stages ONLY
the §9 list, so it stays independently mergeable. No merges, no
rebases performed.

## 12. Remaining risks / recommendations

1. npm CRITICAL/HIGH (tinypool, source-map-js, vite/esbuild chain) —
   needs a dedicated frontend-upgrade workstream (vitest 5, vite 8,
   router 7 triage + full test/build matrix). Not safe here.
2. Spring Boot 3.2.5 support status — needs an engine-scope upgrade
   proposal with proof-fixture impact analysis.
3. Runtime-digest rotation (`4d06…` → current) — engine-scope decision
   with provenance-evidence updates.
4. `pip-audit` local NOT VERIFIED (sandbox network) — CI run required.
5. Hash-pinned (`--require-hashes`) installs and image-signature
   (cosign) verification are future steps; current pins are digest/`==`
   level.
6. Consider failing CI on new critical/high once baselines are clean;
   today scans are advisory-only by design.
