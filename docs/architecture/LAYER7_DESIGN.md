# Layer 7 design: Capability analysis on the canonical Application IR

Status: **in progress (2026-11-24)**. Layer 6 is closed (`LAYER6_DESIGN.md` 10). Deterministic, open source only, no LLM.
Language coverage is frozen: nothing here adds COBOL syntax, and the retained producers R2/R3/R5/R6 stay.

## 1. Audit (what exists)

`engine/modernization/capability_analyzer.py` (about 1,860 lines) classifies PROGRAM, COPYBOOK, CALL and FILE components as
SUPPORTED / PARTIAL / UNSUPPORTED / UNAVAILABLE / UNKNOWN by worst-case aggregation (`semantic_capability`, one construct registry
pinned by `tests/capability_truth.txt`). After Layer 6 M1/M3 its application-level inputs (CALL edges, entries, COPY, FILE) are taken
from, or verified against, the Application IR. Per-program classification still reads the parser IR plus source scans, and that
remains authoritative (frozen coverage).

**Gap found by probe (L7-P1).** The IR carries Layer 5's named reasons for what the parser read without modelling
(`EXTERNAL_CLAUSE_NOT_READ`, `GLOBAL_CLAUSE_NOT_READ`, `NESTED_PROGRAM_NOT_MODELLED`, `RENAMES_NOT_MODELLED`). The analyzer ignored
the first two: a program with an `EXTERNAL` or `GLOBAL` item was reported SUPPORTED although its sharing semantics are not
reproduced. No fixture carries such a reason, so the 110 generation hashes are unaffected.

## 2. Milestones

| Milestone | Scope | Status |
|---|---|---|
| L7-P1 | `engine/modernization/ir_unsupported.py`: closed reason table (EXTERNAL, NESTED, RENAMES -> UNSUPPORTED; GLOBAL -> PARTIAL; an unlisted reason -> UNSUPPORTED, fail closed); the analyzer worsens the PROGRAM component from the IR, with the reasons in `details["ir_unsupported"]`; callers see the callee's level through the existing CALL rule | implemented, `tests/application_ir/test_l7_ir_unsupported.py` |

Rules: IR supplied -> the finding applies; no IR -> behaviour unchanged. A finding only ever lowers a level, never raises one.

## 3. Limits and remaining work (stated up front)

* Without an IR the two clauses are still invisible to the analyzer (the pipeline, API and hash tool always pass the IR).
* The table maps a reason to a level by judgement (GLOBAL is harmless in a flat program, so PARTIAL, not UNSUPPORTED); a Layer 5 reason
  added later is UNSUPPORTED until classified, and a test pins the table against the four reasons Layer 5 emits today.
* Not started: moving per-program classification off source scans (blocked by frozen coverage), IR-derived reachability for unused
  programs, and an IR-keyed capability evidence record.
