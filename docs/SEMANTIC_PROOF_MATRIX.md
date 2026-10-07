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
| GO TO | UNSUPPORTED | `GO TO` has no Java mapping (emitted as a comment) | — |
| GOBACK | UNSUPPORTED | registry entry; `GOBACK.` is no longer mistaken for a paragraph heading | — |
| EXIT PROGRAM | SUPPORTED | parser → `ExitProgramStatement` → `JavaReturn` in the generated body | bare `EXIT.` is diagnosed as unsupported; paragraph/section `EXIT` inside PERFORM remains UNSUPPORTED |
| STRING | SUPPORTED | parser → StringStatement | — |
| UNSTRING | PARTIAL | only the certified delimited subset maps | delimiter object forms not certified |
| DISPLAY | SUPPORTED | parser → DisplayStatement | — |
| STOP RUN | SUPPORTED | parser → StopRunStatement → Java return | — |
| CALL | SUPPORTED | parser → CallStatement → Spring-style dependency mapping | dynamic CALL with an unresolved target is still parsed (program_name may be blank); the dependency is marked by the caller |
| EXEC SQL / EXEC CICS, SORT, MERGE, ACCEPT, INITIALIZE, INSPECT, SEARCH, SET, ALTER, NEXT SENTENCE, SIZE ERROR | UNSUPPORTED | registry source patterns plus diagnostics | no deterministic Java mapping |
| COPY (copybook) | See COPYBOOK components | resolved copybooks contribute to the enclosing source scan | unresolved copybooks are reported on the COPYBOOK component |

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
