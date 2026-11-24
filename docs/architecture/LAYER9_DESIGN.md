# Layer 9 design: Java generation under the Layer 8 plan

Status: **L9-P1, L9-P2 and L9-P3 implemented (2026-11-24)**, from `85c8804` (Layer 8 complete: plan and plan record). Deterministic, open source only,
no LLM. Language coverage is frozen: nothing here adds COBOL syntax. Layer 10 consumes the generation record: `LAYER10_DESIGN.md`.

## 1. Audit (what exists)

Production generation is one path: `UniversalModernizationPipeline` -> `ApplicationGenerator.generate` (per-program mapping from the **parser IR**,
`unit.program`, through `map_cobol_programs_to_application` and the shared `JavaGenerator`/`JavaSourceRenderer`) -> a `RuntimeAdapter`
(`spring_boot`, `plain_java`, `quarkus`, `micronaut`, `jakarta_ee`, from `runtime_registry`) which assembles the project. The Application IR enters
only through `canonicalize` (application-level relationships: call edges, COPY references, entry points) and is refused on any divergence; it never
renders a statement. `ProducerManifest` and `producer.py`/`producers/*` are the experimental producers' timestamped metadata (tests only; the only
production import from `producer.py` is `fail_closed_symbols`); they are not in the production path and are not extended
(`test_the_experimental_producer_manifest_is_not_in_the_production_path`). `tools/generation_hashes.py` mirrors the production path.

## 2. Gaps found (measured, then closed)

| # | Gap | Effect before | Fix |
|---|---|---|---|
| G1 | `ApplicationGenerator` never saw the plan; the pipeline only refused before calling it | a caller of the generator (or a future refactor) could emit a blocked program, a program set the plan never named, or a different entry, with no check | `generation_authority.preflight` / `verify_output`, `ApplicationGenerator.generate(plan=...)`; the pipeline passes the plan it enforced |
| G2 | The assembly adapters received the raw request `config.entrypoint`, not the plan's established entry | with no entry requested **all five runtimes launched the wrong program**: `plain_java`/`jakarta_ee` the first program in discovery order, Spring Boot every service, Quarkus/Micronaut the first class (measured: `SUB` and `DRIVER` sources, `SUB` sorting first, `DRIVER` the plan's root; red before, green after, on all five) | the pipeline passes `plan.oracle.entry_program` to the adapter; for every entry the corpus passes the value is identical, so the 110 hashes did not move |
| G3 | Nothing recorded what a generation produced from which plan | no content-addressed lineage from plan to generated tree | the generation record (section 5), sealed in the evidence manifest and bound to the plan record |
| G4 | Program-id to class identity was a convention | `STUDENT-PROCESSOR` is `Student_Processor` in every target except Spring Boot (`StudentProcessor`); nothing stated or checked it | `runtime_class_name(runtime, program_id)` is the one stated rule per target; the record and the tests use it. The Spring PascalCase rule is **kept** (changing it would move every Spring hash for no behavioural gain) and documented here |

Not a gap, verified: generation is byte-reproducible on all five targets (`test_generation_is_byte_reproducible_for_every_runtime`); program
classes are declared once per program in every target; no program source is concatenated (one class per program).

## 3. Requirement checklist (traceable)

| # | Requirement | Code | Tests | Status |
|---|---|---|---|---|
| A1 | Only approved components are generated; blocked callee/copybook refuses its callers; no partial application | `generation_authority.preflight`, `verify_output`, `ApplicationGenerator.generate` | `test_l9_generation_authority.py` (unit, mutation: forged plans, an emitter that drops/adds a class) | done (L9-P1) |
| A2 | Entry decision respected: plan entry, requested entry, generator entry and assembled launcher agree | `preflight`, `verify_output`, pipeline `entry_program=plan.oracle.entry_program` | `test_with_no_requested_entry_every_runtime_launches_the_entry_the_plan_established` (5 runtimes, red before) | done (L9-P1) |
| A3 | Program identity and boundaries preserved | `runtime_class_name`, `verify_output` | `test_every_runtime_preserves_each_programs_identity_and_boundary`, `test_exactly_the_approved_programs_verify` | done (L9-P1/P3) |
| A4 | Parser IR authoritative for statements; Application IR for relationships and provenance | unchanged (`canonicalize`); IR id carried into the generation record | `test_m4_generation.py`, `test_the_record_names_the_same_plan_as_the_plan_record` | done |
| A5 | Deterministic, reproducible output on every runtime | unchanged generators | `test_generation_is_byte_reproducible_for_every_runtime`, `test_the_record_is_reproducible_across_directories` | done (L9-P3) |
| A6 | Valid project assembly: generated Java compiles | n/a | `test_the_plain_java_project_of_every_generated_application_compiles` (all 46 generated apps, host `javac`), `test_the_jakarta_marked_project_compiles_too`, strict `KNOWN_UNCOMPILABLE` | done (L9-P3) |
| A7 | Consistent behaviour across runtime targets: one plan, one entry, one program set | pipeline | `test_all_runtimes_are_generated_from_one_plan_and_one_entry` | done (L9-P3) |
| A8 | Sealed, content-addressed generation lineage bound to the plan record | `generation_record`, `EvidenceManifest.java_generation`, `ViolationType.JAVA_GENERATION_BINDING_MISMATCH`, `ModernizationReport.generation_record`, `PipelineConfig.java_generation`, `api.service._generation_pairs` | `test_l9_generation_record.py`, `tests/evidence/test_java_generation_evidence.py`, `tests/test_java_generation_api.py` | done (L9-P2) |
| A9 | Differential: with a plan the generator emits exactly the bytes it emits without one | n/a | `test_differential_with_a_plan_the_generator_emits_the_same_bytes_or_refuses_for_the_plan` (every fixture) | done |
| A10 | Certified behaviour preserved: 110 generation hashes, Layers 6-8 and both records | n/a | `tools/generation_hashes.py --check` (identical: 92 generated, 18 refused), `test_l7_*`, `test_l8_*` | done |
| A11 | One production path; experimental producers unwired; no clock in the authority | n/a | architecture-lint tests in `test_l9_generation_authority.py` | done |

## 4. The authority (L9-P1)

`preflight(plan, application_id, discovered_program_ids, requested_entry)` refuses (all reasons listed, nothing generated): no plan; a plan for another
application; an evidence conflict; programs planned but not discovered, or discovered but not planned (a multiset comparison, so duplicate program ids
must match); any PROGRAM, CALL or COPYBOOK component that is not TRANSFORM; a plan that approves nothing; an unresolved entry; an entry that is not
itself approved; a requested entry that disagrees (compared with `normalise`). `verify_output(...)` then requires the emitted program classes to be
exactly the approved programs' classes, the mapped program ids to be the approved ids, and the selected entry class to be the plan's entry.
Both are pure (no I/O, clock or randomness; linted). Refusals surface as `Transformation plan refuses generation: ...` /
`Generated output departs from the transformation plan: ...` errors with `generated_files == ()`; a refusal is never a partial application.
Without a `plan` argument the generator behaves exactly as before (the differential test compares the two over the corpus).

## 5. The generation record (L9-P2)

| Key | Meaning |
|---|---|
| `output_digest` | sha256 of the generated project tree as written by assembly: `"<posix path>\0<file sha256>\n"` lines in sorted path order, exactly the `tree_sha256` of `tools/generation_hashes.py` (a test equates the two on every generated fixture) |
| `program_map_digest` | sha256 of the sorted `(program id, Java class)` rows under the target's `runtime_class_name` rule |
| `plan_digest`, `plan_id`, `ir_id` | the Layer 8 plan record the generation was authorised by |
| `entry_program`, `entry_class` | the plan's entry and the class it is generated as |
| `target_runtime` | closed vocabulary `runtime_registry.RUNTIME_KEYS` |
| `application_id`, `source_hash` | identity; `source_hash` must equal the manifest's own source identity |

Binding rules. `build_record` returns `()` (never a partial record) when the plan, plan record, programs, entry, runtime or tree is missing or
inconsistent, when the generated programs are not exactly the approved programs, or when the tree holds a symlink. The evidence validator requires the
exact key set, lower-case digests, a known runtime, non-empty identities, the source hash, **a plan record beside it**, and equal `application_id`,
`ir_id`, `plan_digest`, `plan_id` between the two. `verify_record` re-derives the record and names every differing key. The manifest key is
conditional: a manifest without it keeps its exact hash. The record is advisory lineage: it never changes generation or a verdict, and (unlike
`ProducerManifest`) carries no clock.

## 6. Limits and remaining work (stated up front)

* `output_digest` is the digest of the tree **as generated**. A project that has since been built (`target/`) legitimately differs; the record is
  written before any build and is not re-derivable from a built tree.
* Spring Boot names classes in PascalCase (`StudentProcessor`) and the other targets use `Student_Processor`. Both are deterministic and recorded per
  target; unifying them is a deliberate output change and is not made here.
* Only `plain_java` and `jakarta_ee` are compiled by the Layer 9 tests (they need no framework jars); the Spring Boot, Quarkus and Micronaut projects are
  compiled and executed by the certification lanes (`certification.yml`, Docker), not by these hermetic tests.
* `workload-studentproc` generates Java that does not compile: its source cuts a data name at column 72 (GnuCOBOL rejects it; the certified verdict is
  UNAVAILABLE). It is pinned as a strict known exception; its hash is part of the 110 and is unchanged.
* The corpus hash tool still covers `spring_boot` and `plain_java` only (`DEFAULT_RUNTIMES`); the other three targets are covered by the determinism and
  identity tests here and by the four-runtime certification.
* The plan's `base_package` remains an unconsumed label (see `LAYER8_DESIGN.md` 6).
* Dependency order stays advisory: programs are emitted in discovery order, which the hashes pin (reordering would move them).
* `ProducerManifest` is left as is (experimental, timestamped); the dialect `profile_id` is still not recorded in generation (it would change hashes of
  untouched output; `LAYER_MODEL.md` contract 3).
