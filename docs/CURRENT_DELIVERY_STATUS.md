# Current Delivery Status

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

**Baseline snapshot (2026-10-10; corrected 2026-10-16, Phase 12 F-02 — no longer labeled "authoritative"):** fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4  
**Branch:** codex/universal-core  
**CI at that snapshot:** Push CI #417 / PR CI #418 — GREEN  
**Live verified SHA/CI:** `opencode.md` (checkpoint) + `docs/BACKLOG.md` register.

This document is retained as the delivery-status entry point. Detailed current truth is now
split into the authoritative documents below.

- docs/PROJECT_STATUS.md — overall implementation status
- docs/ARCHITECTURE.md — current architecture
- docs/REQUIREMENTS.md — current requirements
- docs/CAPABILITY_MATRIX.md — capability/evidence boundary
- docs/VERIFICATION_STATUS.md — verification evidence
- docs/KNOWN_ISSUES.md — current issues
- docs/REMEDIATION_MATRIX.md — remediation priorities
- docs/CONTRACT_STATUS.md — contract/spec implementation status

## Current delivery statement

The repository contains a functioning deterministic COBOL to Java modernization pipeline,
Docker-backed Java and GnuCOBOL execution path, evidence/comparison/verdict infrastructure,
FastAPI control plane, React frontend and green CI.

The implementation is not universally certified. Semantic coverage remains subset-based and
enterprise runtime areas such as broad JCL/CICS/DB2 equivalence remain outside the proven
certification boundary; indexed/relative file **behavioral** equivalence is inside it only for
the certified subset (primary RECORD KEY at offset 0, ACCESS MODE DYNAMIC, no ALTERNATE
RECORD KEY — BL-134), while broad indexed/relative semantics and any VSAM file-image
equivalence stay outside.

## CI

Push CI #417 / PR CI #418 was green across ingestion, backend/COBOL-Java
Docker validation and frontend/build (2026-10-10 snapshot; current CI runs
are tracked in `opencode.md`).
The previous frontend TypeScript build blocker is historical/resolved.

## Documentation rule

This file is a navigation/status document, not a substitute for the authoritative status
files listed above. Historical phase reports must not be interpreted as current state.
