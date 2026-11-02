# MASTER_REMEDIATION_REGISTER

> **ARCHIVED (architecture audit, 2026-11-03):** a dated report kept for history only - moved here from the repository root. It describes the repository at its own recorded date and is not a current status claim. Current status: `README.md`, `docs/CAPABILITY_MATRIX.md`, `docs/reports/PHASE5_FINAL_CERTIFICATION.md`, `docs/reports/PHASE5_RELEASE_READINESS.md`.

- Report date: 2026-10-31
- Branch: codex/universal-core

## This execution
| ID | Severity | File | Status | Evidence |
|---|---|---|---|---|
| A-2 | P2 | api/service.py | Fixed | tests/test_api_security.py::test_uploaded_candidate_disabled_in_production (1 passed) |
| P-4 | P3 | engine/transformation/cobol_parser.py | Fixed | dead pass removed; syntax check ok |
| J-9 | P1 | engine/verdict/derivation.py | Fixed | changed unavailable detection to any(); tests/verdict/test_j9_mixed_states.py (5 passed) |
| J-3 | P0 | engine/transformation/cobol_to_java_mapping.py | Partially fixed | fail-closed raise for SqlStatement/PerformTimesStatement; transformation tests green |
| J-1 | P0 | engine/transformation/spring_boot_generator.py | Already fail-closed | _generate_jdbc_repository raises NotImplementedError (no placeholder) |

## Open (not addressed here)
All other findings in AUDIT_06_MASTER_GAP_REGISTER.md remain open. No finding marked fixed without implementation+test evidence.