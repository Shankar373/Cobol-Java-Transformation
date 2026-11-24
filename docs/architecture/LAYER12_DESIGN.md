# Layer 12 design: Verification and verdict

Status: **audit started (2026-11-24), no code changed.** From the Layer 11 closure. Deterministic, open source only, no LLM. This is a do-not-regress
area (`engine/verdict/derivation.py`, `LAYER_MODEL.md` change rules).

Scope: `engine/verification/**`, `engine/verdict/**`, `scripts/e2e/verify_independent.py`. Output: a fail-closed verdict; a single `VERIFIED` derivation site.

## 1. Audit so far

* **One derivation site.** `VerdictState.VERIFIED` is assigned only in `VerdictDeriver.derive` (`engine/verdict/derivation.py`): errors, unavailable
  infrastructure, unsupported artifacts, an incomplete manifest, zero executed checks and an unrecognised comparison result all come first; any
  MISMATCH is FAILED, any INCONCLUSIVE is PARTIAL, and only an all-MATCH set is VERIFIED.
* **Trust boundary.** `derive_from_validated` re-checks the validation-time integrity hash against the live manifest hash (post-validation mutation
  gives ERROR); `derive_untrusted` clamps a natural VERIFIED to ERROR when integrity validation produced violations. The sealed Layer 7 to 10 records
  (`capability_analysis`, `transformation_plan`, `java_generation`, `build_artifact`) are checked by that validator, so a binding mismatch cannot certify.
* **Other "VERIFIED" strings are not the core verdict.** `engine/jcl/job_lane.py` grades its own jobs and `integrated_proof.py` reads those grades into a
  dependency ledger that states simulator-grade proof; neither writes the run's verdict.
* Existing coverage: `tests/verdict/**` (166 passed locally, 20 Docker skips).

## 2. Next steps (not started)

1. Probe the validator-to-verdict path for each sealed Layer 7 to 10 record with a tampered record end to end (expect ERROR, never VERIFIED).
2. Audit `engine/verification/**` (business invariants, validation summary) and `scripts/e2e/verify_independent.py`.
