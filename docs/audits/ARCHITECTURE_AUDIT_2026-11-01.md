# Repository architecture audit and remediation plan (2026-11-01)

Baseline: `feat/phase2-e2e-validation` @ `6050335` (stacked on PR #7, PR #8).
Read-only audit; nothing in this document has been changed yet.  Execution
is tracked in [CHANGE_LEDGER.md](CHANGE_LEDGER.md); the import graph is
[DEPENDENCY_MAP.md](DEPENDENCY_MAP.md) (regenerate with
`python tools/dependency_map.py`).

Principles for every change below: deterministic and no LLM; GnuCOBOL is
the only authority for supported semantics; anything unsupported fails
closed; a fix starts with a red test; the do-not-regress ledger (§5) stays
green; commit only after focused tests, and push only after the full
regression for the wave; exact-SHA CI confirms each push.

## 1. Inventory

| Area | Tracked files | Production Python | Notes |
|---|---:|---:|---|
| `engine/` | 112 | ~45k lines | transformation 28.6k (42 modules), validation core 15.7k, modernization 4.3k |
| `api/` | 14 | ~6.3k | FastAPI; `service.py` 1.8k is the orchestration hub |
| `frontend/` | 57 | — | React + Vite + TS, 16 vitest files; one HTTP client (`src/api/client.ts`) |
| `tests/` | 637 | — | 4,767 tests collected; 324 files under `tests/verification/` are generated outputs |
| `fixtures/` | 185 | — | 48 COBOL applications (`fixtures/*/cobol`) |
| `docs/` + root | 95 + 46 md | — | many superseded/duplicate reports (§4.6) |
| `scripts/`, `tools/` | 14 | — | e2e runners not in CI |
| `test-artifacts/` | 48 | — | force-added despite `.gitignore`; stale junk except `docker-image-provenance.json` |

Endpoints (19), the per-run data flow, and per-module inventories are in
the dependency map and in §2.

## 2. Data flow of one modernization run

`POST /applications/{id}/ingest` → `api.ingestion.ingest_zip` +
`discover_application` (`ApplicationDiscovery`, `JclDiscovery`) →
`POST /modernize` → `Service._modernize_background` →
`UniversalModernizationPipeline.execute` (capability analysis →
`TransformationPlanGenerator` → `ApplicationGenerator` →
`runtime_adapters` assembly) → `Service._run_validation` →
`VerticalSlicePipeline.run`: `DockerOracleAdapter.execute` (cobc in Docker)
→ candidate adapter (`DockerSpringBoot` / `DockerJava` / Maven) →
`ArtifactCapturer` → `ComparatorRegistry` comparators →
`EvidenceManifest` (sealed) → `EvidenceIntegrityValidator.validate` →
`derive_verdict_validated` → store → `/verdict`, `/approval`, `/download`.

## 3. Verified P0 findings (false success or unchecked trust)

Each item was reproduced or confirmed against the code by hand, not taken
from an audit report on trust.

| ID | Finding | Evidence |
|---|---|---|
| **P0-1** | `ASSIGN TO 'file'` (single quotes) or an ASSIGN literal on the next line: the SELECT parser misses the path, every OPEN/CLOSE/START/REWRITE/DELETE becomes a comment and READ inlines its success body — producer reports **success**. | `cobol_parser.py:1120` vs `_validate_file_organizations` (`:1016`); `mapping:509, 4134, 4288…`; reproduced |
| **P0-2** | Fixed-format continuation lines (`-` in column 7) are not handled: `VALUE 'ABCDEFGHIJ` + `-    'KLMNOP'.` → `"ABCDEFGHIJ -    "`, **success**, no diagnostic. | `cobol_parser.py:565-582`, `copybook_model.py:456`; reproduced |
| **P0-3** | Mapping state lives in module globals (`_main_entry_context`, `_io_var_counter`, `_times_loop_counter`) while the API runs up to 4 jobs on threads: a concurrent mapping can lower EXIT PROGRAM in a CALLed program to a no-op and interleave counters. | `cobol_to_java_mapping.py:446-482, 3935, 5321`; `api/service.py:84, 422` |
| **P0-4** | Approval race: the VERIFIED check runs outside the store lock and `Store.set_run_approval` is an unconditional `UPDATE … WHERE id=?`; a revalidation in between receives the stale APPROVED. | `api/service.py:1503-1519`, `api/store.py:713-722`, `:780-790` |
| **P0-5** | Download checks only `approval_state`, never re-checks the verdict or evidence. | `api/app.py:1087-1094` |
| **P0-6** | Evidence integrity does not check comparison pairing (one ORACLE + one CANDIDATE artifact, matching type, distinct ids) nor result self-consistency (`MATCH` with differences); four declared violation types are never raised. | `engine/evidence/integrity.py:379-404, 49-67` |
| **P0-7** | Silent drops in renderers and the Spring lane: Spring rewrite turns an unresolved CALL into a comment (no `UNSUPPORTED_CALL$`); unknown expressions render as `""`; `map_cobol_statement` has no final `else`; an unknown `selected_service` runs every service. | `java_to_spring_mapping.py:276-320`; `java_generator.py:1115`; `spring_boot_generator.py:293-302, 797`; `mapping:3579-5044` |
| **P0-8** | Verdict views (`run_verdict_state`, `get_verdict`) use a weaker gate than approval/artifacts (hash pair only, no `EvidenceIntegrityValidator`): the dashboard can show VERIFIED for evidence `/artifacts` rejects. | `api/service.py:1393-1440` |

## 4. P1/P2 findings (summary)

### 4.1 Transformation engine
- Two producers gate differently (`producer.py:140-200` fails closed; `producers/internal_native.py:128-133` maps warnings to PARTIAL, never scans for `UNSUPPORTED_*`).
- `RETURN-CODE` is not modelled (undeclared `RETURN_CODE`, javac fails; Spring always `System.exit(0)`); with derivation treating any oracle nonzero exit as UNAVAILABLE, a program ending with RETURN-CODE 4 can never verify.
- Two diverging Java renderers (`java_generator.py:932-1131`, `spring_boot_generator.py:606-818`) plus a third in `copybook_model.render_model_class`; entry generation spread over mapper, generator f-string, Spring runner and `runtime_adapters`; `jakarta_ee` is a pom profile only.  These block Quarkus/Micronaut/Liberty adapters.
- Layering: generator imports the mapper (`java_generator.py:174`); Spring generator and runtime adapter call private helpers of `JavaGenerator`; the oracle imports `transformation.source_format` (reference depends on the system under test); `producers/opensource4j.py` imports execution infrastructure; `cics`/`jcl`/`sql` packages sit at engine root but are transformation subdomains (package-level cycles).
- Size: `map_cobol_statement` 1,509 lines; `map_cobol_program_to_java` 372; parser 4.1k lines.
- Dead: `source_model.py` (whole module), legacy COBOL-direct region of `java_generator.py:1139-2028` (~890 lines, tests only), shadowed duplicate methods, ~15 zero-caller helpers (see DEPENDENCY_MAP).
- Duplicated: fixed-format normalisation (parser and copybook model), three COPY regexes, three class-name helpers giving different names (`Pay_Calc` vs `PayCalc`).

### 4.2 Validation core
- Infrastructure failures are classified as program behaviour: candidate compile infra failure → `nonzero_exit` → FAILED; Docker exit 125-127/137 → `nonzero_exit`; oracle infra error → ERROR before UNAVAILABLE is checked.
- Untrusted evidence can still derive PARTIAL/FAILED (`derivation.py:161`).
- Bindings skipped when fields are absent (oracle digest None, workload id None); candidate image digest unbound; default Java lane image unpinned (`DockerJavaConfig.digest=""`).
- Comparator identity checked against a static table, not the registry that ran; comparator version unbound.
- Seal is unkeyed (detects accidental corruption, not forgery) — a design decision, see §6.
- Declared-missing artifact → INCONCLUSIVE but undeclared one-sided file → MISMATCH (inconsistent); missing vs empty artifacts indistinguishable; short fixed-record file raises instead of MISMATCH; output files keyed by basename (subdirectory collisions).
- Oracle/candidate environment values partly declared rather than observed (compiler version, runtime id, limits).
- ~150 lines of Docker invocation/timeout/staging duplicated across the oracle and three candidate adapters, with unreachable `proc.kill()`; `execution/docker_runner.py` unused; `_run_legacy` kept only for ~10 tests.

### 4.3 Modernization layer
- `TransformationPlanGenerator` copies only `UNRESOLVED` CALL verdicts into the plan; analyzer arity/cycle verdicts and COPYBOOK SKIPs never block generation (safety relies on the later central-status gate).  The stricter `ModernizationPlanner` is tested but not used in production — two plan policies.
- Analyzer and mapper define the UNSTRING subset separately (empty-delimiter disagreement); three statement walkers; dead `except (AttributeError, TypeError): pass` over non-existent IR attributes.
- `ApplicationAssembler` (hard-coded `@SpringBootApplication`) unused.

### 4.4 API and frontend
- Run views re-run discovery on the *current* source tree (not the run's); `generated_app_path` stored per application, approval per run; `/detail` re-parses the tree on every 1.5 s poll.
- Integrity failures swallowed (`except Exception: discovery = None`; UI `.catch(() => null)`); one corrupt run 500s the whole run list.
- `Service` god-object (~1,400 lines, 21 `except Exception`); `/discovery` handler bypasses the service.
- Frontend hard-wired to Spring Boot; `target_runtime` and the certification contract are not in the TS types; verdict/approval states are plain `str` at the boundary; `discovery_success=True` default.
- Server filesystem paths exposed in responses; dead `IngestRequest` and five unused client wrappers.

### 4.5 CI, tests, dependencies
- Docker lane can pass by skipping (only `docker_lane.txt` entries are fail-not-skip; ~20 inline `pytest.skip("Docker not available")`).
- No CI job runs the hermetic (lane-off) suite, so the `docker_lane.txt` staleness check never runs in CI.
- Capability-truth gate list is hand-maintained (has broken three times: `b7f6246`, `6891b19`, `57fc673`).
- Phase 2 e2e runner is manual and always exits 0.
- Tests import private helpers from other test modules; `_docker_available` ×16, `_reset_store` ×13, `_run_gnucobol` ×7.
- J-3 fix (`ce72949`) has no direct regression test.
- `pytest-asyncio` unused; `pydantic`/`starlette`/`PyYAML` imported but undeclared; production image installs test deps; no hashes in the lock.

### 4.6 Documentation and repository hygiene
- 45 root-level reports (most 10-30/10-31 agent reports), several duplicated or superseded; root `COBOL_CAPABILITY_MATRIX.md` contradicts `docs/CAPABILITY_MATRIX.md` (claims DB2/CICS runtime and full file I/O).
- README points to `opencode.md` as the live checkpoint (stale since 10-27); `docs/ARCHITECTURE.md` predates current modules; KNOWN_ISSUES has items already fixed (BL-108/109, D-9 supply chain).
- Missing: CONTRIBUTING, LICENSE (despite the decision record), CHANGELOG, runtime-adapter guide, docs index.
- `test-artifacts/` (48 force-added files) and `tests/verification/` (324 generated files including whole Spring apps) are stale generated output.

## 5. Do-not-regress ledger

Fixes that must stay green (full table with SHAs in the git-history audit;
the pinning tests are the contract):
approval needs VERIFIED + hash match (`091fc21`, BL-091
`test_phase12_p4_bl091_approval_workflow.py`); verdict trust boundary
(`6e64bb4`, `tests/verdict/`); J-9 mixed states `any()`
(`2a1a3ef` — reverted once, `test_j9_mixed_states.py`); capability truth
for COMP/REDEFINES/OCCURS/88/BY CONTENT/ROUNDED (P0-1..5); figurative
constants (BL-018); no dropped statements in scoped constructs
(BL-019..025); STRING/figurative fill (BL-027..030); copybook
nested/REPLACING/ambiguity (BL-031..035); GO TO comment+diagnostic
(BL-026 — reverted once); BigDecimal numerics (`393ac13`); container
hardening and production auth (`c0c4f9b`, `62e647f`); ZIP ingest
hardening; lost updates/optimistic concurrency (BL-139..145); false-success
baseline (`091fc21`, `a40be88`); Phase 2 (`4687404`, `57fc673`,
`6050335`).  Fragile areas (history of reverts): `engine/verdict/derivation.py`,
GO TO handling, the CLAIMS fixture, oracle digest pinning, the
pytest-only capability gate.

## 6. Prioritized remediation plan

Waves run in order; each item is one verifiable change with a red test
first.  ✋ = needs the owner's decision before execution.

**Wave A — close false-success routes (P0)**
1. A1 Unify SELECT/ASSIGN parsing (single/double quotes, optional `TO`, literal on the next line); a file verb on an FD with no resolved path is UNSUPPORTED and the mapper raises instead of commenting. GnuCOBOL pin for `'…'` ASSIGN. (P0-1)
2. A2 Fixed-format `-` continuation: fail closed now (UNSUPPORTED_CONSTRUCT in parser and copybook model); full support is a Phase 3 coverage item with oracle pins. (P0-2)
3. A3 Replace mapping globals with a per-call context; two-thread determinism test. (P0-3)
4. A4 Conditional approval write (`validation_generation` + stage), and download re-checks VERIFIED + evidence. (P0-4, P0-5)
5. A5 Integrity: comparison pairing and result self-consistency; adversarial tests. (P0-6)
6. A6 Fail closed in renderers/Spring lane: raise on unknown expressions/statements, `UNSUPPORTED_CALL$` in the Spring rewrite (+ `JavaDoWhile` recursion), unknown `selected_service` refuses. (P0-7)
7. A7 One verdict gate for every verdict view. (P0-8)
8. A8 Plan generator takes every non-SUPPORTED analyzer CALL/COPYBOOK verdict; generation blocks. Add the missing J-3 regression test.

**Wave B — make CI tell the truth**
9. B1 Docker lane: a skip caused by missing Docker/Java/image fails when `RUN_DOCKER_TESTS=1`.
10. B2 CI job for the hermetic lane (enables the `docker_lane.txt` staleness check).
11. B3 Capability-truth list from one manifest read by CI (ends the pytest-only gate breakage); `tools/dependency_map.py --check` in that job.
12. B4 Infrastructure failures classified as `error`/UNAVAILABLE, never program FAILED; untrusted evidence never better than ERROR. (fragile area — `derivation.py`; J-9 tests stay green)

**Wave C — architecture for a multi-runtime platform** (behaviour-preserving refactors; full regression + Docker lane after each)
13. C1 One `JavaSourceRenderer` for statements/expressions used by every backend.
14. C2 `ContainerRunner` shared by oracle and candidate lanes; adapters declare runtime id, image, command, limits (feeds observed evidence).
15. C3 Runtime-adapter port owning entry/host shape (`main`, `RUN_UNIT$ENTRY`, Spring runner, pom) — prerequisite for Quarkus/Micronaut/Liberty.
16. C4 `map_cobol_statement` → dispatch table that raises on unknown statement types; single-source fixed-format/COPY/class-name helpers; one statement walker for analyzer and mapper; one UNSTRING predicate.
17. C5 Align `InternalNativeJavaProducer` gating with `TransformationProducer`.
18. C6 Split `Service` (ingest / run orchestration / proof queries / approval); per-run discovery snapshot and generated path.

**Wave D — cleanup** (deletions only after grep + full regression)
19. D1 Remove dead code: `source_model.py`, legacy `java_generator.py` COBOL-direct region (repoint its tests), zero-caller helpers, `ApplicationAssembler`, unused `docker_runner` (or absorb into C2), dead API model/client wrappers.
20. D2 ✋ `ModernizationPlanner`: delete, or adopt as the single plan policy.
21. D3 Shared test helpers (`tests/common.py`), ban cross-test private imports.
22. D4 Dependencies: declare pydantic/starlette/PyYAML, drop pytest-asyncio, split runtime/dev locks ✋ (production image change).
23. D5 ✋ Untrack `test-artifacts/` junk and `tests/verification/` generated output; archive root reports into `docs/reports/archive/`; reconcile README/ARCHITECTURE/KNOWN_ISSUES; delete the contradicting root capability matrix; add CONTRIBUTING and a runtime-adapter guide.

**Decisions for the owner (✋)**: keyed evidence seal (key custody); D2; D4 lock split; D5 history-visible moves/untracking.

Wave A starts immediately after Phase 2 CI is green; Phase 3 coverage work
resumes after Wave B, building on C1-C4.
