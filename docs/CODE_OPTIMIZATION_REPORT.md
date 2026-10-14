# Stage D — Code Optimization Report

**Branch:** `codex/universal-core` (unmerged; PR #2 remains open pending human authorization)
**Method:** deterministic no-LLM audit (Stage C) → behavior-preserving edits (Stage D) → test renames (Stage E) → validation (Stage F)

---

## 1. Scope and hard constraints

Every edit in this stage satisfies **all** of the following. Anything that could
not be proven to satisfy them was excluded and is listed in §8.

1. **Behavior-preserving only.** No observable output, exception contract,
   public API surface, security boundary, or evidence artifact changes.
2. **No test-set changes.** No test deleted, skipped, weakened, or added;
   assertions untouched; collection identity stays exactly 3476 tests.
3. **No mixing with behavioral fixes.** Audit-found defects (`[E]`) were *not*
   fixed here; all 29 are filed as BL-040…BL-068 in `docs/BACKLOG.md`.
4. **Fewer lines ≠ better.** Deduplication was accepted only where the
   duplicated code was *provably* identical (or provably equivalent for every
   input), not merely similar.
5. **Evidence integrity.** `test-artifacts/*` churn stays uncommitted.

## 2. Method

Stage C produced per-area audit reports (`T1`–`T8`) and per-area naming audits
(`N1`–`N4`) with findings tagged `[E]` (defect), `[C]` (correctness hazard),
`[D]` (dead code), `[U]` (unnecessary duplication), `[P]` (repeated work),
`[S]` (safe simplification). Stage D consumed only `[D]/[U]/[P]/[S]` items
whose equivalence was re-verified line-by-line against the current code before
any edit was scripted. Every batch was applied by an idempotent, anchor-exact
script (exact-once assertions, `BATCH2_CHECK` dry-run mode) and validated by
the full 3476-test suite before the next batch started.

## 3. Batch 1 — dead code and redundancy (`[D]`/`[U]`/`[S]`)

53 Python edits across 21 files. Categories with the exact edit tags:

| Category | Edits (tag examples) |
|---|---|
| Dead methods removed | `_extract_primary_threshold`, `_extract_output_fields`, `_find_record_name`, `_parse_set`, `_build_step_dependencies`, `_resource_comment`, `_execute_workload_sql`, `_opt_int`/`_opt_hash`, `is_nullable` field |
| Dead branches / stores / loops | no-op `PerformStatement` branch, dead branch 1143-1144, dead loop 1370-1375, no-op dead block 321-324, dead `closed=True` store, dead `symbols` init, always-False `sysin` init, unreachable duplicate raise, unreachable unknown fallbacks |
| Redundant conditions | redundant conjunct 1277, subsumed `TIMES$` conjunct 2014, duplicate union member 658, redundant `.cob` conjunct 398, redundant line re-strip 1099 |
| Import hygiene | hoist `ComputeStatement`, drop shadowing re-imports (`copybook_resolver`, `dataclasses.replace`, `json`, `tz`), drop unused imports (`Any`, `JclSymbol`, `CobolApplication`), `dc_replace`→`replace`, `__import__("re")`→`re.split`, module-level `import re`, `tz.utc`→`timezone.utc` |
| Unused parameters removed | `_parse_dd(lines)`, `_step_comment(job)`, `_build_step_method(job, base_package)`, `_claim_for(stmt_semantic)` |
| Call-site simplification | `jcl_to_spring_batch` no-op program reset 186-187, `_parse_dd` call sites, `sysin` kwarg (dataclass default) |

All 53 compile; import smoke passed; suite green (§7).

### Batch 1-F — frontend

12 edits across 8 files (`App.tsx`, `Header.tsx`, `IntegratedProof.tsx`,
`PipelineStepper.tsx`, `Sidebar.tsx`, `index.css`×3, `Dashboard.tsx`×2,
`ModernizationRun.tsx`×2): dead branches, redundant conditionals, and
duplicate style rules. Gates: `npm run build` (tsc + vite) ✓, `npx vitest run`
122/122 ✓.

## 4. Batch 2 — shared-helper extraction (`[U]` verbatim duplication)

49 edits: **5 new modules** + 44 delegation/import edits. Every duplication
site was verified *verbatim identical* (modulo comments) before extraction;
where tests patch an internal (e.g. `DockerSpringBootCandidateAdapter._check_docker`),
the original method name is kept as a thin delegate so patchability is
preserved.

| New module | Replaces | Sites |
|---|---|---|
| `engine/docker_cli.py` | `check_docker_available()` (docker info/10s), `cleanup_container()` (stop/rm/inspect forensic triple) | `_check_docker`×4 adapters, `_cleanup_container`×2 adapters. Spring's variant (`docker ps`/30s) delegates with explicit parameters — its semantics are preserved exactly. |
| `engine/source_hash.py` | `compute_source_tree_hash()` (sorted rglob, relative-path + bytes) | oracle `_compute_source_hash`, runner `compute_source_hash` (kept as delegate to preserve the public surface). Dropped now-unused `hashlib`/`pathlib` imports. |
| `engine/transformation/sql_split.py` | `split_sql_statements()` (quote-aware `;` splitter) | `sql_parser._split_statements`, `db2_sqlite._split_statements` (db2's empty-statement filter stays at its call site — the two differ *only* there). |
| `engine/transformation/jcl_dependencies.py` | `build_all_dependencies()` (step-order + EXEC + DD loops) | `JclParser._build_all_dependencies`, `JclDiscovery._build_dependencies` (both verbatim copies removed). |
| `api/limits.py` | `env_int_limit(name, default, logger)` | `api/app._env_limit`, `api/ingestion._zip_limit` (verbatim pair). Service's two clamping parsers differ and were left alone. |

Additional extractions: `validator._load_contract_version` (5 verbatim
sites), `jcl_consumer._result_for` (2 sites differing only in `source_path`),
`analyzer._collect_select_read_columns` (select vs declare-cursor), CICS
mapper `_value_name` reuse (provably equivalent for all inputs incl. empty).

## 5. Batch 3 — micro-optimizations (`[P]`/`[S]`)

34 edits. Each item removes repeated work or collapses provably-equivalent
branches. Equivalence argument in parentheses.

| File | Edit (equivalence) |
|---|---|
| `api/service.py` | lazy `jcl_status` default (`k in d` + `d[k]` ≡ `d.get(k, fn())`); single `_upload_file_limit()` read (env cannot change mid-comparison) |
| `engine/pipeline.py` | `_compute_source_identity` single rglob walk (digest bytes identical: same sorted order; counts identical: same file set) |
| `engine/transformation/sql_parser.py` | module-level `_HOST_VARIABLE_RE` + `_PREDICATE_OP_MAP` (constants; not rebuilt per statement/call) |
| `engine/sql/dialect.py` | `_PORTABLE_STATEMENTS` → `frozenset` (membership-only; same keys) |
| `engine/sql/analyzer.py` | compiled `_INTO_CLAUSE_RE`/`_FROM_AFTER_RE` (same patterns, compiled once) |
| `engine/sql/execution.py` | `_run_simple` single execute site (exactly one `execute()` per call in both versions) |
| `engine/sql/model.py` | `table_names()` → `dict.fromkeys` (first-occurrence order kept) |
| `engine/sql/db2_sqlite.py` | identity branch collapsed (both paths return the identical string) |
| `engine/transformation/jcl_discovery.py` | single-walk `_find_jcl_files` (extensioned vs extensionless suffix sets disjoint; `sorted(set())` normalizes); RESOLVED/UNRESOLVED merged (metadata strings identical) |
| `engine/transformation/application_discovery.py` | single-walk `_find_cobol_files` (same disjoint-suffix argument) |
| `engine/jcl/model.py` | `names` hoisted out of the dependency loop (invariant across the loop) |
| `engine/transformation/jcl_parser.py` | subsumed inline-data disjunct (`"*"` ⊂ `startswith("*")`; both branches set only `is_inline`) |
| `engine/jcl/builder.py` | continuation regex dropped (matches a strict subset of `stripped.startswith(",")`) |
| `engine/jcl/diagnostics.py` | `has_errors`/`has_warnings` → `bool(self.errors/warnings)` (same predicate over the same list) |
| `engine/cics/mapper.py` | `_resp_policy` single return (policy then one return; same first-match order) |
| `api/name_derivation.py` | `import io` (replaces `__import__("io")` per call) |
| `engine/transformation/figurative.py` | `_RESERVED_FIGURATIVES = frozenset(CANONICAL_FIGURATIVES)` (whole-token membership ≡ the 12-alternative `fullmatch`: alternation cannot cover a longer token, edge lookarounds always pass) |
| `engine/transformation/ir.py` | `is_numeric` → `figurative.ZERO` (value-identical constant; no import cycle — figurative imports only `re`) |
| `engine/transformation/jcl_to_spring_batch.py` | `_ACTIVATION_BY_CONTROL_KIND` module table (same entries, same KeyError-on-unknown); enum identity instead of `.value` string compare (unique enum values) |
| `engine/transformation/copybook_model.py` | no-op `replace()` kwargs dropped (`dataclasses.replace` preserves unoverridden fields) |
| `engine/candidate/java_adapter.py` | `_EXEC_TIMEOUT_SECONDS` constant (subprocess timeout and evidence field cannot desync) |

## 6. Items reviewed and EXCLUDED (with reasons)

Honesty record — candidates from Stage C that were **not** applied:

| Item | Reason for exclusion |
|---|---|
| extractor double-clean collapse `[S]` | T4's idempotency claim is **false**: a cleaned line whose content starts with six digits (e.g. a `770100-WS`-shaped name) is re-stripped by pass 2 today; removing pass 2 would change output. |
| COND exit-status shared table `[U]` (builder ↔ mapper) | T4's "same strings" claim does not hold: mapper uses `EXIT_STATUS_ANY = "*"`, builder writes literal `"ANY"` — different vocabularies; unifying would change output. Also requires a package-cycle-prone import. |
| `_raw_for_job` pre-scan `[P]` | Equivalence argument non-trivial (scan vs consumption order); needs dedicated tests first. |
| `_build_dataset_edges` union `[U]` | Edge-count semantics (producer-present vs producer-absent with zero consumers) are subtle; deferred pending targeted tests. |
| `_fresh_build_ref`/`_fresh_runtime_ref` `[U]` | Parameterization must reproduce per-role error strings exactly; deferred to keep batches reviewable. |
| Docker capture-method blocks `[U]`, compare methods `[U]`, `_run_legacy` `[U]` | Large mechanical consolidations; out of the small-batch discipline. |
| `_mask_comments` reuse `[P]`, copybook resolve `iterdir`/`rglob` caching `[P]`, workload-contract caching `[P]`, `CobolParser()` construction `[P]` | Caching introduces staleness risk; rejected for this pass. |
| api store migrations `[U]`, frontend `useMemo` `[P]`, subset-version table `[U]` (do-not-change), T2 copybook cycle-check `[U]`, disclaimer-text `[U]` | Intentional/low-value or flagged do-not-change by the audit itself. |
| Batch 1 skips (documented in place) | `cobol_parser` 2007 `PERFORM WITH TEST` disjunct, oracle jar-glob `if`, `DockerSandboxEvidence`, `capture_missing(status)` param, `subset.py _ALL_KNOWN_COMMANDS` — each differed from its twin in a way that mattered. |

## 7. Validation

Per-batch gates (all local runs use explicit `tests/ …` paths to avoid
untracked `tmp/codex-pytest*` rootdir breakage):

| Gate | Result |
|---|---|
| Batch 1 suite (3476 baseline) | 3472 passed, 4 skipped, **0 failed** — the 4 skips are the pre-existing `RUN_DOCKER_TESTS` env-gated tests in `test_claims_transformation.py` (untouched since baseline commit `a399b60`); the Docker daemon is not running locally, and CI runs them green with `RUN_DOCKER_TESTS: "1"` (ci.yml L116) |
| Batch 1 frontend | `npm run build` (tsc) ✓, `npx vitest run` 122/122 ✓ |
| Batch 2 suite (3476 baseline) | 3472 passed, 4 skipped, **0 failed** (JUnit `batch2_junit.xml`: 3476 tests, 0 failures, 0 errors, 4 skipped) — identical skip set to Batch 1 (`TestClaimsCandidate::test_generated_java_compiles` + 3 `TestClaimsInputVariation` Docker-gated tests); runtime 42m51s |
| Batch 3 + Stage E combined full suite (post-rename tree) | 3460 passed, 4 skipped, **12 failed** — all 12 in the Docker/timeout lanes (`test_forensic_evidence`, `test_inventory_generalization`, `test_phase7d_runtime`, `test_e2e` verdict rendering), the documented load-sensitive environmental class (BL-010/BL-017 baseline); every failing test **passes in isolation** (forensic timeout/cleanup 2/2, `TestInventoryMutations` 9/9, phase7d + e2e re-run clean) — no failure is rename-related; evidence `%TEMP%\opencode\phase4\stageDE_fullsuite.txt` + junit |
| Stage E collection identity | **3476 before renames → 3476 after renames** (`pytest --collect-only -q tests`); 136 method renames applied, 0 problems; focused capability-truth gate + renamed-file batch → **592 passed** |
| Final full suite + fresh CI on exact final SHA | *pending — exact-SHA CI run is the run of record for the Docker-gated tests* |

Import smoke: 34 modules (both SQL modules imported in both orders — no
cycle between `engine.sql.*` and `engine.transformation.*`).

## 8. Defects NOT fixed here

The 29 audit-found `[E]` defects (1×P0, 8×P1, 17×P2, 3×P3) are filed as
BL-040…BL-068 in `docs/BACKLOG.md` with full §77 fields (severity, location,
evidence, impact, proposed remediation, status OPEN). The P0 (BL-040): a
valid `STRING ... INTO T.` without `END-STRING` silently loses subsequent
PROCEDURE DIVISION statements.

## 9. Result

- 136 Python edits + 5 new shared modules + 12 frontend edits, all compiled.
  Validation status is exactly the §7 table: Batch 1 and Batch 2 suites
  green (0 failed); the combined Batch 3 + Stage E suite's only failures are
  the 12 Docker/timeout-lane environmental tests (load-sensitive class,
  isolated reruns pass); collection identity 3476 preserved through the 136
  renames. The exact-SHA CI run on the final commit is the run of record.
- No public API, exception contract, evidence artifact, or capability label
  changed. Capability labels, evidence formats, and contract versions are
  untouched.
- No merge into `main` will occur without explicit human authorization.
