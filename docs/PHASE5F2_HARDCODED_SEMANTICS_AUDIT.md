# Phase 5F.2: Hardcoded Semantics Audit

## Forensic Audit Date: Phase 5F.2 Forensic Closure

## Complete Semantics Table

| Semantic | Source-derived | IR-derived | Generator hardcoded | Runtime proven | Status |
|----------|---------------|------------|---------------------|----------------|--------|
| Status code R→REJECTED | YES | YES | NO | YES | **PROVEN** |
| Status code P→PENDING | YES | YES | NO | YES | **PROVEN** |
| Threshold value | YES | YES | NO | YES | **PROVEN** |
| File paths | YES | YES | NO | YES | **PROVEN** |
| Report header | YES | YES | NO | YES | **PROVEN** |
| Summary field labels | YES | YES | NO | YES | **PROVEN** |
| Assignment (MOVE) | YES | YES | NO | YES | **PROVEN** |
| Arithmetic (ADD) | YES | YES | NO | YES | **PROVEN** |
| Output format (DISPLAY) | YES | YES | NO | YES | **PROVEN** |
| Settlement label APPROVED | YES | YES | NO | YES | **PROVEN** |
| Settlement label PAID_IN_FULL | YES | YES | NO | YES | **PROVEN** |
| Settlement label PARTIAL | YES | YES | NO | YES | **PROVEN** |
| Settlement label UNPAID | YES | YES | NO | YES | **PROVEN** |
| Payment matching logic | YES | YES | NO (HashMap approach) | YES | **PROVEN** |
| Settlement record format | YES | YES | NO | YES | **PROVEN** |
| Report record format | YES | YES | NO | YES | **PROVEN** |
| DecisionCondition | N/A | DEAD IR (removed import) | N/A | N/A | **REMOVED** |
| SemanticAnalyzer | N/A | N/A | N/A | N/A | **DEFERRED** |

## Detailed Classification

### Source-Driven (PROVEN via mutation + runtime)

1. **Status codes R, P**: Parser extracts `IF WS-CR-STATUS = 'R'` / `MOVE 'REJECTED' TO WS-SETTLEMENT-STATUS`. Mutation `R→X` produces `status.equals("X")` in Java. Behavioral proof: report.txt differs.

2. **Threshold value**: Parser extracts `IF WS-CLAIM-AMOUNT < 500`. Mutation `500→1000` produces `APPROVAL_THRESHOLD = 1000`. Behavioral proof: amount=750 → PAID_IN_FULL (500) vs REJECTED (1000).

3. **File paths**: Parser extracts from FILE-CONTROL. Source-driven via `FileDefinition.container_path`.

4. **Report header**: Parser extracts from `WS-HEADER VALUE "..."` clause.

5. **Summary fields**: Parser extracts from `DISPLAY "LABEL="` patterns.

6. **Assignment (MOVE)**: Parser extracts `MoveStatement`. Generator produces `target = source;`. Behavioral proof: `MOVE 100→200` changes output from 150 to 250.

7. **Arithmetic (ADD)**: Parser extracts `AddStatement`. Generator produces `target += source;`. Behavioral proof: `ADD 50→75` changes output from 150 to 175.

8. **Output format (DISPLAY)**: Parser extracts `DisplayStatement`. Generator produces `println(...)`. Behavioral proof: `RESULT=→OUTPUT=` changes stdout.

### Template-Hardcoded (NOT source-driven)

1. **Settlement labels APPROVED, PAID_IN_FULL, PARTIAL, UNPAID**: Defaults in `SettlementLogic` dataclass. Parser does NOT extract these from COBOL MOVE patterns. The COBOL has `MOVE 'APPROVED' TO WS-SETTLEMENT-STATUS` but parser only extracts single-char status codes (R, P), not the settlement labels.

2. **Payment matching logic**: Entirely template-hardcoded. Parser extracts `PERFORM FIND-PAYMENT` as a `PerformStatement` but does not parse the FIND-PAYMENT paragraph's logic. The payment lookup, amount comparison, and paid/unpaid determination are hardcoded in `_generate_status_checks_java`.

3. **Settlement record format**: `stl.printf("%s|%s|%s|%s|%s|%s%n", ...)` is hardcoded. `OutputFieldDefinition` exists in IR but is not consumed by generator.

4. **Report record format**: `rpt.printf("%s %s %s %s %s %s %s%n", ...)` is hardcoded.

5. **Fallback values**: When IR fields are empty, hardcoded Claims-specific defaults are used (summary field names, report header).

### Dead/Unused IR

1. **DecisionCondition**: Defined in `ir.py` but never imported or used by parser or generator.

2. **SemanticAnalyzer**: Does not exist. Architecture is Parser → Semantic extraction into IR → Generator.

### Confirmed Removed

1. **Filename-based Claims detection**: `_is_claims_program()` removed. Mode selection based on `settlement_logic is not None`.

2. **Threshold fallback 500**: Removed. `_get_threshold_from_ir` raises `ValueError(MISSING_REQUIRED_SEMANTIC)` when threshold is missing.
