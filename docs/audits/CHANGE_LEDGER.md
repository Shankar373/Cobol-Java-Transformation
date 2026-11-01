# Change ledger — architecture remediation

One row per verified change from
[ARCHITECTURE_AUDIT_2026-11-01.md](ARCHITECTURE_AUDIT_2026-11-01.md) §6.
A row is added only after its focused tests pass; the CI column is filled
from the exact pushed SHA.

| Item | Commit | Change | Callers / dependents checked | Tests (red → green) | Full regression | CI (exact SHA) |
|---|---|---|---|---|---|---|
| audit | — | Audit, dependency map (`tools/dependency_map.py`), this ledger | — | `tools/dependency_map.py --check` | — | — |
