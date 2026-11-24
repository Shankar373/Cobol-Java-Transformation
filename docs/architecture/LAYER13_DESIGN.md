# Layer 13 design: Evidence, contracts and audit trail

Status: **L13-P1 done (2026-11-24); audit continues.** From Layer 12 (audited, `119d236`). Deterministic, open source only, no LLM.
Scope: `engine/evidence/**`, `contracts/**`, `api/artifact_seal.py`.

## 1. Audit so far

* The sealed manifest's conditional keys (`capability_analysis`, `transformation_plan`, `java_generation`, `build_artifact`) are shape-checked and
  cross-bound by `EvidenceIntegrityValidator`; the legacy manifest hash is unchanged when they are absent.
* The artifact seal (`api/artifact_seal.py`) is tamper-*evidence* for filesystem substitution, taken after validation over every bundle file (including
  `target/`), and is stated not to be a signature.

## 2. Gap found and closed: L13-P1 the seal was not bound to the manifest

The seal and the manifest were two independent records of the same artifact: approval and export checked the bundle against the seal, and the manifest
against the verdict, but never the seal against the manifest. A source file or jar swapped *before* the post-validation seal was taken (after the
Layer 10 pre-build binding) would be sealed and then approved/served as the verified artifact while `java_generation.output_digest` and
`build_artifact.artifact_digest` described something else.

`api.artifact_seal.seal_binding_problem(seal, generation, build)` re-derives the project digest from the seal's file map (top-level `target/` left out,
the Layer 9 algorithm, shared via `generation_record.digest_of_files`) and compares it with `output_digest`; with a `build_artifact` record the seal must hold
`target/<artifact_name>` with exactly `artifact_digest`. `Service.require_verified_evidence` (the one gate before approval and export) calls it when the
run carries a seal and those records; a run without them (uploaded candidate, legacy run) is unchanged. Generation output and all hashes are untouched.

Tests: `tests/test_seal_manifest_binding.py` (12): bound bundle, edit/add/remove, substituted or missing jar, nested `target/` is source, malformed seal
refused, and the gate refuses/admits. **Risk stated:** the real Docker lane is not run locally; if the lane leaves extra top-level files in the bundle
the certification/full-integration workflows on this SHA will show it.

## 3. Next steps

Audit `contracts/**` against the code, and the evidence validator's remaining checks.
