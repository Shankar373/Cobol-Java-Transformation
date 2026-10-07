# Cobol-Java-Transformation

**SystemaOps deterministic COBOL to Java modernization and verification platform.**

> CURRENT BASELINE: 90efdca6c9da3e36888c78f8c3b88757dbcc15f3 on codex/universal-core.
>
> CI Run #306 is the last archived green run on record (historical provenance; the numeric
> run ID refers to the pre-Phase-D baseline). Current Phase-D HEAD: 90efdca on
> codex/universal-core.
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

- docs/PROJECT_STATUS.md — current project truth
- docs/ARCHITECTURE.md — current architecture
- docs/REQUIREMENTS.md — current requirements and non-goals
- docs/CAPABILITY_MATRIX.md — current capability/evidence boundary
- docs/VERIFICATION_STATUS.md — current verification evidence
- docs/KNOWN_ISSUES.md — current risks and resolved historical blockers
- docs/REMEDIATION_MATRIX.md — remediation priorities
- docs/CONTRACT_STATUS.md — contract/spec implementation status
- contracts/* and docs/specs/* — normative requirements
- phase reports and forensic reports — historical evidence

Historical reports are not rewritten to make old results look current.

## CI baseline

Run #306 is GREEN:

- Phase 1 ingestion: PASS
- Backend + COBOL/Java Docker: PASS
- Frontend TypeScript/build: PASS
- Docker is exercised in CI.
- The old TypeScript JSX build blocker is resolved in the current baseline.

> Deterministic transformation + independent evidence-driven verification + fail-closed claims.
