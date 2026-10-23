# SystemaOps Complete Read-Only Audit

**Audit date:** 2026-10-23  
**Repository:** https://github.com/Shankar373/Cobol-Java-Transformation  
**Branch audited:** `main`  
**Commit/tree SHA:** `a923c65102d0a1e069db0abad232b09a826a0c3c`  
**Method:** GitHub remote-source inspection. No existing project files were modified, deleted, renamed, or upgraded. The only intended repository mutation is creation of this audit report; no commit/push/reset/clean was performed by this audit.

> **Status: PARTIAL / BLOCKED.** Repository tree metadata and selected critical files were inspected. This GitHub-only session cannot execute code/tests or inspect the local working tree, and did not read all 809 file bodies line-by-line. The report does not claim exhaustive audit completion.

## 1. Executive summary

### Actual project goal

The README describes this repository as an **independent COBOL modernization validation and business-equivalence platform**, not the COBOL-to-Java converter itself. It is intended to execute original COBOL and candidate Java in controlled environments, capture declared artifacts, compare them against contracts, validate evidence and derive reproducible verdicts. See `README.md:92-138`, especially `112-116`.

The README's opening status banner (`README.md:5-30`) is stale: it says Phase 1C is complete and that no production implementation exists, while the actual tree contains hundreds of Python, Java, COBOL, JCL, test, UI and runtime-verification files.

### Verdict

**Prototype / partial verification platform; not universally capable and not production-ready for general COBOL/mainframe modernization.** Significant deterministic components exist: COBOL parser and IR, Java mapping/generation, application/copybook discovery, limited JCL/CICS/SQL lanes, Docker-backed Java/GnuCOBOL adapters, artifact comparators, evidence validation, verdict derivation, API and frontend.

The repository's 2026-09-21 capability report states that its 20-workload campaign achieved **0/20 ORACLE_MATCHED and 0/20 FRESH_VERIFIED**. Seventeen workloads were stopped before successful build, and two failed parsing. Those are historical committed results, not a new run executed during this audit. A separate Phase 7D report claims a narrow arithmetic proof and explicitly limits the result to one workload.

### Top-level findings

| Area | Assessment | Evidence |
|---|---|---|
| Deterministic architecture | IMPLEMENTED_NOT_RUNTIME_VERIFIED in this audit | `engine/transformation/cobol_parser.py`, `ir.py`, mapping/generator chain. |
| COBOL language coverage | PARTIALLY_IMPLEMENTED | Parser explicitly says it is not general-purpose (`cobol_parser.py:1-15`). |
| Java generation | PARTIALLY_IMPLEMENTED | Numeric mapping and historical compile failures; see §§6, 12. |
| GnuCOBOL oracle | BROKEN in reported campaign | `engine/oracle/docker_adapter.py:176-180` invokes `cobc -x` without `-free`; historical report documents fixture compile errors. |
| Runtime parity | BLOCKED / not generally proven | Historical 20-workload report: 0/20 matched/verified. |
| CICS | PROTOTYPE / modeled-only | Generator disclaims CICS TS equivalence and says runtime seams are not implemented by default. |
| JCL | PARTIALLY_IMPLEMENTED | Parser supports a restricted subset and says unsupported constructs can yield minimal IR without error. |
| DB2 | PARTIALLY_IMPLEMENTED / SQLite-only proof | SQL execution module explicitly states SQLite tests do not verify DB2 runtime behavior. |
| Evidence integrity | IMPLEMENTED_NOT_RUNTIME_VERIFIED in this audit | Evidence binding/hash implementation exists; fresh integrated path not executed here. |
| API/UI | Prototype | Source files exist; live deployment/security review not performed. |
| Production readiness | NOT READY | Integration failures, semantic scope gaps and missing current runtime proof. |

## 2. Repository baseline and inventory

### Repository facts

- Public repository: `Shankar373/Cobol-Java-Transformation`
- Default branch: `main`
- Audited commit/tree SHA: `a923c65102d0a1e069db0abad232b09a826a0c3c`
- GitHub API recursive tree: **1,253 entries = 809 blobs + 444 directories**, **5,214,160 bytes** total blob size.
- Extension counts: 247 Python (`.py`), 225 Java (`.java`), 74 COBOL (`.cob`), 5 copybooks (`.cpy`), 4 JCL (`.jcl`), 109 JSON, 56 Markdown, 21 XML, 20 TSX, 10 TypeScript, plus CSS/HTML/CSV/properties/text/config/build artifacts.
- The audited tree did not contain this report before creation.
- GitHub's remote API cannot reveal uncommitted, ignored or local-only files. Local working-tree state is UNKNOWN.

### Inventory summary

| Area | Approximate blob count | Observed scope |
|---|---:|---|
| `engine/` | 87 | Parser, IR, mappings/generators, CICS/JCL/SQL, adapters, evidence, comparator, verdict, orchestration. |
| `tests/` | 460 | Unit/integration/adversarial tests, fixtures and committed generated verification artifacts/results. |
| `fixtures/` | 163 | COBOL programs/copybooks, Java candidates/mutants, JCL, input and expected data, workload definitions. |
| `docs/` | 42 | Phase reports, specs, decisions and current capability verification. |
| `api/` | 6 | FastAPI app, service, storage, models, ingestion and name derivation. |
| `frontend/` | 35+ | React/TypeScript UI, tests, package manifests and build configuration. |
| Root/contracts/other | Remaining | README, contracts, Dockerfiles, phase reports, pytest config and metadata. |

The entire path/size/SHA inventory was retrieved from the tree. It is not reproduced as 809 separate rows here. **The body of every blob was not line-read.** Remaining blobs are METADATA_ONLY / NOT_READ—not “passed” or “safe.”

## 3. File-by-file inspection coverage

Coverage key: **INSPECTED_SELECTED** = full file content fetched, targeted sections inspected; not a claim that every line had semantic review. **METADATA_ONLY** = tree metadata only. **BLOCKED_RUNTIME** = not executed.

### Critical files fetched and line counts confirmed

| File | Lines | SHA prefix | Coverage and principal finding |
|---|---:|---|---|
| `engine/transformation/cobol_parser.py` | 1,708 | `2148651b` | INSPECTED_SELECTED — explicitly limited-subset parser. |
| `engine/transformation/ir.py` | 1,859 | `bc1abead` | INSPECTED_SELECTED — extensive IR but completeness is limited by parser/consumers. |
| `engine/transformation/cobol_to_java_mapping.py` | 805 | `1e1bee2c` | INSPECTED_SELECTED — numeric type mapping can be lossy. |
| `engine/transformation/java_generator.py` | 1,638 | `9b3a933b` | INSPECTED_SELECTED — mode-driven generation; emitted output does not guarantee build success. |
| `engine/pipeline.py` | 714 | `1f70f99c` | INSPECTED_SELECTED — Oracle/candidate/comparison/evidence/verdict pipeline is present in code. |
| `engine/modernization/pipeline.py` | 398 | `b2d62b1f` | INSPECTED_SELECTED — discovery, capability, plan, transform, assembly. |
| `engine/modernization/capability_analyzer.py` | 357 | `0e2dfca7` | INSPECTED_SELECTED — supported/partial/unsupported/unavailable classifications. |
| `engine/oracle/docker_adapter.py` | 260 | `dafbb1cc` | INSPECTED_SELECTED — oracle compiler invocation issue at lines 176-180. |
| `engine/candidate/docker_java_adapter.py` | 599 | `446b0dd3` | INSPECTED_SELECTED — Docker build/execute adapter and timeout/resource controls. |
| `engine/candidate/docker_spring_boot_adapter.py` | 566 | `d3804bab` | INSPECTED_SELECTED — Maven offline build and containerized JAR execution; line 283 skips Maven tests. |
| `engine/comparators/framework.py` | 511 | `cfe40b4e` | INSPECTED_SELECTED — finite comparator registry (stdout, stderr, exit status, text file, fixed record). |
| `engine/evidence/integrity.py` | 555 | `039b4596` | INSPECTED_SELECTED — binding/hash validation, not business correctness itself. |
| `engine/verdict/derivation.py` | 237 | `7d3f7d7b` | INSPECTED_SELECTED — deterministic verdict; V1 excludes INDEXED/RELATIVE/SQL/DATABASE according to module policy. |
| `engine/transformation/cics_parser.py` | 706 | `4f2efbf6` | INSPECTED_SELECTED — CICS command/resource extraction exists. |
| `engine/cics/generator.py` | 739 | `98200ca7` | INSPECTED_SELECTED — unsupported CICS constructs stay explicit; no CICS TS equivalence claim. |
| `engine/transformation/jcl_parser.py` | 510 | `4d679079` | INSPECTED_SELECTED — limited JCL grammar; unsupported statements can produce minimal IR. |
| `engine/jcl/builder.py` | 477 | `8787f568` | INSPECTED_SELECTED — raw-source unsupported-construct diagnostics when raw source is supplied. |
| `engine/sql/execution.py` | 453 | `45dd7a5c` | INSPECTED_SELECTED — controlled SQLite DB2 subset, not real DB2 runtime. |
| `api/app.py` | 458 | `ff7675e8` | INSPECTED_SELECTED — application/run/upload/ingest/modernize/artifact/verdict/download/health routes. |
| `api/service.py` | 703 | `8a125c8d` | INSPECTED_SELECTED — daemon-thread background modernize/revalidate. |
| `api/ingestion.py` | 239 | `2b3d2a1e` | INSPECTED_SELECTED — ZIP size/count/path-traversal/symlink safeguards. |
| `api/store.py` | 391 | `06de48bc` | INSPECTED_SELECTED — SQLite MVP; module docstring says no PostgreSQL/Redis/distributed queue. |
| `tests/verification/run_clean_verification.py` | 769 | `ddc30e2d` | INSPECTED_SELECTED — runtime harness code present; not run in this audit. |
| `tests/verification/run_fresh_baseline.py` | 494 | `56e3ccdc` | INSPECTED_SELECTED — 20-workload staged differential verification harness; not run here. |
| `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` | 362 | `7f18760a` | INSPECTED_SELECTED — historical 2026-09-21 forensic report. |
| `tests/verification/results_fresh2/verification_summary.json` | 363 | `618b3182` | INSPECTED_SELECTED — records 20 workload outcomes: 17 compile errors, two parse failures, one successful build. |
| `tests/verification/results_fresh2/FINAL_REPORT.md` | 116 | `dd608232` | INSPECTED_SELECTED — historical report states zero matched/verified. |
| `tests/verification/results_fresh/summary.csv` | 3 | `9c814b9c` | INSPECTED_SELECTED — one specific copybook-file-multi row claims FRESH_VERIFIED. |
| `PHASE7D_COMPLETION_REPORT.md` | 213 | `5ad949a3` | INSPECTED_SELECTED — bounded one-workload arithmetic result, qualified in report body. |
| `README.md` | 2,816 | `9271b065` | SELECTED_SECTIONS only — entire 131 KB file not line-reviewed; opening status is stale. |
| `frontend/package.json` | 31 | `81414272` | INSPECTED_SELECTED — package scripts/dependencies exist; no frontend commands run. |
| `pytest.ini` | 35 | `25af1b85` | INSPECTED_SELECTED — test discovery/markers/timeouts. |
| Dockerfiles, rest of engine/tests/contracts/docs/fixtures/Java/UI/configs | Varies | Tree metadata | METADATA_ONLY or partial; not fully reviewed line-by-line. |

The requirement to read every relevant file line by line is **NOT COMPLETE**. Selected inspections reveal actionable findings, but this report cannot honestly certify full-repository coverage.

## 4. Architecture and execution flow

### Observed source-level flow

```text
React/TypeScript frontend
        │ API requests
        ▼
FastAPI control plane (api/app.py)
        ▼
Service and SQLite-backed state (api/service.py, api/store.py)
        ▼
ZIP ingestion / application discovery
        ▼
Capability analysis + transformation plan
        ▼
COBOL parser → COBOL IR → semantic mapping → Java IR
        ▼
Plain Java generator and/or Spring Boot mapper/generator
        ▼
Generated candidate source/project
        ▼
Validation pipeline (engine/pipeline.py)
  ├── GnuCOBOL Docker oracle
  ├── Docker Java / Spring Boot candidate
  ├── declared artifact capture
  ├── typed comparator registry
  ├── evidence manifest and integrity validation
  └── deterministic verdict derivation
```

Sources: `engine/modernization/pipeline.py:1-20`, `engine/pipeline.py:1-18`, `api/app.py:1-26`, `engine/evidence/integrity.py:1-18`, `engine/verdict/derivation.py:1-5`. The diagram is inferred from source/docstrings, not traced via a live runtime.

Important conceptual split: transformation and validation are separate responsibilities. Generated Java, successful compilation, generated artifacts or a green unit test do not alone demonstrate business equivalence.

## 5. Runtime evidence and report reconciliation

### Historical 20-workload campaign

The committed `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` is dated 2026-09-21. At lines 79 and 104-113 it reports:
- **0/20 ORACLE_MATCHED; 0/20 FRESH_VERIFIED**;
- 17 transformed workloads stopped at build failures;
- one copybook workload built/attempted execution but did not reach oracle-matched;
- two parser failures: `workload-comp` and `workload-comp3`;
- 12 Java compilation failures and five file-workload POM failures in its detailed diagnosis;
- oracle compiler invocation used `cobc -x` without `-free`, causing source-format errors for the free-format fixtures.

The machine-readable `tests/verification/results_fresh2/verification_summary.json` records timestamp 2026-09-21T08:15:41Z and total_workloads 20: 17 `COMPILATION_ERROR`, two parse failures, one successful build (`workload-copybook)); the retrieved outcomes show verdict `UNAVAILABLE`. These are historical results, not a new runtime run today.

The small `tests/verification/results_fresh/summary.csv` contains one `workload-copybook-file-multi` row claiming FRESH_VERIFIED with four MATCH comparisons, zero vacuous matches and zero integrity violations. It is a single workload result and cannot be generalized.

### Phase 7D report

`PHASE7D_COMPLETION_REPORT.md:142-152` claims a 30-test run including three behavioral-equivalence assertions; lines 182-184 qualify this as **only the arithmetic workload tested at runtime**, note normalization of zero-padded COBOL output (e.g. `SUM=0015`) against Java (`SUM=15`), and state that multi-program CALL chains were untested at runtime. This supports at most a narrow historical demonstration, not universal equivalence.

### What this audit executed

Nothing. Pytest, Maven, javac/java, Docker, GnuCOBOL, API runtime and frontend build/E2E are **BLOCKED_NOT_RUN** in this GitHub-only session. Current runtime success is UNKNOWN; newest inspected committed 20-workload report states 0/20 matched/verified. Local dirty/staged/untracked files are UNKNOWN.

## 6. COBOL-to-Java capability matrix

| Capability | Classification | Evidence / caveat |
|---|---|---|
| Program ID/basic divisions | PARTIALLY_IMPLEMENTED | `cobol_parser.py:240-246` extracts PROGRAM-ID; not a compiler-grade frontend. |
| PIC X/basic PIC 9, MOVE, ADD, DIVIDE, IF/ELSE, PERFORM, STRING/UNSTRING, DISPLAY, STOP RUN | PARTIALLY_IMPLEMENTED | Parser docstring `cobol_parser.py:1-15` lists a demonstrated subset. |
| Structured expressions, conditions and statement IR | IMPLEMENTED_NOT_RUNTIME_VERIFIED | Typed nodes in `ir.py`; accepted grammar is narrower than COBOL semantics. |
| COMPUTE/arithmetic edge cases | PARTIALLY_IMPLEMENTED | Arithmetic IR/mapping exists; rounding, truncation, overflow and size-error behavior need proof. |
| Signed numeric `PIC S9(...)` / COMP | UNSUPPORTED in recorded run | `tests/verification/results/verification_summary.json` records `Unsupported PIC clause: S9(4)`. |
| COMP-3 / packed decimal | UNSUPPORTED in recorded run | Same result records `Unsupported PIC clause: S9(5)V99`. |
| Decimal precision/scale/rounding | PARTIALLY_IMPLEMENTED, unsafe to certify | `cobol_to_java_mapping.py:91-113` documents mapping decimal PIC to Java double; floating point is not generic fixed-point COBOL equivalence. |
| OCCURS | PARTIALLY_IMPLEMENTED | IR/fixtures exist; ODO, multidimensional, indexing, bounds and INITIALIZE semantics need proof. |
| REDEFINES | PARTIALLY_IMPLEMENTED | Fixture/generated sample exists; Java object/string structures do not prove byte-overlay layout. |
| Level-88 condition names | PARTIALLY_IMPLEMENTED | IR node exists; legal values, negation and storage semantics need tests. |
| COPY/COPYBOOK | PARTIALLY_IMPLEMENTED | Resolver/model exist; one historical file-multi result is recorded as verified, but broader campaign did not match. |
| Sequential file I/O | PARTIALLY_IMPLEMENTED | File support exists; encoding, record framing, EOF/status behavior need parity tests. |
| Indexed/relative I/O, START, REWRITE, DELETE | PARTIALLY_IMPLEMENTED; reported integration BROKEN | Historical POM failures for `spring-file-io` without version; VSAM/KSDS parity unproven. |
| Static CALL USING/linkage | PARTIALLY_IMPLEMENTED | Graph/registry and fixtures exist; campaign reports Java compilation failures and mismatched signatures/types. |
| Dynamic/recursive CALL | UNKNOWN / PARTIAL | Fixtures exist, but production E2E behavioral proof not established. |
| GO TO / complex PERFORM variants / compiler-specific syntax | UNSUPPORTED or UNKNOWN by construct | Capability analyzer marks some unsupported variants; no universal grammar. |
| SORT/MERGE, declaratives, broad dialects and other advanced grammar | UNKNOWN/UNSUPPORTED until proven | No comprehensive compiler-grade grammar and corpus verified. |
| Free/fixed source format and continuations | BROKEN in recorded oracle campaign | `engine/oracle/docker_adapter.py:176-180` lacks `-free`; capability report lines 108-110, 355-359 attributes widespread oracle compile failure to this. |
| Universal COBOL modernization | UNSUPPORTED | Limited grammar plus integration/runtime failures; no support for a universal claim. |

## 7. Mainframe dependency matrix

| Dependency | Classification | Evidence / gap |
|---|---|---|
| z/OS compiler/runtime | UNSUPPORTED / NOT VERIFIED | V1 adapter is GnuCOBOL Docker. README `841-867` explicitly marks z/OS as future, not V1 authority. |
| JCL parsing/modeling | PARTIALLY_IMPLEMENTED | `jcl_parser.py:1-18` enumerates JOB/EXEC/DD/inline data/comments/COND/SET subset and warns unsupported input can yield minimal IR. |
| Cataloged PROC, INCLUDE/JCLLIB, continuation, JES condition/disposition/restart semantics | PARTIAL/UNSUPPORTED | `engine/jcl/builder.py:396-477` has some unsupported diagnostics; no JES runtime equivalence evidence. |
| CICS command extraction/model | PARTIALLY_IMPLEMENTED | `cics_parser.py` extracts command/resource references. |
| CICS TS RESP, COMMAREA copy, isolation, pseudo-conversation, terminal I/O | PROTOTYPE / UNSUPPORTED | `engine/cics/generator.py:1-30` expressly disclaims runtime equivalence and says runtime seams are not implemented by default. |
| IMS / DL/I | UNKNOWN / UNSUPPORTED until proven | No IMS runtime adapter or equivalence campaign found in selected evidence. |
| DB2 SQL parsing/repository mapping | PARTIALLY_IMPLEMENTED | SQL parser/analyzer/execution modules and DB2 fixture exist. |
| Real DB2 runtime/packages/locking/isolation/transaction behavior | UNSUPPORTED / NOT VERIFIED | `engine/sql/execution.py:1-13` states SQLite harness does not verify DB2 runtime. |
| VSAM KSDS/ESDS/RRDS | PARTIAL / NOT MAINFRAME-VERIFIED | File abstractions exist; no actual VSAM runtime/logical-extraction proof. |
| Copybooks | PARTIALLY_IMPLEMENTED | Resolver/model exist; nested COPY, REPLACING, library precedence, cycles and compiler preprocessing need exhaustive tests. |
| EBCDIC/CCSID/collating sequence | UNKNOWN / BLOCKED | No target-codepage proof observed; UTF-8/text behavior is not EBCDIC proof. |
| COMP/COMP-3 binary/packed layout | UNSUPPORTED in recorded parser campaign | Parser error evidence in §6; requires exact sign/scale/overflow/invalid-data validation. |
| External/dynamic program dependencies | PARTIAL/UNKNOWN | Call graph exists; target ABI and runtime resolution not proven. |
| Batch scheduler, feeds, GDGs, restart/checkpoint | MODELED_ONLY / UNKNOWN | Dataset-flow model exists; no real scheduler runtime proof. |

## 8. Business-equivalence assessment

**Business equivalence is not established generally.** A valid claim should bind exact input, source/candidate hashes, oracle and target runtime identities, declared output contracts, comparator versions, run identity, and fresh evidence.

Primary risks:
1. **Decimal fidelity:** `map_pic_to_java_type()` at `cobol_to_java_mapping.py:91-113` documents a decimal PIC → `double` rule. This risks divergence in scale, rounding, truncation, signed display, overflow and SIZE ERROR behavior.
2. **Data layout:** REDEFINES, group items, COMP and COMP-3 require storage-layout semantics; flattened strings/classes alone do not prove byte layout.
3. **Formatting/encoding:** Phase 7D normalizes COBOL numeric zero padding against Java output. Normalization must be contract-approved and must not hide defects.
4. **I/O behavior:** record framing/length, EOF, invalid key, alternate key order, START positioning, REWRITE/DELETE, status codes, CCSID and sort order require oracle comparison.
5. **CALL ABI/linkage:** BY REFERENCE/CONTENT/VALUE, parameter mutability, linkage layout, argument count/type, dynamic target and abnormal exits need multi-program runtime proof.
6. **SQL/transactions:** SQLite subset cannot prove DB2 SQLCODE/SQLSTATE edge cases, decimal coercion, cursor lifetime, lock/isolation, rollback or package behavior.
7. **Control flow/error paths:** ON SIZE ERROR, INVALID KEY, AT END, STOP RUN status, ABEND and transaction commit semantics must be compared.
8. **Comparator limits:** `engine/comparators/framework.py:1-12` explicitly restricts registered types. Contracts and semantic extractors must be complete before a MATCH is meaningful.

Verdicts:
- General COBOL→Java equivalence: **UNKNOWN / NOT PROVEN**.
- Historical arithmetic example: **PROTOTYPE / narrow workload proof only**.
- Historical copybook-file-multi result: **one recorded FRESH_VERIFIED workload only**.
- Historical 20-workload pipeline: **0/20 matched/verified**.
- Certification for arbitrary customer/mainframe applications: **UNSUPPORTED**.

## 9. Test-quality assessment

Observed categories include unit tests, integration tests, adversarial evidence/mutation tests, COBOL/JCL fixtures, Java candidates/mutants, generated projects and differential verification scripts. The code correctly distinguishes some evidence stages, and the verification harness explicitly checks vacuous matches. Those safeguards must be tested through the production path with a real oracle.

Do not conflate:
- parse success with semantic completeness;
- IR creation with correct Java mapping;
- source generation with compilation;
- compilation with execution;
- execution with business equivalence;
- valid hashes with semantic correctness;
- stub/mock tests with Docker/target runtime tests;
- empty-vs-empty MATCH with meaningful behavior.

**No test results are new results from this audit.** Historical report claims remain historical and are not presented as current executions.

## 10. Security, operations and production readiness

### Positive implementation signals

- Docker Java adapter describes container-per-execution, `--network none`, read-only source staging, CPU/memory/PID limits, timeout and cleanup (`engine/candidate/docker_java_adapter.py:1-12, 320-345, 487-520`).
- Spring Boot adapter checks configured image digests and builds offline in Docker (`docker_spring_boot_adapter.py:50-91, 283-292`).
- Oracle adapter hashes source before/after and captures exit/stdout/stderr (`engine/oracle/docker_adapter.py:78-88, 96-119, 223-239`).
- ZIP ingestion has stated archive byte/entry/extracted-size/path-traversal/symlink protections (`api/ingestion.py:25-27, 72-136`).

### Production gaps / caution

1. Current image presence/digests and actual sandbox enforcement were not runtime-checked in this audit.
2. Sandbox flags do not repair the historical oracle source-format issue.
3. `docker_spring_boot_adapter.py:283` runs `mvn -o -B -Dmaven.test.skip=true package`; candidate Maven tests are skipped and must be run independently.
4. Authentication/authorization, rate limiting, tenant isolation and secure artifact download were not fully reviewed/tested. Mark UNKNOWN until proven.
5. `api/service.py:230-232, 333-335` launches daemon threads; work can be interrupted by process exit. This is not a durable queue for long-running enterprise jobs.
6. `api/store.py:1-18` states SQLite MVP with no PostgreSQL/Redis/distributed queue. Concurrency, durability, backups, retention and migrations require hardening.
7. Secrets, PII/data retention, deployment threat model, logs and audit retention remain incompletely assessed.
8. Verify every execution/build path has resource caps, bounded temp/output mounts, cleanup and correct host isolation.
9. Generated Java dependency lock/SBOM, vulnerability/license checks and reproducible supply chain were not verified.
10. No live API/browser deployment, load, authz, recovery or release-gate validation took place.

**Production readiness: NOT READY.** Useful security primitives are present but not sufficient for a production certification.

## 11. Documentation discrepancies

| Source | Discrepancy | Recommended action |
|---|---|---|
| `README.md:5-30` | Claims no implementation/parser/tests/runtime/UI exists, contradicted by actual tree. | After owner approval, replace stale banner with actual commit, scope, tested status and limitations. |
| README vs current files | Architecture-only Phase 1C status coexists with hundreds of implementation/test/artifact files. | Separate historical design record from implementation/capability status. |
| `PHASE7D_COMPLETION_REPORT.md:9-10, 142-152, 182-184` | Headline says verified, but scope is one arithmetic workload and output normalization. | State narrow workload scope and comparator normalizations at top. |
| `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md:79, 104-113` | Reports 0/20 matched/verified and extensive build/parser failures. | Treat as the baseline for that run until fresh, reproducible evidence replaces it. |
| `tests/verification/results_fresh/summary.csv` | Only one FRESH_VERIFIED row. | Label as a single-workload artifact, not full-suite proof. |
| `tests/verification/results_fresh2/FINAL_REPORT.md` + JSON | Historical 20-workload campaign has 17 compile errors and two parser failures; timestamp predates audited commit by about one month. | Rerun on a clean environment against exact source SHA after blockers are resolved. |
| Phase reports and artifacts generally | “Fresh” means fresh for their historic campaign, not fresh for current audited commit. | Bind each report to source SHA, run ID, toolchain, image digests, exact command and raw logs. |

## 12. Critical blockers

### P0 — trust in any equivalence verdict

1. **Oracle source-format mismatch:** `engine/oracle/docker_adapter.py:176-180` invokes `cobc -x` without `-free`. The historical capability report at lines 108-110 and 355-359 documents free-format fixture compiler errors. Define source format/dialect per input and test fixed/free/continuation variants.
2. **Generated Java compile failures:** the historical 20-workload campaign has 17 build errors, including invalid identifiers/types/arity/method calls. Fix mapping/IR/generator root causes, not only generated snapshots.
3. **Missing Spring file dependency version:** five file-oriented workloads recorded invalid POMs because `spring-file-io` had no version. Use a pinned/managed dependency or eliminate it.
4. **Fail-closed parsing:** unsupported executable source must never be silently dropped. Every clause should be parsed or explicitly reported UNSUPPORTED with source location/raw text; this applies to JCL as well.
5. **Fresh parity evidence:** historical campaign had 0/20 matches. Compilation, seeded expected results or valid hashes must not imply parity.

### P1 — semantic fidelity

6. Replace decimal-to-double shortcuts with defined COBOL fixed-point, sign, scale, COMP/COMP-3, rounding, truncation and overflow semantics.
7. Prove file/VSAM semantics: framing, key order, alternate keys, START, REWRITE/DELETE, status, encoding.
8. Prove CALL/linkage behavior including by-reference/content/value, dynamic calls and multi-program effects.
9. Add robust grammar/expression tests and explicit unsupported paths.
10. Bind contract-specific normalization and reject missing artifacts, failed oracle execution and vacuous matches.
11. Execute evidence/adversarial mutations through the real production comparator/verdict path.

### P2 — mainframe and production readiness

12. Validate against DB2 or restrict support claims to SQLite-modeled subset.
13. Implement and validate CICS runtime seams or retain PROTOTYPE/UNSUPPORTED classification.
14. Complete JCL parsing and test JES/scheduler/run-control semantics or reject them explicitly.
15. Implement EBCDIC CCSID/collation and exact copybook/storage layout semantics.
16. Complete authn/authz, tenant separation, uploads/downloads, secrets and rate limiting.
17. Replace fragile daemon-worker lifetime with durable jobs, cancellation, recovery and observability.
18. Establish reproducible CI with pinned toolchains/images, tests, security scans, SBOM and immutable evidence archive.

## 13. File-by-file upgrade backlog

This is a plan only; no fixes were applied.

| Order | Files | Priority | Upgrade | Tests / acceptance criteria |
|---:|---|---|---|---|
| 1 | `engine/oracle/docker_adapter.py` | P0 | Correct source-format selection and record exact compiler options. | Docker tests compile/run fixed- and free-format fixtures; preserve intentional compile failures; evidence records compiler/dialect/flags/hash. |
| 2 | `fixtures/**`, workload declarations | P0 | Audit source format/dialect for every fixture and separate invalid fixtures from product bugs. | Direct compile all declared fixtures; each either compiles under declared dialect or is an explicit negative case. |
| 3 | `engine/transformation/cobol_parser.py` | P0/P1 | Parse source format/continuations and improve grammar/diagnostics; support COMP/COMP-3 only with complete semantics. | Valid/invalid grammar corpus, fuzzing, source-to-IR completeness. No relevant clause silently dropped. |
| 4 | `engine/transformation/ir.py` | P1 | Preserve source format, storage usage, scale/sign/rounding, file errors and unresolved dependencies. | IR invariants/round-trips; unsupported cases block generation. |
| 5 | `engine/transformation/cobol_to_java_mapping.py` | P0/P1 | Fix arithmetic folding, PIC mapping, CALL/linkage, control-flow/status semantics. | Red-first regressions for each build failure; decimal boundary values compared with oracle. |
| 6 | `engine/transformation/java_generator.py` | P0/P1 | Fix keyword escaping, types/arity/method calls and statement composition. | Compile all accepted fixtures from clean output; unsupported semantics block rather than emit misleading code. |
| 7 | `java_ir.py`, `spring_boot_ir.py`, `java_to_spring_mapping.py`, `spring_boot_generator.py` | P0 | Fix package/method/dependency declarations; resolve `spring-file-io` version issue. | Offline Maven package all supported generated workloads in digest-pinned container; clean target directory; reproducible result. |
| 8 | `copybook_model.py`, `copybook_resolver.py`, `application_discovery.py` | P1 | Verify nested/cyclic COPY, REPLACING, library precedence, duplicates/layout. | Positive/negative resolver corpus; layout compared with compiler evidence; deterministic resolution and explicit ambiguity errors. |
| 9 | `file_io_support_template.py`, file adapters, `tests/transformation/test_file_semantics.py` | P1 | Match sequential/indexed/relative behavior and status codes. | Differential EOF, duplicate/alternate keys, START, invalid key, REWRITE/DELETE, ordering, record length and encoding tests. |
| 10 | `cics_parser.py`, `engine/cics/model.py`, `mapper.py`, `generator.py` | P2 | Keep CICS modeled-only until runtime semantics exist; then implement selected RESP/COMMAREA/transaction semantics. | CICS-compatible target/simulator with explicit contract; test LINK/XCTL, rollback, ABEND and terminal behavior. |
| 11 | `jcl_parser.py`, `engine/jcl/builder.py`, `jcl_to_spring_batch.py` | P2 | Carry raw-source diagnostics through pipeline; implement or reject PROC/INCLUDE/continuation/COND/DISP/restart. | JCL corpus plus JES/approved-runtime proof for step order, datasets, condition codes and restartability. |
| 12 | `db2_sqlite.py`, `sql/execution.py`, `sql_repository_mapping.py` | P1/P2 | Keep SQLite strictly test-only; define DB2 runtime lane/limitations. | Run same SQL/schema/data on DB2 target, including SQLCODE, decimal, cursor, locking/isolation and rollback. |
| 13 | Oracle/candidate Docker adapters | P0/P2 | Verify isolation flags on every path; add durable command/environment evidence. | Runtime network/filesystem/resource/timeout/cleanup tests; digest mismatch is UNAVAILABLE, never host fallback. |
| 14 | `engine/comparators/framework.py` and artifact contracts/extractors | P0/P1 | Tighten oracle-success gates, missing-artifact and vacuity logic; validate normalization. | Production-path tests for failed oracle, empty outputs, missing files, changed order/content/encoding/status and stale artifacts. |
| 15 | `engine/evidence/integrity.py`, `evidence/models.py`, `verdict/derivation.py` | P0 | Bind run/source/candidate/oracle/image/artifact/comparator identities completely. | Adversarial mutations against real pipeline; any identity/evidence mismatch prevents VERIFIED. |
| 16 | Verification scripts and CI workflows | P0 | Run campaigns on exact tested commit and record all raw results. | Clean repeated full run; 0 unexplained skips; report records source SHA/toolchain/image digest and per-stage failures. |
| 17 | `api/ingestion.py`, `api/app.py`, `api/service.py`, `api/store.py` | P2 | Security and durability review; replace daemon-only job execution with persisted queue/workers. | Authz/tenant, malicious ZIP, concurrency, cancel/restart/retry, retention and recovery tests. |
| 18 | `frontend/**` | P2 | Display engine-owned verdict only; clearly show unsupported/unavailable/incomplete status. | TypeScript, frontend tests/build, API E2E, accessibility and verdict-state tests. |
| 19 | `README.md`, docs/reports/results | P1/P2 | Reconcile stale status and label historic evidence with commit/run/toolchain. | Link/status checks and report-to-manifest SHA verification; no global claim based on a single workload. |
| 20 | All code/config/dependencies | P2 | Complete supply-chain and deployment readiness review after product lane is green. | SAST, dependency/license/SBOM, clean deterministic builds and release security checklist. |

## 14. Required regression and acceptance programme

1. **Oracle first:** run original COBOL fixtures using declared fixed/free format; capture compiler exit/status, stdout/stderr, output files, source hash and compiler identity. A failed compile can never count as oracle execution.
2. **Construct-by-construct testing:** multiple valid, boundary and invalid inputs per accepted COBOL feature; error paths must be compared.
3. **Numeric conformance:** DISPLAY vs COMP vs COMP-3; positive/negative/zero, scale/sign, ROUNDED/truncation, overflow/ON SIZE ERROR and invalid packed data.
4. **I/O conformance:** record framing/length, line endings, encoding/CCSID, EOF, INVALID KEY, duplicates/alternate keys, START, READ NEXT, REWRITE/DELETE, file status and ordering.
5. **CALL and application behavior:** BY REFERENCE/CONTENT/VALUE, linkage output mutations, dynamic/recursive calls, unresolved dependencies and argument mismatches.
6. **JCL/CICS/DB2:** define explicit supported scope and real runtime evidence or keep the capability MODELED_ONLY/UNSUPPORTED.
7. **Evidence attacks:** missing/stale oracle artifacts, wrong hashes, swapped source/candidate, fake runtime identity, empty-vs-empty records, missing artifacts, tampered manifest and unsafe normalization.
8. **Clean end-to-end matrix:** generate from scratch → build in pinned offline image → execute target → execute COBOL oracle → compare every declared artifact → validate evidence → derive verdict. Repeat for deterministic results.
9. **Production controls:** network/filesystem isolation, resource/timeouts/cleanup, ZIP-bomb/path traversal, authz/tenant boundaries, cancellation/recovery and load.

A workload may be VERIFIED only when both programs actually execute successfully in identified runtimes; all required artifacts are fresh and contract-bound; comparators and approved normalization match; no source or artifact is silently omitted; no vacuous match exists; integrity validation has zero violations; and mutation tests show the real production path rejects representative business defects.

## 15. Remaining unknowns and audit limitations

- Every-line review of all 809 blobs is incomplete.
- No pytest/Maven/Docker/compiler/API/browser commands ran in this audit.
- Local uncommitted/staged/untracked files and current local branch are invisible through the GitHub API.
- Historical verification artifacts are from 2026-09-21; no fresh full campaign was invoked.
- Authentication/authorization, tenant isolation, deployment secrets, current sandbox enforcement and runtime image provenance remain incompletely validated.
- No z/OS/JES, CICS TS, IMS or real DB2 runtime evidence was observed.
- No broad customer COBOL dialect corpus or compiler-conformance programme was proven.
- No LLM-based modernization logic is introduced by this audit or backlog; deterministic modernization and fail-closed capability reporting remain the required design.

## 16. Final verdict

**Overall: PARTIAL / BLOCKED AUDIT. Prototype maturity. Production NOT READY. Universal COBOL-to-Java modernization UNSUPPORTED.**

Substantial deterministic code and a promising evidence architecture exist. The critical concern is demonstrated end-to-end integration failure for the recorded campaign: a source-format problem in the production oracle command, generated Java/Maven build failures, limited COBOL semantics, and no mainframe target-runtime proof. A valid evidence hash is not equivalent to business correctness.

Do not approve general production deployment or broad business-equivalence certification until P0 blockers are fixed and proven in clean, digest-pinned CI, and every claimed capability has positive/negative runtime differential evidence.

### Sign-off

- [x] Repository/main commit identified.
- [x] Recursive tree metadata retrieved: 809 blobs / 444 directories.
- [x] Critical transformation, oracle, candidate, comparator, evidence, verdict, CICS/JCL/SQL, API and selected verification files fetched; line counts confirmed.
- [x] Key historical report/result discrepancies checked.
- [ ] Every relevant blob read fully, line by line — **BLOCKED / incomplete**.
- [ ] Clean runtime suite executed in this audit — **BLOCKED / not run**.
- [ ] Full mainframe runtime/security review — **BLOCKED / not run**.
- [ ] Production readiness — **FAIL**.

**This is an evidence-backed partial forensic audit, not a false claim that every repository line has been exhaustively reviewed.**
