# WS4 — Final Integration / Release Candidate Gate

* Workstream: WS4 (final integration gate).
* Gate baseline: `feb164c` (WS2). Workstreams integrated: WS1, WS2 (`feb164c`),
  WS3 (`e70ccbf`), WS5 (`83941b4`), WS6 (`bf55ad7`), WS7 (`accda1f`).
* Engineering baseline before the workstreams: `fedb7dd`.
* Evidence directory: `test-artifacts/w4-gate/`.
* Scope note: this document records what was **measured**. It changes no
  engine semantics and makes no new capability claim.

---

## 1. Verdict

**NOT READY.**

The application/platform chain is proven end to end with real Docker evidence
(section 3). The **production deployment stack is not**: the committed
`docker-compose.production.yml` topology cannot execute the COBOL oracle or the
Java candidate, so a deployed instance can never produce a verdict
(section 7). Two further release risks are recorded in section 9.

This document does **not** claim universal COBOL modernization, universal z/OS
equivalence, or DB2/CICS/JCL runtime equivalence.

---

## 2. Integration defects found and fixed by this gate

| # | Area | Defect | Fix |
|---|------|--------|-----|
| 1 | WS1 API | `GET /runs/{run_id}/report` registered **twice** in `api/app.py` (byte-identical duplicate decorator) | removed the redundant registration; route table now has exactly one |
| 2 | WS1/WS3 frontend | `ModernizationRun.tsx` rendered `<VerdictDisplay>` twice (concurrent WS1 + WS3 edits) | removed the duplicate render |
| 3 | WS1 API ↔ transformation | **`java_entrypoint` default `"Main"` silently corrupted every CALL-containing workload** (see 2.1) | `Service._resolve_entry_program()`; regression tests in `tests/test_entry_program_resolution.py` |
| 4 | WS6 deployment | non-root API container could not reach the mounted Docker socket (see 7.1) | `group_add: ["${DOCKER_GID:-0}"]` on the `api` service (**necessary but not sufficient** — 7.2/7.3 remain) |

Also removed (untracked, zero code references, all listed as problems by
`docs/audits/DOCUMENTATION_PRODUCT_READINESS_AUDIT.md:76-77`): 21 root-level
scratch files (`*.txt` test-log dumps, `demo_workflow.py`, `verify_demo.py`,
`run_final_demo_check.py`, `demo_continue.py`, `demo-source.zip`,
`download_test.zip`, `.commit_msg_new`). Tracked `engine_py_files.txt` was
**restored**, not deleted.

### 2.1 Defect 3 in detail (the significant one)

`ApplicationCreate.java_entrypoint` defaults to the placeholder `"Main"` and the
frontend never sends the field (`frontend/src/App.tsx:115-119`).
`Service._generate_application` forwarded it verbatim into
`ModernizationConfig.entrypoint`. `engine/transformation/java_to_spring_mapping.py:628-652`
(`_derive_entry_point`) honours that value **only when it matches a discovered
COBOL PROGRAM-ID**; anything unmatched falls back to "invoke every service",
which hoists CALL targets into top-level `CommandLineRunner` beans.

For `fixtures/workload-integrated` this reordered the CALL chain:

```
oracle    : INTEGRATED DEMO STARTED / INPUT ... / CALC-START / CALC TAX=015000 / ...
candidate : CALC-START / CALC TAX=000000 / INTEGRATED DEMO STARTED / ... / CALC START again
```

Measured result before the fix: `STDOUT MISMATCH` → runtime verdict `FAILED` →
`central_status NOT_VERIFIED`, on a workload the project's own Phase-D test
certifies as `VERIFIED` when it is given the real PROGRAM-ID.

The fix resolves the entry program from the application's own discovery:
the declared value when it matches, otherwise the single discovered program no
CALL targets, otherwise `""` (existing assembler behaviour, unchanged).
No gate, comparator or verdict rule was weakened.

---

## 3. Golden path Docker proof (real, no mocks)

Workload `workload-integrated` (COPYBOOK + static CALL + LINE SEQUENTIAL file),
driven through the real HTTP API against a real SQLite control plane.
Evidence: `test-artifacts/w4-gate/golden-integrated.json`.

| Step | Measured |
|------|----------|
| COBOL source | `sha256:3e1166c3ea421707ececa92119fcd61eb0300517180df0394d93ec40bc08f1fd` (3 files, 3057 B) |
| GnuCOBOL oracle | `gnucobol-3.1.2`, image `sha256:1a290177e8dfeaae6f9ffa1fd3431e08338e8a11fa164116484a86163e4ffc35`, exit 0 |
| Java/Spring build | Docker `maven-offline-springboot:latest`, exit 0 |
| Java candidate | Docker `eclipse-temurin:21-jdk`, exit 0 |
| Comparison | STDOUT / STDERR / EXIT_STATUS / FIXED_RECORD = **4 × MATCH**, 0 skipped, 0 unavailable |
| Evidence manifest | `sha256:748825898c09955bca4c3abeabc21ae6733fe2403a816db8f80d3bf7b827bfce`, complete, integrity valid |
| Verdict | `VERIFIED` |
| Integrated proof | computed at validation, persisted, `central_status = VERIFIED` |
| Proven dependencies | 6 — `INTGCALC`, `INTGMAIN`, `FILE:INTGMAIN:TAX-OUT`, `FILE:INTGMAIN:TAX-IN`, `COPYBOOK:TAXREC`, `CALL:INTGMAIN->INTGCALC` |
| Certification contract | `declared:workload-integrated` (fixture registry, not the default) |
| **Restart / reload** | new OS process, same DB file; `GET /runs/{id}/integrated-proof` → HTTP 200, payload **byte-identical** to the pre-restart read |
| Run id | `run-52e01d906bc2` |

**Critical release condition: YES.** A real Docker workload went COBOL source →
GnuCOBOL oracle → deterministic transformation → Java/Spring build → Java
candidate execution → output capture → comparison → evidence manifest → evidence
integrity validation → `VERIFIED` verdict → integrated-proof persistence →
process restart → `GET /runs/{id}/integrated-proof` returning the persisted
proof, with 6 `PROVEN` dependencies and no mocks or synthetic evidence.

### 3.1 Gate downgrade proven (JCL lane has no runtime)

Same workload with the JCL job stream visible
(`test-artifacts/w4-gate/golden-integrated-with-jcl.json`, run
`run-1ae6d0511673`): `jcl_status = FULL`, JCL ledger entry
`PARTIAL / required`, 6 runtime dependencies still `PROVEN`,
`central_status = NOT_VERIFIED`, `required_dependencies_proven = false`,
reason: *"JCL has no runtime lane in this repository; the job stream is parsed
and classified but never executed"*. Persisted and identical after restart.

---

## 4. Negative path

| Workload | Outcome | Evidence |
|----------|---------|----------|
| `workload-level88` (88-level + `SET`) | capability `UNSUPPORTED` — "Contains unsupported constructs: SET …"; run `FAILED`; verdict HTTP 404; proof HTTP 404. **No certification.** | `negative-level88.json` |
| `workload-cics` (`EXEC CICS`) | capability `UNSUPPORTED`; run `FAILED` "Transformation plan contains non-transformable programs: CUSTINQ, ORDPROC" | `negative-cics.json` |
| `workload-db2` (`EXEC SQL`) | capability `UNSUPPORTED` (analyser-level measurement) | — |
| `workload-integrated` + JCL | generation and runtime succeed, application-level gate refuses `VERIFIED` with a visible reason (§3.1) | `golden-integrated-with-jcl.json` |

**Limitation (honest):** on a generation failure the API does not persist the
capability analysis, so `GET /runs/{id}/integrated-proof` returns 404 rather
than a `NOT_VERIFIED` proof carrying the blocking reason. The reason *is*
visible on `GET /runs/{id}` (`stage = FAILED`, `error = …`) and in the
infrastructure phase logs. Closing this is WS1 work, not gate work.

---

## 5. Trust attacks

92 adversarial tests pass (`test-artifacts/w4-gate/trust-attacks.log`); 378 pass
across the adversarial/verdict/evidence/persistence/certification suites.

Live attacks against the **real** persisted control plane (each: mutate SQLite
→ restart a new API process → read back). Evidence:
`test-artifacts/w4-gate/trust-attacks-live.json`.

| Attack | Result | Contained |
|--------|--------|-----------|
| flip a sealed MATCH comparison to MISMATCH | 500 `persisted evidence seal mismatch` | YES |
| mutate a sealed artifact `content_hash` | 500 seal mismatch | YES |
| clear the evidence seal | 500 `no seal` | YES |
| VERIFIED verdict, evidence manifest removed | verdict 500 `claims VERIFIED without a persisted evidence manifest` | verdict YES / **proof NO** |
| verdict bound to a different manifest hash | 500 hash mismatch | YES |
| manifest + executions rehomed to another workload | 500 seal mismatch (all endpoints) | YES |
| manifest rehomed to another run id | 500 seal mismatch (all endpoints) | YES |
| persisted verdict `workload_id` rehomed | 200 `VERIFIED`, `workload_id = attacker-workload` | **NO** |
| `runs.workload_id` diverges from the application | 200 `VERIFIED` | **NO** |
| persisted verdict `source_hash` / `candidate_hash` / `oracle_digest` mutated | 200 `VERIFIED` | **NO** |
| persisted verdict state forced `PARTIAL` (control) | 200 `PARTIAL` — state is **not re-derived** on read | — |
| persisted `PARTIAL` verdict forged to `VERIFIED` | 200 `VERIFIED` | **NO** |
| persisted integrated proof forged `NOT_VERIFIED → VERIFIED` | 200 `VERIFIED` | **NO** |

All uncontained attacks require direct write access to the control-plane
database. `docs/TRUST_BOUNDARY.md:62-67` places whole-record rewrites out of
scope and calls authenticated seals "future hardening" — so these are
**documented-by-decision gaps**, except that:

* `docs/TRUST_BOUNDARY.md:92-94` states `integrated_proof.py` "re-validates the
  evidence manifest instead of trusting the verdict before opening the central
  certification gate". That is true when the proof is **computed** and **false**
  for the persisted read path, which serves `report_blob["integrated_proof"]`
  verbatim. The document overstates the shipped guarantee.

---

## 6. Test matrix

| Suite | Command | Result |
|-------|---------|--------|
| Backend + oracle + integration + Docker | `RUN_DOCKER_TESTS=1 python -m pytest -ra tests` | **3022 passed**, 0 failed, 0 skipped, 55m31s |
| Adversarial trust | `pytest tests/adversarial` | 254 collected, all pass |
| Verdict / evidence trust | `pytest tests/verdict tests/evidence` | 18 + 17, all pass |
| Persistence + certification | `pytest tests/test_persistence_integrity.py tests/test_control_plane_persistence.py tests/test_certification_contract.py` | pass |
| Frontend unit/component | `npm test` | **122 passed** (7 files) |
| Frontend types + production build | `npm run build` (`tsc -b && vite build`) | pass, 214.77 kB JS / 63.09 kB gzip |

No test was weakened, skipped or deleted by this gate.

---

## 7. Production deployment

### 7.1 Docker socket unreachable — FIXED (necessary, not sufficient)

`Dockerfile.production` runs as `uid/gid 10001`. The host daemon socket is
`srw-rw---- root:root`. Without group alignment every daemon call fails:

```
permission denied ... /var/run/docker.sock
ValueError: oracle image identity is not established: docker image
'gnucobol-ocesql:latest' resolved to no immutable digest and no sha256 pin
```

The evidence gate behaved correctly (failed closed, no unpinned oracle
identity reported). The **deployment** was wrong. Fixed by adding
`group_add: ["${DOCKER_GID:-0}"]`; verified `docker image inspect` then
returns the RepoDigest from inside the container.

### 7.2 Workspaces are not host-visible — **OPEN, release blocker**

`docker-compose.production.yml` sets `TMPDIR=/app/tmp` (a `tmpfs`) and mounts
`control-plane-work` as a **named volume**, but nothing ever writes workspaces
to `/app/workspaces`. Ingest workspaces and generated projects are therefore
created under the container's own `tmpfs`.

The engine bind-mounts those container-internal paths into sandbox containers
that the **host** daemon starts, so the host resolves
`/app/tmp/ingest-…` against the host filesystem, creates an empty directory,
and the sandbox sees nothing:

```
cobc: /workspace/source/MAIN.cob: No such file or directory
```

Reproduced end to end; verdict degrades to `UNAVAILABLE`.

### 7.3 Workspace ownership — **OPEN**

A host bind mount for workspaces is root-owned; uid 10001 cannot create its
scratch tree: `mkdir: cannot create directory '/var/lib/systemaops/work/tmp':
Permission denied`.

### 7.4 Residual state after working around 7.1–7.3

With the socket, a host-visible workspace bind mount and matching ownership,
the chain executes but the lanes still disagree (STDOUT/STDERR/EXIT_STATUS/
FIXED_RECORD all `MISMATCH`, candidate exit 1). The residual cause is **NOT
VERIFIED** — not diagnosed at this gate.

### 7.5 What does validate

| Check | Result |
|-------|--------|
| `docker compose -f docker-compose.production.yml config` | renders cleanly (`ENV_FILE=.env.production.example`); `group_add` present |
| `docker build -f Dockerfile.production` | builds, exit 0 |
| Runtime identity | `uid=10001(systemaops) gid=10001(systemaops)` |
| `HEALTHCHECK` | `healthy`; `/health` → `{"status":"ok"}` |
| Auth | `/applications` without token → **401**; with `Bearer` → 200 |
| Security headers | HSTS, nosniff, DENY, Referrer-Policy, CSP, no-store — all present |
| `nginx -t` (with resolvable `api` upstream + generated test cert) | **syntax ok / test successful** |
| `bash -n` on all 6 deploy/backup scripts | OK |

**Static-frontend routing defect (OPEN):** `frontend/vite.config.ts` sets no
`base`, so the build emits absolute `/assets/…` URLs, while
`deployment/nginx/systemaops.conf:67-70` serves the SPA only under
`location /app/` (and the app has no router `basename`). Requests for
`/assets/…` fall through to the API proxy. No test or CI step exercises `dist/`
through this nginx config.

### 7.6 Backup / restore / rollback

`scripts/backup/backup.sh`, `restore.sh` and the four `scripts/deploy/*.sh`
are syntactically valid and document their scope honestly. They were **not
executed** against the live stack: `backup.sh`/`restore.sh` assume the named
volumes and would tar/restore the wrong (unused) workspace path until 7.2 is
fixed. Backup scheduling, off-host replication and restore drills are
explicitly **NOT IMPLEMENTED** in `docs/operations/BACKUP_RECOVERY.md`.

---

## 8. Supply chain

| Item | State |
|------|-------|
| Python lock | `requirements.lock` — 26 exact pins. **Not installed by any build**: `Dockerfile.production:50-51` and `ci.yml:25,66` install the ranged `requirements.txt`. The audited pins and the shipped pins can differ. |
| Frontend lock | `frontend/package-lock.json` committed; CI uses `npm ci` (effective reproducibility from the lock, not from `package.json` caret ranges) |
| Container pins | 4 images pinned by `sha256` digest (`Dockerfile.production`, `Dockerfile.maven-offline`, `Dockerfile.gnucobol`, `compose:nginx`) |
| CI actions | all `uses:` SHA-pinned |
| SBOM | CycloneDX for Python (`cyclonedx-bom`) and frontend (`npm sbom`), CI-artifact only, 90-day retention; nothing committed |
| Vulnerability scan | `pip-audit` + `npm audit`, **advisory only** (`continue-on-error`); no gate exists |
| Release manifest | `scripts/supply-chain/build_release_manifest.py` runs clean (exit 0); records 26 Python pins, 123 npm packages, 4 container images, 8 SHA-pinned actions, 3 notes. Reports `lockfileVersion: null` although `package-lock.json` has `lockfileVersion: 3`. |

`Dockerfile.production:31-40` downloads the Docker CLI by version over HTTPS
with **no checksum verification**. Backup scripts use tag-only images
(`python:3.11-slim-bookworm`, `alpine:3.20`), inconsistent with the digest policy.

### 8.1 Dependency findings (no upgrades applied, per instruction)

`npm audit`: 9 findings — **2 critical, 2 high, 5 moderate**
(`tinypool` CRITICAL prototype-pollution→RCE, `vitest` CRITICAL file read/exec,
`source-map-js` HIGH DoS, `vite` HIGH path traversal, plus `esbuild`,
`vite-node`, `react-router`, `@vitest/mocker`). The only direct fix is
`vitest@5.0.3` and `react-router-dom@7.18.4` — both semver-major.
Not upgraded, as instructed.

`pip-audit -r requirements.lock`: **10 known vulnerabilities in 4 packages** —
`pytest` (CVE-2025-71176, dev-only), `anyio` ×2, `idna` (DoS),
and **`starlette` 1.2.1 ×2 (CVE-2026-54282, CVE-2026-54283)**.

**`starlette` is a runtime dependency of the production API**, and
CVE-2026-54283 states that `request.form()` field-count/size limits are
silently ignored for `application/x-www-form-urlencoded` bodies — a DoS on an
endpoint this API exposes. Fix is `starlette>=1.3.1`. Because
`Dockerfile.production` installs the ranged `requirements.txt`, the shipped
version is whatever resolves at build time, not the audited pin. Recorded as a
release risk (see §9).

---

## 9. Release risks carried forward

| # | Risk | Severity |
|---|------|----------|
| R1 | Production stack cannot execute the oracle/candidate lanes (§7.2, §7.3) — a deployed instance can never certify anything | **blocker** |
| R2 | `starlette` CVE-2026-54283 on the production API form path; production image installs ranges, not the audited lock (§8.1) | high |
| R3 | Persisted integrated proof and persisted verdict `state` are not sealed and are not re-derived on read → a database-write attacker can forge `VERIFIED` (§5) | high |
| R4 | `COMP` / `COMP-3` `USAGE` is unmodelled by parser, `CONSTRUCT_REGISTRY` and the coverage registry. Measured: `fixtures/workload-comp` (every field `PIC … COMP`) is classified `SUPPORTED — "All constructs supported"` and certified **VERIFIED at application level**, because its values happen to be DISPLAY-representable. Known as roadmap P0-2; still open. | high |
| R5 | `runs.workload_id` / `verdict.workload_id` are never cross-checked against the application (§5) | medium |
| R6 | npm: 2 critical + 2 high advisories, fixes are semver-major | medium |
| R7 | `requirements.lock` is not installed by `Dockerfile.production` or CI | medium |
| R8 | nginx serves the SPA at `/app/` while the Vite build emits `/assets/…` (§7.5) | medium |
| R9 | Vulnerability scans are advisory only; no CI gate | medium |
| R10 | Backup/restore operate on the unused named volume until R1 is fixed; no scheduler, no off-host copy, no restore drill | medium |
| R11 | `SOURCE_ROOT_MARKERS` matches only literal `main.cob`/`main.cbl`, so a source named `MAIN.cob` falls through to "check one level down"/fallback; and JCL under a sibling `jcl/` directory is invisible to discovery (measured: `jcl_status = NOT_PRESENT`). Copybook resolution is not recursive, so a nested `cobol/` source root breaks `COPY` | low |
| R12 | Baseline SHA `fedb7dd` and CI run ids `#417`/`#418` are pinned in 11 documents but predate `accda1f`, `bf55ad7`, `83941b4`, `feb164c` | low |

---

## 10. Not verified

* R1's residual lane mismatch after 7.1–7.3 are worked around — cause unknown.
* Backup / restore / rollback were not executed against a live stack.
* `docker-compose.production.yml` was validated by `config` render and by
  running the image manually; the full stack (api + nginx over TLS) was never
  brought up together, because the api service cannot validate a workload.
* The `sha256:` digests in the four Dockerfiles were not re-resolved by
  rebuilding those images (`DEPENDENCY_AUDIT.md:143` records the same gap).
* The production image ran under Docker Desktop on Windows; a Linux host may
  differ in socket ownership.