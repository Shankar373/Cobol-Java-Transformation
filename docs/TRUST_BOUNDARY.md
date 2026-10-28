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

## Generated-bundle seal (the on-disk artifact)

The manifest seal above covers the evidence graph, not the bytes a
customer downloads. `api/artifact_seal.py` covers those:

* `compute_generated_seal(root)` hashes every file of the bundle
  (chunked SHA-256, sorted POSIX-relative keys); the result is persisted
  on the run (`runs.generated_seal`). The lifecycle seals **twice** — an
  interim seal at generation and the authoritative seal at the end of
  validation, because the validation lane writes into the bundle
  (e.g. `target/*.jar`), so only the post-validation seal matches the
  approved bytes.
* `verify_generated_seal(root, seal_json)` returns `None` when the tree
  matches the persisted seal exactly, and refuses everything else:
  `ConflictError` (409) for a missing or malformed seal, an unsupported
  algorithm, or any difference in the file set / hashes (changed, added
  or removed files); `ServiceError` (400) when the current tree cannot be
  hashed at all. Both raise before the operation completes.
* Enforced at two points only: the customer `APPROVED` decision
  (`Service.set_run_approval` — a `REJECTED` decision must always work,
  even for a broken bundle) and `GET /runs/{id}/download`.

Trust anchor: the control-plane store, exactly like every other persisted
fact — an attacker who can rewrite the database can rewrite the seal too.
This protects the far likelier case: filesystem substitution of the
artifact between execution, approval and export.

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
  `validation_generation`; stale background workers are rejected on write
  (`Store.update_run` raises `ConflictError` when the stored generation
  moved on — a stale update is discarded, never merged).
* On startup, every run left non-terminal by a restart is failed once
  (`Store.mark_interrupted_runs` → stage `FAILED`, error
  "Interrupted by process restart before completion") because its daemon
  worker cannot survive the restart; the count is logged as
  `startup.reconciled`.
* Terminal writes are bounded, not forced: `Service._persist_final`
  retries `Store.update_run` 3 times (0.05 s doubling backoff), returns
  whether the write landed, and never raises. Success logs `run.terminal`;
  exhausting the retries logs `run.terminal_persist_failed` with
  `run_id`, `stage` and `attempts`.
* When the retry budget is spent **because a concurrent revalidation
  bumped `validation_generation`**, the stale write is accepted as lost —
  forcing it through would clobber the newer attempt. The run then stays
  non-terminal until the next restart's `Store.mark_interrupted_runs()`
  marks it `FAILED`, and that reconciliation is now logged loudly:
  `startup.reconciled`, or `startup.reconcile_failed` if the
  reconciliation itself throws.
* Every run lifecycle transition is logged with `run_id` —
  `run.started`, `run.revalidating`, `run.missing`, `run.failed`,
  `run.terminal`, `run.terminal_persist_failed` (grep lines in
  `docs/operations/RUNBOOK.md`); the database remains the source of
  truth, the log is the trail.
* Restart is a fresh `Store`/`Service` over the same SQLite file; all
  decode-time and retrieval-time guards re-run.

## Runtime-success alone cannot certify

`VERIFIED` requires: all artifacts compared, at least one comparison,
every comparison result in `{MATCH, MISMATCH, INCONCLUSIVE}` (unknown
results derive `ERROR`), complete executions, and — at derivation — a
clean `EvidenceIntegrityValidator` pass. Zero executed checks derive
`UNPROVEN`; incomplete or tampered evidence clamps through
`derive_untrusted` to `ERROR` (never `VERIFIED`).
