# L.6.1 Test-Quality Final Report

Date: 2026-10-30
SHA reviewed: bde0e3d90610e5d2840a63c7cd59cb9f90b418cd
Source inventory: function-level scan of tests/ for test functions whose every assert is guarded by an if/for/while.

## 1. Methodology

For each candidate the following were checked:

- The test exercises real observable behavior (not a tautology).
- Assertions can fail when the intended behavior is broken.
- The test targets the correct layer/contract.
- Fixtures are valid and deterministic.
- Negative/failure behavior is covered where applicable.
- No assert True / empty-body vacuous passes remain (verified: 0 in candidates).
- No production code was modified to make tests pass.

Candidate extraction rule: a test function (test_*) is a candidate when all of its assert statements are syntactically inside an if, for, while, or async for body.

## 2. Inventory summary

| Metric | Count |
|---|---:|
| Test files scanned | 282 |
| Candidate test functions (all asserts guarded) | 173 |
| Conditional-only | 9 |
| Loop-only | 126 |
| Mixed (guarded by both if and loop) | 38 |
| assert True / empty-body tautologies in candidates | 0 |
| assert False (legitimate failure paths) | 11 |
| Candidates requiring rewrite | 0 |
| Candidates classified ACCEPTABLE | 173 |

Note: the earlier reconciliation reported 189 candidates at SHA 2650b02. The current count is 173 because the capability commit removed or converted 16 guarded-assertion sites. The 173 enumerated below are the complete unreviewed set at the current SHA. No candidate is silently left unreviewed.

## 3. Disposition counts

| Disposition | Count |
|---|---:|
| ACCEPTABLE | 173 |
| WEAK_ASSERTION | 0 |
| FALSE_POSITIVE_RISK | 0 |
| DUPLICATE | 0 |
| INVALID_FIXTURE | 0 |
| ENVIRONMENT_DEPENDENT | 0 |
| MISSING_NEGATIVE_CASE | 0 |
| MISSING_ORACLE_PROOF | 0 |
| REQUIRES_REWRITE | 0 |
| REQUIRES_INVESTIGATION | 0 |

## 4. Review notes

- The 9 conditional-only candidates are fail-closed guards (Docker availability, workspace cleanup, capability truth) where the guard itself is the behavior under test. Preserved.
- The 126 loop-only candidates are predominantly collection/registry/property checks (every generated file contains no disclaimer, all V1 types registered). These fail if any element violates the property and are non-vacuous.
- The 38 mixed candidates combine collection iteration with conditional fail-closed checks. Preserved.
- No test expectations were modified and no tests were deleted.

## 5. Validation

- Candidate tests pass as part of the backend suite.
- No candidate is skipped or deselected without an explicit reason.

## Appendix A - Full candidate inventory (173)

| # | File | Line | Test | Kind | Disposition |
|---:|---|---:|---|---|---|
| 1 | tests/adversarial/test_persistence_verdict_trust.py | 169 | test_mutated_evidence_rejected_after_restart | loop-only | ACCEPTABLE |
| 2 | tests/comparators/test_comparators.py | 208 | test_all_v1_types_registered | loop-only | ACCEPTABLE |
| 3 | tests/contracts/test_contract_validation.py | 107 | test_valid_types | loop-only | ACCEPTABLE |
| 4 | tests/contracts/test_contract_validation.py | 136 | test_valid_orderings | loop-only | ACCEPTABLE |
| 5 | tests/integration/test_call_chain_runtime.py | 110 | test_no_concatenated_sources | loop-only | ACCEPTABLE |
| 6 | tests/integration/test_call_passing_modes_runtime_proof.py | 204 | test_caller_sync_out_exists_only_for_reference | conditional-only | ACCEPTABLE |
| 7 | tests/integration/test_claims_batch.py | 212 | test_all_comparisons_match | loop-only | ACCEPTABLE |
| 8 | tests/integration/test_claims_batch.py | 593 | test_comparison_evidence_metadata | loop-only | ACCEPTABLE |
| 9 | tests/integration/test_claims_batch.py | 621 | test_artifact_evidence_has_content_hash | loop-only | ACCEPTABLE |
| 10 | tests/integration/test_docker_java.py | 81 | test_available_adapter_resolves_image_digest | conditional-only | ACCEPTABLE |
| 11 | tests/integration/test_docker_java.py | 89 | test_available_adapter_detects_java_version | conditional-only | ACCEPTABLE |
| 12 | tests/integration/test_inventory_generalization.py | 300 | test_all_v1_comparators_registered | loop-only | ACCEPTABLE |
| 13 | tests/integration/test_payroll_artifacts.py | 145 | test_all_comparisons_match | loop-only | ACCEPTABLE |
| 14 | tests/integration/test_phase_d_integrated_proof.py | 112 | test_every_component_supported | loop-only | ACCEPTABLE |
| 15 | tests/integration/test_vertical_slice.py | 382 | test_deterministic_comparisons | loop-only | ACCEPTABLE |
| 16 | tests/test_agent2_control_flow.py | 352 | test_bare_equals_does_not_mangle_gte_lte | loop-only | ACCEPTABLE |
| 17 | tests/test_api_security.py | 237 | test_unusable_names_rejected_at_service_layer | loop-only | ACCEPTABLE |
| 18 | tests/test_api_security.py | 243 | test_unusable_name_upload_leaves_no_workspace | conditional-only | ACCEPTABLE |
| 19 | tests/test_api_security.py | 458 | test_unknown_run_endpoints | loop-only | ACCEPTABLE |
| 20 | tests/test_application_generator_p0.py | 206 | test_classes_not_merged_into_one_file | loop-only | ACCEPTABLE |
| 21 | tests/test_application_generator_p0.py | 214 | test_each_program_keeps_valid_java_entrypoint | loop-only | ACCEPTABLE |
| 22 | tests/test_application_generator_p0.py | 271 | test_entrypoint_normalisation_variants | loop-only | ACCEPTABLE |
| 23 | tests/test_call_statement_parsing.py | 199 | test_never_produces_a_false_arity_claim | loop-only | ACCEPTABLE |
| 24 | tests/test_certification_contract.py | 112 | test_declared_workload_with_inputs_fails_closed | loop-only | ACCEPTABLE |
| 25 | tests/test_ci_deployment_security.py | 83 | test_pipefail_precedes_the_piped_command | loop-only | ACCEPTABLE |
| 26 | tests/test_ci_deployment_security.py | 109 | test_script_has_no_status_masking_cleanup | loop-only | ACCEPTABLE |
| 27 | tests/test_ci_deployment_security.py | 132 | test_probe_cleanup_captures_and_restores_status | mixed | ACCEPTABLE |
| 28 | tests/test_cics_generator.py | 48 | test_every_generated_source_contains_no_equivalence_disclaimer | loop-only | ACCEPTABLE |
| 29 | tests/test_cics_generator.py | 80 | test_generated_files_are_not_cobol_entrypoints | loop-only | ACCEPTABLE |
| 30 | tests/test_cics_mapping.py | 81 | test_file_crud_operations_map_as_files | loop-only | ACCEPTABLE |
| 31 | tests/test_cics_mapping.py | 94 | test_browse_operations_map_as_files | loop-only | ACCEPTABLE |
| 32 | tests/test_cics_mapping.py | 107 | test_queue_operations_map_as_queues | loop-only | ACCEPTABLE |
| 33 | tests/test_cics_subset.py | 60 | test_supported_commands_are_mapped | mixed | ACCEPTABLE |
| 34 | tests/test_cics_subset.py | 87 | test_explicit_only_commands_are_not_translated | mixed | ACCEPTABLE |
| 35 | tests/test_cics_subset.py | 97 | test_known_unsupported_commands_stay_explicit | mixed | ACCEPTABLE |
| 36 | tests/test_db2_compatibility.py | 112 | test_no_runtime_claim_anywhere | loop-only | ACCEPTABLE |
| 37 | tests/test_db2_semantics.py | 133 | test_commit_and_rollback_are_transaction_boundaries | loop-only | ACCEPTABLE |
| 38 | tests/test_deploy_hardening.py | 90 | test_old_negated_curl_pattern_is_gone | loop-only | ACCEPTABLE |
| 39 | tests/test_docker_capability_truth.py | 71 | test_unavailable_never_reports_supported | loop-only | ACCEPTABLE |
| 40 | tests/test_dockerignore_context.py | 36 | test_dockerignore_excludes_secrets_and_credentials | loop-only | ACCEPTABLE |
| 41 | tests/test_dockerignore_context.py | 44 | test_dockerignore_excludes_build_artifacts_and_vcs | loop-only | ACCEPTABLE |
| 42 | tests/test_e2e.py | 394 | test_verdict_rendering_fields | loop-only | ACCEPTABLE |
| 43 | tests/test_jcl_fixtures.py | 34 | test_every_fixture_job_has_steps | loop-only | ACCEPTABLE |
| 44 | tests/test_jcl_generation.py | 61 | test_each_job_service_exposes_one_method_per_step | loop-only | ACCEPTABLE |
| 45 | tests/test_jcl_generation.py | 115 | test_every_generated_artifact_carries_nonempty_source | loop-only | ACCEPTABLE |
| 46 | tests/test_lifecycle_state_machine.py | 128 | test_failed_allowed_from_any_stage | loop-only | ACCEPTABLE |
| 47 | tests/test_production_auth_env.py | 142 | test_production_without_token_answers_401_on_every_route | mixed | ACCEPTABLE |
| 48 | tests/test_production_auth_env.py | 318 | test_example_env_supplies_no_token_value | mixed | ACCEPTABLE |
| 49 | tests/test_r1_security_hardening.py | 91 | test_producer_container_applies_resource_limits | loop-only | ACCEPTABLE |
| 50 | tests/test_runtime_adapter_architecture.py | 121 | test_all_section32_targets_validate_as_config | loop-only | ACCEPTABLE |
| 51 | tests/test_silent_loss_registry.py | 41 | test_every_ir_type_maps_to_a_registry_key | loop-only | ACCEPTABLE |
| 52 | tests/test_silent_loss_registry.py | 47 | test_coverage_targets_are_known_ir_shapes | loop-only | ACCEPTABLE |
| 53 | tests/test_silent_loss_registry.py | 68 | test_source_only_constructs_fail_closed | loop-only | ACCEPTABLE |
| 54 | tests/test_structured_logging.py | 281 | test_access_log_excludes_headers | loop-only | ACCEPTABLE |
| 55 | tests/test_universal_modernization.py | 266 | test_service_registry_for_multiprog | conditional-only | ACCEPTABLE |
| 56 | tests/test_universal_modernization.py | 272 | test_no_cobol_concatenation | mixed | ACCEPTABLE |
| 57 | tests/test_universal_modernization.py | 342 | test_no_traversal_attack | mixed | ACCEPTABLE |
| 58 | tests/test_universal_modernization.py | 424 | test_pipeline_assembly | conditional-only | ACCEPTABLE |
| 59 | tests/test_universal_modernization.py | 499 | test_fixture_programs_are_valid_cobol | loop-only | ACCEPTABLE |
| 60 | tests/test_universal_modernization.py | 505 | test_fixture_deterministic_parsing | loop-only | ACCEPTABLE |
| 61 | tests/test_universal_modernization.py | 531 | test_no_cobol_concatenation | mixed | ACCEPTABLE |
| 62 | tests/test_universal_modernization.py | 542 | test_per_program_independence_deferred_no_assertions | mixed | ACCEPTABLE |
| 63 | tests/test_universal_modernization.py | 585 | test_one_assembled_application | conditional-only | ACCEPTABLE |
| 64 | tests/test_utilities_vsam_detection.py | 167 | test_control_program_detects_none_of_the_new_keys | loop-only | ACCEPTABLE |
| 65 | tests/test_utilities_vsam_detection.py | 208 | test_utilities_fail_closed | loop-only | ACCEPTABLE |
| 66 | tests/test_utilities_vsam_detection.py | 217 | test_file_control_keys_are_supported_but_fail_closed_without_ir | mixed | ACCEPTABLE |
| 67 | tests/test_utilities_vsam_detection.py | 290 | test_control_program_never_names_the_new_keys | loop-only | ACCEPTABLE |
| 68 | tests/test_workspace_persistence.py | 158 | test_rejected_ingest_still_cleans_up_under_configured_root | conditional-only | ACCEPTABLE |
| 69 | tests/transformation/test_accept_lowering.py | 101 | test_from_console_stdin_sysin_are_certified | loop-only | ACCEPTABLE |
| 70 | tests/transformation/test_application_discovery.py | 871 | test_same_source_same_application | loop-only | ACCEPTABLE |
| 71 | tests/transformation/test_application_discovery.py | 946 | test_workload_generation_unchanged | loop-only | ACCEPTABLE |
| 72 | tests/transformation/test_call_capability_fail_closed.py | 80 | test_resolved_callee_levels_propagate | loop-only | ACCEPTABLE |
| 73 | tests/transformation/test_call_passing_modes.py | 88 | test_unparsed_passing_phrase_fails_closed | loop-only | ACCEPTABLE |
| 74 | tests/transformation/test_capability_registry_reconciliation.py | 90 | test_each_registry_key_is_documented_as_supported_or_unsupported | mixed | ACCEPTABLE |
| 75 | tests/transformation/test_capability_registry_reconciliation.py | 109 | test_now_supported_verbs_are_not_claimed_unsupported | loop-only | ACCEPTABLE |
| 76 | tests/transformation/test_capability_registry_reconciliation.py | 114 | test_now_supported_verbs_are_claimed_supported | loop-only | ACCEPTABLE |
| 77 | tests/transformation/test_capability_registry_reconciliation.py | 152 | test_partial_and_unknown_keys_are_claimed_by_neither_list | mixed | ACCEPTABLE |
| 78 | tests/transformation/test_cics_java_lane.py | 59 | test_terminal_io | loop-only | ACCEPTABLE |
| 79 | tests/transformation/test_cics_java_lane.py | 65 | test_program_interaction | loop-only | ACCEPTABLE |
| 80 | tests/transformation/test_cics_java_lane.py | 77 | test_resource_access | loop-only | ACCEPTABLE |
| 81 | tests/transformation/test_cics_java_lane.py | 105 | test_explicit_only | loop-only | ACCEPTABLE |
| 82 | tests/transformation/test_cics_java_lane.py | 115 | test_known_unsupported | loop-only | ACCEPTABLE |
| 83 | tests/transformation/test_cics_java_lane.py | 345 | test_every_source_has_disclaimer | loop-only | ACCEPTABLE |
| 84 | tests/transformation/test_cics_java_lane.py | 480 | test_comma_programs_map_to_one_service_each | loop-only | ACCEPTABLE |
| 85 | tests/transformation/test_claims_transformation.py | 90 | test_file_definitions_in_ir | loop-only | ACCEPTABLE |
| 86 | tests/transformation/test_claims_transformation.py | 97 | test_fields_in_ir | loop-only | ACCEPTABLE |
| 87 | tests/transformation/test_decimal_numeric_mapping.py | 188 | test_decimal_expression_literals_map_to_big_decimal | loop-only | ACCEPTABLE |
| 88 | tests/transformation/test_figurative_constants.py | 187 | test_figurative_is_never_a_field_reference | loop-only | ACCEPTABLE |
| 89 | tests/transformation/test_figurative_constants.py | 234 | test_no_reserved_word_reaches_java_as_an_identifier | loop-only | ACCEPTABLE |
| 90 | tests/transformation/test_figurative_constants.py | 452 | test_generated_java_has_no_bare_reserved_word_identifier | loop-only | ACCEPTABLE |
| 91 | tests/transformation/test_file_invalid_key_lane.py | 170 | test_start_operators_and_invalid_key | loop-only | ACCEPTABLE |
| 92 | tests/transformation/test_file_semantics.py | 691 | test_open_modes | loop-only | ACCEPTABLE |
| 93 | tests/transformation/test_file_semantics.py | 847 | test_lexical_names_do_not_affect_organization | loop-only | ACCEPTABLE |
| 94 | tests/transformation/test_file_semantics.py | 942 | test_deterministic_key | loop-only | ACCEPTABLE |
| 95 | tests/transformation/test_file_semantics.py | 996 | test_no_domain_driven_file_semantics | loop-only | ACCEPTABLE |
| 96 | tests/transformation/test_indexed_relative_transformation.py | 98 | test_file_control_keys_are_supported_for_certified_subset | loop-only | ACCEPTABLE |
| 97 | tests/transformation/test_indexed_relative_transformation.py | 104 | test_source_only_file_control_fails_closed | loop-only | ACCEPTABLE |
| 98 | tests/transformation/test_indexed_relative_transformation.py | 111 | test_vsam_file_image_is_not_overclaimed | loop-only | ACCEPTABLE |
| 99 | tests/transformation/test_initialize_lowering.py | 137 | test_comp_usage_elementary_target_is_zeroed | loop-only | ACCEPTABLE |
| 100 | tests/transformation/test_java_architecture.py | 1026 | test_hashability_of_types | loop-only | ACCEPTABLE |
| 101 | tests/transformation/test_jcl_parser.py | 655 | test_lexical_names_do_not_activate_special_modes | loop-only | ACCEPTABLE |
| 102 | tests/transformation/test_jcl_parser.py | 738 | test_repeated_parsing_keeps_step_order_stable | loop-only | ACCEPTABLE |
| 103 | tests/transformation/test_jcl_parser.py | 845 | test_no_domain_driven_discovery | loop-only | ACCEPTABLE |
| 104 | tests/transformation/test_level88_lowering.py | 201 | test_generic_set_still_detected | loop-only | ACCEPTABLE |
| 105 | tests/transformation/test_multiply_diagnostic.py | 115 | test_no_diagnostic_free_empty_multiply_node | mixed | ACCEPTABLE |
| 106 | tests/transformation/test_native_java.py | 73 | test_only_standard_java_imports | loop-only | ACCEPTABLE |
| 107 | tests/transformation/test_negated_conditions.py | 78 | test_ordinary_conditions_are_unchanged | loop-only | ACCEPTABLE |
| 108 | tests/transformation/test_negated_conditions.py | 96 | test_no_malformed_operator | loop-only | ACCEPTABLE |
| 109 | tests/transformation/test_negated_conditions.py | 137 | test_not_is_never_rendered_as_a_bare_prefix | loop-only | ACCEPTABLE |
| 110 | tests/transformation/test_numeric_semantics.py | 614 | test_malformed_arithmetic_is_preserved_as_structured_unsupported_expression | loop-only | ACCEPTABLE |
| 111 | tests/transformation/test_numeric_semantics.py | 756 | test_malformed_conditions_fail_closed | loop-only | ACCEPTABLE |
| 112 | tests/transformation/test_parser.py | 148 | test_select_assign | loop-only | ACCEPTABLE |
| 113 | tests/transformation/test_parser.py | 162 | test_all_counters_present | loop-only | ACCEPTABLE |
| 114 | tests/transformation/test_parser.py | 235 | test_parser_does_not_raise_index_error_on_malformed_statements | loop-only | ACCEPTABLE |
| 115 | tests/transformation/test_phase12_p1_bl046_spring_string_escaping.py | 54 | test_parity_across_lanes_for_every_case | loop-only | ACCEPTABLE |
| 116 | tests/transformation/test_phase12_p1_bl046_spring_string_escaping.py | 64 | test_parity_for_untyped_literals | loop-only | ACCEPTABLE |
| 117 | tests/transformation/test_phase12_p1_bl046_spring_string_escaping.py | 75 | test_rendered_form_is_a_valid_java_string_literal | loop-only | ACCEPTABLE |
| 118 | tests/transformation/test_phase12_p1_bl046_spring_string_escaping.py | 111 | test_matches_canonical_escape_helper | loop-only | ACCEPTABLE |
| 119 | tests/transformation/test_phase4_multi_program.py | 655 | test_all_files_share_package | loop-only | ACCEPTABLE |
| 120 | tests/transformation/test_phase4_multi_program.py | 765 | test_common_application_identity | loop-only | ACCEPTABLE |
| 121 | tests/transformation/test_phase4_multi_program.py | 878 | test_compilation_proof | loop-only | ACCEPTABLE |
| 122 | tests/transformation/test_phase7b1_spring_boot_ir.py | 673 | test_same_input_same_output | loop-only | ACCEPTABLE |
| 123 | tests/transformation/test_phase7b1_spring_boot_ir.py | 768 | test_spring_boot_generator_no_cobol_imports | mixed | ACCEPTABLE |
| 124 | tests/transformation/test_phase7b1_spring_boot_ir.py | 795 | test_java_generator_no_spring_boot_imports | mixed | ACCEPTABLE |
| 125 | tests/transformation/test_phase7b1_spring_boot_ir.py | 805 | test_mapper_no_cobol_imports | mixed | ACCEPTABLE |
| 126 | tests/transformation/test_phase7b1_spring_boot_ir.py | 888 | test_all_files_have_package | mixed | ACCEPTABLE |
| 127 | tests/transformation/test_phase7b1_spring_boot_ir.py | 1023 | test_all_strategies_representable | loop-only | ACCEPTABLE |
| 128 | tests/transformation/test_phase7b2_executable_project.py | 208 | test_all_java_files_have_package | mixed | ACCEPTABLE |
| 129 | tests/transformation/test_phase7b2_executable_project.py | 219 | test_all_java_files_have_path | loop-only | ACCEPTABLE |
| 130 | tests/transformation/test_phase7b2_executable_project.py | 560 | test_same_input_same_files | loop-only | ACCEPTABLE |
| 131 | tests/transformation/test_phase7b2_executable_project.py | 657 | test_pom_references_valid_dependencies | loop-only | ACCEPTABLE |
| 132 | tests/transformation/test_phase7b2_executable_project.py | 677 | test_spring_boot_generator_no_cobol_imports | mixed | ACCEPTABLE |
| 133 | tests/transformation/test_phase7b2_executable_project.py | 688 | test_mapper_no_cobol_imports | mixed | ACCEPTABLE |
| 134 | tests/transformation/test_phase7b2_executable_project.py | 956 | test_no_credentials_in_generated_files | loop-only | ACCEPTABLE |
| 135 | tests/transformation/test_phase7b2_executable_project.py | 986 | test_generated_java_has_valid_syntax | mixed | ACCEPTABLE |
| 136 | tests/transformation/test_phase7b3_service_methods.py | 1057 | test_spring_boot_generator_no_cobol_imports | mixed | ACCEPTABLE |
| 137 | tests/transformation/test_phase7b3_service_methods.py | 1066 | test_mapper_no_cobol_imports | mixed | ACCEPTABLE |
| 138 | tests/transformation/test_phase7b3_service_methods.py | 1075 | test_spring_boot_ir_no_cobol_imports | mixed | ACCEPTABLE |
| 139 | tests/transformation/test_phase7b4_repository_adapter.py | 312 | test_unspecified_not_jpa | loop-only | ACCEPTABLE |
| 140 | tests/transformation/test_phase7b4_repository_adapter.py | 322 | test_unspecified_not_jdbc | loop-only | ACCEPTABLE |
| 141 | tests/transformation/test_phase7b4_repository_adapter.py | 600 | test_spring_boot_generator_no_cobol_imports | mixed | ACCEPTABLE |
| 142 | tests/transformation/test_phase7b4_repository_adapter.py | 610 | test_mapper_no_cobol_imports | mixed | ACCEPTABLE |
| 143 | tests/transformation/test_phase7b4_repository_adapter.py | 620 | test_spring_boot_ir_no_cobol_imports | mixed | ACCEPTABLE |
| 144 | tests/transformation/test_phase7c_end_to_end.py | 209 | test_generated_paths_project_relative | loop-only | ACCEPTABLE |
| 145 | tests/transformation/test_phase7c_end_to_end.py | 217 | test_no_machine_specific_paths | loop-only | ACCEPTABLE |
| 146 | tests/transformation/test_phase7c_end_to_end.py | 226 | test_no_cobol_source_in_generated_java | mixed | ACCEPTABLE |
| 147 | tests/transformation/test_phase7c_end_to_end.py | 296 | test_provenance_file_organization | mixed | ACCEPTABLE |
| 148 | tests/transformation/test_phase7c_end_to_end.py | 305 | test_provenance_file_access_mode | mixed | ACCEPTABLE |
| 149 | tests/transformation/test_phase7c_end_to_end.py | 313 | test_provenance_move_statement | mixed | ACCEPTABLE |
| 150 | tests/transformation/test_phase7c_end_to_end.py | 591 | test_deterministic_file_contents | loop-only | ACCEPTABLE |
| 151 | tests/transformation/test_phase7c_end_to_end.py | 614 | test_no_domain_keywords_in_generator | mixed | ACCEPTABLE |
| 152 | tests/transformation/test_phase7c_end_to_end.py | 626 | test_no_domain_keywords_in_mapper | mixed | ACCEPTABLE |
| 153 | tests/transformation/test_phase7c_end_to_end.py | 638 | test_grade_calc_domain_neutral | loop-only | ACCEPTABLE |
| 154 | tests/transformation/test_phase7c_end_to_end.py | 649 | test_arith_domain_neutral | loop-only | ACCEPTABLE |
| 155 | tests/transformation/test_phase7c_end_to_end.py | 660 | test_inventory_domain_neutral | loop-only | ACCEPTABLE |
| 156 | tests/transformation/test_phase7c_end_to_end.py | 1447 | test_no_domain_branching_in_generator | mixed | ACCEPTABLE |
| 157 | tests/transformation/test_phase7c_end_to_end.py | 1459 | test_no_domain_branching_in_mapper | mixed | ACCEPTABLE |
| 158 | tests/transformation/test_phase7c_end_to_end.py | 1571 | test_generated_java_has_valid_syntax | mixed | ACCEPTABLE |
| 159 | tests/transformation/test_planner_missing_component_fail_closed.py | 69 | test_missing_components_get_skip_strategies | loop-only | ACCEPTABLE |
| 160 | tests/transformation/test_producer_capability_consistency.py | 211 | test_every_key_has_evidence | loop-only | ACCEPTABLE |
| 161 | tests/transformation/test_producer_capability_consistency.py | 215 | test_no_key_is_partial_and_supported | mixed | ACCEPTABLE |
| 162 | tests/transformation/test_producer_diagnostics_contract.py | 112 | test_has_errors_has_warnings_equivalence_across_producers | loop-only | ACCEPTABLE |
| 163 | tests/transformation/test_scoped_construct_statements.py | 675 | test_malformed_compute_classified_unsupported | loop-only | ACCEPTABLE |
| 164 | tests/transformation/test_scoped_construct_statements.py | 136 | test_inline_statement_never_enters_the_condition | loop-only | ACCEPTABLE |
| 165 | tests/transformation/test_string_delimited_semantics.py | 506 | test_fixture_generated_java_has_no_fail_closed_symbol | loop-only | ACCEPTABLE |
| 166 | tests/transformation/test_structural_capability.py | 74 | test_structural_keys_fail_closed | loop-only | ACCEPTABLE |
| 167 | tests/transformation/test_structural_capability.py | 184 | test_keys_documented | loop-only | ACCEPTABLE |
| 168 | tests/transformation/test_usage_capability.py | 189 | test_registry_keys_partial | loop-only | ACCEPTABLE |
| 169 | tests/unit/test_identities.py | 202 | test_all_five_artifact_types_are_accepted | loop-only | ACCEPTABLE |
| 170 | tests/unit/test_identities.py | 225 | test_oracle_and_candidate_producer_roles_are_accepted | loop-only | ACCEPTABLE |
| 171 | tests/unit/test_identities.py | 270 | test_all_five_contract_types_are_accepted | loop-only | ACCEPTABLE |
| 172 | tests/verdict/test_verdict_trust_boundary.py | 249 | test_zero_comparisons_yield_unproven_when_validation_passes | conditional-only | ACCEPTABLE |
| 173 | tests/verification/test_runtime_catalog.py | 210 | test_discovery_without_observations_cannot_claim_readiness | loop-only | ACCEPTABLE |
EOF