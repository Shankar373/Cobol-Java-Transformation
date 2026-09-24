# SystemaOps Current Capability Verification

## 1. Verification Date

- **Date (UTC):** 2026-09-21
- **Forensic campaign RUN_ID:** `forensic-20260921073451`
- **Campaign window (UTC):** 2026-09-21T07:34:51Z → ~08:30Z (20 workloads, sequential)
- **Fresh output root (isolated, outside repo):** `C:\Users\bandi\AppData\Local\Temp\opencode\forensic-20260921\`
  - 20 per-workload JSON files (`workload-*.json`), `summary.csv`, `generated_apps/<workload>/` Spring Boot projects
- **Verification harness (new, test-only, does not touch production):**
  - `C:\Users\bandi\AppData\Local\Temp\opencode\forensic_run.py` — drives the EXACT production path per workload:
    `ApplicationDiscovery().discover()` → `ApplicationGenerator().generate()` →
    `map_java_application_to_spring_boot()` → `SpringBootGenerator().generate_project()` →
    `VerticalSlicePipeline` with `DockerOracleAdapter` + `DockerSpringBootCandidateAdapter`
  - `C:\Users\bandi\AppData\Local\Temp\opencode\single_pass_proof.py` — corrected-signature behavioral proof of the single mapping pass
  - `C:\Users\bandi\AppData\Local\Temp\opencode\disco_check.py` — 3-program N→N + paragraph-less discovery/generation checks
- **No production file was modified. No commit. No push. No git destructive operation.**

## 2. Repository Commit / Working Tree State

- **HEAD SHA:** `9ca0cfd8b8c83f2d246eda78ea8bb5b844b2fdf9`
- **Working tree: DIRTY.** All results below reflect the dirty working tree, not pristine HEAD.
- Modified tracked files (`git diff --stat`, 826 insertions, 92 deletions across 9 files):
  - `engine/oracle/docker_adapter.py` (+103/-?)
  - `engine/pipeline.py`
  - `engine/transformation/cobol_parser.py` (+379-line-scale change)
  - `engine/transformation/cobol_to_java_mapping.py`
  - `engine/transformation/ir.py`
  - `engine/transformation/java_to_spring_mapping.py`
  - `engine/transformation/jcl_parser.py`
  - `engine/transformation/spring_boot_generator.py`
  - `engine/transformation/spring_boot_ir.py`
- Untracked (new, not committed): `api/`, `engine/cics/`, `engine/jcl/`, `engine/sql/`,
  `engine/transformation/application_generator.py`, `cics_java_mapping.py`, `copybook_model.py`,
  `copybook_resolver.py`, `jcl_consumer.py`, `jcl_spring_batch_ir.py`, `jcl_to_spring_batch.py`,
  `sql_repository_mapping.py`, plus dozens of `fix_*.py` / `test_*.py` / `apply_fix*.py` scratch scripts
  at repo root and `fixtures/workload-claims`, `docs/decisions/DB2_MODERNIZATION_PROFILE.md`,
  `docs/specs/JCL_*` additions.
- **Consequence:** failures below are properties of the CURRENT working tree. No baseline-vs-dirty
  bisection was performed (out of scope; task forbids reverting existing work).

## 3. Verification Environment

| Component | Value |
|---|---|
| OS | Windows 11 (10.0), amd64 |
| Python | 3.14.3 |
| Host Java | Eclipse Temurin 25.0.3 (LTS) — NOT used for validation |
| Host Maven | Apache Maven 3.9.16 — NOT used for validation |
| Docker | 29.6.2 (desktop-linux context) |
| Oracle image | `gnucobol-ocesql:latest`, RepoDigest `gnucobol-ocesql@sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780`, `cobc (GnuCOBOL) 3.1.2.0` — matches `DockerOracleAdapter.V1_DIGEST` |
| Candidate build image | `maven-offline-springboot:latest`, RepoDigest `maven-offline-springboot@sha256:99d13a5416066fcba901aec7cb10a4bffd4d5e081cf94475478b35e023a7f678` — matches `DockerSpringBootConfig.build_digest` |
| Candidate runtime image | `eclipse-temurin:21-jdk`, RepoDigest `eclipse-temurin@sha256:1f79c73404fb0cccf9a3459eda22892f368d994b1028d6fb1ae871c1f49749a6` — matches `DockerSpringBootConfig.runtime_digest` |
| Candidate adapter availability | `AVAILABLE` (digest checks passed) |
| Network for containers | `--network none` everywhere; no host `javac`/`java` fallback in production path (`use_docker_java=True`; `RealJavaCandidateAdapter` never implicitly selected) |

## 4. Verification Method

Evidence ladder (no skipping):

| Level | Meaning |
|---|---|
| LEVEL 0 = NOT_TESTED | discovery produced no programs, or workload never ran |
| LEVEL 1 = PARSED_ONLY | COBOL parsed/discovered, transformation failed or absent |
| LEVEL 2 = MODELED_ONLY | Java IR mapped, Spring mapping/generation failed |
| LEVEL 3 = TRANSFORMED | Spring Boot project generated (pom + sources on disk) |
| LEVEL 4 = BUILDS | Docker Maven build produced a JAR |
| LEVEL 5 = EXECUTES | JAR started in Docker runtime (even on timeout) |
| LEVEL 6 = ORACLE_MATCHED | fresh pipeline oracle ran AND outputs matched |
| LEVEL 7 = FRESH_VERIFIED | LEVEL 6 + evidence integrity validated, fresh run, hashes recorded |

A workload is FRESH_VERIFIED only with: fresh pipeline oracle execution + fresh Java execution +
actual stdout/exit/file comparison MATCH + integrity validator clean + hashes recorded.
Manual `cobc -free` runs in this report are labeled **SUPPLEMENTARY (non-certifying)** ground truth:
they prove what the COBOL does, but never count toward pipeline levels.

## 5. Executive Result

**Headline: 0 of 20 workloads reach ORACLE_MATCHED or FRESH_VERIFIED through the production pipeline.**

| Workload | Final stage (fresh pipeline) | Verdict |
|---|---|---|
| workload-call-linkage | TRANSFORMED | build failed (javac errors) |
| workload-by-reference | TRANSFORMED | build failed (javac errors) |
| workload-by-content | TRANSFORMED | build failed (javac errors) |
| workload-by-value | TRANSFORMED | build failed (javac errors) |
| workload-dynamic-call | TRANSFORMED | build failed (javac errors) |
| workload-copybook | EXECUTES | ERROR (oracle compile fail + Java timeout in pipeline) |
| workload-subtract | TRANSFORMED | build failed (javac errors) |
| workload-multiply | TRANSFORMED | build failed (javac errors) |
| workload-evaluate | TRANSFORMED | build failed (javac errors) |
| workload-perform-varying | TRANSFORMED | build failed (javac errors) |
| workload-occurs | TRANSFORMED | build failed (javac errors) |
| workload-redefines | TRANSFORMED | build failed (javac errors) |
| workload-level88 | TRANSFORMED | build failed (javac errors) |
| workload-comp | NOT_TESTED | parser rejects `S9(4)`/`S9(9)` |
| workload-comp3 | NOT_TESTED | parser rejects `S9(5)V99`/`S9(7)V99` |
| workload-indexed-file | TRANSFORMED | build failed (invalid POM: `spring-file-io` without version) |
| workload-relative-file | TRANSFORMED | build failed (invalid POM: `spring-file-io` without version) |
| workload-rewrite | TRANSFORMED | build failed (invalid POM: `spring-file-io` without version) |
| workload-delete | TRANSFORMED | build failed (invalid POM: `spring-file-io` without version) |
| workload-start-invalidkey | TRANSFORMED | build failed (invalid POM: `spring-file-io` without version) |

Counts: PARSED_ONLY 0 · MODELED_ONLY 0 · TRANSFORMED 17 (stopped) · BUILDS 1 (copybook) ·
EXECUTES 1 (copybook) · ORACLE_MATCHED 0 · FRESH_VERIFIED 0 · FAILED-or-blocked 19 · UNSUPPORTED-by-parser 2.

Two systemic product blockers explain ~all of it (Section 10):
**B1.** Oracle adapter invokes `cobc -x` with no `-free` flag while every fixture is free-format →
pipeline oracle NEVER executes any workload (all oracle results are GnuCOBOL compile errors, exit 1,
empty stdout). Nothing can reach LEVEL 6/7 until this is fixed.
**B2.** Generated Spring Boot projects do not build: (a) 12 workloads emit uncompilable Java
(COBOL keywords as identifiers, type errors, wrong arity); (b) 5 file workloads emit an invalid
`pom.xml` (`org.springframework:spring-file-io` with no version).

## 6. Capability Matrix

Legend for stage columns: value = highest pipeline level actually demonstrated with fresh evidence
(Section 7). "Oracle" = pipeline oracle executed the program (not merely ran cobc).

| # | Capability | Input | Discovery | Transformation | Generated Artifacts | Builds | Executes | COBOL Oracle | Comparison | Evidence | Final Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Overall architecture | 20 fixtures | all discovered (18/20) | 18/20 Spring projects | pom+src+Application.java all 18 | 1/20 (copybook) | 1/20 (copybook) | 0/20 pipeline | 1/20 attempted (copybook, MISMATCH) | fresh, integrity clean | PARTIALLY VERIFIED (pipeline runs E2E; equivalence unproven) |
| 2 | Dynamic application discovery | multi-file dirs | per-file units, no concatenation (Sec 9A) | n/a | n/a | n/a | n/a | n/a | n/a | fresh JSON | VERIFIED |
| 3 | N → N transformation | 3-prog + 2-prog fixtures | 3→3 units, 2→2 units | per-program classes + ServiceRegistry | Alpha/Beta/Gamma.java, Main/Modify.java | n/a (shape only) | n/a | n/a | n/a | fresh JSON | VERIFIED (structure; runtime unproven) |
| 4 | Single mapping pass | ALPHA.cob via API lane | n/a | generate×1, same object reused, 0 late COBOL maps | n/a | n/a | n/a | n/a | n/a | behavioral proof script | VERIFIED (mapping layer; committed P0 tests fail on test-bug) |
| 5 | Spring Boot generation | 18 discovered apps | n/a | spring mapping+generator OK 18/18 | pom.xml + Application.java + services, entrypoint FQN | 1/18 | 1/18 | n/a | n/a | fresh projects on disk | TRANSFORMED ONLY (BUILDS proven once) |
| 6 | Docker Java execution | copybook JAR (10 MB) | n/a | n/a | JAR in target/ | yes | RC=0, 153 B stdout (manual rerun w/ time) | n/a | vs manual oracle: identical lines (supplementary) | fresh container logs | EXECUTES ONLY (pipeline run timed out at 30 s) |
| 7 | Independent GnuCOBOL oracle | 20 cobol dirs | n/a | n/a | n/a | n/a (cobc) | 0/20 in pipeline | FAILED ALL (missing `-free`) | none possible | fresh stderr captured | FAILED (harness flag bug; programs themselves valid — see Sec 8) |
| 8 | Evidence/security boundary | adversarial mutations | n/a | n/a | n/a | n/a | n/a | n/a | 205/205 unit attacks pass | pytest, no docker | VERIFIED (as unit-tested; NOT behavior proof) |
| 9 | API/control plane | TestClient | discovery/tracking | modernize lane (fake pipeline) | generated dir + entrypoint | n/a | n/a | n/a | n/a | 73 pytest pass | VERIFIED (orchestration; not E2E equivalence) |
| 10 | Frontend console | mocked API | render discovery/edges | n/a | n/a | `vite build` not run here | n/a | n/a | n/a | 81 vitest pass | PARTIALLY VERIFIED (renders; no live-backend E2E) |
| 11 | Dynamic application naming | upload/ingest | detected_name | n/a | n/a | n/a | n/a | n/a | n/a | test_name_derivation pass (in 73) | VERIFIED (unit) |
| 12 | Async progress | modernize/validate | stage transitions | background thread | n/a | n/a | n/a | n/a | n/a | test_async_modernize pass (in 73) | VERIFIED (unit) |
| 13 | COPYBOOK | MAIN.cob+COMMON.CPY | COPY edge recorded | model CommonRecord.java + merged Demo | 2 java artifacts, Spring app | JAR built | RC=0 manual; pipeline timeout | pipeline compile-fail; manual `-free` OK, 7 lines | pipeline MISMATCH (empty-vs-timeout); manual identical (supplementary) | fresh | EXECUTES ONLY |
| 14 | Static CALL arity-0 | call-linkage (MAIN+CALCULATE) | CALL edge MAIN→CALCULATE | 2 program classes + registry | Calculate.java, Main-equivalent, registry | NO (javac: cannot find symbol) | NO | NO (B1 + fixture LINKAGE order defect) | none | fresh | TRANSFORMED ONLY |
| 15 | CALL USING / LINKAGE | by-ref/by-content/by-value | CALL+USING args recorded | Main+Modify classes | 3 artifacts each | NO (String→int, arity) | NO | by-ref/by-value run under manual `-free`; by-content rejected by GnuCOBOL 3.1 (`BY CONTENT` unsupported) | none | fresh | TRANSFORMED ONLY |
| 16 | Dynamic CALL | dynamic-call (MAIN+CALC) | CALL target recorded as STATIC (limitation) | Main+Calc classes | 3 artifacts | NO (javac errors) | NO | NO (B1 + LINKAGE order defect) | none | fresh | TRANSFORMED ONLY (dynamic dispatch itself unproven even structurally) |
| 17 | JCL | fixtures/workload-jcl | jcl discovery exists | JCL→Spring Batch IR + generation (unit) | batch artifacts (unit) | not exercised E2E | NO | NO | none | 117-test subset pass | MODELED ONLY (no z/OS/JES equivalence — none claimed by code) |
| 18 | DB2 / EXEC SQL | fixtures/workload-db2 | SQL deps extracted (unit) | repository mapping (unit) | repository/service (unit) | not exercised E2E | SQLite only (unit) | NO real DB2 | none | unit pass (incl. test_db2_execution) | MODELED ONLY + SQLite-execution (unit); NO DB2 runtime equivalence |
| 19 | CICS | fixtures/workload-cics | CICS constructs parsed (unit) | CICS→Java mapping (unit) | model classes (unit) | not exercised E2E | NO | NO CICS TS | none | 117-test subset pass | MODELED ONLY; NO CICS TS equivalence |
| 20 | COMP | `PIC S9(4)/S9(9) COMP` | 0 programs (parse fail) | none | none | n/a | manual `-free` runs (ground truth Sec 8) | pipeline: never ran | none | fresh parser error | UNSUPPORTED (parser gap; COBOL itself valid) |
| 21 | COMP-3 | `PIC S9(5)V99 COMP-3` | 0 programs (parse fail) | none | none | n/a | manual `-free` runs | pipeline: never ran | none | fresh parser error | UNSUPPORTED (parser gap; COBOL itself valid) |
| 22 | SUBTRACT | 4 SUBTRACT forms | 1 program | Demo class (SUBTRACT folded into println — bug) | SubtractDemo.java + Spring app | NO (`SUBTRACT/FROM/GIVING` as identifiers) | NO | NO (B1); manual `-free`: 75/90/25/85 correct | none | fresh | TRANSFORMED ONLY |
| 23 | MULTIPLY | 4 MULTIPLY forms | 1 program | same folding bug | MultiplyDemo.java + Spring app | NO (same) | NO | NO (B1); manual `-free`: correct | none | fresh | TRANSFORMED ONLY |
| 24 | EVALUATE | grades | 1 program | folding bug | EvaluateDemo.java + Spring app | NO (cannot find symbol) | NO | NO (B1); manual `-free`: B/GOOD correct | none | fresh | TRANSFORMED ONLY |
| 25 | PERFORM VARYING | 2 loops | 1 program | folding bug | PerformVaryingDemo.java + Spring app | NO | NO | NO (B1); manual `-free`: SUM=15 PROD=24 correct | none | fresh | TRANSFORMED ONLY |
| 26 | OCCURS | 5-element table | 1 program | folding bug | OccursDemo.java + Spring app | NO | NO | NO (B1); manual `-free`: SUM=150 correct | none | fresh | TRANSFORMED ONLY |
| 27 | REDEFINES | numeric/char views | 1 program | folding bug | RedefinesDemo.java + Spring app | NO | NO | NO (B1); manual `-free`: correct | none | fresh | TRANSFORMED ONLY |
| 28 | 88-level conditions | STATUS/GENDER | 1 program | type error (int→String) + symbols | Level88Demo.java + Spring app | NO | NO | NO (B1); manual `-free`: correct | none | fresh | TRANSFORMED ONLY |
| 29 | INDEXED files | ORGANIZATION INDEXED | 1 program + file deps | adapter + service generated | project + POM | NO (POM: spring-file-io no version) | NO | NO (B1; fixture line 74 also rejected by GnuCOBOL: `RECORDS...STATUS` syntax) | none | fresh | TRANSFORMED ONLY |
| 30 | RELATIVE files | ORGANIZATION RELATIVE | 1 program + file deps | generated | project + POM | NO (same POM bug) | NO | NO (B1) | none | fresh | TRANSFORMED ONLY |
| 31 | REWRITE | rewrite fixture | 1 program + file deps | generated | project + POM | NO (same POM bug) | NO | NO (B1) | none | fresh | TRANSFORMED ONLY |
| 32 | DELETE | delete fixture | 1 program + file deps | generated | project + POM | NO (same POM bug) | NO | NO (B1) | none | fresh | TRANSFORMED ONLY |
| 33 | START | start fixture | 1 program + file deps | generated | project + POM | NO (same POM bug) | NO | NO (B1) | none | fresh | TRANSFORMED ONLY |
| 34 | INVALID KEY | start-invalidkey | recorded in discovery/file deps | generated | project + POM | NO (same POM bug) | NO | NO (B1) | none | fresh | TRANSFORMED ONLY |
| 35 | Broad COBOL compatibility | 20 fixtures | 18/20 | 18/20 projects, 0/20 build clean | see inventory | 1/20 | 1/20 | 0/20 pipeline | 0/20 matched | fresh | UNPROVEN (no universal claim possible) |
| 36 | CICS TS equivalence | none exists | n/a | n/a | n/a | NO | NO | NO server | none | n/a | NOT TESTED (no harness, no server) |
| 37 | DB2 runtime equivalence | none exists (SQLite only) | n/a | n/a | n/a | n/a | SQLite unit | NO real DB2 | none | unit | NOT TESTED as DB2; SQLite subset EXECUTES (unit) |
| 38 | JCL/z/OS equivalence | none exists | n/a | n/a | n/a | NO | NO | NO z/OS | none | unit | NOT TESTED (parse/model only) |

Additional claimed-but-unlisted capabilities found in repo (all NOT covered by this 20-workload
campaign, status NOT TESTED here): `workload-claims` (batch + hand-written `java-candidate-osc4j`
candidate — note: hand-written, not generated — plus `test_claims_batch.py`),
`workload-payroll`, `workload-gradecalc`, `workload-studentproc`, `workload-arithmetic`,
`workload-multiprog` (multi-program), `workload-minimal`, `workload-indexed`/`workload-relative`
(legacy variants of the `-file` workloads), `workload-db2`, `workload-jcl`, `workload-cics`,
`engine/producers/opensource4j.py` + `internal_native.py` (alternate producers),
`engine/transformation/producer.py` manifest path. None of these were exercised end-to-end in this
verification; any prior claims about them are STALE until re-run through the fixed pipeline.

## 7. Workload Results

Common pipeline facts (all 20, RUN_ID `forensic-20260921073451`):
candidate adapter `DockerSpringBootCandidateAdapter/AVAILABLE`, oracle image
`gnucobol-ocesql:latest` (`@sha256:f6f567...`), build image
`maven-offline-springboot:latest`, runtime `eclipse-temurin:21-jdk`, `--network none`,
no host fallback. Pipeline oracle result for EVERY workload: `exit=1`,
`termination=nonzero_exit`, `stdout=""`, stderr = GnuCOBOL fixed-format compile errors
(B1). Source hashes + per-file COBOL text stored in each JSON.

### workload-subtract — TRANSFORMED ONLY
- Input: `MAIN.cob` (31 lines), PIC 9(4) ×4; 4 SUBTRACT forms (GIVING / in-place / multi-subject).
- Discovery: 1 program `SUBTRACT-DEMO`, 0 calls, 0 copybooks.
- Generated: `SubtractDemo.java` (+ Spring app `com.generated.app.Application`, pom).
  BUG: SUBTRACT statements folded into `System.out.println(...)` with `SUBTRACT/FROM/GIVING`
  emitted as Java identifiers; no arithmetic emitted (see Sec 10 B2a).
- Build: `mvn -o -B package` in Docker → COMPILATION ERROR, `cannot find symbol` ×N
  (SubtractDemo.java:21 etc.). No JAR. `java_exit=1` (synthesized compile-fail).
- Oracle (pipeline): exit 1, `MAIN.cob:1: error: invalid indicator 'F' at column 7`.
- Comparison: none. Evidence: fresh, integrity clean. Verdict: build-blocked.

### workload-multiply — TRANSFORMED ONLY
- Same shape as subtract (MULTIPLY ×4 forms). Same folding bug in `MultiplyDemo.java:21`.
- Build: COMPILATION ERROR, no JAR. Oracle: same B1 failure. No comparison.

### workload-evaluate — TRANSFORMED ONLY
- Input: grade EVALUATE (`MAIN.cob`, 43 lines). Generated `EvaluateDemo.java:18` folding bug.
- Build: COMPILATION ERROR, no JAR. Oracle: same B1 failure. No comparison.

### workload-perform-varying — TRANSFORMED ONLY
- Input: 2 loops (SUM/PROD). Generated `PerformVaryingDemo.java:19` folding bug.
- Build: COMPILATION ERROR, no JAR. Oracle: same B1 failure. No comparison.

### workload-occurs — TRANSFORMED ONLY
- Input: 5-element OCCURS table. Generated `OccursDemo.java:18` folding bug.
- Build: COMPILATION ERROR, no JAR. Oracle: same B1 failure. No comparison.

### workload-redefines — TRANSFORMED ONLY
- Input: numeric/char REDEFINES views. Generated `RedefinesDemo.java:17-21` symbol errors.
- Build: COMPILATION ERROR, no JAR. Oracle: same B1 failure. No comparison.

### workload-level88 — TRANSFORMED ONLY
- Input: STATUS/GENDER 88s. Generated `Level88Demo.java:11`:
  `incompatible types: int cannot be converted to java.lang.String` + symbols at :18.
- Build: COMPILATION ERROR, no JAR. Oracle: same B1 failure. No comparison.

### workload-call-linkage — TRANSFORMED ONLY
- Input: `MAIN.cob` + `CALCULATE.cob` (LINKAGE SECTION ×3, `PROCEDURE DIVISION USING...GOBACK`).
- Discovery: 2 programs (`CALCULATE`, `MAIN`), CALL edge MAIN→CALCULATE recorded, no concatenation.
- Generated: 3 artifacts (2 program classes + ServiceRegistry), Spring app + pom.
- Build: COMPILATION ERROR in `Calculate.java:17-18` (`cannot find symbol`).
- Oracle: B1 on both files; additionally `CALCULATE.cob` is invalid for GnuCOBOL even with `-free`
  (LINKAGE before WORKING-STORAGE; `WS-TEMP is not defined`). Fixture defect F1.
- Comparison: none.

### workload-by-reference — TRANSFORMED ONLY
- Input: `MAIN.cob` + `MODIFY.cob` (`CALL ... USING ... BY REFERENCE`).
- Discovery: 2 programs (`MAIN`, `MODIFY`), CALL+USING recorded.
- Generated: 3 artifacts. Build: `Main.java:11 String→int`, `Main.java:22 MAIN_LOGIC arity`,
  `Modify.java:15` symbols. No JAR. Oracle: B1 only (sources valid; manual `-free` runs, Sec 8).

### workload-by-content — TRANSFORMED ONLY
- Same shape as by-reference. Same 3 javac errors. Oracle B1 in pipeline; manual `-free`:
  `MODIFY.cob:9: error: syntax error, unexpected CONTENT` — GnuCOBOL 3.1.2 has no `BY CONTENT`
  (fixture uses unsupported dialect feature; defect F2).

### workload-by-value — TRANSFORMED ONLY
- Same shape. Same 3 javac errors. Oracle B1 in pipeline; manual `-free` compiles with
  `-Wunfinished` warning and runs (BY VALUE semantics visible, Sec 8).

### workload-dynamic-call — TRANSFORMED ONLY
- Input: `MAIN.cob` + `CALC.cob` (CALL with identifier). Discovery records target as
  `STATIC`-typed edge — dynamic dispatch is NOT modeled (limitation, Sec 10 D4).
- Generated: 3 artifacts. Build: `Main.java:21` + `Calc.java:17-18` symbol errors. No JAR.
- Oracle: B1 + same LINKAGE-order fixture defect as CALCULATE (F1).

### workload-copybook — EXECUTES ONLY
- Input: `MAIN.cob` (33 lines, `COPY COMMON.`) + `COMMON.CPY` (copybook).
- Discovery: 1 program `COPYBOOK-DEMO`, copybooks=[`COMMON`], COPY edge recorded.
- Generated: 2 artifacts (`CopybookDemo.java`, `CommonRecord.java` model) + Spring app
  (`Application.java` with `CommandLineRunner` + `System.exit(0)`, `AppConfig.java`), pom OK.
- Build: SUCCESS — `workload-copybook-app-0.0.1-SNAPSHOT.jar` (10,344,132 B) in `target/`.
- Java execution: pipeline run → `timeout` after 30 s (Spring JVM startup under 512 m/1 CPU
  exceeds the execution budget); manual rerun of the same JAR → RC=0, 153 B stdout (Sec 8).
- Oracle (pipeline): exit 1 — `invalid indicator 'F'` on MAIN.cob AND `COMMON.CPY`
  (`invalid indicator 'A'`, level-number errors) — B1 (copybook staged but compiled fixed).
- Comparison: STDOUT MATCH is vacuous ("" vs ""); STDERR MISMATCH; EXIT_STATUS MISMATCH
  (1 vs null). Verdict ERROR. Integrity: clean (no staleness — failure is genuine).
- Evidence integrity: belongs to this run (`engine_run_id run-workload-copybook-20260921074112`).

### workload-comp — NOT_TESTED (parser UNSUPPORTED)
- Input: `PIC S9(4)/S9(9) COMP` (lines 7,8,10). Discovery: 0 programs —
  `Warning: Failed to parse ... MAIN.cob: Unsupported PIC clause: S9(4)`, unit skipped.
- No transformation, no build, no oracle in pipeline. Manual `-free` ground truth: Sec 8.

### workload-comp3 — NOT_TESTED (parser UNSUPPORTED)
- Input: `PIC S9(5)V99/S9(7)V99 COMP-3`. Discovery: 0 programs —
  `Unsupported PIC clause: S9(5)V99`. Rest as comp.

### workload-indexed-file — TRANSFORMED ONLY
- Input: ORGANIZATION INDEXED + FILE STATUS (75+ lines). Discovery: 1 program
  `INDEXED-FILE-DEMO` + file deps. Generated: project + adapters + services.
- Build: POM unreadable — `'dependencies.dependency.version' for
  org.springframework:spring-file-io:jar is missing` (B2b). No JAR. Oracle: B1 (plus genuine
  GnuCOBOL syntax rejection at line 74 even with `-free`: `unexpected RECORDS...STATUS` —
  fixture defect F3).

### workload-relative-file — TRANSFORMED ONLY
- Same POM failure. Oracle B1 in pipeline (parse printed `DEBUG _parse_read: Found END-READ`
  then generated unbuildable project). No comparison.

### workload-rewrite — TRANSFORMED ONLY
- Same POM failure. Oracle B1. No comparison.

### workload-delete — TRANSFORMED ONLY
- Same POM failure. Oracle B1. No comparison.

### workload-start-invalidkey — TRANSFORMED ONLY
- Same POM failure (`INVALID KEY`/`START` modeled in discovery/file deps only).
  Oracle B1. No comparison.

## 8. Actual COBOL Data vs Generated Java Data

### 8a. Supplementary ground truth: GnuCOBOL with `-free` (non-certifying)
Command per workload:
`docker run --rm --network none -v <fixture>/cobol:/workspace/src:ro gnucobol-ocesql:latest
sh -c "cd /workspace/src && cobc -free -x *.cob -o /tmp/p && /tmp/p"`.
(`ORACLE_EXIT=True` below is pwsh `$?`; GnuCOBOL exit was 0 where output is shown.)

| Workload | COBOL input (essence) | COBOL output (`-free`) | Java output | Match |
|---|---|---|---|---|
| subtract | 100-25 GIVING; -10 in-place; 50-25; 200-A-B | 0075 / 0090 / 0025 / 0085 | (no build) | n/a |
| multiply | 10×5; ×4 in-place; 3×5; 40×5 | 50 / 40 / 15 / 200 | (no build) | n/a |
| evaluate | GRADE=85 | B + GOOD | (no build) | n/a |
| perform-varying | I 1..5 sum; J 1..4 prod | SUM=0015 PROD=0024 | (no build) | n/a |
| occurs | 10..50 ×5 | SUM=0150 | (no build) | n/a |
| redefines | 123456 / ABCDEF moves | PART1=123 PART2=456; A C/DEF split | (no build) | n/a |
| level88 | STATUS=ERROR, G=M, then SET OK/F | STATUS ERROR / MALE / 00 / F | (no build) | n/a |
| by-reference | CALL MODIFY BY REFERENCE 100 | AFTER CALL VALUE=0150 (mutation visible) | (no build) | n/a |
| by-value | CALL MODIFY BY VALUE 100 | AFTER CALL VALUE=0100; LOCAL COPY=6722 | (no build) | n/a |
| by-content | CALL ... BY CONTENT | `unexpected CONTENT` — GnuCOBOL 3.1 lacks it | (no build) | n/a |
| call-linkage | CALL CALCULATE USING A B RESULT | CALC-side uncompilable (LINKAGE order) | (no build) | n/a |
| dynamic-call | CALL WS-PROG-NAME | CALC-side uncompilable (LINKAGE order) | (no build) | n/a |
| copybook | COPY COMMON, CLAIM C-999/100 | 7 lines ending `FINAL CLAIM-AMOUNT=000100` | identical 7 lines, RC=0 (manual JAR rerun) | IDENTICAL (supplementary only) |
| comp | S9 COMP add/sub/mul/div | -0100/+123456789/0500; +400/+123456889/+1000/+123456 | (no transformation) | n/a |
| comp3 | S9V99 COMP-3 arithmetic | +12345.67/-00987.65/0100.00; +11358.02/+13333.32/+200.00/+123.45 | (no transformation) | n/a |
| indexed/relative/rewrite/delete/start | file I/O | not run manually (interactive/file fixtures; pipeline oracle compile-blocked) | (no build) | n/a |

### 8b. File-workload hash table
No file artifacts were produced on either side in-pipeline (oracle never compiled; Java never
built for the 5 file workloads). Table is therefore empty by evidence, not by omission:

| Workload | COBOL file | Java file | COBOL hash | Java hash | Records match |
|---|---|---|---|---|---|
| indexed-file | none produced | none produced | n/a | n/a | NO EVIDENCE |
| relative-file | none produced | none produced | n/a | n/a | NO EVIDENCE |
| rewrite | none produced | none produced | n/a | n/a | NO EVIDENCE |
| delete | none produced | none produced | n/a | n/a | NO EVIDENCE |
| start-invalidkey | none produced | none produced | n/a | n/a | NO EVIDENCE |

## 9. Generated Application Inventory

Per-workload generated file lists + SHA prefixes are stored in each
`forensic-20260921/workload-*.json` (`generated_java_files`, `spring_files`,
`generated_artifact_hash`). Summary:

- Single-program workloads (subtract/multiply/evaluate/perform-varying/occurs/redefines/
  level88/indexed-file/relative-file/rewrite/delete/start-invalidkey/copybook):
  1 COBOL program → 1 program service class + (copybook: +1 `*Record` model) + Spring files
  (`Application.java`, `AppConfig.java`, service, adapter/repository where applicable,
  `application.properties`, `pom.xml`). Spring entrypoint FQN for all:
  `com.generated.app.Application`. `pom_exists=true`, `app_java_exists=true` for all 18.
- Multi-program (call-linkage/by-reference/by-content/by-value/dynamic-call):
  2 COBOL programs → 3 Java artifacts (2 program classes + `ServiceRegistry.java`) + Spring app.
- 3-program synthetic check (`disco_check.py`, fresh `tempfile` dirs):
  ALPHA/BETA/GAMMA → `Alpha.java, Beta.java, Gamma.java, ServiceRegistry.java`,
  entrypoint `Alpha` (deterministic first-program fallback), `program_ids=(ALPHA,BETA,GAMMA)`.
- Paragraph-less synthetic check: NOPARA → `Nopara.java`, success.
- Only JAR produced in campaign: `generated_apps/workload-copybook/target/
  workload-copybook-app-0.0.1-SNAPSHOT.jar` (10,344,132 B).
- No `target/` artifacts for the other 17 (Maven never reached `package`).

## 10. Failed / Partial Capabilities

- **B1. Oracle adapter missing `-free`** (`engine/oracle/docker_adapter.py:263-268`,
  `compile_cmd = f"cobc -x ..."`). Stage: oracle execution. Exact error (all 20):
  `MAIN.cob:1: error: invalid indicator 'F' at column 7` (+ per-file variants). Root cause proven:
  same sources compile+run with `cobc -free` (Sec 8a). Harness/product-lane issue (fixtures are
  uniformly free-format; adapter assumes fixed). Blocks LEVEL 6/7 for everything.
- **B2a. Statement-folding codegen bug** (`cobol_to_java_mapping.py` + dirty-tree changes):
  SUBTRACT/MULTIPL
...[truncated 6154 chars]