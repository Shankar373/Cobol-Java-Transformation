# Layer 1 and Layer 2 audit (2026-11-18)

Independent read-only audits plus probes (scratchpad scripts, 710 discovery tests). "Production-ready" means verified by tests or probes here, not certified.

## Layer 1: secure ingestion and immutable inventory
| Capability | Status |
|---|---|
| ZIP slip, absolute/`..`/drive/control/reserved names, symlinks/special/encrypted entries, duplicate, case and NFC collisions, byte/size limits | production-ready |
| ZIP bomb ratio | fixed: the ratio applies only to entries over 1 MiB (blank-padded COBOL compresses beyond 200:1); byte limits still bound everything |
| Nested archives | implemented: kept as `archive`, never expanded, blocks readiness |
| Git local and remote (https only, SSRF check per resolved IP, pinned DNS, no redirects/proxies, scoped token, commit pinning, hooks off, no submodules/symlinks) | production-ready |
| Git byte fidelity | **fixed**: `.gitattributes` (`eol=crlf`, `ident`, `text=auto`, filters) changed staged bytes and therefore digests per host; `info/attributes` now disables every conversion (test added) |
| Inventory completeness | fixed: an oversized member of unknown class (mainframe members have no extension) is now a blocker instead of a silent omission |
| Checkpoint: content-addressed id, atomic publish, read-only, seal, tamper detection | production-ready; HMAC only when `SYSTEMAOPS_STORE_KEY` is set |
| Determinism | implemented (wall clock only in `run-record.json`) |
| Concurrent identical discovery | **fixed**: shared temp name crashed; per-thread temp names, skip identical artefact, replace retry (Windows) |
| Scanner robustness | **fixed**: a quadratic regex (`\s*...\s*ID DIVISION`) took 57 s on a 100 KB blank line; hostile 100 KB inputs in 13 shapes x 14 extensions now run in about 70 ms per file |
| API authz, path traversal, upload size | implemented, tested |

Open (not fixed here): D4 store key not required in production (checksum-only seal without it); D5 long Windows paths report a misleading error; D7 crash recovery does not sweep `discovery-stage-*` and `.CP-*.tmp-*`; D8 no rate limit or queue bound on discovery — **closed for readiness assessments by Layer 14** (`CONTROL_PLANE_MAX_READINESS_ASSESSMENTS`, typed 429; the `/discovery/runs` pool was already bounded at 2 workers; the UI half, run lost on reload, remains); D9 git symlink/submodule refusal runs after checkout (mitigated by `core.symlinks=false` and the `ls-tree` precheck); D10 `/source` is served without re-verifying the checkpoint; the UI loses the run on reload. Symlink refusal tests are skipped on this Windows host (run on Linux CI).

## Layer 2: application and compiler discovery
| Capability | Status |
|---|---|
| Tool detection (cobc, gcobol, ocesql, JDK, Maven; local and container) | honest; only cobc is probed in the container; gcobol is probed, not used; ocesql is probed, not integrated |
| Dialect/source format | implemented, advisory |
| Build flags from Makefile/JCL/scripts | partial: detected and reported as evidence, **not applied** to the compile plan or copybook ordering |
| Compiler validation framing | `-fsyntax-only` per file with GnuCOBOL; not application compilation, not production-compiler compatibility; the report says so |
| Proprietary compatibility | never claimed; CICS/DL/I/Db2/MQ/LE/OO/assembler listed as unsupported |
| Dependency resolution (copybooks, static CALL, JCL PGM/PROC, SQL INCLUDE, case) | implemented, file:line evidence |
| Dynamic CALL | partial: literal `MOVE`/`VALUE` candidates become resolved edges; others are open items |
| Library search order | missing (heuristic nearest/shortest path) |
| Application boundaries, entry points, cross-application relationships | implemented |
| Readiness gate | strengthened (below) |

Fixed in this change:
* **READY without a compiler** (HIGH): `NOT_ATTEMPTED_NO_COMPILER/TOOL_FAILURE/BUDGET/BLOCKED_DEPENDENCY` made no difference. Now a program that could be checked but got no verdict makes the status `NOT_SUPPORTED` with an `unverified` list (also per application); `READY` requires a real compiler verdict.
* **Stale-readiness bypass** (HIGH): the fingerprint was path/size/mtime. It is now the SHA-256 of every file's content plus the toolchain setting and a policy version. A transient `INTERNAL_ERROR` assessment is no longer cached as BLOCKED.
* **Ungated consumer**: `POST /applications/{id}/vsam/migrate` now passes the same gate.
* **ocesql overclaim**: `EXEC SQL` programs were sent to plain `cobc` when ocesql was on PATH. They are never syntax-checked now (`NOT_ATTEMPTED_SQL_PRECOMPILER`).

Open: build profile (`-std`, `-free`, `-I` order) not applied; library order; ~~the engine `UniversalModernizationPipeline.execute` and background workers do not re-check the gate~~ — **closed by Layer 14 (L14-P1)**: both background workers re-check the gate before generation/validation (the engine stays a pure orchestrator; the service-layer convention is now enforced on every path); ~~legacy `/estate`, `/decomposition` read endpoints use the old discovery~~ — audited 2026-11-26: they read through the sanctioned `graph_view` (layer-2 scanners + `resolve.build_graph`), the remaining cost is a second scan pass per request (`docs/architecture/LAYER14_DESIGN.md` §6); ambiguous references and unresolved dynamic CALLs do not lower readiness; the container image tag is mutable (`gnucobol-ocesql:latest`) and its digest is not recorded.
