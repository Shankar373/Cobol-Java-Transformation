# SEMANTIC_EQUIVALENCE_REPORT

- Report date: 2026-10-31
- Branch: codex/universal-core

## Verdict contract
PASS / FAIL / INCONCLUSIVE / BLOCKED / NOT_APPLICABLE. Unavailable oracle execution is never PASS. Mixed execution states require careful handling; current derivation uses `all()` for unavailable detection (J-9 open).

## Evidence
- Differential tests: tests/transformation/test_claims_transformation.py (Docker-gated, skipped locally).
- Verdict derivation: engine/verdict/derivation.py.

## This execution
J-9 fixed: unavailable detection now uses any() for mixed execution states; regression tests in tests/verdict/test_j9_mixed_states.py (5 passed). VERIFIED never returned when any required execution is unavailable.