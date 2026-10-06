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

## Known unverified limitations (pre-existing Phase B boundaries, unchanged)

- Numeric `VALUE` literals with leading zeros are passed through as Java
  literals; `COMP`/`COMP-3` items are numerics without a documented binary
  encoding contract.
- `pic_length` counts digits+decimal in `P`/`V` configurations that can
  disagree with the Java numeric width; `format_width` values are advisory.
- `EXIT PROGRAM` is realised as a Java return at statement level; PROGRAM
  STATUS/-level interoperability is not claimed.
- Runtime proof is claimed only for the fixtures that ship generated-project
  execution evidence under Docker; capability classification alone is not a
  runtime claim.
