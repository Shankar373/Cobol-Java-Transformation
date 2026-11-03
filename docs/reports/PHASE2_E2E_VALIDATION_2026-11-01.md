# Phase 2 — end-to-end application validation (2026-11-01)

Branch `feat/phase2-e2e-validation` (stacked on `fix/false-success-baseline`,
PR #7).  Deterministic, no LLM anywhere in the path.  Oracle: GnuCOBOL 3.1.2
(`gnucobol-ocesql:latest`); candidate: the generated Spring Boot application,
built offline with Maven and run with `java -jar` in Docker.

## 1. Method

Every directory `fixtures/*/cobol` (48 applications, 3 of them corrected copies
added in this phase) was run through the **real API**, one at a time
(`scripts/e2e/run_fixture_apps.py`):

ZIP → `POST /applications` → `/ingest` → `GET /discovery` → `/modernize`
(discovery, capability analysis, plan, Java generation, Spring Boot assembly,
Docker Maven build, execution, GnuCOBOL differential, evidence, verdict).

Every VERIFIED result was then **re-checked independently**
(`scripts/e2e/verify_independent.py`), sharing no code with the platform's
adapters or comparators: `cobc -x` on the sources directly, `mvn package` +
`java -jar` on the generated project directly, both in an empty working
directory, comparing stdout, stderr, exit code and **every file** left
anywhere in the working directory.

Evidence: `docs/reports/evidence/phase2/e2e_results.jsonl` (per app: stage,
verdict, every comparison and its result) and
`docs/reports/evidence/phase2/independent_verification.jsonl`.

## 2. Results

| Outcome | Apps | Notes |
|---|---:|---|
| **VERIFIED** | **27** | Independent re-check: **27/27 AGREE** (stdout, stderr, exit code, every file byte-identical) |
| PARTIAL | 6 | `delete`, `indexed`, `indexed-file`, `indexed-rewrite-delete-start`, `rewrite`, `start-invalidkey`: behaviour matches, but the INDEXED/RELATIVE file image is an emulation and is not compared |
| UNAVAILABLE | 1 | `studentproc`: GnuCOBOL rejects the source (a data name is cut at column 72); the verdict names the compile failure |
| Refused before generation | 14 | Each with a named reason — see §4 |
| **False success** | **0** | |

VERIFIED: add-giving-verified, arithmetic, by-content, by-reference,
call-chain, call-linkage-valid, copybook, copybook-file-multi,
divide-giving-verified, divide-into-verified, evaluate, file-write-read,
gradecalc, integrated, level88, minimal, multiply, multiply-giving-verified,
multiprog-valid, payroll, perform-varying, perform-varying-verified, subtract,
subtract-giving-verified, subtract-multisource-verified, universal,
workload_inventory.

### Change against the first run of this phase

| App | First run | Final | Why |
|---|---|---|---|
| payroll, subtract, subtract-multisource-verified, workload_inventory | refused | VERIFIED | continued PERFORM headers, separator period, multi-subtrahend SUBTRACT, STRING numeric storage, LINE SEQUENTIAL trailing spaces, keyword-bearing VALUE literals |
| delete, indexed-file, indexed-rewrite-delete-start, rewrite, start-invalidkey | VERIFIED | **PARTIAL** | their indexed files were never compared (working-directory files were not collected); now collected, and the emulated image is reported INCONCLUSIVE |
| indexed | refused | PARTIAL | an unreferenced COMP item no longer makes the program PARTIAL |
| call-linkage, multiprog, dynamic-call | UNAVAILABLE | refused | invalid COBOL (WORKING-STORAGE after LINKAGE) is refused at parse time |
| dynamic-call-valid (new) | — | refused | dynamic `CALL WS-NAME` blocks generation |
| call-linkage-valid, multiprog-valid (new) | — | VERIFIED | corrected copies of the invalid fixtures |

## 3. Gaps found and fixed (all generic — none is fixture-specific)

False-success routes:

1. **Oracle entry program.** Multi-program apps: the oracle chose `main.cob`
   or the first file alphabetically, not the program the Java enters.  The
   service now passes the resolved entry; an unknown, duplicated or
   ambiguous entry refuses to run.
2. **Files written to the working directory were never compared.** Only
   `/workspace/output` was collected.  All three execution lanes now collect
   the working directory too (`engine/execution/workspace_files.py`);
   INDEXED/RELATIVE images are INCONCLUSIVE → PARTIAL.
3. **stderr was never compared.** It now is whenever the source writes to it
   (`UPON STDERR` / `SYSERR`).

Translation defects (oracle-pinned):

4. Spring Boot runner entered only the driver paragraph → `RUN_UNIT$ENTRY`
   (fall-through chain; EXIT PROGRAM a no-op in the entry program).
5. STRING copied a numeric item's Java number → its stored digits.
6. LINE SEQUENTIAL WRITE kept trailing spaces → removed, as GnuCOBOL does.
7. A VALUE literal containing `VALUE`/`PIC`/`OCCURS`/… was cut or read as a
   clause → clause keywords are searched with literal contents masked.
8. Fixed-format columns 73-80 were read as program text → ignored.
9. PERFORM headers continued on following lines, and a separator period on
   its own line, were refused → parsed.
10. `SUBTRACT a b … FROM c [GIVING d]` was refused → supported.

Fail-closed hardening:

11. Divisions / DATA DIVISION sections out of order (GnuCOBOL rejects them).
12. Record SEQUENTIAL files; signed/COMP STRING sources.
13. Dynamic or unresolved CALL now stops generation (previously the project
    built and failed at run time).
14. An oracle compile failure is named in the verdict instead of
    "Required infrastructure unavailable".

## 4. Refused applications (all fail closed with a named reason)

| App | Reason |
|---|---|
| by-value | CALL BY VALUE: GnuCOBOL 3.1.2's implementation is unfinished, no oracle equivalence possible |
| call-linkage, multiprog, dynamic-call | WORKING-STORAGE after LINKAGE — GnuCOBOL rejects the source |
| dynamic-call-valid | dynamic CALL (data-item target) has no static dispatch |
| cics | EXEC CICS |
| db2 | EXEC SQL |
| claims | three variants of PROGRAM-ID CLAIMS in one directory |
| comp, comp3, relative, relative-file | referenced COMP/COMP-3 items: record-area byte encoding not certified |
| occurs | OCCURS outside the certified subset |
| redefines | REDEFINES with numeric reinterpretation |

## 5. Tests added

`tests/integration/test_spring_entry_semantics.py` (Maven build + JAR vs
GnuCOBOL), `tests/test_oracle_entry_binding.py`, `tests/test_stderr_contract.py`,
`tests/test_workspace_file_contract.py`,
`tests/verdict/test_oracle_compile_failure_reason.py`,
`tests/transformation/test_line_sequential_and_string_numeric.py`,
`tests/transformation/test_unresolved_call_blocks_generation.py`, new cases in
`test_false_success_regressions.py` (multi-subtrahend SUBTRACT ×5 + 2
fail-closed, columns 73-80, continued PERFORM header + separator period,
keyword-bearing VALUE literals, section order), `test_usage_capability.py`
(unreferenced COMP), `test_oracle_multiprogram.py` (entry selection).

### Acceptance (exact-SHA CI)

`6050335` — CI run 41331289314, all jobs green: backend + full Docker lane
**4,767 passed, 0 failed, 0 skipped**; capability-truth gate 1,001 passed;
frontend 172 passed; supply chain green.  Two follow-ups were needed after
the first push: the pytest-only gate could not import pydantic
(`57fc673`), and three pre-Phase-2 Docker tests still expected the old
behaviour (`6050335`: one lowered run-unit body; indexed/relative now
PARTIAL by design).

## 6. Open (Phase 3 candidates)

- Record-level comparison of INDEXED/RELATIVE files (would let the 6 PARTIAL
  apps become VERIFIED).
- Referenced COMP / COMP-3, signed STRING sources, OCCURS whole-record
  references, REDEFINES numeric reinterpretation, record SEQUENTIAL files.
- Undefined data names are caught by javac, not the parser.
- Runtime targets other than Spring Boot have no end-to-end API run here.
