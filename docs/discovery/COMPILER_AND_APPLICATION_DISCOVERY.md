# Compiler, application and readiness discovery

Extends `docs/discovery/DISCOVERY.md`. Modules: `enterprise/discovery/compilers.py`, `applications.py`, `readiness.py`; API gate: `api/readiness.py`,
`api/service.py`; UI: `frontend/src/pages/Discovery.tsx` and `frontend/src/components/discovery/`. Deterministic, **no LLM, open-source tools only, nothing proprietary
is installed, called or emulated.**

## Three separate questions

1. **What does the estate require?** (`report.toolchain.required`) Read from the source: `CBL`/`PROCESS` option cards, `$SET` and `>>` directives, `cobc`/`mfcob`/`mvn`
   invocations and flags in Makefiles and scripts, JCL compile and link steps (`IGYCRCTL`, `IEWL`, `IGYW*` procedures), `COB_*` runtime settings. Each item has `file:line` evidence.
2. **What open-source tooling can this host run?** (`report.toolchain.tools`) Probed, with versions and licences: GnuCOBOL `cobc` (on `PATH`, else inside the project's
   `gnucobol-ocesql` container image), the GCC COBOL front end `gcobol`, `ocesql`, a JDK, Maven. A missing tool is recorded with its reason; it never stops discovery.
3. **Is each program acceptable to the open-source compiler?** (`report.compatibility`) A syntax-only check (`cobc -fsyntax-only`, nothing built or run; container: no network,
   source mounted read-only, memory and pid limits, one container per batch of 40 files). Flags follow the evidence: `-std=ibm|mf|cobol85|default` from the detected dialect,
   `-free`/`-fixed` from the detected reference format, `-I` for every copybook directory in the estate. Diagnostics are parsed back to `file:line`.

Verdicts (closed set): `COMPILES`, `COMPILES_WITH_WARNINGS`, `COMPILE_ERRORS`, `NOT_ATTEMPTED_PROPRIETARY`, `NOT_ATTEMPTED_SQL_PRECOMPILER`, `NOT_ATTEMPTED_BLOCKED_DEPENDENCY`
(a missing copybook or callee would make a compile result misleading), `NOT_ATTEMPTED_NO_COMPILER`, `NOT_ATTEMPTED_BUDGET`, `NOT_ATTEMPTED_TOOL_FAILURE`.
A pass means GnuCOBOL accepts the source in that dialect. It is **not** a verdict from the customer's production compiler, and the report says so.

## Open-source options considered

| Tool | Use here |
|---|---|
| GnuCOBOL `cobc` 3.1.2 / 3.2 | the checker (local or container); the same family the platform already uses as its oracle |
| GCC COBOL front end `gcobol` (GCC 15+) | probed and reported; not used for checking yet (no corpus evidence for it) |
| `ocesql` (Open Cobol ESQL, PostgreSQL) | probed and reported only: no precompile step is run, so `EXEC SQL` programs are never syntax-checked (`NOT_ATTEMPTED_SQL_PRECOMPILER`) |
| TinyCOBOL, OpenCOBOL 1.x | not used: unmaintained and superseded by GnuCOBOL |
| IBM Enterprise COBOL, Micro Focus, CICS and Db2 translators, IMS, IBM MQ | proprietary: **not provided, never emulated**; reported as unsupported (below) |

## Unsupported proprietary features (reported by name, with the reason)

`exec-cics`, `exec-dli` (DL/I and `CBLTDLI`), `exec-sql-db2` (the Db2 precompiler), `ibm-mq`, `language-environment` (`CEE*`), `ibm-compiler-options` (`ARITH`, `TRUNC`,
`SSRANGE`, ...), `object-oriented-cobol`, `microfocus-directives`, called `assembler`/PL-I/REXX members. Features that need a translator or runtime with no open-source equivalent
(`stops_check`) keep the program out of the compiler check; the others are recorded and the check continues. The catalogue is in `compatibility.feature_catalog`.

## Applications, entry points and relationships (`applications.json`)

* **Entry points**: `batch-job-step` (a JCL step runs the program), `ims-region-program`, `cics-transaction-program` (a CSD transaction names it), `called-subprogram`,
  `unreferenced-program`.
* **Applications**: connected components of programs, jobs, procedures, transactions and map sets joined by calls, `EXEC PGM`, `INCLUDE`, `LINK`/`XCTL` and transactions. Ids are
  `APP-` plus a hash of the sorted members, so they do not depend on input order. A lone assembler or PL/I member is not an application.
* **Cross-application relationships**: datasets, VSAM clusters, Db2 tables, queues, IMS PSBs, CICS files and copybooks used by more than one application, with per-application use counts.

## The readiness gate (`transformation-readiness.json`)

| State | Meaning | Effect |
|---|---|---|
| `BLOCKED` | discovery is incomplete (a blocking reference is unresolved, a source file could not be scanned, the checkpoint does not verify, a nested archive is unexpanded, discovery itself was refused) | modernization is refused with HTTP 409 and the missing items; no run is created |
| `NOT_SUPPORTED` | complete, but programs use constructs open-source tooling cannot check, GnuCOBOL rejects them, **or the compiler check did not run** (`unverified`: no compiler, tool failure, time budget, blocked dependency) | allowed; the unsupported items and compiler errors are listed on the ingest and modernize responses and in the report |
| `READY` | nothing blocks, nothing unsupported, **and every compilable program received a compiler verdict** | allowed |

Where it is enforced (`api/service.py`): ingest assesses and stores the readiness of the new source tree; **`modernize`** and **`revalidate`** call `_require_ready`, which reuses the stored
record while the tree is unchanged (a SHA-256 of every file's content, plus the toolchain setting and the policy version) and otherwise re-runs discovery. A source tree that cannot be assessed is `BLOCKED`, never ready. `GET /applications/{id}/readiness`
returns the record; `POST .../readiness/refresh` re-assesses. VSAM dataset migration does not consume application source and is not gated.

Existing tests that uploaded the placeholder `b"A"` as COBOL were changed to upload a minimal valid program (`tests/common.py::MINIMAL_COBOL`): the gate rightly treats `b"A"` as a COBOL file
without a `PROGRAM-ID`.

## Real corpus result

Discovery over the repository's 55 fixture workloads (`tests/discovery/test_corpus.py`): 52 READY, 2 NOT_SUPPORTED, 1 BLOCKED (`workload-jcl`, whose JCL names programs and a procedure that are
deliberately absent). Running it found and fixed one scanner defect: a `.java` file mentioning `PROGRAM-ID` was classified as COBOL.

## Configuration

`DISCOVERY_COMPILER_BACKEND` = `auto` (default: local `cobc`, else the container image), `local`, `container`, `none` (an unreadable value means `none`); `DISCOVERY_COMPILE_BUDGET_SECONDS`
(default 240; programs beyond it are `NOT_ATTEMPTED_BUDGET`); `DISCOVERY_COBC_IMAGE` (default `gnucobol-ocesql:latest`). The test suite sets the backend to `none` by default.

## UI

The Estate Discovery page shows the readiness state, the toolchain (required and available, with licences), a filterable compatibility table (verdicts, diagnostics, unsupported features with
reasons), applications with entry points and blockers, and cross-application relationships. Every `file:line` anywhere on the page opens a source viewer that reads the line from the immutable
checkpoint (`GET /discovery/runs/{id}/source`, restricted to inventoried files).

## Limits (actual)

* The check is syntax-only and per file; it does not link, run, or compare behaviour. Programs that need a missing copybook or callee are not checked.
* No IBM, Micro Focus, CICS, Db2, IMS or MQ tooling exists here, so those programs are inventoried and graphed but never compiled; Db2 `EXEC SQL` programs are never checked (ocesql is probed but not integrated).
* Dialect selection for `-std=` is indicative (from source signals); a wrong guess can produce compiler errors that the customer's compiler would not.
* A container-backed check needs Docker and the image; when absent the backend is `none` and every program is `NOT_ATTEMPTED_NO_COMPILER`.
* Application boundaries are structural (coupling in the graph), not business domains; two applications that only share a database are separate and related.
* The gate protects `modernize` and `revalidate`; other read-only endpoints are unchanged.
