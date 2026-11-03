# Contract and Specification Status

> **Current truth (2026-11-02, Phase 5 certification):** Phase 3 accepted on `7e1a0d1`,
> Phase 4 accepted on `32cf586`. The 54-application corpus gives 44 VERIFIED on each of
> the four proven runtimes (`spring_boot`, `plain_java`, `quarkus`, `micronaut` command
> mode), 9 refused by name, 1 UNAVAILABLE (GnuCOBOL rejects the source); every VERIFIED
> result is independently re-checked (AGREE). Application servers are not supported.
> This is a certified *subset*, not universal COBOL compatibility, and the product is
> not certified for production use (owner-dependent gaps:
> `docs/reports/PHASE5_RELEASE_READINESS.md`). Certification evidence:
> `docs/reports/PHASE5_FINAL_CERTIFICATION.md`. Older baselines below are dated history.

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
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
