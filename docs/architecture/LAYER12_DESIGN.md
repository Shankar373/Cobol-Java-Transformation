# Layer 12 design: Verification and verdict

Status: **audited (2026-11-24); one test file added, no engine change; verdict derivation untouched.** From the Layer 11 closure. Deterministic, open source only, no LLM. This is a do-not-regress
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

## 2. L12-P1: sealed-record tamper never verifies (test only)

`tests/verdict/test_sealed_record_tamper_never_verifies.py`: the control manifest verifies; the same manifest carrying a malformed
`capability_analysis`, `transformation_plan`, `java_generation` or `build_artifact` is not admitted by the validator, and `derive_verdict_untrusted`
returns ERROR (never VERIFIED) with the violations surfaced. No defect found. Cross-binding mismatches (a well-shaped record disagreeing with another)
are pinned per layer in `tests/evidence/test_*_evidence.py`.

## 3. Audits without a code change

* `engine/verification/validation_summary.py`: a report view, never a verdict source; PASS only when every comparator MATCHes with no skipped or
  unavailable check and at least one executed check; it always lists what is not proven (no IBM runtime, one recorded input, no REST verification).

## 4. Limits

* `engine/verification/business_invariants.py` and `scripts/e2e/verify_independent.py` were not audited line by line; they are covered by
  `tests/verification/**` and the certification workflow.
