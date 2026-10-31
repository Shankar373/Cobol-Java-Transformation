# FEATURE_ROADMAP

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