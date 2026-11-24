# Layer 11 design: GnuCOBOL oracle and differential execution

Status: **closed with stated limits (2026-11-24): L11-P1 done; comparators, JCL lane and oracle audited with no further defect. Certified: fast CI and supply chain on `51f01d1`, corpus certification (four runtimes) on `b7be27c` (the code commit; `51f01d1` is docs only), dispatched full integration on `51f01d1`, all green; the 110 generation hashes identical.** From `c223e07` (Layer 10 closed with stated limits). Deterministic, open source only, no LLM.
Language coverage is frozen; the 110 generation hashes must not move.

Scope (`LAYER_MODEL.md`): `engine/oracle/**`, `engine/comparators/**`, `engine/jcl/**`. Output: oracle build/run results identified by `oracle_id`.

## 1. Audit so far

* **Image identity is already pinned.** `engine/oracle/docker_adapter.py` resolves the oracle image to an immutable `sha256` identity, refuses to execute by
  tag, refuses a declared pin that does not match the resolved image, and records the `cobc --version` observed inside the executed image (audit V6).
  This is a do-not-regress area (`LAYER_MODEL.md`, change rules).
* **Entry authority (gap confirmed and closed in L11-P1, section 2).** The Java side now takes its entry from the Layer 8 plan (`plan.oracle.entry_program`, Layer 9).
  The oracle side takes it from `api/service.py::_resolve_entry_program`, passed as `PipelineConfig.oracle_entry_program` (`api/service.py:1603`).
  Both start from the same request value, so they agree whenever the service resolves an entry. They can differ when the service returns `""` (several
  call roots) while the plan resolves an entry another way: the oracle then falls back to its own convention (explicit entry, `main.cob`/`main.cbl`,
  legacy) and may run a different program from the one the generated Java enters. The sealed `plan_record` does not carry `entry_program` (its keys are
  fixed by the Layer 8 contract), so the validator cannot compare them today.

## 2. L11-P1: the oracle runs the program the plan enters (closed)

Probe (confirmed): `DRIVER` CALLs itself and `SUB`; `SUB` is in `main.cob`. `Service._resolve_entry_program` counted the self-CALL as making `DRIVER`
called, found no root and returned `""`; the shared rule (`engine.transformation.entrypoint`, which the plan uses) ignores self-calls and resolves
`DRIVER`. With no entry the oracle's convention selected `main.cob` (`SUB`), so the oracle and the generated Java ran different programs.
Fix: the service excludes self-CALL edges, so it resolves what the plan resolves. Generation output is untouched (hashes unchanged).
Tests: `tests/test_oracle_entry_authority.py` (five estates: service entry == shared rule; the oracle selects `driver.cob`).
Residual: the service and the plan still apply the rule in two places; the plan's entry is not in the sealed `plan_record` (its keys are fixed), so
agreement is pinned by test, not by the validator.

## 3. Audits completed without a code change

* **Comparators** (`engine/comparators/framework.py`): a missing artifact is INCONCLUSIVE or MISMATCH by policy, never a match; an unsupported
  normalization or ordering raises; there is no implicit normalization; byte-exact unless a workload declares `crlf_to_lf`. Covered by
  `tests/comparators/**` and the adversarial suites (`tests/adversarial/test_comparator_attacks.py`, `test_normalization_attacks.py`, `test_semantic_mutations.py`).
* **JCL lane / oracle:** extensive existing tests (`tests/test_jcl_*.py`, `tests/test_oracle_*.py`, `tests/test_production_oracle_pin.py`); image identity pinning unchanged.

## 4. Limits (stated, not claimed)

* The oracle compiles with the default `-std=`; the dialect `profile_id` is not recorded beside `oracle_id` (`LAYER_MODEL.md`, open).
* The real GnuCOBOL/Docker oracle is exercised by the certification lanes, not by the Docker-free local tests.
* The plan's entry program is not in the sealed `plan_record`; the entry agreement is pinned by tests, not by the evidence validator.
