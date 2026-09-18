# Phase 6A: Universal COBOL Language + Semantic IR

## Objective
Build a genuinely source-driven semantic foundation before enterprise modernization.

## Classification: **B. UNIVERSAL IR + SOURCE-DRIVEN GENERATION — PARTIAL UNIVERSALITY**

The IR and generator are now generic, but the parser still has workload-specific guard logic for settlement detection.

---

## What Changed

### IR (`engine/transformation/ir.py`)
| Before | After | Type |
|--------|-------|------|
| `StatusCodeDefinition` | `StatusCodeMapping` | Generic naming |
| `settlement_label` | `label` | Generic naming |
| `PaymentLookup` | `LookupOperation` | Generic naming |
| `SettlementLogic` | `DecisionLogic` | Generic naming |
| Backward-compat aliases | `SettlementLogic = DecisionLogic`, `PaymentLookup = LookupOperation` | Compatibility |

### Parser (`engine/transformation/cobol_parser.py`)
| Before | After |
|--------|-------|
| Docstring: "Claims Settlement constructs" | Docstring: "generic supported constructs" |
| `_extract_status_codes` required `MOVE ... TO WS-SETTLEMENT-STATUS` | Extracts ANY `IF field = 'code' + MOVE 'label' TO target` |
| `_extract_settlement_labels` required `TO WS-SETTLEMENT-STATUS` | Requires `TO` target containing `SETTLEMENT` (more selective than before) |
| `_extract_report_header` required `WS-HEADER` | Finds any `PIC X(n) VALUE` header |
| `_extract_payment_lookup` required `PERFORM CHECK-PAYMENT` | Finds any PERFORM paragraph with table search pattern (IF table(idx) = field + MOVE + ADD) |
| `_extract_record_format` hardcoded `REPORT-REC`, `SETTLE-REC` | `_find_record_name` discovers record names from STRING...INTO statements |
| `has_settlement = bool(status_codes or settlement_labels)` | `has_status = bool(status_codes or settlement_labels)` — guard now requires `SETTLEMENT` in target name |

### Generator (`engine/transformation/java_generator.py`)
| Before | After |
|--------|-------|
| Docstring: "Claims Settlement workload" | Docstring: "generic supported constructs" |
| `_generate_settlement_java` | `_generate_decision_java` |
| Hardcoded `cobol_to_java` dict (WS-CR-CLAIM-ID→claimId, etc.) | `_derive_cobol_to_java_mapping` from InputRecordMappings |
| Hardcoded `APPROVAL_THRESHOLD` | `THRESHOLD` |
| Hardcoded `totalClaims`, `totalClaimAmt` | `totalCount`, `totalAmount` |
| Hardcoded `claims.dat`, `payments.dat` | Derived from FILE-CONTROL paths |
| Hardcoded `paymentMap` | `lookupMap` |
| `status_var` hardcoded as `status` | Derived from COBOL field name (WS-CR-STATUS → WS_CR_STATUS) |
| `claim_id_var` hardcoded as `claimId` | Derived from COBOL field name (WS-CR-CLAIM-ID → WS_CR_CLAIM_ID) |
| `_build_status_checks_java(sl)` | `_build_status_checks_java(sl, status_var, claim_id_var, patient_var, amt_str_var)` |
| `_build_stderr_java(sl)` | `_build_stderr_java(sl, claim_id_var, patient_var, amt_str_var, status_var)` |
| Summary field names hardcoded | `_build_summary_java` maps COBOL names → Java vars |

### Producer (`engine/transformation/producers/internal_native.py`)
- Added `DIVIDE` to `supported_constructs`
- Removed `DIVIDE` from `unsupported_constructs`

---

## Evidence

### Regression
```
504 passed, 4 skipped (matches baseline)
```

### Determinism
```
claims: DETERMINISTIC (5/5 runs)
gradecalc: DETERMINISTIC (5/5 runs)
studentproc: DETERMINISTIC (5/5 runs)
minimal: DETERMINISTIC (5/5 runs)
```

### Compilation
```
claims: COMPILES OK
gradecalc: COMPILES OK
studentproc: COMPILES OK
minimal: COMPILES OK
```

### Ruff
- 25 pre-existing F541 (f-string without placeholders) — unchanged
- 2 pre-existing I001 (import ordering) — unchanged
- 1 new F841 (unused variable `payment_lookup`) — fixed
- 1 new F401 (unused import `PicType`) — fixed
- 1 new F841 (unused variable `output_files`) — fixed

---

## Remaining Limitations

1. **Settlement guard**: `_extract_settlement_labels` still requires `SETTLEMENT` in the target field name — this is a heuristic guard, not truly generic
2. **Summary field mapping**: `_build_summary_java` has hardcoded COBOL→Java variable name mapping for summary fields (TOTAL_CLAIMS→totalCount, etc.)
3. **Generator mode selection**: Still driven by `settlement_logic is not None` check, not capability-based
4. **6-label vocabulary**: The settlement label extraction still has a fixed vocabulary (REJECTED/PENDING/APPROVED/PAID_IN_FULL/PARTIAL/UNPAID)
5. **Lookup detection**: Payment lookup extraction relies on finding IF table(idx) = search + MOVE + ADD pattern — may not generalize to all lookup patterns
6. **Record format extraction**: Still requires STRING...INTO patterns — no support for WRITE/COMPUTE record formats
7. **No EVALUATE support**: COBOL EVALUATE statements not yet parsed
8. **No COMPUTE/SUBTRACT/MULTIPLY**: Arithmetic operations beyond ADD/DIVIDE not supported
9. **Nested IF bug**: Parser doesn't correctly handle DISPLAY after nested IFs (workaround: compound conditions)
10. **OpenSourceCOBOL4J**: NOT VERIFIED (Docker execution blocked on Windows)
