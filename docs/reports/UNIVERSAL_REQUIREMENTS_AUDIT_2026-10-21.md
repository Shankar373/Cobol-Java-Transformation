# Universal Requirements Audit — Master README §76/§80 Deliverable

**Audit type:** evidence-backed, audit-first (§76) + explicitly authorized implementation (§80 second stage)
**Verified commit:** `6145e892e95282a0ca85eb678057a0ea9890389c` (branch `codex/universal-core`)
**Audit date:** 2026-10-21
**Working tree at audit start:** 39 uncommitted entries (in-flight BL-094…BL-097 changeset — preserved intact, never staged)
**Runtime environment:** Python 3.11.9, Node 20.20.2, Java 21.0.12, Docker 29.8.2, GnuCOBOL image available
**Scope:** `MASTER_IMPLEMENTATION_README.md` §1–§80 + `docs/REQUIREMENTS.md` (constraints) + `contracts/*.md` vs. actual code/tests

> Per §76 the audit was performed read-only first. This document is the preserved
> remediation baseline; implementation follows it in separately identified batches.

---

## 1. Baseline and method

| Item | Value |
| --- | --- |
| Repository / branch | `Shankar373/Cobol-Java-Transformation`, `codex/universal-core` |
| HEAD | `6145e89` (docs checkpoint commit) |
| Prior CI evidence | runs 38980053986 / 38980054137 at `6145e89` = success (recorded in `opencode.md:10-11`) |
| Test surfaces | 212 collected test files, ≈3943 tests (backend), 143 frontend vitest |
| Audit method | 5 parallel read-only code-audit passes (pipeline wiring, semantic/mainframe coverage, frontend↔backend contract, security/trust/no-LLM, documentation/backlog), then independent line-level verification of every P1 finding by the primary auditor |

Verification status is stated per finding: **VERIFIED** = line-level confirmed by direct
read during this audit; **REPORTED** = produced by a audit pass and still to be
re-confirmed at fix time.

---

## 2. Architecture / data-flow map (real entry points)

```text
POST /applications/{id}/ingest   api/app.py:477 → Service.ingest_application  api/service.py:452
  → api/ingestion.py:105 ingest_zip → application_discovery.py:128 discover
POST /applications/{id}/modernize api/app.py:453 → service.py:632 → _modernize_background :698
  → _generate_application :925 → modernization/pipeline.py:229 execute (phases 1-5)
      capability_analyzer.py:315 → transformation_plan.py:125 → application_generator.py:71
      → runtime_adapters.py:479 (fail-closed target resolution)
  → _run_validation :1041 → engine/pipeline.py:513 run (phases 6-11)
      oracle/docker_adapter.py:278 execute → candidate/docker_spring_boot_adapter.py:313 compile / :465 execute
      → comparators/framework.py:109 compare → evidence/integrity.py:123 validate
      → verdict/derivation.py:374 derive → store.py:452 persist
GET  /runs/{id}, /detail, /artifacts, /verdict, /report, /integrated-proof, /approval, /download
      api/app.py:541-824 → frontend/src/api/client.ts → ModernizationRun.tsx / ApprovalPanel.tsx
```

**Wiring verdict:** the canonical pipeline is genuinely wired end-to-end and fail-closed
(no stage is a stub). One E2E test proves the real path (`tests/test_e2e.py:84-139`:
ingest → build → oracle → compare → evidence → `VERIFIED`).

---

## 3. Findings matrix

Severity follows §77: **P0** = false VERIFIED / trust-boundary bypass / semantic corruption;
**P1** = major capability or security weakness blocking release; **P2** = coverage,
quality-gate or documentation gap; **P3** = low-risk improvement.

### P0

None opened. The verdict path was re-audited and remains fail-closed
(`engine/verdict/derivation.py:265` is the single `VERIFIED` site, guarded at
`:219-233`, `:256-259`, `:282-309`; integrity violations clamp at `:146-182` applied by
`engine/pipeline.py:653-657`). No `SKIPPED→PASS`, `UNKNOWN→VERIFIED`, or hard-coded
`VERIFIED` exists (repo grep = 0 hits).

### P1 — implementation required

| ID | Finding | Evidence | Status |
| --- | --- | --- | --- |
| A-01 | Reference producer container runs with **no isolation flags** (no `--network none`, no memory/cpu/pid caps, read-write bind mount, no cleanup on timeout) — violates §34 for every container | `engine/transformation/producers/opensource4j.py:124-134` (mount `:127` read-write, `timeout=120` `:133`) | **VERIFIED** |
| A-02 | Control-plane auth is **opt-in and off by default**; only `scripts/deploy/start-production.sh` refuses unauthenticated start — compose/Dockerfile production paths do not enforce it | `api/app.py:192-201` (`token is None` ⇒ skip), `docker-compose.production.yml`, `Dockerfile.production` | **VERIFIED** (code) / deployment enforcement REPORTED |
| A-03 | Candidate **environment identity asserts `network_policy="none"` unconditionally**, including the host `RealJavaCandidateAdapter` lane ⇒ evidence claims isolation that was not measured (§34/§76.4) | `engine/pipeline.py:619` (oracle) and `:625` (candidate), host lane selected at `:156-160` | **VERIFIED** |
| A-04 | `contracts/VERDICT_CONTRACT.md:104,119` require a mutation-validation precondition for certification; **no implementing code exists** (`engine/verdict/derivation.py:184-271`, grep `mutation_validation` = 0) | contract vs. code | REPORTED |
| A-05 | `contracts/TRANSFORMATION_PRODUCER_CONTRACT.md:93-99` require capping verdict at `UNAVAILABLE` for non-regenerating producers; field exists (`engine/contracts/models.py:172,178`) but derivation never reads it | contract vs. code | REPORTED |
| A-06 | **Three-way capability truth drift** on indexed/relative files, `REWRITE`, `START`: `docs/CAPABILITY_MATRIX.md:19` "Transform path: No (rejected)" vs `docs/cobol_coverage_registry.json:1` "runtime=SUPPORTED" vs code which implements them (`cobol_to_java_mapping.py:2397,2425`, `file_io_support_template.py:184,218,245`) while the authoritative analyzer registry marks the enabling SELECT clause unsupported (`semantic_capability.py:237`) | three sources | REPORTED (code lines plausible; reconcile at fix) |
| A-07 | Frontend **swallows 401** ⇒ with `CONTROL_PLANE_API_TOKEN` set and no token the whole UI silently shows "persistent history is unavailable"; no UI surface exists to set a token | `frontend/src/App.tsx:84-85`, `frontend/src/pages/Dashboard.tsx:119-122`, `client.ts:70` (`setApiToken` has no caller UI) | REPORTED |
| A-08 | `docs/KNOWN_ISSUES.md:14,18` declare **open P0** items while `opencode.md:169` declares "P0: explicitly empty" and the register's only OPEN row is P3 | doc vs doc | REPORTED |

### P2 — implementation required

| ID | Finding | Evidence | Status |
| --- | --- | --- | --- |
| B-01 | Multipart upload collision check is **case-sensitive** while the ZIP path casefolds ⇒ `A.cob` + `a.cob` both pass and silently overwrite on Windows (inconsistent with BL-097) | `api/service.py:560-571` vs `api/ingestion.py:151` | **VERIFIED** |
| B-02 | No **compression-ratio** guard on ZIP ingest (zip-bomb); bounded only indirectly (50 MB in / 200 MB out) | `api/ingestion.py:116-165`; repo grep `compress_size` = 0 | **VERIFIED** |
| B-03 | `_guard_content_length` silently returns on missing/non-numeric `Content-Length` and is **never called** by JSON routes (`POST /applications`, `/modernize`, `/approval`) ⇒ chunked oversized JSON is buffered unbounded | `api/app.py:254-258`, routes `:387`, `:453`, `:601` | REPORTED |
| B-04 | **422 response-shape mismatch**: FastAPI validation `detail` is an array; client types it `string` ⇒ rendered `"[object Object]"` | `frontend/src/api/client.ts:333` and `:577` vs `api/app.py:614,617` | **VERIFIED** (client) |
| B-05 | `discovery_success` / `discovery_errors` returned by the API but **never typed or read** by the frontend ⇒ partial discovery renders as success (silent data-quality loss) | `api/models.py:257-258`, `api/ingestion.py:254-258,291-295` vs `client.ts:152-162` | REPORTED |
| B-06 | **§16 no-silent-loss violated**: `LOCAL-STORAGE` section and the `REPLACE` directive are neither parsed nor diagnosed anywhere in `engine/` (0 matches), and neither has a registry row | `engine/**` grep `LOCAL-STORAGE` = 0 | **VERIFIED** |
| B-07 | JCL / CICS / DB2 "transform path" results are computed in memory but **never written into `java_candidate_path`**, so no generated artifact for those lanes is ever built or compared | `engine/transformation/jcl_consumer.py:88-165`, `api/service.py:221-224` vs `service.py:1018-1021` | REPORTED |
| B-08 | Registry claims contradicted by code: "COPY REPLACING unimplemented" (`copybook_model.py:500,606` implements it), "IMS/MQ/utilities no detection patterns" (`semantic_capability.py:440-450` has them), "USAGE silently ignored, no diagnostic" (`cobol_parser.py:358-363` emits one) | registry vs code | REPORTED |
| B-09 | `contracts/JAVA_CANDIDATE_CONTRACT.md:27-29` forbids `pom.xml`; the shipped Spring/Maven lane emits one (`spring_boot_generator.py:152,217-220`) — no V2 contract, **and no backlog row** (§77 violation) | contract vs code | REPORTED |
| B-10 | **No time-based evidence staleness** enforcement (only generation-based staleness exists) despite §42 "stale evidence protection" | `engine/verdict/derivation.py:354`, `engine/evidence/integrity.py:177` record timestamps; no TTL comparison | REPORTED |
| B-11 | **No rate limiting** anywhere (only the concurrency-slot 429); no `limit_req` in nginx | grep `rate_limit\|limit_req\|slowapi` = 0 | REPORTED |
| B-12 | **No run cancellation / retry / whole-run deadline**; only per-step Docker timeouts | `api/service.py:406-419` daemon threads; grep cancel/retry in `api/` = message text only | REPORTED |
| B-13 | Duplicate/orphan planners + assembler called only by tests (violates §9 "one canonical pipeline") | `engine/modernization/modernization_planner.py:333,360`, `application_assembler.py:34` | REPORTED |
| B-14 | Dead backend routes / unreachable features: `POST /applications/{id}/upload`, `POST /runs/{id}/validate`, `GET /health`, `GET /applications/{id}` have no UI caller | `api/app.py:419,624,824,406` vs `frontend/src` | REPORTED |
| B-15 | Upload size cap discovered only **after** the application row is created ⇒ orphaned "NO SOURCE" apps | `frontend/src/App.tsx:142` then `:151`, backend 413 at `app.py:286-289` | REPORTED |
| B-16 | Documented-but-unenforced: no RBAC / tenant isolation / tamper-evident audit log (§43 future items — must not be claimed present) | `api/app.py:608-610` (approver = recorded input) | REPORTED |

### P3 — opportunistic

| ID | Finding | Evidence |
| --- | --- | --- |
| C-01 | `source_root` computed but never used | `api/service.py:477` |
| C-02 | Discovery executed twice per ingest when JCL+COBOL exist | `api/ingestion.py:213-214`, `:281-282` |
| C-03 | `producer_capabilities` parameter stored, never read | `capability_analyzer.py:311` |
| C-04 | `GET /discovery` recomputes on every call instead of returning the ingest-time snapshot | `api/app.py:519-520` |
| C-05 | Unreachable legacy comparison lane (`workload is None` never true) | `engine/pipeline.py:681` |
| C-06 | Duplicate polling of the same run (2000 ms + 1500 ms) | `App.tsx:96-131`, `ModernizationRun.tsx:240-271` |
| C-07 | Download button not approval-gated ⇒ guaranteed first-attempt 409 | `ModernizationRun.tsx:768-772,812-817` vs `app.py:763-769` |
| C-08 | Certification-contract fields returned but not surfaced in UI | `app.py:663-664`, `client.ts:271-288` |
| C-09 | `target_runtime` (§32) absent from frontend types | `models.py:62` vs `client.ts:114-134` |
| C-10 | `engine/execution/docker_runner.py` dead code yet documents the control set | zero importers |
| C-11 | Oracle default image `:latest` (mitigated: digest enforced before execution) | `engine/oracle/adapter.py:47` vs `contracts/ORACLE_CONTRACT.md:37` |
| C-12 | Comparator defaults to `("crlf_to_lf",)` when contract demands explicit enumeration | `comparators/framework.py:248,305,433` vs `contracts/ARTIFACT_CONTRACT_SPEC.md:81` |

---

## 4. Requirement → code → test → evidence traceability (§76.3 summary)

| Requirement (§) | Implemented | Strongest demonstrated level | Key test |
| --- | --- | --- | --- |
| Ingestion + traversal limits (§11) | Yes | FRESH_VERIFIED (unit + adversarial) | `test_ingestion_diagnostics.py`, `test_zip_duplicate_entry_rejection.py`, `test_phase11_p1_upload_integrity.py` |
| Discovery / dependency graph (§12-13) | Yes | MODELED_ONLY + API exposure | `test_r11_discovery_robustness.py`, `test_external_dependency_edges.py` |
| Capability analysis (§14) | Yes | MODELED_ONLY (fail-closed planner) | `test_capability_registry_reconciliation.py` |
| Parser / IR (§16-17) | Partial, honest | PARSED_ONLY + diagnostics | `test_parser.py`, `test_ir.py`, `test_silent_loss_registry.py` |
| Numeric semantics (§18) | Partial, honest (`PARTIAL_SUPPORT` on COMP/COMP-3) | ORACLE_MATCHED for DISPLAY subset | `test_numeric_semantics.py`, `integration/test_numeric_oracle_proof.py` |
| Copybooks (§20) | Yes, fail-closed | FRESH_VERIFIED | `test_copybook_*`, `integration/test_copybook_runtime.py` |
| CALL (§21) | Yes, fail-closed | FRESH_VERIFIED | `test_call_resolution_truth.py`, `test_phase12_p1_bl045_*` |
| JCL (§23) | discovery/classification/IR yes; **runtime missing** | TRANSFORMED / fail-closed gate | `test_jcl_*`, `integration/test_jcl_spring_boot_compile.py` |
| DB2/SQL (§24) | discovery/translation yes; SQLite shim only | PARTIAL (shim ≠ DB2 equivalence) | `test_db2_*`, `integration/test_phase_d_negative_integration.py` |
| VSAM/Files (§25) | subset yes (indexed/relative runtime exists) | ORACLE_MATCHED subset | `integration/test_indexed_semantics.py`, `test_relative_semantics.py` |
| CICS (§26) | detection/mapping yes; **no runtime lane** | UNSUPPORTED fail-closed | `test_cics_*` |
| MQ (§27) | detection only | BLOCKED fail-closed | `test_ims_mq_detection.py` |
| IMS (§28) | detection only | BLOCKED fail-closed | `test_ims_mq_detection.py` |
| External utilities (§29) | detection only; **no dependency-ledger kind** | UNSUPPORTED fail-closed | `test_utilities_vsam_detection.py` |
| Evidence integrity (§38) | Yes | FRESH_VERIFIED + adversarial | `tests/evidence/*`, `tests/adversarial/*` |
| Verdict (§39) | Yes, fail-closed | FRESH_VERIFIED | `test_verdict_trust_boundary.py` |
| Approval workflow (§70) | Yes (BL-091) | API-level | `test_phase12_p4_bl091_approval_workflow.py` |
| Security §42 | See P1/P2 above | controls listed in §3 | `test_api_security.py` |
| No-LLM (§3/§79) | **PASS on every executable surface** | dependency + import scan | see §5 |

---

## 5. §79 No-LLM compliance gate — **PASS**

0 model-provider packages in `requirements.txt` (6 deps), `requirements.lock` (48 pins),
`frontend/package.json` + lockfile; 0 model API keys/endpoints in `.github/workflows/*`,
all Dockerfiles, `docker-compose*`, `deployment/`, `scripts/`; 0 model imports in
`engine/` + `api/`. All remaining LLM mentions are documentation describing the
prohibition (allowed by §79). **No remediation required.**

---

## 6. Proposed remediation batches (dependencies noted)

| Batch | Contents | Depends on | Regression risk |
| --- | --- | --- | --- |
| **R1 Security** | A-01 producer isolation, B-01 casefold collisions, B-02 compression ratio, B-03 JSON body guard, A-02 production auth enforcement | baseline test run | Low–medium (upload error paths) |
| **R2 Evidence honesty** | A-03 `network_policy` derived from the actual adapter, never asserted for host lane | R1 | Medium (evidence shape asserted by tests) |
| **R3 Frontend contract** | B-04 422 detail, A-07 401 surfacing + token entry, B-05 discovery errors, B-15 size hint, C-07 download gating | none | Low |
| **R4 No-silent-loss** | B-06 `LOCAL-STORAGE` + `REPLACE` explicit diagnostics, B-08 registry truth reconciliation, A-06 capability drift resolution | none | Medium (capability labels are test-asserted) |
| **R5 Contract gaps** | A-04/A-05/B-09 registered as backlog rows; implement or explicitly carry with owner decision | human decision | Low |
| **R6 Documentation** | §78 baseline notes, historical labels, KNOWN_ISSUES reconciliation, `opencode.md` checkpoint | all batches | None |

Items that cannot be honestly implemented without a product decision are **registered,
not faked** (§60/§61): B-10 time-based staleness policy, B-11 rate-limit policy,
B-12 cancellation semantics, B-16 RBAC/tenant/audit-log scope (§43 lists them as
future production requirements), MQ/IMS/utilities runtime lanes (§27/§28), JCL runtime
equivalence (§23).

---

## 7. Green-baseline protection (§63)

- Baseline recorded: HEAD `6145e89`, in-flight changeset preserved untouched, no staging, no commits.
- Per-file test evidence written to `test-artifacts/one-by-one/` (never staged — D-4/BL-093 invariant).
- Focused tests are run per file before and after each batch; the full per-file sweep is repeated after R1–R4.
- No test is deleted, weakened, or skipped; new coverage is added red-first.

## 8. Human decisions required

| ID | Decision | Blocking |
| --- | --- | --- |
| D-4 | `test-artifacts/*` cleanup authorization (BL-093, OPEN) | evidence hygiene |
| D-7 | Rate limiting + time-based staleness policy values | B-10, B-11 |
| D-8 | Cancellation/retry semantics for in-flight runs | B-12 |
| D-9 | RBAC/tenant/audit-log scope (§43) | B-16 |
| D-10 | JAVA_CANDIDATE contract V2 extension for the Maven/Spring lane | B-09 |

## 9. Explicit unknowns / not verifiable here

- Remote CI status for the audited SHA was read from the checkpoint record, not re-queried in this session.
- Whether `scripts/deploy/start-production.sh` is the only production entry path (deployment-side enforcement of A-02) requires a deployment environment to confirm.
- True DB2 equivalence (vs the SQLite shim) cannot be established without a DB2 runtime — labelled `PARTIAL` by design.

## 10. Next-step recommendation

Proceed to implementation batches R1 → R4 (each red-first, tests re-run file-by-file),
register R5 items in `docs/BACKLOG.md`, then synchronize documentation (R6) and update
`opencode.md` with actual results.

---

## 11. Verification addendum (2026-10-21, after the initial report)

Line-level confirmation performed by the primary auditor; these items move from
`REPORTED` to **VERIFIED**:

| ID | Confirmation |
| --- | --- |
| A-04 | `contracts/VERDICT_CONTRACT.md:119` ("Required mutation validation passed") and `:104` (mutation-gate failure) vs `engine/verdict/derivation.py` — the module contains only post-validation *tamper* detection (`:104`, `:127`), no mutation-validation gate. |
| A-05 | `contracts/TRANSFORMATION_PRODUCER_CONTRACT.md:85-99,121` require the `UNAVAILABLE` cap; `engine/contracts/models.py:172` declares `requires_mutation_regeneration: bool = True` and `:178` lists the manifest key — `derivation.py` never reads either. |
| B-07 | No `write_text`/`write_bytes`/`mkdir` anywhere in `engine/transformation/jcl*.py`, `cics*.py`, `sql*.py` — those lanes cannot materialize an artifact. |
| B-09 | `contracts/JAVA_CANDIDATE_CONTRACT.md:27` ("No build system - no `pom.xml`"), `:37` ("Deferred to V2"), `:119` (change control) confirmed against the shipped Spring/Maven lane. |
| B-13 | `ModernizationPlanner` has no caller except its own module body (`modernization_planner.py:337`) and the package re-export (`__init__.py:23`). |
| B-14 | `uploadFiles` (`client.ts:356`), `validateRun` (`:407`), `getHealth` (`:440`) are defined and never called anywhere under `frontend/src`. |
| B-01/B-02/B-03/B-04/B-06/A-01/A-02/A-03 | Verified during the audit itself (see §3). |

Still `REPORTED` (fix-time confirmation required): A-06/B-08 registry-vs-code detail,
A-07/B-05/B-15/B-16 frontend/deployment specifics, B-10/B-11/B-12 absence claims.
