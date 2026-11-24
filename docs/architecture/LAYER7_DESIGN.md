# Layer 7 design: Capability analysis on the canonical Application IR

Status: **L7-P1, L7-P2 and L7-P3 implemented (2026-11-24)**. Layer 6 is closed (`LAYER6_DESIGN.md` 10). Deterministic, open source only, no LLM.
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

## 2. Requirement checklist (traceable)

| # | Requirement | Code | Tests | Status |
|---|---|---|---|---|
| R1 | Program-level Layer 5 reasons (EXTERNAL, GLOBAL, nested, RENAMES) classified from the IR; unlisted reason fails safe | `ir_unsupported.REASON_LEVELS`, `level_of`, `apply` | `test_l7_ir_unsupported.py` | done (L7-P1) |
| R2 | Every IR note kind/code has a documented disposition (floor or evidenced non-blocking); unknown code or kind fails closed | `ir_unsupported.note_floor`, `UNSUPPORTED_NOTE_FLOORS` | `test_l7_ir_notes.py` (table closure against `UNSUPPORTED_USE_CODES`, mutations) | done (L7-P2) |
| R3 | Provenance: the Layer 5 fact ids behind a finding are on the component (`details["ir_provenance"]`, `["ir_unsupported"]`) | `ir_unsupported.apply` | `test_l7_ir_notes.py` | done |
| R4 | A note no program owns is an application-level finding, never dropped; it reaches Layer 8 as a SKIP entry | `ir_unsupported.application_findings` (component `IR-NOTES`, type CALL) | `test_l7_ir_notes.py`, `test_l7_contract.py` | done |
| R5 | Consistency: every unit has exactly one PROGRAM component, every CALL edge a CALL component, overall = worst, closed level vocabulary | analyzer (unchanged) | `test_l7_contract.py` over all fixture applications | verified |
| R6 | Determinism: a repeated analysis is byte-identical; note order does not matter | sorted note ids | `test_l7_contract.py`, `test_l7_ir_notes.py` | verified |
| R7 | Layer 8 contract: only SUPPORTED reaches TRANSFORM; IR findings reach the plan | `transformation_plan` (unchanged) | `test_l7_contract.py` | verified |
| R8 | Fixture reports identical with and without the IR findings (no certified verdict moved) | n/a | `test_l7_ir_unsupported.py` (fixture parametrised), 110 generation hashes | verified |
| R10 | IR-keyed capability evidence record in the sealed manifest: deterministic content, IR/fact provenance, source and application identity binding, integrity validation, fail-closed | `capability_record` (`build_record`, `verify_record`, `shape_problems`), `EvidenceManifest.capability_analysis`, `ViolationType.CAPABILITY_ANALYSIS_BINDING_MISMATCH`, `ModernizationReport.capability_record`, `PipelineConfig.capability_analysis`, `api.service._capability_pairs` | `test_l7_capability_record.py`, `tests/evidence/test_capability_analysis_evidence.py`, `tests/test_capability_analysis_api.py` | done (L7-P3) |
| R9 | Conflicting IR/discovery data: UNSUPPORTED `IR->DISCOVERY` finding (Layer 6 M1) | `consume.canonicalize` | `test_m1_capability.py` | inherited |

Rules: IR supplied -> findings apply; no IR -> behaviour unchanged. A finding only ever lowers a level, never raises one, and the
verdict text is changed only when the IR lowers the level (a confirmed level keeps its text and gains provenance only).

## 3. Milestones

| Milestone | Scope | Status |
|---|---|---|
| L7-P1 | closed program-reason table (EXTERNAL, NESTED, RENAMES -> UNSUPPORTED; GLOBAL -> PARTIAL; unlisted -> UNSUPPORTED) | implemented |
| L7-P2 | closed note-disposition table, provenance, application-level finding, Layer 7 -> 8 contract tests, adversarial and mutation tests | implemented |
| L7-P3 | capability record: `capability_id` (whole report incl. provenance details), `ir_id`/`semantic_id` of the analysed IR, `plan_id` (Layer 8 plan rows), `source_hash` (same algorithm as `SourceIdentity`), `application_id`, `overall_level`; built by the modernization pipeline, carried by `ModernizationReport` and the stored run report, sealed in the manifest as a conditional key (a manifest without it keeps its exact hash) | implemented |

## 4. Dispositions measured over the 55 fixture applications (not assumed)

| IR note | Count | Analyzer verdict on the owning program | Disposition |
|---|---|---|---|
| refusal / `UNSUPPORTED_CONSTRUCT` | 43 | UNSUPPORTED 43/43 | floor UNSUPPORTED (already agreed) |
| diagnostic / `PARTIAL_SUPPORT` | 35 | SUPPORTED 24, UNSUPPORTED 11 | analyzer-owned (certified-construct rules); no floor |
| unsupported / `CONDITION_UNSTRUCTURED` | 4 | SUPPORTED 3, UNSUPPORTED 1 | Layer 5 extraction limit on certified `PERFORM VARYING ... UNTIL`; no floor |
| unsupported / `COPYBOOK_NOT_EXPANDED` | 6 | SUPPORTED 6 | covered by the analyzer's copybook components; no floor |

## 5. The capability record (L7-P3)

| Key | Meaning |
|---|---|
| `capability_id` | sha256 of the application id, every component (id, type, level, reason, details incl. `ir_provenance`/`ir_unsupported`), overall level and the four ids below |
| `ir_id`, `semantic_id` | the Application IR the analysis consumed |
| `plan_id` | sha256 of the Layer 8 plan's `(component, type, action)` rows and counts |
| `source_hash` | the source tree hash, computed as `engine.pipeline` computes `SourceIdentity.source_hash` |
| `application_id`, `overall_level` | identity and the closed level vocabulary |

Binding rules. The evidence validator requires the exact key set, lower-case sha256 digests, a known level, a non-empty application id,
and `source_hash` equal to the manifest's own `source_identity.source_hash` (a record for another source is refused). The manifest
holds no report, IR or plan, so the other ids are tamper-evident through the seal; `capability_record.verify_record` re-derives the
record from a report, plan, IR and tree and names every key that differs (the API test reproduces the sealed record from the source
tree exactly, `plan_id` included). The record is advisory lineage: it never changes generation or a verdict.

**IR identity is not shared with `application_ir`.** The IR the analysis consumes is built by the modernization pipeline from the
discovered texts; the API's `application_ir` is projected from a document that also carries the checkpoint, source digest, profiles
and graph, so the two `ir_id`/`semantic_id` values differ by construction and are not required to be equal. The record's IR is
bound to *its* report through `capability_id`.

## 6. Limits and remaining work (stated up front)

* Without an IR none of the IR findings are visible and no record is produced (the pipeline, API and hash tool always pass the IR).
* Levels for reasons and codes are judgements recorded in the tables (GLOBAL is harmless in a flat program, so PARTIAL); a code added
  by Layer 5 later is UNKNOWN (notes) or UNSUPPORTED (program reasons) until classified.
* `STATEMENT_PARTLY_PARSED`, `OPERAND_UNPARSED`, `INSPECT_OPERAND_KIND_UNKNOWN`, `GOTO_TARGET_UNPARSED` and
  `COMPILER_OPTION_UNMODELLED` are floored PARTIAL on judgement: no fixture emits them, so tests construct them as forged IR notes.
* Per-program classification still reads the parser IR and source scans (frozen coverage); `PARTIAL_SUPPORT` stays analyzer-owned.
* The record's `capability_id` depends on whether Docker was available to the analysis (UNAVAILABLE components), so it records what
  was analysed on that host; it is not host-independent by design.
* The manifest cannot re-derive the report by itself (no report is persisted beside it); re-derivation needs the source tree.
