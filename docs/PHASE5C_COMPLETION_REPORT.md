# Phase 5C Completion Report — Indexed/Relative Semantic Validation

## Status: VERIFIED COMPLETE

## Forensic Root Cause
Predecessor used `all(rec in cobol_content for rec in lines)` — substring
containment — as fallback when byte-exact comparison of indexed/relative
files failed. This passed missing records, reordered subsets, extra
duplicates, and substring matches.

## Supported INDEXED Operations
- Single primary key (PIC X(4))
- Fixed-width records (PIC X(16))
- WRITE, READ (NEXT), REWRITE, DELETE
- DYNAMIC access mode
- START KEY >= for cursor positioning

## Supported RELATIVE Operations
- Relative record numbers (PIC 9(4) COMP)
- Fixed-width records (PIC X(20))
- WRITE by RRN, READ by RRN, REWRITE by RRN
- DYNAMIC access mode

## Canonical Semantic Model
Pipe-delimited text via stdout:
- INDEXED: `KEY|DATA` (e.g., `K001|RECORD-ONE--0001`)
- RELATIVE: `RRNN|DATA` (e.g., `0001|REL-RECORD-A----01`)
- Terminal: `FILESTATUS=00` + `END`

## Oracle Evidence
- COBOL program creates indexed/relative file
- Performs all supported operations
- Scans final state via sequential read
- Outputs canonical dump to stdout
- File status reported

## Java Evidence
- Java uses TreeMap (in-memory, different physical representation)
- Performs equivalent logical operations
- Outputs identical canonical dump format
- Byte-exact match with oracle stdout

## Mutation Matrix

### INDEXED (8 mutations)
| Mutation | Description | Verdict |
|---|---|---|
| missing-key | K003 removed | FAILED |
| extra-key | K004 added | FAILED |
| wrong-key | K003→K999 | FAILED |
| changed-content | K003 content altered | FAILED |
| wrong-mapping | K001/K002 content swapped | FAILED |
| duplicate-record | K001 written twice | FAILED |
| incorrect-delete | K002 not deleted | FAILED |
| incorrect-rewrite | K002 not rewritten | FAILED |

### RELATIVE (6 mutations)
| Mutation | Description | Verdict |
|---|---|---|
| missing-record | RRN 3 removed | FAILED |
| extra-record | RRN 4 added | FAILED |
| wrong-rrn | RRN 3→RRN 9 | FAILED |
| changed-content | RRN 3 content altered | FAILED |
| shifted-record | All records shifted +1 | FAILED |
| incorrect-rewrite | RRN 2 not rewritten | FAILED |

## False-PASS Defense
- Missing key → MISMATCH → FAILED
- Extra key → MISMATCH → FAILED
- Wrong key → MISMATCH → FAILED
- Changed content → MISMATCH → FAILED
- No substring/subset acceptance
- No containment logic
- No count-only comparison

## Physical Representation Test
COBOL: Berkeley DB indexed file
Java: TreeMap (in-memory)
Both produce identical canonical dump
→ MATCH → VERIFIED

## Determinism
Both indexed and relative workloads run twice produce:
- Identical stdout bytes
- Identical verdict
- Identical comparison results

## Regression
- Baseline: 336/336 passed
- New Phase 5C: 23 tests (13 indexed + 10 relative)
- Total: 359/359 passed
- Ruff: 52 findings (all pre-existing, 0 new)

## Limitations
- Single primary key only (no alternate keys)
- Fixed-width records only (no variable-length)
- No duplicate-key semantics
- No composite keys
- DELETE not tested for relative files
- Sequential access only (no full RANDOM verification)
- GnuCOBOL 3.1.2.0 oracle only

## Explicit Disclaimers
- This does NOT establish z/OS equivalence
- This validates GnuCOBOL 3.1.2.0 oracle behavior only
- Physical representation differences are by design invisible
- The canonical dump format is specific to this validation platform

## Files Created
- `fixtures/workload-indexed/cobol/INDEXED.cob`
- `fixtures/workload-indexed/java-candidate/IndexedDump.java`
- `fixtures/workload-indexed/java-candidate-mutated/` (8 files)
- `fixtures/workload-indexed/workload.py`
- `fixtures/workload-relative/cobol/RELATIVE.cob`
- `fixtures/workload-relative/java-candidate/RelativeDump.java`
- `fixtures/workload-relative/java-candidate-mutated/` (6 files)
- `fixtures/workload-relative/workload.py`
- `tests/integration/test_indexed_semantics.py`
- `tests/integration/test_relative_semantics.py`
- `docs/decisions/PHASE5C_INDEXED_RELATIVE_SEMANTICS_PLAN.md`

## Engine Changes
- `engine/oracle/docker_adapter.py:176-180` — compile command adds `cd /workspace`
  before program execution (backward-compatible: existing workloads unaffected)
