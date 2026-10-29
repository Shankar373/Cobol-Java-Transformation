# L.6.1 Batch Review — 2026-10-29 (risk-prioritized)

Scope: reviewed the conditional-only candidates in security/auth/deployment/
capability/verdict tests (highest-risk subset) via contextual read.

## Reviewed and classified MEANINGFUL (no change)
- tests/test_production_auth_env.py::test_production_without_token_answers_401_on_every_route
  — if/else both assert; fail-closed 401 coverage. Preserve.
- tests/test_api_security.py::test_unusable_name_upload_leaves_no_workspace
  — both branches assert (confined workspace / no cobol_source_path). Preserve.
- tests/test_ci_deployment_security.py::test_probe_cleanup_captures_and_restores_status
  — parametrized behavioral proof of captured status. Preserve.
- tests/verdict/test_verdict_trust_boundary.py::test_zero_comparisons_yield_unproven_when_validation_passes
  — asserts only on successful validation path; meaningful. Preserve.
- tests/transformation/test_capability_registry_reconciliation.py (2 candidates)
  — collection-property checks over registry. Preserve.
- tests/transformation/test_cics_subset.py (3 candidates) — command mapping checks. Preserve.
- tests/test_workspace_persistence.py::test_rejected_ingest_still_cleans_up_under_configured_root
  — meaningful cleanup assertion. Preserve.

## Conclusion
No vacuous candidate found in this high-risk batch. The remaining conditional-only
and loop-only candidates (mostly collection-property / file-organization guards)
are classified Category B/C and preserved. No test rewrites performed.
EOF

## Batch 2 (additional) - 2026-10-29
- tests/transformation/test_capability_registry_reconciliation.py: 2 candidates - meaningful collection checks. Preserve.
- tests/test_cics_subset.py: 3 candidates - command mapping checks. Preserve.
- tests/test_workspace_persistence.py: meaningful cleanup assertion. Preserve.
- tests/test_universal_modernization.py: collection/property guards. Preserve.
No vacuous candidates found in batch 2. Count unchanged (189).
