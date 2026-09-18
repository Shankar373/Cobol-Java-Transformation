# TRANSFORMATION PRODUCER CONTRACT — V1 (external interface only)

> **Status:** AUTHORITATIVE on the platform side; **producer-binding force gated on
> LLM-integration-owner co-approval** (PD-05 joint decision — platform half approved,
> co-approval PENDING). Contract version: **1.0**. Implementation of the producer is
> OUT OF SCOPE (DR-26): this document defines only the boundary interface.
> Authority chain: [PHASE1B_OWNER_APPROVALS.md](../decisions/PHASE1B_OWNER_APPROVALS.md)
> → [Phase-1 report PD-05](../decisions/PHASE1_DECISION_REPORT.md) → this contract.

---

## 1. Purpose

The transformation producer (LLM, deterministic translator, human, or hybrid) is
**external, replaceable, untrusted, and producer-agnostic**. This contract defines the
**minimal mandatory manifest** a producer must deliver with each Java candidate package,
the platform's intake rules, and the mutation-regeneration capability requirement.

The platform does NOT specify — and must never depend on — model choice, prompts,
transformation internals, LLM frameworks, agent frameworks, or generation algorithms.

## 2. Producer Properties (binding on the platform's design)

| Property | Consequence |
|---|---|
| **External** | The producer is never a component of this platform |
| **Replaceable** | Swapping producers must not change validation architecture or verdicts |
| **Untrusted** | Producer output is input to validation, never evidence |
| **Producer-agnostic** | The platform validates candidates from any producer identically — LLM A, LLM B, another LLM, deterministic translator, human developer, hybrid pipeline |

Producer claims about its output (quality, coverage, "equivalent") are **metadata,
never validation evidence**. An LLM cannot certify its own transformation.

## 3. The Flow at the Boundary

```
COBOL workload (platform-provided source identity)
        ↓
Transformation Producer (external, out of scope)
        ↓
Java Candidate Package = plain Java source tree (JAVA_CANDIDATE_CONTRACT §2)
                        + mandatory producer manifest (§4 below)
        ↓
Platform intake (fail-closed validation of manifest + tree + hashes)
        ↓
Validation Engine (sole semantic trust boundary)
```

## 4. Mandatory Producer Manifest (V1)

The candidate package MUST include a manifest declaring:

| Field | Purpose | Notes |
|---|---|---|
| `producer_identity` + `producer_version` | Branding/provenance | Never evidence |
| `candidate_identity` | Candidate identity | Platform-assigned at intake if absent |
| `workload_identity` / source binding | Binds candidate to the COBOL workload | |
| `source_hash(es)` | Candidate↔source binding is checkable | Platform verifies against its own source hashes |
| `generated_files` list | Complete file inventory | Each file with its own hash |
| `entrypoint` | Main class; argument/stdin conventions | Consumed by JAVA_CANDIDATE_CONTRACT |
| `java_version` | Target version | |
| `dependency_declaration` | Empty or vendored in V1 | No resolution, no fetch |
| `runtime_requirements` | CWD, output conventions, env vars | |
| `generation_metadata` | Timestamp + transformation info | Informational only |
| `mutation_regeneration_capability` | Whether this producer can regenerate a candidate from mutated COBOL on demand | **Required declaration** (§6) |

**Intake rules (fail-closed):**

- Missing mandatory field ⇒ **package refused**. No guessing, no defaults, no partial
  acceptance.
- `source_hash` mismatch against the platform's known source identity ⇒ **refused**
  (the candidate does not belong to the declared workload).
- File-list/hash mismatch with the actual tree ⇒ **refused**.
- Extra undeclared files ⇒ flagged; anomaly recorded.

## 5. Optional Extensions (explicitly non-binding)

A producer MAY additionally supply semantic mappings, coverage reports, or other
transformation metadata. The platform MAY record these as provenance and display them,
but they are **never** consumed by comparators, verdicts, or certification. Their
absence never affects validation.

## 6. Mutation-Regeneration Capability (critical)

**Mutation validation requires the producer to regenerate a candidate from mutated
COBOL on demand** — the platform must NOT hand-edit Java as a substitute (that would
make the platform its own producer and break the ownership boundary).

Rules:

- The producer **declares** regeneration capability in the manifest (required field).
- If a producer cannot regenerate on demand: mutation validation for its candidates is
  capped at **`UNAVAILABLE`** — explicitly stated in the verdict, **never silently
  skipped, never faked, never hardcoded**. Per VERDICT_CONTRACT §7, a workload-run
  cannot reach `VERIFIED` without required mutation validation — so non-regenerating
  producers cannot achieve V1 certification for their candidates. This is the honest
  consequence, stated up front.
- Regenerated candidates pass through the **same** intake validation (hashes, manifest)
  — no fast-path, no trust by ancestry.

## 7. Co-Approval Gate

PD-04/PD-05 are joint decisions. Platform-side approval is recorded; **this contract
binds the producer interface only after the LLM integration owner co-approves**. Until
co-approval:

- The contract text is stable for engine design (intake, manifest validation, execution
  layer can be built against it).
- Real-producer integration and producer-side mutation regeneration remain gated.

## 8. Test-First Requirements (platform side)

| Test | Expected |
|---|---|
| Manifest missing mandatory field | Refusal (fail-closed) |
| `source_hash` mismatch | Refusal |
| File-list/tree mismatch | Refusal |
| Producer claim of equivalence supplied | Recorded as provenance only; verdict unchanged (test proves no effect) |
| Non-regenerating producer + mutation stage | `UNAVAILABLE`; never silent skip; verdict reflects it |
| Two producers, identical candidates | Identical validation treatment (producer-agnostic test) |
| Swapping producers | No architecture/verdict change beyond candidate identity |

## 9. Change Control

Version 1.0. Any change to mandatory fields, the candidate shape reference, or the
regeneration semantics requires: new contract version + ADR + joint re-approval.
