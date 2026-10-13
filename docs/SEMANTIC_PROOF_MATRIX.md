# Semantic Proof Matrix

Classification of COBOL constructs in the deterministic COBOL → Java lane.
Every row names the current verdict and the evidence/failure mode.  A SUPPORTED
claim means the parser produces IR *and* the mapper maps it to Java.  A
*source-level* UNSUPPORTED row means the construct exists in source but the
parser never produces IR for it; absence of IR proves the mapper cannot see it,
so such a program is reported UNSUPPORTED rather than silently SUPPORTED.

| Construct | Verdict | Evidence path | Failure mode when unsupported |
|---|---|---|---|
| MOVE | SUPPORTED | parser → MoveStatement → assignment mapping | — |
| ADD / SUBTRACT / MULTIPLY / COMPUTE | SUPPORTED | parser → arithmetic IR → Java arithmetic | arithmetic IR fallback emits diagnostic |
| DIVIDE (BY form) | SUPPORTED | parser + `DivisionStatement` when GIVING present | `DIVIDE … BY` without GIVING, line-item rendering, and division by a non-present target are rejected by the regex and reported by diagnostics |
| DIVIDE (INTO form) | SUPPORTED | `DIVIDE a INTO b [GIVING c]` parsed into numerator/denominator of the same IR node; `b/a → c` (or `b`) | `DIVIDE a INTO b REMAINDER r` needs the standard IR shape; diagnostics emitted when unmatched |
| IF/ELSE | SUPPORTED | parser lowers to JavaIf/JavaReturn | — |
| EVALUATE | SUPPORTED at IR level; source-level UNSUPPORTED when no `IfStatement` results | lowering to IfStatement preserved | missing lowering emits source-level UNSUPPORTED |
| PERFORM (plain paragraph) | SUPPORTED | parser → PerformStatement → Java method/branch mapping | out-of-line / UNTIL / THRU for a range outside known paragraphs |
| PERFORM TIMES (and the legacy `PERFORM TIMES IR` node) | IR-level SUPPORTED; source-level UNSUPPORTED when dropped | same parser node; missing node ⇒ never executed by the mapper | `PERFORM … TIMES` with empty IR diagnosis |
| READ | SUPPORTED-subset | `READ file [AT END/NOT AT END]` parses a bounded clause | clause-less `READ file.` consumes no following statements; unterminated `AT END` yields diagnostic; INVALID KEY clauses surface UNSUPPORTED at source level |
| WRITE | SUPPORTED | parser → WriteStatement | — |
| OPEN | SUPPORTED | parser → OpenStatement | — |
| CLOSE | source-level UNSUPPORTED | parser has no CloseStatement path (generator branches exist) | any `CLOSE` in source marks the program UNSUPPORTED |
| START | source-level UNSUPPORTED | no parser construct; generator branches exist | same |
| REWRITE | source-level UNSUPPORTED | no parser construct; generator branches exist | same |
| DELETE | source-level UNSUPPORTED | no parser construct; generator branches exist | same |
| INVALID KEY | source-level UNSUPPORTED | `invalid_key_body`/`not_invalid_key_body` are never populated by the parser; mapper consumes them when present | any INVALID KEY instance marks the program UNSUPPORTED |
| COMP | PARTIAL | parser records `USAGE COMP`/synonyms on DataItem; numeric value semantics mapped; record-area byte encoding not certified | marked PARTIAL by parser → analyzer; use DISPLAY-equivalent numerics when byte layout matters |
| COMP-1 | PARTIAL | USAGE COMP-1 recorded; value semantics mapped; byte encoding not certified | marked PARTIAL; prefer DISPLAY for exact single-precision layout |
| COMP-2 | PARTIAL | USAGE COMP-2 recorded; value semantics mapped; byte encoding not certified | marked PARTIAL; prefer DISPLAY for exact double-precision layout |
| COMP-3 | PARTIAL | USAGE COMP-3 (packed decimal) recorded; numeric value semantics mapped; packed sign/byte encoding not certified | marked PARTIAL; value semantics only — record layout excluded |
| COMP-5 | PARTIAL | USAGE COMP-5 (native binary) recorded; value semantics mapped; byte encoding not certified | marked PARTIAL; record-layout-dependent behavior excluded |
| REDEFINES | UNKNOWN | parser records `DataItem.redefines`; mapper has no overlay lowering (generated Java for `workload-redefines` does not compile) | marked UNKNOWN until full-ladder runtime proof; never SUPPORTED |
| OCCURS | UNKNOWN | parser records `DataItem.occurs`; mapper has no table lowering (generated Java for `workload-occurs` does not compile) | marked UNKNOWN until full-ladder runtime proof; `OCCURS DEPENDING ON` blocked |
| 88-LEVEL | UNKNOWN | parser records level-88 condition names; mapper has no condition-name lowering (generated Java for `workload-level88` does not compile) | marked UNKNOWN until full-ladder runtime proof; never SUPPORTED |
| BY VALUE / BY CONTENT | **deliberately unclassified (blocked)** | mapper implements sync-in / no-sync-out (callee writes lost — correct COBOL semantics), but there is no registry key by design | no key ⇒ no support verdict can be derived from a passing mode; locked by `test_by_value_and_by_content_are_never_claimed_supported` |
| ROUNDED | SUPPORTED | parser preserves the ROUNDED flag on ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE; mapper selects `RoundingMode.HALF_UP` on the receiver (default stays `DOWN`) | `test_decimal_arithmetic_semantics.py` asserts `setScale(0, java.math.RoundingMode.HALF_UP)` |
| FIGURATIVE CONSTANT | SUPPORTED | parser emits `ir.FigurativeConstant` (ZERO / SPACES / QUOTES / LOW-VALUE / HIGH-VALUE / `ALL "<pattern>"`); `figurative_to_width(kind, fill, width)` is the single fill rule — the value is **materialized at the declared PIC width** for both `MOVE` and `VALUE` (pattern replication truncated at the final copy per COBOL 13.18.40.9; `ZEROS` on an alphanumeric receiver stores `00000`), and `= SPACES` compares **every** character (`C.replace(" ", "").isEmpty()`) rather than a single character | previously parsed to a `FieldReference` named after the reserved word, mapping to an undeclared Java identifier (`A = ZERO;` — non-compiling) with zero diagnostics and a false SUPPORTED verdict (BL-018); then the emission layer padded one character instead of filling (`"AB   "` for `ALL "AB"`) and the `VALUE` path emitted raw COBOL text (`static String WS_V = "ALL "*    ";` — non-compiling) under a SUPPORTED verdict (BL-030, GnuCOBOL 3.1.2 oracle `ORACLE_MATCH=YES` 11/11); `test_figurative_constants.py`, `test_figurative_fill_semantics.py` |
| INLINE SCOPED STATEMENT | SUPPORTED | a statement on the same line as `WHEN` / `IF ... THEN` / `ELSE` is split from the condition and parsed into the arm body; a scope-opening verb owns through its matching terminator | previously absorbed into the condition (`A = 1 OR A = DISPLAY OR A = "ONE"`) or skipped whole, deleting the statement with zero diagnostics; `test_scoped_construct_statements.py` |
| EVALUATE `WHEN ... ALSO` | SUPPORTED-subset | the arm spec is split on `ALSO` and the real alternatives are OR-ed; a `THRU` range inside an `ALSO` group contributes both bounds | `ALSO` is a keyword, never a value; a malformed range is diagnosed, not dropped |
| EVALUATE `WHEN OTHER` | SUPPORTED | maps to the `else_body` of the lowered `IfStatement` | previously mis-observed only as a side effect of the inline defect; locked by tests |
| NEGATED RELATIONAL (`NOT =/>=/<`) | SUPPORTED | folded into the operator itself (`NOT >` -> `<=`, `NOT =` -> `!=`) | Java cannot express this as a prefix: `!A > B` compares a boolean and `A !> B` does not compile; the previous blind `replace("NOT ", "!")` emitted both. `test_negated_conditions.py` |
| EXPONENTIATION (`**`) | UNSUPPORTED (fails closed) | parsed as `ir.IntrinsicCall(name='**')` with an explicit `UNSUPPORTED_CONSTRUCT` diagnostic; classified UNSUPPORTED through real discovery | previously parsed as two `*` operators producing `2 * <empty field> * 3` — a wrong numeric result with no diagnostic (§18) |
| INTRINSIC (`FUNCTION MIN(...)`) | UNSUPPORTED (fails closed) | parsed as `ir.IntrinsicCall(name=...)` with an explicit diagnostic; a field named `FUNCTION-CODE` still parses as a field reference | previously fell through to `FieldReference(name='FUNCTION MIN(1, 2)')` — an impossible identifier (BL-018 defect class) |
| UNMAPPED EXPRESSION IN CODEGEN | UNSUPPORTED (fails closed) | an unmapped `Expression` maps to a deliberately undefined symbol (`UNSUPPORTED_INTRINSIC$POWER`, `UNSUPPORTED_EXPRESSION$<NODE>`) that `javac` reports by name; the `$` separator is illegal in a COBOL data name, so no field can ever declare it | previously the mapper's `str(expr)` fallthrough printed the Python dataclass repr into Java (`WS_A = Math.abs(IntrinsicCall(name='**', ...))`) — malformed output that failed closed only because `javac` could not parse a repr, and fail-open for any future node; BL-025 |
| GO TO | UNSUPPORTED | `GO TO` has no Java mapping (emitted as a comment) | — |
| GOBACK | UNSUPPORTED | registry entry; `GOBACK.` is no longer mistaken for a paragraph heading | — |
| EXIT PROGRAM | SUPPORTED | parser → `ExitProgramStatement` → `JavaReturn` in the generated body | bare `EXIT.` is diagnosed as unsupported; paragraph/section `EXIT` inside PERFORM remains UNSUPPORTED |
| STRING | SUPPORTED (certified subset) | parser → `StringStatement` (delimiter exprs, pointer, overflow, varying pointer) → delimiter-excluding write with tail preservation; **BL-028**: the written value is clipped to the receiver's declared PIC width (`T.substring(0, Math.min(T.length(), W))`) and the pointer follows the oracle-pinned boundary rule — inside `1 .. W+1` it writes and advances capped at `W+1`, outside it is a no-op with the pointer unchanged (GnuCOBOL 3.1.2, `ORACLE_MATCH=YES` 8/8 + boundary 3/3) | identifier delimiters, `ON OVERFLOW`, `VARYING IN` and non-integer pointers fail closed with an `UNSUPPORTED_STRING$…` symbol + diagnostic (BL-027/BL-029); a receiver with no declared width (group/undeclared) keeps the legacy emission and fails closed at `javac`; `test_string_delimited_semantics.py` |
| UNSTRING | PARTIAL | only the certified delimited subset maps | delimiter object forms not certified |
| DISPLAY | SUPPORTED | parser → DisplayStatement | — |
| STOP RUN | SUPPORTED | parser → StopRunStatement → Java return | — |
| CALL | SUPPORTED | parser → CallStatement → Spring-style dependency mapping | dynamic CALL with an unresolved target is still parsed (program_name may be blank); the dependency is marked by the caller. Phase 3 audit filed OPEN defects: multi-line CALL statements are unparsed (BL-036), `ON EXCEPTION` is swallowed into `USING` producing false arity (BL-037), and `ProgramCall.resolution` stays stale for resolved static calls (BL-038) — all P2, each fails closed or is cosmetic, none can produce a false READY |
| EXEC SQL / EXEC CICS, SORT, MERGE, ACCEPT, INITIALIZE, INSPECT, SEARCH, SET, ALTER, NEXT SENTENCE, SIZE ERROR | UNSUPPORTED | registry source patterns plus diagnostics | no deterministic Java mapping |
| COPY (copybook) | See COPYBOOK components | resolved copybooks contribute to the enclosing source scan; nested `COPY` inside a copybook is expanded at materialization (BL-031: missing/ambiguous/cyclic nested targets fail generation with explicit diagnostics); `COPY … REPLACING` substitutes supported operand forms before data parsing (BL-032: unappliable/malformed clauses fail generation with diagnostics naming `REPLACING`, and capability classifies the program `UNSUPPORTED` through the same clause parser) | unresolved copybooks are reported on the COPYBOOK component — currently classified `SUPPORTED` with only `resolution=…` visible (BL-033 OPEN: plan may say `READY` while generation fails) |

## Discovery honesty

- Fixed-format sources with 6-column sequence numbers are now recognised: the
  area prefix is stripped before parsing and such files never disappear
  silently from `discovery_errors`.
- Every statement the parser recognises but cannot turn into IR is emitted as a
  `UNSUPPORTED_CONSTRUCT` diagnostic and surfaces as an
  `unparsed_statement` finding on the program component, forcing UNSUPPORTED.
- Unknown statements are emitted as the same class of diagnostic, so a renamed
  or unhandled source construct cannot silently keep the program SUPPORTED.

## Phase-C remediation exercised by

- `tests/adversarial/test_silent_loss_remediation.py`
- `tests/adversarial/test_semantic_mutations.py`
- `tests/test_silent_loss_registry.py`

## Phase-D proof: numeric VALUE/literal semantics (D1)

Deterministic COBOL numeric VALUE semantics implemented in
`engine/transformation/numeric_semantics.py` and applied to every numeric
initializer and numeric expression literal.  Contract (oracle-verified):

| Semantics | Rationale | Evidence |
|---|---|---|
| leading-zero numeric literals are decimal | `VALUE 007`/`009` must never be emitted as Java octal (`007`) or a Java compile error (`009`) | GnuCOBOL DISPLAY `007`/`009`; generated Java `static int D = 7;` compiles and prints `000028` |
| fractional digits are truncated, not rounded | `PIC 9(2)V99 VALUE 1.234` stores `1.23` | GnuCOBOL DISPLAY `01.23`; generated `static double F = 1.23;` |
| overflow keeps least-significant declared digits | `PIC 9(3) VALUE 1234` stores `234` | GnuCOBOL DISPLAY `234`; `PIC 9(10) VALUE 12345678901` → `2345678901` |
| ZERO/ZEROS/ZEROES are `0` | figurative zero is a valid numeric VALUE | GnuCOBOL `VALUE ZEROS` displays `000` |
| non-numeric numeric VALUE fails closed | `VALUE SPACE` on a numeric item is a GnuCOBOL compile error; the lane must not emit a bare Java identifier | `NumericValueError` raised; source reported UNSUPPORTED |
| signed literal on an unsigned PIC fails closed | GnuCOBOL rejects `PIC 9(3) VALUE -5` / `+007` with `error: data item not signed`; accepting it would store a magnitude the oracle never stores | `NumericValueError` from `normalize_value_for_pic(signed=False)`; `test_signed_value_on_unsigned_pic_fails_closed` |
| integral literal outside Java `int` range is typed `long` and suffixed `L` | `static long BIG = 123456789012345678;` is `error: integer number too large` even for a `long` target | GnuCOBOL stores `PIC 9(18) VALUE 123456789012345678`; generated `static long BIG = 123456789012345678L;` compiles and DISPLAYs byte-identically |
| `DISPLAY` uses a type-aware `String.format` specifier | `String.format("%06d", <double>)` is `IllegalFormatConversionException`, and `%04d` of `-12` is `-012` instead of the oracle's `-0012` | `display_format_spec()`; GnuCOBOL vs generated Java stdout byte-identical for `007`, `-0012`, `+0012`, `0012.50`, `-001.2`, `+001.2`, `123456789012345678` |
| an unsigned receiver stores the *magnitude* of a negative result | `COMPUTE UN = 0 - 5` on `PIC 9(3)` stores `005`, not `-5` | GnuCOBOL `005`/`001.2`; generated `Math.abs(...)` lane byte-identical (`test_unsigned_receiver_magnitude_byte_identical_to_gnucobol`) |
| `%f` conversions are pinned to `java.util.Locale.US` | the platform locale can substitute its own decimal separator | fractional `DISPLAY` specs are emitted as `String.format(java.util.Locale.US, "%07.2f", X)` |
| `format_width == pic_length` | width no longer double-counts fractional digits (was `pic_length + decimal_places`) | `PIC 9(6)V99`: `pic_length=8`, `format_width=8` |

Runtime differential proof (Docker-gated): `tests/integration/test_numeric_oracle_proof.py`
compiles the same sources with GnuCOBOL 3.1.2 and with the generated Java
(temurin:21), and asserts `Decimal(DISPLAY)` equals the normalized literal and
byte-identical DISPLAY stdout across four lanes: the integer VALUE lane, the
signed/decimal DISPLAY-shape lane, the unsigned-receiver magnitude lane, and the
shipped `workload-comp` / `workload-comp3` fixtures.

Host-Java (non-Docker) corroboration: `tests/transformation/test_numeric_semantics.py`
compiles and runs the generated Java for the same shapes and checks the
`String.format` specifiers against the oracle text.

Boundary (documented, not fabricated): `DISPLAY` *text* for INTEGER and DECIMAL
`DISPLAY` items (signed and unsigned, integer and implied-decimal PICs) is
PROVEN byte-identical to GnuCOBOL, as is the stored *value* of a numeric
literal/VALUE.  Still not claimed: high-precision arithmetic beyond what
IEEE-754 `double` can represent, and the *record-area byte encoding* of
`COMP`/`COMP-3`/`BINARY` items (packed sign overpunch, binary layout) — the
record WRITE lane is proven separately and is untouched by D1.

## Known unverified limitations (pre-existing Phase B boundaries, unchanged)

- Numeric `VALUE` literals with leading zeros are now normalized through the
  Phase-D contract (D1) and no longer leak Java-octal forms; the remaining
  boundary is decimal arithmetic precision on `double`.
- `COMP`/`COMP-3` items are numerics without a documented binary encoding
  contract.
- `EXIT PROGRAM` is realised as a Java return at statement level; PROGRAM
  STATUS/-level interoperability is not claimed.
- Runtime proof is claimed only for the fixtures that ship generated-project
  execution evidence under Docker; capability classification alone is not a
  runtime claim.
