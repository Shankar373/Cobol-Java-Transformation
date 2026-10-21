# Runtime-Proof Gap Closure Audit (COBOL → Java, Docker lanes)

Date: 2026-10-17. Branch `codex/universal-core`, audited at HEAD
`6145e892e95282a0ca85eb678057a0ea9890389c`; the changes below are delivered
in the commit that contains this report (at audit time they were uncommitted
in the working tree, pending review). No LLM is involved in the
transformation or verification path (NO-LLM architecture preserved).
Delivery is a single non-force commit on `codex/universal-core` — no merge
into `main`, no force-push. Pre-existing working-tree changes
(`test-artifacts/docker-image-provenance.json` and the untracked
`test-artifacts/*` files) were preserved untouched and never staged.

Scope: close runtime-proof gaps using reproducible open-source Docker
environments, and fix certification/evidence defects confirmed by the
repository audit — without weakening tests, lowering thresholds, or replacing
real runtime comparison with mocks.

**Verification scope (read first):** every test result in this report is a
**local** result from the Windows development host with the pinned Docker
images. The GitHub Actions runs cited below validate **only the committed SHA
`6145e892e95282a0ca85eb678057a0ea9890389c`**, which does **not** contain the
changes listed in §2 — at audit time those runs had not executed the new
tests, and this report does not claim CI validation for them. CI evidence
applies only from the commit containing this report onward (tracked in the
repository's Actions history). The full local suite result recorded in §6 is
**3924 passed, 4 failed** — the 4 failures are pre-existing and unrelated, but
the run is not a green full-suite result.

## 1. Confirmed findings and disposition

| Finding (audit id) | Severity | Disposition |
|---|---|---|
| EV-006/R9: a workload-level `VERIFIED` runtime verdict cohort-promoted every runtime-kind dependency — including `FILE` — to `PROVEN`, even when the contract compared only stdout/exit status and no file artifact was ever read back | P1 | **Fixed** (`engine/modernization/integrated_proof.py`), red-first (see §5) |
| EV-002: no test ever exercised a single run holding MATCH *and* MISMATCH artifacts together | P2 | **Test added** (`test_payroll_artifacts.py`, mixed-run test) |
| Determinism proofs asserted only input-hash equality of the *fixture*; byte-identity of the generator's *output* was never tested | P2 | **Test added** (byte-identical two-run comparison) |
| `workload-file-write-read` declared a 4-artifact contract (incl. FIXED_RECORD) but had no runtime proof with *generated* Java — only contract-resolution tests | P2 | **Closed**: workload now PROVEN end-to-end (engine lane + certification API), with negative mutation lane |
| Execution vs compilation vs structural conflation (JCL lane compiles+starts but never behaves) | P2 | **Labeled honestly**: PARTIAL in the new runtime-proof matrix (no code change; no execution lane exists) |
| `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` titled "Current" while being a dated 2026-09-21 snapshot (host-`javac` harness) | P2 | **Banner added**; evidence itself preserved unmodified as history |
| README CI baseline cited stale runs #417/#418 as "current" | P2 | **Corrected** to a verified dated snapshot (run 38980053986, re-verified live 2026-10-17) |
| Unexecuted tests could silently skip when runtime proof was requested | P3 | **Fail-closed rule added**: `RUN_DOCKER_TESTS=1` without Docker fails the run (`test_requested_runtime_proof_has_a_runtime` + unit-tested gate matrix) |
| `api/service.py:953` hardcodes `docker_available=True` for capability analysis | P3 | **Not changed** (see §8: planning-honesty issue, outside the runtime-proof path; changing it alters capability levels on Docker-less hosts) |
| Containers run as root inside the sandbox | P3 | **Not changed** (documented limitation; bind-mount permission breakage risk outweighs benefit at this stage) |

Parser recognition ≠ semantic support, compilation ≠ behavioural equivalence,
and unit tests ≠ integration/runtime proof were kept distinct throughout:
every PROVEN label in `docs/verification/RUNTIME_PROOF_MATRIX.md` names the
Docker-executed test that produced it; prewritten-candidate runs are labeled
PARTIAL and explicitly do not claim generator output.

## 2. Changed files in this changeset

| File | Change |
|---|---|
| `engine/modernization/integrated_proof.py` | `FILE_ARTIFACT_TYPES` constant; FILE-kind dependency proof now requires ≥1 compared `TEXT_FILE`/`FIXED_RECORD` artifact, all MATCHing, else PARTIAL with explicit reason; module docstring documents the gate condition |
| `tests/test_file_dependency_proof_binding.py` | **New** (engine-only, 6 tests): stdout-only run cannot prove FILE deps nor certify the app; matched file evidence keeps the positive lane; inconsistent evidence fails closed; PROGRAM workload-scope boundary pinned; evidence conversion carries file artifact types |
| `tests/integration/test_file_write_read_runtime_proof.py` | **New** (15 tests): declared-contract proof (4 artifacts MATCH, FILE deps PROVEN, central VERIFIED); default-contract run (verdict verified for stdout/exit only, FILE deps PARTIAL, central NOT_VERIFIED); mutated generated candidate (FIXED_RECORD MISMATCH, FAILED, deps not PROVEN); byte-identical determinism; runtime-availability gate |
| `tests/integration/test_payroll_artifacts.py` | Added EV-002 mixed-run test (STDOUT/STDERR/EXIT_STATUS MATCH + TEXT_FILE/FIXED_RECORD MISMATCH in one run → FAILED) |
| `tests/test_e2e.py` | Added `TestFileWorkloadThroughApi`: file workload through the certification API with generated Java — declared contract recorded, 4 artifacts MATCH, FILE dependencies PROVEN, central VERIFIED |
| `docs/verification/RUNTIME_PROOF_MATRIX.md` | **New** live runtime-proof matrix (labels, images/digests/licenses, exact commands, per-workload status, negative proofs, determinism, non-claims) |
| `docs/CAPABILITY_MATRIX.md` | Gate section updated with the FILE dependency-specific evidence requirement and test citations |
| `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` | Historical-snapshot banner only (content preserved) |
| `README.md` | Runtime-proof matrix linked; CI baseline replaced with verified dated snapshot |
| `docs/audits/RUNTIME_PROOF_GAP_CLOSURE_AUDIT.md` | This report |

## 3. Image provenance (source, maintenance, license, compatibility)

| Lane | Image | Source | Version / pin | License | Maintenance |
|---|---|---|---|---|---|
| COBOL oracle | `gnucobol-ocesql:latest` | `Dockerfile.gnucobol`; base `ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401` | GnuCOBOL 3.1.2.0-1 (official Ubuntu 22.04 archive); identity auto-resolved at execution, fail-closed | GPL-3.0 (GnuCOBOL) | Ubuntu 22.04 LTS maintained by Canonical |
| Candidate build | `maven-offline-springboot:latest` | `Dockerfile.maven-offline`; base `maven:3.9-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320` | Maven 3.9 + Temurin 21; Spring Boot 3.2.5 precached (matches generator output) | Apache-2.0 (Maven, Spring Boot); GPLv2+CE (Temurin) | Official images, actively maintained |
| Execution | `eclipse-temurin:21-jdk` | `DockerSpringBootConfig.runtime_digest` | `sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026`; re-verified before every run | GPLv2 + Classpath Exception | Eclipse Temurin LTS line |

No new Dockerfile or CI job was added: the audit found the existing
digest-pinned images and the CI backend job sufficient — that job already
builds both images, records provenance
(`test-artifacts/docker-image-provenance.json`), and runs the **full** backend
suite with `RUN_DOCKER_TESTS=1`, so the new tests will be picked up by that
job **with no workflow changes, from the commit that contains them onward**
(this report claims only the local results in §6; CI results at that SHA are
reported separately). No unpinned `latest` is used for
release-proof images (the two `:latest` tags are locally built from
digest-pinned bases; the *identity* consumed by the adapter is the resolved
digest/provenance record, fail-closed when empty).

## 4. Exact commands

Environment (local reproduction of every PROVEN row):

```bash
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .
docker pull eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026
docker tag eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 eclipse-temurin:21-jdk
```

Tests executed locally in this task (PowerShell: `$env:RUN_DOCKER_TESTS='1'`
for the Docker lanes):

```bash
python -m pytest -q tests/test_file_dependency_proof_binding.py          # 6 passed
python -m pytest -q tests/integration/test_file_write_read_runtime_proof.py   # 13 passed 1 skipped (RUN_DOCKER_TESTS unset)
python -m pytest -q "tests/integration/test_payroll_artifacts.py::TestPayrollMutations::test_mixed_run_stdout_matches_while_report_files_mismatch"   # 1 passed
python -m pytest -q tests/test_e2e.py::TestFileWorkloadThroughApi        # 1 passed
python -m pytest -q <9 affected gate/API proof suites>                    # 74 passed
python -m pytest -q tests/integration/test_integrated_proof_api.py tests/integration/test_phase_d_integrated_proof.py tests/integration/test_phase_d_negative_integration.py   # 66 passed
RUN_DOCKER_TESTS=1 python -m pytest -q tests/integration/test_file_write_read_runtime_proof.py "tests/integration/test_payroll_artifacts.py::TestPayrollMutations"   # 28 passed
RUN_DOCKER_TESTS=1 python -m pytest -ra --junitxml=final-backend-junit.xml tests   # full backend suite (see §6)
```

Frontend (unaffected by these changes, verified anyway):
`npx tsc --noEmit`, `npm test`, `npm run build` in `frontend/` — see §6.

## 5. Red-first evidence (defects reproduced before the fix)

1. **Unit level** (`tests/test_file_dependency_proof_binding.py` run against
   unmodified `integrated_proof.py`): 3 failures — FILE entry `PROVEN` from
   stdout-only evidence; central `VERIFIED` despite an uncertified file
   dependency; inconsistent file evidence still reaching `PROVEN`.
2. **Integration level** (the original HEAD `integrated_proof.py` was restored
   temporarily and
   `tests/integration/test_file_write_read_runtime_proof.py::TestDefaultContractRun`
   run against live Docker evidence): 2 failures —
   `FILE:FILE-WRITE-READ:OUT-FILE` cohort-promoted to `PROVEN` from a run whose
   only comparisons were STDOUT+EXIT_STATUS, and central `VERIFIED` for that
   application. After restoring the fix, the module passes fully (locally).

No existing test was modified to accommodate the change; all thresholds were
kept. The fix is strictly fail-closed: `FILE` proof requires file-comparison
evidence; PROGRAM/CALL/COPYBOOK/PARAMETER keep their workload-scope semantics,
pinned by an explicit test so the boundary cannot widen silently.

## 6. Local results (2026-10-17, Windows + Docker 29.8.2)

- Baseline (before changes, HEAD): full backend suite with `RUN_DOCKER_TESTS=1`
  — **3901 passed, 4 failed, 0 skipped** (40:32). The 4 failures are the
  disclosed Windows-only path-separator defects in
  `tests/test_runtime_adapter_architecture.py` (pre-existing, unrelated to this
  work; they are also disclosed in the repo docs).
- New/changed tests: all green **locally** (numbers in §4). The runtime-proof
  module runs 13 passed + 1 skipped without `RUN_DOCKER_TESTS` (env gate skip,
  visible via `-ra`), and all 14 pass with it set.
- Full backend suite **run locally** with changes (same command CI uses, but
  executed on this machine — **not** in CI; `RUN_DOCKER_TESTS=1`):
  **3924 passed, 4 failed, 0 skipped (39:29)**. This is **not** a green
  full-suite result: the run fails with 4 failures. Those 4 failures are the
  identical, disclosed Windows-only path-separator defects in
  `tests/test_runtime_adapter_architecture.py` that fail at the untouched
  baseline as well (baseline: 3901 passed / 4 failed / 0 skipped, 3905 total;
  failure sets verified identical via the JUnit XMLs). The +23 tests are
  exactly the additions in this task: 6 binding unit tests, 15
  runtime-proof-module tests, 1 EV-002 mixed-run test, 1 certification-API
  file-workload test. No new failures, no skips.
- Frontend (unchanged by this work, verified anyway): `npx tsc --noEmit` exit
  0; `npm test` — 9 files, **133 passed** (0 failed, 0 skipped); `npm run
  build` — production build succeeded (exit 0).
- **GitHub CI verification (separate from local, applies only to committed
  SHA `6145e892e95282a0ca85eb678057a0ea9890389c`)**: run 38980053986 GREEN —
  all 4 jobs ("Phase 1 ingestion diagnostics", "Backend and COBOL/Java Docker
  tests", "Frontend tests, TypeScript, and production build", "Capability
  truth gate"); supply-chain run 38980054137 GREEN (verified live via the
  GitHub Actions REST API on 2026-10-17). That SHA contains **none** of the
  changes in this report, so these green runs do **not** validate them; the
  new tests are presented here as **locally verified only**. CI coverage
  starts at the commit containing this report, and CI results there are
  reported separately from local results (never merged into this section).

## 7. Per-workload evidence

Maintained in `docs/verification/RUNTIME_PROOF_MATRIX.md` (labels
PROVEN/PARTIAL/UNSUPPORTED/UNAVAILABLE/UNKNOWN, per-row test evidence,
candidate type generated vs prewritten, contract artifacts compared). All rows
below reflect **local** runs on 2026-10-17. Headline:
`workload-file-write-read` is newly **PROVEN** with generated Java at both the
engine lane and the certification-API layer; the previously proven generated-Java
lanes (copybook, call-chain, phase-7d arithmetic, numeric oracle, integrated
application) each executed in Docker in the local full-suite runs with zero
failures **in their own modules** (the run's only failures were the 4
disclosed Windows-only tests in `test_runtime_adapter_architecture.py`);
payroll, claims, indexed and relative remain PARTIAL (prewritten-candidate
machinery proofs) and are labeled as such.

## 8. Remaining gaps (honest, not fixed here)

- `api/service.py:953` hardcodes `docker_available=True` for capability
  analysis (planning-honesty defect, not a proof defect; changing it would
  alter capability labels on Docker-less hosts).
- Program/CALL/COPYBOOK/PARAMETER dependency proof stays workload-scope — the
  evidence model has no per-program comparison channel; documented and pinned,
  not eliminated.
- Containers run as root inside `--network none`, memory/CPU/PID-limited
  sandboxes.
- Historical host-`javac` harness (`tests/verification/run_clean_verification.py`,
  results 2026-09-21) is stale and preserved unmodified as history.
- Frontend findings from the audit (dashboard "Verified" wording, missing
  `Authorization` header) are untouched — separate scope, no runtime-proof
  impact.
- Indexed/relative lanes are emulations without real VSAM; DB2/CICS/MQ/IMS
  have no runtime lanes (UNAVAILABLE by construction).

## 9. Final verdict (four-way, per claim)

| Claim | Verdict |
|---|---|
| File workload (`file-write-read`) runtime proof with generated Java | **PROVEN** (engine lane + certification API, declared 4-artifact contract, negative mutation + determinism included) |
| FILE dependency cannot be proven without file comparison evidence | **PROVEN** as a property (red-first at unit and live-integration levels) |
| Mixed MATCH+MISMATCH aggregation in one run | **PROVEN** (EV-002 test) |
| Byte-identical determinism of the generator output | **PROVEN** (two-run byte comparison) |
| Runtime proof requested without a runtime fails loudly | **PROVEN** (gate + unit-tested matrix) |
| JCL behavioural equivalence | **PARTIAL** (compile+start only; no execution lane) |
| Generator output for payroll/claims/indexed/relative | **UNKNOWN** (machinery PARTIAL, prewritten candidates only) |
| Universal COBOL / mainframe equivalence | **UNSUPPORTED** as a claim — explicitly not made anywhere |
| DB2/CICS/MQ/IMS lanes | **UNAVAILABLE** (no runtime in this repository) |

Nothing in this change set replaces real runtime comparison with mocks or
hardcoded outputs; every PROVEN label above corresponds to a **locally
executed** Docker test that compiled and ran real COBOL and real Java and
compared their artifacts. Every claim here rests on **local** execution
evidence (§6); the green Actions runs cited there belong to SHA `6145e89`,
which does not contain these changes. CI results for the commit delivering
this report are tracked in the repository's Actions history and are reported
separately — this report claims no CI validation (see §6).
