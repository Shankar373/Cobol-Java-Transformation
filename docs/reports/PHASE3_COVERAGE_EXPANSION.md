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
   STRING sources.
3. **Files** — record-level comparison of INDEXED/RELATIVE files (turns the
   6 PARTIAL apps into VERIFIED when equal); record SEQUENTIAL files.
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
