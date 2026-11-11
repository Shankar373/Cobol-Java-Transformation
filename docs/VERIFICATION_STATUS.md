# Verification Status

> **Dated snapshot (2026-11-02, Phase 5 certification of `main`) - not the current status of `impl/enterprise-platform`.**
> On that date the 54-application corpus gave 44 VERIFIED on each of the four runtimes (`spring_boot`, `plain_java`,
> `quarkus`, `micronaut` command mode), accepted at `7e1a0d1` (Phase 3) and `32cf586` (Phase 4). The implementation branch
> has moved on (45 of 55 VERIFIED per runtime after numeric-edited PIC; see [PROTOTYPE_HANDOFF.md](PROTOTYPE_HANDOFF.md) for the
> current commit, workflow links, limitations and verdicts). This is a certified *subset*, not universal COBOL compatibility,
> and no version of this product is certified for production use. Older baselines below are dated history.

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

Baseline: fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4
CI: Push CI #417 / PR CI #418 — GREEN

## CI evidence

| Gate | Result |
|---|---|
| Phase 1 ingestion | PASS |
| Backend + COBOL/Java Docker | PASS |
| Frontend tests/build | PASS |
| Docker availability in CI | Confirmed |
| Current baseline | GREEN |

## What green proves

The checked test suites and build gates pass at the current baseline. Docker-backed backend
and COBOL/Java execution tests function in CI.

## What green does not prove

It does not prove universal COBOL semantic coverage, universal mainframe/z/OS equivalence,
complete JCL/CICS/DB2 behavior, complete indexed/relative file semantics, every numeric
edge case, production security readiness, or mutation proof of every evidence/verdict route.

## Verdict model

The implementation uses seven deterministic states:

VERIFIED, FAILED, PARTIAL, UNPROVEN, UNAVAILABLE, UNSUPPORTED, ERROR.

Verdicts derive from validated evidence and cannot be upgraded by claims, skipped checks or
missing artifacts.

## Highest-value next proof

1. Broaden semantic transformation tests.
2. Harden numeric and file semantics.
3. Exercise CALL and multi-program paths.
4. Prove evidence/verdict integrity under tampering and replay.
5. Add mutation testing around comparators and verdict derivation.
6. Add production security and persistence controls.
7. Keep capability and documentation claims synchronized with executable evidence.
