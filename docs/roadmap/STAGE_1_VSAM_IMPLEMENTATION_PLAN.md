# Stage 1 - COBOL + VSAM: implementation plan and progress (2026-11-13)

Status vocabulary: `IMPLEMENTED_AND_VERIFIED`, `IMPLEMENTED_NOT_RUNTIME_VERIFIED`, `PARTIAL`, `SIMULATOR_VERIFIED`,
`UNSUPPORTED`, `NOT_IMPLEMENTED`, `EXTERNAL_DEPENDENCY`, `OWNER_DECISION_REQUIRED`. Evidence classes are never promoted:
`GNUCOBOL_DIFFERENTIAL`, `DETERMINISTIC_TEST`, `DOCUMENTED_SEMANTICS`, `NONE`; `IBM_RUNTIME_VERIFIED` appears nowhere
because no IBM environment has been used. Sources and tags for the external facts: [research report](../research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md).

## 1. Starting point (read from the code)

| Piece | Where | State |
|---|---|---|
| ORGANIZATION INDEXED, primary RECORD KEY, ACCESS SEQUENTIAL/RANDOM/DYNAMIC, START, READ NEXT, REWRITE, DELETE, FILE STATUS | `engine/transformation/file_io_support_template.py` (`CobolFileIo`), `cobol_to_java_mapping.py`, `capability_analyzer.py` | `IMPLEMENTED_AND_VERIFIED` against GnuCOBOL on bounded shapes (fixtures `workload-indexed*`) |
| ALTERNATE RECORD KEY, random read; one browse shape (ACCESS DYNAMIC, two alternate keys, `PIC X(2)`, FILE STATUS only) | `alternate_key.py`, `CobolFileIo` | `PARTIAL`, deliberately not generalised |
| ORGANIZATION RELATIVE | same runtime, fixtures `workload-relative*` | `PARTIAL` (GnuCOBOL RELATIVE, not IBM RRDS) |
| Variable record-sequential, COMP / COMP-3 / binary | fixtures `workload-record-sequential`, `workload-comp*`, `workload-binary-values` | verified against GnuCOBOL |
| IDCAMS `DELETE`, `DEFINE GDG`, `REPRO`, `SET MAXCC` | `engine/jcl/orchestrator.py` | `PARTIAL`, `DOCUMENTED_SEMANTICS`; the shell reference refuses IDCAMS |
| ESDS, RBA/RRN addressing, `DEFINE CLUSTER`, `LISTCAT`, `BLDINDEX`, `ALTER`, spanned records, linear data sets | nowhere | `NOT_IMPLEMENTED` / `UNSUPPORTED`, refused by name |

`ENGINEERING_INFERENCE`: GnuCOBOL `INDEXED` is not a VSAM KSDS, so a match proves the COBOL-visible behaviour of the shape
tested, not VSAM storage behaviour. Nothing here may be called "VSAM equivalence".

## 2. Semantic model (done: `engine/vsam/model.py`)

`DatasetDefinition` carries dataset identity, organization (SEQUENTIAL, KSDS, ESDS, RRDS), record format (fixed, variable
with a 4-byte RDW), record length, encoding (ASCII, EBCDIC cp037), primary key, alternate keys (offset, length, unique,
character or binary) and access modes. `validate()` refuses what VSAM does not allow, naming each problem: a KSDS without a
unique primary key, a key outside the record, a primary key on an ESDS or RRDS, any alternate index on an RRDS or a
sequential dataset, a variable-length RRDS. `CAPABILITIES` classifies 13 capabilities one by one (see the table in
`model.py`); there is no `VSAM_SUPPORTED` flag. Tested in `tests/test_vsam_model_reconcile.py`.

Still to model: RBA/RRN addressing, file-status mapping per organization, spanned records, free-space/CI behaviour. These
need an IBM reference before any claim.

## 3. Organizations: boundaries and exit criteria

### KSDS
- Done: primary-key shapes above (GnuCOBOL differential).
- Next, testable now with GnuCOBOL: more alternate-index shapes one at a time (`ACCESS RANDOM` first, then each browse
  form), each with a fixture and a negative test; generalise only when a differential covers the exact shape.
- Needs IBM: ordering above ASCII keys, RBA change on insert, free space, spanned records.
- Exit: every KSDS capability row in `CAPABILITIES` is `IMPLEMENTED_AND_VERIFIED` with a named fixture, or refused by name.

### ESDS
- Documented (VERIFIED_EXTERNAL_SOURCE): entry order, RBA that never changes, append at the end, no delete or lengthen,
  alternate indexes allowed.
- Plan: model in `DatasetDefinition` (done), add an append-only dataset class with RBA bookkeeping, refuse `DELETE` and
  record lengthening with a named diagnostic, and a deterministic test per rule.
- No local reference exists (GnuCOBOL has no ESDS), so evidence stays `DETERMINISTIC_TEST` /
  `IMPLEMENTED_NOT_RUNTIME_VERIFIED` until an IBM run exists. Status today: `NOT_IMPLEMENTED`.
- Must not be modelled as KSDS.

### RRDS
- Documented: RRN from 1; fixed-length slots, empty slots, slot reuse after delete; variable RRDS indexed; no alternate
  index.
- Today: GnuCOBOL RELATIVE is `PARTIAL`. Plan: fixtures for empty-slot read, delete-then-write reuse and each file status,
  compared with GnuCOBOL; record every behaviour where GnuCOBOL's documented RELATIVE semantics could differ from RRDS as
  `NOT_ESTABLISHED`.
- Do not reuse the KSDS implementation without a test showing the semantics are the same.

### IDCAMS
Inventory (`DEFINE CLUSTER`, DATA/INDEX components, `REPRO`, `LISTCAT`, `DELETE`, `BLDINDEX`, `ALTER`): implement a
bounded subset, one verb at a time, each with a parse test, a diagnostic with source location for every unsupported
clause, and no claim of DFSMS compatibility. `DEFINE CLUSTER` is the first to add because it names organization, keys and
record size and so feeds `DatasetDefinition`.

## 4. Data migration and reconciliation (done: `engine/vsam/reconcile.py`, `collation.py`)

`reconcile_migration(source, source_bytes, destination, destination_bytes, rejected)` recomputes, without trusting the
migrator: source and destination identity (organization, format, length, encoding, byte count, SHA-256), source and
destination record counts, rejected-record count, duplicate-key count, key set equality (after translating character keys
between encodings, never binary keys), key order in the destination's own collating sequence, record content, and named
failures and warnings. States: `RECONCILED`, `RECONCILED_PARTIAL` (counts and keys consistent but content not comparable
because the encodings differ and no field layout was supplied) and `FAILED`. A target file that merely exists fails
(count and key checks). Variable-length input is split by RDW with structural errors reported.

Tested (37 tests): clean migration; lost, substituted, changed and reordered records; duplicate source keys with and
without deliberate rejection; duplicate destination keys; rejecting a nonexistent or repeated record; truncated record;
invalid definitions; ASCII-to-EBCDIC with correct and wrong destination order; RDW corruption; determinism.

Not done: field-level translation (EBCDIC DISPLAY to ASCII with COMP-3 and binary fields preserved) from a COBOL record
layout; REDEFINES and OCCURS handling; restart after an interrupted migration; hashing at volume. Next task below.

## 5. Fixtures for the Stage 1 proof

| # | Fixture | Today |
|---|---|---|
| 1 | sequential batch | exists |
| 2 | KSDS random lookup | exists (`workload-indexed*`) |
| 3 | KSDS sequential browse | exists |
| 4 | KSDS alternate index | one certified shape |
| 5 | non-unique alternate index | within the certified shape |
| 6, 7 | ESDS append, sequential read | missing; blocked on a reference |
| 8 | RRDS direct access | partial (RELATIVE) |
| 9 | variable-length records | exists for record-sequential |
| 10 | EBCDIC ordering | deterministic unit tests only |
| 11 | packed and binary data | exists |
| 12 | invalid file operations | partly covered by file-status tests |
| 13 | interrupted migration and recovery | missing |

## 6. Progress and next smallest slice

Done in this change: semantic model and capability classes, EBCDIC key collation, migration reconciliation report (all
`IMPLEMENTED_NOT_RUNTIME_VERIFIED`, `DETERMINISTIC_TEST`), G-14 (file ownership no longer guessed), G-15 and G-17.

Next smallest independently verifiable slice: a field-aware migration converter driven by the existing COBOL record
layout (`FileDefinition.record_groups`) that translates DISPLAY fields between EBCDIC and ASCII, copies COMP-3 and binary
fields untouched, and feeds `reconcile_migration` so content can be compared (`RECONCILED` instead of
`RECONCILED_PARTIAL`), with a checkpoint file so an interrupted run resumes at a recorded record number. Differential
evidence is limited to GnuCOBOL reading the converted file; IBM validation of EBCDIC data stays `EXTERNAL_DEPENDENCY`.

## 7. Awaiting IBM validation (`REQUIRES_OWNER_OR_CUSTOMER_INPUT`)

KSDS ordering above ASCII and RBA behaviour; ESDS append, RBA and delete refusal; RRDS slot reuse and variable RRDS;
alternate-index upgrade sets; IDCAMS output and condition codes; VSAM file-status codes under error; spanned records.
Action needed from the owner: access to a licensed z/OS (or equivalent) environment and permission to run the fixtures.
