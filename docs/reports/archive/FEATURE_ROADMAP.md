# FEATURE_ROADMAP

> **ARCHIVED (architecture audit, 2026-11-03):** a dated report kept for history only - moved here from the repository root. It describes the repository at its own recorded date and is not a current status claim. Current status: `README.md`, `docs/CAPABILITY_MATRIX.md`, `docs/reports/PHASE5_FINAL_CERTIFICATION.md`, `docs/reports/PHASE5_RELEASE_READINESS.md`.

- Report date: 2026-10-31
- Branch: codex/universal-core

## Implemented and verified (this repo)
- COBOL parsing, IR, mapping, Java/Spring Boot generation, Docker validation, API, frontend workflows, capability truth gates.

## This execution focus
- Security hardening: production gating of uploaded candidate execution (A-2).
- Minor hygiene: dead code removal (P-4).

## Next recommended milestones
1. Resolve J-9 verdict derivation truth table with regression tests.
2. Implement J-1 JDBC repository methods (not UnsupportedOperationException).
3. Fail-closed generator for unsupported statements (J-3) with diagnostics.
4. Continue parser diagnostic hardening (S-17).