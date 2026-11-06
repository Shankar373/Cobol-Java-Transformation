# Capability status by evidence class

Each capability of the enterprise roadmap, classified by what is actually true of it, as of `impl/enterprise-platform` at `2e0f5c6` (CI 41963301415, supply chain 41963301173). The classes are
cumulative only where the table says so; a blank is "no", never "unknown".

* **Implemented** -- code exists on `impl/enterprise-platform`.
* **Tested** -- hermetic tests (and, where marked, Docker-lane tests) pass in CI.
* **Oracle-verified** -- output equals a real reference runtime: GnuCOBOL 3.1.2 (`VERIFIED`), or the OCESQL +
  PostgreSQL 14 reference (database target, **not** DB2).
* **Simulator-verified** -- a Java library equals an in-repo specification (`SIMULATOR_VERIFIED`). This says
  nothing about IBM runtimes, and nothing here can produce an IBM verdict.
* **Production-integrated** -- reachable from the product's transformation or API path, so a user gets it.
* **Blocked** -- cannot progress without an owner decision, credentials, an IBM environment or a prerequisite
  feature (see `OWNER_DECISIONS.md`).

Commit SHAs and the CI / supply-chain / certification run IDs for every row are in
[`EXECUTION_LEDGER.md`](EXECUTION_LEDGER.md).

| Capability | Impl. | Tested | Oracle-verified | Simulator-verified | Prod.-integrated | Blocked / not done |
|---|---|---|---|---|---|---|
| ASSIGN ddname + DD binding, dataset catalogue (4) | yes | yes | GnuCOBOL | | yes (ingest API, UI) | |
| JCL preprocessor: PROC, symbolics, SET (5) | yes | yes | | | yes (discovery) | IF/ELSE blocks, nested PROC depth limits |
| JCL job to Java launcher (6) | yes | yes | GnuCOBOL (step programs) | | not wired into `/modernize` | wiring is a decision for unit 18's follow-up |
| Utilities IEFBR14 / IEBGENER / IDCAMS, GDGs, dispositions (8) | yes | yes | | documented-semantics only | with the launcher | no JES/IBM utility oracle; SORT, IEBCOPY, LISTCAT, IDCAMS DEFINE CLUSTER refused |
| Keyed `ACCESS MODE RANDOM` (7) | yes | yes | GnuCOBOL | | yes | SEQUENTIAL access, ALTERNATE KEY refused |
| `INSPECT` literal subset (9) | yes | yes | GnuCOBOL (360 fuzzed statements) | | yes | data-name operands, TRAILING |
| `SORT` and `MERGE` file to file (9) | yes | yes | GnuCOBOL (7 fixed forms, 100 fuzzed programs, incl. unsorted MERGE inputs) | | yes | INPUT/OUTPUT PROCEDURE, several GIVING files, COLLATING, record-sequential, signed/binary keys |
| linear `SEARCH` and `SET` on indexes (9) | yes | yes | GnuCOBOL (documented forms, 100 fuzzed programs) | | yes | `SEARCH ALL` is certified for `WHEN table(idx) = value` (100 fuzzed programs); refused: other SEARCH ALL conditions, VARYING an index, group/non-DISPLAY tables, index below 1, SET expressions |
| `GO TO` between paragraphs and plain `EXIT.` (26) | yes | yes | GnuCOBOL (documented form, 100 fuzzed programs) | | yes | DEPENDING, ALTER, jumps out of a PERFORM range, GO TO under simple/TIMES/UNTIL/VARYING PERFORM, LINKAGE programs, EXIT PROGRAM, EXIT PERFORM/PARAGRAPH/SECTION |
| `SEARCH` (9) | | | | | | not implemented; refused. Needs INDEXED BY / SET index support |
| Numeric-edited PIC (9) | WIP, uncommitted | partly | | | no | **authorization to merge** (`feat/phase3-coverage`) |
| `EXEC SQL` as IR (10) | yes | yes | | | analysis only | |
| `DatabaseDialect` DB2 / PostgreSQL (11) | yes | yes (table-driven) | | | used by the SQL lowering | dialects beyond PostgreSQL: owner decision |
| JDBC lowering of a SQL subset (12) | yes | yes | OCESQL + PostgreSQL 14 | | yes | **not DB2-verified**; indicators, WHENEVER, dynamic SQL refused |
| Data migration / reconciliation (13) | yes | yes | PostgreSQL 14 | | library, not an API | signed / packed / EBCDIC sources, VSAM and DB2 sources |
| MQ simulator SIMMQ-1 (14) | yes | yes | | yes (Java twin = Python spec) | no | lowering needs binary group storage (see below) |
| IMS DL/I simulator SIMDLI-1 (15) | yes | yes | | yes | no | lowering needs PCB / I-O area layouts |
| CICS simulator SIMCICS-1 (16) | yes | yes | | yes | no | lowering needs an `EXEC CICS` precompiler |
| Estate graph, API, UI (17) | yes | yes | | | yes (`/estate`, UI panel) | portfolio view, persistence |
| Decomposition proposal (18) | yes | yes | | | yes (`/decomposition`) | multi-artifact / container generation; hosting |
| RBAC on bearer tokens (19) | yes | yes | | | yes (middleware) | OIDC / SSO, per-resource ownership |
| Windows CI lane (19) | yes | n/a (CI) | | | n/a | see the ledger row for the run that proved it |
| Type-check ratchet and coverage floor (19) | yes | yes | | | n/a | baseline errors remain; see `tests/mypy_baseline.txt` |
| Artifact signing (19) | | | | | | **signing keys and retention** |
| Docker socket isolation (19) | | | | | | **deployment target** |

## Evaluations recorded for the roadmap's open questions

### Integrating the MQ / IMS / CICS simulators into generated code

Not done, deliberately. A deterministic proof needs the *same program* to run on a reference side and a
Java side that both implement the simulator specification, and each simulator would need three things first:

1. **MQ** -- the call arguments are structures (`MQOD`, `MQPMO`, `MQGMO`, `MQMD`) made of `BINARY` fields. The
   lowering refuses group storage with non-DISPLAY encodings, so a real MQ program cannot be lowered, and a
   Java library that only accepts our simplified integers would be a claim about a program nobody writes.
2. **CICS** -- `EXEC CICS` needs a translator; GnuCOBOL cannot compile it. A translator, a GnuCOBOL-callable
   implementation of SIMCICS-1 (a third implementation to keep equal) and the Java lowering are one feature,
   not a patch.
3. **IMS** -- PCB masks and I/O areas are byte layouts the IR does not model.

Doing less would put an unproven path in front of users under a verified-sounding label. What the product
does instead: the estate marks every MQ / IMS / CICS reference `BLOCKED` or `UNPROVEN`, and the evidence on
the edge says that a verified simulator exists, that generated code does not call it, and that no IBM runtime
was run.

### Interrupted-run recovery

Kept fail-closed. At startup every run left non-terminal is marked `FAILED` with the stage it had reached (the
last-stage anchor survives, `tests/test_last_stage_anchor.py`), and a client may start validation again. A
re-queue was rejected: the stages are not idempotent (workspaces, containers, partially written evidence), a
resumed run would mix evidence from two processes, and a duplicate could execute while its predecessor's
container still runs. Automatic recovery of the *never started* case adds nothing the client's retry does not.

### The two Windows-specific failures

Both were real and are fixed: a non-ASCII character in a generated Java comment (compiled on a UTF-8 host,
failed under cp1252), now a guarded invariant (`tests/test_generated_java_ascii.py`); and a test that used
whatever `bash` was first on `PATH`, which on Windows is the WSL launcher and answers 0 to everything, now
skipped unless a bash that prints its own `BASH_VERSION` exists. The Windows CI lane also runs the host-javac
tests on Java 21, the certified runtime, because the runner's default JDK rejects Java 16+ source.
