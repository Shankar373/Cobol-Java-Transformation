# Layer 12 design: Verification and verdict

Status: **audit complete (2026-11-26): L12-P1 and L12-P2 done, verdict derivation untouched.** From the Layer 11 closure. Deterministic, open source only, no LLM. This is a do-not-regress
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

## 3. L12-P2: an outcome cannot disagree with its declaration

`admit_report` verified the definition digest, the outcome/declaration id
sets and the recomputed `overall`, but never compared an outcome to the
declaration of the same id. A digest-correct report claiming
`expected=999, passed=true` for a declaration of `expected=0` was therefore
admitted as PASS (and compared as MATCH), and duplicate `invariant_id`s —
which `evaluate_invariants` refuses at build time — were admitted too.

Now `admit_report` refuses duplicate ids and requires every outcome's
`kind`, `phase` and `expected` to equal its own declaration; the comparator
turns that refusal into INCONCLUSIVE at `business_invariant_report`, so a
contradictory report can never reach MATCH. Red-first:
`tests/verification` 5 failed / 93 passed → 98 passed (four admission tests
plus one e2e: a contradictory candidate report yields INCONCLUSIVE, not
MATCH).

## 4. Audits without a code change

* `scripts/e2e/verify_independent.py`, audited line by line: no gap. A
  non-zero compile exit, an undecodable image (it keeps its own name rather
  than being dropped), a missing or duplicated jar and an exception all land
  short of AGREE; per-record output is folded into the compared `files` map
  as `name#records`; stdout/stderr are compared as full bytes (the 600/300
  truncation is evidence-only); images are pinned to immutable ids; the build
  runs `mvn -o` under `--network none`.
* `engine/verification/business_invariants.py` evaluation path: no gap found.
  Missing sources, non-UTF-8 text, malformed JSON, an unresolvable
  `json_path`, an indivisible or empty record file, an out-of-range
  `record_index` and a non-integer fixed field all fail the invariant rather
  than passing it; floats are rejected at declaration time so no comparison
  depends on IEEE-754 rounding; an empty invariant set cannot build a report
  (no vacuous pass).
* `engine/verification/validation_summary.py`: a report view, never a verdict source; PASS only when every comparator MATCHes with no skipped or
  unavailable check and at least one executed check; it always lists what is not proven (no IBM runtime, one recorded input, no REST verification).

## 5. Limits

* `admit_report` cannot re-derive `passed`: it trusts the outcome booleans
  once they are structurally consistent with their declarations. Forging a
  coherent report is the manifest seal's job (Layers 10/13), not this module's.
* The Docker lane was not run locally on this change; `tests/verification`
  and the certification workflow cover it on CI.
