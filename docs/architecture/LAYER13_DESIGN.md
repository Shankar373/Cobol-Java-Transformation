# Layer 13 design: Evidence, contracts and audit trail

Status: **audit complete (2026-11-25): L13-P1, L13-P2, L13-P3 done.** From Layer 12 (audited, `119d236`). Deterministic, open source only, no LLM.
Scope: `engine/evidence/**`, `contracts/**`, `api/artifact_seal.py`.

## 1. Audit so far

* The sealed manifest's conditional keys (`capability_analysis`, `transformation_plan`, `java_generation`, `build_artifact`) are shape-checked and
  cross-bound by `EvidenceIntegrityValidator`; the legacy manifest hash is unchanged when they are absent.
* The artifact seal (`api/artifact_seal.py`) is tamper-*evidence* for filesystem substitution, taken after validation over every bundle file (including
  `target/`), and is stated not to be a signature.
* **Evidence validator, remaining checks (2026-11-25).** Every check in `EvidenceIntegrityValidator.validate` was read end to end: run / workload /
  source-candidate / oracle / DialectProfile / semantic-facts / application-IR / capability-analysis / transformation-plan / java-generation /
  build-artifact bindings, comparison↔artifact pairing, comparator binding, comparison-result domain, source-tree mutation, `EXIT_STATUS`
  completeness, the construction-time seal, required-evidence coverage, and (new, §3) artifact↔execution role binding. No further gap found.
  The `EXIT_STATUS` completeness condition was checked against the adapters: candidates only ever record `normal` / `nonzero_exit` / `timeout` /
  `error` (`engine/candidate/java_adapter.py`, `docker_java_adapter.py`, `docker_spring_boot_adapter.py`), and the oracle records `return_code`
  only for its own program result (`classify_oracle_termination`), so `has_nonzero_candidate` covers every divergence that needs certifying; an
  oracle `nonzero_exit` is already UNAVAILABLE in the deriver.
* **Approval / export.** Both are gated by the single `Service.require_verified_evidence`, which re-derives the verdict from the validated manifest
  and (since L13-P1) checks the seal against the manifest. No separate admission path exists.

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

## 3. Gap found and closed: L13-P2 an artifact could name the wrong producing execution

`contracts/ARTIFACT_CONTRACT_SPEC.md` §4: "each artifact is bound to exactly one producing execution via `producer_role` + `execution_id`. Cross-role
ambiguity is schema-invalid." §5 rule 3 requires producer/execution bindings to be consistent.

The validator bound every artifact to an execution that exists in the same run, and required a comparison's oracle side to carry `producer_role ==
"ORACLE"` and its candidate side `"CANDIDATE"` — but never checked the two claims against each other. An artifact could label itself ORACLE while
naming the *candidate* execution that produced it.

That left a self-certification path (`tests/test_layer13_artifact_execution_role_binding.py::_cross_role`): every comparison is internally consistent
and MATCHes, yet no comparison ever pits oracle output against candidate output — one pair compares the candidate's bytes with the candidate's bytes,
the other compares the oracle's bytes with the oracle's bytes. Required evidence is satisfied because it counts artifacts by *execution id*
(`_validate_required_evidence`) while pairing counts them by *role*, so the two notions of "which side is this" disagree. The manifest validated and
derived VERIFIED for a program that never ran against the reference; the deriver alone would still certify it (the evidence looks like an all-MATCH
set), so the check belongs in the validator, not the deriver.

**Fix.** `ViolationType.ARTIFACT_ROLE_MISMATCH`; `EvidenceIntegrityValidator._execution_role(runtime_id)` maps `oracle*` → `"ORACLE"`,
`candidate*` → `"CANDIDATE"`, anything else → `None` (no role claim, no accusation). `_validate_artifact_execution_binding` refuses when the proven
role disagrees with the claimed `producer_role`. `derive_untrusted` then clamps the natural VERIFIED to ERROR, so the manifest never certifies.

Tests (red first): `tests/test_layer13_artifact_execution_role_binding.py` (7) — honest control validates and still derives VERIFIED; both cross-role
directions refused; the mutation that swaps the two artifacts' producing executions refused; the self-certifying manifest refused and clamped to
ERROR; and the natural-VERIFIED-before-the-clamp case documenting why the validator, not the deriver, must own the check.

## 4. Gap found and closed: L13-P3 the contract loader substituted declared fields

`engine/contracts/validator.py` opens with the rule it exists to enforce: "There must be NO 'best effort' contract interpretation."
`load_artifact_contract` broke it for two declared fields:

* `on_extra` was never read — a comparator declaring `on_extra: "FAILED"` loaded with the default `"MISMATCH"`, so the loaded contract did not say
  what the contract said. `FailurePolicy.__post_init__` validated `on_missing` and `on_malformed` but not `on_extra`, so any value (including a
  certifying one such as `"MATCH"`) was accepted silently.
* `permanently_forbidden` was never passed to `ArtifactContract` — a contract declaring extra permanent prohibitions loaded with only the
  `("substring_containment",)` default.

Reading `permanently_forbidden` naively would have *weakened* ADR-0002: the default currently protects `substring_containment` whether or not the
contract mentions it, and a declared empty list would disarm it.

**Fix.** `FailurePolicy.FAIL_CLOSED_STATES = frozenset({"UNAVAILABLE", "FAILED", "INCONCLUSIVE", "MISMATCH"})` (the union of the two sibling
vocabularies; `MATCH` deliberately absent) plus an `__post_init__` check. `ArtifactContract.__post_init__` (with
`MANDATORY_PERMANENTLY_FORBIDDEN = {"substring_containment"}`, per `ARTIFACT_CONTRACT_SPEC.md` §2: "This prohibition survives all future versions")
refuses a declared set that omits a mandatory prohibition or names an entry outside `NormalizationPolicy.FORBIDDEN` — an unenforceable claim.
`load_artifact_contract` reads both fields and wraps every `ValueError` in `ContractValidationError`, so a contract problem is always reported under
the loader's own error type.

Tests (red first): `tests/test_layer13_contract_loader_fidelity.py` (10) — shown **9 failed / 1 control passed** against the old loader, then 10
passed: declared `on_extra` / `permanently_forbidden` honoured, arbitrary `on_extra` refused by model and by loader, narrowing or emptying the
permanent prohibition refused, an unenforceable prohibition refused, the whole enforced set declarable (control), and a default contract loading
unchanged.

## 5. Audited, no change

* **Comparators.** `_normalize` already refuses any normalization other than the implemented `crlf_to_lf`; `NormalizationPolicy.__post_init__`
  refuses the six `FORBIDDEN` normalizations at construction (every production and fixture site constructs the policy object, never a raw tuple);
  `BUSINESS_INVARIANT_COMPARATOR` rejects any normalization and any ordering other than `SEQUENTIAL`.
* **Verdict derivation.** `VerdictState.VERIFIED` is assigned only in `VerdictDeriver.derive`; unknown artifact types reach `UNSUPPORTED` via
  `_check_for_unsupported`, and a comparison claiming a type its artifacts do not carry is a pairing violation. Untouched by this audit
  (do-not-regress area).
* **Evidence-seal / manifest / approval / export** — see §1.

## 6. Limitation stated, not fixed

* **The contract subsystem has no production caller.** `ContractValidator` and `load_*_contract` are referenced only from tests; the pipeline's real
  guard is the comparator registry (`engine/pipeline.py`: an unregistered `artifact_type` raises by name, a declared `comparator_id` that disagrees
  with the registry raises by name) plus the normalization/failure-policy constructors above. Every behaviour `ARTIFACT_CONTRACT_SPEC.md` demands of
  "no fallback comparison" is therefore enforced — by duplication rather than by the contract object. Wiring `ContractValidator` into the pipeline is
  an architectural change (it would make the registry and the contract two sources of truth for the same five types) and is deliberately **not** done
  here; recorded in `docs/KNOWN_ISSUES.md`.

## 7. Next steps

Layer 13 is closed. Remaining Layer 12 scope: line-by-line audit of `engine/verification/business_invariants.py` and
`scripts/e2e/verify_independent.py` (both already covered by tests; see `LAYER12_DESIGN.md` §4).
