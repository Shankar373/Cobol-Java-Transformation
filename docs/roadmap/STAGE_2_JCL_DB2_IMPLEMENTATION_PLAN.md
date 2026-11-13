# Stage 2 - JCL + Db2: plan (2026-11-13)

Nothing in Stage 2 was implemented in this change. This is a plan with exit criteria; no stage is marked complete because a
parser or a controlled test exists. External facts and tags: [research report](../research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md).

## 1. JCL

### Current state (`OBSERVED_REPOSITORY`)
- `engine/jcl/`: preprocessor (PROC, symbolics, SET), DD binding and dataset catalogue, a Java job launcher
  (`orchestrator.py`) with `COND`, dispositions, GDGs, inline data and native `IEFBR14` / `IEBGENER` / `IDCAMS` subset,
  assembly (`assembly.py`), a job lane (`job_lane.py`), a mapping to a Spring Batch application model
  (`engine/transformation/jcl_to_spring_batch`, `jcl_spring_batch_ir`) and a POSIX shell reference runner
  (`reference.py`) that compares step programs with GnuCOBOL and refuses IDCAMS and generation datasets.
- The reference is **not JES**. Its semantics are the documented ones the code implements; no IBM runtime was used.
  Status: `PARTIAL`, evidence `DOCUMENTED_SEMANTICS` plus GnuCOBOL for the step programs.

### Gap against IBM behaviour
| Behaviour | Source | State |
|---|---|---|
| `RESTART` on JOB, deferred-step restart rules (conditional dispositions, passed data sets cataloged, `GDGBIAS`) | IBM restart page (VERIFIED_EXTERNAL_SOURCE) | `NOT_IMPLEMENTED` |
| checkpoint restart, automatic restart | not on the page read | `NOT_IMPLEMENTED` |
| `IF/THEN/ELSE/ENDIF`, `COND` | IBM JCL reference | `COND` implemented; `IF/THEN/ELSE/ENDIF` to be confirmed from the code before any claim |
| `JCLLIB`, `INCLUDE` | IBM JCL reference | to be confirmed |
| catalog behaviour, temporary data sets, `DISP` abnormal-end handling | IBM restart page | partial (dispositions modelled; abend handling untested) |
| JES scheduling, queues, job dependencies | IBM | out of scope; needs a scheduler decision (Stage 4) |

### Plan
1. Inventory every JCL statement and parameter the parser sees and classify each (supported, partial, refused by name);
   commit the table next to `CAPABILITY_MATRIX.md`. Exit: no statement is dropped silently (a test per refusal).
2. Restart model: record per-step return codes and dataset state in a durable run record; implement `RESTART=stepname`
   for the subset where the IBM page's requirements can be checked (conditional dispositions present, passed data sets
   cataloged); refuse otherwise with the page's reason. Exit: restart tests that interrupt after step N and resume at N+1
   with identical final datasets.
3. Use Spring Batch only where it fits: chunk transaction boundary, `JobRepository` metadata and restart state; keep step
   activation, dataset dispositions and `COND` as our own rules (Spring Batch does not provide them).
4. Do not describe the Java job lane as JES equivalence. Exit: README/matrix wording unchanged unless an IBM reference
   exists.

External dependency: a JES environment to compare restart and disposition behaviour (`REQUIRES_OWNER_OR_CUSTOMER_INPUT`).

## 2. Db2

### Current state (`OBSERVED_REPOSITORY`)
- `engine/sql/`: extractor, analyzer, model, dialects (`database_dialect.py`, `db2_sqlite.py`), execution harness,
  fixed-width record migration with reconciliation (`migration.py`). A bounded `EXEC SQL` subset lowers to JDBC and is
  compared with OCESQL + PostgreSQL 14. Indicators, `WHENEVER` and dynamic SQL are refused.
- Status: `PARTIAL`; evidence class **controlled portable SQL**, not Db2 runtime. Statuses never reach
  `DB2_RUNTIME_VERIFIED`.

### Three separate evidence levels
1. SQL structure parsed and modelled (extractor, analyzer) - exists.
2. Controlled portable execution (PostgreSQL/OCESQL, SQLite) - exists for the subset.
3. Actual Db2 for z/OS execution - `EXTERNAL_DEPENDENCY` (licensed Db2, IBM driver, customer credentials).

### Gap (what IBM documents and we do not model)
SQLCA/`SQLCODE`/`SQLSTATE` declaration forms and per-statement values (the Db2 page says COBOL either includes an SQLCA or
declares `SQLCODE PIC S9(9) COMP-5` and `SQLSTATE PIC X(5)`); indicator variables beyond NULL insertion; cursor lifecycle
and `FETCH`; `WHENEVER`; commit/rollback and isolation; locking and deadlock retry; `DECIMAL` / `COMP-3` mapping;
dynamic SQL; stored procedures; IBM JCC driver licence.

### Plan
1. Model SQLCODE/SQLSTATE as first-class values after each statement; lower to Java with the portable values only and
   label them `PORTABLE_SQLSTATE`, never `DB2_SQLCODE`.
2. Indicator variables, then cursors (`OPEN/FETCH/CLOSE`) one at a time with a differential against OCESQL, each with
   negative tests; keep `WHENEVER` and dynamic SQL refused until designed.
3. Decimal mapping rules for `COMP-3` and `PIC S9(n)V9(m)` with boundary tests.
4. Define the interface for a real Db2 target (JDBC URL, driver, credentials injected, never stored) and a test that stays
   skipped-by-design, not green, without it.

Exit for Stage 2: statement inventory complete; restart implemented for the documented subset; portable SQL subset
extended with differential evidence; Db2 and JES comparisons listed as external with the exact owner action (provide a
licensed environment).
