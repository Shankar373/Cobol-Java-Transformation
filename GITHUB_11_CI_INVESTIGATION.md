# GITHUB_11_CI_INVESTIGATION

## Pushed SHA

Final SHA: `9c8985858a448bd80bb606b3d3034c53e5a8edf7` on branch `codex/universal-core`.

## Workflow runs

| Run ID | Workflow | Status | Conclusion | SHA |
|---|---|---|---|---|
| 41112271828 | SystemaOps CI | completed | **success** | 9c89858... |
| 41112271736 | Supply chain (SBOM + vulnerability scanning) | completed | **success** | 9c89858... |

## SystemaOps CI jobs (run 41112271828)

| Job | Status | Conclusion |
|---|---|---|
| Capability truth gate | completed | success |
| Phase 1 ingestion diagnostics | completed | success |
| Frontend tests, TypeScript, and production build | completed | success |
| Backend and COBOL/Java Docker tests | completed | **success** |

## Investigation history

### Initial CI failure at starting SHA c2725e63 (run 41030405967)
- Single failure: `tests/transformation/test_phase7c_end_to_end.py::TestBuildAndExecution::test_docker_status_recorded` — AssertionError: assert 'VERIFIED' == 'BLOCKED / NOT VERIFIED'.
- Root cause: test unconditionally asserted `status == "BLOCKED / NOT VERIFIED"` while computing `status = "VERIFIED" if (gate and runtime_available)`. In CI, RUN_DOCKER_TESTS=1 and eclipse-temurin image present → status="VERIFIED". Fixed by making assertion conditional on gate.

### Intermediate CI failure (run 41064932501, SHA 103ebbd)
- 20+ failures: oracle image 'gnucobol-ocesql:latest' has no immutable digest identity. Caused by my Dk-6 fix requiring RepoDigest for oracle (locally-built image has only Image ID). Reverted.

### Intermediate CI failure (run 41072864949, SHA bd8dfd6)
- Claims batch failures: oracle exit code 1. Caused by CLAIMS.cob multi-line PERFORM UNTIL not compiling in fixed format (missing period after END-READ, and single-line too long). Fixed by adding period and keeping multi-line layout (fits 72 cols).

### Final result
- All 4 jobs pass. CI is green for SHA 9c89858.

## Conclusion
CI investigation complete. All workflows pass for the final pushed SHA. No remaining CI failures.