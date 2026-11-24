# Layer 8 design: Modernization planning

Status: **L8-P1 implemented (2026-11-24)**, from `4a2808c` (Layer 7 complete and certified). Deterministic, open source only, no LLM.
Language coverage is frozen: nothing here adds COBOL syntax, and the retained producers R2/R3/R5/R6 stay. Layer 9 is not started.

## 1. Audit (what exists)

`engine/modernization/transformation_plan.py::TransformationPlanGenerator` is the single production planner. The pipeline
(`engine/modernization/pipeline.py`) builds it from `canonical_application(application, ir)` (Layer 6 M2) and the Layer 7 capability
report, enforces it (any SKIP program, CALL or copybook refuses generation, and the plan's entry must equal the generator's), and
passes it to the Layer 7 capability record (`plan_id`). `engine/modernization/modernization_planner.py` is EXPERIMENTAL, is imported
by nothing in production (only the package `__init__` re-export), and is **not** wired in or duplicated here
(`test_the_experimental_planner_is_not_wired_into_production`).

## 2. Gaps found by probe (all fail-open or untrue, all closed in L8-P1)

Each was reproduced with a forged or contradictory capability report before the change (scratch probe, not committed) and is a test now.

| # | Gap | Effect before | Fix |
|---|---|---|---|
| G1 | Capability lookup was `{component_id: component}`: a later component overwrote an earlier one | `UNSUPPORTED` then `SUPPORTED` for one program planned TRANSFORM | `plan_evidence.reconcile`: worst level per `(type, id)`; a disagreement is a plan note |
| G2 | Lookup ignored component type | a copybook named like a program was planned from the program's evidence | key is `(component_type, component_id)` |
| G3 | Report's `application_id` and `overall_level` were never checked against the application or its own components | a report for another application, or one whose overall level contradicts its components, was trusted | conflict: every program and copybook SKIP, conflict named |
| G4 | Components naming a program or copybook the application does not have were ignored | silently dropped evidence | conflict (as G3) |
| G5 | A level that was not a `CapabilityLevel` raised `AttributeError` | crash instead of a block | treated as UNKNOWN, planned SKIP |
| G6 | A TRANSFORM program could CALL a SKIP program | plan inconsistent with itself (only the pipeline's blanket refusal hid it) | `plan_graph.blocked_by_dependency` (fixed point), `blocked_by` names the dependency |
| G7 | A TRANSFORM program could COPY a SKIP copybook | same | same rule, `uses copybook NAME` |
| G8 | A non-SUPPORTED FILE component was invisible to the plan | an owning program claiming support was planned TRANSFORM | the owner program is SKIP with the file's reason |
| G9 | Only `UNRESOLVED` CALL edges were planned SKIP | an `AMBIGUOUS` or unknown resolution passed | every CALL edge that is not `RESOLVED` is a SKIP component |
| G10 | `_topological_sort` was a documented no-op; `priority` was always 0 | no dependency order anywhere | `plan_graph.dependency_ranks`: callees first, ties and cycles in discovery order; `priority`, `TransformationPlan.execution_order` |
| G11 | `OraclePlan.source_format` was the constant `"free"`; `link_modules` always empty | the plan stated an oracle parameter the oracle adapter never used (the fixtures are fixed format) | derived from the programs with `source_format.detect_source_format` (`free`/`fixed`/`mixed`/`""`); `link_modules` = the other source files, sorted as the oracle adapter sorts them |
| G12 | The plan carried no provenance | a SKIP could not be traced to the Layer 5 fact behind it | `ComponentPlan.capability_level` and `provenance` (the `ir_provenance` ids of the capability component) |
| G13 | `entrypoint_resolved` ignored whether the entry program is transformed | an entry nobody emits looked resolved | `entry_transformable` (the existing `entrypoint_resolved` contract is unchanged) |

Not a gap, verified: `include_service_registry` equals the Java generator's `len(application.programs) > 1`; the pipeline already refuses
a planner/generator entry disagreement; every runtime target gets the same actions and order (`test_every_runtime_target_...`).

## 3. Requirement checklist (traceable)

| # | Requirement | Code | Tests |
|---|---|---|---|
| P1 | Only SUPPORTED evidence for the component's own type and id may TRANSFORM | `transformation_plan.generate`, `plan_evidence.reconcile` | `test_every_transform_has_supported_evidence_...`, corpus contract |
| P2 | PARTIAL, UNSUPPORTED, UNAVAILABLE, UNKNOWN, missing, conflicting and malformed evidence blocks with a reason | `plan_evidence`, `_plan_program`, `_blocked_by_conflict` | `test_duplicate_evidence_...`, `test_a_level_that_is_not_...`, `test_conflicting_report_...`, `test_a_missing_capability_still_blocks`, `test_an_unproven_capability_level_...` |
| P3 | Dependency ordering from the CALL graph, deterministic | `plan_graph.dependency_ranks/order`, `priority`, `execution_order` | `test_dependency_order_...`, `test_a_cycle_...`, `test_plan_priority_...` |
| P4 | CALL / COPY / FILE dependencies are enforced in the plan, not only by the pipeline | `plan_graph.blocked_by_dependency`, FILE owner block, non-RESOLVED CALL edges | `test_a_caller_of_a_blocked_callee_...`, `test_a_program_using_a_blocked_copybook_...`, `test_an_unsupported_file_component_...`, `test_a_call_edge_that_is_not_resolved_...` |
| P5 | Entry selection agrees with the canonical IR, the generator and the oracle adapter | `_resolve_entrypoint` (shared rule), `entry_transformable` | `test_differential_the_plan_from_the_canonical_ir_...`, `test_differential_the_plan_links_what_the_oracle_adapter_links`, `test_planner_entrypoint.py`, `test_an_entry_whose_program_...` |
| P6 | Oracle parameters (format, link set) and assembly requirements agree with the actual pipeline | `plan_graph.oracle_parameters`, `AssemblyPlan` (unchanged) | `test_source_format_is_derived_...`, `test_link_modules_...`, `test_a_generated_multi_program_plan_...` |
| P7 | Provenance: capability level and Layer 5 fact ids on each component; reaches the report dict | `ComponentPlan.capability_level/provenance`, `to_dict` | `test_the_layer5_provenance_...`, `test_the_report_dict_carries_...` |
| P8 | The Layer 7 `plan_id` contract is preserved | `capability_record.plan_id_of` (unchanged) | `test_plan_id_definition_is_unchanged_...`, `test_the_capability_record_binds_exactly_the_plan_...` |
| P9 | Certified behaviour and the 110 generation hashes do not move (refusal text included) | `blocked_by` keeps a blocked caller out of the refusal's program list | `tools/generation_hashes.py --check`, `test_a_refused_callee_blocks_its_caller_in_the_plan_but_...` |
| P10 | One production planner; the experimental planner stays unwired | n/a | `test_the_experimental_planner_is_not_wired_into_production` |
| P11 | Mutation: a fail-open reconciliation is detected | n/a | `test_a_fail_open_reconciliation_would_be_detected` |

## 4. The `plan_id` decision

`plan_id` (Layer 7) is the sha256 of the plan's `(component_id, component_type, action)` rows and the two program counts. Its
definition is **unchanged**, so every Layer 7 record keeps its meaning. The new fields (`priority`, `capability_level`,
`provenance`, `blocked_by`, `evidence_*`) are deliberately outside it, and `test_plan_id_definition_is_unchanged_...` pins both the
definition and that decoration cannot move it. A dependency-blocked program changes `plan_id` (its action changed), which is
correct: the plan changed. The component *list* keeps discovery order; dependency order lives in `priority` and `execution_order`,
so no id moved for an unchanged plan.

## 5. Behaviour preserved

All 110 generation hashes, including the 18 refusal records (error and limitation text), are identical. This is why a program
blocked only by its dependency carries `blocked_by` and is left out of the pipeline's "non-transformable programs" list: the
refusal still names the root cause (the callee's or the copybook's own reason) and nothing else. Duplicate program ids
(`workload-claims` has three) keep their former last-wins reason text; the disagreement is a plan note, not rewritten text.

## 6. Limits and remaining work (stated up front)

* The plan's `base_package` (`com.modernized.app`) is a label no production code consumes: the real package is chosen per
  runtime adapter (`com.generated.app` for Spring Boot). It is pinned by an older test and left unchanged; it is not an assembly
  requirement the pipeline enforces.
* `OraclePlan.input_files` stays empty: oracle inputs come from the test vectors, not from the plan.
* `link_modules` is the set of other source files; the oracle adapter only compiles top-level modules, so a nested layout can differ
  (the differential test skips fixtures where the adapter selects no module).
* Dependency order is advisory for generation: the generator emits in discovery order, and the plan's order is not consumed by it.
  `plan_id` does not bind order or provenance (section 4).
* Duplicate program ids are not a conflict (the oracle and generator already refuse them by name at entry selection); the worst
  capability level applies to all of them.
* `mixed` oracle source format is reported, not blocked: generation reads mixed files per line (the oracle lanes refuse them).
* A report that contains no components while programs exist still plans every program SKIP ("no capability analysis result").
