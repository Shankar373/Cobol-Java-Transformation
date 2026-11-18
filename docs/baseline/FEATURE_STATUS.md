# Feature status (2026-11-18)

Status words: **VERIFIED** (executable evidence, in CI), **IMPLEMENTED** (code and tests, narrower evidence), **PARTIAL**, **NOT STARTED**,
**BLOCKED** (needs external evidence), **REFUSED** (rejected by name on purpose). "GnuCOBOL" is the only reference used; no row is IBM-verified.

## Core modernization

| Capability | Status | Evidence and limits |
|---|---|---|
| COBOL parse, IR, Java generation for plain Java, Spring Boot, Quarkus, Micronaut | VERIFIED (certified subset) | Corpus certification of 55 applications on four runtimes; quarkus and micronaut in command mode only; Jakarta EE not certified |
| Sequential, indexed, relative files; FILE STATUS | VERIFIED (narrow) | GnuCOBOL differential tests; emulated side files, not on-disk VSAM |
| ALTERNATE RECORD KEY (random access) and browsing (`START`, `READ NEXT`) | VERIFIED (narrow shapes) | Browsing: DYNAMIC access, two alternate keys, `PIC X(2)` fields, FILE STATUS only; refused otherwise |
| Numeric edited, `INSPECT` (literal subset), `SORT`/`MERGE`, `SEARCH`, reference modification, qualified names, `**`, some intrinsics | VERIFIED (subset) | see `docs/CAPABILITY_MATRIX.md` |
| `OCCURS DEPENDING ON`, `SYNCHRONIZED`, `COMP-1`/`COMP-2` layouts, `MOVE CORRESPONDING` beyond the single-line form, EBCDIC program data | REFUSED or NOT STARTED | refused by name |

## VSAM (Stage 1)

| Capability | Status | Evidence and limits |
|---|---|---|
| Streaming migration of KSDS, RRDS, fixed and variable ESDS | VERIFIED (GnuCOBOL) | parity and API-to-generated-Java tests; 10 GiB at about 33 MiB peak; interrupt and resume with identical hashes |
| Alternate keys in the migrated KSDS image (fixed length, up to three, unique or with duplicates) | VERIFIED (GnuCOBOL) | unit tests plus two API-to-Java tests with a negative control |
| Disk-backed read-only index in the generated Java runtime | VERIFIED | 165 MB file under a 48 MB heap |
| IBM RRDS equivalence, ESDS RBA, IDCAMS `DEFINE CLUSTER`/`LISTCAT`/`BLDINDEX`/`ALTER`, IBM runtime verification | BLOCKED | needs IBM captures; request pack in `docs/vsam/IBM_EVIDENCE_REQUEST_PACK.md` |
| Streaming writes in the generated Java runtime (`OUTPUT`, `I-O`, `EXTEND` are in memory) | NOT STARTED | enterprise Phase 6 |

## Enterprise platform

| Phase | Status | Evidence and limits |
|---|---|---|
| 0 contracts, job states, quotas, benchmarks | VERIFIED | `tests/enterprise/` |
| 1 durable infrastructure | PARTIAL | PostgreSQL and SQLite with migrations, atomic transitions, leased workers, crash recovery, bounded retries (CI runs PostgreSQL). Not built: S3 adapter, Redis/Celery, cross-process test on PostgreSQL, retention |
| 2 GitHub ingestion | PARTIAL | pinned, safe snapshot core, 38 tests against a local stand-in server plus one manual live run on a tiny repository. Separately, `enterprise/discovery/` ingests Git (local and remote https, commit-pinned) into an immutable checkpoint through the API and UI; see `docs/discovery/DISCOVERY.md` |
| 3 ZIP ingestion | PARTIAL | safe extraction library (22 tests). Discovery adds an upload endpoint, checkpoint and UI page (single request, no resumable upload sessions) |
| Discovery gate on modernize/revalidate | IMPLEMENTED | `docs/discovery/COMPILER_AND_APPLICATION_DISCOVERY.md`: BLOCKED refuses with 409, NOT_SUPPORTED lists what is unhandled; open-source (GnuCOBOL) syntax check only |
| 4 scalable inventory | IMPLEMENTED (in-process) | COBOL estate discovery: complete file and directory inventory, dependency graph with unresolved tracking, runtime dependencies, dialect evidence, completeness gate; about 700 backend tests, 5 frontend tests. Lexical, not compiled; no external worker queue; see `docs/discovery/DISCOVERY.md` |
| 5 streaming VSAM | VERIFIED for one process | see VSAM table |
| 6 streaming Java | PARTIAL | read-only disk index only |
| 7 hardening | NOT STARTED beyond existing controls | shared bearer tokens remain |

## JCL, Db2, CICS/IMS/MQ (Stages 2 to 4)

| Area | Status | Evidence and limits |
|---|---|---|
| JCL job launcher (COND, dispositions, GDG, IEFBR14/IEBGENER/IDCAMS subset) | IMPLEMENTED, partial | `tests/test_jcl_*`; not JES. An audit probe on 2026-11-17 fed 102 constructs through parse, expand and plan; 46 left no trace in the parsed model or any diagnostic (a few of those are probe artifacts). Real silent drops include the statements `JCLLIB`, `INCLUDE`, `OUTPUT`, `XMIT`, `CNTL`, `COMMAND` and `/*JOBPARM`, many DD keywords (`LRECL`, `REFDD`, `DDNAME`, `PATH`, `SUBSYS`), `DSNAME=` refused as "names no dataset", unnamed concatenation DDs, and `PARM` never passed to programs. The fix exists unmerged on the local branch `codex/stage2-jcl-policy-wip` (commit `9d8fab1`); it is **not** in this baseline |
| JCL `RESTART`, `IF/THEN/ELSE` evaluation | NOT IMPLEMENTED | `IF` blocks are refused by name |
| Db2 / SQL | PARTIAL | bounded portable `EXEC SQL` subset against OCESQL + PostgreSQL; no SQLCODE/SQLSTATE model, indicators, cursors, `WHENEVER` or dynamic SQL; no Db2 runtime evidence |
| CICS, IMS, MQ | simulators only | blocked in the product; no IBM evidence |
| Mainframe dependency elimination | NOT STARTED | |
