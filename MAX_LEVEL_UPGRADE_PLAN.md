# Max-Level Upgrade Plan — Universal, Runtime-Proven, Business-Equivalent

**Date:** 2026-10-28  
**Repository:** `Shankar373/Cobol-Java-Transformation` (SystemaOps)  
**Branch:** `codex/universal-core` (no commit/push performed)  
**Status:** Plan + capacity audit. No code changes are made by this document.

---

## 1. Direct answer to "can we upgrade each file to max level?"

**Yes — but only as a phased, evidence-gated program, not as a single pass.**

The repository is already an evidence-driven, fail-closed modernization platform with a frozen capability-truth gate, a 93-row backlog, and a file-level audit. "Max level" is therefore not a style pass; it is a **measurable maturity ladder** (Section 3). Every file can be raised, but the cost is dominated by (a) COBOL language/platform coverage that does not yet exist, (b) runtime proof lanes that require new Docker images and fixtures, and (c) enterprise-operability work that is explicitly deferred by decision (D-2…D-6). Attempting to "upgrade all files at once" would destroy the fail-closed discipline that makes the existing proofs trustworthy.

**Recommended posture:** treat this as a **program of 7 waves** (Section 5), each ending in a green CI + evidence update, starting with Wave 0 (hygiene + commit) before any feature work.

---

## 2. Capacity audit — what the repository can do today

### 2.1 Size and test capacity

| Metric | Value |
|---|---:|
| Production/test source files (`.py/.ts/.tsx/.java/.cob/.md/.yml/.json/.sh`) | 1,004 |
| Lines of code/docs/config | 208,929 |
| Python files | 438 |
| Java files | 225 |
| COBOL fixtures | 79 |
| Backend test files | 250 |
| Frontend test files | 16 |
| Backend tests collected (`pytest --collect-only`, excluding `tmp/`, `test-artifacts/`) | 4,467 |
| Frontend tests (Vitest) | 172 passing |
| TypeScript compile (`tsc --noEmit`) | clean |
| Production build (`npm run build`) | clean |

### 2.2 Capability capacity (source of truth: `docs/CAPABILITY_MATRIX.md`)

| Tier | Constructs |
|---|---|
| **Supported (oracle/proof-backed subset)** | MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF/ELSE, PERFORM (plain/UNTIL/TIMES/VARYING), STRING, UNSTRING (subset), DISPLAY, STOP RUN, EXIT PROGRAM, READ (AT END/NOT AT END), WRITE, OPEN/CLOSE (sequential), static resolved CALL (value-result proven), ROUNDED (HALF_UP), figurative constants, VALUE/ALL fill, PIC X/9/S/V value semantics, COPY + COPY REPLACING (operand subset), hierarchical working storage, JCL parse/link (structural) |
| **Partial / not certified** | COMP/COMP-1/2/3/5 (value semantics only; byte encoding unverified, D-6), indexed/relative files (emulated lanes), DB2/SQL (parse/analyze/harness), UNSTRING breadth, PERFORM THRU (bounded), JCL central status (never PROVEN) |
| **Unsupported (fail-closed with diagnostics)** | GO TO, GOBACK (transform target), SORT, MERGE, INSPECT, SEARCH, SET, ALTER, ACCEPT, INITIALIZE, NEXT SENTENCE, ON SIZE ERROR, `**`/FUNCTION, standalone REWRITE/DELETE/START, INVALID KEY (program UNSUPPORTED), EXEC SQL/EXEC CICS constructs, EXEC DLI/MQI (classification), dynamic/unresolved CALL, CALL BY VALUE/BY CONTENT (negative contract) |
| **Unknown / unverified** | REDEFINES, OCCURS, 88-level lowering (mapped Java does not compile — never SUPPORTED), nested programs/ENTRY, standalone REPLACE, fixed/free-format + dialect breadth, conditional compilation |

### 2.3 Runtime-proof capacity (`docs/verification/RUNTIME_PROOF_MATRIX.md`)

| Label | Count | Meaning |
|---|---:|---|
| PROVEN | 21 | Generated/hand-written candidate executed in Docker and byte-compared to GnuCOBOL oracle |
| PARTIAL | 12 | Machinery proven with prewritten candidates or structural-only |
| UNSUPPORTED | 4 | Fail-closed, diagnostic named |
| UNAVAILABLE | 6 | Requires a runtime/dependency not present |
| UNKNOWN | 8 | Not yet measured |

### 2.4 Backlog and audit capacity

| Source | OPEN | FIXED/KNOWN |
|---|---:|---:|
| `docs/BACKLOG.md` | 63 | 283 |
| `docs/FILE_LEVEL_AUDIT.md` (markers) | 9 OPEN + 25 KNOWN | 11 FIXED this session |
| File-level audit severity markers | 75 HIGH, 217 MEDIUM, 202 LOW | — |

### 2.5 Platform/runtime capacity

| Target | Project structure | Build | Execution lane | Proof status |
|---|---|---|---|---|
| `spring_boot` | Maven (Spring Boot 3.2.5, offline-pinned) | Docker Maven | `DockerSpringBootCandidateAdapter` | PROVEN for proven workloads (default lane) |
| `plain_java` | Dependency-free Maven jar | same | `MavenProjectCandidateAdapter` | Build lane exists; narrower runtime proof |
| `jakarta_ee` | Maven pom, zero deps, `com.modernized.app.jakarta` | same | `MavenProjectCandidateAdapter` | Generation profile only; no app-server runtime proof (honest non-claim) |

### 2.6 Enterprise-operability capacity (disclosed gaps, D-level decisions)

- Single shared bearer token, no RBAC, no audit log.
- SQLite single-node, in-process job threads.
- Containers run as non-root now (BL-135), but root-in-sandbox history documented.
- No coverage/mutation gates yet (D-3).
- No Gradle/Quarkus/Micronaut targets (non-goals until business demand).
- No real DB2/CICS/MQ/IMS/JCL behavioural lanes.

---

## 3. "Max level" definition — the maturity ladder

Every production file is graded L0→L5. "Max level" means reaching the highest level **justified by evidence**, never by assertion.

| Level | Name | Evidence required |
|---|---|---|
| L0 | Exists | File present, compiles/imports |
| L1 | Documented & typed | Docstring, type hints, contract stated |
| L2 | Unit-tested | ≥1 focused test, no skips masking failures |
| L3 | Integration-tested | Cross-module test, error paths covered |
| L4 | Runtime-proven | Docker lane executed, oracle-compared where applicable |
| L5 | Business-equivalence proven | Sealed evidence manifest, verdict VERIFIED, negative mutation retained, byte-deterministic output |

**Rule (from Master README §14/§40/§53):** a file/construct may not be labelled above the level its tests actually reach. `UNKNOWN is not PASS`. Compilation is not equivalence.

---

## 4. What "universal + business equivalence" actually requires

To move from "certified subset" to "universal", the following must each become L5:

1. **Language completeness** — every COBOL verb and data declaration in the ISO/IBM dialects the product claims.
2. **Storage fidelity** — COMP/COMP-1…5 byte encoding round-trips vs. GnuCOBOL (and, eventually, a z/OS reference oracle; today GnuCOBOL is the documented, non-z/OS oracle).
3. **File/VSAM semantics** — indexed/relative beyond the certified subset, ALTERNATE RECORD KEY, REWRITE/DELETE/START, INVALID KEY, byte-identical file images (today: emulated store, no VSAM image equivalence claimed).
4. **Embedded platforms** — EXEC SQL/DB2, EXEC CICS, MQ, IMS, JCL behavioural execution lanes.
5. **Data redefinition** — REDEFINES, OCCURS, 88-level lowering producing compiling Java.
6. **Control flow** — GO TO, PERFORM THRU, nested programs, ENTRY, ALTER, SORT/MERGE.
7. **I/O & ACCEPT** — ACCEPT, INITIALIZE, date/time, concurrency controls.
8. **Java target breadth** — plain_java and jakarta_ee runtime proof; servlet target if business demand.
9. **Per-program proof** — dependency proof beyond workload scope (evidence-model extension).
10. **Enterprise operability** — RBAC, audit log, durable queue, multi-node, coverage/mutation gates.

None of (1)–(10) can be done by editing "each file" in isolation; each requires **new tests + new evidence**. That is the plan's organizing principle.

---

## 5. Phased plan (7 waves)

Each wave ends with: (a) all touched tests green, (b) `RUNTIME_PROOF_MATRIX.md` / `CAPABILITY_MATRIX.md` updated only where evidence exists, (c) `docs/BACKLOG.md` rows updated, (d) CI green at the exact SHA.

### Wave 0 — Baseline, hygiene, and commit (R-1) — *start here*

**Goal:** make the current working tree the new, CI-validated baseline before any feature work.

| Task | Files | Acceptance |
|---|---|---|
| Commit the in-flight changeset + BL-094…BL-097 as one non-force commit (owner authorization required) | working tree | Single commit on `codex/universal-core` |
| Run full CI at that SHA | `.github/workflows/ci.yml`, `supply-chain.yml` | 4/4 jobs green |
| Reconcile untracked `test-artifacts/*` (D-4 decision) | `test-artifacts/` | Either gitignored or removed; never staged by default |
| Stabilize the 10 historical full-suite test-expectation contradictions | `tests/integration/test_call_passing_modes_runtime_proof.py`, `tests/test_copybook_capability_transitivity.py` | Already corrected in working tree; verify CI |
| Fix the remaining HIGH file-audit items that are pure correctness, no design decisions | `api/app.py` (seal TOCTOU verify-then-read), `api/service.py` (lost update on `update_application`, terminal-state guarantees), `api/store.py` (WAL/busy_timeout, guards) | Red-first tests + green |

**Exit gate:** CI green at exact SHA; `opencode.md` checkpoint updated with junit counts.

### Wave 1 — Core statement completion (L2→L4)

**Goal:** move the most common unsupported verbs to SUPPORTED with oracle proof.

| Construct | Work | Files | Proof |
|---|---|---|---|
| ACCEPT | Add statement IR, parser handler, Java lowering, semantic capability registry entry | `engine/transformation/cobol_parser.py`, `source_model.py`, `semantic_capability.py`, codegen | GnuCOBOL oracle differential test |
| INITIALIZE | Same pipeline; figurative/numeric fill rules | same family | oracle test |
| ON SIZE ERROR | Remove from expression → named diagnostic → optionally implement arithmetic overflow handling | `numeric_semantics.py`, parser | oracle test |
| INSPECT | TALLYING/REPLACING/CONVERTING | new parser + IR + codegen | oracle test |
| SEARCH / SEARCH ALL | table search | parser + IR + codegen | oracle test |
| SET | condition-name / index manipulation | parser + IR | oracle test |
| SORT / MERGE | INPUT/OUTPUT PROCEDURE, USING/GIVING | new module | oracle test |
| NEXT SENTENCE | control-flow lowering | parser | oracle test |
| ALTER | (gated; likely non-goal unless business demand) | — | — |

**Exit gate:** each construct moves from UNSUPPORTED to SUPPORTED only after a green Docker differential test is added to `tests/integration/` and `RUNTIME_PROOF_MATRIX.md`.

### Wave 2 — Data structures and lowering (L3→L5)

**Goal:** make REDEFINES/OCCURS/88-level produce compiling, equivalent Java.

| Task | Files | Proof |
|---|---|---|
| REDEFINES memory overlay model | `ir.py`, codegen, `numeric_semantics.py` | oracle byte test |
| OCCURS (fixed + DEPENDING ON) | parser, IR, codegen | oracle test |
| 88-level condition-name lowering fix (currently non-compiling) | `source_model.py`, codegen | compile + oracle |
| Nested programs / ENTRY | parser, CALL threading | oracle |
| Standalone REPLACE | preprocessor | oracle |
| Fixed/free format + dialect breadth | parser, `cobol_coverage_registry.json` | parser tests |

**Exit gate:** `test_level88_lowering.py`-style suites green; mapped Java compiles in Docker Maven for a boundary matrix.

### Wave 3 — File/VSAM and indexed/relative expansion (L4→L5)

**Goal:** expand the certified indexed/relative subset and add REWRITE/DELETE/START + INVALID KEY.

| Task | Files | Proof |
|---|---|---|
| REWRITE/DELETE/START statements | parser, IR, runtime adapter, candidate Java | oracle |
| INVALID KEY handling | parser + runtime | oracle |
| ALTERNATE RECORD KEY | indexed store emulation | oracle (emulation honestly labelled) |
| COMP/COMP-3 byte encoding certification (D-6 decision first) | `numeric_semantics.py`, new encoder | differential byte tests vs GnuCOBOL fixtures |

**Exit gate:** `RUNTIME_PROOF_MATRIX.md` rows updated with generated-Java evidence; D-6 decision recorded in `docs/decisions/`.

### Wave 4 — Embedded platforms (L2→L4)

**Goal:** behavioural lanes for DB2, CICS, MQ, IMS, JCL.

| Task | Prerequisite | Proof |
|---|---|---|
| JCL behavioural execution lane (exit codes, dataset outputs) | deterministic step runner | integration lane mirroring COBOL oracle |
| DB2 lane (SQLite harness is explicitly not DB2; need real DB2 container or honest scope reduction) | digest-pinned DB2 image or decision to keep harness-labelled | differential |
| CICS generation→execution | app-server runtime lane | differential |
| MQ/IMS detection→execution | runtime images | differential |

**Exit gate:** honest labels; never claim z/OS equivalence (GnuCOBOL-scoped only).

### Wave 5 — Java target runtime proof (L3→L5)

**Goal:** convert plain_java and jakarta_ee from build-lane to runtime-proven.

| Task | Files | Proof |
|---|---|---|
| plain_java per-workload runtime proof | `runtime_adapters.py`, `MavenProjectCandidateAdapter` | Docker differential |
| jakarta_ee runtime lane (Open Liberty/WildFly digest-pinned image) | new adapter + image | differential |
| Servlet WAR target (P2) | new adapter | differential |
| Gradle (P4, only on business demand + pinned distribution) | build adapter | differential |

### Wave 6 — Enterprise operability and quality gates (L3→L5)

**Goal:** close the §43 and D-3/D-5 gaps.

| Task | Files | Proof |
|---|---|---|
| RBAC + audit log + durable queue + multi-node | `api/app.py`, `store.py`, service | adversarial suites |
| Per-program dependency proof channel | evidence model extension | unit + Docker |
| Coverage + mutation gates (D-3) | CI, `ci.yml` | CI green |
| Per-application concurrency guards, WAL, retention/GC | `api/store.py`, `service.py`, `paths.py` | stress tests |

---

## 6. How to start (concrete, this week)

1. **Read first (no code):** `MASTER_IMPLEMENTATION_README.md` §8/§14/§40/§53/§76/§77, `docs/CAPABILITY_MATRIX.md`, `docs/verification/RUNTIME_PROOF_MATRIX.md`, `docs/BACKLOG.md`, `docs/FILE_LEVEL_AUDIT.md` Section A.
2. **Confirm Docker is available** (`docker version`, `RUN_DOCKER_TESTS=1`); the audit found it is available on this host. Without it no L4/L5 claim can be made (A.5).
3. **Get owner authorization for Wave 0 commit** (R-1) — all current work is uncommitted by design.
4. **Run the exact CI selection locally** before touching anything:
   - `python -m pytest -q tests` (with `RUN_DOCKER_TESTS=1` if Docker present)
   - `cd frontend && npm run test && npx tsc --noEmit && npm run build`
5. **Pick ONE construct per Wave 1 iteration** (e.g., ACCEPT) and do it red-first: failing test → parser IR → codegen → Docker oracle test → matrix update. Never batch multiple verbs in one PR (capability-truth gate + reviewability).
6. **Record decisions** (D-2/D-3/D-5/D-6) in `docs/decisions/` before implementing the affected waves; the project explicitly forbids silently choosing them.
7. **Update `docs/BACKLOG.md`** with new BL rows for every change (§77 contract).
8. **Update `docs/verification/RUNTIME_PROOF_MATRIX.md`** only when a Docker lane is green; never on unit tests alone.
9. **Keep the no-LLM invariant** (re-verified: 0 model-provider packages/keys/endpoints) — any "AI-assisted" feature is out of scope.
10. **Measure, don't claim:** use the §3 ladder and the integrated-proof gate (`evaluate_central_status`) which can only downgrade.

---

## 7. Risks and blockers

| Risk | Mitigation |
|---|---|
| Scope explosion ("universal" is unbounded) | Freeze the claim set: only constructs with a GnuCOBOL oracle test may be labelled SUPPORTED |
| z/OS equivalence overclaim | Documented non-claim; GnuCOBOL 3.1.2 is the oracle; z/OS reference oracle would be a separate, funded workstream |
| Uncommitted working tree | Wave 0 first; CI at exact SHA is the only valid baseline |
| D-level decisions (D-2…D-6) block Waves 3/4/6 | Get explicit owner decisions before those waves; do not implement by assumption |
| COMP/COMP-3 byte encoding (D-6) may be infeasible without a reference oracle | Keep value-semantics-only label honest if so |
| Test suite runtime (~90 min full Docker run) | Use focused selections per construct; full suite only at wave boundaries |
| Single-node SQLite/in-process jobs | Do not scale horizontally until Wave 6 |

---

## 8. Success metrics (how we know "max level" is reached)

- **Language:** `CAPABILITY_MATRIX.md` SUPPORTED row covers every verb in `cobol_coverage_registry.json` that the product claims; UNSUPPORTED rows all have named diagnostics + tests.
- **Runtime proof:** every SUPPORTED construct has a PROVEN row in `RUNTIME_PROOF_MATRIX.md` with a cited test module and exact command.
- **Business equivalence:** every PROVEN workload has a VERIFIED verdict with a sealed evidence manifest and at least one negative mutation test.
- **Determinism:** byte-identical generated output across repeated runs (already pinned by in-tree test).
- **Quality gates:** coverage + mutation thresholds enforced in CI (D-3 decided).
- **Security:** release-gate checkbox 14 upgraded (RBAC/audit/multi-node per decided scope).
- **Honesty:** `evaluate_central_status` never reports VERIFIED for any workload whose dependency is not PROVEN; FILE deps require compared file artifacts (already enforced, EV-006/R9).

---

## 9. What this plan deliberately does NOT do

- Does not rewrite historical reports (§78 — history preserved, labelled).
- Does not claim universal COBOL support, z/OS equivalence, or production readiness.
- Does not introduce LLM/AI dependencies (prohibited, re-verified: 0 model-provider packages/keys/endpoints).
- Does not merge to `main` or push.
- Does not close D-level decisions without owner input.

---

## 10. Immediate next command

```text
# 1. Confirm baseline
git status && git log --oneline -5
# 2. Confirm toolchain
docker version && python --version && java -version 2>&1 | head -1 && node --version && mvn -version | head -1
# 3. Confirm Docker proof lane is runnable
RUN_DOCKER_TESTS=1 python -m pytest -q tests/test_numeric_oracle_proof.py 2>&1 | tail -5
```

Then proceed to Wave 0, task 1 (owner-authorized commit).
