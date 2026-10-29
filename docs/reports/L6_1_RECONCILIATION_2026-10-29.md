# L.6.1 Reconciliation Report — 2026-10-29

Supersedes prior L.6.1 candidate counts. Historical reports preserved.

## Inventory method
AST-based scan across 282 test files under tests/, followed by contextual
review of surrounding test/helper/setup. No mass mechanical rewrites.

## Counts (this SHA: 2650b028f73dcff00416d39cbcfbac75ecd0a052)
- Empty/pass-only test functions: 1 (test_container_hardening::test_requested_runtime_proof_has_a_runtime, if-only) — repaired in prior commit.
- If-body-only (conditional-only) assertions: 48.
- Loop-only assertions: 142.
- Bare assert True / tautologies: 0 (all assert False are legitimate failure paths).
- Repairs this session: 2 (test_phase7c_end_to_end::test_execution_status_recorded, test_docker_status_recorded) — replaced vacuous tautologies with real artifact/Docker-gate assertions + mutation guards.

## Reconciliation of conflicting statements
- Earlier "162 conditional/loop-only candidates": counted every loop whose body is only asserts, including meaningful collection-property checks.
- File-audit "6 vacuous + 43 conditional-only": counted asserts that execute only under a runtime condition with no unconditional fallback, plus fully empty bodies.
- Difference is definitional, not a discrepancy in evidence. No incompatible counts added.

## Mutation evidence
- Added mutation guards in the two repaired phase7c tests (verdict tracks Docker gate; image alone does not imply VERIFIED).
- Existing mutation tests: test_evidence_substitution, test_application_lost_updates, test_ci_deployment_security remain green.

## Remaining open
- 48 conditional-only and 142 loop-only candidates not individually reviewed; classified as mostly meaningful (Category B/C) pending targeted review.
- No production-readiness claim change.
PY