# COMPARATOR SPECIFICATION — V1

> **Status:** SPECIFICATION (Phase 1C foundation). This document defines the comparator
> subsystem design. Implementation is a later phase. Specification version: **1.0**.
> Authority chain: [ARTIFACT_CONTRACT_SPEC.md](../../contracts/ARTIFACT_CONTRACT_SPEC.md)
> → this specification.

---

## 1. Purpose and Scope

This specification defines how the platform compares oracle-side and candidate-side
artifacts to determine behavioral equivalence. The comparator subsystem is part of the
**Validation Engine** (sole semantic trust boundary per DR-29).

**Scope (V1):** comparison of exactly five artifact types defined in the V1 Artifact
Type Registry (ARTIFACT_CONTRACT_SPEC §2). No comparator may run on any artifact type
not in the registry.

**Out of scope (V1):** INDEXED/RELATIVE content comparison, SQL/database state
comparison, variable-length SEQUENTIAL comparison, BINARY opaque comparison,
TRANSACTION_STATE comparison. These are deferred to future versioned contract extensions.

## 2. Relationship to ARTIFACT_CONTRACT_SPEC

The artifact contract defines:
- Which artifact types exist (registry)
- How artifacts are identified, bound, and validated
- Contract fields and validation rules

This comparator specification defines:
- How validated artifacts are compared
- Comparison semantics per artifact type
- Evidence emitted by comparisons
- Normalization, ordering, and field-level rules

**Critical invariant:** comparison operates on the **logical representation** declared
in the artifact contract, not on raw physical bytes. The artifact contract declares the
extraction strategy; the comparator consumes the extracted logical form.

## 3. Typed Comparator Registry (CLOSED — V1)

The V1 comparator registry contains **exactly five** comparators, one per artifact type.
Adding a comparator is a versioned contract change (new contract version + ADR), never
silent growth.

| Comparator ID | Artifact Type | Comparison Strategy |
|---|---|---|
| `STDOUT_COMPARATOR` | `STDOUT` | Byte-level with normalization |
| `STDERR_COMPARATOR` | `STDERR` | Byte-level with normalization |
| `EXIT_STATUS_COMPARATOR` | `EXIT_STATUS` | Exact integer equality |
| `TEXT_FILE_COMPARATOR` | `TEXT_FILE` | Byte-level with normalization |
| `FIXED_RECORD_COMPARATOR` | `FIXED_RECORD` | Record-level + byte-level |

**No generic fallback comparator exists.** If no registered comparator matches the
artifact type, the comparison is refused with `UNSUPPORTED` — never guessed, never
silently skipped, never approximated.

## 4. Comparator Interface/Contract

Every comparator MUST implement:

| Method | Requirement |
|---|---|
| `compare(oracle_artifact, candidate_artifact) → ComparisonResult` | Deterministic, reproducible, side-effect-free |
| `supported_types() → Set[ArtifactType]` | Returns exactly the types this comparator handles |
| `version() → str` | Semantic version of the comparator implementation |

**ComparisonResult schema:**

```json
{
  "comparator_id": "string",
  "comparator_version": "string",
  "oracle_artifact_id": "string",
  "candidate_artifact_id": "string",
  "result": "MATCH | MISMATCH | INCONCLUSIVE",
  "details": {
    "differences": ["string"],
    "normalization_applied": ["string"],
    "field_level_results": ["object"]
  },
  "evidence_hash": "sha256:..."
}
```

**Result states:**

| State | Meaning |
|---|---|
| `MATCH` | Artifacts are equivalent under this comparator's rules |
| `MISMATCH` | Artifacts demonstrably differ |
| `INCONCLUSIVE` | Comparison could not complete (malformed input, partial capture) |

## 5. V1 Comparison Semantics (per artifact type)

### 5.1 STDOUT Comparator

**Strategy:** byte-level comparison with declared normalizations.

**Normalization rules (exhaustive — anything not listed is forbidden):**

| Normalization | Condition | Rule |
|---|---|---|
| CRLF → LF | If declared in artifact contract's `normalization_policy` | Replace `\r\n` with `\n` before comparison |
| Trailing whitespace | NEVER (not in V1 normalization policy) | Raw bytes |
| Trailing newline | NEVER (not in V1 normalization policy) | Raw bytes |
| Encoding normalization | NEVER | Declared encoding must match observed bytes |

**Ordering:** byte-level; no record ordering (stream of bytes).

**Missing STDOUT on one side:** artifact contract's `failure_policy` applies →
`UNAVAILABLE`/`FAILED`; comparison is not attempted.

**Extra STDOUT on one side:** recorded as `MISMATCH` (unexpected output is a difference).

**Malformed STDOUT:** `INCONCLUSIVE`; verdict capped below `VERIFIED`.

### 5.2 STDERR Comparator

**Strategy:** byte-level comparison with declared normalizations.

**Normalization rules:** identical to STDOUT (§5.1).

**Critical rule:** STDERR is **never hardcoded as MATCH**. Every STDERR artifact is
actually compared. The predecessor silently passed STDStreams that differed (Lesson 12).

**Missing STDERR on one side:** if both sides produced empty STDERR, `MATCH`. If one
side produced STDERR and the other did not, `MISMATCH`.

**Extra STDERR on one side:** `MISMATCH`.

**Malformed STDERR:** `INCONCLUSIVE`.

### 5.3 EXIT_STATUS Comparator

**Strategy:** exact integer equality.

**Rules:**
- Oracle exit code must equal candidate exit code exactly.
- Missing exit code is **never "0"** — it is `MISSING` → artifact failure policy.
- Exit code is an observed process outcome, not a defaulted value.

**Missing exit code on one side:** artifact contract's `failure_policy` applies.

**Malformed exit code (non-integer):** `INCONCLUSIVE`.

### 5.4 TEXT_FILE Comparator

**Strategy:** byte-level comparison with declared normalizations.

**Normalization rules:** identical to STDOUT (§5.1), applied per-file.

**Ordering:** byte-level within each file; file identity by `logical_name`.

**Missing file on one side:** artifact contract's `failure_policy` applies.

**Extra file on one side:** recorded as `MISMATCH`.

**Multiple TEXT_FILE artifacts:** each compared independently; all must match for
overall `MATCH`.

### 5.5 FIXED_RECORD Comparator

**Strategy:** two-phase comparison — record-level then byte-level.

**Phase 1: Record count validation**
- Oracle record count must equal candidate record count.
- Missing record count → `INCONCLUSIVE`.

**Phase 2: Record-level comparison**
- Records compared in order (if `ordering_policy = SEQUENTIAL`) or after sorting
  (if `ordering_policy = SORTED`).
- Each record compared byte-level.

**Field-level comparison rules:**

| Rule | Requirement |
|---|---|
| Record boundary | Fixed-length records; boundary by declared `record_length` |
| Partial records | Trailing padding bytes compared if present; short records = `MALFORMED` |
| Byte-level | Exact byte equality within each record |
| Field extraction | NOT in V1 — field-level comparison is record-level only |

**Ordering semantics:**

| Policy | Behavior |
|---|---|
| `SEQUENTIAL` | Records compared in capture order |
| `SORTED` | Records sorted by a declared key before comparison |
| `UNORDERED` | Records compared as a multiset (any order matches) |

**Duplicate semantics:** duplicate records within one artifact are compared as-is;
no deduplication. If oracle has duplicates and candidate does not, `MISMATCH`.

**Missing records on one side:** artifact contract's `failure_policy` applies.

**Extra records on one side:** `MISMATCH`.

**Malformed records (wrong length):** `INCONCLUSIVE`.

## 6. Missing Artifact Behavior

| Scenario | Behavior |
|---|---|
| Oracle artifact MISSING, candidate artifact present | `MISMATCH` (unexpected candidate output) |
| Oracle artifact present, candidate artifact MISSING | Artifact contract `failure_policy` → `UNAVAILABLE`/`FAILED` |
| Both sides MISSING | Depends on artifact type: for STDOUT/STDERR, `MATCH` (both empty); for EXIT_STATUS/TEXT_FILE/FIXED_RECORD, `UNAVAILABLE` (required artifact absent) |

## 7. Extra Artifact Behavior

| Scenario | Behavior |
|---|---|
| Candidate produces artifact not in oracle | `MISMATCH` (unexpected output) |
| Oracle produces artifact not in candidate | `MISMATCH` (missing expected output) |
| Artifact type outside registry | `UNSUPPORTED` for that artifact; no comparison attempted |

## 8. Malformed Artifact Behavior

| Scenario | Behavior |
|---|---|
| Content hash mismatch (tamper detection) | `MALFORMED`; comparison refused |
| Encoding mismatch | `MALFORMED`; comparison refused |
| Record length mismatch (FIXED_RECORD) | `MALFORMED`; verdict capped |
| Truncated content | `INCONCLUSIVE`; verdict capped |
| Empty content where non-empty expected | Depends on artifact contract's `failure_policy` |

## 9. Normalization Rules (normative)

**Principle:** normalization is the **minimum necessary transformation** to make
physically identical content compare equal. Normalization never obscures semantic
differences.

**V1 permitted normalizations (exhaustive):**

| Normalization | Artifact Types | Rule |
|---|---|---|
| CRLF → LF | STDOUT, STDERR, TEXT_FILE | Replace `\r\n` with `\n` |

**Absolutely forbidden normalizations:**

| Normalization | Prohibition |
|---|---|
| Case folding | Never — COBOL is case-sensitive in specific contexts |
| Whitespace normalization | Never — whitespace is semantically significant |
| Encoding conversion | Never — declared encoding must match observed bytes |
| Trailing whitespace removal | Never |
| Trailing newline removal | Never |
| Substring containment | **PERMANENTLY FORBIDDEN** as general equivalence strategy (ADR-0002) |

## 10. Ordering Semantics

| Artifact Type | Ordering |
|---|---|
| STDOUT | Byte-level (no record ordering) |
| STDERR | Byte-level (no record ordering) |
| EXIT_STATUS | Single value (no ordering) |
| TEXT_FILE | Byte-level within each file |
| FIXED_RECORD | Per `ordering_policy` in artifact contract |

## 11. Duplicate Semantics

| Scenario | Behavior |
|---|---|
| Duplicate `artifact_id` in evidence | Intake error (ARTIFACT_CONTRACT §4) |
| Duplicate records within FIXED_RECORD | Compared as-is; no deduplication |
| Duplicate TEXT_FILE with same `logical_name` | Intake error |

## 12. Comparator Versioning

| Rule | Requirement |
|---|---|
| Version format | Semantic versioning (MAJOR.MINOR.PATCH) |
| MAJOR change | Incompatible comparison behavior change |
| MINOR change | Backward-compatible behavior addition |
| PATCH change | Bug fix, no behavior change |
| Version in evidence | Every comparison result includes `comparator_version` |
| Version binding | Verdict scope includes comparator versions (VERDICT_CONTRACT §4) |
| Upgrade path | New version → ADR → contract version bump → new comparator registered |

## 13. Evidence Emitted by Every Comparator

Every comparison produces evidence containing:

```json
{
  "comparison_id": "string (platform-assigned, globally unique)",
  "run_id": "string (binding to run)",
  "workload_id": "string (binding to workload)",
  "comparator_id": "string",
  "comparator_version": "string",
  "oracle_artifact_id": "string",
  "candidate_artifact_id": "string",
  "artifact_type": "string",
  "result": "MATCH | MISMATCH | INCONCLUSIVE",
  "normalization_applied": ["string"],
  "differences": ["string"],
  "field_level_results": ["object"],
  "evidence_hash": "sha256:...",
  "timestamp": "ISO-8601"
}
```

## 14. NO_CONTRACT Behavior

If no artifact contract exists for a comparison pair:

1. Comparison is **refused** — `NO_CONTRACT`.
2. The artifact contributes `UNPROVEN` to the verdict.
3. No fallback comparison is attempted.
4. No generic comparator runs.
5. The refusal is recorded as evidence.

**This is the most defensive failure mode.** The platform never compares artifacts
without explicit contracts.

## 15. UNSUPPORTED Behavior

If the artifact type is outside the V1 registry:

1. The artifact is marked `UNSUPPORTED`.
2. No comparator is invoked.
3. The verdict explicitly states the exclusion.
4. The verdict is capped below `VERIFIED` if the artifact is required by the workload.
5. No fallback to substring containment or any other approximation.

## 16. Prohibition of Generic Fallback Comparators

**Absolute prohibition:** no comparator may:

- Accept artifact types outside its declared `supported_types()`
- Fall back to byte-level comparison for structured artifacts
- Use substring containment for any semantic comparison
- Approximate, guess, or infer equivalence
- Skip comparison and default to `MATCH`

If a registered comparator cannot handle an artifact (malformed, truncated, wrong
encoding), it returns `INCONCLUSIVE` — never `MATCH`, never `MISMATCH`, never skipped.

## 17. Absolute Prohibition of Substring Containment

**PERMANENTLY FORBIDDEN (ADR-0002):** substring containment as a general equivalence
strategy. This prohibition:

- Applies to all artifact types, all comparators, all versions
- Survives all future contract versions
- Is enforceable as a static architecture test (no comparator implementation may
  contain substring-matching logic for semantic comparison)
- Was proven to produce false-PASS in the predecessor (7/10 adversarial cases wrongly
  green)

## 18. Deterministic/Reproducible Comparison Requirements

| Requirement | Rule |
|---|---|
| Determinism | Same inputs → same result, always (no randomness, no timestamps, no env vars) |
| Reproducibility | Same evidence → same verdict, across runs and platforms |
| Idempotency | Comparing the same artifacts twice → same result |
| No side effects | Comparator does not modify artifacts, evidence, or state |
| Pure function | Result depends only on input artifacts and comparator version |

## 19. Negative Test Requirements

Every comparator MUST have negative tests proving:

| Test | Expected |
|---|---|
| Identical artifacts → MATCH | Proves positive path works |
| Single-byte difference → MISMATCH | Proves detection works |
| Missing artifact → appropriate failure state | Proves missing handling works |
| Malformed artifact → INCONCLUSIVE | Proves malformed handling works |
| Wrong artifact type → refusal | Proves type enforcement works |
| Substring containment attempted → blocked | Proves prohibition is enforced (architecture test) |
| Normalization not in policy → raw comparison | Proves normalization enforcement |

## 20. Metamorphic/Adversarial Cases

| Case | Expected |
|---|---|
| Oracle and candidate produce same output in different order (FIXED_RECORD, UNORDERED) | `MATCH` if multiset equality holds |
| Oracle and candidate produce same output with different whitespace | `MISMATCH` (whitespace is significant) |
| Candidate produces empty output where oracle produces non-empty | `MISMATCH` |
| Candidate produces extra output beyond oracle | `MISMATCH` |
| Both sides produce identical binary-identical output | `MATCH` |
| Output differs only in trailing newline | `MISMATCH` (trailing newline not normalized) |
| Output differs only in CRLF vs LF | `MATCH` if CRLF→LF normalization declared |

## 21. Explicit V1 Exclusions

The following are explicitly excluded from V1 comparison:

| Exclusion | Reason | Future Version |
|---|---|---|
| INDEXED/RELATIVE content | ADR-0002: V1 exclusion; V2 oracle-stage dump | V2 |
| SQL/database state | ADR-0007: V1 exclusion | V2 |
| VARIABLE-LENGTH SEQUENTIAL | Not in V1 registry | Future |
| BINARY opaque | Not in V1 registry | Future |
| TRANSACTION_STATE | Not in V1 registry | Future |
| ERROR_STATE | Not in V1 registry | Future |
| Field-level extraction within FIXED_RECORD | V1 is record-level only | Future |

---

**End of COMPARATOR SPECIFICATION V1.**
