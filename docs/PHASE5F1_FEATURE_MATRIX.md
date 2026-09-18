# Phase 5F.1 Transformation Feature Matrix

**Date:** 2026-09-15

| Construct | Parsed | IR | Generated | Executed | Behaviorally Proven |
|-----------|--------|-----|-----------|----------|-------------------|
| IDENTIFICATION DIVISION | YES | program_id | class name | YES | YES |
| PROGRAM-ID | YES | CobolProgram.program_id | Java class name | YES | YES |
| FILE-CONTROL | YES | FileDefinition | file I/O paths | YES | YES |
| ASSIGN TO | YES | FileDefinition.container_path | input/output dirs | YES | YES |
| PIC X(n) | YES | DataItem(PicType.ALPHANUMERIC) | String fields | YES | YES |
| PIC 9(n) | YES | DataItem(PicType.NUMERIC) | int fields | YES | YES |
| OCCURS | YES | DataItem.occurs | array size | YES | YES |
| OPEN INPUT | YES | OpenStatement | BufferedReader | YES | YES |
| READ | YES | ReadStatement | readLine() | YES | YES |
| WRITE | YES | WriteStatement | println() | YES | YES |
| MOVE | YES | MoveStatement | assignment | YES | YES |
| ADD | YES | AddStatement | += operator | YES | YES |
| IF/ELSE | YES | IfStatement | if/else | YES | YES |
| PERFORM | YES | PerformStatement | method call | YES | YES |
| PERFORM VARYING | PARTIAL | (skipped) | (skipped) | N/A | NO |
| STRING | YES | StringStatement | string concat | YES | YES |
| UNSTRING | YES | UnstringStatement | split() | YES | YES |
| DISPLAY | YES | DisplayStatement | System.out/err | YES | YES |
| GO TO | YES | GoToStatement | comment | YES | YES |
| STOP RUN | YES | StopRunStatement | return | YES | YES |
| Threshold business rule | YES | ThresholdRule | APPROVAL_THRESHOLD | YES | YES |
| COMPUTE | NO | (skipped + diag) | (skipped) | N/A | N/A |
| SUBTRACT | NO | (skipped + diag) | (skipped) | N/A | N/A |
| MULTIPLY | NO | (skipped + diag) | (skipped) | N/A | N/A |
| DIVIDE | NO | (skipped + diag) | (skipped) | N/A | N/A |
| SORT | NO | (skipped + diag) | (skipped) | N/A | N/A |
| CALL | NO | (skipped + diag) | (skipped) | N/A | N/A |
| EVALUATE | NO | (skipped + diag) | (skipped) | N/A | N/A |
| ACCEPT | NO | (skipped + diag) | (skipped) | N/A | N/A |
| CLOSE | NO | (skipped + diag) | (skipped) | N/A | N/A |

## Legend

- **Parsed**: Parser extracts from COBOL source
- **IR**: Represented in CobolProgram data structure
- **Generated**: Emitted in Java source code
- **Executed**: Runs in Docker/Java environment
- **Behaviorally Proven**: Runtime evidence confirms correct behavior

## Notes

- Constructs marked "skipped + diag" emit UNSUPPORTED_CONSTRUCT warnings, resulting in PARTIAL status
- "Behaviorally Proven" requires Docker execution with discriminating input
- Threshold rule: PROVEN with amount=750 against thresholds 500 and 1000
- File paths: PROVEN with alternate-claims.dat
