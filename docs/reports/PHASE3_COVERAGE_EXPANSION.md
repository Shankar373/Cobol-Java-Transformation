# Phase 3 — COBOL coverage expansion and multi-runtime support

Started 2026-11-01 on `feat/phase3-coverage` (stacked on
`fix/audit-wave-a` → PR #8 → PR #7), after Phase 2 was accepted on
`6050335` (exact-SHA CI: 4,767 passed, 0 skipped).

Rules for every increment: deterministic, no LLM; GnuCOBOL 3.1.2 is the
only authority for a "supported" claim (each construct gets an oracle pin
plus generated Java run against it); every unsupported variant fails closed
with a named diagnostic; changes are generic — never shaped to one fixture;
each increment is checked against the full fixture corpus (generated Java
byte-diff versus the previous commit) and, where it adds an application,
run end to end through the API and re-checked independently.

## 1. Audit (coverage baseline)

Sources: the Phase 2 end-to-end run (48 applications), the capability
matrix, and the 2026-11-01 architecture audit
(`docs/audits/ARCHITECTURE_AUDIT_2026-11-01.md`).

| Gap | Effect today | Evidence |
|---|---|---|
| Fixed-format continuation lines | wrong value, transformation "succeeds" | audit P0-2 (reproduced) |
| ASSIGN spellings other than `TO "x"` | all file I/O dropped, "succeeds" | audit P0-1 (fixed in `f930db5`) |
| Indexed/relative file images not compared | 6 apps PARTIAL | Phase 2 report §2 |
| Referenced COMP / COMP-3 items | 4 apps refused | Phase 2 §4 (comp, comp3, relative, relative-file) |
| REDEFINES with numeric reinterpretation | refused | Phase 2 §4 (redefines) |
| OCCURS outside the certified subset | refused | Phase 2 §4 (occurs) |
| Signed / COMP STRING sources | refused | Phase 2 fix 12 |
| Record SEQUENTIAL files | refused | Phase 2 fix 12 |
| RETURN-CODE | undeclared Java symbol; nonzero oracle exit is UNAVAILABLE | audit §4.1 |
| CALL BY VALUE, EXEC SQL/CICS | refused | Phase 2 §4 |
| Runtimes other than Spring Boot | plain Java / Jakarta EE build, no end-to-end API run; Quarkus, Micronaut, Liberty absent | audit §4.1, §4.2 |

## 2. Plan (order of work)

1. **Source reading** — continuation lines, literal escapes, and anything
   else that makes the parser read different text than the compiler
   (every program depends on it). *Done, §3.*
2. **Application data** — RETURN-CODE; COMP/COMP-3 storage; REDEFINES
   numeric reinterpretation; OCCURS whole-record references; signed
   STRING sources.  *RETURN-CODE done, §3.2; COMP/COMP-3 by value, §3.4.*
3. **Files** — record-level comparison of INDEXED/RELATIVE files (turns the
   6 PARTIAL apps into VERIFIED when equal); record SEQUENTIAL files.
   *INDEXED done, §3.3; RELATIVE, §3.5; record SEQUENTIAL, §3.6.*
4. **Multi-runtime** — end-to-end API lanes for plain Java and Jakarta EE
   with GnuCOBOL proof, then a runtime-adapter port for the entry/host
   shape and additional runtimes (Quarkus, Micronaut, Open Liberty), each
   validated as its own target.
5. **Application corpus** — a new fixture application for each increment
   that combines the constructs the way production code does.

## 3. Results so far

### 3.1 Source reading (increment 1)

| Construct | Before | Now | Proof |
|---|---|---|---|
| `-` continuation (literal, word, numeric, chained) | read as code → wrong value, success | folded exactly as GnuCOBOL (literal padded to column 72) | `test_fixed_format_continuation.py` (source pins, Java vs oracle output, Docker oracle pin) |
| Malformed continuation | silently mis-read | UNSUPPORTED_CONSTRUCT | same file |
| `'IT''S'` / doubled `""` | DISPLAY dropped the quote; VALUE/MOVE kept it doubled | re-delimited canonically; value exact | `test_literal_quote_escapes.py` |
| VALUE `'…"'` (ends in the other quote) | closing `"` stripped | only matching delimiters removed | same file |
| Literal holding both quote characters | — | fails closed | same file |
| CALL/COPY discovery after a continued or escaped literal | phantom CALLs from literal text; real CALLs missed | scans compiler-visible text | `test_..._discovery_reads_continued_and_escaped_literals_as_data` |

Application: `fixtures/workload-notices` (continued literal/word/numeric,
both escape styles, single-quoted ASSIGN, LINE SEQUENTIAL write + read
back) — **VERIFIED** through the API (stdout, exit status, `NOTICES.TXT`
MATCH) and **AGREE** in the independent re-check (direct `cobc` vs direct
`mvn` + `java -jar`). Evidence: `docs/reports/evidence/phase3/`.

Regression: generated Java for all 48 Phase 2 applications is
byte-identical to `f930db5` (34 generate, 14 refused, unchanged); no
existing fixture used these constructs.

### 3.2 RETURN-CODE and exit status (increment 2)

GnuCOBOL behaviour measured first: the register displays as
`+000000004`, computes like `PIC S9(9)`, and the process exits with
`RETURN-CODE & 0xFF` however the run unit ends (300 → 44, -1 → 255); a
libcob runtime error writes `libcob: error:` and exits 1.

| Layer | Change |
|---|---|
| Parser | declares the register (`01 RETURN-CODE PIC S9(9) VALUE 0`) for a program that uses it; fails closed when the program CALLs or is CALLed |
| Mapper / hosts | `RUN_UNIT$EXIT_STATUS()` (`RETURN_CODE & 255`); `main` and the Spring Boot runner exit with it — programs without the register are byte-identical |
| Oracle | `classify_oracle_termination`: a nonzero exit is `return_code` only when the compile succeeded, the source uses RETURN-CODE and no libcob error was reported; otherwise `nonzero_exit` (UNAVAILABLE, as before) |
| Integrity / verdict | an oracle `return_code` requires EXIT_STATUS evidence and comparison; `unavailable_count` counts only executions that could not serve as evidence |

Application: `fixtures/workload-batch-rc` (validation job step ending
with RC 4) — **VERIFIED** through the API (stdout, EXIT_STATUS 4,
`TXNS.DAT` MATCH) and **AGREE** in the independent re-check (both sides
exit 4).  Generated Java for the 48 Phase 2 applications is unchanged
versus `4bcc514`.

### 3.3 INDEXED files compared by records (increment 3)

GnuCOBOL 3.1.2 keeps an INDEXED file as a Berkeley DB B-tree; the
generated runtime keeps `<file>.idx` (a `K<keylen>` line, then
`key\x01data` per record, in key order).  The images can never be
byte-equal, so until now every program writing an INDEXED file was
PARTIAL however well it behaved.

| Layer | Change |
|---|---|
| Reader | `engine/comparators/indexed_records.py`: walks the B-tree from the metadata root (internal → leaf pages) and returns the live records in key order; refuses (`UnreadableImage`) anything it does not certify — wrong magic/version/page size, encryption, unknown page type, overflow or duplicate items, out-of-page offsets, truncation. Shares nothing with the COBOL parser or the generated runtime |
| Pipeline | `_compare_indexed_records`: when the oracle left `<file>` and the candidate `<file>.idx` (each on its own side only) and both decode, one TEXT_FILE artifact `generated-file:<file>#records` (one `hex\tprintable` line per record) is compared byte-exactly; otherwise the image keeps the INCONCLUSIVE path (PARTIAL) |
| RELATIVE | unchanged — INCONCLUSIVE/PARTIAL: the Java emulation keeps RELATIVE records in memory and writes no image, so there is nothing to compare |
| Independent re-check | `verify_independent.py` decodes the B-tree differently (linear scan of every leaf page, then sort by key) and records the decoded records of both sides |

Reader proof: on `MANY.DAT` (400 descending-key writes, every 7th
deleted, every 5th rewritten — a multi-level tree) the reader returns
exactly GnuCOBOL's own sequential READ NEXT (343 records); the Docker test
regenerates the image and checks again.  On fresh oracle images of all six
applications below, the platform reader and the independent reader return
identical records (those images are single-leaf; multi-level trees are
covered by `MANY.DAT`).

Negative cases (`tests/test_indexed_record_comparison.py`, real pipeline,
stub executions): a changed, missing, extra or reordered record →
`#records` MISMATCH → **FAILED**; an overflow image (`BIG.DAT`), an image
on one side only, or a RELATIVE file → INCONCLUSIVE, never VERIFIED;
malformed headers/pages/emulations are refused by the readers.

Applications (all previously PARTIAL), each run alone through the API and
then alone through the independent re-check:

| Application | API verdict | STDOUT / EXIT / `#records` | Records (both sides) | Independent |
|---|---|---|---|---|
| workload-delete | **VERIFIED** | MATCH / MATCH (0) / MATCH | 1 | AGREE |
| workload-indexed | **VERIFIED** | MATCH / MATCH (0) / MATCH | 2 | AGREE |
| workload-indexed-file | **VERIFIED** | MATCH / MATCH (0) / MATCH | 2 | AGREE |
| workload-indexed-rewrite-delete-start | **VERIFIED** | MATCH / MATCH (0) / MATCH | 2 | AGREE |
| workload-rewrite | **VERIFIED** | MATCH / MATCH (0) / MATCH | 2 | AGREE |
| workload-start-invalidkey | **VERIFIED** | MATCH / MATCH (0) / MATCH | 2 | AGREE |

The independent records (hex) of each side are in
`evidence/phase3/independent_verification.jsonl`.  The two RELATIVE
fixtures (`workload-relative`, `workload-relative-file`) were still
refused at generation for their referenced COMP/COMP-3 items at this
point, exactly as in Phase 2 (resolved in §3.4).

### 3.4 Binary and packed items by value; numeric lowerings (increment 4)

Audit: four Phase 2 applications (`comp`, `comp3`, `relative`,
`relative-file`) were refused only because they reference COMP/COMP-3
items, all standalone and all used by value.  Measured first: GnuCOBOL
3.1.2 (`default.conf`: `binary-truncate: yes`, `pretty-display: yes`)
prints identical output for `fixtures/workload-binary-values` with and
without its USAGE clauses, so such an item has DISPLAY value semantics,
and the Java already stores it as a number.

Forcing the refusal off (probe only, never committed) showed why it must
stay off for anything else: `workload-relative` did not compile (the FD
record `REL-REC` reached the Java as an undeclared name), and the new
application exposed four lowerings that were wrong for DISPLAY items too —
programs the analyzer already classified SUPPORTED:

| Defect (generated Java) | GnuCOBOL | Now |
|---|---|---|
| `WS_U = WS_DIGITS;` — PIC X into numeric did not compile | digit content read as unsigned integer, low-order digits kept | digit-guarded `parseInt`/`BigDecimal`; other content stops the run |
| `WS_PACKED < 0 && …` — BigDecimal with `<` did not compile | — | compound conditions with a decimal operand split per atom (`compareTo`) |
| `String.format("%-8s", WS_SHORT)` gave `10      ` | `0010    ` (unsigned digits at PIC width) | `String.format("%04d", Math.abs(..))` |
| `Math.toIntExact(WS_BIG)` / `Math.multiplyExact` threw | exact result truncated to the receiver | exact BigDecimal when an operation can exceed its Java type; also fixes a silent `int * int` overflow into a long receiver |

| Layer | Change |
|---|---|
| Capability analyzer | `_is_value_only_item`: COMP/BINARY/COMP-3/PACKED-DECIMAL, standalone WORKING-STORAGE item, no COPY/REPLACE; every occurrence (compiler-visible text, comments and literals masked) is its declaration, a RELATIVE KEY, or a PROCEDURE reference governed by ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE/MOVE/DISPLAY/IF/EVALUATE/PERFORM/INITIALIZE, never reference-modified, after `OF`/`IN` or in a statement naming LENGTH/BYTE-LENGTH. COMP-5, COMP-1, COMP-2 unchanged (PARTIAL) |
| Parser / IR | `FileDefinition.record_groups`: each FD 01 record as a data-description tree; FD record names are checked like groups (`file_record_groups` / `uncertified_file_records`) |
| Mapper | group views include certified FD records; the four lowerings above |

Applications through the API (no bypass), each then independently re-checked:

| Application | Before | Now | Independent |
|---|---|---|---|
| workload-binary-values (new) | — | **VERIFIED** | AGREE |
| workload-comp | refused | **VERIFIED** | AGREE |
| workload-comp3 | refused | **VERIFIED** | AGREE |
| workload-multiply-giving-verified | VERIFIED | **VERIFIED** (generated Java changed: exact product) | AGREE |
| workload-universal | VERIFIED | **VERIFIED** (same) | AGREE |
| workload-relative | refused | PARTIAL (stdout, exit MATCH; RELATIVE image INCONCLUSIVE) | — |
| workload-relative-file | refused | PARTIAL (same) | — |

Regression: generated Java for the other 42 Phase 2 applications is
byte-identical to `2ebedc4`.  Existing tests that pinned the throwing
`Math.*Exact` lowering were changed to assert the exact form and the
oracle-pinned values (`test_decimal_arithmetic_semantics.py`,
`test_arithmetic_giving.py`); the tests that pinned "referenced COMP is
PARTIAL" now pin the byte-level cases (`test_usage_capability.py`).

Found and left refused (named diagnostics, recorded in KNOWN_ISSUES):
ON SIZE ERROR, signed literals in conditions (`> -1`), a figurative
constant in a numeric comparison (`> ZERO`).

### 3.5 RELATIVE files compared by records; file OPEN statuses (increment 5)

Measured on GnuCOBOL 3.1.2 first (`tests/data/relative/RELPROBE.cob`):
a RELATIVE file is one slot per RRN — an 8-byte little-endian record size
plus the whole record area, RRN `n` at `(n - 1) * (8 + length)`; never-
written and DELETEd slots have size 0 (DELETE keeps the old bytes); the
file ends at the last slot.  GnuCOBOL's own READ NEXT over a file with
gaps, a DELETE and REWRITEs (`RELREAD.cob`) lists exactly the live slots.

| Layer | Change |
|---|---|
| Reader | `gnucobol_relative_records`: the record length is not in the image, so it is inferred — exactly one length must make every slot's size 0 or that length, with a live slot; anything else (no live record, ambiguous layout, truncation) is refused. `emulated_relative_records` reads the Java `.rel` |
| Pipeline | `_compare_file_records` (was INDEXED-only): RELATIVE images compared as (RRN, record) lines in one `<file>#records` artifact — a record in the wrong slot is a MISMATCH |
| Java runtime | RELATIVE records persisted to `<file>.rel` after every change (they lived in memory only) |
| Independent re-check | its own RELATIVE reader (`struct.iter_unpack` over every candidate layout), RELATIVE files named from the source by its own regex |

Found while auditing the runtime against the oracle, and fixed (each pinned):

| Java runtime before | GnuCOBOL 3.1.2 | Now |
|---|---|---|
| WRITE onto an occupied RRN overwrote it, status 00 | INVALID KEY, status 22, record kept | 22, record kept |
| OPEN INPUT / I-O / EXTEND of a missing RELATIVE or INDEXED file: 00 (empty file) | 35 | 35 |
| OPEN INPUT of a missing sequential file: 23; EXTEND created it | 35 | 35 |
| `SELECT OPTIONAL` accepted and ignored (silent loss) | missing file opens with 05, reads empty | fails closed (UNSUPPORTED_CONSTRUCT) |

Applications through the API, each then independently re-checked.  The
runtime change touches every program with files, so every file
application was re-run on the final template:

| Application | Before | Now | Independent |
|---|---|---|---|
| workload-relative | PARTIAL (RELATIVE image INCONCLUSIVE) | **VERIFIED** (`REL.DAT#records` MATCH) | AGREE |
| workload-relative-file | PARTIAL (same) | **VERIFIED** (`RELFILE.DAT#records` MATCH; RRN 1 deleted) | AGREE |
| 11 other file applications (copybook-file-multi, delete, file-write-read, indexed, indexed-file, indexed-rewrite-delete-start, integrated, payroll, rewrite, start-invalidkey, inventory) | VERIFIED | **VERIFIED** | AGREE |
| workload-studentproc | UNAVAILABLE | UNAVAILABLE — unchanged: GnuCOBOL rejects the source | — |

Regression: only the generated `CobolFileIo.java` changed, in exactly those
14 applications; all other generated Java is byte-identical to `83b9df6`.
A runtime test that pinned the old `23` for a missing file now pins `35`
(`test_file_invalid_key_lane.py`).

Still INCONCLUSIVE (PARTIAL), by design: a RELATIVE image with no live
record or an ambiguous layout; a file a program reads without creating it
in the same run.

### 3.6 Record SEQUENTIAL files, WRITE … FROM, line/page control (increment 6)

ORGANIZATION SEQUENTIAL — explicit, or the default without an
ORGANIZATION clause — is the everyday batch file, and failed closed
entirely.  Measured on GnuCOBOL 3.1.2: one fixed-length record description
gives bare record areas back to back (no terminator, trailing spaces
kept); several record descriptions of different lengths switch to
variable records behind a 4-byte header (2-byte big-endian length + 2 zero
bytes) — pinned, and refused.

| Layer | Change |
|---|---|
| Parser / IR | `FileDefinition.record_sequential`; `_validate_record_sequential` certifies one record description that is an elementary PIC X item or a certified group view, with no VARYING / CONTAINS n TO m / RECORDING MODE / LINAGE and no OPEN I-O, REWRITE, DELETE or START on the file |
| Runtime | `CobolFileIo.writeRecord` / `readRecord` (fixed width, no terminator) — purely additive |
| Mapper | WRITE pads the record to its width and calls `writeRecord`; READ calls `readRecord` |
| Analyzer | sequential OPEN EXTEND is SUPPORTED (appends exactly like GnuCOBOL, pinned for LINE and record SEQUENTIAL); OPEN I-O stays PARTIAL |

Found by the oracle while building the application, fixed for every
organization:

| Before | GnuCOBOL 3.1.2 | Now |
|---|---|---|
| `WRITE r FROM x` wrote r's previous fields (the record assembly ignored FROM) | MOVE x TO r, then WRITE r | the record fields take x's characters and exactly those are written |
| — | into a group record the move copies x's stored bytes: `S9(5)` -42 is written `0004r` | unsigned DISPLAY integers reproduced; signed / scaled / COMP senders fail closed |
| `WRITE … AFTER ADVANCING 2 LINES` (one line) dropped with no diagnostic | line/page control characters around the record | fails closed (UNSUPPORTED_CONSTRUCT) |

Application: `fixtures/workload-record-sequential` (extract with field
MOVEs, OPEN EXTEND, `WRITE … FROM` a group, READ/AT END/FILE STATUS
totals, a summary record written FROM a group with FILLER literals) —
**VERIFIED** through the API (stdout, exit status, `EXTRACT.DAT` and
`SUMMARY.DAT` byte-exact MATCH) and **AGREE** in the independent re-check.

Regression: only the generated `CobolFileIo.java` changed, in the 14 file
applications, by the two added methods (no line removed); their service
code is byte-identical to `9111a50`, so nothing calls the new methods.
All other generated Java is byte-identical.  No fixture used WRITE … FROM
or ADVANCING.

### 3.7 Condition operands (increment 7)

Audit of every condition form left open by increment 4, each run through
the analyzer and the generator, then measured on GnuCOBOL 3.1.2:

| Form | Before | GnuCOBOL | Now |
|---|---|---|---|
| `X IS NEGATIVE` / `IS POSITIVE` | **SUPPORTED, but** parsed as a condition-name; Java `X == NEGATIVE` (undeclared, did not compile) | algebraic sign; `MOVE -0` is ZERO, not NEGATIVE | relation to ZERO (`sign_conditions.py`, shared by parser and mapper) |
| `X IS NOT NEGATIVE` | refused | — | `X >= ZERO` |
| `> -1`, `= +3`, `< -1.25`, `< 1.25`, `-5 < X` | refused (operand matcher accepted only `\w+`) | algebraic | signed/decimal literal operands |
| `X > ZERO`, `X = ZEROS` (numeric) | generated correctly, classified UNKNOWN | algebraic | SUPPORTED: the analyzer's figurative walk now enters Conditions |
| `A = ZERO` (PIC X) | refused | every character '0' (`'0000'` yes, `'00 0'` no) | whole-field `'0'` fill |
| `X = 1 OR 2` (numeric) | **SUPPORTED, but** Java `X == 1 \|\| 2` (did not compile) | abbreviated combined relation | fails closed, as on the alphanumeric path |

Proof: 28 conditions (simple, compound, decimal, negative zero) pinned on
GnuCOBOL and matched by the generated Java (`tests/test_condition_operands.py`).
Application: `fixtures/workload-balance-check` (EVALUATE TRUE over sign
conditions and a signed limit, PERFORM UNTIL … IS ZERO, compound signed
ranges, a PIC X status against ZERO/ZEROS) — **VERIFIED** through the API
and **AGREE** in the independent re-check.

Regression: generated Java for all 48 Phase 2 applications and the four
earlier Phase 3 applications is byte-identical to `cf0b12d`.

Left refused: ordering against an alphanumeric ZERO (`A > ZERO` on PIC X);
an IF/ELSE written on one source line (named diagnostic; found while
building the probe).

### 3.8 ON SIZE ERROR (increment 8)

Measured on GnuCOBOL 3.1.2 first (12 cases, `tests/test_size_error.py`):
a result needing more integer digits than the receiver — after ROUNDED —
is a size error, and so is a zero divisor; the receiver keeps its value
and the SIZE ERROR body runs.  Truncated fraction digits are not a size
error, nor is a negative result stored (as its magnitude) in an unsigned
receiver.  Without the phrase, a zero divisor leaves the receiver unchanged
too — the generated Java throws instead (KNOWN_ISSUES; the run fails, never
verifies).

| Layer | Change |
|---|---|
| IR | `size_error_body` / `not_size_error_body` on ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE; every statement walker (parser, analyzer, mapper) visits them |
| Parser | `_parse_with_size_error`: the verb parser sees the header only; bodies collected inline, on following lines, up to `END-<verb>` or the period |
| Mapper | `_emit_arithmetic`: zero-divisor test, exact BigDecimal result, magnitude bound 10^integer-digits, store or keep; without the phrase the output is byte-identical to before |
| Analyzer | `SIZE ERROR` classified from the parsed bodies (SUPPORTED); a phrase the parser did not attach stays source-only (UNSUPPORTED) |

The shared clause collector (also used by READ/WRITE/REWRITE/START/DELETE)
had four defects, found while testing inline forms and fixed:

| Before | Now |
|---|---|
| `READ F AT END … NOT AT END … END-READ` on one line put both bodies under AT END, with no diagnostic | each body under its own clause |
| a body statement followed by the terminator on the same line (`DISPLAY 'K' END-READ`) swallowed the terminator; the scope ran into the following statements | the terminator closes the clause |
| a clause header line that also carried the terminator (`AT END DISPLAY 'E' END-READ`) was re-read as a statement — the program was refused ("Skipped unsupported statement") | the line belongs to the verb |
| a DISPLAY in an ON SIZE ERROR body read the next `NOT ON SIZE ERROR` line as four operands | clause headers end a DISPLAY |

Application: `fixtures/workload-interest-accrual` (COMPUTE ROUNDED capped
by ON SIZE ERROR, DIVIDE by zero terms, NOT ON SIZE ERROR bodies, a
saturating accumulator in a period-terminated sentence) — **VERIFIED**
through the API and **AGREE** in the independent re-check.

Regression: generated Java for all 48 Phase 2 applications and the five
earlier Phase 3 applications is byte-identical to `84d92d4`.  Tests that
pinned "SIZE ERROR is refused" now pin the attached bodies; the
`divide_on_size_error` false-success case moved from "fails closed" to
"supported", with GnuCOBOL's output (`ERR`, `0`).
