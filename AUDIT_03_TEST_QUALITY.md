# AUDIT_03_TEST_QUALITY

## 1. Test suite scale

- Collection: 4550 tests (`python -m pytest --collect-only -q`).
- Backend CI run (exact SHA c2725e63, run 41030405967): 4549 passed, 1 failed, 3 warnings in 1284.62s.
- Capability truth gate (run 41030405967): 850 passed, 1 deselected.
- Phase 1 ingestion diagnostics: 3 passed.
- Frontend: 16 test files, 172 tests passed (CI run 41030405967).

## 2. CI-blocking test defect

- `tests/transformation/test_phase7c_end_to_end.py::TestBuildAndExecution::test_docker_status_recorded` (lines 1604-1631) unconditionally asserted `status == "BLOCKED / NOT VERIFIED"` at line 1629 while computing `status = "VERIFIED" if (gate and runtime_available)` at line 1627. Environment-dependent: passes locally (gate off), fails in CI (gate on + temurin image present). See C-1 in AUDIT_01. **Fixed** this session; verified passing in both environments.

## 3. Previously reported issues — status

### Backend root-suite WSL `bash.exe` failure
- Documented in `WSL_CI_FAILURE_ROOT_CAUSE.md`: `tests/test_ci_deployment_security.py::TestVerifyProductionPropagatesProbeFailure::test_fixed_idiom_propagates_grep_status` fails on Windows because `bash` resolves to the WSL launcher shim, which does not preserve GNU Bash `$?` semantics. On Linux CI, `bash` is GNU Bash and the test passes. Root cause: environment/launcher, not a security regression. Recommended: keep test unchanged for Linux CI; use `wsl.exe -e bash` locally. No source fix required. Classification: ENVIRONMENT LIMITATION (local Windows only).

### Docker integration failures
- CI backend run executes full suite with `RUN_DOCKER_TESTS=1` and builds/pulls Docker images. The only failure at c2725e63 was C-1 (above). Other Docker integration tests (relative/indexed semantics, file write/read proof, Docker Java) pass in CI (4549 passed). Local Windows Docker availability varies; tests that require Docker are gated by `RUN_DOCKER_TESTS`.

### OCESQL image RepoDigest / provenance issue
- CI builds `gnucobol-ocesql:latest` from `Dockerfile.gnucobol` (`docker build --pull`) and records provenance via `scripts/record_docker_image_provenance.py`. The prior report flagged missing RepoDigest for the OCESQL image. The CI step "Pull pinned Java execution image" uses a digest-pinned runtime image (`DockerSpringBootConfig().runtime_digest`) and tags it `eclipse-temurin:21-jdk`. The gnucobol image is built locally (no digest pin). Pending security/CI audit for whether this is a blocker. Status: requires further validation (owner-dependent for image signing).

### Frontend test process exit discrepancy
- CI frontend job: 16 test files, 172 tests passed. Frontend uses Vitest. The prior report mentioned a process exit discrepancy; not reproduced in CI. Local run may differ due to environment. Status: NOT REPRODUCED in CI.

### L.6.1 candidate-count reconciliation
- Prior report `L6_1_CANDIDATE_RECONCILIATION.md`. Not re-evaluated in this pass beyond collection count (4550). Status: PARTIALLY VERIFIED (counts reconcile to 4550 collected).

## 4. Test quality assessment

- Tests generally execute real production code (parser, IR, mapping, generation, Docker, API).
- Negative cases present: unsupported construct rejection, zip-slip, symlink, zip-bomb, approval gating, seal verification.
- Boundary cases: numeric semantics, PIC widths, fixed-record trailing partial.
- Generated Java compilation tested via Docker Maven image in CI.
- COBOL/Java differential tests present (numeric oracle proof, indexed/relative semantics).
- Mocks: `engine/candidate/docker_java_adapter.py` and `engine/execution/docker_runner.py` are real subprocess/Docker, not mocks, on production paths. `tests/execution/test_candidate.py` and `test_oracle.py` pin that placeholders never fabricate results.
- Skipped tests: gated by `RUN_DOCKER_TESTS` (documented, legitimate environment gating). No evidence of tests converted to skipped to obtain green.
- Tests that assert only existence: `tests/transformation/test_parser.py:244` (`assert program.paragraphs is not None`), `tests/transformation/test_ir.py:181` (`assert stmt is not None`), and several count-based assertions. These cannot catch partial parsing (P-15). Severity P3 (test gap).
- Flakiness/environment-dependence: WSL bash test (local Windows only); `test_docker_status_recorded` (fixed this session).

## 5. Baseline full-suite run

- In progress (PID 25332). Result to be recorded in `VALIDATION_08_FINAL_REGRESSION.md`.
- Command: `python -m pytest -q --junitxml=C:\Users\bandi\AppData\Local\Temp\opencode\baseline-full.xml`.
- Working directory: repo root. Environment: Windows, no RUN_DOCKER_TESTS (default).

## 6. Verdict

- CI at starting SHA: 1 failure (C-1), now fixed.
- All other reported issues: either environment-specific (WSL bash), not reproduced (frontend exit), or require owner-dependent validation (OCESQL digest).
- Test quality: generally strong; main gaps are existence-only assertions and environment-dependent tests.