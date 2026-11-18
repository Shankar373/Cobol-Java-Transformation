# COBOL estate discovery (ingestion, checkpoint, inventory, dependency graph)

Package `enterprise/discovery/`, API `api/discovery_routes.py`, UI page `frontend/src/pages/Discovery.tsx`.
Deterministic and rule-based. **No LLM, no ML, no network access except an explicit remote Git fetch.**
Discovery produces evidence about an estate; it does not start any Java transformation, and the report says whether
that may begin (see "The completeness gate").

## Provenance of the code

The generic layers were audited and adapted from the Stage 1 Pascal discovery
(`Shankar373/Pascal-Java-Transformation`, branch `feat/stage1-ingestion-discovery`, commit `61a071b`), not rewritten:

| Reused (adapted) | Where | Notes |
|---|---|---|
| Immutable, sealed, content-addressed checkpoint (create, verify, reuse, tamper detection) | `checkpoint*.py` | environment variables renamed to `SYSTEMAOPS_*`; defects fixed (below) |
| Safe Git ingestion (hardened environment, no hooks, no symlinks or submodules, pinned commit) | `gitingest.py`, `gitproc.py`, `gittree.py` | unchanged logic |
| Remote Git (https, SSRF policy, DNS pinning, credential scrubbing, ref to exact commit) | `remotegit.py`, `remotegit_policy.py` | unchanged logic |
| Limits, tree accounting, hashing, error and diagnostic taxonomy, dependency graph model | `limits.py`, `treelimits.py`, `hashing.py`, `errors.py`, `graph.py`, `model.py` | graph vocabulary replaced by the COBOL estate vocabulary |
| Orchestration (ingest, checkpoint, scan, analyse, report; progress; run record) | `discover.py` | rewritten around the COBOL stages |
| Generic ingestion, checkpoint, Git and remote-Git tests | `tests/discovery/test_checkpoint*.py`, `test_git_*.py`, `test_remote_git*.py`, `test_remotegit_policy.py`, `test_hashing.py`, `test_directory_links.py` | adapted to the new package; 491 tests |

Replaced rather than copied: ZIP extraction uses the platform's existing `enterprise/ingest/safe_extract.py` (one extractor, not two);
all Pascal detection, classification, project/unit/dialect logic, the blueprint and the Pascal dashboard were **not** reused.
The UI is a new page in the existing React app.

## What discovery finds (COBOL specific)

* **Classification** of every file by name and content (members often have no extension): COBOL, copybook, JCL job, JCL procedure,
  BMS, SQL/DDL, IDCAMS and SORT control files, build files, scripts, CI, assembler, PL/I, REXX, CLIST, data, documents, archives, binary,
  unknown. EBCDIC (cp037) sources, including 80-byte record files without line breaks, are decoded for scanning and flagged.
* **COBOL**: reference format (fixed, free, mixed), program ids, nested programs, `COPY` (library, `REPLACING`), `-INC`/`++INCLUDE`,
  static and dynamic `CALL` (followed through `VALUE`/`MOVE` literals), `ENTRY`, `SELECT`/`ASSIGN` with organisation, keys, file status and
  VSAM candidates, `SORT`/`MERGE`, environment access, `CBL`/`PROCESS` options, dialect signals.
* **Embedded subsystems**: `EXEC SQL` (tables per operation, cursors, includes, dynamic SQL, stored procedure calls), `EXEC CICS` (programs, files,
  maps, transactions, queues), `EXEC DLI` and `CBLTDLI` calls (PSB, segments, function codes), MQ API calls and queue names, DB2/LE/runtime library calls.
* **JCL**: jobs, procedures, steps, DDs (datasets, GDG, members, temporary, referback, in-stream, SYSOUT, DUMMY, USS paths), symbols (`SET`, `PROC`
  defaults), `INCLUDE`, `JCLLIB`, step-level DD overrides, IDCAMS (clusters KSDS/ESDS/RRDS/LDS, AIX, GDG, REPRO), SORT/ICETOOL, TSO/DB2 (`DSN`, `RUN`, `BIND`),
  IMS region controller, CICS CSD and MQ utility definitions, compile and link steps.
* **Other**: BMS mapsets, DDL tables/indexes/views, `Makefile`/`cobc`/script/Maven/Gradle build configuration, `COB_*` runtime settings, Java dependencies.
* **Dependency graph** (`dependency-graph.json`): every edge has source file, line and column; four resolutions (`resolved`, `external`, `ambiguous`,
  `unresolved`); unresolved edges carry a closed reason and a `blocking` flag and are never dropped. COBOL files are bound to datasets through the JCL step that runs the program.
* **Runtime dependencies** and **dialect evidence** (indicative only), each with the source positions that justify it.

## Artefacts (deterministic: same bytes in, same bytes out)

`discovery-report.json`, `dependency-graph.json`, `file-inventory.json` (every file and every directory, empty ones included),
`unresolved-references.json`, `discovery-summary.md`; `run-record.json` holds the only wall-clock values. No artefact contains a local path.

## The completeness gate

`INCOMPLETE` when the checkpoint does not verify, a file is missing from the inventory or too large to scan, a scanner reports an error, a blocking
reference is unresolved (missing program, copybook, procedure, include, mapset or source), or an archive nested in the upload is unexpanded.
Otherwise `COMPLETE_WITH_OPEN_ITEMS` (dynamic targets, catalog objects such as external tables, ambiguous references, unclassified files, unbound DD names)
or `COMPLETE`. `ready_for_transformation` is false whenever the status is `INCOMPLETE`. Nothing in this change consumes the flag: Java transformation was not started.

## Integrity and security

* Source is frozen into `checkpoints/<CP-id>/` (read-only, sealed with SHA-256 or HMAC-SHA256 when `SYSTEMAOPS_STORE_KEY` is set) **before** any scan; scanning
  re-hashes every file it reads and the report step re-verifies the checkpoint. The original ZIP is preserved byte for byte. The customer input is never modified.
* Git is pinned to the exact commit and tree before processing; `.git` is not part of the source. Remote Git: https only, public hosts only, resolved IP pinned,
  redirects off, credentials scrubbed from every message. The API accepts only https Git URLs and ZIP uploads, never server paths.
* ZIP: traversal, absolute and drive paths, backslashes, device names, symlinks and special files, encrypted entries, duplicate and case/Unicode-colliding names,
  bombs (ratio and bytes written), entry and depth limits; a refusal leaves no staging, checkpoint or report.

### Defects fixed before reuse (audit of the ported code)

1. Reuse of an existing checkpoint now requires identical content (`source_digest`), not just an existing id; ids widened from 48 to 128 bits.
2. The extracted ZIP and the preserved original are now the same single staged copy (no swap window).
3. Directory-spelling case collisions (`Foo/a` vs `foo/b`) are refused.
4. ZIP file-versus-directory conflicts and unreadable input files raise typed refusals, not raw `OSError`s with local paths.
5. A trailing newline in a commit pin is rejected.
6. A reused checkpoint's report takes its provenance from the stored checkpoint, and artefacts are written atomically.

Known and not fixed: unkeyed seals are accepted when `SYSTEMAOPS_STORE_KEY` is unset (set the key in production; unkeyed seals only detect accidental change);
local Git clones have no size watchdog; short (7 to 39 hex) commit pins are accepted for local repositories;
`192.0.0.8` and `3fff::/20` are treated as public by the SSRF policy.

## API

| Method and path | Role | |
|---|---|---|
| `POST /discovery/runs/zip` | operator | multipart upload, bounded by `CONTROL_PLANE_MAX_ZIP_ARCHIVE_BYTES`; 202 |
| `POST /discovery/runs/git` | operator | `{url (https), ref?, label?}`; 202 |
| `GET /discovery/runs`, `GET /discovery/runs/{id}` | viewer | state, steps, gate |
| `GET /discovery/runs/{id}/{report,graph,inventory,unresolved,summary}` | viewer | artefacts |
| `POST /discovery/runs/{id}/verify` | operator | re-hash the checkpoint |

Runs execute on a two-worker pool and are recorded in `runs/<id>.json`; after a restart an unfinished run is `interrupted`. Storage is under
`CONTROL_PLANE_WORKSPACE_DIR/discovery`. ZIP limits follow the control plane's `CONTROL_PLANE_MAX_ZIP_*` settings.

## Limitations (actual)

* Lexical scanning, not compilation: `COPY ... REPLACING` and copybook text are not expanded, conditional compilation is not evaluated, nested copybook content is not seen inside programs.
* Names built at run time are reported as dynamic; only same-program `VALUE`/`MOVE literal` candidates are followed.
* JCL procedures and symbols resolve only from the same upload; `IF/THEN/ELSE` conditions are recorded, not evaluated.
* Datasets, tables, queues, PSBs and CICS resources are linked by name; definitions exist only if the DDL, IDCAMS, MQSC or CSD source is in the upload.
* Dialects are indicative evidence, not a compiler verdict. No IBM, Micro Focus or GnuCOBOL compile is run.
* Archives nested in the upload are inventoried and block the gate; they are not expanded.
* Symlink and junction tests are skipped on this Windows machine (no privilege); they run on Linux CI.
* Discovery runs in-process on a thread pool (like the rest of the control plane); there is no external worker queue, retention or quota for checkpoints.
* The UI lists the report; it has no graph visualisation.

## Compiler, application and readiness discovery

See [`COMPILER_AND_APPLICATION_DISCOVERY.md`](COMPILER_AND_APPLICATION_DISCOVERY.md): open-source compiler detection and syntax-only compatibility, unsupported proprietary features, entry points,
application boundaries, cross-application relationships, and the readiness gate that `modernize` and `revalidate` enforce.

## Tests

`tests/discovery/` (backend, about 700 tests) and `frontend/src/__tests__/discovery.test.tsx`. Coverage numbers are in `docs/discovery/COVERAGE.md`.
