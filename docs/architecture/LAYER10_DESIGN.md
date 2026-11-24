# Layer 10 design: Build, packaging and runtime targets

Status: **closed with stated limits (2026-11-24): L10-P1, L10-P2, the B4 fix and the audits of section 5 done and certified on `c223e07` (fast CI, supply chain, four-runtime corpus certification, dispatched full integration all green).** Open by decision, not defect: byte-reproducible jars (would change generated poms and the 110 generation hashes; needs an explicit decision). From `785fba4` (Layer 9 complete and certified). Deterministic, open source
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
| B2 | `validate_candidate` (Spring/Maven lanes) checks only that declared files exist, not their hashes | **reclassified, not a gap**: `validate_candidate` is never called in production (`grep` over `engine/` and `api/` finds only the definitions), and the manifest it would check is derived from the same tree moments earlier, so a hash check there would be circular. The real check is B1's binding against the *sealed* generation digest | no change; documented |
| B3 | The build lane did not identify the artifact it produced | the runnable artifact was not content-addressed in the evidence | **closed in L10-P2** |
| B4 | The before/after candidate source-tree hash (`_candidate_source_tree_hash`) excluded any path with a part named `target`, `build`, `out`, `.git`, `node_modules` or `__pycache__`, at any depth, while the candidate identity excluded only the top-level `target` | a file written or rewritten under a nested `src/out/` (or `build/`, ...) during build or execution left `source_tree_hash_before == after`: the mutation check the evidence validator enforces was blind there (probed: a file added under `src/out/` did not move the hash) | **closed**: only top-level build-output directories are excluded; a top-level *file* with such a name is source |

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

## 3b. L10-P2: the built artifact is content-addressed (`engine/candidate/build_record.py`)

`EvidenceManifest.build_artifact` (conditional sealed key; a manifest without it keeps its exact hash) holds `artifact_digest` (sha256 of the jar the lane
built and then executed: the execution is staged from exactly those bytes), `artifact_name` (a bare `.jar` name) and `built_tree_digest` (the project tree
the build ran on, `target/` excluded, the Layer 9 algorithm). `VerticalSlicePipeline` builds it from the compilation result of a **successful** build that
produced **exactly one jar and nothing else**; no jar, several jars, a class file, a path-like name or an unhashable tree give no record. The evidence
validator (`BUILD_ARTIFACT_BINDING_MISMATCH`) requires the exact key set, lower-case digests and a bare jar name, and, when the manifest also carries a
Layer 9 `java_generation` record, `built_tree_digest == output_digest` (what was built is what was generated). A refused candidate (L10-P1) never reaches
the builder and so records no artifact. Advisory lineage: it never changes a verdict. Tests: `tests/candidate/test_build_record.py`,
`tests/evidence/test_build_artifact_evidence.py`, and three end-to-end cases in `tests/test_candidate_generation_binding.py` (a one-jar lane seals the record
equal to the generation digest; a lone class file and a refused candidate seal none).

### B4 fix and tests

`VerticalSlicePipeline._candidate_source_tree_hash` now skips a file only when it lies under a **top-level** directory in `_SOURCE_TREE_EXCLUDED_DIRS`.
Generated projects contain no such nested directory, so their candidate hashes and all 110 generation hashes are unchanged; an uploaded candidate that does is
now hashed more strictly (the safe direction). `tests/test_candidate_mutation_hash.py` (13 tests): a file added under each of six nested directory names moves
the hash; the four top-level build-output names do not; a top-level file named `target` is source; edits move it; it is deterministic.

## 4. Remaining Layer 10 work (not started; stated up front, not claimed)

* The real Maven/Docker build is exercised by the certification lanes, not by these hermetic tests (the lane is doubled; the jar digest is that of the bytes
  the double returns). The jar is not reproducible byte for byte (Maven embeds timestamps), so `artifact_digest` identifies *this* build, not a rebuild.
* Four-runtime build and execution certification of L10-P1/P2 on the exact SHA (Docker lanes): dispatched for each push, see the ledger.

## 5. Audits completed without a code change (evidence, not assumption)

* **Runtime-target parity.** `tests/test_runtime_registry.py` and `tests/test_runtime_selection.py` already pin the registry as the single source for the
  engine tables, the certified set as the certification matrix, the API's accepted set and `candidate_adapter_for_target` (fail closed on an unknown
  target); `tests/test_framework_runtimes.py` keeps the offline image's pre-cached Quarkus/Micronaut set in step with the generated poms. All pass.
* **Container hardening.** `tests/test_container_hardening.py` scans every `"docker", "run"` site under `engine/` and requires the shared
  `container_run_hardening_flags` (`no-new-privileges`, `--cap-drop ALL`, `fsize` ulimit, non-root `--user`) at each; `NON_ROOT_EXEMPT_LANES` is empty. All pass.
* **Generated build files are pinned** (new, `tests/candidate/test_generated_pom_pinning.py`, all five targets): no floating version (range, `LATEST`,
  `RELEASE`, `SNAPSHOT` on anything the build fetches; the artifact's own `0.0.1-SNAPSHOT` is excluded), every property/plugin/dependency version is a
  concrete release or a property, and the Java release is declared concretely (17 or 21). Found no defect.
