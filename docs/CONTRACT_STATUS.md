# Contract and Specification Status

> **Dated snapshot (2026-11-02, Phase 5 certification of `main`) - not the current status of `impl/enterprise-platform`.**
> On that date the 54-application corpus gave 44 VERIFIED on each of the four runtimes (`spring_boot`, `plain_java`,
> `quarkus`, `micronaut` command mode), accepted at `7e1a0d1` (Phase 3) and `32cf586` (Phase 4). The implementation branch
> has moved on (45 of 55 VERIFIED per runtime after numeric-edited PIC; see [PROTOTYPE_HANDOFF.md](PROTOTYPE_HANDOFF.md) for the
> current commit, workflow links, limitations and verdicts). This is a certified *subset*, not universal COBOL compatibility,
> and no version of this product is certified for production use. Older baselines below are dated history.

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `docs/PROTOTYPE_HANDOFF.md` and `docs/audits/EXECUTION_LEDGER.md` (the live record as of the
> 2026-11-12 audit; `opencode.md` and `docs/BACKLOG.md` are historical).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

Baseline: fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4

The contracts were originally written during the greenfield phase. Their normative
requirements remain relevant, but old statements saying implementation is a later phase are
no longer current.

| Contract/spec | Current status |
|---|---|
| ORACLE_CONTRACT.md | Normative; implementation exists; continue requirement-by-requirement runtime audit |
| ARTIFACT_CONTRACT_SPEC.md | Normative; artifact/comparison implementation exists; continue coverage audit |
| VERDICT_CONTRACT.md | Normative; deterministic verdict implementation exists; continue route/mutation audit |
| JAVA_CANDIDATE_CONTRACT.md | Normative V1 shape; V2 Spring Boot/Maven lane now defined in `JAVA_CANDIDATE_CONTRACT_V2.md` (D-10 approved 2026-10-21, BL-110 FIXED); version boundary reconciled |
| TRANSFORMATION_PRODUCER_CONTRACT.md | Boundary contract; external-producer model must be reconciled with current internal deterministic transformer |
| docs/specs/EVIDENCE_SPEC.md | Normative design; evidence implementation exists; implementation-status audit required |
| docs/specs/COMPARATOR_SPEC.md | Normative design; comparator implementation exists; implementation-status audit required |

## Architectural reconciliation

The repository owns a deterministic COBOL to Java transformation path and also retains an
external-candidate trust boundary.

These are separate concerns:

1. deterministic transformation owned by this repository;
2. external candidate validation through an untrusted input boundary;
3. evidence and verdict certification independent of producer claims.

Requirements should not be silently deleted. Changes to ownership, candidate shape or
certification scope require an explicit ADR and contract/version change.
