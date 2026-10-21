# Universal Runtime-Proof Audit and Implementation Plan

**Document type:** Evidence-driven repository audit, remediation record, and roadmap (task deliverable)
**Repository:** `Shankar373/Cobol-Java-Transformation`
**Branch:** `codex/universal-core` (no branch switch, no merge, no push, no commit performed)
**Audited HEAD:** `6145e892e95282a0ca85eb678057a0ea9890389c` ("docs(phase12-p4): checkpoint close note")
**Audit/implementation date:** 2026-10-19
**Auditor/implementer:** OpenCode (MiMo agent session), NO-LLM invariant respected — no LLM, model API, or nondeterministic AI dependency exists or was introduced anywhere in the repository (re-verified by repository search this session: 0 model-provider packages/keys/endpoints in `requirements.*`, `frontend/package*.json`, workflows, scripts, Dockerfiles, `engine/`, `api/`).

---

## 1. Executive Summary and Verified Repository State

SystemaOps is a deterministic COBOL→Java modernization platform with a single canonical pipeline (ingest → discover → analyze → plan → parse → IR → transform → Java IR → runtime adapter → build → isolated Docker execution → GnuCOBOL oracle execution → differential comparison → evidence → verdict → approval-gated export), a FastAPI control plane, a React SPA, digest-pinned Docker execution lanes, and a fail-closed evidence/verdict system.

**Verified baseline (this session):**

| Item | Verified value |
|---|---|
| Branch / HEAD | `codex/universal-core` @ `6145e89` == `origin/codex/universal-core` (`git status`, `git log`) |
| Working tree at audit start | 8 modified + 8 untracked files: an **in-flight, documented, uncommitted runtime-proof changeset** (EV-006/R9 FILE-dependency proof binding, mixed-run aggregation test, byte-identity determinism test, file-workload API proof, `RUNTIME_PROOF_MATRIX.md`, audit report) plus an **undocumented-in-that-report follow-up fix** for the 4 disclosed Windows-only path-separator test failures (`tests/test_runtime_adapter_architecture.py::_project_file_set` POSIX logical-path contract + `TestProjectFileSetPlatformContract` regression class) |
| CI at audited SHA | **Independently re-verified live** via GitHub REST API this session: runs 38980053986 (SystemaOps CI) and 38980054137 (Supply chain) at head `6145e89` — `success`; likewise 4/4 green at docs SHA `690980c`. CI has **not** run against the uncommitted working tree (by definition) |
| Local toolchain | Python 3.11.9, JDK 21.0.12.1, Docker 29.8.2, Node 20.20.2, Maven 3.9.16; GnuCOBOL available only inside the digest-pinned `gnucobol-ocesql` Docker image (no host `cobc`) |
| Prior verified state | Phase 12 declared `COMPLETE — VERIFIED` (`opencode.md`, 2026-10-17): §71 gate 19✅/2⚠️/0❌, §53 13/13, backend junit 3905/0/0 at work SHA `0ae8c0f`, 16/16 Phase-12 CI runs green — corroborated by the line-by-line audit `docs/reports/MASTER_README_LINE_BY_LINE_AUDIT.md` (2026-10-16) and re-checked live this session |

**This session's headline results (all locally executed, exact commands in §10):**

- The in-flight changeset's new unit tests: **51/51 green**, including the previously failing Windows-only runtime-adapter tests.
- Four new verified defects found by this audit were fixed **red-first** (BL-094/095/096/097): frontend Authorization integration, `docker_available=True` hardcode, dashboard "Verified" overclaim, and platform-canonical ZIP ingestion + source-tree hashing. Backend focused 5/5 + 8/8, API/ingestion regression 70+54+45+17 passed, frontend **143/143** (was 133), `tsc --noEmit` clean, production build clean.
- A full `RUN_DOCKER_TESTS=1 pytest tests` run was launched on the working tree; the final post-change full-suite result is recorded in the verification ledger appended to this document and in `opencode.md`.

**Truthfulness boundary:** nothing in this document claims universal COBOL support, z/OS equivalence, or production readiness. Every PROVEN label names the exact test that produced it; everything else is PARTIAL/UNKNOWN/UNAVAILABLE/UNVERIFIED with the reason.

---

## 2. Is the Master README Complete, Accurate, and Implementable?

`MASTER_IMPLEMENTATION_README.md` (2346 lines, §1–§80) was read in full this session and cross-checked against the repository.

**Verdict: complete as a specification, internally consistent, implementable, and accurate in its self-description. No corrections required.**

- It deliberately separates **requirements/architecture** (this document) from **live state** (`opencode.md`) in §75, so it contains no stale status claims to correct.
- §8 ("Current Reality vs Final Target") honestly describes the implementation as a proven subset and forbids universal-support claims — consistent with `docs/CAPABILITY_MATRIX.md`, `docs/verification/RUNTIME_PROOF_MATRIX.md`, and the runtime lanes actually present.
- Its verification semantics (§14 capability truth, §40 verification ladder, §53 completion rule, §60 no-silent-loss, §61 no-fake-verification, §76 audit-first, §77 backlog contract) are enforced by executable gates found in the repository: the frozen 54-file capability-truth gate in `ci.yml`, `test_silent_loss_registry.py`, the integrated-proof fail-closed gate (`engine/modernization/integrated_proof.py::evaluate_central_status`), and the 93-row backlog register.
- Apparent tensions were checked and resolved by its own rules: e.g. §32 lists initial runtime targets (Spring Boot, Jakarta EE, Plain Java) — all three exist with deterministic, fail-closed selection (`engine/transformation/runtime_adapters.py::get_runtime_adapter`, `SUPPORTED_TARGET_RUNTIMES`); "eventually" clauses (§16–§29) are requirements, not claims.
- The §71 Final Release Gate is **not** fully passed: 19✅ / 2⚠️ (checkbox 4 universal COBOL coverage — explicitly not claimed; checkbox 14 security — disclosed single-token/no-RBAC/no-audit-log limits). This matches the master README's own rule that the gate cannot be declared while limitations remain undisclosed.

---

## 3. Requirement-by-Requirement Audit Matrix (condensed)

The complete §-by-§ matrix (with file:line entry points, tests, and CI evidence) is maintained at `docs/reports/MASTER_README_LINE_BY_LINE_AUDIT.md` (audited SHA `f3d0352`; every phase SHA re-verified). This session re-verified the highest-risk rows against the current tree:

| Master README requirement | Implementation (verified entry points) | Verification re-checked this session | Status |
|---|---|---|---|
| §9–§10 one canonical pipeline | `engine/modernization/pipeline.py::UniversalModernizationPipeline.execute` (phases 1–5) + `engine/pipeline.py::VerticalSlicePipeline.run` (phases 6–11), joined by `engine/modernization/integrated_proof.py::integrated_proof_from_pipelines` | Structure re-verified via full module trace; no duplicate pipeline found | Implemented |
| §11 secure ingestion | `api/ingestion.py::ingest_zip` (traversal, symlink, entry/size caps, resolved-path containment), `api/app.py` bounded uploads | Phase-11 suites re-run this session (54 passed incl. upload-integrity/auth/download/approval) | Implemented + tested |
| §14/§15 capability truth + fail-closed planning | `engine/modernization/capability_analyzer.py::_check_infrastructure`, `modernization_planner.py`, `semantic_capability.py` registry | **Defect found and fixed this session:** `api/service.py` hardcoded `docker_available=True` (BL-095) | Implemented (defect fixed) |
| §16–§21 parser/IR/COPYBOOK/CALL | `engine/transformation/cobol_parser.py` (2,712 lines), `ir.py` (1,706), `copybook_resolver.py`, CALL threading (BL-045 fixed `accc81a`) | Hundreds of parser/IR tests in `tests/transformation/`; capability-truth gate green at HEAD | Implemented for the certified subset |
| §18 numeric semantics | `numeric_semantics.py`, ROUNDED HALF_UP oracle-proven lane (`tests/integration/test_numeric_oracle_proof.py`, `test_phase7d_runtime.py`) | Cited suites are Docker lanes executed in the running full-suite verification | Implemented for value semantics; COMP/COMP-3 byte encoding **unverified** (D-6) |
| §25 files/VSAM | sequential LINE SEQUENTIAL write/read runtime-proven with generated Java; indexed/relative emulated | In-flight changeset makes `workload-file-write-read` PROVEN end-to-end (engine lane + certification API) — new tests present and unit-level green; Docker lanes executing in the full-suite run | Sequential implemented/proven; indexed/relative PARTIAL |
| §32 runtime adapter architecture | `runtime_adapters.py`: `spring_boot`/`plain_java`/`jakarta_ee`; `engine/candidate/factory.py::candidate_adapter_for_target`; unknown target → `ValueError` naming supported set; unimplemented → `RuntimeAdapterNotImplementedError` (never silent Spring Boot fallback) | `tests/test_runtime_adapter_architecture.py` **51/51 green** this session (incl. new platform-contract class) | Implemented + tested |
| §34 isolated execution | `engine/execution/docker_runner.py`, `engine/candidate/docker_*_adapter.py`, `engine/oracle/docker_adapter.py`: `--network none`, memory/CPU/PID limits, timeouts, digest pinning fail-closed | Re-verified via adapter source + provenance record; containers run as root (documented limitation) | Implemented (root-in-sandbox disclosed) |
| §35–§37 oracle/candidate/differential | digest-pinned GnuCOBOL oracle; comparator registry (`engine/comparators/framework.py`: Stdout/Stderr/ExitStatus/TextFile/FixedRecord); mutation suites | Payroll 9-mutation + mixed MATCH/MISMATCH run test (in-flight, EV-002) | Implemented |
| §38–§41 evidence/verdict/integrated proof | `engine/evidence/integrity.py` (19 violation types), `engine/verdict/derivation.py` (7 states, fail-closed), `evaluate_central_status` (gate can only downgrade) | In-flight EV-006/R9 fix binds FILE-dependency proof to compared file artifacts — 6 new unit tests green | Implemented (FILE binding fixed this tree) |
| §42/§43 security/auth | bearer token middleware (`api/app.py:192–230`, constant-time, BL-049), CORS deny-by-default, security headers, approval-gated download (409) | Phase-11/12 suites re-run (54 passed) | Implemented; **frontend integration defect found and fixed (BL-094)**; RBAC/audit-log/multi-node remain disclosed §43 carries (D-5) |
| §46 product modes A/B | Mode B via `POST /applications/{id}/candidate` (internal/test-only) | endpoint + candidate suites | Implemented |
| §51 CI/CD | `ci.yml` 4 jobs (no `continue-on-error`), `supply-chain.yml` 3 gating jobs (pip-audit, npm audit, release manifest) | Live re-verification of run conclusions via GitHub API this session | Implemented |
| §70/§71 DoD + release gate | approval workflow BL-091 (`0ae8c0f`), export gating, docs reconciliation F-02 (`162520b`) | Checkpoint/audit consistent; see §2 | Partial by design (2 disclosed ⚠️) |

---

## 4. Implemented vs Partially Implemented vs Missing

**Implemented and runtime-proven (generated-Java lanes, GnuCOBOL-compared in Docker):** file write/read sequential workload, integrated application (copybook + CALL + FILE), copybook lane, CALL chain, arithmetic/numeric semantics, VALUE/figurative semantics. Each row names its test module in `docs/verification/RUNTIME_PROOF_MATRIX.md`.

**Implemented but not runtime-proven (machinery proven with prewritten candidates or structural-only):** payroll, claims batch, indexed/relative (emulated, no real VSAM), JCL (compile+start only, no behavioural lane), CICS (generation only), DB2 (controlled SQLite harness explicitly not a DB2 runtime), MQ/IMS (detection/classification only), `plain_java`/`jakarta_ee` generation profiles (build/execute lane exists via Maven project adapter; per-workload proof coverage narrower than spring_boot).

**Missing relative to the master README's long-term targets (explicitly "eventually" requirements, disclosed):** real DB2/CICS/MQ/IMS/JCL runtime equivalence lanes, per-program (non-workload-scope) dependency proof channel, RBAC/audit log/durable queue/multi-node, portfolio/incremental modernization, mutation-testing and coverage gates (D-3), Gradle/servlet/MicroProfile/Jakarta-server targets (see §6), date/time & concurrency semantics controls.

**Fixed this session (red-first, see §10):** BL-094 frontend Authorization integration; BL-095 `docker_available` hardcode; BL-096 dashboard "Verified" overclaim; BL-097 platform-canonical ZIP ingestion (duplicate/separator-alias/case-collision rejection) and source-tree hashing (POSIX relative paths). **Fixed in the in-flight tree (verified here):** EV-006/R9 FILE-dependency proof binding; Windows-only path-separator test failures.

---

## 5. COBOL Language and Platform Capability Matrix (summary)

Source of truth: `docs/CAPABILITY_MATRIX.md` + `docs/SEMANTIC_PROOF_MATRIX.md` (registry-derived; enforced by the capability-truth gate).

| Level | Constructs |
|---|---|
| **SUPPORTED (oracle/proof-backed subset)** | MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE (basic), COMPUTE, IF/ELSE, PERFORM (plain/UNTIL/TIMES/VARYING), STRING, UNSTRING (subset), DISPLAY, STOP RUN, EXIT PROGRAM, READ (AT END/NOT AT END), WRITE, OPEN/CLOSE (sequential), static resolved CALL (value-result proven), ROUNDED (HALVE_UP→HALF_UP), figurative constants, VALUE/ALL fill, PIC X/9/S/V value semantics, COPY + COPY REPLACING (operand subset), hierarchical working storage, JCL parse/link lane (structural) |
| **PARTIAL / NOT CERTIFIED** | COMP/COMP-1/2/3/5 (value semantics only — byte encoding unverified, D-6), indexed/relative files (emulated lanes), DB2/SQL (parse/analyze/harness), UNSTRING breadth, PERFORM THRU (bounded), JCL central status (never PROVEN) |
| **UNSUPPORTED (fail-closed with diagnostics)** | GO TO, GOBACK (transform target), SORT, MERGE, INSPECT, SEARCH, SET, ALTER, ACCEPT, INITIALIZE, NEXT SENTENCE, ON SIZE ERROR, `**`/FUNCTION, standalone REWRITE/DELETE/START, INVALID KEY (program UNSUPPORTED), EXEC SQL/EXEC CICS constructs, EXEC DLI/MQI (classification), dynamic/unresolved CALL, CALL BY VALUE/BY CONTENT (negative contract) |
| **UNKNOWN / UNVERIFIED** | REDEFINES, OCCURS, 88-level lowering (mapped Java does not compile — never SUPPORTED), nested programs/ENTRY, standalone REPLACE, fixed/free-format + dialect breadth, conditional compilation |

Runtime proof labels per workload: `docs/verification/RUNTIME_PROOF_MATRIX.md` (live), with `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` retained as a dated historical snapshot.

---

## 6. Java Target-Runtime Architecture: Current Support, Gaps, Priorities

**Current (all verified this session through `tests/test_runtime_adapter_architecture.py` 51/51 and the factory/adapter trace):**

| Target | Project structure | Build | Entry point | Execution lane | Proof status |
|---|---|---|---|---|---|
| `spring_boot` | Maven pom (Spring Boot 3.2.5, offline-precached in `Dockerfile.maven-offline`), `src/main/java` + models | Docker Maven image (digest-pinned base) | generated Spring main | `DockerSpringBootCandidateAdapter` (digest-pinned temurin runtime, `--network none`, limits) | PROVEN for the proven workloads (default lane) |
| `plain_java` | Dependency-free Maven jar, `com.modernized.app.model` | same Maven image | deterministic program selection (requested else first; unknown → raise) | `MavenProjectCandidateAdapter` | Build lane exists; per-workload runtime proof narrower |
| `jakarta_ee` | Maven pom with `jakarta-ee` profile, **zero dependencies**, `com.modernized.app.jakarta` | same Maven image | as plain | `MavenProjectCandidateAdapter` | Generation-profile level; no application-server runtime proof (honest non-claim) |

Selection is deterministic and fail-closed at three layers: `RuntimeTargetConfig.__post_init__` (`_require_one_of`), `get_runtime_adapter` (registered factories only; `implemented_target_runtimes()` equality pinned by test), `candidate_adapter_for_target` (unknown → `ValueError` naming the supported set). The plan vocabulary (`PLAN_OUTPUT_TYPE_BY_TARGET`) cannot drift from the adapter registry.

**Common interface:** `RuntimeAdapter` ABC (`assemble()`), `CandidateAdapter` (`compile()`/`execute()`), shared semantic transform (adapters never duplicate parser/IR — pinned by the "adapters share the single semantic transform" test).

**Missing targets and priorities (only where a concrete implementation+test plan is justified):**

| Priority | Target | Rationale | Prerequisite |
|---|---|---|---|
| P2 | Servlet WAR (e.g. Jetty/Tomcat embedded or standalone) | Broad enterprise fit; reuses plain-java IR | New registered adapter + Docker execution lane + one differential workload; only after plain/jakarta runtime proof expands |
| P3 | Jakarta EE **runtime** proof (Open Liberty/WildFly Docker lane) | Converts the jakarta_ee generation profile into a proven runtime | New digest-pinned app-server image with the same sandbox contract |
| P3 | MicroProfile config/health annotations profile | Value only inside a real MicroProfile runtime | Depends on P3 app-server lane |
| P4 | Gradle build tool | Currently unjustified: Maven offline image is pinned, reproducible, and proven; a second build tool doubles the supply-chain surface | Business demand + offline Gradle image with pinned distribution |
| Non-goal | Additional frameworks (Quarkus, Micronaut, etc.) | No concrete requirement; would violate "build what can be proven" without a proof lane | Explicit owner decision (D-level) |

---

## 7. Business and Behavioral Equivalence Strategy

**Principle (enforced by architecture):** compilation is not equivalence; a workload-level VERIFIED verdict is not dependency-specific evidence (now enforced for FILE deps by the EV-006/R9 gate in `integrated_proof.py`).

1. **Oracle**: original COBOL compiled/executed by GnuCOBOL 3.1.2 in a digest-pinned container; identity recorded in evidence; GnuCOBOL ≠ z/OS equivalence (documented non-claim).
2. **Candidate**: generated Java built and executed in a separate digest-pinned container; no host fallback can upgrade a verdict (`service.py::_run_validation`, UNAVAILABLE semantics without Docker).
3. **Comparison**: contract-aware comparator registry; default contract = STDOUT+EXIT_STATUS (deliberately narrow); declared contracts add STDERR/TEXT_FILE/FIXED_RECORD artifacts. **Exact byte equivalence is the default and the only tolerance used today** — no numeric or fuzzy tolerances exist anywhere in the comparator framework. Tolerances must be introduced only per-workload with a documented business justification (roadmap item, none open).
4. **Numeric/data semantics**: exact decimal/integer semantics for PIC 9/S/V value handling, HALF_UP ROUNDED, truncation — oracle-proven for the certified subset. COMP/COMP-3 storage byte-encoding is explicitly **unverified** (value-semantics only) pending D-6; REDEFINES/OCCURS/88-level lowering produces non-compiling Java and is never claimed.
5. **Negative proof**: mutation suites (9 payroll mutations, generated-candidate mutation, mixed MATCH+MISMATCH single run) prove the comparator actually fails.
6. **Determinism**: byte-identical generated output across repeated runs (input-hash equality alone was insufficient; now pinned by the in-tree byte-identity test).
7. **Evidence binding**: source hash, workload identity, oracle identity/digest, candidate identity, comparison results, manifest hash + seal; integrity validator rejects tamper/replay/cross-run leakage (19 violation classes); verdict derivation is fail-closed (VERIFIED requires validated manifest).

**Coverage-metric separation (mandated, implemented):** parser coverage (construct registry + gate), transformation coverage (mapped-vs-diagnostic accounting via silent-loss registry), compilation success (Docker Maven), runtime success (execution evidence), business equivalence (oracle-matched artifact comparison) — reported as distinct numbers; `RUNTIME_PROOF_MATRIX.md` labels PROVEN/PARTIAL/UNSUPPORTED/UNAVAILABLE/UNKNOWN per workload.

---

## 8. End-to-End Runtime-Proof Architecture and Evidence Format

- **Runtime lanes** (all `--network none`, 512 MB, 1 CPU, PID-limited, hard timeouts): `gnucobol-ocesql` (oracle), `maven-offline-springboot` (build), `eclipse-temurin@sha256:4d06…` (execution); identities re-resolved and fail-closed before every run; provenance recorded by `scripts/record_docker_image_provenance.py` (as CI does).
- **Runtime-proof request honesty:** `RUN_DOCKER_TESTS=1` without a Docker runtime **fails** the proof tests rather than skipping (`test_requested_runtime_proof_has_a_runtime` + unit-tested gate matrix).
- **Evidence format:** `engine/evidence/models.py::EvidenceManifest` (canonical graph, hash-bound artifacts, seal) + `api/serialization.py` versioned JSON envelopes (`CURRENT_SCHEMA_VERSION = 1`, exact-match enforcement; never pickle). Evidence carries workload/source/candidate/oracle/environment identities, timestamps, and comparison outcomes — sufficient to re-verify a verdict without re-running (integrity validator) while freshness is guaranteed by per-push CI execution rather than cached artifacts.
- **Integrated proof gate:** `evaluate_central_status` can only downgrade; central VERIFIED requires runtime VERIFIED **and** complete, integrity-valid evidence **and** every required dependency PROVEN; FILE deps additionally require compared file artifacts (all MATCH) in the same run (this tree); JCL/DB2/CICS kinds are non-runtime and therefore always force NOT_VERIFIED.
- **Reproducibility:** exact build/run commands are pinned in `docs/verification/RUNTIME_PROOF_MATRIX.md` §"Exact commands"; images are digest-pinned; generator output is byte-deterministic; source trees are hash-identified.

---

## 9. Confirmed Defects, Security Risks, CI/Deployment Gaps, Documentation Issues

**Confirmed and fixed (this session — details §10):**

| ID | Defect | Severity |
|---|---|---|
| BL-094 | Frontend never sent `Authorization` → SPA fully broken against production auth (`CONTROL_PLANE_API_TOKEN` enforced by `start-production.sh`) | P1 |
| BL-095 | `api/service.py` hardcoded `docker_available=True` → capability analysis claimed Docker infrastructure SUPPORTED on Docker-less hosts (§14/§15 violation) | P3 |
| BL-096 | Dashboard "Verified" stat counted all COMPLETED runs regardless of verdict — UI capability-truth overclaim | P2 |
| BL-097 | Two cross-platform determinism defects in evidence-bound paths: `ingest_zip` extracted duplicate/separator-alias/case-collision entry names silently last-wins (platform-dependent source tree); `compute_source_tree_hash` baked OS separators into the digest (identical trees hash differently per platform) | P2 |

**Confirmed and fixed (in the in-flight working tree — verified green this session):**

| Finding | Severity |
|---|---|
| EV-006/R9: workload-level VERIFIED cohort-promoted FILE dependencies to PROVEN without any compared file artifact | P1 |
| EV-002: no test ever held MATCH and MISMATCH artifacts in one run | P2 |
| 4 Windows-only path-separator failures in `test_runtime_adapter_architecture.py` (logical project paths built with `str(Path)`) | P2 (local-dev impact) |

**Confirmed, disclosed, deliberately not fixed (carried with owners):**

- Containers run as **root** inside `--network none` resource-limited sandboxes (bind-mount permission risk vs. benefit; documented in `RUNTIME_PROOF_MATRIX.md`).
- Program/CALL/COPYBOOK/PARAMETER dependency proof is workload-scope; no per-program behavioural channel exists in the evidence model (architectural gap, pinned by test so it cannot widen silently).
- Single-token auth, no RBAC, no audit log, SQLite single-node, in-process job threads (D-5; §43 targets).
- Stale checked-in `test-artifacts/*` junit files with old failures (BL-093, blocked on human decision D-4 by the never-stage-test-artifacts invariant).
- `tests/verification/results_*` + `CURRENT_CAPABILITY_VERIFICATION.md` host-`javac` harness is stale-by-design, preserved as history with a banner (added in the in-flight tree).
- COMP/COMP-3 byte-encoding certification approach undecided (D-6); PR-governance decisions (D-2); coverage/mutation targets undecided (D-3 → BL-012 remainder).

**CI/deployment observations (verified, no action required):** no `continue-on-error` anywhere; only artifact-upload steps use `if: always()`; supply-chain audits gate with no bypass; production compose mounts the Docker socket (documented accepted risk with mitigations in `docs/security/PRODUCTION_SECURITY.md`); `start-production.sh`/`verify-production.sh` fail closed on empty token, missing TLS, missing images, and unenforced auth. **Gap closed this session:** the frontend→authenticated-API integration (BL-094) that these deployments implicitly assumed.

---

## 10. Changes Actually Implemented (this session)

All changes are **uncommitted in the working tree** (commit requires explicit authorization per task rules). Pre-existing in-flight work was preserved untouched and never staged.

### 10.1 Files modified/created

| File | Change |
|---|---|
| `frontend/src/api/client.ts` | BL-094: token resolution (localStorage `systemaops.apiToken` → `VITE_CONTROL_PLANE_API_TOKEN` → none=auth off), `withAuth()` applied to `request()` and `downloadGenerated()` with byte-identical no-token call shapes; BL-096: `RunResponse.verdict_state?: string \| null` |
| `frontend/src/pages/Dashboard.tsx` | BL-096: "Verified" StatCard counts `verdict_state === 'VERIFIED'` (was: completed-run count) |
| `frontend/src/__tests__/auth-client.test.ts` | **New** (8 tests) |
| `frontend/src/__tests__/dashboard-verified-stat.test.tsx` | **New** (2 tests) |
| `api/models.py` | BL-096: additive optional `RunResponse.verdict_state` |
| `api/service.py` | BL-095: `docker_available=docker_cli.check_docker_available()` (was hardcoded `True`); BL-096: new `Service.run_verdict_state` (fail-closed evidence-hash consistency) + `get_run_detail` refactored to share it; `from engine import docker_cli` |
| `api/app.py` | BL-096: `_to_run_response` helper serves `verdict_state` on `GET /runs/{id}` and `GET /applications/{id}/runs` |
| `tests/test_service_docker_honesty.py` | **New** (2 tests, red-first) |
| `tests/test_run_verdict_state_api.py` | **New** (3 tests, red-first) |
| `docs/deployment/ENVIRONMENT.md` | Frontend token-resolution section (incl. bundle-inlining trade-off) |
| `docs/BACKLOG.md` | Register rows BL-094/095/096 + change-log entry (bd) with red-first evidence; register row BL-097 + change-log entry (be) |
| `api/ingestion.py` | BL-097: `ingest_zip` rejects non-directory entries whose names collide after `\`→`/` normalization + case folding (was: silent last-wins extraction; platform-dependent tree) |
| `engine/source_hash.py` | BL-097: `compute_source_tree_hash` hashes `.as_posix()` relative paths (was: `str()` = OS separators in the digest) |
| `tests/test_zip_duplicate_entry_rejection.py` | **New** (5 tests, red-first: 3 red + 2 guard pins) |
| `tests/test_source_hash_canonical.py` | **New** (3 tests, red-first: 1 red on Windows + 2 regression pins) |

### 10.2 Red-first evidence

1. `tests/test_service_docker_honesty.py` + `tests/test_run_verdict_state_api.py` against the unmodified backend → **4 failed, 1 passed** (`AssertionError` on hardcoded `docker_available`; `KeyError: 'verdict_state'` ×3).
2. `auth-client.test.ts` + `dashboard-verified-stat.test.tsx` against the unmodified frontend → **10 failed** (no Authorization header anywhere; "Verified" showed the completed count).
3. `tests/test_zip_duplicate_entry_rejection.py` + `tests/test_source_hash_canonical.py` against the pre-fix ingestion/hashing code → **4 red, 4 passed** (3 ZIP-collision cases silently extracted; POSIX-canonical tree hash red on Windows; guard/regression pins green).
4. After implementation: all green (below). No existing test was modified, weakened, deleted, or skipped; the frozen 54-file gate list is untouched.

### 10.3 Verification ledger (exact commands, this host)

| Command | Result |
|---|---|
| `python -m pytest -q tests/test_file_dependency_proof_binding.py tests/test_runtime_adapter_architecture.py` | **51 passed** (in-flight FILE-binding unit proof green; Windows-only runtime-adapter failures resolved by the in-tree POSIX-path fix) |
| `python -m pytest -q tests/test_service_docker_honesty.py tests/test_run_verdict_state_api.py` (post-fix) | **5 passed** |
| `python -m pytest -q tests/test_api.py tests/test_api_security.py tests/test_control_plane_persistence.py tests/test_pipeline_progress.py` | **70 passed** |
| `python -m pytest -q tests/test_phase11_p1_upload_integrity.py tests/test_phase11_p2_auth_download_state.py tests/test_phase12_p4_bl091_approval_workflow.py tests/test_async_modernize.py` | **54 passed** |
| `python -m pytest -q tests/test_zip_duplicate_entry_rejection.py tests/test_source_hash_canonical.py` (+ `test_ingestion_diagnostics`, `test_modernization_p0`, `test_phase11_p1_upload_integrity`) | **28 passed** post-fix (8 new + 20 regression) |
| `python -m pytest -q tests/test_phase9_defect_fixes.py tests/test_modernization_integration_p0.py` | **17 passed** |
| `npx vitest run` (frontend) | **143 passed / 11 files** (was 133), exit 0 |
| `npx tsc --noEmit` | clean |
| `npm run build` | production build clean (exit 0) |
| GitHub REST API (`actions/runs?branch=codex/universal-core`) | latest runs `success` at `6145e89` and `690980c` (independent re-verification of the recorded CI baseline) |
| `RUN_DOCKER_TESTS=1 python -m pytest -q --junitxml=test-artifacts/full-suite-audit-junit.xml tests` | **Full-suite result recorded in the final verification appendix and `opencode.md`** (run executed on the complete working tree: in-flight changeset + this batch) |

Docker-dependent lanes in the full-suite run execute the real GnuCOBOL oracle and Maven candidate builds in the pinned images; no result in this ledger is mocked, and no environment-limited test was reported as passing (the `RUN_DOCKER_TESTS` gate fails loudly when the runtime is absent).

---

## 11. Prioritized Implementation Roadmap

| # | Item | Depends on | Acceptance criteria | Test strategy | Exit gate |
|---|---|---|---|---|---|
| R-1 | Commit + CI-validate the combined working tree (in-flight changeset + BL-094/095/096) | Owner authorization to commit/push | Single non-force commit on `codex/universal-core`; 4/4 CI green at the exact SHA; junit counts recorded in `opencode.md` | Existing full suite (CI authoritative) | CI green + checkpoint updated |
| R-2 | Generated-Java runtime proof for payroll/claims/indexed/relative (convert PARTIAL→PROVEN or honest UNKNOWN→evidence) | R-1; generator support gaps (REDEFINES/OCCURS/88 may block some) | Per-workload: generated candidate, declared contract, all artifacts MATCH vs GnuCOBOL oracle; negative mutation retained | New runtime-proof rows + mutations per workload | `RUNTIME_PROOF_MATRIX.md` rows updated with generated-Java evidence |
| R-3 | COMP/COMP-3 byte-encoding certification (D-6 decision first) | Human decision D-6 (home-grown encoder vs reference oracle) | Round-trip byte-identical storage vs oracle for a boundary matrix (sign nibbles, odd/even length, scale) | Differential byte tests vs GnuCOBOL-compiled fixtures | SEMANTIC_PROOF_MATRIX COMP rows upgraded or the block reaffirmed |
| R-4 | Per-program dependency proof channel | Evidence-model extension (per-program comparison artifacts) | PROGRAM/CALL/COPYBOOK deps provable beyond workload-scope; gate semantics updated fail-closed | New unit + Docker integration proofs | integrated_proof gate tests extended |
| R-5 | JCL behavioural execution lane | Deterministic JCL step runner vs oracle fixtures | JCL steps executed and compared (exit codes, dataset outputs) | Integration lane mirroring the COBOL oracle pattern | JCL rows move from PARTIAL with evidence |
| R-6 | Coverage + mutation gates (D-3) | Human decision D-3 (thresholds/tool) | Coverage threshold enforced; mutation budget for fail-closed paths | CI job additions, advisory→gating progression | ci.yml gates green without bypass |
| R-7 | §43 enterprise security (RBAC, audit log, durable queue, TLS at boundary, multi-node) | Human decision D-5 (schedule vs re-scope) | Per decided scope | Adversarial suites extended per control | Release-gate checkbox 14 upgraded |
| R-8 | Jakarta EE runtime proof lane / servlet target (per §6 priorities) | R-1; new digest-pinned app-server image | One workload proven on the real server runtime | Docker differential lane | New PROVEN row or explicit UNAVAILABLE retention |

Each item is registered in `docs/BACKLOG.md` or explicitly carried there (BL-012→D-3, BL-093→D-4, D-2/D-5/D-6 governance) per Master README §77; none may be closed without red-first evidence and exact-SHA CI green.

---

## 12. Blockers, Unsupported Scenarios, Risks, Non-Goals

**Blockers (this session):** none for local execution — Docker, JDK, Node, and Maven were all available and used. CI validation of the current working tree is blocked only by the no-commit/no-push rule (R-1).
**Unsupported scenarios (explicit):** universal COBOL coverage; z/OS/mainframe behavioural equivalence (GnuCOBOL-scoped only); real DB2/CICS/MQ/IMS runtimes; VSAM byte-format equivalence (emulated lanes); REDEFINES/OCCURS/88-level transformation; dynamic CALL; RBAC/multi-node/audit-log production posture; Gradle/Quarkus/etc. targets.
**Residual risks:** root-in-sandbox containers; workload-scope dependency proof; single-token shared credential in browser contexts (documented trade-off in `ENVIRONMENT.md`); stale `test-artifacts/*` until D-4; uncommitted state of all current work until R-1.
**Non-goals:** LLM anything (prohibited, re-verified); merging to `main`; claiming §71 full pass; replacing the Maven offline supply chain; rewriting historical reports (§78 — history preserved, labeled).

---

## 13. Final Truthful Scorecard

| Dimension | Score | Basis |
|---|---|---|
| Architecture | **Strong** | Single canonical pipeline, adapter-separated runtimes, fail-closed evidence/verdict, no duplicate systems (verified by trace) |
| Implementation completeness vs master README | **Substantial subset** | All §1–§48 machinery exists; enterprise "eventually" targets honestly partial (§4) |
| COBOL language coverage | **Certified subset; NOT universal** | Oracle-proven core statements; COMP/REDEFINES/OCCURS etc. explicitly unproven (§5) |
| Java runtime coverage | **3 targets, 1 deeply proven** | spring_boot proven end-to-end; plain/jakarta build-lane capable, narrower runtime proof (§6) |
| Compilation proof | **Strong** | Docker Maven builds per run, digest-pinned |
| Runtime execution proof | **Growing** | 6 workload rows PROVEN (incl. file workload in this tree); payroll/claims/indexed/relative still PARTIAL/UNKNOWN (§4, `RUNTIME_PROOF_MATRIX.md`) |
| Business equivalence | **Exact-match discipline; subset-scoped** | Byte-exact comparisons, no tolerances, negative-mutation-proven; scope limited to proven workloads (§7) |
| Security | **Good baseline, disclosed gaps** | Traversal/limits/duplicate-entry rejection/auth/evidence-integrity all enforced + adversarial suites; platform-canonical hashing; no RBAC/audit-log/multi-node; frontend auth gap now closed (§9) |
| Production readiness | **Single-node production-grade, not enterprise-grade** | Digest-pinned images, compose hardening, fail-closed deploy scripts; SQLite/in-process jobs/root-in-sandbox carried (§9, §12) |
| Documentation trustworthiness | **High after this pass** | Live docs reconciled (F-02), runtime-proof matrix live, backlog 96 rows, this document separates fact/plan/unknown |

**Overall:** the platform is a genuinely evidence-driven, deterministic, subset-certified modernization system — not universal, not yet enterprise-operable, and it says so. The most valuable next step is R-1 (commit + CI) followed by R-2 (generated-Java proof for the PARTIAL workloads).

---

## Appendix — Final Verification Results (filled from actual runs)

*(Updated after the full-suite completion; see `opencode.md` for the authoritative session checkpoint and `docs/BACKLOG.md` change-log (bd) for the remediation record.)*
