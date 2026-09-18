# ARTIFACT CONTRACT SPEC — V1

> **Status:** AUTHORITATIVE (approved via ADR-0002 + ADR-0006 / PD-02 + PD-03).
> Contract version: **1.0**. Implementation is a later phase.
> Authority chain: [PHASE1B_OWNER_APPROVALS.md](../decisions/PHASE1B_OWNER_APPROVALS.md)
> → [ADR-0002, ADR-0006](../decisions/ADR-0001_0004.md) → this contract.

---

## 1. Purpose

Every artifact participating in business equivalence MUST have a declared, validated
contract **before** comparison. Comparison without a valid contract is architecturally
impossible (explicit `NO_CONTRACT` refusal) — **there is no fallback comparison, ever**.

Core rule: **physical representation ≠ business semantics.** A contract declares each
side's physical representation, the logical (business) representation, and the
extraction strategy mapping between them. Comparison operates on the declared logical
representation.

## 2. V1 Artifact Type Registry (CLOSED — ADR-0006)

The V1 registry contains **exactly** these five compared-artifact types:

| Type | Compared as | Notes |
|---|---|---|
| `STDOUT` | Process stdout bytes | CRLF normalization only where contract declares it |
| `STDERR` | Process stderr bytes | Never hardcoded MATCH; always actually compared |
| `EXIT_STATUS` | Observed process exit code | Missing exit code is never "0" |
| `TEXT_FILE` | Text file bytes under declared normalization | |
| `FIXED_RECORD` | Fixed-length record sequence | Record-level + byte-level comparison |

**Evidence-envelope fields (captured, never compared as artifacts):** execution metadata,
hashes, sizes, record counts, timing, termination information.

**Excluded from V1 (fail closed as `UNSUPPORTED`, stated in verdict):**

| Type | Excluded by |
|---|---|
| `INDEXED`, `KSDS`, `RELATIVE`, `RRDS`, `ESDS` (content) | ADR-0002 (V1 exclusion; V2 oracle-stage dump) |
| `DATABASE_STATE`, `SQLCODE`, `SQLSTATE`, SQL artifacts | ADR-0007 (V1 exclusion) |
| `SEQUENTIAL` (variable-length), `BINARY` (opaque), `TRANSACTION_STATE`, `ERROR_STATE` | Not in the V1 registry — future versioned additions |

The registry is **closed**: adding a type is a versioned contract change (new contract
version + ADR), never silent growth. No generic comparator may ever run on any type.

> **PERMANENTLY FORBIDDEN (ADR-0002):** substring containment as a general equivalence
> strategy — for INDEXED, RELATIVE, KSDS, RRDS, structured records, database state, or
> any semantic structured artifact. This prohibition survives all future versions.

## 3. Artifact Contract Fields (schema v1.0)

Every artifact contract declares:

| Field | Requirement |
|---|---|
| `artifact_id` | Platform-assigned, globally unique |
| `workload_id` | Binding to workload identity |
| `execution_id` | Binding to the producing execution |
| `producer_role` | `ORACLE` \| `CANDIDATE` |
| `artifact_type` | One of the five registry types |
| `logical_name` | Stable name within the workload contract (e.g., `STDOUT`, `OUTPUT-FILE`) |
| `location` | Path/logical location within the execution workspace |
| `media_type` / `encoding` | e.g., `text/plain; charset=ISO-8859-1`, `application/octet-stream` |
| `size_bytes` | Observed size |
| `record_count` | Where applicable (`FIXED_RECORD`) |
| `content_hash` | SHA-256 of content |
| `captured_at` | Execution-bound timestamp |
| `environment_id` | Binding to environment identity |
| `contract_version` | Schema version of this contract |
| `completeness` | `COMPLETE` \| `MISSING` \| `MALFORMED` |
| `provenance` | Producing execution + capture mechanism identity |

**Comparison-policy block (per artifact):**

| Field | Requirement |
|---|---|
| `comparator_id` + `comparator_version` | Which registered comparator applies |
| `normalization_policy` | **Explicitly enumerated permitted normalizations** (e.g., CRLF→LF) — anything not listed is forbidden |
| `ordering_policy` | Where record order is significant (FIXED_RECORD) |
| `failure_policy` | Fail-closed state on missing/malformed/unsupported |

## 4. Identity and Binding Rules

- **Oracle vs candidate identity:** each artifact is bound to exactly one producing
  execution via `producer_role` + `execution_id`. Cross-role ambiguity is
  schema-invalid.
- **Workload binding:** both sides' artifacts for a comparison must bind to the same
  `workload_id` and the same declared input identity; otherwise the comparison is
  refused (`identity_mismatch`), not warned.
- **Missing artifact semantics:** `completeness = MISSING` contributes an explicit
  artifact-level failure (`UNAVAILABLE`/`FAILED` per the contract's failure policy) —
  **never** empty-but-successful, never silently skipped.
- **Duplicate artifact semantics:** duplicate `artifact_id` (or duplicate
  logical_name within one execution) is an **intake error** — not last-wins, not
  ignored.
- **Unsupported type semantics:** a type outside the registry yields `UNSUPPORTED` for
  that artifact — no fallback comparator, no guessed comparison, stated in the verdict.
- **Wrong hash / wrong identity / wrong type / wrong encoding:** contract validation
  fails closed with the specific violation recorded as evidence.

## 5. Validation Rules (enforced before any comparison)

1. Contract present and schema-valid — else `NO_CONTRACT` refusal.
2. `artifact_type` ∈ registry — else `UNSUPPORTED`.
3. Producer/execution/workload bindings consistent — else `identity_mismatch`.
4. `completeness = COMPLETE` — else the artifact's failure policy applies.
5. Content hash matches observed bytes — else `MALFORMED` (tamper/transfer detection).
6. Declared encoding matches observed bytes — else `MALFORMED`.

## 6. Content-Addressing (ADR-0008 / DR-16)

Artifact content is stored **content-addressed by SHA-256**; the manifest references
hashes. Two artifacts with identical content share storage; identity remains distinct.

## 7. Test-First Requirements (for implementation)

| Test | Expected |
|---|---|
| Missing artifact | `MISSING` + failure policy state; never empty-success |
| Duplicate artifact | Intake error; comparison refused |
| Wrong hash | `MALFORMED`; verdict capped below `VERIFIED` |
| Wrong identity binding | `identity_mismatch`; comparison refused |
| Wrong type (outside registry) | `UNSUPPORTED`; no fallback comparator |
| Wrong encoding | `MALFORMED` |
| Incomplete artifact | Failure policy; never green |
| No contract | `NO_CONTRACT` refusal — comparison impossible |
| Substring containment anywhere in a comparator | Prohibited by design; comparator registry contains no such strategy (static architecture test) |

## 8. Change Control

Version 1.0. Adding artifact types (e.g., the V2 INDEXED/RELATIVE logical representation
per ADR-0002, or SQL artifacts per ADR-0007's V2 entry criteria) requires: a new
contract version, an ADR, and comparator + mutation proofs for the new type **before**
any verdict may rest on it.
