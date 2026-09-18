# PHASE 1B — OWNER APPROVALS (VERBATIM RECORD)

> **Record type:** Decision provenance record. This file preserves the owner's
> Phase-1B approval message verbatim. It is the authoritative evidence for every
> `CONFIRMED` status change made in Phase 1C.
>
> **Recorded:** 2026-09-13 (session date per environment)
> **Repository state at recording:** `README.md` (2,752 lines) +
> `docs/decisions/PHASE1_DECISION_REPORT.md` — documentation only, zero implementation.

## Authorization scope (from the owner's decision notes)

> "These approvals authorize Phase 1C contract drafting. No production
> implementation starts until the contracts and ADRs are completed and validated."

## Verbatim owner approval message

```text
OWNER APPROVAL

PD-01: APPROVE
Decision: GnuCOBOL 3.1.2.0 + Open-COBOL-ESQL 1.4, digest-pinned, as V1
authoritative oracle. Every verdict must explicitly include oracle identity
scope. Never claim z/OS equivalence.

PD-02: APPROVE
Decision: Exclude INDEXED/RELATIVE content equivalence from V1 and return
UNSUPPORTED when required. V2 target is oracle-stage semantic dump/extraction.
Substring containment is permanently forbidden as a general equivalence strategy.

PD-03: APPROVE
Decision: V1 artifact types are:
STDOUT
STDERR
EXIT_STATUS
TEXT_FILE
FIXED_RECORD

Execution metadata, hashes, sizes, counts, timing, and termination information
remain evidence-envelope fields.

PD-04: APPROVE
Decision: V1 Java candidate = plain Java source tree + platform-controlled
javac + explicit entrypoint manifest. Maven/Spring Boot deferred to V2.
JOINT APPROVAL WITH LLM INTEGRATION OWNER.

PD-05: APPROVE
Decision: Minimal mandatory producer manifest with candidate/source identity,
hashes, generated-file list, entrypoint, Java/dependency metadata, runtime
requirements, and mutation-regeneration capability.
Producer remains external, replaceable, untrusted, and producer-agnostic.
JOINT APPROVAL WITH LLM INTEGRATION OWNER.

PD-06: APPROVE
Decision: Exclude SQL/database equivalence from V1. SQL is V2 only after the
required semantic definitions, database-state artifact contract, real state
comparison, differential tests, and mutation proofs exist.

PD-07: APPROVE
Decision:
- Certification unit = ONE WORKLOAD-RUN
- Partial certification = NOT ALLOWED in V1
- Verdict states =
  VERIFIED
  PARTIAL
  FAILED
  UNPROVEN
  UNAVAILABLE
  UNSUPPORTED
  ERROR
- Certification = evidence-derived verdict-state model
- No weighted score / percentage / 100-point certification model

PD-08: APPROVE
Decision:
- Validation Engine = Python 3.12
- Backend / Control Plane = FastAPI
- Frontend = React + TypeScript + Vite
- Frontend uses a NEW project-owned design system
- Existing SystemaOps UI is NOT a dependency
- Validation Engine remains independently executable

Additional decisions:

DR-16: APPROVE
Decision: JSON evidence manifests + SHA-256 content-addressed artifacts,
no signing in V1, digest-pinned oracle identities.

DR-17: APPROVE
Decision: Fresh oracle execution for every V1 run. No baseline reuse in the
first vertical slice.

DR-18: APPROVE
Decision: Container-per-execution, read-only staged source, network none,
resource limits, hard timeout, no host RW source mounts, no chmod 777,
no hardcoded/default credentials.

DR-19: DEFER

DR-20: APPROVE
Decision: V1 is single-user, single-workload-at-a-time.

DR-31: DEFER
Decision: Final frontend/backend implementation details will be decided after
the contract and engine foundations are established.

Decision notes:
These approvals authorize Phase 1C contract drafting.
No production implementation starts until the contracts and ADRs are completed
and validated.
```

## Consequence register map (what these approvals resolve)

| DR | Subject | Resulting status | Authority |
|---|---|---|---|
| DR-06 | Verdict vocabulary | **CONFIRMED** — 7 states incl. `ERROR` | PD-07 |
| DR-07 | Platform language/build | **CONFIRMED** — Python 3.12 / FastAPI / React-TS-Vite | PD-08 |
| DR-08 | Authoritative oracle | **CONFIRMED** — GnuCOBOL 3.1.2.0 + OCESQL 1.4, digest-pinned, scoped | PD-01 |
| DR-09 | INDEXED/RELATIVE strategy | **CONFIRMED** — excluded from V1 (`UNSUPPORTED`); V2 oracle-stage dump | PD-02 |
| DR-11 | V1 artifact scope | **CONFIRMED** — the five approved types | PD-03 |
| DR-12 | SQL/DB scope | **CONFIRMED** — excluded from V1 | PD-06 |
| DR-13 | Java target contract | **CONFIRMED (platform side)** — plain tree + platform `javac` + entrypoint manifest; **LLM-owner co-approval PENDING** | PD-04 |
| DR-14 | Producer I/O contract | **CONFIRMED (platform side)** — minimal mandatory manifest; **LLM-owner co-approval PENDING** | PD-05 |
| DR-15 | Certification unit / partial policy | **CONFIRMED** — one workload-run; no partial certification in V1 | PD-07 |
| DR-16 | Evidence format/storage | **CONFIRMED** — JSON + SHA-256 content-addressed; no signing V1; digest-pinned identities | DR-16 approval |
| DR-17 | Baseline lifecycle | **CONFIRMED** — fresh oracle execution every V1 run; no reuse | DR-17 approval |
| DR-18 | Sandbox/isolation | **CONFIRMED** — container-per-execution policy as stated | DR-18 approval |
| DR-19 | Product identity/users | **DEFERRED by owner** — remains OPEN | — |
| DR-20 | Scale/concurrency | **CONFIRMED** — single-user, single-workload V1 | DR-20 approval |
| DR-24 | GnuCOBOL as first oracle adapter | **CONFIRMED by consequence** (PD-01 makes GnuCOBOL the V1 oracle; the first adapter necessarily targets it) | PD-01 |
| DR-25 | Environment-scoped verdicts | **CONFIRMED by consequence** (PD-01: "Every verdict must explicitly include oracle identity scope"; PD-07 verdict contract carries the scope block) | PD-01 + PD-07 |
| DR-30 | Certification model | **CONFIRMED** — evidence-derived verdict state; weighted/percentage models prohibited | PD-07 |
| DR-31 | Frontend/backend tech details | **DEFERRED by owner** — remains OPEN | — |

**Still OPEN after Phase 1B:** DR-10 (semantic-analysis depth — P1, blocks the semantic
layer only), DR-19 (product identity — deferred), DR-31 (frontend/backend details —
deferred), DR-21/22/23 (first slice / build ordering / full repo structure — PROPOSED,
resolved at implementation authorization), DR-26/27/28 (unchanged: OUT OF SCOPE /
FUTURE), Q11 (mutation detection standard — P1).

**Joint-approval gate:** PD-04/PD-05 are approved platform-side. The
`TRANSFORMATION_PRODUCER_CONTRACT` and `JAVA_CANDIDATE_CONTRACT` are drafted as
platform-authoritative for engine design; they become binding on the producer interface
only after the LLM integration owner co-approves. Until co-approval: candidate intake
against real producers and producer-side mutation regeneration remain gated.
