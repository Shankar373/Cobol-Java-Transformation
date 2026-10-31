# SECURITY_REMEDIATION_REPORT

- Report date: 2026-10-31
- Branch: codex/universal-core

## Fixed this execution
- A-2 (P2): `use_uploaded_candidate` execution path disabled in production deployments. api/service.py + regression test.

## Open security findings
- A-1 (RBAC/separation of duties) owner-dependent.
- A-3 (bundled token bypass) owner-dependent.
- Dk-1 (Docker socket) accepted/owner.
- Remaining A-4..A-12, Dk-* per audit register.