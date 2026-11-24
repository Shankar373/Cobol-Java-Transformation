# Layer 10 design: Build, packaging and runtime targets

Status: **started (2026-11-24): L10-P1 implemented; the layer is NOT complete.** From `785fba4` (Layer 9 complete and certified). Deterministic, open source
only, no LLM. Language coverage is frozen; Layer 11 is not started.

Scope (`LAYER_MODEL.md`): `engine/candidate/**` (build + execute lanes), `engine/execution/**` (containers, hardening, workspace files),
`engine/docker_cli.py`, `engine/transformation/runtime_adapters.py` (assembly, covered by Layer 9) and `runtime_registry.py`.
Output: a runnable artifact per runtime target.

## 1. Audit so far (what exists)

* **Targets.** `runtime_registry.RUNTIME_TARGETS` is the single table: `spring_boot` (lane `spring_boot`), `plain_java`, `quarkus`, `micronaut`
  (lane `maven`, certified) and `jakarta_ee` (lane `maven`, generated but not certified, not accepted by the API).
  `candidate.factory.candidate_adapter_for_target` resolves the lane from the table and fails closed on an unknown target.
* **Lanes.** `DockerSpringBootCandidateAdapter` builds any Maven project offline (`mvn -o package`) and runs the jar in a disposable container;
  `MavenProjectCandidateAdapter` is its honestly-named subclass for the dependency-free and command-mode targets. `PlainJavaCandidateAdapter` and the
  host `RealJavaCandidateAdapter` are never selected by the service (the placeholder raises rather than fabricate a result, audit D-6).
* **Validation pipeline** (`engine.pipeline.VerticalSlicePipeline`) records the candidate source-tree hash before and after build/execute
  (`_candidate_source_tree_hash`, build directories excluded) and derives `candidate_hash`; a build that cannot run is an infrastructure error
  (verdict `ERROR`), a build that ran and failed is a nonzero exit (verdict `FAILED`).

## 2. Gaps found

| # | Gap | Effect | Status |
|---|---|---|---|
| B1 | Nothing tied the project handed to the build lane to the project Layer 9 generated. The pipeline hashed the tree before and after the build, but only to show it was not *rewritten during* validation, never that it *was the generation's output* | a project edited, extended or truncated between generation and validation would be built, run and compared as if it were that generation; the sealed generation record's `output_digest` was never consulted after sealing | **closed in L10-P1** |
| B2 | `validate_candidate` (Spring/Maven lanes) checks only that declared files exist, not that their bytes are the declared hashes | a declared file with other content passes validation | open (L10-P2) |
| B3 | The build lane does not identify the artifact it produced (jar digest) in evidence | the runnable artifact is not content-addressed | open (L10-P2) |

## 3. L10-P1: the build lane validates only the project generation recorded

`generation_record.generation_binding_problem(pairs, project_dir)` re-derives the project's tree digest with the Layer 9 algorithm, leaving out only
the top-level Maven output directory `target/` (`BUILD_OUTPUT_DIRS`), and compares it with the recorded `output_digest`. `VerticalSlicePipeline`
calls it with the run's `java_generation` pairs before the build: on a mismatch (or an unhashable tree: missing directory, symlink) the adapter is **not
called**, the candidate is recorded as an infrastructure error (`termination_status=error`, `execution_phase=BUILD`, verdict `ERROR`, never a
comparison) and the message names both digests. With no record (an uploaded candidate, a run that never went through generation) nothing is bound
and behaviour is unchanged. A nested `target/` directory is *not* excluded (only the top-level build output is), so source cannot hide under one.

Tests (`tests/test_candidate_generation_binding.py`): the untouched project is bound; build outputs do not move the digest while the unexcluded digest
does; edit / add / remove / rename / nested-`target` are each refused; a missing project and a symlink are refused; end to end through the real
service with the candidate lane doubled, an untouched project reaches the builder once and a project edited after generation never does and ends `ERROR`.

## 4. Remaining Layer 10 work (not started; stated up front, not claimed)

* B2: verify declared candidate files by hash in `validate_candidate`.
* B3: content-address the built artifact (jar) and bind it to the generation record in the execution evidence.
* Parity audit of every `RUNTIME_KEYS` row against its adapter, pom content (pinned versions, offline cache coverage) and the build image identity.
* Container hardening and workspace-file handling audit (`engine/execution/**`) against the certified contract.
* Four-runtime build and execution certification of the above on the exact SHA (Docker lanes).
