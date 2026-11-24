# Layer 11 design: GnuCOBOL oracle and differential execution

Status: **audit started (2026-11-24), no code changed.** From `c223e07` (Layer 10 closed with stated limits). Deterministic, open source only, no LLM.
Language coverage is frozen; the 110 generation hashes must not move.

Scope (`LAYER_MODEL.md`): `engine/oracle/**`, `engine/comparators/**`, `engine/jcl/**`. Output: oracle build/run results identified by `oracle_id`.

## 1. Audit so far

* **Image identity is already pinned.** `engine/oracle/docker_adapter.py` resolves the oracle image to an immutable `sha256` identity, refuses to execute by
  tag, refuses a declared pin that does not match the resolved image, and records the `cobc --version` observed inside the executed image (audit V6).
  This is a do-not-regress area (`LAYER_MODEL.md`, change rules).
* **Entry authority (candidate gap, not yet probed).** The Java side now takes its entry from the Layer 8 plan (`plan.oracle.entry_program`, Layer 9).
  The oracle side takes it from `api/service.py::_resolve_entry_program`, passed as `PipelineConfig.oracle_entry_program` (`api/service.py:1603`).
  Both start from the same request value, so they agree whenever the service resolves an entry. They can differ when the service returns `""` (several
  call roots) while the plan resolves an entry another way: the oracle then falls back to its own convention (explicit entry, `main.cob`/`main.cbl`,
  legacy) and may run a different program from the one the generated Java enters. The sealed `plan_record` does not carry `entry_program` (its keys are
  fixed by the Layer 8 contract), so the validator cannot compare them today.

## 2. Next steps (not started)

1. Probe the entry divergence with a two-root estate whose plan resolves an entry; confirm or refute.
2. If confirmed: feed the oracle the plan's entry when a plan exists and refuse a disagreement, without changing the `plan_record` keys.
3. Audit comparators (`framework.py`, `indexed_records.py`) and `engine/jcl/**` for fail-closed behaviour and determinism.
