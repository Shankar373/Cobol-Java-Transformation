# Phase 5G Feature Matrix

> **HISTORICAL (label added 2026-10-16, Phase 12 F-02 documentation reconciliation):**
> dated phase record (2026-09-16), not a current status claim (Master README §78).
> Correction against canonical truth: the Parser Coverage table below shows
> **GO TO** with ✓ in the "Supported" column; parse recognition ≠ supported —
> canonical status is **GO TO = UNSUPPORTED** (comment + diagnostic only).
> Canonical authority: `docs/SEMANTIC_PROOF_MATRIX.md`. Live status:
> `opencode.md` + `docs/BACKLOG.md` register.

## IR Types

| IR Type | Purpose | Source-driven | Generic |
|---------|---------|---------------|---------|
| CobolProgram | Complete program IR | ✓ | ✓ |
| InputRecordMapping | UNSTRING field ordering | ✓ | ✓ |
| RecordFormat | STRING output format | ✓ | ✓ |
| SettlementLogic | Decision tree | ✓ | ✓ (Claims-specific naming) |
| PaymentLookup | Table search | ✓ | ✓ (Claims-specific naming) |
| StatusCodeDefinition | Status code mapping | ✓ | ✓ |
| ThresholdRule | Numeric threshold | ✓ | ✓ |
| IfStatement | Conditional | ✓ | ✓ |
| PerformStatement | Subroutine call | ✓ | ✓ |
| MoveStatement | Assignment | ✓ | ✓ |
| AddStatement | Accumulation | ✓ | ✓ |
| DivideStatement | Division | ✓ | ✓ |
| DisplayStatement | Output | ✓ | ✓ |
| UnstringStatement | Parse delimited | ✓ | ✓ |
| StringStatement | Format output | ✓ | ✓ |

## Generator Modes

| Mode | Trigger | Capabilities | Workloads |
|------|---------|--------------|-----------|
| Settlement | settlement_logic is not None | Full decision tree, record formats, payment lookup | CLAIMS |
| File I/O | input_record_mappings is not empty | UNSTRING parsing, processing, DISPLAY | STUDENT-PROCESSOR |
| Minimal | otherwise | MOVE, ADD, DIVIDE, IF, DISPLAY | GRADE-CALC |

## Workload Coverage

| Workload | Mode | UNSTRING | STRING | File I/O | IF/ELSE | DIVIDE | DISPLAY |
|----------|------|----------|--------|----------|---------|--------|---------|
| CLAIMS | Settlement | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| STUDENT-PROCESSOR | File I/O | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| GRADE-CALC | Minimal | — | — | — | ✓ | ✓ | ✓ |

## Parser Coverage

| Construct | Supported | Notes |
|-----------|-----------|-------|
| IDENTIFICATION DIVISION | ✓ | PROGRAM-ID extraction |
| ENVIRONMENT DIVISION | ✓ | FILE-CONTROL paths |
| DATA DIVISION | ✓ | FILE SECTION, WORKING-STORAGE |
| PROCEDURE DIVISION | ✓ | Paragraphs, statements |
| PIC X(n) | ✓ | Alphanumeric |
| PIC 9(n) | ✓ | Numeric |
| OCCURS | ✓ | Table declaration |
| MOVE | ✓ | String and numeric |
| ADD | ✓ | Accumulator |
| DIVIDE | ✓ | New in Phase 5G |
| IF/ELSE | ✓ | Nested, compound (AND/OR) |
| DISPLAY | ✓ | STDOUT/STDERR |
| UNSTRING | ✓ | Generic field extraction |
| STRING | ✓ | Record format extraction |
| PERFORM | ✓ | Simple and UNTIL |
| READ | ✓ | AT END / NOT AT END |
| WRITE | ✓ | Record output |
| OPEN/CLOSE | ✓ | INPUT/OUTPUT |
| GO TO | ✓ | Comment in generated Java |
| STOP RUN | ✓ | No-op |
| EVALUATE | ✗ | Diagnostic emitted |

## Regression

| Suite | Collected | Passed | Skipped | Failed |
|-------|-----------|--------|---------|--------|
| All non-Docker tests | 508 | 504 | 4 | 0 |
| Transformation | — | ✓ | — | — |
| Evidence | — | ✓ | — | — |
| Verdict | — | — | 4 | — |
