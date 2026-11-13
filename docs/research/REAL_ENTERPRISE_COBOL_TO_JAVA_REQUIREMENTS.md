# Real enterprise COBOL-to-Java requirements, and what SystemaOps reproduces (2026-11-13)

Purpose: ground the Stage 1-4 plans in documented enterprise behaviour instead of in what the current code happens to
do. Every statement carries one tag:

- `VERIFIED_EXTERNAL_SOURCE` - stated on the cited official page. The pages were read by a summarising fetch tool, so
  wording is paraphrased; where a page did not say something, that is recorded under "Not on the page".
- `OBSERVED_REPOSITORY` - read from this repository's code, tests or evidence at the commit named in
  [EXACT_HEAD_ENTERPRISE_BASELINE.md](../reports/EXACT_HEAD_ENTERPRISE_BASELINE.md).
- `ENGINEERING_INFERENCE` - our reasoning; not a source claim.
- `REQUIRES_OWNER_OR_CUSTOMER_INPUT` - cannot be settled without the owner, a customer or a licensed IBM environment.

No customer source code was accessed. SystemaOps contains no LLM, and nothing below changes that: AWS Transform is
studied only for the breadth of a real workflow, and its AI features are not a model for this product.

## 1. A real production case: Venerable's Agent Management System

Source: [AWS APN blog](https://aws.amazon.com/blogs/apn/how-venerable-accelerated-growth-by-modernizing-its-mainframes-on-aws/).

| Finding | Tag |
|---|---|
| 3.8 million lines of COBOL and Assembler on z/OS; 650 online screens; 250 batch jobs; 2,000+ programs | VERIFIED_EXTERNAL_SOURCE |
| Online application on CICS with BMS-defined screens; batch ran partly as CICS background transactions started with `START`, and consumed CICS resources | VERIFIED_EXTERNAL_SOURCE |
| 110 VSAM files in variable and multi-record formats plus 25 Db2 tables, 15 GB in total, moved to SQL Server on Amazon RDS | VERIFIED_EXTERNAL_SOURCE |
| Programs passed COBOL records of 128 K bytes between each other; code used GETMAIN, pointers and simulated z/OS memory addressing | VERIFIED_EXTERNAL_SOURCE |
| Sorting had to handle collating-sequence differences between ASCII and EBCDIC | VERIFIED_EXTERNAL_SOURCE |
| Month-end and year-end peaks set the throughput requirement; RTO 4-6 hours, RPO 15 minutes, active/passive across availability zones | VERIFIED_EXTERNAL_SOURCE |
| Some online background transactions were replaced by Java batch processes using embedded SQL (the only redesign the page states) | VERIFIED_EXTERNAL_SOURCE |
| Done with a vendor refactoring suite (Heirloom), 16 months, in production since June 2020 | VERIFIED_EXTERNAL_SOURCE |

Not on the page: cutover and rollback detail, semantic-equivalence or test evidence, and whether any step used generative
models. It is a vendor case, not a standard.

### What the case reveals that our corpus does not cover

All rows are `ENGINEERING_INFERENCE` comparing the case to `OBSERVED_REPOSITORY` fixtures (55 small applications, each a
single batch run on one recorded input).

| Real-world property | Our corpus |
|---|---|
| Estate scale (2,000+ programs, 3.8 M lines) | Largest fixture is a few programs; no scale or throughput test exists |
| Online CICS + BMS transactions | `EXEC CICS` is refused; simulators only (`SIMULATOR_VERIFIED`) |
| Batch started from CICS (`START`) | not representable |
| VSAM variable and multi-record files | one record-sequential variable fixture; multi-01 FDs are bound by the FILE SECTION (G-14) but not differential-tested at scale |
| 128 KB records and pointer / GETMAIN code | not represented; pointer and storage-address constructs are unsupported |
| ASCII vs EBCDIC collation in sorts and key order | no EBCDIC run; `engine/vsam/collation.py` adds deterministic ordering tests only |
| Peak-volume performance, DR with RTO/RPO | no performance corpus (a coarse baseline file exists); single-node SQLite control plane |
| Data migration of 15 GB with reconciliation | `engine/vsam/reconcile.py` (offline, byte-level) and `engine/sql/migration.py` (fixed-width to SQL); no volume test |

## 2. Breadth of an enterprise modernization workflow

Source: [AWS Transform for mainframe](https://docs.aws.amazon.com/transform/latest/userguide/transform-app-mainframe.html).

- Supported estate: z/OS COBOL and PL/I, JCL and PROC, CICS CSD, BMS, Db2, VSAM, IMS TM, copybooks. - VERIFIED_EXTERNAL_SOURCE
- Capabilities listed: analysis, decomposition, planning, documentation generation, refactoring to Java. - VERIFIED_EXTERNAL_SOURCE
- A human is asked for more information, to approve intermediate artifacts (for example domain decomposition, wave
  planning) and when issues cannot be resolved automatically. - VERIFIED_EXTERNAL_SOURCE
- The page does not say which steps are generative and which deterministic. - UNCONFIRMED by the page
- Deterministic equivalents we need: discovery and dependency graph (exists, `OBSERVED_REPOSITORY`), a decomposition
  *proposal* for human approval (exists, no multi-artifact output), approval records, traceability from source to Java.
  - ENGINEERING_INFERENCE

## 3. VSAM

Sources: [z/OS summary of VSAM data set types](https://www.ibm.com/docs/en/zos/3.2.0?topic=types-summary-vsam-data-set),
[CICS 5.5: VSAM data sets (KSDS, ESDS, RRDS)](https://www.ibm.com/docs/en/cics-ts/5.5.0?topic=control-vsam-data-sets-ksds-esds-rrds).

| Organization | Documented behaviour | Tag |
|---|---|---|
| KSDS | records in key collating sequence; key at a fixed position and unique in the data set; direct access by key or RBA; alternate indexes permitted; a record's RBA can change; spanned records permitted | VERIFIED_EXTERNAL_SOURCE |
| ESDS | entry order; direct access by RBA, which never changes; new records go after the last record; a record cannot be deleted or lengthened (space may be reused for a record of the same length); alternate indexes permitted; standard RBA is 32-bit (4 GB), extended uses 64-bit | VERIFIED_EXTERNAL_SOURCE |
| Fixed RRDS | relative record number from 1; fixed-length slots; records go into empty slots; a deleted record's slot can be reused; no alternate index; no spanned records | VERIFIED_EXTERNAL_SOURCE |
| Variable RRDS | RRN order, any length up to the maximum, located through an index; no alternate index; no spanned records | VERIFIED_EXTERNAL_SOURCE |
| Alternate index | KSDS and ESDS only; fixed-length, fixed-position key that need not be unique; any number per base; access through a path behaves like a KSDS; direct base updates reach the index only if it is in the base's upgrade set | VERIFIED_EXTERNAL_SOURCE |
| Linear data set | no record-level processing | VERIFIED_EXTERNAL_SOURCE |

Not on those pages: record and key length limits, COBOL FILE STATUS mapping, COBOL ORGANIZATION/ACCESS rules, IDCAMS
syntax, recovery.

What the repository does (`OBSERVED_REPOSITORY`): GnuCOBOL `INDEXED` and `RELATIVE` files are generated to a Java runtime
(`CobolFileIo`) and compared with GnuCOBOL on bounded shapes; one alternate-key browse shape is certified;
`IDCAMS DELETE`, `DEFINE GDG`, `REPRO` and `SET MAXCC` are a documented native subset in the JCL job lane
(`engine/jcl/orchestrator.py`) that the reference runner refuses. Nothing models ESDS, RBA, variable RRDS, spanned
records, `DEFINE CLUSTER`, `LISTCAT`, `BLDINDEX` or `ALTER`.

`ENGINEERING_INFERENCE`: GnuCOBOL `INDEXED` is a BDB/VBISAM-style indexed file, not a VSAM KSDS, so a GnuCOBOL match
proves COBOL-visible behaviour for the shape tested, not VSAM storage behaviour (free space, RBA changes, control
intervals, spanned records). ESDS and fixed/variable RRDS differ from KSDS in addressing and in delete semantics, so they
need their own models and their own reference. `REQUIRES_OWNER_OR_CUSTOMER_INPUT`: an authorised z/OS (or equivalent
licensed) environment to run the same programs against real VSAM.

## 4. Db2 for z/OS

Sources: [SQLCA / SQLCODE / SQLSTATE in COBOL](https://www.ibm.com/docs/en/db2-for-zos/13.0.0?topic=catiss-defining-sql-communications-area-sqlstate-sqlcode-in-cobol),
[host variables](https://www.ibm.com/docs/en/db2-for-zos/13.0.0?topic=variables-host).

- A COBOL program either includes an SQLCA (`EXEC SQL INCLUDE SQLCA`, STDSQL(NO)) or declares `SQLCODE` as
  `PIC S9(9) COMP-5` and `SQLSTATE` as `PIC X(5)` (STDSQL(YES), where defining an SQLCA is a compile error). Db2 sets both
  after every SQL statement and the application should check them. - VERIFIED_EXTERNAL_SOURCE
- A host variable is a single data item declared in the host language and used in an SQL statement; with the precompiler
  its name must be unique in the program. A negative indicator value inserts NULL. - VERIFIED_EXTERNAL_SOURCE
- Not on those pages: COBOL-to-SQL type mapping (`DECIMAL` / `COMP-3`), indicator semantics beyond NULL insertion, cursor
  lifecycle, isolation, locking, deadlock handling, `WHENEVER`, dynamic SQL, stored procedures, driver licensing.
- Repository (`OBSERVED_REPOSITORY`): a bounded `EXEC SQL` subset lowers to JDBC and is compared against OCESQL +
  PostgreSQL 14; indicators, `WHENEVER` and dynamic SQL are refused. This is **controlled portable SQL evidence, not Db2
  runtime evidence**: SQLCODE/SQLSTATE values, locking and isolation of real Db2 are unverified. Real Db2 verification needs
  a licensed Db2 and driver. - REQUIRES_OWNER_OR_CUSTOMER_INPUT

## 5. CICS

Source: [CICS application programming languages and APIs](https://www.ibm.com/docs/en/cics-ts/6.x?topic=applications-cics-application-programming-languages-cics-api).

- `EXEC CICS` is used from Assembler, C, C++, COBOL, PL/I and REXX; Java uses JCICS (most of the EXEC CICS API) or JCICSX
  (fewer functions, designed for local workstation development and testing). - VERIFIED_EXTERNAL_SOURCE
- Channels and containers are the recommended way to pass data; a COMMAREA is a single block limited to 32 KB. - VERIFIED_EXTERNAL_SOURCE
- Not on the page: command semantics, RESP codes, syncpoint, pseudo-conversational behaviour, BMS.
- Repository: `SIMCICS-1` Python/Java simulators with conformance suites, `SIMULATOR_VERIFIED`; `EXEC CICS` programs are
  classified UNSUPPORTED and refused. - OBSERVED_REPOSITORY
- A simulator proves conformance to its own specification only. Real CICS needs an authorised CICS region or JCICS
  runtime. - REQUIRES_OWNER_OR_CUSTOMER_INPUT

## 6. JCL and restart

Source: [JCL requirements and restrictions for a deferred step restart](https://www.ibm.com/docs/en/zos/2.5.0?topic=restart-jcl-requirements-restrictions-deferred-step).

- `RESTART` is coded on the JOB statement. For a restart to work, the original run must use conditional dispositions that
  delete NEW data sets and keep OLD data sets of the restarted step, and must catalog data sets passed to the restart step
  or later; conditional disposition processing is not done during an abend. - VERIFIED_EXTERNAL_SOURCE
- Restart DDs must define receiving data sets completely (volume, device, label type, which cannot be retrieved from the
  catalog); `DISP=MOD` tape is not repositioned; `COND` and `PGM=` referencing a preceding step, and `VOL=REF`, must not
  be used in the restart step or later. - VERIFIED_EXTERNAL_SOURCE
- GDG: with `GDGBIAS=JOB`, generations created in earlier steps must be referenced by actual relative numbers (`+1`
  becomes `0`). - VERIFIED_EXTERNAL_SOURCE
- Not on the page: checkpoint restart, automatic restart, scheduling, JES queues.
- Repository: JCL preprocessor, DD binding, a Java job launcher with `COND`, dispositions, GDGs and native `IEFBR14` /
  `IEBGENER` / `IDCAMS` subset; its reference is a POSIX shell script, **not JES**. `RESTART`, checkpoint restart and
  deferred-step restart are not implemented. - OBSERVED_REPOSITORY

## 7. Spring Batch

Sources: [chunk-oriented processing](https://docs.spring.io/spring-batch/reference/step/chunk-oriented-processing.html),
[what's new](https://docs.spring.io/spring-batch/reference/whatsnew.html).

- Items are read one at a time and written in chunks inside a transaction boundary; when the count reaches the commit
  interval the chunk is written and the transaction committed. An optional processor sits between read and write. -
  VERIFIED_EXTERNAL_SOURCE
- The reference documents restart, skip, retry, `JobRepository` and `ExecutionContext` as topics, but the pages read did
  not show their content. - UNCONFIRMED by the page
- Current reference is Spring Batch 6.0.x on Spring Framework 7; a Java 17 baseline was reported by a search summary of
  the migration guide, not read from the docs page. - moderately confirmed
- Repository: a Spring Batch adapter exists in the JCL job lane; verify dependency versions and JDK against it before any
  upgrade (the build image is JDK 21). - OBSERVED_REPOSITORY
- Spring Batch gives mechanisms (chunk transactions, a metadata store, restart state); it does not by itself reproduce JCL
  step activation, dataset dispositions or `COND` semantics, which stay our own deterministic rules.
  - ENGINEERING_INFERENCE

## 8. What can and cannot be certified

| Area | Can be tested with open-source tools | Needs a licensed IBM environment | Honest evidence class today |
|---|---|---|---|
| COBOL batch subset, copybooks, static CALL | GnuCOBOL 3.1.2 differential | to claim IBM Enterprise COBOL equivalence | GnuCOBOL differential (certified subset) |
| Indexed / relative files, one alternate-key shape | GnuCOBOL | VSAM KSDS/ESDS/RRDS behaviour | GnuCOBOL differential, bounded |
| ESDS, RBA, variable RRDS, spanned, IDCAMS clusters | no local reference | yes | not implemented |
| EBCDIC key order | deterministic unit tests | to confirm against real data | deterministic test only |
| Db2 SQL subset | PostgreSQL/OCESQL | Db2 for z/OS and driver | controlled portable evidence |
| JCL | shell reference, Spring Batch | JES | documented semantics, no oracle |
| CICS, IMS, MQ | in-repo simulators | CICS TS, IMS, IBM MQ | `SIMULATOR_VERIFIED` |
| Performance, DR, cutover, decommissioning | load and failover tests on our side | customer workload and mainframe | not established |

Nothing in this repository is `IBM_RUNTIME_VERIFIED`.
