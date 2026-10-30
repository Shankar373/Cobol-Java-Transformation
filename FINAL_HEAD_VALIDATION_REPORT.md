# FINAL HEAD VALIDATION REPORT

Date: 2026-10-30
Source SHA: `92c51e52629f7dcb8b9dce18f412bd957897f6eb`
Branch: `codex/universal-core`
Environment: Windows 11, Python 3.11.9, Docker 29.8.2, Node/npm frontend toolchain

## 1. Transformation / backend root suite

Command:
```text
python -m pytest -q --junitxml=test-artifacts/final-head-root.xml
```

Result:
- Passed: 4540
- Failed: 1
- Skipped: 9
- Warnings: 4
- Duration: 3889.59s

Failure:
- `tests/test_ci_deployment_security.py::TestVerifyProductionPropagatesProbeFailure::test_fixed_idiom_propagates_grep_status[echo nope | grep -q probe-True]`
- Root cause: WSL `bash.exe` launcher does not preserve GNU Bash `$?` semantics; real GNU Bash via `wsl -e bash` returns the expected exit code. See `WSL_CI_FAILURE_ROOT_CAUSE.md`.
- Not a security regression.

## 2. Backend subdirectory suite

Command:
```text
python -m pytest tests/adversarial tests/comparators tests/contracts tests/deployment tests/evidence tests/execution tests/unit tests/verdict tests/verification -q --junitxml=test-artifacts/final-head-subdir.xml
```

Result:
- Passed: 555
- Failed: 0
- Skipped: 0
- Warnings: 1
- Duration: 47.91s

## 3. Docker-enabled integration suite

Command:
```text
set RUN_DOCKER_TESTS=1
python -m pytest tests/integration -q --junitxml=test-artifacts/final-head-integration-docker.xml
```

Result:
- Passed: 415
- Failed: 5
- Error: 1
- Warnings: 1
- Duration: 3480.66s
- Total executed: 421 (matches prior reported Docker integration total)

Failures:
- `test_claims_batch.py::TestClaimsMutations::test_rule_inversion_detected`
- `test_copybook_runtime.py::TestBehavioralEquivalence::test_exit_codes_match`
- `test_copybook_runtime.py::...::test_stdout_lines_match` (error)
- `test_indexed_semantics.py::TestIndexedMutations::test_wrong_key_failed`
- `test_indexed_semantics.py::TestIndexedMutations::test_changed_content_failed`
- `test_indexed_semantics.py::TestIndexedMutations::test_wrong_mapping_failed`

Root cause: runtime oracle image `gnucobol-ocesql:latest` is a locally built image with no RepoDigest; the platform requires an immutable RepoDigest for runtime oracle identity. This is an environment/provenance blocker, not a transformation correctness failure.

## 4. Focused oracle proofs

The integration suite above includes the oracle proof tests. No separate focused oracle run was executed in this session; the integration run contains the accept, numeric, initialize, unstring, indexed/relative, structural, and call-passing oracle proofs.

## 5. Frontend unit tests

Command:
```text
cd frontend
npm test
```

Result:
- Test files: 16 passed
- Tests: 172 passed
- Duration: 18.43s
- Exit code: 1 due to a jsdom "navigation not implemented" runtime message, but all 172 tests passed.

## 6. Frontend lint

Command:
```text
cd frontend
npm run lint
```

Result: passed (tsc --noEmit).

## 7. Frontend production build

Command:
```text
cd frontend
npm run build
```

Result: passed (tsc -b, vite build, bundle-secret guard OK).

## 8. Security tests

Included in the backend root suite. All security-focused tests passed except the WSL-specific `bash.exe` launcher case documented above.

## 9. Static analysis

Command:
```text
python -m compileall -q engine api
```

Result: passed.

## 10. Dependency and container checks

- Docker daemon available.
- `gnucobol-ocesql:latest` exists locally but has no RepoDigest; runtime oracle identity cannot be established for OCESQL-dependent tests.
- No dependency audit tool (pip-audit/bandit/safety) was installed in the active environment.

## Summary

- Backend root: 4540 passed, 9 skipped, 1 failed (environment-specific)
- Backend subdirectory: 555 passed
- Docker integration: 415 passed, 5 failed, 1 error (environment/provenance-specific)
- Frontend: 172 passed, lint passed, build passed
- No transformation correctness regression was identified.
