# VERDICT CONTRACT — V1

> **Status:** AUTHORITATIVE (approved via ADR-0004 + ADR-0005 / PD-07). Resolves
> DR-06, DR-15, DR-30. Contract version: **1.0**. Implementation is a later phase.
> Authority chain: [PHASE1B_OWNER_APPROVALS.md](../decisions/PHASE1B_OWNER_APPROVALS.md)
> → [ADR-0004, ADR-0005](../decisions/ADR-0001_0004.md) → this contract.

---

## 1. Purpose

The verdict is the platform's single authoritative statement of what is proven. This
contract defines the verdict vocabulary, the derivation rules, the certification model,
and the invariants that make verdict fabrication architecturally impossible.

## 2. Verdict Vocabulary [CONFIRMED — ADR-0004]

Exactly seven states, no more, no less:

| State | Meaning | May render green? |
|---|---|---|
| `VERIFIED` | Complete evidence; all mandatory invariants hold. The **only** certifiable state. | Yes |
| `PARTIAL` | Incomplete validation that does not qualify for V1 certification. | **No** |
| `FAILED` | **Behavioral divergence** — the candidate demonstrably differs from the oracle. | **No** |
| `UNPROVEN` | **Insufficient evidence** to determine equivalence either way. | **No** |
| `UNAVAILABLE` | Required **infrastructure/capability unavailable** (oracle down, environment missing). | **No** |
| `UNSUPPORTED` | Capability/artifact **intentionally outside supported scope** (fail-closed, e.g., INDEXED content or SQL artifacts in V1). | **No** |
| `ERROR` | **Validator/platform processing failure** — the validator itself failed to run, crashed, or could not process inputs (including execution timeout). | **No** |

`ERROR` ≠ `UNAVAILABLE` ≠ `FAILED`: platform failure vs missing infrastructure vs
behavioral divergence. The predecessor conflated these with fatal consequences
(swallowed baseline exceptions became warnings).

## 3. Core Invariant: Pure Derivation

> **A verdict is a pure function of an evidence manifest — nothing else.**

The verdict engine MUST NOT derive truth from:

- booleans or convenience flags
- environment variables
- source text
- file existence
- test count
- hardcoded metrics
- declared capabilities
- skipped tests
- model/producer claims
- baseline existence

Every reported metric (comparison counts, mutation detection rates, pass rates) is
**computed from evidence records** — never hardcoded.

## 4. Mandatory Verdict Scope Block

Every verdict carries its complete scope identity (schema-invalid without it):

```
run_id, workload_id
source identity (hash), candidate identity (hash)
oracle identity (adapter + image digest)          [ADR-0001]
environment identity
artifact contract versions, comparator versions
executed_check_count
skipped_count, unavailable_count
supported_scope_statement (incl. V1 exclusions)
```

A verdict answers "equivalent **under which conditions**" — never an unscoped claim.

## 5. Prohibited Transitions (impossible by construction)

| Prohibited | Enforcement |
|---|---|
| `SKIP` → `PASS` | Skipped stages contribute explicit skip counts; verdict caps below `VERIFIED` |
| `UNAVAILABLE` → `VERIFIED` | Unavailable infrastructure caps the verdict at `UNAVAILABLE` |
| `0 executed checks` → `GREEN`/`PASS` | `executed_check_count = 0` ⇒ verdict cannot be `VERIFIED` |
| `missing evidence` → `VERIFIED` | Manifest completeness is a mandatory precondition |
| `source inspection` → `VERIFIED` | Source text is not a verdict input (§3) |
| `baseline exists` → `VERIFIED` | Baseline validity derives from recorded identity binding, never existence |
| `UNPROVEN`/`ERROR` → promoted by absence of findings | Verdicts are monotone: downgrade only |

**Absence of evidence is never evidence of equivalence.**

## 6. Certification Model [CONFIRMED — ADR-0005]

1. **Certification unit = ONE WORKLOAD-RUN.**
2. **Partial certification is NOT allowed in V1.** `PARTIAL` is a verdict, never a
   certification.
3. **Certification exists only when:** (a) the evidence manifest is complete AND (b)
   the verdict is `VERIFIED`.
4. **Weighted scores / percentages / 100-point grades are prohibited** as certification
   authority.

**Invalidation (any occurrence → certification void):**

- identity change (source hash, candidate hash, oracle digest, environment,
  contract/comparator versions)
- stale evidence (per ADR-0008/DR-17: V1 re-executes the oracle fresh every run — no
  baseline reuse — so staleness is structurally excluded, and any detected staleness is
  an invalidating anomaly)
- mutation-gate failure
- evidence-manifest incompleteness
- unsupported artifact silently ignored

## 7. Derivation Requirements (summary)

For a workload-run to be `VERIFIED`, ALL must hold (each verified against evidence
records, not assumed):

1. Required oracle execution `SUCCEEDED` with complete evidence (ORACLE_CONTRACT §5).
2. Required candidate execution succeeded with complete evidence.
3. All contract-declared artifacts captured `COMPLETE` (ARTIFACT_CONTRACT §4).
4. All contract validations passed (§5 there).
5. All required comparisons executed and passed — `executed_check_count > 0` and equals
   the contract-declared check set.
6. Required mutation validation passed (production-path, same comparator stack).
7. Evidence manifest complete and reconstructable.
8. No unsupported artifact silently ignored — every exclusion states `UNSUPPORTED`
   explicitly in the verdict.
9. Source tree verified unchanged post-run (oracle immutability proof).

Any unmet precondition caps the verdict at the corresponding non-VERIFIED state per
the mapping: infrastructure absent → `UNAVAILABLE`; insufficient evidence → `UNPROVEN`;
behavioral divergence → `FAILED`; out-of-scope artifact/capability → `UNSUPPORTED`;
platform failure/timeout → `ERROR`; incomplete-but-valid subset validation → `PARTIAL`.

## 8. Rendering Rules (frontend/backend obligation)

The frontend **renders authoritative engine state**; it never recomputes verdicts (e.g.,
"zero differences → PASS" in the UI is forbidden). All non-`VERIFIED` states render
non-green. Status colors must correspond to the engine verdict (PASS→green,
FAIL→red, WARNING/PARTIAL→amber, UNKNOWN/UNPROVEN/UNAVAILABLE/UNSUPPORTED→neutral,
ERROR→red/error). Color is never the sole indicator — text labels always accompany it.

## 9. Test-First Requirements

| Scenario | Expected verdict/state |
|---|---|
| Valid evidence, all checks pass | `VERIFIED` (certifiable) |
| Real difference in a compared artifact | `FAILED` |
| Insufficient evidence (artifact missing w/o failure-policy) | `UNPROVEN` |
| Platform/execution failure, timeout | `ERROR` |
| Oracle/environment absent | `UNAVAILABLE` |
| INDEXED/SQL artifact required by workload | `UNSUPPORTED` for that artifact; verdict reflects it |
| Zero executed checks | Never `VERIFIED` (architecture-impossible) |
| Skipped comparison | Never PASS; contributes skip count |
| Stale/identity-mismatched evidence | Never `VERIFIED`; invalidation |
| `baseline_verified=True`-style flag anywhere in inputs | Not a verdict input — ignored (test proves verdict unchanged when flag present) |

## 10. Change Control

Version 1.0. Vocabulary changes (adding/removing states) require an ADR and
supersede-checking across ORACLE_CONTRACT §7, ARTIFACT_CONTRACT §2 exclusions, evidence
spec, and frontend rendering rules.
