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
broad CALL and multi-program behavior, copybook completeness, indexed/relative files,
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
