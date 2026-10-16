# MASTER README LINE-BY-LINE AUDIT

**Document type:** Independent audit deliverable (Master README §76 / §80)
**Audited commit:** `f3d0352812eaa6314f39384a78189d6a20151c8a` (branch `codex/universal-core`, HEAD == origin)
**Audit date:** 2026-10-16
**Mode:** Read-only (audit-first). No source, test, architecture, or capability-claim changes were made. No merge to `main`.
**Auditor:** OpenCode (§76 independent audit pass before Phase 12 implementation)

---

## 1. Exact Baseline and Audit Scope (§76.1)

| Item | Value |
|---|---|
| Repository | `Shankar373/Cobol-Java-Transformation` |
| Branch | `codex/universal-core` |
| HEAD | `f3d0352812eaa6314f39384a78189d6a20151c8a` == `origin/codex/universal-core` (git fetch verified) |
| Working tree | Clean except preserved `test-artifacts/*` (modified/untracked — never staged, per standing invariant) |
| Merge state | Not merged to `main`; PR governance items (PR #1/#2/#3/#6) remain open by design (BL-013/014/015/016) |
| CI at audited SHA | **GREEN** — 4/4 runs: SystemaOps CI push `38907021483`, SystemaOps CI PR `38907028432`, Supply chain push `38907021370`, Supply chain PR `38907028746`; all 14 jobs `success`; head_sha verified = `f3d0352812ea…` for every run/job |
| Test environment | `.venv-audit` (Python 3.11), `PYTHONPATH=repo root`; Docker/Java host toolchain unavailable locally → Docker/Java-gated tests skip locally and run in CI Linux (documented, not chased) |
| NO-LLM invariant | **PASS** — 0 model-provider packages in `requirements.txt`, `requirements.lock`, `tmp/requirements-win.txt`, `frontend/package.json`, `frontend/package-lock.json`; 0 model API keys/endpoints/`MODEL_NAME` in `.github/workflows/*`, `scripts/**`, Dockerfiles, `.env*`; 0 model imports in `engine/`, `api/` (code identical to `b2fb1a2`, which was scanned at Phase 11; `f3d0352` = `b2fb1a2` + docs only) |
| Authority documents read | `MASTER_IMPLEMENTATION_README.md` (all 2346 lines, §1–§80), `opencode.md` (3592 lines, phase verdicts), `docs/BACKLOG.md` (6045 lines, full register + change-log), `docs/CAPABILITY_MATRIX.md`, `docs/SEMANTIC_PROOF_MATRIX.md`, `docs/KNOWN_ISSUES.md`, `docs/REMEDIATION_MATRIX.md`, `docs/CODE_AUDIT_REPORT.md`, `docs/SYSTEMAOPS_PRODUCT_STATUS.md`, `docs/ARCHITECTURE.md`, all `docs/PHASE*` reports, root `README.md`, `.github/workflows/ci.yml`, `.github/workflows/supply-chain.yml` |

**Audit scope:** every Master README section (§1–§80), all 13 phases (0–12), all subsystems (ingestion → UI), all COBOL constructs claimed anywhere, all 90 backlog register rows, test/CI integrity, documentation consistency, NO-LLM compliance.

---

## 2. Architecture / Data-Flow Map with Real Entry Points (§76.2)

Trace verified end-to-end (entry point → integration → caller), not inferred from file existence:

| Stage | Real entry point (file:line) | Integration path | Tests exercising the real path |
|---|---|---|---|
| Ingestion | `api/app.py:407` `POST /applications/{id}/upload`; `api/app.py:465` `POST …/ingest`; `api/ingestion.py` | FastAPI → `api/service.py` → engine | `tests/test_ingestion_diagnostics.py` (CI job `phase1-ingestion`), Phase-11 upload integrity suite |
| Discovery | `api/app.py:500` `GET …/discovery`; `engine/transformation/application_discovery.py` (`_extract_calls` L400, program rows L311/L351) | source scan → program/CALL/COPY inventory → `called_programs` | `tests/test_phantom_dependency_masking.py`, `test_call_resolution_truth.py`, `test_external_dependency_edges.py` (capability gate) |
| Dependency graph / capability | `engine/modernization/capability_analyzer.py` (`_iter_call_statements` L144), `engine/transformation/semantic_capability.py` | IR statement walk → capability registry | `tests/transformation/test_capability_registry_reconciliation.py`, `test_capability_walker_depth.py`, `test_usage_capability.py` (gate) |
| Planning | `engine/modernization/modernization_planner.py` (`_map_blocking_reasons` L693–745) | capability → BLOCKED/SUPPORTED plan, fail-closed | `tests/transformation/test_planner_missing_component_fail_closed.py` (gate) |
| Parse | `engine/transformation/cobol_parser.py:312` `CobolParser.parse` (L365) | source → `CobolProgram` IR (`engine/transformation/ir.py`) | 223 pytest files across `tests/transformation/` |
| Semantic IR | `engine/transformation/ir.py` (`CallStatement` L505, `called_programs` L992) | parser → IR → mapper | `test_silent_loss_registry.py` (gate) |
| Transformation | `engine/transformation/cobol_to_java_mapping.py` (`map_cobol_statement` L1919, `map_cobol_programs_to_application` L3280) | IR → Java IR; `program_map` built L3302 | `test_domain_neutral_proof.py`, `test_java_architecture.py`, `test_phase3_generator_migration.py` |
| Java generation | `engine/transformation/java_generator.py`, `spring_boot_generator.py` | Java IR → source files | `test_generator_string_literals.py`, `test_spring_model_emission_unique.py` (gate) |
| Runtime adapter | `engine/candidate/*` (factory, docker adapters), `engine/transformation/runtime_adapters.py` | profile → adapter → build | `tests/test_runtime_adapter_architecture.py` (gate, 28 tests) |
| Build/package | Maven (offline image) in CI `backend-oracle` job | adapter → JAR | `tests/test_phase9_build_execute.py`, `tests/candidate/*` |
| Candidate execution | `engine/execution/docker_runner.py` (resource limits, timeouts) | isolated container run | `tests/execution/*`, `tests/integration/test_docker_java.py` |
| Oracle execution | `engine/oracle/docker_adapter.py` (GnuCOBOL image, digest-pinned) | independent COBOL run | `tests/integration/test_numeric_oracle_proof.py`, `test_oracle_multiprogram.py` |
| Differential comparison | `engine/comparators/framework.py` (registry L194; Stdout L224, Stderr L281, ExitStatus L338, TextFile L409, FixedRecord L466) | contract-aware compare → result | `tests/comparators/*` (incl. `test_fixed_record_trailing_partial.py` gate) |
| Evidence | `engine/evidence/models.py:384` `EvidenceManifest`, canonical graph L246; `engine/evidence/integrity.py:106` `EvidenceIntegrityValidator` | manifest → hash → seal → validate (fail-closed) | `tests/evidence/*`, `tests/adversarial/test_phase_a_trust_hardening.py`, Phase-10 gate files |
| Verdict | `engine/verdict/derivation.py:374` `derive_verdict_validated`, `:385` `derive_verdict_untrusted` | validated manifest → 7-state verdict; untrusted → fail-closed | `tests/verdict/*`, `tests/test_certification_contract.py` |
| Integrated proof | `engine/modernization/integrated_proof.py:361` `evaluate_central_status`, `:458` `runtime_evidence_from_result` | lanes → central status (gate can only downgrade) | Phase-10 `test_phase10_p0_integrated_proof_gate.py` etc. (gate) |
| Persistence / API | `api/store.py` (SQLite), `api/app.py` runs/validate/verdict/report (L529–L699) | run state → API | `tests/test_api_*` suites (backend job) |
| UI / export | `frontend/src/api/client.ts`, pages; `api/app.py:700` `GET /runs/{id}/download` (50 MiB / 5000-file caps, BL-067) | API → React → download ZIP | `frontend/src/__tests__/*` — 7 files / 122 tests, all pass (run this audit) |

**Failure/unavailable paths:** fail-closed is pervasive (verdict untrusted path, planner BLOCKED, unsupported-construct diagnostics, evidence validation errors). Local Docker/Java unavailability → documented skips; CI executes them (`RUN_DOCKER_TESTS=1`, images built from `Dockerfile.gnucobol` / `Dockerfile.maven-offline`, runtime digest pulled).

**Gap found in the flow:** the §9 canonical pipeline stage **“Customer Approval → Export”** has Export but **no Customer Approval implementation** (see F-01).

---

## 3. Requirement-to-Code-to-Test-to-Evidence Traceability Matrix (§76.7.4)

Status legend: **PASS** = implemented + tested + CI-verified at audited SHA · **PARTIAL** = some lanes implemented/verified, remainder documented-but-absent or unverified · **FAIL** = required but absent/broken · **BLOCKED** = prevented by environment/human decision · **UNVERIFIED** = claimed but not independently provable in this audit.

| # | Requirement (source line) | Implementation | Integration | Tests | CI evidence | Status |
|---|---|---|---|---|---|---|
| §1–§7 | Purpose/mission/deliverables/universal objective (L13–240) | Product exists as specification; deliverable list L173–196 | — (document contract) | — | — | PASS (spec-level) |
| §8 | Current reality vs target: no universal claim (L241–274) | Honest partial-state docs (`CAPABILITY_MATRIX`, SPS §15–19) | docs authority §78 | capability-truth gate (54 files/632 tests) | gate job green | PASS |
| §9–§10 | One canonical pipeline; no duplicates (L275–346) | `engine/pipeline.py:121` `VerticalSlicePipeline`; single mapper/generator set | service → engine | `tests/integration/test_vertical_slice.py`, plan-enforcement tests | backend job green | PASS |
| §11 | Secure ingestion (L347–377) | `api/ingestion.py`, `api/app.py:407/465`; traversal/size limits (`api/limits.py`) | API → service | Phase-11 `test_phase11_p1_upload_integrity.py` (8) | green | PASS |
| §12–§13 | Discovery + dependency graph (L378–436) | `application_discovery.py`, `external_dependency_edges.py` | discovery → planner | gate: phantom-dependency, call-resolution, external-edges tests | gate green | PASS |
| §14–§15 | Capability analysis + planning (L437–482) | `capability_analyzer.py`, `modernization_planner.py` | capability → BLOCKED plan | `test_planner_missing_component_fail_closed.py` | gate green | PASS |
| §16–§17 | COBOL parser + semantic IR (L483–562) | `cobol_parser.py`, `ir.py` | parser → IR → mapper | parser/IR suites (hundreds of tests) | backend green | PASS (supported subset; universality PARTIAL per §76.3) |
| §18–§19 | Numeric + data semantics (L563–610) | `numeric_semantics.py`, `figurative.py`, PIC mapping | oracle-proven lane | `test_numeric_semantics.py`, `test_figurative_fill_semantics.py` (gate), `test_numeric_oracle_proof.py` | backend green (oracle runs in CI) | PARTIAL — value/display semantics oracle-proven; COMP/COMP-3 **byte encoding unverified** (documented KNOWN-ISSUES P0, roadmap) |
| §20–§21 | COPY/REPLACE, CALL semantics (L611–646) | `copybook_resolver.py`, CALL handling `cobol_to_java_mapping.py:2708–2812` | discovery → mapping | gate: 7 copybook tests + call tests (BL-031…BL-039 fixed) | gate green | PASS (COPY REPLACING subset; standalone REPLACE UNVERIFIED) |
| §22–§23 | JCL (L647–708) | `jcl_parser.py`, `jcl_spring_boot_adapter.py`, `engine/jcl/` | discovery → JCL lane | gate: 6 JCL files + `test_jcl_lane_hygiene.py` | gate green | PARTIAL — modeled/execution-lane proven per workload; "not certified" disclosed (central NOT_VERIFIED) |
| §24 | DB2/SQL (L709–731) | `sql_parser.py`, `engine/sql/*` | SQL lane → ledger | gate: 4 SQL/DB2 files; Phase-10 BL-083 producers | gate green | PARTIAL — modeled, diagnostics fail-closed; runtime DB2 equivalence not claimed |
| §25 | VSAM/Files (L732–756) | file I/O mapping, runtime-adapter storage | mapper → `CobolFileIo` | `test_file_invalid_key_lane.py`, `test_rewrite_binding.py` (gate), Phase-4 suites | backend green | PASS (sequential/relative subset); indexed DYNAMIC/alternate keys disclosed unverified |
| §26–§29 | CICS/MQ/IMS/utilities (L757–839) | `engine/cics/`, detection (`test_ims_mq_detection.py`, `test_utilities_vsam_detection.py` gate) | detection → plan BLOCKED | gate green | gate green | PARTIAL — detection/classification only, disclosed structural-only |
| §30–§31 | Semantic transformation + Java IR (L840–886) | `cobol_to_java_mapping.py`, `java_ir.py` | IR → Java IR → generator | `test_domain_neutral_proof.py`, `test_silent_loss_registry.py` (gate) | gate green | PASS (subset); BL-045 residual (F-02) |
| §32 | Runtime adapter architecture, 3 targets (L887–918) | `plain_java` / `spring_boot` / `jakarta_ee` profiles (BL-088/089/090 fixed) | factory → adapters | `test_runtime_adapter_architecture.py` (28, gate) | gate green | PASS |
| §33–§34 | Build/packaging + isolated execution (L919–1000) | Maven offline image; `docker_runner` limits (CPU/mem/PID/timeout) | adapters → Docker | `tests/execution/*`, `test_sandbox_paths.py` | backend green | PASS |
| §35–§36 | Independent oracle + candidate execution (L965–1000) | digest-pinned GnuCOBOL image, pinned temurin JDK | parallel runs | `test_oracle_multiprogram.py`, `test_numeric_oracle_proof.py` | backend green (3857 passed) | PASS |
| §37 | Differential comparison (L1001–1024) | comparator registry + mutations | compare → evidence | `tests/comparators/*` + adversarial mutation suites | backend green | PASS |
| §38–§39 | Evidence + verdict (L1025–1078) | `EvidenceIntegrityValidator`, `derive_verdict_*`, 7 states | evidence → API → UI | `tests/evidence/*`, `tests/verdict/*`, Phase-10 gate files | gate + backend green | PASS (production-path hardening completed Phase 10/11) |
| §40–§41 | Verification ladder + integrated proof (L1079–1136) | levels 0–7, `evaluate_central_status` fail-closed | proof → verdict | Phase-10 `test_phase10_p0_integrated_proof_gate.py` | gate green | PASS |
| §42 | Security/trust boundary (L1137–1181) | bearer auth, path traversal, archive limits, identity binding | API middleware → service | `tests/adversarial/*` (254 tests) + Phase-11 security suites | backend green | PASS (with disclosed §43 gaps below) |
| §43 | Enterprise security target (L1182–1205) | single-token auth, SQLite, no audit log | — | — | — | PARTIAL — **single-token auth / no RBAC / no audit log / no multi-node** explicitly disclosed (§43 targets, carried) |
| §44–§45 | Open-source strategy (L1206–1271) | Phase-5E evaluation report; KEEP/AUGMENT/REPLACE respected | docs | `PHASE5E_OPEN_SOURCE_TRANSFORMER_EVALUATION.md` | — | PASS (evaluation done; no component replaced without regression) |
| §46 | Product modes A/B (L1272–1315) | Mode B external candidate validation (candidate upload endpoint `api/app.py:424`) | API | candidate suites | backend green | PASS |
| §47–§48 | Differentiation + traceability (L1316–1369) | source→IR→Java trace fields, evidence identities | evidence graph | traceability tests in evidence suites | backend green | PASS |
| §49–§50 | Testing strategy + fresh E2E (L1370–1446) | unit/contract/integration/security/adversarial + fresh E2E in CI | CI jobs | 3600 test functions / 200 files; CI runs full tree | **3857 passed, 0 failed, 0 skipped** (backend, exact SHA); frontend 122/122 | PASS |
| §51 | CI/CD (L1447–1478) | `ci.yml` (4 jobs) + `supply-chain.yml` (3 jobs, gating) | push/PR triggers | all jobs no `continue-on-error` | 4/4 runs green at audited SHA | PASS |
| §52–§53 | Phase map + completion rule (L1479–1540) | 13 phases; §53 13-point verdicts in `opencode.md` | checkpoint | per-phase focused+regression | exact-SHA CI per phase (re-verified today Phases 0–9: all GREEN) | PASS (process); Phase 12 not yet run |
| §54 | Known high-risk areas (L1542–1578) | each P0/P1/P2 area mapped to gates/tests | — | capability gate, oracle proof, adversarial suites | green | PASS (risk areas have active controls; mutation testing absent → F-05) |
| §55–§56 | Enterprise + incremental requirements (L1579–1642) | partially (durable jobs=threads, retention, export); incremental not implemented | — | — | — | PARTIAL — disclosed "must eventually" items (portfolio, rollback, approval gates) |
| §57–§63 | Execution contract / reuse / determinism / no-silent-loss / no-fake-verification / test preservation / green baseline (L1643–1800) | enforced by workflow + `test_silent_loss_registry.py` + gate list | — | gate 54 files frozen list | gate green | PASS |
| §64–§69 | Checkpoint + truth rules (L1801–1953) | `opencode.md` present, phase verdicts match git SHAs (all 14 phase SHAs verified in history) | — | — | — | PASS |
| §70 | Definition of Done (L1954–2030) | see §7 scoring below | — | — | — | PARTIAL |
| §71 | Final Release Gate (L2032–2058) | see §7 scoring below | — | — | — | PARTIAL (1 blocking FAIL) |
| §74–§75 | Build what can be proven / state lives in opencode.md (L2102–2152) | followed | — | — | — | PASS |
| §76–§80 | Audit-first / backlog contract / doc authority / NO-LLM / audit rule (L2154–2345) | this report is the §76/§80 artifact; 90-row backlog; §79 PASS | — | — | — | PASS (this audit) |

---

## 4. Phase Status (0–12)

| Phase | Declared (checkpoint) | Work SHA(s) | Independent verification this audit | Status |
|---|---|---|---|---|
| 0 Architecture freeze | COMPLETE — VERIFIED | `bdb4c9a` | SHA in history; CI at exact SHA **GREEN (4 runs)** | COMPLETE — VERIFIED |
| 1 Parser/IR | COMPLETE — VERIFIED | `7dceec1` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 2 COBOL semantics | COMPLETE — VERIFIED | `de8a808` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 3 CALL/COPYBOOK/graph | COMPLETE — VERIFIED | `4deddfc` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 4 Files/VSAM | COMPLETE — VERIFIED | `7bcf714` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 5 JCL | COMPLETE — VERIFIED | `b7f6246` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 6 DB2/SQL | COMPLETE — VERIFIED | `0efa49f` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 7 CICS/MQ/IMS | COMPLETE — VERIFIED | `e67b59e` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 8 Runtime adapters | COMPLETE — VERIFIED | `5f82889` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 9 Build/Execute/Verify | COMPLETE — VERIFIED | `2a5e4fd` | CI exact SHA GREEN | COMPLETE — VERIFIED |
| 10 Evidence/Certification | COMPLETE — VERIFIED 13/13 | `0f4d049`→`72679a6`→`cb6dc55` (+docs `c039de3`) | verified in-session with 12/12 exact-SHA runs | COMPLETE — VERIFIED |
| 11 Enterprise security | COMPLETE — VERIFIED 13/13 | `1c37503`→`b2fb1a2` (+docs `f3d0352`) | verified in-session with 8/8 runs; docs commit CI re-verified **GREEN today** (4/4) | COMPLETE — VERIFIED |
| 12 Regression/E2E/Release gate | **NOT STARTED** | — | gate precondition (Phases 10+11 independently verified) **satisfied** | OPEN — ready to start |

---

## 5. Supported / Partially Supported / Unsupported Capabilities (§76.3)

Declared levels reconciled across `CAPABILITY_MATRIX.md`, `SEMANTIC_PROOF_MATRIX.md`, `SYSTEMAOPS_PRODUCT_STATUS.md` §15–19 (canonical set per `CURRENT_DELIVERY_STATUS.md:16-23`); strongest level demonstrated governs.

**SUPPORTED (oracle/proof-backed subset):** MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE (basic forms), COMPUTE (post-Phase-7), IF/ELSE, PERFORM (plain/UNTIL/TIMES/VARYING), STRING (certified), UNSTRING (pipe/delimited subset), DISPLAY, STOP RUN, EXIT PROGRAM, READ (AT END/NOT AT END), WRITE, OPEN/CLOSE (sequential), static resolved CALL (value-result proven), ROUNDED (HALF_UP), figurative constants + VALUE/ALL fill, PIC X/9/S/V value semantics, COPY + COPY REPLACING (supported operand forms), hierarchical working storage (BL-058), JCL parse/link lane (workload-proven), runtime targets `plain_java`/`spring_boot`/`jakarta_ee` (build+execute verified per workload), evidence integrity, 7-state verdict, integrated proof fail-closed, differential comparison (byte-identical for certified fixtures).

**PARTIAL / NOT CERTIFIED (disclosed):** COMP/COMP-1/2/3/5 (value semantics only — byte encoding unverified), indexed/relative files (structural lane + Phase-5C workload proofs exist but certification "not claimed"), DB2/SQL, CICS, JCL central status (modeled → NOT_VERIFIED), UNSTRING breadth, PERFORM THRU/out-of-line (blocked outside known paragraphs), oracle identity provenance (declared, not runtime-verified), evidence-ladder rows beyond current subset.

**UNSUPPORTED (fail-closed with diagnostics):** GO TO (comment+diagnostic), GOBACK as transform target, SORT, MERGE, INSPECT, SEARCH, SET, ALTER, ACCEPT, INITIALIZE, NEXT SENTENCE, ON SIZE ERROR (forms), `**`/FUNCTION, standalone REWRITE/DELETE/START (indexed), INVALID KEY marks program UNSUPPORTED, EXEC SQL/EXEC CICS constructs (lane modeled, construct unsupported), EXEC DLI/MQI (classification only), RELEASE/IDCAMS (detection), dynamic/unresolved CALL, CALL BY VALUE/BY CONTENT (never claimed).

**UNVERIFIED / UNKNOWN:** REDEFINES, OCCURS (generated Java does not compile — never SUPPORTED), 88-level lowering, nested programs/ENTRY, standalone REPLACE, fixed/free format + dialects breadth, conditional compilation.

**Documentation contradictions flagged (§76.6):** 16 cross-document status contradictions (C1–C16) — e.g., GO TO "Supported" in `PHASE5E/5F1/5G` reports vs UNSUPPORTED in canonical SPM; Phase-5C "VERIFIED COMPLETE" for indexed vs CM "not certified"; `CODE_AUDIT_REPORT` "29 OPEN" vs register (25 now FIXED); SPS §16/§17 GOBACK wording. Per §78 these historical reports are **history**, not live claims — but they require an explicit reconciliation pass (F-04).

---

## 6. Findings Matrix — Remaining Defects and Gaps (§76.7.3, §76.7.5)

**P0: NONE OPEN.** All eight filed P0 backlog items (BL-027/029/030/031/032/040/053/088) are FIXED and gate-enforced; the §54 P0 risk areas (capability truth drift, parser/IR mismatch, numeric semantics) have active controls (capability-truth gate, silent-loss registry, oracle proof). No new P0 exposure found in this audit.

### P1

| ID | Finding | Evidence (file:line) | Root cause | Impact |
|---|---|---|---|---|
| BL-045 | **REPRODUCED at audited SHA (empirical red evidence).** Nested CALL inside IF/PERFORM loses `called_programs` — value-result sync and entry-method resolution silently diverge from top-level CALL | `engine/transformation/cobol_to_java_mapping.py` — recursion sites **L2187, L2190** (IfStatement), **L2584, L2614, L2638, L2677** (PerformStatement bodies) call `map_cobol_statement(s, program)` **without** `called_programs`; ReadStatement branches L2238–2308 do thread it. Probe: top-level CALL to linkage callee → `SYNC-ASSIGN Inner.L_ARG / CALL Inner.MAIN_LOGIC / SYNC-ASSIGN W_A`; same CALL nested in IF → plain `CALL Inner.MAIN_LOGIC args=1` (no sync, no linkage inspection). With paragraph-entry callee (no linkage): top-level resolves `Inner.p100_INIT`, nested falls back to `Inner.MAIN_LOGIC` (wrong method) | Mapper recursion predates the `called_programs` parameter; six sites never updated | Nested CALLs (standard COBOL) generate **semantically different Java** than identical top-level CALLs: BY REFERENCE mutations lost, wrong entry method → runtime divergence or compile error. Silent semantic loss risk (§60) |
| BL-046 | Spring Boot lane emits **unescaped** string literals — diverges from native lane (BL-030 fix not applied here) | `spring_boot_generator.py:670` `return f'"{expr.value}"'`, `:677` same; native helper `_escape_java_string` exists at `java_generator.py:852` but is not used | BL-030 remediation applied only to the native generator | Literals containing `"`/`\`/control chars produce invalid Java or behavior divergence between lanes |
| F-01 (new; to be filed as backlog ID at Phase 12 start) | **Customer Approval stage (§9 pipeline L316, §70 Product "approval workflow" L2026, §71 checkbox 21 L2057) has no implementation** — no API endpoint, no service logic, no frontend surface anywhere (`api/*.py`, `engine/**`, `frontend/src` all searched: 0 approval-workflow hits) | §9 L316; §70 L2026; §71 L2057; search results above | Stage never implemented in any phase | §71 Final Release Gate cannot pass; §70 DoD Product incomplete. Export exists (`api/app.py:700`) but nothing gates it on approval |

### P2

| ID | Finding | Evidence | Root cause | Impact |
|---|---|---|---|---|
| BL-065 | Legacy Java-generator region isinstance-checks IR classes never imported → `NameError` if reached | `java_generator.py:1792` (ReadStatement), `:1849` (MoveStatement), `:1887` (IfStatement); module imports only `java_ir`, `figurative`, `numeric_semantics` (top of file) | Legacy region predates import cleanup | Latent crash path in generation; must be proven unreachable or fixed fail-closed |
| F-02 | Documentation synchronization debt (§76.6): (a) root `README.md:11-13` presents **"CURRENT BASELINE: fedb7dd / Current CI: #417/#418"** — stale wording contradicting its own BL-009 note and the live authority (`opencode.md` = `f3d0352`, CI 4/4 green); (b) five backlog sections still say **OPEN** while their register rows say FIXED 2026-10-16 (BL-047/048/049/067/068; sections L1112/L1141/L2283/L3005/L3029 vs register L5994–5996/L6014/L6015); (c) `CODE_AUDIT_REPORT.md:145-159` "29 OPEN" stale (25 FIXED); (d) capability contradictions C1–C16 (§5 above) | exact lines cited | No reconciliation pass since Phase 11 | Misleads readers about current state; §71 "Documentation synchronized" cannot pass |
| F-03 | Test-integrity skips that can mask regressions: (a) `tests/test_universal_modernization.py:311` **skips on generation failure** (`pytest.skip(f"Generation failed…")` instead of failing); (b) `tests/integration/test_phase_d_negative_integration.py:379` assertion-shaped conditional skip | exact lines cited | Skip used where failure/expected-diagnostic assertion belongs | §53 rule ("must not pass because of a skip") violated in spirit: a broken generator could turn these green-by-skip |
| BL-012 (remainder) | CI depth: **no coverage thresholds, no mutation testing, no Python lint/type gate** (KNOWN_ISSUES P2 "CI depth"; `PHASE5F`/`KNOWN_ISSUES.md:47-49`) | no `pytest.ini`/`pyproject` coverage config; `ci.yml` runs pytest without coverage/mutation | deliberately deferred 2026-10-10, re-scoped for Phase 12 | §54 P2 "deeper CI coverage / mutation testing" unmet; fail-closed paths lack mutation proof |

### P3

| ID | Finding | Evidence | Impact |
|---|---|---|---|
| BL-066 | Planner reason mapping substring-parses analyzer prose; GO TO double-appends `UNSUPPORTED_CONSTRUCT`; any "parsed" wording maps to `PARSE_FAILURE` | `modernization_planner.py:735` `"parse" in reason_lower`; `:738` and `:740` append `UNSUPPORTED_CONSTRUCT` twice | Duplicate/misleading blocking reasons in plan output (correctness of diagnostics, not safety — fail direction is still BLOCKED) |
| F-04 (new) | **Stale checked-in evidence artifacts**: `git ls-files test-artifacts` shows committed junit XMLs containing failures — `phaseD-final2-junit.xml` (10 failures), `phaseD-baseline` (7), `phaseD-final` (4), `ci/backend-junit.xml` (29 errors) | artifact zip of run `38907021483` + `git ls-files` output | Could be mistaken for current results; §76.5 explicitly requires reporting this. **Removal is blocked by the "never commit test-artifacts/* changes" invariant → needs human authorization (D-4)** |
| F-05 (new) | Backlog metadata gap: BL-001…BL-024 lack explicit priority/severity fields | `docs/BACKLOG.md:2203-2212` (self-documented, targets a documentation pass) | §77 contract completeness |

### BLOCKED / CARRIED (not defects of code)

- **BL-010** BLOCKED (environment): no host JDK / Docker-in-Docker on the audit workstation; covered by CI Linux — carried.
- **BL-012** partial scope (above) — Phase 12 decision.
- **BL-013/014/015/016** — human PR-governance decisions (re-diff-or-close PR #1; do-not-merge PR #6; keep PR #2/#3 open) — carried.

---

## 7. §53 Completion Evaluation and §71 Final Release Gate Scoring (§76.7)

### §53 (13-point rule) — project-level evaluation at audited SHA

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | implementation matches architecture | PASS | §2 map; ARCHITECTURE.md subsystems all present |
| 2 | contracts satisfied | PASS | `contracts/` specs + contract tests in gate/backend |
| 3 | focused tests pass | PASS | gate 54 files green in CI at exact SHA |
| 4 | regression tests pass | PASS | backend **3857 passed / 0 failed / 0 skipped** at exact SHA |
| 5 | integration behavior verified | PASS | adversarial + integration suites in CI |
| 6 | fresh E2E verified where applicable | PASS (CI) / PENDING (Phase-12 local fresh run) | CI backend runs full fresh pipeline per push; Phase 12 will re-run fresh E2E as its own gate |
| 7 | evidence reproducible + integrity-validated | PASS | Phase-10 seal re-check/validator suites in gate |
| 8 | limitations documented | PASS | KNOWN_ISSUES + SPS §15–19 + disclosed limitations list |
| 9 | no silent semantic loss | PARTIAL | silent-loss registry active, but BL-045 (F-02 above) is an open silent-divergence path until fixed |
| 10 | defects fixed or explicitly carried | PASS | 90-row register: every item has ID/status/owner/target; 4 open items assigned Phase 12; F-01/F-04 to be filed at Phase 12 start |
| 11 | all gap classes audited | PASS | this report |
| 12 | acceptance criteria satisfied | PARTIAL | per-phase yes; project-level waits on Phase 12 |
| 13 | checkpoint updated from actual results | PASS (Phases ≤11) / PENDING (this audit appended) | `opencode.md` verdicts match git + CI re-verification |

**Project §53 verdict: NOT YET COMPLETE — Phase 12 outstanding (this audit is its entry gate).**

### §71 Final Release Gate (21 checkboxes)

| # | Gate item | Score | Basis |
|---|---|---|---|
| 1 | Architecture complete | ✅ | §9/§10 canonical single pipeline |
| 2 | Discovery complete | ✅ | discovery + edge suites (disclosed walker-F6 scope) |
| 3 | Dependency graph complete | ✅ | graph + unresolved-dependency detection |
| 4 | COBOL semantic coverage validated | ⚠️ PARTIAL | supported subset validated; universal coverage explicitly not claimed (roadmap) |
| 5 | IR validated | ✅ | registry reconciliation gate |
| 6 | Transformation validated | ✅ | oracle-proven subset + fail-closed diagnostics |
| 7 | Runtime adapters validated | ✅ | 3 targets (§32) + architecture gate |
| 8 | Java build validated | ✅ | Maven CI per push |
| 9 | Candidate execution validated | ✅ | Docker sandbox runs in CI |
| 10 | Oracle execution validated | ✅ | GnuCOBOL digest-pinned runs in CI |
| 11 | Differential comparison validated | ✅ | comparator registry + mutation suites |
| 12 | Evidence integrity validated | ✅ | validator + Phase-10 seal re-check |
| 13 | Verdict validated | ✅ | 7 states, fail-closed, tamper/replay suites |
| 14 | Security validation passed | ⚠️ PASS with disclosed limits | adversarial 254 green; single-token/no-RBAC/no-audit-log disclosed (§43 carried) |
| 15 | Regression suite passed | ✅ | 3857 passed at exact SHA |
| 16 | Fresh E2E passed | ⚠️ PASS in CI / local fresh re-run = Phase 12 task | CI backend is fresh per push |
| 17 | CI green | ✅ | 4/4 runs at audited SHA |
| 18 | Documentation synchronized | ❌ FAIL | F-02 (README "current" baseline, 5 stale OPEN sections, stale CODE_AUDIT counts, C1–C16) |
| 19 | Known limitations documented | ✅ | KNOWN_ISSUES + SPS + this report |
| 20 | Export validated | ✅ | download endpoint + caps + frontend tests |
| 21 | Customer approval workflow validated | ❌ FAIL | F-01 — not implemented anywhere |

**§71 score: 16 ✅ / 3 ⚠️ / 2 ❌ — NOT enterprise-ready-declarable.**

---

## 8. Regression Risks and Green-Baseline Protection Plan (§76.7.7)

1. **Red-first, batch-per-priority:** P0 (state explicitly: no P0 open) → P1 (BL-045, BL-046, F-01) → P2 (BL-065, F-02 docs, F-03 skips, BL-012 remainder) → P3 (BL-066, F-04, F-05). Never start a batch until the previous is exact-SHA CI green.
2. **BL-045 fix is the highest regression risk** — it touches the hot mapper recursion (`cobol_to_java_mapping.py`); six call sites change. Protection: focused red test first (CALL-inside-IF value-result + entry-method parity), then gate 54 files + full backend suite; the parity assertion must compare nested vs top-level output, not a hardcoded string.
3. **Gate list (54 files) must not shrink or weaken**; `ci.yml` file list is frozen (§63). No test deletions, no skip additions, no assertion loosening anywhere.
4. **`test-artifacts/*` never staged** — F-04 removal requires explicit human authorization (invariant conflict).
5. **BL-046 fix** must reuse `java_generator._escape_java_string` (single canonical escape) and prove lane parity with a focused test (quoted/backslash literal in both lanes).
6. **BL-065 fix** must prove reachability first (red test invoking the legacy region) — if unreachable, fail-closed guard + test, not deletion of existing behavior (§62).
7. **Fresh E2E at Phase 12 close** must be executed fresh (no artifact reuse) per §50; local Docker gaps documented, CI Linux is the execution venue.
8. **No merge to `main`**; branch stays `codex/universal-core`.

---

## 9. Items Requiring a Human / Product / Legal / Security Decision (§76.7.8)

| ID | Decision needed |
|---|---|
| D-1 | **Customer approval workflow scope (F-01):** what constitutes approval (API state machine? UI sign-off? immutable approval record?) — product decision before implementing the §71/§9 stage |
| D-2 | BL-013/014/015/016 — PR #1/#2/#3/#6 governance (re-diff-or-close / keep-open / do-not-merge) |
| D-3 | BL-012 remainder — coverage threshold %, mutation-testing tool and scope for Python gate |
| D-4 | F-04 — authorize (or permanently waive) removal of stale checked-in `test-artifacts/*` evidence files, given the standing "never commit test-artifacts changes" invariant |
| D-5 | §43 targets — RBAC/audit-log/multi-node: schedule or formally re-scope as post-release |
| D-6 | COMP/COMP-3 byte-encoding certification approach (home-grown encoder vs reference oracle) — current disclosure must remain until decided |

---

## 10. Explicit Unknowns (§76.7.9)

- Docker/Java-gated behavior not re-executed **locally** during this audit (workstation limitation); covered by CI Linux at the audited SHA — local full-suite counts include documented skips (environmental).
- Mutation coverage of fail-closed paths: unknown (no mutation tooling) → F-05/D-3.
- Large-workload performance (§55): unmeasured.
- Historical PR branches (#1/#2/#3/#6) divergence not re-diffed (human decision D-2).
- Licensing posture re-verified only from Phase-5E historical evaluation, not re-audited today.

---

## 11. Test and CI Audit Summary (§76.5)

- **Inventory:** 200 pytest files / 3600 test functions (`tests/`), + 7 vitest files / 122 tests (frontend). Skips: 14 `skipif` definitions + 41 runtime `pytest.skip` calls, **all** Docker/Java/`RUN_DOCKER_TESTS`-environmental **except** the two masking skips in F-03. 0 `xfail`, 0 bare `@pytest.mark.skip`.
- **CI at audited SHA (`f3d0352`):** backend job **3857 passed, 0 failed, 0 skipped, 1 warning (1018.77s)**; capability-truth gate 54 files green; `phase1-ingestion` green; frontend green; supply-chain 3 jobs green (pip-audit/npm-audit **gating**, 0 `continue-on-error` anywhere). 4/4 runs `conclusion=success`, all head_sha = audited SHA.
- **Historical phase CI (re-verified today, authenticated):** Phases 0–9 exact SHAs — **all 10 GREEN (4 successful runs each, 0 failures)**. Phase 10/11 runs verified in their sessions (12/12, 8/8); Phase-11 docs commit `f3d0352` CI re-verified green today.
- **CI checks that are advisory/absent:** none found blocking-wise (no `continue-on-error`); absent = coverage/mutation/lint (F-05→BL-012/D-3).
- **Tested commit == audited commit:** yes (backend + gate jobs ran on `f3d0352`).
- **Stale/checked-in artifacts:** yes — F-04.
- **Local full-suite run:** executed this audit (counts appended below).

---

## 12. Final Project Verdict

> **PROJECT NOT COMPLETE.** All mandatory requirements are **not yet** verified: §71 has two FAIL items (Customer Approval Workflow not implemented — F-01; Documentation not synchronized — F-02), four backlog defects remain open with empirical evidence (BL-045 P1 reproduced, BL-046 P1 confirmed, BL-065 P2 confirmed, BL-066 P3 confirmed), and Phase 12 (full regression + fresh E2E + release gate) has not run.
>
> **What is solid:** Phases 0–11 are independently verified COMPLETE — every phase SHA re-checked against GitHub Actions today (Phases 0–9 all GREEN; 10/11 verified with exact-SHA CI), the audited SHA is fully GREEN (4/4 runs, 3857 backend tests / 122 frontend tests passing), the NO-LLM invariant holds everywhere (dependencies, workflows, scripts, code), the fail-closed evidence/verdict/proof architecture is real and gate-enforced, and the backlog contract (§77) holds — 78/90 FIXED, 4 open, none P0.
>
> **Gate check (user condition):** Phases 10 and 11 are independently verified complete → **Phase 12 implementation is unblocked.**

---

## 13. Next-Step Recommendation (§76.7.10)

1. File F-01/F-03/F-04 as backlog IDs (BL-091/BL-092/BL-093) and record Phase-12 assignments; ask for D-1 (approval-workflow scope) decision.
2. **Batch P0:** explicitly empty — state it, verify no new P0 (done in this audit).
3. **Batch P1:** BL-045 (red-first parity test → thread `called_programs` through the six recursion sites) + BL-046 (reuse canonical escape helper, lane-parity test) + F-01 if D-1 provided (else carry with explicit acceptance).
4. **Batch P2:** BL-065 (reachability red test → fail-closed), F-02 docs sync (README wording, 5 stale OPEN sections, CODE_AUDIT counts, capability reconciliation), F-03 (convert masking skips to failures), BL-012 remainder per D-3.
5. **Batch P3:** BL-066 (structured reason mapping), F-04 per D-4, F-05 metadata pass.
6. Phase-level close: full regression + fresh E2E (§50), §71 re-score, §53 13-point verdict, `opencode.md` + `BACKLOG.md` change-log updates → `PHASE 12 COMPLETE — VERIFIED` only if all 13 criteria pass.

---

*Prepared strictly from repository evidence at `f3d0352812eaa6314f39384a78189d6a20151c8a`. All line numbers verified by direct read/grep in this session. No test output, commit, or CI claim is fabricated; environment-limited conclusions are labeled as such (§76.7).*
