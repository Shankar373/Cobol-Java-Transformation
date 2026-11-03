# Enterprise alignment audit and roadmap

**Baseline:** `main` @ `b0c1f6bb58be9b61fe0b7b94a59f945c55697ca9` (merge of PR #9; tree identical to the
candidate `967d313` certified 4 runtimes x 44/54 VERIFIED, independent re-check AGREE 44/44).
**Method:** four independent read-only audits of a clean checkout (JCL/batch/VSAM; CICS/MQ/IMS; DB2/SQL and
database targets; platform/API/frontend/security/CI) plus a measured import-reachability pass. Key claims were
spot-checked against the code; where a claim is an audit agent's reading and not a measurement, it is marked
*(reported)*. Nothing here changes implementation.

**Baseline evidence (all on the exact SHA `b0c1f6b`):** SystemaOps CI run 41674480967 - success (Docker/GnuCOBOL
oracle lane 5,203 passed / 0 skipped, hermetic 4,752, capability gate 1,297, lint, frontend); supply chain run
41674480813 - success; corpus certification run 41675939896 (manual dispatch, `headSha` verified) - success on
all four runtimes, 54 apps each: 44 VERIFIED, 9 refused, 1 UNAVAILABLE, independent AGREE 44/44.

## 1. Vision and where the product stands

**Vision:** a deterministic (no-LLM), evidence-based modernization platform for the whole legacy estate - COBOL,
JCL, CICS, DB2, VSAM, IMS, MQ, copybooks, data flows, integrations, batch and operational dependencies - producing
a hybrid Java architecture (keep tightly coupled workflows together, decompose suitable capabilities into
independently deployable services), with DB2/IMS coexistence *and* selective migration to PostgreSQL or other
pluggable database targets. Behavioural equivalence is proven by evidence and every unproven case fails closed.

**Today (measured):** a certified *COBOL-to-Java* subset on four runtimes in single-artifact form, with a
pilot-grade control plane. Everything else in the vision is detection, modelling or absent:

| Area | Status on `b0c1f6b` | Evidence |
|---|---|---|
| COBOL batch subset | **Certified** (4 runtimes, oracle-compared, independent re-check) | corpus 44/54, `docs/reports/PHASE5_FINAL_CERTIFICATION.md` |
| Sequential / indexed / relative files | **Proven, narrow**: emulated side files, two oracle tests on ~80-line fixtures; not VSAM | `tests/integration/test_indexed_relative_oracle_proof.py` |
| JCL | **Structural only**: parse, discovery, dependency edges, status; no Java from JCL; PROC/symbolics/IF-THEN-ELSE rejected | `engine/jcl`, `api/ingestion.py`, `integrated_proof.py` |
| DB2 / EXEC SQL | **Detected and blocked**. A SQLite-backed lane exists but is not wired to the product | registry `EXEC SQL`; `engine/sql/*` |
| CICS | **Detected and blocked**. A ~1.8k-line generator lane exists, unreachable and never compiled in tests | `engine/cics/*` |
| IMS / MQ | **Detected and blocked**; real call forms (`CALL 'CBLTDLI'`, `'MQOPEN'`) only get a generic INCONCLUSIVE marker | `pipeline.py:723-749` |
| VSAM / IDCAMS | IDCAMS classified UNSUPPORTED; no catalog, GDG, alternate indexes | registry |
| Hybrid / decomposed output | **Absent**: one `JavaApplication` becomes one jar | `runtime_adapters.py` |
| Database targets (PostgreSQL etc.) | **Absent**: no dialect layer | audit of `engine/sql` |
| Control plane | Pilot-grade: one shared token, no RBAC, in-process daemon-thread jobs, Docker socket mounted, no signing | `FULL_AUDIT_2026-11-03.md`, `docker-compose.production.yml` |

## 2. Findings by domain

### 2.1 Platform core
- The two "pipelines" are two stages, not duplicates: `engine/modernization/pipeline.py` (generation) and
  `engine/pipeline.py` (validation); `api/service.py` (2,032 lines, one class) glues them. The "single
  authoritative orchestrator" docstring is true for generation only.
- Real duplication: the candidate-adapter selection + `_run_validation` call exists twice in `api/service.py`
  (modernize and revalidate). `engine/pipeline.py:_run_legacy` is reachable only when `config.workload is None`,
  which the API never sets.
- Stale references: `api/service.py:7` and `api/models.py:315` cite `engine.pipeline.UniversalModernizationPipeline`
  (it lives in `engine.modernization.pipeline`).
- Runtime targets are listed in several places (`runtime_adapters.py`, `candidate/factory.py`, API models,
  frontend, certification script). `jakarta_ee` is accepted by the API but is not one of the four certified
  runtimes.
- Import-reachability from `api.app`/the pipelines (measured): nine modules are unreachable and used only by tests:
  `engine/modernization/application_assembler`, `engine/sql/{db2_sqlite,execution,harness,repository_model}`,
  `engine/transformation/{jcl_spring_boot_adapter,sql_repository_mapping}`, `engine/transformation/producers/*`.
  Seven carry an EXPERIMENTAL label pinned by `tests/test_experimental_modules.py`; `producers/opensource4j`,
  `sql/db2_sqlite`, `sql/execution` and `sql/harness` are not labelled *(reported)*.

### 2.2 JCL, batch, VSAM *(reported, spot-checked)*
- Works: file lowering for SEQUENTIAL/LINE SEQUENTIAL/RECORD SEQUENTIAL/INDEXED/RELATIVE with FILE STATUS; JCL
  parse -> discovery -> dependency edges -> PARTIAL status into the integrated-proof ledger.
- Gaps: no runnable job stream; steps do not invoke lowered programs; `JclApplication.procedures/symbols` are never
  populated; PROC/PEND/SET/IF-THEN-ELSE/INCLUDE rejected; no dataset catalog or GDG; **ASSIGN is certified only for a
  quoted literal**, so the normal mainframe form (`ASSIGN TO ddname` bound by a JCL DD) is absent; IDCAMS
  DEFINE/REPRO/DELETE absent; ALTERNATE RECORD KEY parsed but not lowered; missing FILE STATUS codes
  (21, 24, 41-49 ...); SELECT OPTIONAL rejected; keyed-file proof depth is two small oracle tests.
- `jcl_spring_boot_adapter` is an EXPERIMENTAL stub that only prints step names.

### 2.3 CICS, MQ, IMS *(reported, spot-checked)*
- Registry rows for `EXEC CICS`, `EXEC DLI`, `EXEC MQI` are UNSUPPORTED and plans block, which is honest.
- `EXEC MQI` is not IBM syntax; real MQ is `CALL 'MQCONN'/'MQOPEN'/'MQGET'/'MQPUT'` and real batch IMS is
  `CALL 'CBLTDLI'/'AIBTDLI'`. Detection and edge extraction therefore miss the real-world forms (only
  `pipeline.py` has a generic INCONCLUSIVE pattern). This is the largest real-world detection gap.
- The CICS lane (`engine/cics/*`, `cics_java_mapping.py`, `cics_parser.py`) is unreachable from the product,
  generates an interface seam (`CicsRuntime` with void methods) and is never compiled in tests; no BMS maps,
  EIB, RESP, pseudo-conversational state. `fixtures/workload-cics` declares comparators for a workload nothing
  can execute.
- Docs inconsistencies: `CAPABILITY_MATRIX.md:86` says no PCB/segment edges although the code produces them.
- **Equivalence strategy (decision):** GnuCOBOL cannot execute CICS/DL-I/MQ. The only deterministic route is one
  versioned in-repo **simulator per subsystem** that both sides link (a GnuCOBOL-callable shim on the oracle
  side, a Java library on the target side), run on an identical scripted input, comparing a canonical call/state
  trace plus final state. This proves equivalence *relative to the simulator specification*, never against IBM's
  runtime, and must be labelled `SIMULATOR_VERIFIED`, distinct from `IBM_VERIFIED`. IBM CICS/IMS images are
  entitlement-blocked (BL-132); MQ Developer is free (BL-131).

### 2.4 DB2 / SQL and database targets *(reported, spot-checked)*
- The product does not transform EXEC SQL; `cobol_parser` never produces `EmbeddedSqlBlock`. Wired: detection,
  and a table-dependency ledger (proof state BLOCKED).
- Not wired: `engine/sql/analyzer` (host-variable direction, indicators), `status` (only 4 SQLCODEs),
  `db2_sqlite` (SQLite test adapter; DECIMAL->NUMERIC and TIMESTAMP->TEXT, no exactness), the 1,187-line
  `sql_parser`, an EXPERIMENTAL repository model, and a JPA stub (`JpaRepository<Object, Long>`, SELECT only).
- Absent: `INCLUDE SQLCA`/DCLGEN, WHENEVER, SQLERRD, isolation/savepoints/locking codes, WITH HOLD and scrollable
  cursors, dynamic SQL, a **dialect abstraction for PostgreSQL or other targets**, a differential proof
  (the oracle image has no OCESQL or database), and data migration/reconciliation. The golden trace in
  `fixtures/workload-db2` is self-generated and proves nothing about the COBOL logic.

### 2.5 API, frontend, security, CI
- API: applications, upload/ingest, discovery, modernize, runs, artifacts, approval, validate, verdict, report,
  integrated-proof, download, health/ready. One shared bearer token; the approver is free text; no users, roles,
  tenants, pagination, delete/update, cancel or retry. Jobs are daemon threads and are marked FAILED on restart.
- Frontend: three pages, state-based navigation; sidebar placeholders non-functional; the discovery graph is only
  counts and lists. No portfolio view, dependency graph, per-construct coverage view or evidence browser, and no
  endpoint exposes `semantic_capability`.
- Open security items still accurate: no RBAC, Docker socket mounted into the API container (root-equivalent),
  no artifact signing, SQLite single node, token in `localStorage`, no per-token rate limit (nginx only), no
  retention/encryption at rest, no metrics.
- CI: capability gate, ruff (pyflakes + syntax only), hermetic, Docker/oracle (180 min cap), frontend, supply
  chain, certification (only on `[certify]` or dispatch). Gaps: no type check, no coverage measurement, no
  Windows lane in main CI, no frontend end-to-end tests, Trivy report-only, `tests/docker_lane.txt` is a manual
  88-entry skip list that drifts, certification is not mandatory before a merge.
- README is out of date (see section 5).

## 3. Dependabot PRs #10-#27 (reviewed separately; none merged or closed)

Verified from the PR diffs and the locks on `main`. Dependabot did not touch `main`; each PR is its own branch.

| PR | Change | Finding | Disposition |
|---|---|---|---|
| #10 | `ubuntu` 22.04 -> 26.04 in `Dockerfile.gnucobol` | The oracle's GnuCOBOL 3.1.2 comes from pinned Ubuntu 22.04 packages; a new base changes the **ground truth** and the package pins | **Reject / ignore** (oracle changes need their own certified unit) |
| #11 | `python` 3.11 -> 3.15 in `Dockerfile.production` | Certified on 3.11; locks are hashed for 3.11 wheels | **Defer** to a deliberate Python upgrade unit |
| #12 | `maven` temurin 21 -> 26 in `Dockerfile.maven-offline` | Generation targets and the offline Maven cache are certified on Java 21 | **Reject / ignore** |
| #13 #14 #19 #25 | pip floors: uvicorn >=0.54, starlette >=1.10, pydantic >=2.14.2, fastapi >=0.162 | Floors exceed the **locked** versions (0.52.3, 1.3.1, 2.13.4, 0.141.1), so `requirements.txt` would contradict its hash-pinned lock | **Defer**: take only with regenerated locks in one dependency-refresh unit |
| #20 #22 | pip floors: PyYAML >=6.0.3, httpx >=0.28.1 | Equal to the locked versions (no-ops) | **Accept candidate** (low value, no risk) |
| #15 #16 #18 #26 | actions setup-python/setup-node/checkout/upload-artifact -> v7.x | New SHAs match the upstream tags (verified for checkout, setup-python, setup-node, upload-artifact) | **Batch** into one actions-refresh unit, with CI as the gate |
| #21 | vitest 5.0.3 -> 5.0.5 | patch | **Accept candidate** after its CI |
| #17 #23 #24 #27 | typescript 7, jsdom 30, plugin-react 6, react 19 | Majors; the frontend pins React 18 / Vite 6 | **Defer** to a frontend-modernization unit |

Additional note: Dependabot's push and pull_request runs compete with the project's own CI for runners; a later
unit should tighten `.github/dependabot.yml` (grouping, ignore rules for pinned runtime pieces, path filters).

## 4. Target architecture

Deterministic spine kept as is: **ingest -> discover -> semantic IR -> capability analysis -> plan -> deterministic
lowering -> generate -> oracle/candidate execution -> comparison -> evidence -> verdict**. Extensions:

1. **Estate model** (new): one dependency graph over programs, copybooks, JCL jobs/steps, datasets, DB2 tables,
   CICS transactions, IMS PCBs/segments and MQ queues; every edge carries a proof state. Backs the portfolio,
   graph and coverage views and the decomposition planner.
2. **Runtime-target registry** (new): one table of runtime, adapter, candidate lane, certified flag; the API
   rejects uncertified targets.
3. **Subsystem simulators** (new): `SIMMQ`, `SIMDLI`, `SIMCICS` as versioned specs with a COBOL shim and a Java
   library, canonical trace format, trace comparator, verdict label `SIMULATOR_VERIFIED`.
4. **Database layer** (new): `DatabaseDialect` (DB2 first, PostgreSQL second, pluggable), type map (DECIMAL,
   TIMESTAMP, VARCHAR), SQL rewriter, SQLCODE/SQLSTATE mapper, JDBC persistence generation with exact
   `BigDecimal`, a PostgreSQL+OCESQL oracle image, and a migration/reconciliation module.
5. **Batch layer** (new): DD binding and dataset catalog (incl. GDG), JCL preprocessor (PROC/symbolics/SET/IF),
   JCL job -> Java orchestrator, IDCAMS/utility emulation.
6. **Hybrid decomposition** (new): partitioner (call graph, file ownership, copybook sharing) -> reviewable plan
   -> remote-CALL lowering with copy-in/copy-out semantics -> multi-artifact assembly -> multi-container
   candidate lane -> composed-system equivalence rule. Default remains "keep together"; decomposition is opt-in.
7. **Control plane** (hardening): durable job queue with cancel/retry/resume, OIDC + RBAC with derived approver,
   evidence signing, socket-proxy isolation, observability.

## 5. Roadmap (each unit: code + API + UI + docs + tests together; focused local tests; one commit; full CI gate)

| # | Unit | Size | Depends on | Deterministic proof |
|---|---|---|---|---|
| 0 | This audit, honest README, execution ledger (docs only) | S | - | CI green; README claims map to code |
| 1 | Platform hygiene: runtime-target registry; reject uncertified targets; stale docstrings; remove `_run_legacy`; label experimental modules | S-M | 0 | existing suites + registry tests |
| 2 | Real MQ/IMS call-form detection and dependency edges; reconcile matrix rows | S | 1 | mutation/negative tests (comment/literal masking) |
| 3 | Dependency refresh unit (locks, actions) incl. Dependabot triage | M | 1 | full CI + certification |
| 4 | `ASSIGN TO ddname` <-> JCL DD binding, dataset catalog | M | 2 | GnuCOBOL run with the same DD mapping |
| 5 | JCL PROC/symbolics/SET/IF preprocessor | M | 4 | golden expanded-JCL suite |
| 6 | JCL job -> Java batch orchestrator | L | 4, 5 | GnuCOBOL multi-step driver: step RCs + final files byte-equal |
| 7 | Keyed-file breadth (offsets, ACCESS modes, alternate keys, FILE STATUS set) | M | - | oracle fuzz on generated fixtures |
| 8 | IDCAMS/GDG/dataset utilities | M-L | 6, 7 | byte-diff of emulated files; GDG resolution model |
| 9 | Numeric-edited PIC (existing local work, on authorization), INSPECT, SEARCH, SORT/MERGE | L | - | oracle fuzz on all four runtimes + corpus app |
| 10 | EXEC SQL -> IR, SQLCA, INCLUDE/DCLGEN | L | 1 | IR goldens; negatives still blocked |
| 11 | `DatabaseDialect` (DB2, PostgreSQL) + type map + SQLCODE mapper | M | 10 | table-driven unit tests |
| 12 | OCESQL+PostgreSQL oracle image and JDBC persistence generation | L | 11 | same seeded DB, stdout/RC + DB-state hash |
| 13 | Data migration and reconciliation | M | 12 | source-vs-target keyed checksums |
| 14 | MQ simulator + shim | L | 2 | differential trace + queue image |
| 15 | IMS DL/I simulator, hierarchy->relational mapping | L | 14 | status codes + DB image identical |
| 16 | CICS simulator/precompiler, BMS maps | L | 14, 7 | per-transaction trace incl. pseudo-conversational |
| 17 | Estate model + read-only enterprise API/UI (portfolio, graph, coverage, evidence browser) | M-L | 2, 4 | API/UI tests; coverage endpoint = registry |
| 18 | Decomposition planner, remote-CALL lowering, multi-artifact assembly, multi-container lane | L | 17 | composed-system equivalence vs single-jar |
| 19 | Control-plane hardening: durable queue, OIDC+RBAC, signing, socket proxy, type check, coverage, Windows lane | L | owner decisions | security tests, restart/cancel drills |

## 6. Owner-dependent decisions (blockers outside the code)
- Identity provider (OIDC issuer, roles), key management / signing authority, retention and encryption policy.
- Target databases beyond DB2 and PostgreSQL; hosting (Kubernetes/compose) for decomposed services.
- IBM CICS/IMS entitlement (BL-132) - or acceptance that CICS/IMS equivalence stays `SIMULATOR_VERIFIED`.
- Whether Python/Java/Ubuntu runtime pins may move (and re-certification of the oracle if so).
- Approval to merge the paused numeric-edited PIC work (kept safe, not part of this baseline).

## 7. Claims policy
No capability is claimed until the corresponding unit has passed its proof and CI. Simulator-based equivalence is
labelled as such. The README states what the platform is, what it is not, and the roadmap separately.
