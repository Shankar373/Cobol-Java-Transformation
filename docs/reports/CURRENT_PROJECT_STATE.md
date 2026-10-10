# Current Project State

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

> **CURRENT STATUS DOCUMENT — supersedes the old snapshot in this file.**
>
> Baseline: fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4
> Branch: codex/universal-core
> Push CI #417 / PR CI #418: GREEN

## Current state

The project is an implemented deterministic COBOL to Java modernization and verification
platform. It is not the old greenfield documentation-only state.

Implemented areas include secure ingestion, discovery, semantic IR, capability analysis,
transformation planning, deterministic COBOL to Java mapping/generation, Docker execution,
GnuCOBOL oracle execution, artifact comparison, evidence integrity, verdict derivation,
FastAPI persistence/control plane, React UI and CI.

## Current limitation

The project is not universally certified. Current proof is bounded by the tested semantic
subset and the execution/comparison contracts. Numeric edge cases, broad CALL behavior,
copybook completeness, indexed/relative files, JCL, CICS, DB2, production security and
broader mutation/adversarial proof remain open areas.

For authoritative current status, use docs/PROJECT_STATUS.md and the other current documents
listed there.

The historical reports that follow this file remain immutable evidence of earlier project
states and should not be read as current baseline claims.
