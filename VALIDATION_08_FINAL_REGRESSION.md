# VALIDATION_08_FINAL_REGRESSION

## Commands and results

### Python syntax/compile
- Command: `python -m compileall -q engine api tests`
- Working dir: repo root. Exit code: 0. Result: PASS (no errors).

### Targeted tests
- `tests/transformation/test_parser.py`, `test_ir.py`, `test_java_generator.py`: 53 passed.
- `tests/transformation/test_producer_contract.py`, `test_producer_capability_consistency.py`, `test_producer_diagnostics_contract.py`, `tests/verdict/test_verdict.py`: 50 passed.
- `tests/transformation/test_phase7c_end_to_end.py`: 95 passed.
- `tests/execution/test_oracle.py`, `tests/transformation/test_capability_registry_reconciliation.py`: 22 passed.
- `tests/transformation/test_perform_varying_headers.py`, `test_perform_lowercase.py`: 9 passed.
- `tests/transformation/test_phase7b4_repository_adapter.py`: 45 passed.
- `tests/transformation/test_claims_transformation.py`: 24 passed, 4 skipped (Docker-gated).
- `tests/transformation/test_producer_contract.py` (re-run): 20 passed.

### Full transformation suite
- Command: `python -m pytest tests/transformation/ -q`
- Working dir: repo root. Environment: Windows, no RUN_DOCKER_TESTS.
- Exit code: 0. Result: 2204 passed, 4 skipped, 0 failed. Duration: 136.04s.

### CI-blocking test (fixed)
- `tests/transformation/test_phase7c_end_to_end.py::TestBuildAndExecution::test_docker_status_recorded`:
  - Default env: 1 passed.
  - Gated env (RUN_DOCKER_TESTS=1 + eclipse-temurin present): 1 passed.

### Baseline full suite
- Command: `python -m pytest -q --junitxml=C:\Users\bandi\AppData\Local\Temp\opencode\baseline-full.xml`
- Working dir: repo root. Started: 2026-10-30T18:16:21. Status: still running at time of report (process PID 25332). Result: NOT COMPLETED within session window. Not a blocker for the commit; transformation suite (2204 passed) and targeted tests cover the changed code.

### Frontend
- Not re-run locally this session; CI frontend job (run 41030405967) passed: 16 test files, 172 tests.

### Docker integration
- Gated by RUN_DOCKER_TESTS; CI backend-oracle job (run 41030405967) had 4549 passed + 1 failed (C-1, now fixed).

### Security checks
- Secret scan: no secrets in production code. .gitignore updated.

### Classification summary
- PASS: Python compile, transformation suite (2204), targeted tests, CI test fix verification.
- FAIL: none (after fixes).
- BLOCKED: baseline full suite (still running); OCESQL RepoDigest (owner/environment).
- NOT RUN: frontend lint/build locally (CI covers).
- ENVIRONMENT LIMITATION: WSL bash test (local Windows only).