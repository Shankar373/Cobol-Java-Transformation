# SECURITY_REMEDIATION_REPORT

> **ARCHIVED (architecture audit, 2026-11-03):** a dated report kept for history only - moved here from the repository root. It describes the repository at its own recorded date and is not a current status claim. Current status: `README.md`, `docs/CAPABILITY_MATRIX.md`, `docs/reports/PHASE5_FINAL_CERTIFICATION.md`, `docs/reports/PHASE5_RELEASE_READINESS.md`.

- Report date: 2026-10-31
- Branch: codex/universal-core

## Fixed this execution
- A-2 (P2): `use_uploaded_candidate` execution path disabled in production deployments. api/service.py + regression test.

## Open security findings
- A-1 (RBAC/separation of duties) owner-dependent.
- A-3 (bundled token bypass) owner-dependent.
- Dk-1 (Docker socket) accepted/owner.
- Remaining A-4..A-12, Dk-* per audit register.