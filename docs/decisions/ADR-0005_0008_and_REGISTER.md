# ADR-0005 — Certification Unit & Evidence-Derived Certification Model

**Status:** **ACCEPTED (CONFIRMED)**

**Date:** 2026-09-13 · **Owner:** Platform owner
**Authority:** Phase-1B approval, PD-07 (resolves DR-15 and DR-30). Pairs with ADR-0004.

## Context

The predecessor's certification model (weighted 5-tier, 100-point scoring) was never
adopted nor rejected by this project (DR-30 conflict), and its audit showed partial
evidence averaging into passing grades — the structural failure mode this platform
exists to prevent.

## Decision

1. **Certification unit = ONE WORKLOAD-RUN** — a single validation execution of one
   workload under one fully-declared identity set.
2. **Partial certification is NOT allowed in V1.** Certification is all-or-nothing per
   workload-run. `PARTIAL` is a verdict, never a certification.
3. **Certification model = evidence-derived verdict state.** Certification exists only
   when (a) the evidence manifest is complete and (b) the verdict is `VERIFIED`.
4. **Weighted scores, percentages, and 100-point grades are prohibited** as certification
   authority.

**Certification invalidation (any → void):** identity change (source hash, candidate
hash, oracle digest, environment, contract/comparator versions) · stale evidence ·
mutation-gate failure · evidence-manifest incompleteness · unsupported artifact silently
ignored.

## Consequences

- DR-15, DR-30 → CONFIRMED.
- VERDICT_CONTRACT.md carries the certification derivation rules; aggregation beyond a
  single workload-run (programs/applications) is out of scope for V1 certification.

---

# ADR-0006 — V1 Artifact Scope

**Status:** **ACCEPTED (CONFIRMED)**

**Date:** 2026-09-13 · **Owner:** Platform owner
**Authority:** Phase-1B approval, PD-03 (resolves DR-11).

## Context

Only five artifact classes ever had trustworthy differential comparison in the
predecessor (independent execution + real mutation proofs): stdout, stderr, exit code,
text files, fixed-record files (E10). Everything else was false-PASS, bypassed, or never
compared.

## Decision

**V1 artifact contract types (exhaustive):**

```
STDOUT | STDERR | EXIT_STATUS | TEXT_FILE | FIXED_RECORD
```

Execution metadata, hashes, sizes, record counts, timing, and termination information
are **evidence-envelope fields** — captured, not compared as artifacts.

V1 scope does not expand merely because more artifact types are technically possible;
INDEXED/RELATIVE content and SQL/DB artifacts are excluded by ADR-0002/0007 and fail
closed as `UNSUPPORTED`.

## Consequences

- DR-11 → CONFIRMED.
- ARTIFACT_CONTRACT_SPEC.md enumerates exactly these five types; the contract registry
  is closed — adding types later is a versioned contract change, not silent growth.

---

# ADR-0007 — SQL/Database Scope

**Status:** **ACCEPTED (CONFIRMED)**

**Date:** 2026-09-13 · **Owner:** Platform owner
**Authority:** Phase-1B approval, PD-06 (resolves DR-12).

## Context

Predecessor SQL evidence state: DB2CURNULL01 NULL divergence and host-variable binding
live failures; database state never compared anywhere; mock JDBC stubs compiled into
runs labeled parity (E5/E6). Executable infrastructure (local PostgreSQL) is not
provable equivalence.

## Decision

**V1 excludes SQL/database equivalence.** SQL-containing workloads fail closed with
`UNSUPPORTED` for SQL artifacts, with the exclusion stated in the verdict.

**SQL becomes V2 only after all of:** host-variable semantics defined · NULL behavior
defined · database-state artifact contract exists · real state comparison exists ·
DB mocks forbidden from positive evidence · differential tests + mutation proofs exist.

**Stdout alone never certifies database equivalence.**

## Consequences

- DR-12 → CONFIRMED.
- No database adapter or DATABASE_STATE comparator in V1; SQL workloads are honest
  `UNSUPPORTED` rather than false-certified.

---

# ADR-0008 — Evidence Format, Baselines, Sandbox, Scale

**Status:** **ACCEPTED (CONFIRMED)**

**Date:** 2026-09-13 · **Owner:** Platform owner
**Authority:** Phase-1B approvals DR-16, DR-17, DR-18, DR-20 (bundled record).

## Decisions

**DR-16 — Evidence format/storage:**
- JSON evidence manifests.
- SHA-256 content-addressed artifacts.
- **No signing in V1.**
- Oracle identities are **digest-pinned** (immutable reference, never a mutable tag).

**DR-17 — Baseline lifecycle (V1):**
- **Fresh oracle execution for every V1 run** — no baseline reuse in the first vertical
  slice. (Identity-bound reuse arrives only with the regression suite, as a separate
  later decision.)

**DR-18 — Sandbox / execution isolation:**
- Container-per-execution.
- Read-only staged source copies.
- `network none` (V1 has no SQL; no candidate networking).
- Resource limits (memory/CPU/pids).
- Hard timeout — timeout is a platform failure (`ERROR`), never PASS.
- **No host read-write source mounts. No chmod 777. No hardcoded/default credentials.**

**DR-20 — Scale/concurrency:**
- V1 is single-user, single-workload-at-a-time. No queueing, no distribution, no
  persistence beyond manifests-on-disk.

## Consequences

- DR-16/17/18/20 → CONFIRMED.
- EVIDENCE_SPEC.md, BASELINE_SPEC.md, and SECURITY_SPEC.md draft against these
  parameters; the DR-18 hard rules are normative for the execution layer.

---

# ADR Register (running list)

| ADR | Subject | Status | Date | Authority |
|---|---|---|---|---|
| 0000 | ADR numbering meta-convention | PROPOSED | 2026-09-13 | — |
| 0001 | Authoritative V1 oracle | **ACCEPTED** | 2026-09-13 | PD-01 |
| 0002 | INDEXED/RELATIVE strategy | **ACCEPTED** | 2026-09-13 | PD-02 |
| 0003 | Platform technology stack | **ACCEPTED** | 2026-09-13 | PD-08 |
| 0004 | Verdict vocabulary (7 states) | **ACCEPTED** | 2026-09-13 | PD-07 |
| 0005 | Certification unit & model | **ACCEPTED** | 2026-09-13 | PD-07 |
| 0006 | V1 artifact scope | **ACCEPTED** | 2026-09-13 | PD-03 |
| 0007 | SQL/database scope | **ACCEPTED** | 2026-09-13 | PD-06 |
| 0008 | Evidence/baseline/sandbox/scale | **ACCEPTED** | 2026-09-13 | DR-16/17/18/20 |
| — | Java candidate contract (platform side) | **ACCEPTED, joint co-approval PENDING** | 2026-09-13 | PD-04 — see JAVA_CANDIDATE_CONTRACT |
| — | Producer contract (platform side) | **ACCEPTED, joint co-approval PENDING** | 2026-09-13 | PD-05 — see TRANSFORMATION_PRODUCER_CONTRACT |

> ADR-0009/0010 (candidate & producer contracts) will be numbered and recorded with
> full ADR form once the LLM integration owner co-approves PD-04/PD-05. The contracts
> themselves are drafted now as platform-authoritative; their producer-binding force is
> gated on co-approval.
