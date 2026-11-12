# Project Status

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
Branch: codex/universal-core
CI at this snapshot (2026-10-10): Push CI #417 / PR CI #418 — GREEN (live runs: `opencode.md`)

## Executive status

The repository is no longer a greenfield contract-only project. It contains a functioning
deterministic COBOL to Java modernization pipeline, execution/verification infrastructure,
control plane, frontend, Docker runtime and CI.

The project is subset-certified, not universally certified. Green CI proves the checked
repository gates pass; it does not prove semantic equivalence for every COBOL construct or
every mainframe runtime.

## Domain status

| Domain | Implementation | Test/CI | Broad runtime proof | Status |
|---|---|---|---|---|
| Secure ingestion | Yes | Yes | Yes | GREEN |
| Discovery | Yes | Yes | Yes | GREEN |
| COBOL parser | Yes | Yes | Partial | YELLOW |
| Semantic IR | Yes | Yes | Partial | YELLOW |
| Copybooks | Yes | Yes | Partial | YELLOW |
| CALL / dependencies | Yes | Yes | Partial | YELLOW |
| Capability analysis | Yes | Yes | Partial | YELLOW |
| Transformation planning | Yes | Yes | Partial | YELLOW |
| COBOL to Java mapping | Yes | Yes | Partial | YELLOW/RED |
| Java generation | Yes | Yes | Tested subset | YELLOW |
| Arithmetic semantics | Yes, subset | Yes | Limited | YELLOW/RED |
| Sequential files | Yes | Yes | Tested subset | YELLOW |
| Indexed/relative files | Yes, certified subset (BL-134) | Yes | Limited — certified-subset oracle proof (generated Java byte-identical vs GnuCOBOL 3.1.2); no broad/VSAM file-image proof | YELLOW |
| JCL | Modeling/subset | Yes | No broad runtime proof | RED |
| CICS | Modeling/subset | Yes | No broad runtime proof | RED |
| DB2 | Modeling/subset | Yes | No DB2 runtime proof | RED |
| Docker execution | Yes | Yes | Yes in CI | GREEN |
| GnuCOBOL oracle | Yes | Yes | Tested scope | GREEN |
| Comparator | Yes | Yes | Partial | YELLOW |
| Evidence integrity | Yes | Yes | Partial | YELLOW |
| Verdict derivation | Yes | Yes | Partial | YELLOW |
| Persistence | Yes | Yes | Functional | YELLOW |
| API | Yes | Yes | Partial production hardening | YELLOW |
| Security hardening | Phase 4 hardening accepted (`32cf586`, `docs/reports/PHASE4_SECURITY_PRODUCTION_READINESS.md`) | Partial | No production certification; identity/RBAC, signing, framework upgrades owner-dependent | AMBER |
| Frontend | Yes | Yes | Build verified | YELLOW |
| CI | Yes | Yes | Yes | GREEN |
| Documentation | Partially reconciled | N/A | N/A | YELLOW |

## Current non-claims

Do not claim universal COBOL compatibility, universal z/OS equivalence, complete JCL/CICS/DB2
runtime equivalence, complete indexed/relative file equivalence, production-grade
multi-tenant security, or VERIFIED status solely because Java compiles or CI is green.

## Baseline protection

The current green baseline is an acceptance anchor. Future changes must preserve or explicitly
replace it with stronger evidence; regressions must not be hidden by weakening tests or
capability labels.
