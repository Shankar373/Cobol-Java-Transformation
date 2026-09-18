# Phase 5F.2: IR-Driven Transformation Architecture

## Status

Accepted (with documented limitations)

## Context

Phase 5F.1 froze with 12 template-hardcoded elements in the generator. The
generator could produce correct Java for Claims workloads, but only because
the business semantics (status codes, thresholds, labels, output format) were
hardcoded in the Java template — not derived from the COBOL source.

## Actual Architecture

```
COBOL source
    ↓
CobolParser.parse()
    ↓ (pattern-based extraction)
    - _extract_status_codes(): IF/MOVE patterns for status definitions
    - _extract_primary_threshold(): numeric threshold from IF conditions
    - _extract_report_header(): WS-HEADER VALUE clause
    - _extract_summary_fields(): DISPLAY summary labels
    - _extract_settlement_logic(): orchestrates extractions
    ↓
CobolProgram IR (with SettlementLogic)
    ↓
JavaGenerator.generate()
    ↓ (two modes)
    - Settlement mode: consumes SettlementLogic for status/threshold
    - Minimal mode: generic MOVE/ADD/IF/DISPLAY
    ↓
Generated Java source
```

**Note: SemanticAnalyzer was NOT implemented.** The parser performs semantic
extraction directly. This is classified as DEFERRED architecture.

## What Was Actually Implemented

### IR Extension
- `StatusCodeDefinition`: code, settlement_label, field_name
- `ThresholdRule`: field_name, operator, value
- `OutputFieldDefinition`: field_name, delimiter, width
- `SettlementLogic`: status_codes, threshold_rule, report_header, etc.

### Parser Extension
- Pattern-based extraction of status codes from `IF <field> = '<char>'` / `MOVE '<label>' TO WS-SETTLEMENT-STATUS`
- Pattern-based extraction of threshold from `IF <field> <op> <number>`
- Pattern-based extraction of report header from `WS-HEADER VALUE "..."`
- Pattern-based extraction of summary fields from `DISPLAY "LABEL="`

### Generator Refactor
- Mode selection: `settlement_logic is not None` (not filename-based)
- Settlement mode: status codes, threshold, labels, record formats, payment lookup all from IR
- Minimal mode: generic statement generation
- Threshold fallback removed: `ValueError(MISSING_REQUIRED_SEMANTIC)`
- Settlement labels extracted: REJECTED, PENDING, APPROVED, PAID_IN_FULL, PARTIAL, UNPAID
- Record formats extracted from STRING statements
- Payment lookup extracted from CHECK-PAYMENT paragraph
- All fallback business semantics removed

## What Was NOT Implemented

1. **SemanticAnalyzer**: No separate semantic analysis layer. Parser extracts directly into IR.

2. **DecisionCondition**: Dead IR — defined in `ir.py` but never used. Import removed from forensic_audit.py.

3. **Control flow**: PERFORM and GO TO are parsed but not fully generated (GO TO is a comment).

## Alternatives Considered

### Option A: Full SemanticAnalyzer (original plan)

Pros: Clean separation of concerns.
Cons: Not implemented due to scope. Parser extraction is sufficient for current needs.
Verdict: DEFERRED.

### Option B: Parser → Semantic extraction → Generator (ACTUAL)

Pros: Simpler, works for current scope.
Cons: Some semantics still hardcoded. Parser has pattern-matching limitations.
Verdict: ACCEPTED.

## Consequences

### Positive
- 9 source-driven semantic categories proven with behavioral evidence
- Filename-based Claims detection removed
- Threshold fallback removed
- Non-Claims COBOL (SIMPLE-CALC) works in minimal mode
- Deterministic output

### Negative
- 6 template-hardcoded semantic categories remain
- Payment matching is entirely hardcoded
- Settlement record format is hardcoded
- DecisionCondition is dead IR
- SemanticAnalyzer is deferred

### Risks
- Pattern-based extraction may miss edge cases
- Hardcoded settlement labels may not match all COBOL workloads
- Payment matching logic is Claims-specific and not reusable
