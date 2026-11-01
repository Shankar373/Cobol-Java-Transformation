# Change ledger — architecture remediation

One row per verified change from
[ARCHITECTURE_AUDIT_2026-11-01.md](ARCHITECTURE_AUDIT_2026-11-01.md) §6.
A row is added only after its focused tests pass; the CI column is filled
from the exact pushed SHA.

| Item | Commit | Change | Callers / dependents checked | Tests (red → green) | Full regression | CI (exact SHA) |
|---|---|---|---|---|---|---|
| audit | `6072460` | Audit, dependency map (`tools/dependency_map.py`), this ledger | — | `tools/dependency_map.py --check` | — | — |
| A1 (P0-1) | see git log | One SELECT/ASSIGN extractor (`_SELECT_ASSIGN`) over the joined FILE-CONTROL text: both quote styles, optional TO, continued clauses; non-literal ASSIGN → UNSUPPORTED_CONSTRUCT. READ with no file path → `UNSUPPORTED_FILE$READ$<file>` instead of inlining NOT AT END. The modernization pipeline refuses generated Java carrying `UNSUPPORTED_*$` symbols (shared `producer.fail_closed_symbols`), as the producer already did | `_parse_file_control` (parser only); `_resolve_path` users (7 file verbs); `UniversalModernizationPipeline.execute` → `api/service.py` (raises on `generation_success=False`); generation replay of all 48 fixture apps: 0 changes vs Phase 2 evidence | `test_assign_clause_forms.py`: 8 red → 20 green, +5 GnuCOBOL pins (Docker lane) | hermetic 4,404 passed (1 known Windows-only); pytest-only gate 1,001 passed | pending |

**Sequencing (owner decision, 2026-11-01):** after A1, the remaining audit
items are deferred until the five roadmap phases are complete; Phase 3
(COBOL coverage expansion) starts now.
