# AUDIT_02_SEMANTIC_TRACE

End-to-end semantic trace through the modernization pipeline:
COBOL Source → Lexer/Parser → IR → Semantic Analysis → Capability Decision → Modernization Plan → Java Mapping → Java Generation → Compilation → Runtime Execution → Behavioral Comparison.

## 1. Representative pipeline stages and key anchors

| Stage | File:Lines | Notes |
|---|---|---|
| Source preprocessing / parse | `engine/transformation/cobol_parser.py:472-613` | Line-oriented; fixed-format column handling; REPLACE preprocessor; logical-line joining for MOVE/ADD/IF. |
| Data description → IR | `cobol_parser.py:951-1041` (`parse_data_description_lines`), `:1073-1116` (`_parse_working_storage`), `:1118-1143` (`_flatten_working_storage_record`). |
| IR definition | `engine/transformation/ir.py` (DataItem, MoveStatement, AddStatement, …, IfStatement, PerformStatement, CallStatement, ComputeStatement). |
| Capability analysis | `engine/modernization/capability_analyzer.py:316-396` (`analyze`), `:663-785` (`_walk`). |
| Semantic capability registry | `engine/transformation/semantic_capability.py` (CONSTRUCT_IR_COVERAGE, CONSTRUCT_SOURCE_PATTERNS, effective_source_level). |
| Capability → plan enforcement | `engine/modernization/pipeline.py:308-338`. |
| COBOL → Java mapping | `engine/transformation/cobol_to_java_mapping.py:3074-4425` (`map_cobol_statement`), `:4615-4951` (`map_cobol_program_to_java`). |
| Java generation | `engine/transformation/java_generator.py`, `spring_boot_generator.py`. |
| Producer (single program) | `engine/transformation/producer.py:103-143`. |
| Application generator | `engine/transformation/application_generator.py:125-177`. |
| Differential verification | `engine/verification/*`, `engine/comparators/*`, `engine/verdict/*`, `engine/candidate/*`. |

## 2. MOVE

- Parser: `MoveStatement` built in `_parse_move` (`cobol_parser.py:1839-1857`). On regex miss → empty `MoveStatement(source="", target="")` + warning (P-15).
- Mapping: `map_cobol_statement` handles `MoveStatement` (in `cobol_to_java_mapping.py` MOVE branch). Numeric receiver semantics applied via `_apply_numeric_receiver_semantics` (1766-1876).
- Risk: empty node survives; capability analyzer `_note_ir` marks unmapped IR classes UNSUPPORTED, but `MoveStatement` is mapped, so a malformed MOVE with empty fields still maps to a no-op-ish Java statement. Capability verdict can overstate support. (P-2/P-15.)

## 3. ADD / SUBTRACT / MULTIPLY / DIVIDE / COMPUTE

- Parser: `_parse_add` (1883-1884 empty on miss), `_parse_subtract`, `_parse_multiply` (1930-1933), `_parse_divide` (2086-2087), `_parse_compute` (2129-2130). Empty nodes on miss.
- Mapping: arithmetic expression via `map_cobol_expr_to_java` (1306-1350) + tokenizer (1362-1467). On exception → `_unsupported_arithmetic_expression` (fail-closed JavaUnsupportedExpression). Good.
- Numeric semantics: `_apply_numeric_receiver_semantics` (1766-1876) scales receiver; unsigned integer receivers throw on overflow (S-9, suspected).
- ROUNDED: handled via `_scale_numeric_receiver`/`_promote_numeric_expression_to_decimal` (1498-1965). Capability registry has `ROUNDED` flag (semantic_capability).
- Defect: `_parse_pic_details` fractional count bug (P-1/S-7) → wrong scale for parenthesized PIC like `9(5)V9(2)`.
- Defect: `_numeric_java_literal` swallows `NumericValueError` (S-8).

## 4. IF / ELSE / END-IF

- Parser: `_parse_if` (2266-2360) → `IfStatement`. On empty condition, empty node emitted (P-5).
- Mapping: `map_cobol_condition_to_java` (2372-2884).
- Negated conditions handled (test_negated_conditions in capability gate).
- Risk: empty IfStatement survives as empty control node (P-5).

## 5. EVALUATE

- Parser: `_parse_evaluate` (2132-2265) → `EvaluateStatement`. Empty node on no arms (P-5).
- Mapping: handled in `map_cobol_statement`.
- Risk: partial parsing survives.

## 6. PERFORM variants

- Parser: `_parse_perform` (2454-2455 empty on miss) → `PerformStatement` with `paragraph_name`, `thru`, `times`, `varying`, `until_condition`, `test_after`.
- Mapping: `map_cobol_statement` PERFORM branch (4264-4287+). 
  - **Defect S-10**: `WITH TEST AFTER` (`test_after`) parsed but ignored → pre-test loop (wrong iteration count when condition initially true).
  - **Defect S-11**: VARYING assumes int loop vars and integer stop values; field-valued `by` emitted as raw literal.
  - **Defect S-12**: `_expand_thru_range` (3026-3043) returns only `[first]` on inverted/unknown range.
- PERFORM THRU: `_expand_thru_range` expands paragraph range.

## 7. CALL

- Parser: `_parse_call` (1974-1975) → `CallStatement(program_name, is_dynamic)`. On failure hardcodes `is_dynamic=True` (P-16).
- Mapping: CALL branch (4359-4410). Sync-in for all passing modes; sync-out only for REFERENCE + plain reference. BY CONTENT/BY VALUE correctly no sync-out. Default passing mode = REFERENCE (COBOL default) — acceptable.
- Capability: `_iter_call_statements` (capability_analyzer.py:165-178) swallows AttributeError/TypeError (S-16).
- Multi-program: `map_cobol_programs_to_application` (5028-5106).

## 8. PIC clauses

- Parser: `_parse_pic` (332-361), `_parse_pic_details` (1047-1057).
  - **Defect P-1/S-7**: fractional count by raw `'9'` chars → `PIC 9(5)V9(2)` yields `decimal_places=1` instead of 2.
- IR: `DataItem` with `pic_type`, `pic_length`, `decimal_places`, `signed`.
- Mapping: `map_pic_to_java_type` (131-241), `map_pic_to_java_default`.

## 9. COMP / COMP-3 / COMP-5

- Capability registry: `semantic_capability.py` usage-level narrowing for COMP/COMP-3 (byte-encoding). `application_discovery` filters PARTIAL_SUPPORT diagnostics (application_discovery.py:273-277).
- Usage capability: `test_usage_capability` in capability gate.
- No silent discard; COMP-3 handled via numeric semantics.

## 10. REDEFINES

- Parser: `_parse_redefines` (in cobol_parser). IR: `RedefinesClause`.
- `engine/transformation/redefines.py:87-184` builds redefines plan; multiple redefines of same base silently overwrite (P-9/P-3).
- Mapping: redefines buffer/sync (4519-4591).

## 11. OCCURS

- Capability: OCCURS handled; `test_copybook_capability_transitivity` etc.
- Mapping: OCCURS subscripts (242-418).

## 12. COPY / COPY REPLACING

- `engine/transformation/copybook_model.py:307-318` (`_expand_copybook_text`): unparseable REPLACING → ERROR diagnostic, fail-closed (OK).
- `engine/transformation/copybook_resolver.py:89-109`: search dirs via rglob; symlinked dirs may be missed (S-14, P3).
- Capability: `test_nested_copybook_materialization`, `test_copy_replacing_materialization`.

## 13. File status and file operations

- File verbs parsed (OPEN/READ/WRITE/CLOSE/START/REWRITE/DELETE) with clause collection (`_collect_file_clauses`, 1437-1566). Empty nodes on miss (P-2).
- `open_statements` collection skips nested OPEN (P-13).
- Mapping: file record layout/key/status helpers (1037-1138), status binding (1139-1282).
- `CobolProgram.open_statements` used for file-role capability derivation.

## 14. Numeric overflow and truncation

- Unsigned integer receiver overflow throws (`Math.*Exact`) instead of COBOL modulo truncation (S-9, suspected P2).
- Decimal receiver applies `remainder(10**n)` (COBOL-style). Inconsistent.

## 15. Signed and decimal values

- `Literal.is_signed` defaults False; leading `+` not treated as signed (P-10 from parser audit, latent P3).
- Decimal places bug (P-1/S-7).

## 16. Paragraph and section execution

- `_parse_procedure_division` (1144+). Paragraphs → methods (`map_cobol_paragraph_to_method`, 4592-4614).
- PERFORM THRU expands paragraph range (3014-3045).
- Section execution: handled.

## 17. Unsupported constructs

- Parser emits `UNSUPPORTED_CONSTRUCT` as warning (P-7/S-17/S-24) → `has_errors` false → producer reports success (S-1).
- Capability analyzer catches unsupported via IR walk + source scan + structure (capability_analyzer.py).
- Pipeline blocks generation if any PROGRAM component is SKIP (pipeline.py:308-338).
- **But**: single-program producer path (producer.py) does not consult capability gate → false success (S-1, P0).

## 18. Generated Java real implementation

- `map_cobol_statement` returns `[]` for unhandled IR classes (S-4) without raising; capability gate is the only guard.
- `JavaUnsupportedExpression` is fail-closed (checked downstream).

## 19. Runtime results match COBOL reference

- Differential verification: `engine/verification/*`, `engine/comparators/*`, `engine/verdict/*`, `engine/candidate/*`.
- Pending Java generation audit findings (subagent in progress) for verdict logic / mock comparators.

## 20. CI-blocking test defect

- See AUDIT_01 §4 / C-1. Fixed.

## Conclusion

The pipeline has strong capability-gating architecture, but two critical honesty gaps:
1. Single-program producer path reports success for unsupported constructs (S-1, P0).
2. Application generator reports success even when statements are dropped (S-2, P0/P1).

Both are mitigated by the capability gate in the multi-program pipeline, but the producer path is a real false-success vector. Numeric precision (P-1/S-7) and PERFORM semantics (S-10/S-11) are concrete correctness defects.