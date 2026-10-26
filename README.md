# Cobol-Java-Transformation

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

**SystemaOps deterministic COBOL to Java modernization and verification platform.**

> HISTORICAL SNAPSHOT (dated 2026-10-10, BL-009): baseline at that time
> fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4 on codex/universal-core; CI at that
> time: Push CI #417 GREEN, PR CI #418 GREEN — NOT current. The live verified
> SHA and its CI runs are recorded in `opencode.md` and `docs/BACKLOG.md`.
> Older CI run IDs (e.g. #306) and SHAs (e.g. 90efdca) are historical provenance only.
>
> This repository contains a working deterministic modernization pipeline, execution and
> verification infrastructure, FastAPI control plane, React frontend, Docker-backed runtime
> and oracle path, evidence integrity, and verdict derivation.
>
> The project does not use an LLM for transformation decisions. Semantic transformation is
> deterministic and fail-closed.

## Current project statement

The project modernizes a defined, supported subset of COBOL workloads into Java and provides
execution/evidence infrastructure to compare source and candidate behavior.

This is not a claim of universal COBOL compatibility. Unsupported, partial, unavailable, or
unproven constructs remain explicitly identified.

## Current pipeline

COBOL ZIP -> secure ingestion -> discovery -> dependency analysis -> semantic IR ->
capability analysis -> transformation plan -> deterministic COBOL to Java mapping ->
Java generation -> Docker Java execution and GnuCOBOL oracle execution -> artifact capture ->
comparison -> evidence integrity -> deterministic verdict -> FastAPI control plane -> React UI.

## Quick Start (verified 2026-10-21)

All commands below were executed and confirmed against commit `49821ad`
(Linux/WSL2 host, Python 3.12, Node 20, Docker 29). CI is the authoritative
environment for the full Docker suite; see "Local results vs CI evidence"
after the commands.

**Prerequisites:** Python 3.11+ (`python`), Node 20 + npm, Docker.

```bash
# 1. Backend (FastAPI control plane, port 8000; auth OFF by default —
#    set CONTROL_PLANE_API_TOKEN to require a bearer token on every route
#    except /health; CONTROL_PLANE_ENV=production FAILS CLOSED without
#    that token — startup error plus 401 on every non-/health route,
#    wired into docker-compose.production.yml and start-production.sh)
python -m pip install -r requirements.lock
python -m uvicorn api.app:app --port 8000

# 2. Verify it is up
curl http://localhost:8000/health
# expected: {"status":"ok"}

# 3. Frontend (second terminal; Vite dev server on 5173, proxies
#    /applications, /runs and /health to localhost:8000)
cd frontend
npm ci
npm run dev
# open http://localhost:5173/app/
```

**Docker execution lanes (needed for real end-to-end runs, same commands CI
uses):**

```bash
# build the two locally-pinned images (repo root)
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .

# pull/tag the digest-pinned Java runtime image (identity checked every run)
docker pull eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026
docker tag eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 eclipse-temurin:21-jdk

# REQUIRED whenever the Maven image is rebuilt: record image provenance so
# the candidate adapter can verify image identity (fail-closed otherwise)
python scripts/record_docker_image_provenance.py
# expected: prints build + runtime identity (repo-digest) and writes
# test-artifacts/docker-image-provenance.json — the regenerated working-tree
# update is never staged/committed without explicit D-4 authorization

# end-to-end proof: upload -> pipeline -> Docker oracle + candidate ->
# compare -> verdict (arithmetic VERIFIED path, Mode-A file workload, ZIP
# ingestion, approval-gated download)
RUN_DOCKER_TESTS=1 python -m pytest -q tests/test_e2e.py
```

**Tests (fast, no Docker):**

```bash
python -m pytest -q tests/test_silent_loss_registry.py tests/test_ingestion_diagnostics.py   # 18 passed
python tools/check_backlog_table.py           # OK: 122 register rows
cd frontend && npm test                       # vitest suite
cd frontend && npm run lint                   # tsc --noEmit
cd frontend && npm run build                  # tsc -b && vite build
```

**Troubleshooting (observed behavior, not hypothetical):**

- *Candidate adapter reports `UNAVAILABLE`, verdict `FAILED` with "build
  failure is not execution evidence", or `/runs/{id}/artifacts` returns
  500 "failed integrity validation":* the recorded image provenance does not
  match your local images (typically after rebuilding
  `maven-offline-springboot`). Fix: re-run
  `python scripts/record_docker_image_provenance.py`. This is fail-closed by
  design — a build failure can never surface as evidence.
- *`RUN_DOCKER_TESTS=1` but Docker missing:* the runtime-proof tests **fail**
  rather than skip (`tests/integration/test_file_write_read_runtime_proof.py`);
  an unexecuted test is never reported as proof.
- *Sequential full-suite Docker runs on WSL2 show intermittent failures under
  load:* known environment limitation (BL-010); run the affected tests in
  isolation, and treat Linux CI as the authoritative Docker result.
- *Download button disabled / HTTP 409:* export requires customer approval
  (BL-091); submit `APPROVED` in the approval panel first.
- *401 from the API:* a `CONTROL_PLANE_API_TOKEN` is set; enter the token in
  the Dashboard's token form (or call the API with
  `Authorization: Bearer <token>`).

**Local results vs CI evidence:** counts printed by local commands above are
local evidence on this machine. The authoritative test evidence for a commit is
the GitHub Actions run for that **exact SHA** (job conclusions are public; CI
job logs require repo admin rights, so per-job counts inside CI are not quoted
unless read from an uploaded artifact). Current verified SHA + CI runs:
`opencode.md`, `docs/BACKLOG.md`.

## Submission guide

A submission-ready project guide — architecture, sample input with verified
output, test/CI evidence, supported subset, security posture with deferred
controls, demo script, evaluator Q&A, and the §71 completion matrix with
remaining blockers — is in **[docs/SUBMISSION_GUIDE.md](docs/SUBMISSION_GUIDE.md)**
(verified at `49821ad`, 2026-10-21).

## Implemented

- Secure ZIP ingestion with traversal and extraction limits.
- Application discovery and dependency modeling.
- COBOL parser and semantic IR.
- Deterministic capability analysis and transformation planning.
- Deterministic COBOL to Java transformation.
- Java/Spring generation lanes.
- Docker-backed Java candidate execution.
- GnuCOBOL oracle execution in CI.
- Artifact capture and comparison infrastructure.
- Evidence integrity validation.
- Seven-state deterministic verdict derivation.
- SQLite-backed API/control-plane persistence.
- React frontend.
- CI for ingestion, backend/oracle/Docker, and frontend/build.

## Evidence ladder

Parser recognition does not automatically mean semantic transformation support.

1. recognized
2. parsed
3. represented in IR
4. capability analyzed
5. transformation mapped
6. Java generated
7. Java compiles
8. Java executes
9. COBOL oracle executes
10. behavior compared
11. mutation verified
12. end-to-end verified

Current proof is subset-based.

## Current boundaries

High-risk or incomplete proof areas include numeric precision/sign/COMP/COMP-3/rounding,
broad CALL and multi-program behavior, copybook completeness, indexed/relative files
beyond the oracle-proven certified subset (and any VSAM file-image equivalence),
JCL, CICS, DB2, production security hardening, persistent serialization, and broad
mutation/adversarial proof.

GnuCOBOL equivalence is not a blanket claim of z/OS or mainframe equivalence.

## Verification principles

- Unknown is not PASS.
- Unavailable is not VERIFIED.
- Compilation is not behavioral equivalence.
- Missing evidence cannot become a green result.
- Comparator contracts are explicit and fail closed.
- Producer metadata is provenance, not validation evidence.
- Evidence binds workload, source, candidate, execution, artifacts, and hashes.
- Unsupported enterprise constructs remain visible.

## Current documentation

- docs/SYSTEMAOPS_PRODUCT_STATUS.md - canonical product status and positioning
- docs/PROJECT_STATUS.md — current project truth
- docs/ARCHITECTURE.md — current architecture
- docs/REQUIREMENTS.md — current requirements and non-goals
- docs/CAPABILITY_MATRIX.md — current capability/evidence boundary
- docs/VERIFICATION_STATUS.md — current verification evidence
- docs/verification/RUNTIME_PROOF_MATRIX.md — live per-workload runtime-proof status (Docker lanes, images/digests, exact commands, honest labels)
- UNIVERSAL_RUNTIME_PROOF_AUDIT_AND_IMPLEMENTATION_PLAN.md — 2026-10-19 evidence-driven audit, remediation record (BL-094/095/096) and roadmap
- docs/KNOWN_ISSUES.md — current risks and resolved historical blockers
- docs/REMEDIATION_MATRIX.md — remediation priorities
- docs/CONTRACT_STATUS.md — contract/spec implementation status
- contracts/* and docs/specs/* — normative requirements
- phase reports and forensic reports — historical evidence

Historical reports are not rewritten to make old results look current.

## CI baseline

Dated snapshot (verified 2026-10-17 via the GitHub Actions REST API against
commit `6145e892e95282a0ca85eb678057a0ea9890389c` — not a live pointer; re-check
before quoting):

- Run 38980053986 ("SystemaOps CI", created 2026-10-16T23:11:17Z) — GREEN, all
  4 jobs: "Phase 1 ingestion diagnostics", "Backend and COBOL/Java Docker
  tests" (full `pytest tests` with `RUN_DOCKER_TESTS=1`), "Frontend tests,
  TypeScript, and production build", "Capability truth gate".
- Run 38980054137 (supply-chain provenance) — GREEN.
- Docker is exercised in CI: the backend job builds the GnuCOBOL and Maven
  images, records image provenance, and runs the full backend suite with the
  Docker lanes enabled.
- The old TypeScript JSX build blocker is resolved in the current baseline.
- These runs cover only commit `6145e892e95282a0ca85eb678057a0ea9890389c`
  (the snapshot SHA above). The runtime-proof gap-closure and Windows
  path-separator test-fix changes delivered on top of it are validated only
  by the Actions runs at their own containing commit — check CI there.

Per-workload runtime-proof status (based on local runs of the named test
modules, with per-row evidence) is tracked in
docs/verification/RUNTIME_PROOF_MATRIX.md.

> Deterministic transformation + independent evidence-driven verification + fail-closed claims.
