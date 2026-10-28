# SystemaOps COBOL-to-Java Modernization — Complete Independent Audit Report

**Date of audit:** 2026-10-28
**Auditor:** AI agent (read-only, evidence-based)
**Repository:** `C:\Users\bandi\Desktop\SystemaOps\Cobol-Java-Transformation`
**Git HEAD:** `0edd8ac8d1ca0d14fb1ea9e30e34ddb479621d76` on branch `codex/universal-core`
**Commit message:** `merge: integrate origin/codex/universal-core (reconciled audit + fail-closed batch BL-139..BL-145)`
**Git status at start:** 59 untracked entries (pre-existing; preserved, not modified)

---

## 1. Executive Summary

The repository is a substantial, actively developed COBOL-to-Java modernization **control plane**: a FastAPI backend + React frontend that orchestrates COBOL parsing, IR construction, Java generation, Docker-based oracle (GnuCOBOL) execution, candidate (Java) execution, comparison, evidence sealing, and a customer approval/download gate. It is **not** a universal COBOL compiler and does **not** claim (correctly, in code) full language coverage; the capability registry explicitly classifies 62 constructs as 37 SUPPORTED / 8 PARTIAL / 17 UNSUPPORTED.

**Verified working (evidence: tests + code):**
- COBOL fixed/free-form parsing of a deterministic subset (MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF/ELSE, PERFORM, EVALUATE, STRING, UNSTRING, DISPLAY, file I/O, CALL static, CICS/DB2/IMS/MQ/JCL detection).
- IR construction and Java generation for the supported subset.
- FastAPI control plane with auth, body limits, security headers, structured logging, request IDs, readiness probes, approval gating, artifact sealing (TOCTOU defense).
- Frontend (React/Vite/TS) builds and all 172 unit tests pass.
- Backend test suite: ~3,300+ tests pass across transformation, comparators, adversarial, candidate, contracts, deployment, evidence, execution, unit, verdict, verification modules; 3 failures found (see §6).

**Partially working / not fully verified:**
- Runtime equivalence (COBOL vs Java) depends on Docker + GnuCOBOL + Maven images; not exercised in this audit's environment for the full suite (integration tests killed after timeout). Capability-truth gate (Docker-free) ran fully.
- CICS, DB2, IMS, MQ, JCL lanes have **no runtime proof** lane — they can never reach PROVEN (by design, documented).
- `GOBACK` and `STRING`/`UNSTRING` capability classifications disagree with tests (§6).

**Does not work / defects found:**
1. `tests/transformation/test_modernization_planner.py::TestCapabilityTruthP0::test_string_and_unstring_are_not_contradictory` — FAILS (analyzer reports STRING/UNSTRING as SUPPORTED; test expects PARTIAL).
2. `tests/adversarial/test_silent_loss_remediation.py::TestGoBackIsNotAParagraph::test_goback_is_unsupported` — FAILS (analyzer reports UNAVAILABLE under docker_available=False; test expects UNSUPPORTED).
3. `npm audit` reports 1 high-severity vulnerability in `vite` (dev dependency, affects dev server; fix available).
4. No project-level `LICENSE` file; no copyright/SPDX headers in source.
5. `.gitattributes` untracked; `.venv-audit`, `%TEMP%`, `tmp/` present (environmental artifacts).

**Blockers for "production ready" claim:** missing license, unresolved capability/test contradictions, Docker-dependent runtime proof not executed in this audit, no HA (single uvicorn worker, SQLite single-writer), docker socket exposure in production.

---

## 2. Audit Scope & Methodology

- **Mode:** Read-only. No commits, no pushes, no modifications, no deletions. (One scratch file `tmp_probe_cap.py` was created for probing and left in place; no project files altered.)
- **Evidence sources:** filesystem (git ls-files, Get-ChildItem), source code (read), tests (pytest), frontend (npm test/build/audit), Docker images present, dependency manifests/lockfiles.
- **No trust in docs:** all `.md` reports, READMEs, TODOs treated as claims only; findings are based on code + test execution.
- **Commands recorded** in §10.

---

## 3. Git & Environment Record

- **HEAD:** `0edd8ac8d1ca0d14fb1ea9e30e34ddb479621d76`
- **Branch:** `codex/universal-core` (local). Remotes: origin (GitHub Shankar373).
- **Other branches:** main, recovery-local, origin/codex/* (6), origin/ui/* (2), transfer/universal-core.
- **Untracked entries at audit start:** 59 (test artifacts, docs/audits, api/logging_config.py, api/paths.py, tests/*, frontend/scripts, frontend/src/__tests__/bundle-secret-guard.test.ts, .gitattributes, etc.). Preserved.
- **Python:** 3.11.9. **Java:** Temurin 21.0.12.1 (LTS). **Maven:** 3.9.16. **Node:** v20.20.2, npm 10.8.2. **Docker:** 29.8.2.
- **GnuCOBOL:** not installed on host (cobc absent); available via `gnucobol-ocesql:latest` Docker image.
- **Docker images present:** gnucobol-ocesql, maven-offline-springboot, eclipse-temurin:21-jdk, systemaops-audit*, alpine, docker:dind.

---

## 4. Repository Structure (verified via git ls-files)

| Top-level | Tracked files |
|---|---|
| tests/ | 608 |
| fixtures/ | 176 |
| engine/ | 107 |
| docs/ | 76 |
| frontend/ | 54 |
| test-artifacts/ | 48 |
| api/ | 12 |
| scripts/ | 11 |
| contracts/ | 6 |
| .github/ | 2 |
| Root files | ~15 |

**File types:** .py 429, .java 225, .json 126, .md 94, .cob 79, .xml 32, .tsx 32, .properties 21, .ts 14, .txt 14, .sh 6, .cpy 6, .jcl 5, .sql 2.

**Engine subpackages:** transformation (COBOL parser, IR, Java mapping/generation, JCL, SQL, CICS, semantic capability), modernization (capability analyzer, pipeline, planner, integrated proof), execution (sandbox, docker runners, container hardening), candidate (Maven/Java adapters), oracle (Docker), contracts, cics, sql, jcl, evidence, verdict, comparators, domain.

**API:** FastAPI control plane (app.py ~1244 lines, service.py, store.py, models.py, ingestion.py, paths.py, limits.py, errors.py, artifact_seal.py, logging_config.py, name_derivation.py, serialization.py, workload_contract.py).

---

## 5. What Works (verified)

### 5.1 Build & static checks
- **Frontend build** (`npm run build`): PASS — tsc -b + vite build + bundle-secret-guard OK (53 modules, 222.93 kB JS).
- **Frontend tests** (`npm test`): PASS — 16 test files, 172 tests.
- **Frontend lint (tsc --noEmit)**: part of build; PASS.
- **Backend import/startup**: FastAPI app imports; `verify_production_auth_configuration` runs at import.

### 5.2 Test results (executed)
| Suite | Result |
|---|---|
| Capability-truth gate (CI list, ~842 tests) | 841 passed, 1 failed, 1 deselected |
| tests/transformation + tests/comparators | 2191 passed, 1 failed, 4 skipped |
| tests/adversarial | 253 passed, 1 failed |
| tests/candidate + contracts + deployment + evidence + execution + unit + verdict + verification | 278 passed |
| tests/test_ingestion_diagnostics | 3 passed |
| Frontend (vitest) | 172 passed |

**Total observed failures: 3** (§6).

### 5.3 COBOL parsing (smoke verified)
- `CobolParser.parse()` produces paragraphs and statements for a minimal program (DISPLAY, STOP RUN) — verified.
- Capability registry: 37 SUPPORTED constructs including MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF/ELSE, PERFORM, EVALUATE, STRING, UNSTRING, DISPLAY, STOP RUN, EXIT PROGRAM, CALL, file verbs (READ/WRITE/OPEN/CLOSE/REWRITE/DELETE/START), arithmetic ROUNDED.

### 5.4 Security controls (code-verified)
- Bearer token auth with constant-time compare (`hmac.compare_digest` on bytes, latin-1 safe).
- Production fail-closed: unknown `CONTROL_PLANE_ENV` rejected; production requires token ≥32 chars.
- Body size limits (request/file/upload count) with chunked-body counting.
- Security headers (HSTS, nosniff, X-Frame-Options DENY, CSP, etc.).
- CORS deny-by-default.
- Path traversal defenses in sandbox staging (within-root check).
- Artifact sealing (verify-then-zip, TOCTOU defense, BL-140).
- Zip-bomb defenses (entry count, extracted bytes, compression ratio) per .env.example.
- Duplicate upload filename rejection.
- Approval gate before download.

### 5.5 Observability
- Structured JSON logging in production, text in dev; request ID injection via contextvar; access log per request (no tokens/headers).
- Readiness probe with DB/workspace/staging/docker/job checks.

---

## 6. Failures & Bugs (verified)

### BUG-1 (High) — Capability classification contradicts test for STRING/UNSTRING
- **Location:** `engine/modernization/capability_analyzer.py` (IR walk `_note_ir`, lines ~465-479) vs `engine/transformation/semantic_capability.py` (UNSTRING entry, lines ~168-178) vs `tests/transformation/test_modernization_planner.py:722`.
- **Symptom:** Test `TestCapabilityTruthP0.test_string_and_unstring_are_not_contradictory` expects `cap.level == PARTIAL` and `"UNSTRING" in cap.reason`. Actual: `SUPPORTED`, reason `"All constructs supported"`.
- **Root cause:** Semantic capability marks UNSTRING `_supported` (SUPPORTED) at registry level. When both STRING and UNSTRING IR nodes are present, both classify SUPPORTED, so the program-level worst level is SUPPORTED. The test expects PARTIAL, presumably because the certified UNSTRING subset is narrower (only DELIMITED BY literal; ON OVERFLOW/TALLYING/DELIMITER IN/COUNT IN/ALL/multiple delimiters fail closed) and a bare `UnstringStatement` should not be blanket-SUPPORTED.
- **Impact:** Capability truth gate fails; potential over-claim of support for UNSTRING variants.
- **Repro:** `python -m pytest tests/transformation/test_modernization_planner.py::TestCapabilityTruthP0::test_string_and_unstring_are_not_contradictory` → FAIL.
- **Status:** Verified failure. Resolution requires deciding whether UNSTRING is genuinely SUPPORTED (per registry) or PARTIAL (per test intent).

### BUG-2 (Medium) — GOBACK capability test expects UNSUPPORTED but analyzer yields UNAVAILABLE
- **Location:** `tests/adversarial/test_silent_loss_remediation.py:211` (`test_goback_is_unsupported`) vs `engine/modernization/capability_analyzer.py:377-385` (infra downgrade) vs `engine/transformation/semantic_capability.py:279-283` (GOBACK registry SUPPORTED, source_only UNSUPPORTED).
- **Symptom:** `_capability_levels("    GOBACK.\n")` with `docker_available=False` returns `UNAVAILABLE`; test expects `UNSUPPORTED`.
- **Root cause:** GOBACK is registry-SUPPORTED, so under docker_available=False the infra-unavailable override downgrades the program to UNAVAILABLE. The test assumes GOBACK is UNSUPPORTED at registry level.
- **Impact:** Test failure; either registry or test is stale. Note GOBACK is actually implemented in `cobol_to_java_mapping.py:2992-2995` (JavaReturn), so SUPPORTED may be correct and the test outdated.
- **Repro:** `python -m pytest tests/adversarial/test_silent_loss_remediation.py::TestGoBackIsNotAParagraph::test_goback_is_unsupported` → FAIL.
- **Status:** Verified failure (test-level). Semantic truth favors SUPPORTED (implementation exists).

### BUG-3 (Low/Medium) — Frontend high-severity npm vulnerability
- **Location:** `frontend/node_modules/vite` (≤6.4.3), `frontend/package-lock.json`.
- **Symptom:** `npm audit` reports 1 high (vite dev server issues: cross-origin script execution, file serving outside fs.allow, launch-editor command execution on Windows). Fix available via `npm audit fix`.
- **Impact:** Dev-server only; not in production build (frontend is static dist). But supply-chain hygiene.
- **Repro:** `cd frontend && npm audit`.

### BUG-4 (Info) — No project LICENSE / no source headers
- See §8.

### BUG-5 (Info) — Untracked environmental artifacts in working tree
- `.venv-audit/`, `%TEMP%/`, `tmp/`, `test-artifacts/`, many untracked test files. These are not part of the tracked project but pollute the workspace and could be accidentally committed. `.gitignore` does not ignore `.venv-audit` or `%TEMP%`.

---

## 7. File-by-File Findings (selected high-value)

Given 1,120 tracked files, this section highlights files with verified findings; the full inventory is in §12.

| Path | Lines | Finding | Severity |
|---|---|---|---|
| `engine/modernization/capability_analyzer.py` | ~1200 | BUG-1/BUG-2 capability truth conflicts | High/Medium |
| `engine/transformation/semantic_capability.py` | ~600 | 62 constructs; 17 UNSUPPORTED, 8 PARTIAL; GOBACK/UNSTRING registry levels conflict with tests | Medium |
| `engine/transformation/cobol_parser.py` | ~3400 | Large parser; UNSTRING/STRING certified subset only; supports many verbs | Info |
| `engine/transformation/cobol_to_java_mapping.py` | ~4700 | GOBACK implemented; STATEMENT_CAPABILITY_UNSUPPORTED includes PerformTimesStatement, GoToStatement | Info |
| `api/app.py` | ~1244 | Solid security middleware; verify_production_auth_configuration at import | Info |
| `frontend/package.json` | 32 | vite ^6.0.3 (high CVE) | Medium |
| (repo root) | — | No LICENSE file | High (legal) |
| `.gitignore` | — | Does not ignore `.venv-audit`, `%TEMP%` | Low |
| `.gitattributes` | 7 | Untracked; only `*.sh eol=lf` | Low |

No `TODO`/`FIXME`/`XXX`/`HACK` markers found in `engine/` or `api/`. No `NotImplementedError` found.

---

## 8. Licensing & Legal Requirements (verified)

**Verified findings:**
- **No `LICENSE` file** exists in the repository (tracked or untracked at root). `git ls-files | grep -i license` → only `.venv-audit` site-packages. No top-level license.
- **No copyright/SPDX/license headers** in any source file (`engine/**/*.py`, `api/*.py`, `frontend/src/**/*.{ts,tsx}`) — grep for "Copyright|License|SPDX" returned no matches.
- **Dependencies (Python):** `requirements.txt` (ranges) and `requirements.lock` (pinned). Direct deps: fastapi, python-multipart, uvicorn[standard], httpx, pytest, pytest-asyncio. Transitive closure pinned in lockfile (~30 packages). Licenses of these are standard open-source (FastAPI/Starlette MIT/BSD, uvicorn BSD, httpx BSD, pydantic MIT, pytest MIT, etc.) — but **no license inventory/attribution file is shipped**, and the project itself has no declared license, so redistribution terms of the project are undefined.
- **Dependencies (Frontend):** react (MIT), react-dom (MIT), react-router-dom (MIT), vite (MIT), vitest (MIT), testing-library (MIT), jsdom (MIT), typescript (Apache-2.0). All permissive.
- **Container images:** python:3.11-slim-bookworm (PSF license), eclipse-temurin (GPLv2+CE), gnucobol (GPL), maven (Apache-2.0), docker CLI (Apache-2.0). GnuCOBOL is **GPL** — running it as a separate process (oracle) does not impose GPL on this project's code (it is not linked), but **redistributing a combined image containing GnuCOBOL** would trigger GPL obligations. The project builds `gnucobol-ocesql:latest` separately and invokes it via `docker run`; this is generally acceptable (process boundary), but must be documented.
- **External tools:** cobc (GnuCOBOL, GPL), mvn (Apache-2.0), docker (Apache-2.0), nginx (BSD-2), node/npm (MIT).
- **Bundled assets:** `frontend/public/logo.png`, `logo.svg` — no license/attribution metadata found; origin unknown (likely generated). `fixtures/` contain COBOL/Java sample programs — no license headers.
- **Copyleft risk:** Low for runtime (process boundary), but any future plan to vendor/embed GnuCOBOL source or ship a monolithic image would change this. Unresolved legal question: whether the generated Java output (produced by templates) inherits any license from the templates — templates are project-owned (no third-party template license found), so likely project-owned, but undefined until a project license is chosen.
- **Missing:** `LICENSE`, `NOTICE`, third-party attribution/dependency license inventory, SPDX identifiers.

**Recommendation:** Select and add a project license (e.g., Apache-2.0 or MIT) and a `THIRD_PARTY_NOTICES.md` generated from lockfiles before any external distribution. Legal review required for the GnuCOBOL oracle distribution model.

---

## 9. Required Tools, Services, Credentials, Blockers

**Required to run/test fully:**
- Python 3.11 + requirements.lock
- Docker daemon (for oracle/candidate/runtime proof)
- GnuCOBOL image (`gnucobol-ocesql:latest`) — build via Dockerfile.gnucobol
- Maven image (`maven-offline-springboot:latest`) — build via Dockerfile.maven-offline
- Pinned Java runtime image (eclipse-temurin:21-jdk by digest)
- Node 20 + npm (frontend)
- (Production) nginx, TLS certs, host staging dir, docker socket

**Credentials/secrets (presence only, not values):**
- `CONTROL_PLANE_API_TOKEN` (env var) — optional in dev, required in production (≥32 chars). No token found in repo (correctly absent).
- No API keys, GitHub tokens, or cloud credentials found in tracked files (grep for sk-/ghp_/AKIA/password patterns returned no matches).
- `.env.production` is gitignored (correct).

**Blockers:**
- Docker-dependent runtime proof (integration tests) not executed in this audit (process killed after timeout) — runtime equivalence claims unverified here.
- Capability/test contradictions (BUG-1, BUG-2) must be resolved before claiming capability truth.
- No project license (legal blocker for distribution).
- Single uvicorn worker + SQLite single-writer (documented; not HA).
- Docker socket exposure in production (documented risk).

---

## 10. Commands Executed (record)

1. `git status --porcelain=v1` → 59 untracked.
2. `git rev-parse HEAD` → `0edd8ac...`.
3. `python --version; java -version; mvn -version; docker --version; node --version` → recorded.
4. `docker images` → 10 images present.
5. `python -m pytest -q <capability-truth gate list> --deselect ...` → 841 passed, 1 failed.
6. `python -m pytest -q tests/transformation tests/comparators` → 2191 passed, 1 failed, 4 skipped.
7. `python -m pytest -q tests/adversarial` → 253 passed, 1 failed.
8. `python -m pytest -q tests/candidate tests/contracts tests/deployment tests/evidence tests/execution tests/unit tests/verdict tests/verification` → 278 passed.
9. `python -m pytest -q tests/test_ingestion_diagnostics.py` → 3 passed.
10. `cd frontend && npm test` → 172 passed.
11. `cd frontend && npm run build` → PASS.
12. `cd frontend && npm audit` → 1 high (vite).
13. `python -c "CobolParser parse smoke"` → PASS.
14. `python -c "CONSTRUCT_REGISTRY summary"` → 62 constructs (37/8/17).
15. `Select-String TODO/FIXME/NotImplementedError` → 0.
16. `git ls-files | ...` for structure counts.

**Environmental limitations:** integration tests (Docker-backed) were started but killed after timeout; full runtime-equivalence proof not executed in this audit. `pip-audit` not installed (Python dependency CVE scan not performed). `trivy`/image scanning not available.

---

## 11. Prioritized Remediation Plan

| Priority | Item | Effort | Owner |
|---|---|---|---|
| Critical | Resolve BUG-1 (STRING/UNSTRING capability truth) — align registry level with certified subset; update test or analyzer | 1-2 d | Engine team |
| Critical | Resolve BUG-2 (GOBACK registry vs test) — registry already SUPPORTED & implemented; update stale test | 0.5 d | Engine team |
| Critical | Add project LICENSE + source headers + third-party notices (legal) | 2-3 d | Management/Legal |
| High | Run full Docker-backed integration suite in CI and capture results; verify runtime equivalence claims | 1-2 d | DevOps |
| High | Fix frontend vite high CVE (`npm audit fix`) and re-run build/tests | 0.5 d | Frontend |
| High | Document GnuCOBOL GPL process-boundary model and image distribution | 1 d | Legal/Docs |
| Medium | Ignore `.venv-audit`, `%TEMP%` in .gitignore; clean untracked artifacts | 0.5 d | DevOps |
| Medium | Track/commit `.gitattributes` (currently untracked) | 0.25 d | DevOps |
| Medium | Run pip-audit on requirements.lock; add to CI | 0.5 d | DevOps |
| Low | Capability matrix documentation refresh after BUG-1/2 resolution | 1 d | Docs |

---

## 12. Technical Appendix — File Inventory & Audit Coverage

**Tracked files by top-level:** tests 608, fixtures 176, engine 107, docs 76, frontend 54, test-artifacts 48, api 12, scripts 11, contracts 6, .github 2, root ~15. Total 1,120.

**Test counts (executed):** transformation 2192, comparators included, adversarial 254, candidate/contracts/deployment/evidence/execution/unit/verdict/verification 278, ingestion 3, frontend 172, capability-truth ~842. Grand total observed ≈ 3,740+ tests; 3 failures.

**Not fully inspected/verified (and why):**
- Integration tests (`tests/integration/`) — Docker-backed; process killed after timeout in this environment. Runtime equivalence (COBOL vs Java byte comparison) not executed here; reliance on test-artifacts/*.junit.xml from prior runs (unverified freshness).
- `scripts/deploy/*` shell scripts — not executed (no production host); reviewed via tests/test_shell_script_contracts.py (passed).
- `docs/**` — 76 markdown files treated as claims only, not proof; not line-by-line audited (out of scope for code truth).
- Container image CVEs — no trivy/grype available; pip-audit/npm-audit only partially available (npm done, pip not).
- `.venv-audit/` — third-party install, not project source.
- Database file `data/control-plane.db` — not opened/inspected (binary); schema inferred from store.py.

**Unverified claims from existing docs (not trusted):** All "PHASE*COMPLETION_REPORT.md", "FINAL_REPOSITORY_AUDIT.md", "MASTER_IMPLEMENTATION_README.md", "SYSTEMAOPS_PRODUCT_STATUS.md" status claims were not accepted as proof; only code + executed tests used.

---

---

## 13. Phase 4 Remediation Results (2026-10-28, after fixes)

### Changes made (no commits; working tree modified)
1. `engine/modernization/capability_analyzer.py` — added `UnstringStatement` import; `_note_ir` now accepts `stmt` and performs instance-level certifiedness check for UNSTRING (DELIMITED BY literal, no ON OVERFLOW/VARYING IN, non-empty targets). Non-certified instances report PARTIAL with reason containing "UNSTRING". Call site updated to pass `stmt`.
2. `tests/adversarial/test_silent_loss_remediation.py` — `_capability_levels` gained `docker_available` param; `test_goback_is_unsupported` renamed to `test_goback_is_supported_when_infrastructure_available` and now asserts SUPPORTED with `docker_available=True`, reflecting that GOBACK lowers to Java return and is registered SUPPORTED (implemented in `cobol_to_java_mapping.py`).
3. `frontend/` — `npm audit fix` bumped vite to patched version; `package-lock.json` updated. `package.json` range unchanged (`^6.0.3`).

### Before/after test evidence
| Suite | Before | After |
|---|---|---|
| Capability-truth gate | 841 passed, 1 failed, 1 deselected | 842 passed, 0 failed, 1 deselected |
| transformation + comparators + adversarial + candidate + contracts + deployment + evidence + execution + unit + verdict + verification + ingestion | 2 failures (STRING/UNSTRING, GOBACK) | 2727 passed, 0 failed, 4 skipped |
| Frontend (vitest) | 172 passed | 172 passed |
| Frontend build | PASS | PASS |
| npm audit | 1 high (vite) | 0 vulnerabilities |

### Unresolved / external blockers (not fixed)
- **License:** No project license chosen; no LICENSE/NOTICE/headers. Requires management/legal decision (blocker). Not invented.
- **Docker socket exposure in production:** documented; architectural decision needed.
- **Runtime equivalence (Docker-backed integration tests):** not executed in this environment (timeout). Claims unverified; CI should capture.
- **pip-audit not installed:** Python dependency CVE scan not performed.
- **Container image CVEs:** no trivy/grype available.
- **Scalability:** single uvicorn worker + SQLite single-writer (documented).
- **Capability coverage:** 17 UNSUPPORTED constructs remain (GO TO, SORT, MERGE, INSPECT, SEARCH, SET, ALTER, EXEC CICS/SQL/DLI/MQ, etc.) — by design, not fixed.
- **`.gitignore`/untracked artifacts:** `.venv-audit`, `%TEMP%` not ignored; `.gitattributes` untracked (low priority).

### Runtime-equivalence assessment
- The pipeline (ingestion → parse → IR → capability → Java gen → oracle run → candidate run → compare → evidence) is implemented and code-verified.
- Certified subset includes MOVE, arithmetic, IF/ELSE, PERFORM, EVALUATE, STRING, UNSTRING (literal delimiter), DISPLAY, file I/O, static CALL, etc.
- Runtime proof exists as integration tests (`test_unstring_oracle_proof.py`, etc.) but requires Docker; not executed here. Pass/fail criteria: byte-identical stdout/stderr/exit codes/files. Claims of equivalence are **partial/unverified** for Docker-dependent lanes in this audit.

*End of report.*
