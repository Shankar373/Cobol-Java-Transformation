# Trust Boundary

This document describes the implemented trust boundary between untrusted
input and the API response used for certification decisions. It is a
description of the code, not an aspiration.

## Pipeline

```
UNTRUSTED INPUT
    ↓
api.ingestion           (zip extraction, traversal/drive-letter rejection)
    ↓
pipeline evidence build (engine.pipeline)
    ↓
EvidenceIntegrityValidator.validate()   ← trust-boundary admission
    ↓                                     (violations → derive_untrusted,
    ↓                                      which never returns VERIFIED)
ValidatedEvidenceManifest
    ↓
derive_verdict_validated()  → deterministic Verdict
    ↓
Store.update_run            (lifecycle state machine, generation guard)
    ↓
serialization.encode_*      (versioned JSON envelope, Phase A seal)
    ↓
restart / reload
    ↓
Store.get_run               (envelope, schema version, field types, seal
    ↓                         re-verification — all fail closed)
Service.get_verdict         (verdict hash must match evidence manifest hash;
    ↓                         VERIFIED requires a persisted evidence manifest)
TRUSTED API RESPONSE
```

## Deterministic decision: nested workload identity

`ExecutionEvidence.workload_id` and `ComparisonEvidence.workload_id` are
optional; `ArtifactEvidence` has no workload field at all. The validator
enforces the binding **only when the field is populated** (an explicit,
mismatched workload id is a `WORKLOAD_BINDING_MISMATCH` violation).
Evidence without an explicit workload id binds **transitively**:
artifact → `execution_id` → execution `run_id` → manifest `workload_id`.

This is intentionally valid, because adapters may lack workload context;
transitive binding is pinned by `TestTransitiveWorkloadBinding` in
`tests/adversarial/test_phase_a_trust_hardening.py`.

## Evidence seal scope

`EvidenceManifest.sealed_hash` / `manifest_hash` are the hash of the
canonical evidence graph (`canonical_evidence_graph` in
`engine/evidence/models.py`). Deliberately excluded:

* `created_at` — construction timestamp, not evidence content;
* `verdict_evidence` — derivation output, never an input;
* `sealed_hash` itself;
* nested `ArtifactIdentity.content_hash` / `size_bytes` / `record_count`
  — the evidence-level `ArtifactEvidence.content_hash` is authoritative
  and is covered.

Any in-place mutation of a covered field is detected at decode time
(fail closed). An attacker who can **rewrite the whole record** —
evidence graph, re-seal, and verdict — consistently cannot be detected by
hash chaining alone; database files must be protected by filesystem
permissions and backups. Authenticated seals are future hardening, not a
current claim.

## Verdict / evidence consistency at retrieval

`Service._check_evidence_verdict_consistency` runs on every
`GET /runs/{id}/verdict` and `GET /runs/{id}/detail`, and at persist
time:

* `verdict.evidence_manifest_hash` must equal the evidence manifest's
  computed hash (a stale verdict from a different run/reset is rejected);
* a `VERIFIED` verdict with **no** persisted evidence manifest is
  rejected — certification always requires integrity-sealed evidence.

Non-certifying states (`UNPROVEN`, `FAILED`, `PARTIAL`, `UNAVAILABLE`,
`UNSUPPORTED`, `ERROR`) may be served without a manifest for backward
compatibility.

## Raw / unsafe derivation APIs

* `VerdictDeriver.derive()` / `derive_verdict()` accept raw manifests and
  bypass the validator — retained for tests only; no caller in `api/` or
  the production pipeline path.
* `derive_unsafe_from_raw()` is internal-only; the pipeline's error-override
  path clamps its result through `derive_untrusted()` so it can never
  certify `VERIFIED`.
* `engine/modernization/integrated_proof.py` re-validates the evidence
  manifest instead of trusting the verdict before opening the central
  certification gate.

## Revalidation and restart

* `POST /runs/{id}/validate` resets only terminal runs (single flight),
  atomically clearing evidence, verdict and error and incrementing
  `validation_generation`; stale background workers are rejected on write.
* On startup, non-terminal runs are failed once
  (`Store.mark_interrupted_runs`) because their daemon worker cannot
  survive a restart.
* Restart is a fresh `Store`/`Service` over the same SQLite file; all
  decode-time and retrieval-time guards re-run.

## Runtime-success alone cannot certify

`VERIFIED` requires: all artifacts compared, at least one comparison,
every comparison result in `{MATCH, MISMATCH, INCONCLUSIVE}` (unknown
results derive `ERROR`), complete executions, and — at derivation — a
clean `EvidenceIntegrityValidator` pass. Zero executed checks derive
`UNPROVEN`; incomplete or tampered evidence clamps through
`derive_untrusted` to `ERROR` (never `VERIFIED`).
