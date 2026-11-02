# Change ledger — architecture remediation

One row per verified change from
[ARCHITECTURE_AUDIT_2026-11-01.md](ARCHITECTURE_AUDIT_2026-11-01.md) §6.
A row is added only after its focused tests pass; the CI column is filled
from the exact pushed SHA.

| Item | Commit | Change | Callers / dependents checked | Tests (red → green) | Full regression | CI (exact SHA) |
|---|---|---|---|---|---|---|
| audit | `6072460` | Audit, dependency map (`tools/dependency_map.py`), this ledger | — | `tools/dependency_map.py --check` | — | — |
| A1 (P0-1) | see git log | One SELECT/ASSIGN extractor (`_SELECT_ASSIGN`) over the joined FILE-CONTROL text: both quote styles, optional TO, continued clauses; non-literal ASSIGN → UNSUPPORTED_CONSTRUCT. READ with no file path → `UNSUPPORTED_FILE$READ$<file>` instead of inlining NOT AT END. The modernization pipeline refuses generated Java carrying `UNSUPPORTED_*$` symbols (shared `producer.fail_closed_symbols`), as the producer already did | `_parse_file_control` (parser only); `_resolve_path` users (7 file verbs); `UniversalModernizationPipeline.execute` → `api/service.py` (raises on `generation_success=False`); generation replay of all 48 fixture apps: 0 changes vs Phase 2 evidence | `test_assign_clause_forms.py`: 8 red → 20 green, +5 GnuCOBOL pins (Docker lane) | hermetic 4,404 passed (1 known Windows-only); pytest-only gate 1,001 passed | `f930db5` green (Phase 2/3 CI) |

**Sequencing (owner decision, 2026-11-01):** after A1, the remaining audit
items are deferred until the five roadmap phases are complete; Phase 3
(COBOL coverage expansion) starts now.

## Resumed 2026-11-03 (after Phase 5 acceptance, `16cc305`)

Every remaining item was re-verified against `16cc305` first (Phases 3-5
changed much of the code): A2 was already done (Phase 3 increment 1 made
fixed-format continuation fully supported with GnuCOBOL pins); A3-A8 were
open. Regression method for every change below: the generated project of
all 54 fixture applications on `spring_boot` and `plain_java` (108 builds,
90 generated) is hashed file by file before and after - **byte-identical**
for all of Wave A - and each new test is shown red against the previous
code, then green.

| Item | Commit | Change | Callers / dependents checked | Tests (red → green) | Full regression | CI (exact SHA) |
|---|---|---|---|---|---|---|
| A2 (P0-2) | `4bcc514` | Superseded by Phase 3 increment 1: continuation lines and quote escapes read as GnuCOBOL reads them (oracle-pinned), not refused | — | `test_fixed_format_continuation.py`, `test_literal_quote_escapes.py` | Phase 3 | green (Phase 3 CI) |
| A3 (P0-3) | see push | Mapping state (`_main_entry_context`, scratch-name and TIMES counters) moved from module globals to thread-local state: a CALLed program's EXIT PROGRAM lowered as a no-op while another job lowered an entry program; one job's reset renumbered another's names | `cobol_to_java_mapping` only (no external readers); API runs ≤4 mapping jobs on threads | `TestA3MappingStateIsolation`: 2 red (real interleaving) → green | 108-build snapshot identical | pending |
| A4 (P0-4/5) | see push | Approval write bound to the checked `validation_generation` (`ConflictError` when a revalidation landed in between); `Service.require_verified_evidence` is the one gate for approval and export; download re-checks VERIFIED + consistency + integrity instead of trusting the approval column | `set_run_approval` (service, store), `download_generated`; BL-091 approval suite | `TestA4ApprovalAndExport`: 3 red → green | approval/download/verdict tests 186 passed | pending |
| A5 (P0-6) | see push | Integrity: a comparison must pair an ORACLE with a CANDIDATE artifact (never itself), both of the comparison's type; a MATCH may not record differences (`MALFORMED_EVIDENCE`) | every real pipeline manifest: Docker-lane vertical slice, forensic evidence, indexed/relative/record-sequential, fresh-verified, Phase 9 (159 passed) | `TestA5ComparisonPairing`: 4 red → green | evidence/verdict/adversarial 338 passed | pending |
| A6 (P0-7) | see push | Fail closed: unknown expressions raise in both renderers (were `""`); Spring rewrite emits `UNSUPPORTED_CALL$EXTERNAL/RECURSIVE/NO_ENTRY` (were comments) and recurses into do-while/try/switch; an unknown selected service raises (ran every service); `map_cobol_statement` raises on an unmapped statement type (returned no Java) | both generators, `java_to_spring_mapping`, mapper; JCL adapter's intentional empty selection unaffected | `TestA6FailClosed`: 5 red → green | 108-build snapshot identical; transformation suite 2,393 passed | pending |
| A7 (P0-8) | see push | `Service._gate_served_verdict`: every verdict view (run list, run, detail, `/verdict`, comparisons, integrated proof) serves VERIFIED only when the evidence also passes the integrity validator - the check approval and artifacts already applied | 4 call sites; failure views for non-VERIFIED verdicts unchanged | `TestA7OneVerdictGate`: 4 red → green | API/proof/adversarial 335 passed | pending |
| A8 | see push | The plan takes every CALL the analysis did not classify SUPPORTED (arity, cycle, dynamic, unproven callee) as a SKIP; a skipped COPYBOOK blocks generation, carrying the analyzer's reason (BL-033 wording kept); J-3 guard pinned | plan generator, pipeline; copybook suites (BL-031..039) 150 passed | `TestA8…`: 2 red → green, J-3 pin | 108-build snapshot identical | pending |

Also: `docs/audits/DEPENDENCY_MAP.md` regenerated (stale since Phases 3-5).
