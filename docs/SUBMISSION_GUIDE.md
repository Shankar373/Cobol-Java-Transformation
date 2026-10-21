# SystemaOps — Submission Guide

> **Verified commit:** `49821ad1e1d91845dee4ed04e46aa7ab009dcb71`
> (`codex/universal-core`, 2026-10-21). This guide is written against that
> exact tree and its exact-SHA CI results. It links to the repository's
> existing authoritative documents instead of restating them (Master README
> §78 authority hierarchy). Live state is tracked in `opencode.md`; defects
> and decisions in `docs/BACKLOG.md`.

## 1. Objective and architecture

**Objective:** understand a legacy COBOL application, deterministically
modernize it to Java, execute the result independently, compare behavior
against the original, preserve trustworthy evidence, and give the customer a
defensible modernization decision — with **no LLM in any lane**
(`MASTER_IMPLEMENTATION_README.md` §3, §79).

**Architecture (one paragraph):** a FastAPI control plane (`api/`) persists
state in SQLite and drives a background pipeline
(`engine/modernization/pipeline.py`): secure ZIP ingestion → application
discovery + dependency graph (`engine/transformation/application_discovery.py`) → capability
analysis (`engine/modernization/capability_analyzer.py`) → transformation plan
(`engine/modernization/transformation_plan.py`) → deterministic COBOL→Java mapping and generation
(`engine/transformation/cobol_parser.py`, `engine/transformation/cobol_to_java_mapping.py`, `engine/transformation/spring_boot_generator.py`)
→ digest-pinned Docker execution of the GnuCOBOL oracle and the Java
candidate (`engine/oracle/docker_adapter.py`,
`engine/candidate/docker_spring_boot_adapter.py`) → registry-driven artifact
comparison (`engine/comparators/framework.py`) → evidence-integrity
validation (`engine/evidence/integrity.py`) → fail-closed seven-state verdict
(`engine/verdict/derivation.py`) → approval-gated customer download. The
React SPA (`frontend/`) drives the same API. Detailed diagrams and module
rationale: `docs/ARCHITECTURE.md`.

## 2. Deterministic workflow

Every run moves through explicit stages (frontend + API agree on them:
`frontend/src/api/stages.ts` ↔ `api/models.py`):

```text
CREATED → DISCOVERING → ANALYZING → PLANNING → TRANSFORMING
        → ASSEMBLY_COMPLETED → EXECUTING_ORACLE → BUILDING
        → EXECUTING_GENERATED → COMPARING → VALIDATING_EVIDENCE
        → COMPLETED | FAILED
```

Fail-closed at every gate: unknown/unavailable is never PASS, a missing or
integrity-invalid evidence manifest can never produce `VERIFIED`, and
unsupported constructs surface as explicit diagnostics (README
"Verification principles"; `docs/KNOWN_ISSUES.md` reconciliation note).

## 3. Startup and demo instructions

Full verified commands, expected outputs, and troubleshooting live in
**`README.md` → "Quick Start (verified)"**. In short:

```bash
python -m pip install -r requirements.lock
python -m uvicorn api.app:app --port 8000        # backend, auth off by default

cd frontend && npm ci && npm run dev              # SPA on http://localhost:5173
```

For the Docker execution/oracle lanes, build the two pinned images and record
image provenance first (see Quick Start); then run the E2E proof:

```bash
RUN_DOCKER_TESTS=1 python -m pytest -q tests/test_e2e.py
```

## 4. Supported sample input and its verified output

**Input:** `fixtures/workload-arithmetic/cobol/ARITH.cob` — a compact,
representative program using `PIC 9(n)` fields, `COMPUTE`, `DIVIDE ... GIVING
... REMAINDER`, comparison conditions, and `DISPLAY`.

**Verified output (real GnuCOBOL 3.1.2 oracle, executed in Docker on
2026-10-21):**

```text
SUM=0015
DIFF=0005
PROD=00000050
QUOT=0002
REM=0000
A_GT_B=TRUE
A_EQ_B=FALSE
A_LT_B=FALSE
```

**Verified equivalence path:** the repository's Mode-B end-to-end test
(`tests/test_e2e.py::TestArithRealE2E`) uploads this COBOL plus the known-good
Java candidate, runs the full pipeline, and asserts: run stage `COMPLETED`,
verdict **`VERIFIED`**, `oracle_id == "gnucobol-3.1.2"`, `executed_check_count
>= 2`, every declared comparison result **`MATCH`**, and an
`evidence_manifest_hash` bound to the run. The generated-Java (Mode-A)
path is separately proven by
`tests/test_e2e.py::TestFileWorkloadThroughApi` against
`fixtures/workload-file-write-read` (per-workload status:
`docs/verification/RUNTIME_PROOF_MATRIX.md`).

## 5. Test and CI evidence

**Exact-SHA GitHub CI (authoritative; at `49821ad`, 2026-10-21) — 4/4 runs
successful, 14/14 jobs green:**

| Workflow | Event | Run |
|---|---|---|
| SystemaOps CI (4 jobs: capability truth gate, phase-1 ingestion, backend + Docker oracle, frontend tests/TS/build) | push | https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/39621938126 |
| Supply chain (SBOM + vulnerability scanning, 3 jobs) | push | https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/39621938124 |
| SystemaOps CI | pull_request (PR #2) | https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/39621946810 |
| Supply chain | pull_request (PR #2) | https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/39621946515 |

Workflow/job *conclusions* are read from the public GitHub API. **Per-job test
counts inside CI are not reported here**: CI job logs require repository admin
rights (API returns 403), and this guide does not invent numbers.

**Local evidence (this machine, WSL2 — distinct from CI):**

- Focused backend truth suites: `tests/test_silent_loss_registry.py` +
  `tests/test_ingestion_diagnostics.py` → **18 passed** (2026-10-21).
- End-to-end suite `tests/test_e2e.py` after provenance regeneration →
  arithmetic Mode-B **VERIFIED path passing**; file-workload Mode-A test
  **passed (22.7 s)**; all classes **6/6 passed when run in isolation**.
  Sequential full-file runs on this WSL2 host show intermittent
  Docker-load-related failures (see Troubleshooting) — Linux CI is the
  authoritative Docker environment.
- Backlog structural gate: `python tools/check_backlog_table.py` → **OK: 122
  rows, all 7 columns, unique ids**.

## 6. Supported COBOL subset and known limitations

The supported subset and evidence ladder rung for each construct are declared,
machine-readably, in `docs/cobol_coverage_registry.json`, summarized in
`docs/CAPABILITY_MATRIX.md`, and proven per workload in
`docs/verification/RUNTIME_PROOF_MATRIX.md`. Highlights:

- **Proven end-to-end (generated Java vs GnuCOBOL oracle):** sequential
  LINE SEQUENTIAL file write/read, arithmetic runtime lane, copybook runtime
  lane, CALL-chain runtime lane, numeric VALUE/literal oracle proof,
  `workload-integrated` COBOL↔Java lane (JCL lane unavailable → central
  `NOT_VERIFIED` by design).
- **Explicitly not claimed:** universal COBOL coverage; z/OS/mainframe
  equivalence; `COMP`/`COMP-3` byte-layout equivalence (PARTIAL); JCL, CICS,
  DB2, MQ, IMS artifact materialization (fail-closed, BL-116); indexed/relative
  *transformation* (runtime lane only, hand-written candidates).
- Known risks and open items: `docs/KNOWN_ISSUES.md`; central defect/decision
  register: `docs/BACKLOG.md`.

## 7. Security posture and deferred controls

**Present and enforced:** optional constant-time bearer-token auth
(`CONTROL_PLANE_API_TOKEN`; unset = auth off = documented dev default;
production compose refuses to start without it — BL-099), bounded request/file
bodies and file-count caps, ZIP traversal + zip-bomb ratio guards (BL-097,
BL-103), case-fold collision checks (BL-102), security headers, typed
fail-closed errors, container sandboxing (`--network none`, memory/CPU/pids
limits, digest-pinned images), approval-gated export (409 until `APPROVED`),
and evidence-integrity seals over artifact hashes.

**Deferred by explicit owner decision (documented, never claimed):** D-7 TTL
staleness + rate limiting (BL-113/114), D-8 cancellation/retry (BL-115), D-9
enterprise security scope — RBAC, tenant isolation, audit logging, external
secrets, TLS/egress, multi-node (BL-122), D-10 candidate-contract V2
consumption, D-11 mutation gate + producer capability cap (BL-111/112).
Full list: `docs/KNOWN_ISSUES.md` "Deferred production gaps (owner-approved
2026-10-21)". Security detail: `docs/security/PRODUCTION_SECURITY.md`.

## 8. Demo script

**API-level (fully scripted, the fastest honest demo):**

```bash
# 0. one-time for Docker lanes (repo root)
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .
python scripts/record_docker_image_provenance.py

# 1. backend
python -m pip install -r requirements.lock
python -m uvicorn api.app:app --port 8000

# 2. run the verified E2E in a second terminal
RUN_DOCKER_TESTS=1 python -m pytest -q tests/test_e2e.py::TestArithRealE2E -s
```

Expected: the test finishes `1 passed`; inside it the run reaches
`COMPLETED`, verdict `VERIFIED`, all comparisons `MATCH`.

**Browser walkthrough:**

1. `python -m uvicorn api.app:app --port 8000` and, in a second terminal,
   `cd frontend && npm run dev`.
2. Open `http://localhost:5173/app/` → Dashboard (shows run history; with
   auth off it loads without a token).
3. "New modernization" → name it → upload a ZIP containing a supported
   program (e.g. zip `fixtures/workload-arithmetic/cobol/`) → create.
   The UI runs create → ingest → modernize and streams the pipeline stages.
4. On the run page: watch discovery/analysis/plan/transform; when it reaches
   `COMPLETED`, open **Verdict** (state, oracle id, comparisons) and
   **Integrated proof**.
5. Download is **disabled with "awaiting approval"** until you submit
   `APPROVED` in the approval panel; after approval the button enables and
   `GET /runs/{id}/download` returns a ZIP (before approval: HTTP 409).
   Reject with a reason to see the rejected state reflected in the label.

**Negative-path demo (fail-closed behavior):** upload a program using an
unsupported construct (e.g. `INSPECT`) or a non-ZIP file — discovery/capability
report it explicitly and the run fails closed; nothing is silently accepted
(`tests/test_e2e.py::TestZipIngestionE2E::test_invalid_zip_rejected`).

## 9. Likely evaluator questions

| Question | Evidence-backed answer |
|---|---|
| Is an LLM used anywhere? | No. §79 scan over all executable surfaces (deps, workflows, scripts, frontend) is clean; transformation is deterministic code. Re-run: search the tree for model-provider packages. |
| Is this universal COBOL modernization? | No, and it never claims to be. A defined subset is proven end-to-end; everything else stays `UNKNOWN`/`UNSUPPORTED`/`PARTIAL` in `docs/cobol_coverage_registry.json`. |
| Can a verdict be wrong-but-green? | The single `VERIFIED` site (`engine/verdict/derivation.py:265`) sits behind evidence-integrity validation and a hash-locked consistency check; build failures cannot masquerade as execution evidence; missing evidence yields non-`VERIFIED` states. |
| How do you prove the Java matches the COBOL? | Independent execution: GnuCOBOL in Docker (digest-pinned) vs the candidate in a network-isolated container, declared artifacts compared by explicit comparator contracts, under a sealed evidence manifest. |
| Why is download gated? | Customer approval workflow (BL-091, D-1): export returns 409 until `APPROVED`; every UI entry point is disabled with an explanatory label (BL-119). |
| Production-ready? | No — honestly documented: `docs/KNOWN_ISSUES.md` + §70 gaps (durable queue, rate limits, RBAC/audit, TLS, multi-node) with owner-approved deferrals D-7…D-11. |
| Where is CI green? | Exact SHA `49821ad`: 4/4 workflow runs green (links in §5). Older runs/SHAs in historical reports are labeled historical (BL-009). |
| What happens without Docker? | Docker lanes report `UNAVAILABLE` and the run fails closed — never a fake pass (`RUN_DOCKER_TESTS=1` without Docker fails, rather than skips). |

## 10. Completion matrix (§71 release gate) and remaining blockers

Score at `49821ad` (2026-10-21 audit): **19 ✅ / 2 ⚠️ / 0 ❌**.

- ✅ Architecture, Discovery, Dependency graph, IR, Transformation, Runtime
  adapters, Java build, Candidate execution, Oracle execution, Differential
  comparison, Evidence integrity, Verdict, Regression suite, Fresh E2E, CI
  green, Documentation synchronized, Known limitations documented, Export,
  Customer approval workflow — verified against code + tests + exact-SHA CI.
- ⚠️ **COBOL semantic coverage validated** — validated *as a subset*; universal
  coverage is deliberately not claimed.
- ⚠️ **Security validation** — control-plane controls enforced; enterprise
  scope (RBAC/audit/TLS/rate-limit) deferred under D-9 and documented.

**Remaining blockers / open decisions (unchanged):**

- **BL-093** — stale tracked `test-artifacts/*` junit snapshots; blocked on
  human decision **D-4** (never staged without authorization).
- **D-7** TTL + rate limiting · **D-8** cancellation/retry · **D-9**
  enterprise security · **D-11** mutation gate + producer cap — all
  owner-approved deferrals with contract waiver references (BL-111/112/113/114/115/122).
- **BL-116** JCL/CICS/DB2 artifact materialization — fail-closed today;
  materialize-vs-analysis-only decision deferred.
- **BL-012** coverage/mutation thresholds; **BL-013/014/015/016** stale-PR
  dispositions (owner decisions); **BL-010** Linux-CI-only Docker E2E claim.

**Submission readiness:** the repository is ready to submit **as a
deterministic, evidence-driven prototype** for the supported subset, with the
above limitations documented rather than hidden. It is **not** a claim of
universal COBOL coverage or enterprise certification.
