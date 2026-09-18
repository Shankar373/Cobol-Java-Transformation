# EVIDENCE SPECIFICATION — V1

> **Status:** SPECIFICATION (Phase 1C foundation). This document defines the evidence
> subsystem design. Implementation is a later phase. Specification version: **1.0**.
> Authority chain: [VERDICT_CONTRACT.md](../../contracts/VERDICT_CONTRACT.md) →
> [ORACLE_CONTRACT.md](../../contracts/ORACLE_CONTRACT.md) →
> [ARTIFACT_CONTRACT_SPEC.md](../../contracts/ARTIFACT_CONTRACT_SPEC.md) →
> this specification.

---

## 1. Purpose

Evidence is the platform's **only source of truth**. A verdict is a pure function of an
evidence manifest (VERDICT_CONTRACT §3). This specification defines the evidence object
model, integrity requirements, and rules that make evidence fabrication architecturally
impossible.

**Core invariant:** evidence is recorded, never manufactured. If something was not
observed, there is no evidence of it. Absence of evidence is never evidence of absence
or equivalence.

## 2. Evidence Object Model

### 2.1 Evidence Envelope

Every evidence object is wrapped in an envelope containing:

```json
{
  "evidence_id": "string (platform-assigned, globally unique)",
  "evidence_type": "string (enum of evidence types)",
  "schema_version": "string (e.g., '1.0')",
  "created_at": "ISO-8601 timestamp",
  "content_hash": "sha256:... (hash of the evidence content)",
  "content": "object (type-specific evidence payload)"
}
```

### 2.2 Evidence Types (V1)

| Evidence Type | Source | Content |
|---|---|---|
| `oracle_execution` | ORACLE_CONTRACT §5 | Oracle execution record |
| `candidate_execution` | JAVA_CANDIDATE_CONTRACT §5 | Candidate execution record |
| `artifact_capture` | ARTIFACT_CONTRACT_SPEC §3 | Artifact capture record |
| `artifact_contract_validation` | ARTIFACT_CONTRACT_SPEC §5 | Contract validation result |
| `comparison_result` | COMPARATOR_SPEC §13 | Comparator output |
| `mutation_result` | Future MUTATION_SPEC | Mutation validation result |
| `verdict_derivation` | VERDICT_CONTRACT §7 | Verdict derivation record |

## 3. Workload/Run Identity

Every evidence object is bound to exactly one workload-run:

| Field | Requirement |
|---|---|
| `run_id` | Platform-assigned, globally unique identifier for this validation run |
| `workload_id` | Binding to the workload being validated |
| `run_timestamp` | When the run was initiated |
| `run_status` | `RUNNING` \| `COMPLETED` \| `FAILED` \| `TIMEOUT` |

**Invariant:** one `run_id` → one workload → one complete evidence manifest → one
verdict. No evidence sharing across runs. No verdict reuse across runs.

## 4. Source Identity/Hash

The COBOL source being validated carries an identity that MUST appear in evidence:

| Field | Requirement |
|---|---|
| `source_id` | Platform-assigned workload identifier |
| `source_hash` | SHA-256 of the complete source tree (all files, recursively) |
| `source_hash_algorithm` | `sha256` (fixed in V1) |
| `source_tree_manifest` | List of all source files with individual hashes |
| `source_timestamp` | When the source was captured |

**Invariant:** source hash is computed BEFORE execution and verified UNCHANGED after
execution (ORACLE_CONTRACT §4.1). A changed source tree invalidates the run.

## 5. Candidate Identity/Hash

The Java candidate being validated carries an identity that MUST appear in evidence:

| Field | Requirement |
|---|---|
| `candidate_id` | Platform-assigned or producer-declared identifier |
| `candidate_hash` | SHA-256 of the complete candidate tree (all files, with individual hashes) |
| `candidate_hash_algorithm` | `sha256` (fixed in V1) |
| `candidate_tree_manifest` | List of all candidate files with individual hashes |
| `producer_identity` | Producer identity + version (metadata, never evidence) |
| `generation_timestamp` | When the candidate was generated |

**Invariant:** candidate hash is computed at intake and bound into all evidence and
verdict scope (VERDICT_CONTRACT §4). Identity change ⇒ new verdict run required.

## 6. Oracle Identity/Image Digest

The oracle carries a mandatory identity (ORACLE_CONTRACT §2):

| Field | Requirement |
|---|---|
| `oracle_id` | Adapter identity (V1: `gnucobol-3.1.2`) |
| `image_digest` | **Digest pin (sha256:...) — NEVER a mutable tag** |
| `compiler_version` | Captured `cobc --version` output (from execution) |
| `preprocessor_version` | OCESQL version where used |
| `base_image` | Base image identity |

**Invariant:** an oracle identity without a digest is schema-invalid. Reference by
`:latest` is prohibited (predecessor defect: mutable tags silently changed the oracle).

## 7. Runtime Identity

The execution environment carries an identity:

| Field | Requirement |
|---|---|
| `runtime_id` | Platform-assigned runtime environment identifier |
| `runtime_type` | `oracle` \| `candidate` |
| `container_image` | Digest-pinned image reference |
| `java_version` | For candidate: JDK version used |
| `cobol_compiler` | For oracle: GnuCOBOL version |
| `os_base` | Base OS (e.g., Alpine 3.19) |
| `network_policy` | V1: `none` |
| `resource_limits` | Memory, CPU, PIDs limits |

## 8. Controlled Input Identity

Inputs to the execution carry an identity:

| Field | Requirement |
|---|---|
| `input_id` | Platform-assigned input identifier |
| `input_type` | `stdin` \| `file` \| `mixed` |
| `stdin_hash` | SHA-256 of stdin bytes (if applicable) |
| `input_files` | List of input file paths with hashes |
| `input_hash` | Combined hash of all inputs |

**Invariant:** oracle and candidate receive IDENTICAL inputs (differential requirement).
Input identity is bound into evidence and verdict scope.

## 9. Artifact Identity

Each captured artifact carries an identity (per ARTIFACT_CONTRACT_SPEC §3):

| Field | Requirement |
|---|---|
| `artifact_id` | Platform-assigned, globally unique |
| `artifact_type` | One of the five V1 registry types |
| `logical_name` | Stable name within the workload contract |
| `producer_role` | `ORACLE` \| `CANDIDATE` |
| `content_hash` | SHA-256 of artifact content |
| `size_bytes` | Observed size |
| `record_count` | Where applicable (FIXED_RECORD) |

## 10. SHA-256 Content Addressing

All content addressing uses SHA-256 (ADR-0008 / DR-16):

| Content | Hash |
|---|---|
| Source tree | SHA-256 over all source files |
| Candidate tree | SHA-256 over all candidate files |
| Each artifact | SHA-256 of artifact content |
| Evidence objects | SHA-256 of evidence content |
| Oracle image | Digest-pinned by SHA-256 |

**Storage rule:** content-addressed storage — two objects with identical content share
storage; identity remains distinct.

## 11. Execution Provenance

Every execution record contains complete provenance (ORACLE_CONTRACT §5,
JAVA_CANDIDATE_CONTRACT §5):

| Field | Requirement |
|---|---|
| `execution_id` | Platform-assigned, globally unique |
| `run_id` | Binding to the validation run |
| `runtime_id` | Binding to the execution environment |
| `command` | Verbatim command executed |
| `environment` | Environment variables (explicit set), working directory |
| `input` | Controlled input identity (§8) |
| `start_time` | Execution start timestamp |
| `end_time` | Execution end timestamp |
| `exit_code` | Observed process exit code |
| `stdout` | Captured bytes (reference to content-addressed storage) |
| `stderr` | Captured bytes (reference to content-addressed storage) |
| `generated_files` | Every file produced, with per-file SHA-256 |
| `source_tree_hash_before` | Source hash before execution |
| `source_tree_hash_after` | Source hash after execution (immutability proof) |
| `termination_status` | `normal` \| `timeout` \| `nonzero_exit` \| `error` |

## 12. Timestamps

All timestamps are ISO-8601 UTC. Required timestamps:

| Timestamp | When |
|---|---|
| `run_timestamp` | Run initiation |
| `source_capture_timestamp` | Source tree captured |
| `candidate_intake_timestamp` | Candidate package received |
| `execution_start_time` | Process started |
| `execution_end_time` | Process ended |
| `artifact_capture_time` | Artifact captured from execution |
| `comparison_timestamp` | Comparison executed |
| `verdict_timestamp` | Verdict derived |

## 13. Commands

Every executed command is recorded verbatim as evidence:

| Field | Requirement |
|---|---|
| `command_string` | Exact command line executed |
| `working_directory` | CWD during execution |
| `environment_variables` | Explicit env vars (never inherited implicitly) |
| `timeout_applied` | Whether a hard timeout was enforced |
| `timeout_duration` | Timeout value if enforced |

## 14. Exit Status

The observed process exit code is recorded as evidence:

| Field | Requirement |
|---|---|
| `exit_code` | Integer exit code (observed, never defaulted) |
| `exit_code_source` | `process_observation` (never `configuration_inference`) |
| `termination_status` | `normal` \| `timeout` \| `nonzero_exit` \| `error` |

**Critical rule:** missing exit code is NOT "0". Missing exit code is `MISSING` →
artifact failure policy.

## 15. Stdout/Stderr References

Captured output streams are stored content-addressed:

| Field | Requirement |
|---|---|
| `stdout_hash` | SHA-256 of stdout bytes |
| `stdout_size` | Byte count |
| `stdout_reference` | Content-addressed storage path |
| `stderr_hash` | SHA-256 of stderr bytes |
| `stderr_size` | Byte count |
| `stderr_reference` | Content-addressed storage path |

**Invariant:** empty output is still captured and hashed. Missing output is NOT
"empty" — it is `MISSING`.

## 16. Generated Artifact References

Every file produced by an execution is recorded:

| Field | Requirement |
|---|---|
| `file_path` | Relative path within execution workspace |
| `file_hash` | SHA-256 of file content |
| `file_size` | Byte count |
| `file_type` | MIME type or `application/octet-stream` |
| `capture_timestamp` | When the file was captured |

## 17. Comparator Evidence

Every comparison produces evidence (per COMPARATOR_SPEC §13):

| Field | Requirement |
|---|---|
| `comparison_id` | Platform-assigned, globally unique |
| `comparator_id` | Which comparator was used |
| `comparator_version` | Version of the comparator |
| `oracle_artifact_id` | Binding to oracle artifact |
| `candidate_artifact_id` | Binding to candidate artifact |
| `result` | `MATCH` \| `MISMATCH` \| `INCONCLUSIVE` |
| `normalization_applied` | List of normalizations applied |
| `differences` | List of differences found |
| `field_level_results` | Per-field results (FIXED_RECORD) |

## 18. Mutation Evidence

Mutation validation evidence (definition deferred to MUTATION_SPEC; requirements):

| Field | Requirement |
|---|---|
| `mutation_id` | Which mutation was applied |
| `mutated_source_hash` | Hash of the mutated COBOL source |
| `regenerated_candidate_hash` | Hash of the candidate regenerated from mutated source |
| `mutation_detection_result` | Whether the mutation was detected |
| `comparison_evidence` | Evidence from the comparison of mutated output vs oracle |

**Critical rule:** mutation regeneration requires the producer to regenerate on demand
(TRANSFORMATION_PRODUCER_CONTRACT §6). The platform never hand-edits Java.

## 19. Completeness

An evidence manifest is **complete** when ALL of the following hold:

| Requirement | Verification |
|---|---|
| Oracle execution evidence present | `oracle_execution` evidence exists |
| Candidate execution evidence present | `candidate_execution` evidence exists |
| All contract-declared artifacts captured | Each artifact has `artifact_capture` evidence |
| All contract validations passed | Each artifact has `artifact_contract_validation` evidence |
| All required comparisons executed | Each comparison has `comparison_result` evidence |
| Required mutation validation present | `mutation_result` evidence exists |
| No evidence hashes are `null` | Every evidence object has a `content_hash` |

**Incomplete manifest → verdict capped below VERIFIED** (VERDICT_CONTRACT §7).

## 20. Integrity Checks

Evidence integrity is verified by:

| Check | Rule |
|---|---|
| Content hash verification | Every evidence object's `content_hash` matches its `content` |
| Chain of binding | `run_id`, `workload_id`, `execution_id` chains are consistent |
| Identity binding | Source, candidate, oracle identities match across evidence |
| Temporal ordering | Timestamps are internally consistent |
| No fabrication | Every evidence object traces to an observed event |

## 21. Evidence Immutability Expectations

| Rule | Requirement |
|---|---|
| Write-once | Evidence objects are never modified after creation |
| Content-addressed | Hash is the identity; modification changes the hash |
| Append-only | Evidence manifest grows, never shrinks |
| No deletion | Evidence is never removed from a completed run |
| No overwriting | Evidence is never replaced |

## 22. Reconstruction Requirements

A verdict MUST be **reconstructable from evidence**:

| Requirement | Rule |
|---|---|
| Complete manifest | All evidence present |
| Independent verification | Any party with the same evidence can re-derive the verdict |
| No hidden state | Verdict depends only on evidence manifest, nothing else |
| No external dependencies | Verdict reconstruction requires no network, no configuration, no environment |
| Deterministic derivation | Same evidence → same verdict, always |

## 23. Tamper/Missing/Truncation Detection

| Scenario | Detection | Consequence |
|---|---|---|
| Evidence content tampered | Content hash mismatch | Evidence invalid; verdict `ERROR` |
| Evidence object missing | Manifest completeness check fails | Verdict capped below `VERIFIED` |
| Evidence truncated | Hash mismatch or schema validation failure | Evidence invalid; verdict `ERROR` |
| Evidence fabricated (not observed) | No corresponding execution record | Evidence invalid; verdict `ERROR` |
| Evidence reused across runs | Run ID mismatch | Evidence invalid; verdict `ERROR` |

## 24. Stale Evidence Handling

**V1 rule (ADR-0008 / DR-17):** the oracle is re-executed fresh every run. No baseline
reuse. Staleness is structurally excluded.

| Scenario | Handling |
|---|---|
| Oracle re-executed with same source | Fresh evidence; identity binding verified |
| Candidate identity changed | New run required; old evidence invalid |
| Oracle image digest changed | New run required; old baselines invalid |
| Comparator version changed | New run required; old comparison evidence invalid |

**Future (V2+):** if baseline reuse is introduced, staleness detection requires:
- Evidence timestamp freshness checks
- Identity binding re-verification
- Explicit staleness flags in evidence

## 25. Identity Mismatch Handling

| Scenario | Detection | Consequence |
|---|---|---|
| Source hash mismatch across evidence | Identity check fails | Run invalid; verdict `ERROR` |
| Candidate hash mismatch across evidence | Identity check fails | Run invalid; verdict `ERROR` |
| Oracle digest mismatch across evidence | Identity check fails | Run invalid; verdict `ERROR` |
| Workload ID mismatch | Binding check fails | Evidence refused; verdict `ERROR` |
| Execution ID mismatch | Chain check fails | Evidence refused; verdict `ERROR` |

## 26. Relationship Between Evidence and Verdict

```
Evidence Manifest
      ↓
Verdict Engine (pure function)
      ↓
Verdict
```

**Rules:**

1. Verdict is a **pure function** of evidence manifest (VERDICT_CONTRACT §3).
2. Verdict depends on **nothing else** — no configuration, no environment, no
   external state, no human judgment.
3. Verdict is **monotone** — can only downgrade, never upgrade (VERDICT_CONTRACT §5).
4. Verdict carries **complete scope** — identity of all inputs (VERDICT_CONTRACT §4).
5. Verdict is **reconstructable** — any party with the same evidence re-derives
   the same verdict.

## 27. Explicit Rules (normative)

### Rule: Verdict must be reconstructable from evidence

A verdict without its complete evidence manifest is schema-invalid. Any party with
the same evidence manifest MUST re-derive the same verdict.

### Rule: Environment/config presence is not execution evidence

The presence of `PGHOST`, `JAVA_HOME`, `cobc`, or any other configuration or
tool does NOT constitute evidence of execution. Status is derived ONLY from
observed state — probed, executed, captured (ORACLE_CONTRACT §3).

### Rule: Hardcoded evidence is forbidden

Every evidence value is **observed and recorded** — never hardcoded, never
defaulted, never fabricated. Missing exit code is NOT "0". Missing stderr is
NOT "empty-success". Missing evidence is NOT "PASS".

### Rule: Missing mandatory evidence blocks VERIFIED

If any mandatory evidence object is absent from the manifest, the verdict cannot
be `VERIFIED` (VERDICT_CONTRACT §7). The verdict is capped at the appropriate
non-VERIFIED state.

### Rule: Zero executed checks cannot become VERIFIED

`executed_check_count = 0` ⇒ verdict cannot be `VERIFIED`
(VERDICT_CONTRACT §5). This is architecture-impossible, not merely prohibited.

## 28. Evidence Manifest Schema (V1)

The complete evidence manifest for a workload-run:

```json
{
  "manifest_version": "1.0",
  "run_id": "string",
  "workload_id": "string",
  "source_identity": {
    "source_id": "string",
    "source_hash": "sha256:...",
    "source_tree_manifest": ["object"]
  },
  "candidate_identity": {
    "candidate_id": "string",
    "candidate_hash": "sha256:...",
    "candidate_tree_manifest": ["object"],
    "producer_identity": "string (metadata only)"
  },
  "oracle_identity": {
    "oracle_id": "string",
    "image_digest": "sha256:...",
    "compiler_version": "string",
    "preprocessor_version": "string"
  },
  "runtime_identities": ["object"],
  "controlled_input": "object",
  "execution_evidence": ["oracle_execution | candidate_execution"],
  "artifact_evidence": ["artifact_capture"],
  "contract_validation_evidence": ["artifact_contract_validation"],
  "comparison_evidence": ["comparison_result"],
  "mutation_evidence": ["mutation_result"],
  "verdict_derivation": "object",
  "manifest_hash": "sha256:...",
  "created_at": "ISO-8601"
}
```

## 29. Test-First Requirements (for implementation)

| Test | Expected |
|---|---|
| Complete evidence manifest → verdict derivable | Proves reconstruction works |
| Missing evidence → verdict capped below VERIFIED | Proves completeness enforcement |
| Fabricated evidence detected → verdict ERROR | Proves fabrication detection |
| Tampered evidence detected → verdict ERROR | Proves integrity checking |
| Identity mismatch detected → verdict ERROR | Proves binding enforcement |
| Same evidence → same verdict across runs | Proves determinism |
| Stale evidence detected → run invalid | Proves staleness handling |

---

**End of EVIDENCE SPECIFICATION V1.**
