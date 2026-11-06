# Source-level gap audit (2026-11-06)

Scope: the code on `impl/enterprise-platform` at `e4d7bc6` (registry `engine/transformation/semantic_capability.py`,
parser, mapper, analyzer, tests), read directly. Documents were used only to locate code. Evidence classes:
**RUNTIME-PROVEN** (generated Java equals GnuCOBOL 3.1.2 or OCESQL + PostgreSQL 14 in a test that runs in CI),
**SIMULATOR-ONLY** (Java twin equals an in-repo specification; no vendor runtime), **PARTIAL**, **UNSUPPORTED**
(detected, classified, never transformed). Nothing here is IBM-verified: the only runtimes available are
GnuCOBOL 3.1.2 and PostgreSQL 14, so no claim of IBM Enterprise COBOL, DB2, CICS, IMS or MQ equivalence is made.

## 1. Procedure and data constructs (`CONSTRUCT_REGISTRY`: 43 SUPPORTED, 9 PARTIAL, 12 UNSUPPORTED)

| Construct | State in source | Gap and why it matters |
|---|---|---|
| `GO TO` | **Closed in unit 26 (bounded subset, GnuCOBOL-proven)**; DEPENDING, jumps out of PERFORM ranges, GO TO under simple/loop PERFORMs, LINKAGE programs stay refused | Plain `EXIT.` was also refused as an unknown statement and is now a no-op |
| `ALTER`, `NEXT SENTENCE` | UNSUPPORTED (parser records a diagnostic; mapper emits a comment) | Need their own lowering |
| `LOCAL-STORAGE`, `RELEASE`, `SET` (non-index forms: ADDRESS, pointers) | UNSUPPORTED | LOCAL-STORAGE needs per-invocation state; RELEASE needs SORT INPUT PROCEDURE |
| `COMP`, `COMP-3`, `COMP-5`, `COMP-1`, `COMP-2` | PARTIAL: value semantics mapped, byte encoding not certified | Packed/binary byte layouts decide whether record-level (VSAM, sequential, EBCDIC) data migrates correctly |
| `REDEFINES`, `OCCURS` | PARTIAL; certified subsets exist (digit views; fixed one-dimensional DISPLAY tables) | Multi-dimension, `DEPENDING ON`, group tables, non-DISPLAY tables are refused |
| `BY VALUE`, `REPLACE` | PARTIAL; BY VALUE cannot be proven because GnuCOBOL 3.1.2's implementation is unfinished | Not provable on the available oracle |
| `SORT`/`MERGE` | RUNTIME-PROVEN for file-to-file; INPUT/OUTPUT PROCEDURE, several GIVING files, COLLATING refused | `RELEASE`/`RETURN` missing |
| `SEARCH`/`SEARCH ALL`/`SET idx` | RUNTIME-PROVEN subsets (linear; binary on equality) | Multi-WHEN SEARCH ALL, multi-key, `VARYING` an index refused |
| `INSPECT` | RUNTIME-PROVEN literal subset | data-name operands, `TRAILING`, combined forms refused |
| numeric-edited PIC | NOT in this branch (uncommitted on `feat/phase3-coverage`, needs owner authorization) | blocks report-style output |

## 2. Files and data (VSAM modernization)

RUNTIME-PROVEN: sequential, LINE SEQUENTIAL, INDEXED (RECORD KEY at any position, `ACCESS` SEQUENTIAL-by-default/RANDOM/DYNAMIC subset; units 27 and 29),
RELATIVE, FILE STATUS, START, REWRITE, DELETE, INVALID KEY. Open: `ALTERNATE RECORD KEY`, primary key at a non-zero
offset, `ACCESS MODE SEQUENTIAL` write-order rules, packed/binary/EBCDIC record encodings, VSAM catalog (IDCAMS DEFINE
CLUSTER) and REPRO as data movement; the keyed side file is a Java-native structure, not VSAM.

## 3. JCL and DB2

JCL: analysis plus a launcher (`engine/jcl/`) for COBOL steps, COND, IEFBR14, IEBGENER, IDCAMS (DELETE, DEFINE GDG,
REPRO, SET MAXCC), GDGs, dispositions; proven against GnuCOBOL runs and documented utility semantics only (no JES, no IBM
utility oracle). Not covered: nested procedures, IF/THEN/ELSE evaluation, DFSORT/ICETOOL, IEBCOPY, abends, restart.
DB2: `EXEC SQL` is RUNTIME-PROVEN against OCESQL + PostgreSQL 14 (a reference, not DB2); DB2-specific SQL, cursors with
isolation clauses, SQLCODE/SQLSTATE parity with DB2 and stored procedures are unproven.

## 4. CICS, IMS, MQ

All three are UNSUPPORTED in the transformer (`EXEC CICS`, `EXEC DLI`, `CALL DLI`, `EXEC MQI`, `CALL MQI`). SIMULATOR-ONLY
models exist (SIMCICS-1, SIMDLI-1, SIMMQ-1, Python reference and Java twin on a shared trace comparator). Missing: the
precompiler/translator path from COBOL to the Java libraries, a COBOL-callable shim to produce an oracle trace, BMS maps,
PCB/IO areas, MQ structures (MQMD, MQOD, MQGMO). Without an IBM environment these can only reach SIMULATOR_VERIFIED.

## 5. Mainframe-independent execution

The generated Java runs on a plain JVM (Spring Boot, Quarkus, Micronaut, plain Java certified on four runtimes against a
GnuCOBOL corpus). Open: multi-artifact and container generation for a decomposed estate (planner exists), packaging of
batch launchers, and the control-plane items that need decisions (OIDC/SSO, signing, Docker socket isolation).

## 6. Quality gates

Type check ratchet (209 baseline errors), coverage floor 88%, no branch coverage, Windows lane for hermetic tests. The
condition mapper still refuses abbreviated combined relations over subscripts and multi-dimension subscripts.

## 7. Prioritized backlog derived from the above

1. ~~`GO TO` / paragraph fall-through lowering~~ done in unit 26 for the bounded subset (see the capability matrix for what stays refused).
2. COMP-3 / COMP / COMP-5 byte encodings in record areas, with a GnuCOBOL byte-level oracle.
3. `NEXT SENTENCE`, `LOCAL-STORAGE`, `RELEASE`/`RETURN` with SORT procedures.
4. VSAM breadth: alternate keys, key offset, ACCESS SEQUENTIAL rules.
5. JCL: IF/THEN/ELSE, nested procedures, DFSORT subset.
6. CICS/IMS/MQ lowering to the simulator libraries (SIMULATOR_VERIFIED ceiling).
7. Multi-artifact generation from the decomposition planner.
