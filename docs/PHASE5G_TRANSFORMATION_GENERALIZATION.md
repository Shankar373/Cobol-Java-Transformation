# Phase 5G — Transformation Generalization

## Date: 2026-09-16

## Objective

Prove the transformation engine is genuinely GENERIC and REUSABLE, not a Claims
implementation with reusable interfaces.

## Architecture

```
COBOL source
    ↓
CobolParser.parse()
    ↓
CobolProgram IR
    ├── InputRecordMapping[] (UNSTRING field ordering)
    ├── SettlementLogic (status codes, thresholds, labels, payment lookup)
    ├── FileDefinition[] (file paths)
    ├── DataItem[] (WORKING-STORAGE variables)
    └── Paragraph[] (statements)
    ↓
JavaGenerator.generate()
    ├── Settlement mode (when settlement_logic is not None)
    ├── File I/O mode (when input_record_mappings is not empty)
    └── Minimal mode (otherwise)
    ↓
Generated Java source
```

## IR Extensions (Phase 5G)

### InputRecordMapping

New IR type that captures UNSTRING field ordering and delimiter:

```python
@dataclass(frozen=True)
class InputRecordMapping:
    record_name: str    # e.g. "CLAIM-REC"
    file_name: str      # e.g. "CLAIMS-FILE"
    delimiter: str      # e.g. "|"
    fields: tuple[str, ...]  # ordered field names
```

This replaces hardcoded `c[0]`, `p[1]`, `p[3]` positional access in the generator.

### Generator Modes

1. **Settlement mode**: For programs with SettlementLogic (Claims workload).
   Uses IR-derived status codes, thresholds, labels, record formats.
2. **File I/O mode**: For programs with InputRecordMappings.
   Derives variable declarations, parsing code, and processing from IR.
3. **Minimal mode**: For simple programs without file I/O.
   Generates MOVE, ADD, DIVIDE, IF/ELSE, DISPLAY.

## Supported Constructs

| Construct | Parser | Generator | Notes |
|-----------|--------|-----------|-------|
| MOVE | ✓ | ✓ | String and numeric |
| ADD | ✓ | ✓ | Accumulator pattern |
| DIVIDE | ✓ | ✓ | New in Phase 5G |
| IF/ELSE | ✓ | ✓ | Nested IFs, compound conditions (AND/OR) |
| DISPLAY | ✓ | ✓ | STDOUT and STDERR |
| UNSTRING | ✓ | ✓ | Generic field ordering from IR |
| STRING | ✓ | ✓ | Record format from IR |
| PERFORM paragraph | ✓ | ✓ | Simple paragraph call |
| PERFORM UNTIL | ✓ | Partial | In settlement mode only |
| READ/WRITE | ✓ | ✓ | File I/O |
| OPEN/CLOSE | ✓ | ✓ | File lifecycle |
| GO TO | ✓ | ✓ | Comment in generated Java |
| STOP RUN | ✓ | ✓ | No-op |
| OCCURS | ✓ | ✓ | Table declaration |
| EVALUATE | ✗ | ✗ | Not supported — diagnostic emitted |

## Non-Claims Workloads

### GRADE-CALC (in-memory)
- MOVE, ADD, DIVIDE, IF (compound conditions), DISPLAY
- Uses minimal generation mode
- Compiles and runs correctly

### STUDENT-PROCESSOR (file I/O)
- UNSTRING, MOVE, ADD, DIVIDE, IF (compound conditions), DISPLAY
- Uses file I/O generation mode
- Reads pipe-delimited records, computes grades, displays results
- Compiles and runs correctly

## Source Mutation Evidence

All workloads demonstrate source → IR → Java → runtime mutation:

| Workload | Mutation | IR Changed | Java Changed | Runtime Changed |
|----------|----------|------------|--------------|-----------------|
| GRADE-CALC | threshold 90→95 | ✓ | ✓ | ✓ |
| GRADE-CALC | score 85→95 | ✓ | ✓ | ✓ |
| GRADE-CALC | name Alice→Bob | ✓ | ✓ | ✓ |
| STUDENT-PROCESSOR | threshold 90→85 | ✓ | ✓ | ✓ |
| STUDENT-PROCESSOR | input file name | ✓ | ✓ | ✓ |

## Determinism

Identical source + configuration produces byte-identical Java across 5 runs
for all workloads (GRADE-CALC, STUDENT-PROCESSOR, CLAIMS).

## Remaining Limitations

1. **Label vocabulary**: Parser recognizes 6 specific settlement labels.
   Labels outside this vocabulary cause MISSING_REQUIRED_SEMANTIC.
2. **Docker execution**: BLOCKED / NOT VERIFIED (Windows Docker performance).
3. **Payment file structure**: Generator assumes CSV column positions from
   COBOL UNSTRING ordering. Not dynamically derived.
4. **UNSTRING/PERFORM/GO TO**: Full control flow for these constructs is
   limited. Simple cases work; complex cases produce diagnostics.
5. **EVALUATE**: Not supported — diagnostic emitted.
