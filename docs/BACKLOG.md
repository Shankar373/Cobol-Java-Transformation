# SystemaOps Defect and Gap Backlog

**Status:** live backlog (authoritative per Master README Section 77).
**Audit date:** 2026-10-10 (Phase 0 closure remediation)
**Audited repository:** `Shankar373/Cobol-Java-Transformation`
**Audited branch:** `codex/universal-core`
**Audit baseline HEAD:** `55f885dae77bd415fc60db6d90e59ef26fc47944` ("docs(checkpoint): record final local regression and CI job status")
**Baseline CI:** [Push CI #453 — SUCCESS](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045547063), [PR CI #454 — SUCCESS](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045549842), [Supply chain #35 — SUCCESS](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045547098), [Supply chain #36 — SUCCESS](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045549866).
**Note:** These are baseline results. Fresh CI for the documentation remediation commit must be verified separately before Phase 0 is marked complete.

Authority hierarchy (Master README Section 78):
`MASTER_IMPLEMENTATION_README.md` > `opencode.md` > registries/contracts > current verification/status reports > historical reports.

Priority guidance (Master README Section 77): P0 = incorrect business semantics, false VERIFIED/certification, trust-boundary bypass, critical security exposure, or
data-loss risk; P1 = major required workflow/capability failure; P2 = important
coverage/quality/documentation gap; P3 = lower-risk improvement.

Verification vocabulary: **VERIFIED** (reproduced this audit with cited evidence),
**STATIC** (read from source/tests, not executed here), **HISTORICAL** (previously
produced evidence, not re-run here).

---

## P0 — correctness, capability truth, trust

### BL-001 — Producer capability declaration contradicted the authoritative registry
- **Type:** defect (capability truth)
- **Status:** FIXED — 2026-10-10 (this audit/implementation session)
- **Observed behavior:** `engine/transformation/producers/internal_native.py` returned
  a hand-maintained `supported_constructs`/`unsupported_constructs` list on every
  `TransformationResult`. It declared `GO TO` **supported** (registry: UNSUPPORTED),
  `OCCURS` supported (no registry key; mapping unverified), and `COMPUTE`,
  `SUBTRACT`, `MULTIPLY`, `CALL`, `EVALUATE` **unsupported** (registry: SUPPORTED).
- **Expected behavior:** Producer metadata must never contradict the authoritative
  registry (`engine/transformation/semantic_capability.py`), per Master README
  Sections 14 and 77 and `docs/COBOL_UNIVERSALITY_ROADMAP.md` P0-1.
- **Root cause:** Stale duplicated capability list that drifted from the registry.
- **Affected files:** `engine/transformation/producers/internal_native.py`.
- **Source:** `docs/COBOL_UNIVERSALITY_ROADMAP.md` §12 P0-1; static read.
- **Impact:** Any consumer of producer metadata received a false UNSUPPORTED for
  supported sends and a false SUPPORTED for `GO TO`. Direct capability-trust defect.
- **Remediation:** Derive both lists from `CONSTRUCT_REGISTRY` by capability level so
  contradiction is impossible by construction; PARTIAL constructs are claimed by
  neither list.
- **Acceptance criteria / tests:**
  `tests/transformation/test_capability_registry_reconciliation.py` (11 tests) —
  no supported claim is registry UNSUPPORTED/PARTIAL, no unsupported claim is registry
  SUPPORTED/PARTIAL, every registry SUPPORTED/UNSUPPORTED key is represented, and the
  exact P0-1 cases (`GO TO`, `COMPUTE`, `SUBTRACT`, `MULTIPLY`, `CALL`, `EVALUATE`).
- **Evidence:** `python -m pytest tests/transformation/test_capability_registry_reconciliation.py tests/transformation/test_producer_contract.py` → 29 passed (2026-10-10).
- **Last verified commit:** (this session commit — see `opencode.md`).

### BL-002 — COMP / COMP-3 USAGE silently ignored (no diagnostic, no registry key)
- **Type:** defect (no silent loss)
- **Status:** FIXED — 2026-10-10 (this session)
- **Observed behavior:** `PIC S9(4) COMP` parses with zero diagnostics; the USAGE
  clause and its storage-encoding semantics are dropped without a trace.
  `engine/transformation/cobol_parser.py` had no `USAGE`/`COMP`/`COMP-3` handling and
  `DataItem` carried no usage field; the registry had no `COMP`/`COMP-3` keys.
- **Expected behavior:** Master README Sections 18/19/60: recognized constructs must
  produce explicit diagnostics and honest capability classification, never silent loss.
- **Root cause:** USAGE clause never modeled.
- **Affected files:** `engine/transformation/cobol_parser.py`,
  `engine/transformation/ir.py`, `engine/transformation/semantic_capability.py`,
  `engine/modernization/capability_analyzer.py`,
  `engine/transformation/application_discovery.py`,
  `docs/SEMANTIC_PROOF_MATRIX.md`.
- **Source:** `docs/COBOL_UNIVERSALITY_ROADMAP.md` §12 P0-2 / §6.1.
- **Impact:** Silent narrowing of numeric storage semantics; false confidence for
  COMP/COMP-3 workloads.
- **Remediation (implemented):**
  * `DataItem.usage: str | None` records the canonical USAGE token (COMP, COMP-1,
    COMP-2, COMP-3, COMP-5; synonyms COMPUTATIONAL/BINARY/PACKED-DECIMAL collapse;
    DISPLAY/absent → None).
  * Parser extracts the clause in WORKING-STORAGE, FILE SECTION and
    `parse_data_description_lines` (copybooks), and emits a non-blocking
    `PARTIAL_SUPPORT` diagnostic per item.
  * Registry keys `COMP`/`COMP-1`/`COMP-2`/`COMP-3`/`COMP-5` at PARTIAL
    ("value semantics only; byte encoding excluded"); `canonical_usage` +
    `USAGE_TO_CONSTRUCT` helpers; source patterns for the copybook classifier.
  * Capability analyzer walks `DataItem.usage` and classifies the program PARTIAL;
    discovery filters `PARTIAL_SUPPORT` out of the loss channel so it never forces
    UNSUPPORTED. Mapper/runtime behavior unchanged.
- **Acceptance criteria / tests:**
  `tests/transformation/test_usage_capability.py` (22 tests) — parser records usage
  (incl. synonyms, file-section, literal/field-name negatives), emits
  PARTIAL_SUPPORT, analyzer classifies `workload-comp`/`workload-comp3` PARTIAL
  (never SUPPORTED), no-usage program stays SUPPORTED, registry keys PARTIAL.
- **Evidence:** `pytest tests/transformation/test_usage_capability.py` → 22 passed;
  `workload-comp`/`workload-comp3` → PARTIAL (2026-10-10).
- **Last verified commit:** (this session commit — see `opencode.md`).

### BL-003 — REDEFINES / OCCURS / 88-level mapping unverified, no registry keys
- **Type:** defect (capability truth)
- **Status:** FIXED — 2026-10-10 (this session)
- **Observed behavior:** Fixtures `workload-redefines`, `workload-occurs`,
  `workload-level88` parse, but no mapping-output or runtime evidence was found and
  the registry has no keys for `REDEFINES`, `OCCURS`, or 88-level conditions.
- **Expected behavior:** Master README Sections 19/60; roadmap P0-3. A construct that
  parses but is unproven must not be presented as supported.
- **Affected files:** `engine/transformation/semantic_capability.py`,
  `engine/modernization/capability_analyzer.py`, `docs/SEMANTIC_PROOF_MATRIX.md`.
- **Source:** roadmap §10 / §12 P0-3.
- **Impact:** Parsed-but-unproven constructs invite false confidence.
- **Remediation (implemented):**
  * Registry keys `REDEFINES` / `OCCURS` / `88-LEVEL` at UNKNOWN (fail-closed,
    never SUPPORTED) until a full-ladder runtime proof exists.
  * Source patterns for the copybook classifier (data-division scan).
  * Capability analyzer scans the DATA DIVISION explicitly (the procedure-
    restricted scan cannot see these) and emits UNKNOWN findings.
  * Negative tests: `OCCURS DEPENDING ON` blocked; 88-level program UNKNOWN;
    plain program stays SUPPORTED.
- **Acceptance criteria / tests:**
  `tests/transformation/test_structural_capability.py` (9 tests) — registry keys
  UNKNOWN, `workload-redefines`/`workload-occurs` UNKNOWN, `workload-level88`
  non-SUPPORTED, minimal 88-level UNKNOWN, `OCCURS DEPENDING ON` blocked, plain
  program SUPPORTED.
- **Evidence:** `pytest tests/transformation/test_structural_capability.py` →
  9 passed; fixtures redefines/occurs → UNKNOWN (2026-10-10).
- **Last verified commit:** (this session commit — see `opencode.md`).

### BL-004 — BY CONTENT / BY VALUE capability hole
- **Type:** defect (capability truth)
- **Status:** **RESOLVED BY DESIGN DECISION — no code change** (2026-10-10)
- **Observed behavior:** Mapper implements sync-in/no-sync-out for BY CONTENT/BY VALUE;
  fixtures exist; no registry key means capability UNKNOWN, and no dedicated runtime
  comparison was found.
- **Expected behavior:** roadmap P0-4; honest classification of parameter modes.
- **Impact:** Parameter-mode divergence is a classic silent-divergence source.
- **Premise correction (CI evidence):** an earlier attempt in this session added
  `BY CONTENT`/`BY VALUE` registry keys at PARTIAL.  CI run #435/#436/#437/#438
  failed on `test_by_value_and_by_content_are_never_claimed_supported`, which
  asserts these modes must **never** appear as registry keys.  That negative
  contract is deliberate and predates this session: it encodes the repository's
  choice of the roadmap P0-4 option "**keep blocked**".
- **Resolution:** the registry keys and the analyzer classification were reverted.
  The conservative contract is preserved and is now documented explicitly:
  * `semantic_capability.py` carries a comment stating the modes are deliberately
    keyless, citing the negative contract test.
  * `capability_analyzer.py` records that an unproven passing mode must not derive
    a support verdict — matching the existing rule on `_analyze_call_linkage_arity`
    ("a mode that cannot be proven compatible is never guessed").
  * `docs/SEMANTIC_PROOF_MATRIX.md` documents the modes as *deliberately
    unclassified (blocked)* rather than PARTIAL.
  * Rationale: no registry key means no consumer can read a support verdict out
    of these modes, which is the conservative outcome. Mapper behavior is
    unchanged and remains correct COBOL value semantics.
- **Verification level:** VERIFIED — the previously failing contract test now
  passes (26 passed in `test_phase_d_negative_integration.py`).

### BL-005 — ROUNDED flag consumption unverified
- **Type:** defect (capability truth)
- **Status:** FIXED — 2026-10-10 (this session); recorded symptom was falsified
- **Observed behavior:** `ROUNDED` is parsed into IR on arithmetic statements but no
  mapping evidence found; no registry key.
- **Expected behavior:** roadmap P0-5 — prove the flag reaches Java or mark mapping
  UNKNOWN with a negative test.
- **Affected files:** `engine/transformation/semantic_capability.py`,
  `engine/modernization/capability_analyzer.py`, `docs/SEMANTIC_PROOF_MATRIX.md`.
- **Impact:** Rounding is a numeric-semantics risk area (Master README Section 18).
- **Premise correction:** the recorded symptom ("parsed into IR but no mapping
  evidence found") was **falsified during remediation**. The flag already reaches
  Java: `stmt.rounded` selects `java.math.RoundingMode.HALF_UP` on the receiving
  item (`_apply_numeric_receiver_semantics`), with the default staying `DOWN`
  truncation, and the pre-existing suite
  `tests/transformation/test_decimal_arithmetic_semantics.py` (10 tests) already
  asserted it. The defect was purely that the registry had no key.
- **Remediation (implemented):**
  * Registry key `ROUNDED` at SUPPORTED with mapping evidence.
  * Source pattern for ROUNDED.
  * Analyzer reads the `rounded` IR flag in the statement walk, so the verdict is
    backed by the parsed flag and the source scan no longer reports it as
    source-only.
- **Acceptance criteria / tests:**
  `tests/transformation/test_rounded_capability.py` (7 tests) — registry key
  SUPPORTED, source pattern detects it, ROUNDED program classifies SUPPORTED,
  flag reaches Java as HALF_UP, default stays truncation, plain program SUPPORTED.
- **Evidence:** `pytest tests/transformation/test_rounded_capability.py` → 7 passed
  (2026-10-10).
- **Last verified commit:** (this session commit — see `opencode.md`).

---

### BL-031 — `COPY` statements inside copybooks are silently dropped during materialization (no recursion, no cycle detection)

- **Type:** defect (no silent loss / capability truth)
- **Priority:** P0 — phase-blocking. Rationale: Master README §54 lists
  `capability truth drift` as a P0 risk and §53.9 forbids silent semantic
  loss; this defect produced **generation `success=True`, plan `READY`,
  capability `SUPPORTED`, zero diagnostics** while the emitted Java
  referenced copybook fields that were never declared (javac cannot compile
  it) — the exact BL-018/BL-030 defect shape (false green verdict over a
  broken artifact) in the Phase 3 copybook lane.
- **Severity:** high — every application whose copybooks themselves use
  `COPY` (a standard mainframe pattern) silently loses the nested
  declarations.
- **Status:** **FIXED — 2026-10-12 (Phase 3 cycle, this session)** — see the
  Phase 3 change-log entry (j) for the exact-SHA CI and full-suite evidence.
- **Found by:** the Phase 3 §76 audit-first probes (`%TEMP%\opencode\phase3\probe_colocated.py`,
  cases R2/R3, run 2026-10-12 against the real
  discovery → capability → planner → `prepare_application_copybooks` →
  `ApplicationGenerator.generate` path).
- **Observed behavior (verified, not assumed):** `OUTER.cpy`
  (`01 OUTER-FIELD …` + `COPY INNER.`) with `INNER.cpy` present next to it:
  discovery records only `OUTER` (`INNER` never enters `app.copybooks`, the
  edge list, capability or the plan); `parse_data_description_lines` ignores
  the nested `COPY` line by design, so the merged program IR contains only
  `OUTER-FIELD`; `ApplicationGenerator.generate` returns **`success=True`**
  with no errors; the emitted `Nestmain.java` references `INNER_FIELD` with
  **no declaration** (`static String OUTER_FIELD = …` only) — non-compiling
  Java; plan status `READY`, `blocking_summary=["No blocking issues
  identified"]`, `COPYBOOK:OUTER` `SUPPORTED`. Three-level nesting behaves
  the same (only the top level materializes). A **cyclic** pair
  (`CICA.cpy` ⇄ `CICB.cpy`) and a **self-copying** copybook are not detected
  at all: same silent drop, same `READY`/`success=True`. A `COPY` inside a
  `01` group is dropped along with its position in the hierarchy.
- **Expected behavior:** Master README §16/§60 (recognized constructs must
  never disappear silently; they must produce explicit diagnostics),
  §53.9 (no silent semantic loss remains), §14/§15 (fail-closed), and the
  Phase 3 requirement that copybook missing/cyclic handling is explicit —
  a nested dependency must either be materialized or fail generation with a
  diagnostic naming it.
- **Root cause:** `copybook_model.parse_copybook` fed raw copybook text
  straight to `CobolParser.parse_data_description_lines`, which deliberately
  ignores non-data lines — so a nested `COPY` statement was invisible at
  parse time; `prepare_application_copybooks` resolved only unit-level COPY
  references and had no recursion, no cycle scope and no diagnostic channel
  for copybook-internal COPY statements.
- **Affected files:** `engine/transformation/copybook_model.py` (new
  `_mask_comments`/`_find_copy_statements`/`_expand_copybook_text`/
  `_strip_sequence_numbers`/`_parse_copybook_expanded`; the `models` loop
  in `prepare_application_copybooks` now parses via the expanded path),
  `tests/test_nested_copybook_materialization.py` (new, 12 tests),
  `.github/workflows/ci.yml` (capability-truth gate selection).
- **Impact:** silent loss of nested declarations plus non-compiling Java
  under a green verdict — a §53.9/§60 counterexample reachable through the
  supported generation path.
- **Remediation (implemented, deterministic, no LLM):** before data parsing,
  copybook text is expanded **in memory only**: fixed-format (6-column
  sequence number) lines are normalized at read time exactly as
  `CobolParser.parse` normalizes program source (so sequence-numbered data
  entries and `*`/`/` indicator comment lines are handled identically);
  COPY statements are located
  comment-masked and statement-position-guarded (a `COPY` inside a VALUE
  literal or a data-name is never a dependency), the statement's span runs to
  its terminating period (so a `REPLACING` clause is consumed with it, not
  spliced as data), and the target is resolved with the existing
  `copybook_resolver` against the same search directories the generation
  lane uses. The target's expanded text replaces the statement **at the
  statement's own position**, preserving group hierarchy and sibling order.
  Missing (`COPYBOOK_UNRESOLVED`, message names the parent copybook),
  ambiguous (`COPYBOOK_AMBIGUOUS`), unreadable (`COPYBOOK_UNREADABLE`) and
  cyclic/self (`COPYBOOK_CYCLE`, message is the full `A -> B -> A` chain)
  nested targets append `ERROR` diagnostics, which fail generation through
  the existing `CopybookPreparation.has_errors` contract — never silently
  dropped, never expanded twice, never recursed without bound (cycle scope
  is the ancestor chain of the current path, so diamonds remain legal).
  Sources on disk are read only — the no-rewrite/no-concatenation contract
  is unchanged.
- **Acceptance criteria / tests:**
  `tests/test_nested_copybook_materialization.py` (12 tests, dependency-free,
  wired into the `ci.yml` capability-truth gate): nested + three-level
  nesting materialized in program IR **and declared in the generated Java**;
  position inside a group preserved (`O-A, I-MID, O-B`); missing nested
  target fails generation with a diagnostic naming the parent copybook;
  cyclic and self copybooks fail closed with `Cyclic COPY reference` and
  terminate; a comment-line `COPY` inside a copybook is never expanded;
  copybook sources are byte-identical after materialization; plus three
  format-robustness cases: fixed-format (6-column sequence number) copybook
  lines still expand (normalization mirrors `CobolParser.parse`), a `*>`
  inside a VALUE literal is data (quote-aware masking, the COPY after it
  still expands), and a `COPY` token inside a VALUE literal is never a
  dependency. No existing test weakened or skipped.
- **Evidence (defect proven first):** pre-fix the original 9 contract tests
  ran **7 failed / 2 passed**
  (`%TEMP%\opencode\phase3\bl031_pre_fix_red.txt`);
  the audit probes above captured the pre-fix green-verdict/broken-output
  facts. Post-fix: **12 passed**
  (`%TEMP%\opencode\phase3\bl031_post_fix_green.txt`); focused copybook
  suites `test_copybook_m7.py` + `test_copybook_integration_m7.py` +
  `test_application_generator_p0.py` + `test_r11_discovery_robustness.py`
  → **56 passed**; `test_phase_d_negative_integration.py` → **26 passed**;
  capability-truth gate → **334 passed** (322 + 12 new); ingestion gate →
  3 passed. Serialized full suite and exact-SHA CI: see change-log entry (j).
- **Owner/role:** copybook materialization maintainer (transformation lane).
  **Target phase:** Phase 3 (fixed in-cycle). **Dependency:** existing
  `copybook_resolver` resolution/ambiguity semantics and the
  `CopybookPreparation.has_errors` fail-closed contract. **Residual risk:**
  the capability analyzer still scans only the top-level copybook file
  (constructs inside nested copybooks are unclassified — filed **BL-039**);
  discovery still records no nested COPY edge, so a missing nested target is
  diagnosed at generation rather than at plan time (family **BL-033**);
  `REPLACING` operands are consumed but not applied (**BL-032 — FIXED
  2026-10-13**); nested
  resolution shares the generation lane's flat search directories
  (**BL-035**).

### BL-032 — `COPY … REPLACING` operands are silently ignored (wrong/empty declarations under a green verdict)

- **Type:** defect (silent loss / capability truth)
- **Priority:** P0 — same shape as BL-031: generation reports
  `success=True`, plan `READY`, capability `SUPPORTED`, zero diagnostics,
  while the replacement never happens. Found in the same Phase 3 probe round
  (`probe_colocated.py` case R1).
- **Severity:** high — `COPY X REPLACING ==&TAG-NAME== BY ==WS-NAME== …` is
  the standard mechanism for parameterized copybooks.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 2)** (see change-log entry
  (k)). Defect proven first (`%TEMP%\opencode\phase3\bl032_pre_fix.txt`:
  merged working storage **empty**, `success=True`, `Rmain.java` referencing
  an undeclared `WS_TOKEN`, `COPYBOOK:REPL` classified `SUPPORTED`), then
  fixed with deterministic (no-LLM) code.
- **Observed behavior (verified, pre-fix):** `REPL.cpy`
  (`01 &WS-NAME PIC X(&WS-LEN).`) copied with
  `COPY REPL REPLACING ==&WS-NAME== BY ==WS-TOKEN== ==&WS-LEN== BY ==8==.`:
  the merged program's working storage is **empty** (pseudo-text names are
  not valid data-names, so the entry does not parse), generation returns
  **`success=True`**, and `Rmain.java` references an undeclared `WS_TOKEN`
  while `ReplRecord.java` is an **empty** model class. `REPL` is
  `RESOLVED`, `COPYBOOK:REPL` `SUPPORTED`, plan `READY`.
- **Expected behavior:** Master README §55 lists `COPY/REPLACE` as a
  required enterprise capability; §60 requires that partially-recognized
  constructs expose the fact instead of silently discarding semantics; §14/§15
  require fail-closed behavior for anything not actually applied.
- **Affected files:** `engine/transformation/copybook_model.py` (clause
  grammar `_parse_replacing_clause`, substitution `_apply_replacing`,
  unit-level extraction `_unit_replacing_pairs`, per-program clause models),
  `engine/modernization/capability_analyzer.py` (`_scan_copy_replacing` —
  verdict truth for clauses the lane cannot apply).
- **Impact (historical):** wrong (empty or unsubstituted) declarations
  reached generated Java under a green verdict; javac failed, or — for a tag
  that happened to parse — the wrong field name was silently emitted.
- **Resolution (implemented 2026-10-13):** the `REPLACING` clause grammar is
  parsed by one deterministic implementation (`_parse_replacing_clause`:
  pseudo-text `==…==` operands possibly multi-line, COBOL-word operands,
  multiple pairs, case-insensitive) and applied by `_apply_replacing`: a
  single simultaneous left-to-right pass with COBOL word-boundary guards (a
  pattern never partially matches a longer word), quoted literals treated as
  data and never substituted, replacement text never rescanned; in-memory
  only, sources never modified. The clause lives in the *program's* COPY
  statement, so it is extracted from the unit source and applied per
  (program, target) when that reference is materialized; nested COPY
  statements inside copybooks carry their own clause, and the caller's pairs
  apply to the fully-expanded target text (nested targets included).
  Unappliable forms (`LEADING`/`TRAILING`/`PARTIAL` phrases, `+`/`-`
  prefixed operands, literal operands) and malformed clauses fail closed
  with `COPYBOOK_REPLACING_UNSUPPORTED` / `COPYBOOK_REPLACING_MALFORMED`
  diagnostics naming `REPLACING`, failing generation through the existing
  `CopybookPreparation.has_errors` contract; capability classifies such
  programs `UNSUPPORTED` via `_scan_copy_replacing`, which reuses the same
  clause parser so verdict truth cannot drift from what generation does.
- **Verification:** 23 focused tests in
  `tests/test_copy_replacing_materialization.py` (dependency-free, wired
  into the `ci.yml` capability-truth gate) → **23 passed**; capability-truth
  gate (the 13-file selection) → **357 passed**; ingestion gate → **3
  passed**; BL-031 nested + phase-D negative suites → **38 passed**,
  copybook M7 suites → **33 passed** (no existing test weakened); fresh E2E
  (`bl032_e2e_gen.py`): `generation_success=True`, `WS_TOKEN` **declared**
  (pre-fix referenced but never declared), `JAVAC_OK` (Temurin 21),
  GnuCOBOL 3.1.2 oracle **`ORACLE_MATCH=YES 1/1`**
  (`bl032_e2e_result.txt`). Serialized full suite and exact-SHA CI results
  are recorded in change-log entry (k).
- **Acceptance criteria:** all five met — (1) supported operand forms
  substitute before parsing and the declared field names appear in generated
  Java (`TestReplacingSubstitution`); (2) unsupported phrase/malformed forms
  raise an explicit diagnostic naming `REPLACING` and fail generation
  (`TestReplacingFailClosed`); (3) capability reports `UNSUPPORTED` — never
  `SUPPORTED` — for an unapplied clause (`TestReplacingCapabilityTruth`);
  (4) focused tests joined the capability-truth gate (`ci.yml`); (5) no
  existing test weakened.
- **Owner/role:** copybook materialization maintainer. **Target phase:**
  Phase 3. **Dependency:** BL-031's statement scanner (implemented).
  **Residual risk (bounded, documented):** pseudo-text containing a period
  truncates the statement span and fails closed as malformed (never silently
  mis-applied); a tagged nested COPY target (`COPY &LIB`) fails closed as
  unresolved; when one program copies the same target twice with different
  clauses the first statement's pairs win; clause-parameterized copybooks
  get per-program merged IR and deliberately no shared model plan
  (substituted content is program-specific); plan-time fail-open for the
  BL-033 family still precedes generation (tracked separately).



## P1 — required workflow / operational gaps

### BL-006 — No central defect/gap backlog existed
- **Type:** documentation/process
- **Status:** FIXED — 2026-10-10 (this file created)
- **Observed behavior:** Master README Section 77 requires a central backlog; none
  existed (only `docs/REMEDIATION_MATRIX.md` and roadmap prose).
- **Remediation:** This document.

### BL-007 — `opencode.md` checkpoint was stale
- **Type:** documentation/process
- **Status:** FIXED — 2026-10-10
- **Observed behavior:** `opencode.md` claimed HEAD `7ae5873`, clean working tree, and
  prerequisites-not-installed, while the working tree had untracked files and the
  remote was one commit ahead (`81e7955`). It was also untracked in git.
- **Remediation:** Rewritten as a live checkpoint and committed (Master README
  Sections 64–68).
- **Evidence:** See `opencode.md`.

### BL-008 — Integrated-proof wiring claim contradicts code
- **Type:** documentation contradiction
- **Status:** FIXED — 2026-10-10 (this session)
- **Observed behavior:** `docs/SYSTEMAOPS_PRODUCT_STATUS.md` §18 states
  "`integrated_proof_from_pipelines` not yet wired into `api/service.py` (Phase E)",
  but `api/service.py` now calls `integrated_proof_from_pipelines` /
  `runtime_evidence_from_result` and persists
  `run.modernization_report["integrated_proof"]`, exposed via
  `api/app.py:get_run_integrated_proof` and `services/service.py:get_integrated_proof`.
- **Expected behavior:** Master README Section 78 — reconcile contradictions via an
  explicit documented decision; actual repository state wins.
- **Affected files:** `docs/SYSTEMAOPS_PRODUCT_STATUS.md` (and any doc echoing it).
- **Impact:** Documentation understates implemented behavior; undermines trust in
  status docs.
- **Remediation (implemented):** `docs/SYSTEMAOPS_PRODUCT_STATUS.md` §18 now records
  the wired proof path with its concrete locations (`api/service.py`
  `runtime_evidence_from_result` during validation, persistence as
  `run.modernization_report["integrated_proof"]`, `get_integrated_proof` with a
  recompute fallback, and the `api/app.py` route), and explicitly notes that the
  earlier "not yet wired" claim contradicted the code and was removed. No other
  document echoed the stale claim, so nothing else needed changing.
- **Verification level:** VERIFIED by static read of `api/service.py` lines 164, 230,
  986–1016, 1142–1160 and `api/app.py` line 615.

### BL-009 — Live status documents cite a stale baseline commit / CI run
- **Type:** documentation contradiction
- **Status:** FIXED — 2026-10-10 (this session)
- **Observed behavior:** `README.md`, `docs/PROJECT_STATUS.md`,
  `docs/SYSTEMAOPS_PRODUCT_STATUS.md`, `docs/CURRENT_DELIVERY_STATUS.md`,
  `docs/VERIFICATION_STATUS.md`, `docs/ARCHITECTURE.md`, `docs/CONTRACT_STATUS.md`,
  `docs/KNOWN_ISSUES.md`, `docs/REMEDIATION_MATRIX.md`,
  `docs/reports/CURRENT_PROJECT_STATE.md` all cited baseline `fedb7dd` /
  Push CI #417 / PR CI #418, while HEAD had moved well past that.
- **Expected behavior:** Master README Section 78 — every live status report must
  identify its verified commit and audit date.
- **Impact:** Readers cannot tell which commit the status describes; drift risk.
- **Remediation (implemented):** added a dated **Baseline note** to the header of
  all ten live status documents, stating that their SHA / CI run IDs are a dated
  snapshot rather than a live pointer, and that the current verified commit and
  CI conclusions live in `opencode.md` and `docs/BACKLOG.md`.  The documented
  remediation choice was "explicitly label the older references as of their date"
  rather than rewriting historical references, so no historical run ID was
  altered.  `docs/COBOL_UNIVERSALITY_ROADMAP.md` was deliberately **not**
  annotated: its `fedb7dd` / #417 / #418 references are part of the historical
  audit narrative (and it already tracks a newer baseline), so rewriting them
  would destroy provenance.
- **Verification level:** VERIFIED by static read of all ten files.

### BL-010 — Local Windows validation limits (no host JDK; Docker-in-Docker blocked)
- **Type:** operations/environment
- **Status:** BLOCKED (environment) — re-documented 2026-10-11 at `bdb4c9a`
- **Observed behavior (accurate as of `bdb4c9a`, corrected from the earlier
  "Docker unusable" wording):**
  * **No JDK on the Windows host PATH.** `javac`/`java` are absent, so every
    test that shells out to the host compiler fails with
    `FileNotFoundError: [WinError 2]` — at HEAD that is exactly **22**
    `tests/transformation/*` tests (zero assertion failures among them) plus
    **4** `tests/integration/test_vertical_slice.py` tests. The 4 vertical
    tests do fail through assertions, but the asserted value is itself the
    missing toolchain (`compilation_errors=('Java compiler not available',)`;
    `candidate_stderr=b'Java compiler not available'`, `use_docker_java=False`)
    — a missing-toolchain failure, not a behavioral one. Verified in the clean
    serialized run of 2026-10-11: 26 failed = 22 + 4, an exact subset of the
    `b8a746f` baseline identities (zero new failures).
  * **Docker Desktop (WSL2) is running and container execution works
    locally.** During this audit Docker containers were observed executing on
    this host (`javac-*` containers from
    `engine/candidate/docker_java_adapter.py`, `maven-*` containers from the
    offline Spring Boot builder); `gnucobol-ocesql`, `maven-offline-springboot`
    and `eclipse-temurin:21-jdk` images are present with RepoDigests; and in
    the HEAD full-suite run the three `tests/integration/test_forensic_evidence.py`
    tests **passed locally**. The earlier blanket statement that local
    Docker-backed gates "cannot be re-run" is therefore **too strong** and has
    been corrected.
  * **Docker-in-Docker binding is still blocked** (`systemaops-dind`) and was
    **not** retried — the standing instruction forbids Docker-in-Docker retries
    and any WSL2/kernel/cgroup/Docker security change.
  * **Two local-Docker failure modes observed at HEAD, both only under
    concurrency:** (a) `oracle image identity is not established: docker image
    'gnucobol-ocesql:latest' resolved to no immutable digest` when a second
    process is rebuilding/retagging the image at the same moment; (b) `Java
    execution timeout` in the candidate adapter when two full suites compete
    for the Docker daemon. Both disappear when suites are serialized, which is
    why the "serialize full-suite runs" rule in `opencode.md` is mandatory and
    not advisory.
- **New local Linux lane (verified 2026-10-11):** the prepared
  `systemaops-audit` container (Ubuntu, `javac`/`java` 21.0.12, Python 3.12,
  host Docker socket bind-mounted, repo available at `/repo`) can execute the
  host-JDK-dependent tests locally. Run against a copy of the tree at
  `bdb4c9a`: the **11 javac-dependent transformation files pass — 71 passed,
  4 skipped** (all 4 skips are the deliberate `RUN_DOCKER_TESTS` gate), i.e.
  the exact 22 host failures are proven missing-JDK, not defects.
- **Expected behavior:** Master README Sections 34/50 — Docker is authoritative
  and fresh E2E must run; blocked Docker validation must use the Linux CI
  environment.
- **Impact:** host-JDK-dependent local evidence comes from the audit container
  or from Linux CI, never from the Windows PATH. Docker-dependent
  oracle/candidate/fresh-E2E gates are validated by exact-SHA Linux CI
  (Push #501 / PR #502 at `bdb4c9a`), with local Docker execution usable but
  not authoritative.
- **Remediation:** Do not retry Docker-in-Docker or change
  WSL2/kernel/cgroup/Docker security settings (explicit instruction). Serialize
  full-suite runs. Use the audit container for host-JDK-dependent checks and
  Linux CI for Docker-dependent validation.
- **Verification level:** environment-observed + verified by execution
  (container run above); **Last verified commit:** `bdb4c9a`.

---

### BL-033 — An unresolvable or ambiguous COPYBOOK classifies `SUPPORTED` and the plan says `READY` while generation deterministically fails

- **Type:** defect (capability truth / planning semantics)
- **Priority:** P1 — major planning/capability failure. Not P0 because no
  wrong artifact is produced: generation itself fails closed with explicit
  `COPYBOOK_UNRESOLVED` errors and the central proof status stays
  NOT_VERIFIED (the Phase-D negative contracts still hold). P1 because the
  capability graph and the plan — the documents a consumer acts on —
  positively assert the opposite of what the same run's generation does.
- **Severity:** medium-high — §54 `capability truth drift` on the
  dependency component, plus an unreachable fail-closed path in the planner.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 3)** (see change-log entry
  (l)). Defect proven first (`%TEMP%\opencode\phase3\bl033_pre_fix.txt`:
  missing/ambiguous/quoted targets all classified `SUPPORTED` with plan
  `READY` and `blocking_summary=["No blocking issues identified"]` while
  generation failed `Missing COPY target`), then fixed with deterministic
  (no-LLM) code. Resolution: `_analyze_copybook` now fails closed — any
  reference that is `UNRESOLVED`, `AMBIGUOUS`, or otherwise without a
  resolved path (including mixed sets where one consumer resolves and
  another does not) classifies `UNSUPPORTED` with a reason naming the
  copybook and its resolution status; the planner's
  `_map_blocking_reasons` maps copybook reasons containing
  missing/unresolved/ambiguous to `MISSING_COPYBOOK` (previously the mapping
  was unreachable dead code). The consuming program's verdict is unchanged;
  resolved copybooks keep `SUPPORTED`.
- **Found by:** Phase 3 audit probes (`probe_phase3.py` P1/P2/P4;
  `probe_colocated.py` R5 — same real discovery → capability → planner →
  generation path).
- **Observed behavior (verified):** a program `COPY MISSING-REC.` with no
  such file on disk: discovery records `resolution=UNRESOLVED`;
  `_analyze_copybook` returns **`SUPPORTED`** ("Copybook dependency
  discovered; declarations are consumed as program source context …
  (resolution=UNRESOLVED)"); `CopybookPlan.may_proceed=True`; plan
  **`READY`** with `blocking_summary=["No blocking issues identified"]`;
  generation then fails: `Missing COPY target: MISSING-REC (in M5)` +
  `Program M5 references COPY MISSING-REC with no materialized model`.
  An **AMBIGUOUS** copybook (two equal-precedence candidates, which
  discovery itself marks `resolution=AMBIGUOUS`) behaves identically —
  `_analyze_copybook`'s `not resolved_paths` branch collapses both statuses
  to `SUPPORTED`. The planner's `BlockingReason.MISSING_COPYBOOK` mapping
  (reason must contain "copybook" + "missing") is **dead code** on this
  path: the capability level is `SUPPORTED`, so `_map_blocking_reasons`
  returns early and the reason text never contains "missing". A quoted
  target (`COPY 'P2REC'`) hits the same contradiction (capability
  `SUPPORTED`/plan `READY`, generation `Missing COPY target: 'P2REC'`).
  Contrast: a missing CALL target is classified non-SUPPORTED with a
  dedicated negative contract (`test_unresolved_call_is_classified_not_supported`)
  — the copybook has no mirror.
- **Expected behavior:** Master README §14/§15 (fail-closed), §20
  (capability must reflect actual transformability), §53.2/§53.9 (contracts
  satisfied, no false green); PLM (Phase 3) requires honest
  capability/planner outcomes for COPYBOOK dependencies.
- **Affected files:** `engine/modernization/capability_analyzer.py`
  (`_analyze_copybook` early-return branch), `engine/modernization/modernization_planner.py`
  (`_build_copybook_plan`, `_map_blocking_reasons`).
- **Impact:** a `READY` plan and `SUPPORTED` dependency promise a
  transformable application that the same run cannot generate; the planner's
  missing-copybook blocking reason can never fire.
- **Remediation (planned):** classify a copybook whose reference is
  `UNRESOLVED` or `AMBIGUOUS` as non-SUPPORTED with a reason that names the
  copybook and its resolution status (so `_map_blocking_reasons` produces
  `MISSING_COPYBOOK`), keeping the *consuming program's* verdict unchanged
  unless its own constructs warrant otherwise; add a capability-truth
  negative contract mirroring the CALL one.
- **Acceptance criteria:** (1) missing/ambiguous/quoted-unresolvable
  copybook components are never `SUPPORTED`; (2) the plan for such an
  application is not `READY` and carries `MISSING_COPYBOOK`; (3) a plan may
  not report "No blocking issues" when generation deterministically fails
  for the same inputs; (4) resolved copybooks keep their current verdicts;
  (5) focused tests join the capability-truth gate; no existing negative
  contract weakened.
- **Owner/role:** capability/planning maintainer. **Target phase:**
  Phase 3. **Dependency:** discovery's `CopybookReference.resolution`
  values; planner blocking-reason mapper. **Residual risk:** until fixed,
  consumers reading only the plan overestimate readiness (generation still
  protects the final verdict).

### BL-034 — Comment lines and string literals create phantom CALL/COPY dependencies (raw-source extraction)

- **Type:** defect (false dependency / workflow blocking)
- **Priority:** P1 — a *valid* application is blocked at plan time and can
  even fail generation because of text that is not executable code.
- **Severity:** medium — conservative direction (fail-closed on good input,
  never fail-open), but it blocks correct workloads with misleading reasons.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 4, combined P1 cycle with
  BL-035)** (see change-log entry (m)). Defect proven first
  (`%TEMP%\opencode\phase3\bl034_pre_fix.txt`: comment-only CALL +
  string-literal CALL text produced two phantom `UNRESOLVED_CALL` edges and
  a `PARTIAL` plan for a program with no executable CALL; a comment-only
  `COPY` produced a phantom `CopybookReference` and made a valid program
  fail generation with `Missing COPY target`), then fixed with
  deterministic (no-LLM) code. Resolution: a single literal-aware scanner
  (`_scan_call_copy`, `_CALL_COPY_SCAN`) replaces the raw regexes in both
  extractors — comment lines are blanked offset-preservingly, and the
  alternation priority consumes any string literal or `*>` inline comment
  that is not the verb's own operand, so only real statements produce
  edges/references; a word guard keeps identifier suffixes (MYCALL,
  X-COPY) out. Real single/double-quoted/bare CALLs and COPYs are still
  extracted and still fail closed when unresolved; USING handling and the
  negative contracts are unchanged. (The BL-034 probe also exposed a
  BL-033 residual: the planner's unanchored `"call" in reason` test read
  the word "determi**call**y" in the copybook reason as a CALL — hardened
  to a word-boundary match in the same cycle.)
- **Found by:** Phase 3 audit probes (`probe_phase3.py` P5; `probe_silent.py`
  Q6; `probe_colocated.py` R4).
- **Observed behavior (verified):** (a) a program containing only the
  comment `      *    CALL 'X'.` and `DISPLAY "CALL 'Y' …"` produces two
  unresolved CALL edges (`X`, `Y`) → plan `PARTIAL`/blocked with
  `UNRESOLVED_CALL`; (b) a comment `      *    COPY NOT-A-REAL-BOOK.`
  becomes a real `CopybookReference(resolution=UNRESOLVED)` and a `COPY`
  edge, and — because generation resolves unit-level refs —
  `ApplicationGenerator.generate` **fails**: `Missing COPY target:
  NOT-A-REAL-BOOK (in CM)` — a comment-only COPY makes the program
  ungeneratable, while capability simultaneously reports the component
  `SUPPORTED` and the plan `READY` (cross-defect with BL-033). Root cause:
  `_extract_calls` / `_extract_copybooks` in
  `engine/transformation/application_discovery.py` run regexes over the raw
  source, while the sibling `_extract_file_dependencies` already masks
  comments (`_COBOL_COMMENT_LINE`, `_COBOL_INLINE_COMMENT`,
  `_COBOL_STRING_LITERAL` are defined but unused by these two extractors);
  the parser's own CALL extraction (`_parse_call`) is statement-aware, so
  the two lanes also disagree on multi-line CALL (see BL-036).
- **Expected behavior:** Master README §14/§20 (a dependency must exist in
  code, not in comments); false blocking of correct input is a workflow
  failure; phantom dependencies also corrupt the application graph that
  Phase 3 exists to build.
- **Affected files:** `engine/transformation/application_discovery.py`
  (`_extract_calls`, `_extract_copybooks`).
- **Impact:** valid programs blocked (`UNRESOLVED_CALL`) or fail generation
  (`Missing COPY target`) on comment/string text; the call/copybook graph
  carries edges that do not exist.
- **Remediation (planned):** apply the existing comment/inline-comment
  masking (and literal-aware CALL-target extraction, since CALL targets are
  themselves quoted) to both extractors, with statement-position guarding
  as in BL-031; keep every *real* unresolved dependency visible and
  classified exactly as today.
- **Acceptance criteria:** (1) comment/string-only CALL/COPY text produces
  no edge, no component and no generation error; (2) real CALL/COPY
  statements (single- and double-quoted targets, multi-line) are still
  extracted and still fail closed when unresolved; (3) positive and
  negative focused tests join the gate; (4) no existing dependency contract
  weakened.
- **Owner/role:** application discovery maintainer. **Target phase:**
  Phase 3. **Dependency:** the masking helpers already present in
  `application_discovery.py`. **Residual risk:** until fixed, phantom
  edges remain reachable; note BL-033 would newly *block* the phantom
  copybook case conservatively (still fail-closed, but noisy) — the two
  should be fixed together or BL-034 first.

### BL-035 — Discovery and generation search different directories for copybooks (subdirectory layouts: `RESOLVED`/`READY` then `Missing COPY target`)

- **Type:** defect (capability/generation contradiction)
- **Priority:** P1 — the standard "copybooks in their own directory"
  layout is discovered as resolved and planned `READY`, then fails
  generation.
- **Severity:** medium-high for real corpora (copybook directories are
  conventional); zero for flat layouts.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 4, combined P1 cycle with
  BL-034)** (see change-log entry (n)). Defect proven first
  (`%TEMP%\opencode\phase3\bl035_pre_fix.txt`: subdir layout → discovery
  `RESOLVED` with the `cb\` path, capability `SUPPORTED`, plan `READY`,
  generation `Missing COPY target: OUTER (in NESTMAIN)` +
  `…no materialized model`; flat control fine in both lanes), then fixed
  with deterministic (no-LLM) code. Resolution: one search-directory
  authority — `copybook_resolver.copybook_search_dirs` (root first, then
  every directory that holds a file, sorted) now feeds **both** lanes:
  `ApplicationDiscovery._copybook_search_dirs` delegates to it, and
  `prepare_application_copybooks` uses exactly that set when
  `source_root` is given (the legacy unit-parent path remains only for
  the no-`source_root` fallback). Per-directory scan stays non-recursive
  (`iterdir`), ambiguity stays an explicit error in both lanes (never
  first-match), resolver precedence rules untouched.
- **Found by:** Phase 3 audit probe `probe_silent.py` (Q3/Q4/Q5), 2026-10-12.
- **Observed behavior (verified):** with sources at `<root>/` and copybooks
  at `<root>/cb/OUTER.cpy`: `ApplicationDiscovery._copybook_search_dirs`
  scans **every subdirectory recursively** (`rglob`), so discovery records
  `resolution=RESOLVED` with the absolute path and capability reports
  `SUPPORTED` / plan `READY`; but `prepare_application_copybooks` builds its
  search list as `[source_root] + unit source parents` only and
  `copybook_resolver._candidate_files` is **non-recursive** (`iterdir`), so
  generation fails `Missing COPY target: OUTER (in NESTMAIN)` +
  `…no materialized model`.
- **Expected behavior:** one resolution authority: either discovery's
  search set is what generation uses, or both are restricted identically —
  §14/§15/§20 require the verdict and the artifact-producing path to agree.
- **Affected files:** `engine/transformation/application_discovery.py`
  (`_copybook_search_dirs`), `engine/transformation/copybook_model.py`
  (`prepare_application_copybooks` search-list construction),
  `engine/transformation/copybook_resolver.py` (documented non-recursive
  per-directory scan).
- **Impact:** layout-dependent false failure of the generation lane behind
  a `READY` plan; also affects BL-031 nested resolution (same search list).
- **Remediation (planned):** share one deterministic search-directory
  builder between discovery and generation (recursion and precedence
  decided once, ambiguity still an explicit error, never first-match).
- **Acceptance criteria:** (1) a copybook found by discovery is found by
  generation for the same tree, in every layout either lane accepts;
  (2) ambiguity/missing semantics unchanged (explicit errors); (3) focused
  tests cover flat, nested and duplicate-name layouts in the gate;
  (4) no existing resolution test weakened.
- **Owner/role:** copybook resolution maintainer. **Target phase:**
  Phase 3. **Dependency:** `copybook_resolver` precedence rules (BL-001-era
  contract tests in `test_copybook_m7.py`). **Residual risk:** until fixed,
  subdirectory layouts fail generation after a green plan.



### BL-011 — Reconciliation audit hook (producer lists ⊆ registry) not enforced in CI
- **Type:** test/quality
- **Status:** FIXED — 2026-10-10 (this session)
- **Observed behavior:** roadmap §16 recommends a reconciliation test; BL-001 added
  one for the internal native producer only. No generic guard covered every producer.
- **Remediation (implemented):**
  * New `tests/transformation/test_producer_capability_consistency.py` covers **both**
    producers under `engine/transformation/producers/`.
  * Deterministic-lane producers must agree with the registry in **both**
    directions; every producer (any lane) must declare a non-empty capability
    surface, never claim a construct both ways, and only use members that are
    registry keys or declared structural vocabulary.
  * `test_capability_registry_reconciliation.py` extended: every registry key must
    resolve to a verdict automatically (so BL-002…BL-005 keys could not be added
    without the producer noticing), and PARTIAL/UNKNOWN keys must appear in neither
    list.
  * Hoisted the opensource4j adapter's inline capability tuples to module-level
    `_PRODUCER_SUPPORTED_CONSTRUCTS` / `_PRODUCER_UNSUPPORTED_CONSTRUCTS` so its
    claims are inspectable without running the external compiler.
- **Scope decision (documented, not erased):** the opensource4j adapter is an
  *external* lane requiring `libcobj.jar`, not the deterministic lane the registry
  describes. It legitimately claims `GO TO` / `SORT`, which our mapper cannot
  express. Forcing it to mirror the registry would falsify its real behaviour, so
  the divergence is now **asserted explicitly** by
  `test_external_producer_divergence_is_known_and_bounded` (which pins the exact
  divergence set) instead of being hidden.
- **Verification level:** VERIFIED (both producers; 67 tests pass in the focused run).

### BL-012 — CI depth below roadmap target
- **Type:** test/quality
- **Status:** PARTIALLY FIXED — 2026-10-10 (capability gate added)
- **Observed behavior:** CI ran only ingestion, backend/oracle/Docker, and
  frontend jobs. Capability truth was enforced only inside the Docker-gated
  backend job, so a producer/registry contradiction surfaced after the full
  COBOL/Java image build and was easy to misattribute. No coverage thresholds or
  mutation testing.
- **Source:** Master README Sections 51/54 (P2), `docs/KNOWN_ISSUES.md` P2.
- **Remediation (implemented):** added a dedicated **`capability-truth`** CI job
  that runs the reconciliation/silent-loss/usage/structural/rounded gates
  (81 tests) with **only pytest installed** — no `requirements.lock`. It fails in
  about a minute instead of after the image build, and the dependency-free
  install also proves the registry/analyzer/producer surface has no hidden
  third-party coupling.
- **Deliberately still open:** coverage thresholds and mutation testing are not
  added; they are not yet justified by evidence and would add CI time without a
  defined target.
- **Verification level:** VERIFIED locally and by CI on baseline `55f885d`.
  Push CI #453 and PR CI #454 both passed, including the capability-truth gate.
  Coverage thresholds and mutation testing remain explicitly deferred below.

### BL-040 — `STRING` without `END-STRING` silently swallows the rest of the PROCEDURE DIVISION

- **Type:** defect (silent semantic loss — §54/§60 class).
- **Priority:** P0 — phase-blocking. Same shape as BL-027/BL-030: a valid
  program (`STRING … INTO T.` without the optional `END-STRING`) parses
  "successfully" while every statement after the `STRING` is dropped from
  the IR with no diagnostic — a green verdict over a wrong program is
  reachable.
- **Severity:** high — `END-STRING` is optional in COBOL; any such program
  loses all subsequent logic silently.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle A, this session)** —
  defect proven first (7 failed / 4 passed on the new focused file,
  `%TEMP%\opencode\phase4\bl040_pre_fix.txt`), then fixed, then 12/12
  green. Discovered 2026-10-14 by the repository-wide line-by-line audit
  (Stage C, baseline `4deddfc`).
- **Found by:** audit group T1 (`cobol_parser.py`); verified by hand:
  dispatch `L1068-1070` does no period pre-bounding; the continuation loop
  `L2251-2259` stops only at `END-STRING` or EOF; `_parse_string_text`
  `L2140-2199` treats the swallowed text as a tail and discards it (no
  diagnostic path exists).
- **Observed behavior (verified):** for `STRING A DELIMITED BY SIZE INTO B.`
  followed by further statements, `_parse_string` consumed every following
  line into `full_text`; the statements never reached the IR.
- **Expected behavior:** the statement ends at its terminating period (or
  `END-STRING`); a following statement must never be swallowed.
- **Root cause:** continuation join was bounded by `END-STRING` only; the
  period terminator honoured everywhere else was not (contrast the DISPLAY
  fix).
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_parse_string`; module-level `_STRING_CONTINUATION_STOP` derived from
  `_STATEMENT_LEADING_VERBS`).
- **Impact:** silent statement deletion in the canonical parser lane;
  downstream capability/verdict could not see it.
- **Remediation (implemented, deterministic, no LLM):** `_parse_string`
  now (1) returns immediately when the opening line already ends with `.`
  (mirrors `_parse_display`); (2) stops the continuation join after a line
  ending with the statement period; (3) stops *before* a scope terminator
  (`_SCOPE_TERMINATOR`) or a verb-led/file-clause-header line
  (`_STRING_CONTINUATION_STOP`, **word-boundary** matched so a data-name
  like `MOVE-DATE` still continues the statement — derived from the
  dispatcher's own verb vocabulary so the two cannot drift). Refined
  contract, recorded during remediation: a *complete* unterminated STRING
  (has INTO) stays lenient with **no** diagnostic — with the boundaries in
  place it loses nothing, and adding one would fail-closed on lossless
  input (the BL-034/BL-035 anti-pattern, and the shape the capability-truth
  gate's `test_missing_delimited_by_defaults_to_size` already pins); an
  *incomplete* STRING (no INTO) still fails closed through the existing
  `_emit_unparsed` channel.
- **Acceptance criteria / tests:**
  `tests/transformation/test_string_period_termination.py` (12 tests,
  wired into the `ci.yml` capability-truth gate): period-terminated
  single-line and multi-line (with ON OVERFLOW) STRING keep every following
  statement; lowercase `string` identical; verb-led line ends an
  unterminated STRING and the next statement is preserved; `MOVE-DATE`
  data-name continues (word-boundary proof); complete-unterminated stays
  lenient/lossless, incomplete-unterminated diagnosed via `_emit_unparsed`;
  END-STRING join (BL-027) byte-identical.
- **Evidence (defect proven first):** pre-fix **7 failed / 4 passed**
  (`%TEMP%\opencode\phase4\bl040_pre_fix.txt`); post-fix **12 passed**;
  BL-027/BL-029 regression batch (string_delimited + generator literals +
  multiline formats + decision records + scoped constructs + silent-loss
  adversarial) **131 passed**; `tests/transformation/` + e2e + control-flow
  batch **1965 passed / 4 skipped** (the two `TestArithRealE2E` flakes pass
  on rerun and fail identically with the fix stashed — Docker cold-start,
  not this change); capability-truth gate **440 passed** (428 + 12 new).
  No existing test weakened or skipped.
- **Owner/role:** parser / IR maintainer. **Target phase:** Phase 4
  (cycle A, fixed in-cycle). **Dependency:** none. **Residual risk:** a
  same-line two-statement spelling (`STRING ... INTO B. MOVE ...` on one
  physical line) is out of scope — the parser's line-oriented statement
  model does not split same-line statements for any verb.

### BL-041 — `file_io` generation mode silently drops statements that carry neither `.text` nor `.expression`

- **Type:** defect (silent semantic loss).
- **Priority:** P1 — silent logic loss (CALL/IF/PERFORM/RETURN statements
  vanish from the emitted program). May upgrade to P0 after a reproduction
  shows the mode reachable under a green verdict.
- **Severity:** medium-high.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle B)**; defect-proven-first:
  the new focused file
  `tests/transformation/test_file_io_main_body_rendering.py` ran **5 failed
  / 2 passed** against the unmodified generator
  (`%TEMP%\opencode\phase4\bl041_pre_fix.txt`) — local declaration, CALL
  statement, IF block and WHILE loop all silently vanished from the emitted
  main body, and the unmapped-statement case raised no diagnostic at all.
- **Found by:** audit group T3; verified: `java_generator.py L431-440`
  iterates main-method body statements and appends only when
  `hasattr(stmt, 'text')` or `hasattr(stmt, 'expression')`; every other
  statement type is skipped with no diagnostic; the local `stmt_str` at
  `L436` is computed and unused.
  *Correction recorded at fix time:* the audit's claim that `RETURN`
  statements were dropped is **inaccurate** — `JavaReturn` carries an
  `.expression` attribute so it was already rendered (regression test
  `test_file_io_main_body_renders_return_statement_regression` pins this).
  The silently dropped types are local declarations, method calls, IF
  blocks, loops, and blocks (anything without `.text`/`.expression`).
- **Observed behavior (verified):** in the file_io template path, calls,
  IF blocks, loops and local declarations are omitted from the generated
  main body.
- **Expected behavior:** either emit every statement type or fail closed
  with a diagnostic naming the unmapped construct (house invariant:
  never drop executable statements).
- **Root cause:** heuristic comment/expression split written for a narrow
  demo path was never fail-closed.
- **Affected files:** `engine/transformation/java_generator.py` L431-440.
- **Impact:** wrong generated program without diagnostics if the mode is
  reached. Reachability confirmed at fix time: `_derive_generation_mode`
  (`cobol_to_java_mapping.py` L3405-3418) selects `file_io` for
  `caps.input_record_mapping` programs, so the path is production-reachable.
- **Remediation (done):** every main-body statement is now rendered via
  `_stmt_to_string` into the main body in source order (comments keep
  their record-loop placement); a statement whose rendering is empty
  fails closed with `ValueError("MISSING_REQUIRED_SEMANTIC: … statement
  type <TypeName> has no generator mapping.")`; the dead `stmt_str`
  local is removed.
- **Acceptance criteria:** met — no silent statement drop (7 focused
  tests: red 5/2 pre-fix → green 7/7 post-fix, including a fail-closed
  test naming `JavaThrow`) + generator/file-lane regression batch
  **168 passed**. No existing test weakened or skipped.
- **Owner/role:** Java generator maintainer. **Target phase:** **Phase 4
  (cycle B — fixed 2026-10-14)**. **Dependency:** none remaining.
  **Residual risk:** multi-line renderings (IF/WHILE) are indented one
  level at insertion; an empty `JavaBlock` now fails closed rather than
  rendering as a no-op (fail-closed direction, per the house invariant).

### BL-042 — Producer diagnostics are dict-shaped, not `Diagnostic` objects (`TransformationResult.has_errors` crashes or mis-reports)

- **Type:** defect (contract mismatch / capability-truth risk).
- **Priority:** P1 — a diagnostics consumer that crashes is fail-closed,
  but a consumer that mis-reports could hide errors; the contract
  (`diagnostics: tuple[Diagnostic, …]`) is violated at the source.
- **Severity:** medium.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle C)**; defect-proven-first:
  the new focused file
  `tests/transformation/test_producer_diagnostics_contract.py` ran **5
  failed / 1 passed** against the unmodified producers
  (`%TEMP%\opencode\phase4\bl042_pre_fix.txt`) — internal-native
  returned plain `dict` diagnostics (proven `['dict']` in the failure)
  and the OpenSourceCOBOL4J adapter returned engine diagnostics whose
  enum level made `has_errors` silently mis-report `False` for a real
  ERROR diagnostic.
- **Found by:** audit group T3; verified: `producers/internal_native.py
  L148-156` and `L169-175` build plain `dict`s where the result type
  declares `Diagnostic`; T3 found three mutually incompatible shapes across
  `internal_native.py`, `contracts.py`, `opensource4j.py`.
- **Observed behavior (verified):** dict items reach consumers expecting
  `.level`/`.code` attributes; enum-level diagnostics make the string
  comparisons in `has_errors`/`has_warnings` return False.
- **Expected behavior:** every producer emits real `Diagnostic` instances;
  `has_errors` and any `.level` access work identically for all producers.
- **Root cause:** producers written against an ad-hoc dict convention
  predating the `Diagnostic` dataclass; the adapter reused the engine
  enum-level Diagnostic at a boundary whose contract is string-level.
- **Affected files:** `engine/transformation/producers/internal_native.py`,
  `engine/transformation/producers/opensource4j.py`,
  `engine/transformation/diagnostics.py` (new `to_contract_diagnostic`
  helper).
- **Impact:** contract violation at the producer boundary; downstream
  error visibility depended on which consumer ran (crash vs mis-report).
- **Remediation (done):** new `to_contract_diagnostic` in
  `diagnostics.py` converts engine diagnostics (enum level/code) to the
  boundary `contracts.Diagnostic` (string level/code) through one shared
  helper; internal-native converts `diagnostics.all` through it and
  constructs a real `Diagnostic(level="ERROR", code="TRANSFORMATION_ERROR",
  …)` on its exception path; the adapter wraps all five
  `Diagnostic.error(...)` sites. **Honesty note:** the pre-existing
  dict-shape assertions in `tests/transformation/test_producer_contract.py`
  (L106-107, 158, 169, 195, 207) were updated to attribute access — this
  is an alignment strengthening toward the declared
  `tuple[Diagnostic, ...]` contract (attribute access now works for every
  producer), not a weakening; no assertion's meaning was reduced.
  `engine/transformation/producer.py` (legacy `errors: tuple[str, …]`
  result with no diagnostics field, used only by the RUN_DOCKER_TESTS
  claims tests) is a separate contract and out of this item's scope.
- **Acceptance criteria:** met — all producers pass the diagnostics-shape
  contract test (6 focused tests: red 5/1 pre-fix → green 6/6 post-fix,
  including has_errors/has_warnings equivalence across producers);
  producer-contract + capability-consistency batch **42 passed**;
  full `tests/transformation` + `tests/integration` regression **2257
  passed / 4 skipped / 0 failed**. No existing test weakened.
- **Owner/role:** transformation producer maintainer. **Target phase:**
  **Phase 4 (cycle C — fixed 2026-10-14)**. **Dependency:** none.
  **Residual risk:** none for the two live producers; the legacy
  `producer.py` contract remains separate by design.

### BL-043 — Modernization planner defaults *missing* copybook/file capability components to `SUPPORTED` (fail-open)

- **Type:** defect (capability truth).
- **Priority:** P1 — contradicts the fail-closed default used for programs;
  a missing analyzer component silently becomes a green plan for
  copybooks and files.
- **Severity:** medium-high.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle B)**; defect-proven-first:
  the new focused file
  `tests/transformation/test_planner_missing_component_fail_closed.py`
  ran **5 failed / 2 passed** against the unmodified planner
  (`%TEMP%\opencode\phase4\bl043_pre_fix.txt`) — `cap=None` yielded
  `SUPPORTED` + `INTERNAL_NATIVE` + `DOCKER_ORACLE` for both copybook
  and file components, exactly as the audit claimed.
- **Found by:** audit group T2; verified: `modernization_planner.py
  L605-612` (`_build_copybook_plan`) and `L637-644` (`_build_file_plan`)
  set `CapabilityLevel.SUPPORTED` when `cap is None`.
- **Observed behavior (verified):** absent capability component ⇒
  `SUPPORTED` + `INTERNAL_NATIVE` + `DOCKER_ORACLE` strategies with the
  reason "Copybook resolution supported" / "…supported".
- **Expected behavior:** missing component must fail closed (UNKNOWN or
  UNSUPPORTED) like the program path.
- **Root cause:** optimistic default guarded only by the invariant "the
  analyzer always emits every component" — an unenforced assumption.
- **Affected files:** `engine/modernization/modernization_planner.py`
  L600-654.
- **Impact:** capability-truth drift if analyzer output ever misses a
  component (e.g. future partial analyzers, error paths).
- **Remediation (done):** both builders now mirror `_build_program_plan`:
  `cap is None` ⇒ `CapabilityLevel.UNKNOWN`, reason
  "No copybook/file capability analysis available", blocking
  `(BlockingReason.UNKNOWN_CONSTRUCT,)`, and the existing non-SUPPORTED
  branch maps to `SKIP`/`SKIP` strategies.
- **Acceptance criteria:** met — `cap=None` yields non-SUPPORTED with a
  blocking reason (7 focused tests: red 5/2 pre-fix → green 7/7
  post-fix, including pass-through regressions for present components);
  planner-dependent regression batch **189 passed**. No existing test
  weakened or skipped.
- **Owner/role:** modernization planner maintainer. **Target phase:**
  **Phase 4 (cycle B — fixed 2026-10-14)**. **Dependency:** none.
  **Residual risk:** none — the fail-closed default cannot green-light
  missing analysis.

### BL-044 — CALL resolution is stamped case-sensitively by discovery but matched case-insensitively by the analyzer (contradictory facts)

- **Type:** defect (consistency / provenance).
- **Priority:** P1 — one CALL fact can read `UNRESOLVED` (edge/record) and
  `ARITY_MISMATCH` (plan) simultaneously for mixed-case sources.
- **Severity:** medium.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle B)**; defect-proven-first:
  the new focused file
  `tests/transformation/test_call_name_case_normalization.py` ran **4
  failed / 3 passed** against the unmodified lanes
  (`%TEMP%\opencode\phase4\bl044_pre_fix.txt`) — a lowercase CALL
  literal against an uppercase PROGRAM-ID read `UNRESOLVED` in the
  record/edge while the arity lane resolved the same callee, and a
  case-variant self CALL was misclassified as an unresolved external
  target instead of recursive.
- **Found by:** audit group T2; verified: `application_discovery.py L600`
  uses `call.target in known_programs` (case-sensitive) while
  `capability_analyzer.py L252/L261` matches case-insensitively.
- **Observed behavior (verified):** COBOL is
  case-insensitive, but a lowercase/mixed-case CALL target against an
  uppercase program-id resolves differently in the two lanes.
- **Expected behavior:** one normalization rule (uppercase) in both lanes.
- **Root cause:** independent membership checks without a shared
  normalization helper.
- **Affected files:** `engine/transformation/application_discovery.py`
  L600; `engine/modernization/capability_analyzer.py` L252/L261
  (note: the audit entry cited `capability_analyzer.py` as
  `engine/transformation/…`; the file lives in `engine/modernization/`).
- **Impact:** contradictory plan reasons for valid programs; trust/
  provenance inconsistency (BL-038 class).
- **Remediation (done):** new shared `normalize_cobol_name` in
  `engine/transformation/ir.py` (the module both lanes import) applied
  to every program-id join: discovery's `known_programs` set and target
  check, the analyzer's LINKAGE-arity `by_id`/target, the analyzer's
  `program_levels` keys and callee lookup, and the case-variant
  self-CALL checks in both `_analyze_call` and the planner's
  `_build_call_relationship` fallback. Source spelling of `target` and
  edge `target` are preserved (only comparisons normalize).
- **Acceptance criteria:** met — resolution and arity agree for
  mixed-case sources (7 focused tests: red 4/3 pre-fix → green 7/7
  post-fix, including self-CALL stays recursive and same-case/missing/
  dynamic regressions); CALL/discovery/analyzer/planner regression
  batch **249 passed**. No existing test weakened or skipped.
- **Owner/role:** application discovery maintainer. **Target phase:**
  **Phase 4 (cycle B — fixed 2026-10-14)**. **Dependency:** none.
  **Residual risk:** none for program-id joins; other name spaces
  (copybook stems, file names) still compare as-spelled and would need
  their own normalization decisions if a contradiction is ever
  demonstrated there.

### BL-045 — Nested-statement recursion drops `called_programs` (CALLs inside IF/PERFORM bodies lose resolution metadata)

- **Type:** defect (provenance/coverage).
- **Priority:** P1 — nested CALLs (standard COBOL) lose value-result/
  entry-point resolution metadata in the mapping lane.
- **Severity:** medium.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; line-read verified (T3), hand-verified at
  `L2183-2195`.
- **Found by:** audit group T3 (`cobol_to_java_mapping.py` L2183-2195,
  L2584-2677): recursive `map_cobol_statement` calls for IF/PERFORM bodies
  return Java statements only; the caller-side `called_programs`
  collection is not updated for nested CALLs.
- **Observed behavior (verified at code level):** top-level CALL edges are
  collected; nested CALLs are mapped but never registered.
- **Expected behavior:** every reachable CALL (at any nesting depth)
  contributes its program reference.
- **Root cause:** recursion path predates the called_programs collector and
  was never updated (BL-038-adjacent).
- **Affected files:** `engine/transformation/cobol_to_java_mapping.py`
  L2183-2195, L2584-2677.
- **Impact:** incomplete program references in the generated metadata;
  downstream resolution cannot see nested callers.
- **Remediation (planned):** thread the collector through recursion (or
  collect from IR post-mapping); focused test with a CALL inside an IF.
- **Acceptance criteria:** nested CALL appears in called_programs;
  focused + regression tests green.
- **Owner/role:** mapping maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none once threaded.

### BL-046 — Spring Boot generator emits String literals without BL-030 escaping (invalid Java or semantic divergence from the native lane)

- **Type:** defect (semantic equivalence).
- **Priority:** P1 — the native lane escapes quotes/backslashes (BL-030);
  the Spring Boot lane does not, so the same COBOL literal can produce
  invalid Java (`"A"B"`) or divergent values.
- **Severity:** medium.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified by hand.
- **Found by:** audit group T3; verified: `spring_boot_generator.py
  L654-669` renders `f'"{expr.value}"'` with no escaping at either site.
- **Observed behavior (verified):** a literal containing `"` or `\` emits
  uncompilable or wrong Java.
- **Expected behavior:** identical escaping helper as the native lane
  (single source of truth).
- **Root cause:** duplicated literal renderer written before BL-030.
- **Affected files:** `engine/transformation/spring_boot_generator.py`
  L654-669.
- **Impact:** fail-closed at javac (no false green) but wrong-value risk
  where the emitted string still compiles (e.g. backslash forms).
- **Remediation (planned):** reuse the native escaping helper; oracle/
  compile test with quotes and backslashes in literals.
- **Acceptance criteria:** both lanes emit identical escaped literals;
  focused test green.
- **Owner/role:** Spring Boot generator maintainer. **Target phase:**
  unassigned. **Dependency:** native escaping helper reuse. **Residual
  risk:** none once shared.

### BL-047 — Duplicate upload filenames silently collapse in the API ingestion dict (one file never written; collision check bypassed)

- **Type:** defect + security (ingestion integrity; silent file loss).
- **Priority:** P1 — silent data loss on an accepted upload; the
  service-level collision detector can never fire because the dict has
  already merged the keys.
- **Severity:** medium.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified by hand.
- **Found by:** audit group T6; verified: `api/app.py L298-301` keys
  `contents: dict[str, bytes]` by filename, so duplicates overwrite;
  `files_received` undercounts what the client actually sent.
- **Observed behavior (verified):** two files with the same name ⇒ last
  wins; no 4xx; the collision check documented in
  `service.upload_cobol_source` never sees the duplicate.
- **Expected behavior:** duplicate names rejected (or disambiguated) with
  an explicit error — matching the documented contract.
- **Root cause:** dict keyed by unvalidated filename.
- **Affected files:** `api/app.py` L298-301 (with
  `api/service.py` `_write_upload` collision contract).
- **Impact:** accepted upload silently loses a file; downstream
  transformation runs on incomplete sources.
- **Remediation (planned):** detect duplicates while building the dict →
  4xx; adversarial test with duplicate names.
- **Acceptance criteria:** duplicate-name upload fails closed with a
  named error; security suite green.
- **Owner/role:** API maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none once rejected.

### BL-048 — Upload endpoints delete the previous source directory before the new upload is validated and written (data loss on a rejected upload)

- **Type:** defect (operations/data-loss).
- **Priority:** P1 — an update that fails validation (traversal, collision,
  disk error) leaves the record pointing at a deleted directory and the
  previous good source gone.
- **Severity:** medium.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified by hand.
- **Found by:** audit group T6; verified: `api/service.py L488-490`
  (`upload_cobol_source`) and `L503-506` (`upload_java_candidate`) call
  `_cleanup_temp_dir` before `_write_upload`.
- **Observed behavior (verified):** cleanup precedes write; a raise in
  `_write_upload` strands the record.
- **Expected behavior:** write new → persist → delete old (or delete only
  after successful persist).
- **Root cause:** cleanup ordered by "previous artifact" thinking, not by
  transactionality.
- **Affected files:** `api/service.py` L488-490, L503-506.
- **Impact:** previous source lost on any rejected re-upload.
- **Remediation (planned):** reorder to write-then-cleanup; test with a
  traversal-rejecting re-upload asserting the old source still exists.
- **Acceptance criteria:** failed re-upload preserves the previous
  directory; service tests green.
- **Owner/role:** API/service maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none once reordered.

### BL-078 — WHERE-predicate string literals are uppercased into the semantic model (`'abc'` → `'ABC'`)

- **Type:** defect (silent semantic corruption).
- **Priority:** P1 — the SQL semantic model misrepresents data values that
  DB2 compares case-sensitively; the corruption is silent and flows into
  `SqlPredicate.right.literal`, the analyzer's read model, and any future
  Java generation derived from it.
- **Severity:** high (wrong value recorded as truth).
- **Status:** **FIXED — 2026-10-15, Phase 6 batch P1 (defect-proven-
  first).** Red `3 failed, 1 passed`
  (`%TEMP%\opencode\phase6\bl078_pre_fix.txt`: both literal-case tests +
  the host-variable case test failed; the identifier-folding control
  passed) → operator/keyword positions located on a literal-masked
  uppercase copy, operands sliced from the original text, unquoted
  identifiers fold to uppercase inside `_parse_expression` (DB2
  identifier rules). Focused green `14 passed`
  (`bl079_focused_green.txt`, whole fidelity file); SQL-lane regression
  `223 passed` (`bl080_focused_green.txt`); gate-wired
  (`test_sql_predicate_fidelity.py`, bare-venv dependency-free gate
  `615 passed`). No existing test weakened.
- **Found by:** Phase 6 audit probe G
  (`%TEMP%\opencode\phase6\audit_probes.txt`).
- **Observed behavior (verified):** `SELECT … WHERE NAME = 'abc'` yields
  `predicate.right.literal == 'ABC'` — `_parse_predicate` splits the
  **uppercased** text (`text.upper().split(op)`) and feeds the uppercase
  halves to `_parse_expression`, so literal data values are case-destroyed.
- **Expected behavior:** operand text is sliced from the **original** SQL
  string at offsets found in the uppercase copy (identifier folding is
  fine; literal data must survive verbatim).
- **Root cause:** convenience uppercasing of the whole operand text instead
  of case-insensitive position search + original-text slicing.
- **Affected files:** `engine/transformation/sql_parser.py`
  (`_parse_predicate`).
- **Impact:** silent value corruption in the semantic model; wrong truth in
  dependency/usage records and any downstream consumer.
- **Remediation (planned):** search on the uppercased copy, split the
  original text at the same offsets; focused tests pin literal-case
  preservation (string literal + host variable + column control).
- **Acceptance criteria:** red test captured pre-fix; focused suite green;
  no existing test weakened.
- **Owner/role:** SQL parser maintainer. **Target phase:** Phase 6 (batch
  P1). **Dependency:** none (shares `_parse_predicate` with BL-079).
  **Residual risk:** none.

### BL-079 — compound/IN/BETWEEN WHERE predicates are mangled into invented fake column names that flow into table usage and dependency records

- **Type:** defect (silent semantic corruption / invented data).
- **Priority:** P1 — the parser invents column names that never existed in
  the SQL and they propagate into `read_columns`, `Db2TableUsage`, and
  `Db2TableDependency` (the database-dependency graph).
- **Severity:** high (fabricated identifiers in the dependency truth).
- **Status:** **FIXED — 2026-10-15, Phase 6 batch P1 (defect-proven-
  first).** Red `8 failed, 5 passed`
  (`%TEMP%\opencode\phase6\bl079_pre_fix.txt`; missing-IR-field
  AttributeErrors + fake-column assertions) → quote/paren-aware
  conjunct splitter (BETWEEN's AND protected), literal-masked operator
  search, `_is_simple_operand` never-fabricate rule, IN → `right_list`,
  BETWEEN → `left_operand`/`right_operand`, additive
  `where_predicates` on `SqlSelect`/`SqlUpdate`/`SqlDelete`
  (`where_predicate` = first conjunct, compatibility), analyzer
  collects every conjunct's columns; one boundary bug caught by the
  existing suite mid-fix (`p1_sql_regression_after_bl079.txt`:
  `1 failed, 213 passed` — underscore identifiers rejected by the new
  operand regex) → regex fixed, underscore pin added to the fidelity
  file. Focused green `14 passed` (`bl079_focused_green.txt`); SQL-lane
  regression `223 passed`; gate-wired (bare-venv `615 passed`). No
  existing test weakened.
- **Found by:** Phase 6 audit probes H/L/M
  (`%TEMP%\opencode\phase6\audit_probes.txt`).
- **Observed behavior (verified):**
  (H) `WHERE ACCT = 1 AND BAL = 2` → `right.column.column_name ==
  '1 AND BAL = 2'` (one fake column), and the analyzer records
  `read_columns == ['ACCT', '1 AND BAL = 2']`;
  (L) `WHERE ACCT IN (1, 2, 3)` → `right.column.column_name == '(1, 2, 3)'`,
  `right_list` stays empty;
  (M) `WHERE BAL BETWEEN 100 AND 500` → `right.column.column_name ==
  '100 AND 500'`, `left_operand`/`right_operand` never populated.
  `_PREDICATE_OP_MAP` declares IN/BETWEEN/LIKE support the parser never
  delivers.
- **Expected behavior:** every conjunct parsed on its own (top-level AND/OR
  split, quote- and paren-aware, BETWEEN's AND not split); IN lists go to
  `right_list`; BETWEEN goes to `left_operand`/`right_operand`; operand
  text that is not a clean column/literal/host-variable is never
  fabricated into a column name.
- **Root cause:** single-pass "first operator wins" split of the entire
  WHERE text; IR fields `right_list`/`left_operand`/`right_operand`
  defined but never populated.
- **Affected files:** `engine/transformation/sql_parser.py`
  (`_parse_predicate`, `_parse_expression`), `engine/sql/analyzer.py`
  (`_collect_select_read_columns`), additive `ir.SqlSelect` field for the
  conjunct list.
- **Impact:** fake columns in the database dependency graph; `BAL` (and any
  further conjunct columns) missing from read-column truth.
- **Remediation (planned):** conjunct splitting helper + IN/BETWEEN
  fidelity + analyzer collection of every conjunct's columns; additive
  `SqlSelect.where_predicates` (all conjuncts, canonical view) keeping
  `where_predicate` as the first conjunct for compatibility; unparsed
  conjuncts produce no fabricated column (diagnostic via BL-080 channel).
- **Acceptance criteria:** red tests captured pre-fix (one per probe shape
  H/L/M + column-collection parity); focused suite green; dependency
  records contain only genuine SQL identifiers.
- **Owner/role:** SQL parser maintainer. **Target phase:** Phase 6 (batch
  P1). **Dependency:** shares `_parse_predicate` with BL-078; feeds
  BL-081 (ON conditions). **Residual risk:** AND/OR grouping is recorded
  as a flat conjunct list (documented subset limitation — no boolean tree
  invented).

### BL-080 — unsupported EXEC SQL statements are silently dropped with zero diagnostics, and EXECUTE IMMEDIATE is misclassified as plain EXECUTE

- **Type:** defect (silent loss, contract inconsistency).
- **Priority:** P1 — contradicts the SQL lane's own no-silent-loss
  doctrine (`db2_sqlite.py`: "It never silently drops semantics") and
  §24's unsupported-semantics requirement; the modernization ledger can
  claim a complete SQL model while whole declarations vanish.
- **Severity:** medium-high.
- **Status:** **FIXED — 2026-10-15, Phase 6 batch P1 (defect-proven-
  first).** Red `5 failed, 3 passed`
  (`%TEMP%\opencode\phase6\bl080_pre_fix.txt`; disclosure: one of the
  five was the new test's own wrong expectation that preserved texts
  keep the `;` delimiter — the shared splitter strips top-level `;`
  uniformly for every statement, exactly like `raw_sql`; expectation
  corrected post-red with an inline comment, product behavior
  unchanged) → `EmbeddedSqlBlock.unsupported_statements` (additive)
  + else-branch capture + None-parse capture for every typed branch +
  `CALL` without a name + `execute_immediate` wiring + analyzer
  `validation` entries (`unsupported SQL text preserved: …`). Focused
  green `223 passed` (`bl080_focused_green.txt`, unsupported file +
  fidelity file + whole SQL lane); gate-wired
  (`test_sql_unsupported_statement_diagnostics.py`, bare-venv
  `615 passed`). Fully-supported blocks unchanged
  (`unsupported_statements == ()` pinned). No existing test weakened.
- **Found by:** Phase 6 audit probe F
  (`%TEMP%\opencode\phase6\audit_probes.txt`).
- **Observed behavior (verified):** a block containing
  `BEGIN DECLARE SECTION;`, `INCLUDE SQLCA;`,
  `WHENEVER NOT FOUND CONTINUE;`, `DECLARE STMT1 STATEMENT FOR …;`,
  `EXECUTE IMMEDIATE :SQL-TEXT;`, `SELECT …;` yields exactly 2 statements —
  the four unsupported lines vanish with no record (`EmbeddedSqlBlock`
  has no diagnostic channel), and `EXECUTE IMMEDIATE` parses as plain
  `EXECUTE` with `execute_immediate=False` (IR field exists, never set).
- **Expected behavior:** every unclassified statement text preserved in an
  `unsupported_statements` channel on `EmbeddedSqlBlock` (additive,
  default empty); the analyzer surfaces them as validation diagnostics;
  `EXECUTE IMMEDIATE` sets the IR flag so its semantics stay distinct.
- **Root cause:** parser dispatch loop has no else-branch; IR flag never
  wired.
- **Affected files:** `engine/transformation/sql_parser.py`,
  `engine/transformation/ir.py` (additive `EmbeddedSqlBlock` field),
  `engine/sql/analyzer.py` (validation surfacing).
- **Impact:** ledger truth claims can overstate SQL coverage; WHENEVER /
  SQLCA declarations invisible to modernization planning.
- **Remediation (planned):** additive `unsupported_statements` tuple +
  else-branch capture + analyzer validation entries + `execute_immediate`
  wiring; focused tests pin preservation and diagnostics.
- **Acceptance criteria:** red test captured pre-fix; focused suite green;
  existing blocks (fully-supported SQL) unchanged.
- **Owner/role:** SQL parser + analyzer maintainer. **Target phase:**
  Phase 6 (batch P1). **Dependency:** none. **Residual risk:** none.

## P2 — coverage, quality, documentation

### BL-018 — Figurative constants parsed as field references (silent, non-compiling Java)
- **Type:** defect (silent semantic loss + false SUPPORTED verdict)
- **Status:** FIXED — 2026-10-10 (Phase 1 parser/IR work)
- **Observed behavior:** A COBOL figurative constant (`ZERO`, `ZEROS`,
  `ZEROES`, `SPACE`, `SPACES`, `QUOTE`, `QUOTES`, `LOW-VALUE(S)`,
  `HIGH-VALUE(S)`, `ALL "x"`) — a reserved **word** with a fixed value — was
  lowered by `CobolParser._build_expression` to `FieldReference(name="ZERO")`.
  The mapper then emitted `A = ZERO;` and
  `C = String.format("%-60s", SPACES).substring(0, 60);` — Java referencing an
  **undeclared variable**, which does not compile. Zero diagnostics were
  produced, and `CapabilityAnalyzer` still certified the program
  `SUPPORTED` with reason "All constructs supported". The real fixture
  `fixtures/workload-payroll/cobol/PAYROLL.cob` (`MOVE SPACES TO RPT-RECORD`)
  generates exactly this non-compiling Java today.
- **Expected behavior:** Master README Sections 14 (capability must derive from
  actual implementation), 16 ("figurative constants" is required parser
  coverage), 17 (the IR must represent semantics, not merely syntax), and 60
  (no silent loss). A recognised construct must never disappear, and must
  never be certified as supported while producing non-compiling output.
- **Root cause:** the reserved-word table had no entry for figurative
  constants, so the expression builder fell through to its "field reference"
  default. The mapper, capability registry and analyzer shared that blind spot.
- **Affected files:** `engine/transformation/figurative.py` (new),
  `engine/transformation/ir.py`, `engine/transformation/cobol_parser.py`,
  `engine/transformation/cobol_to_java_mapping.py`,
  `engine/transformation/semantic_capability.py`,
  `engine/modernization/capability_analyzer.py`,
  `tests/transformation/test_figurative_constants.py` (new).
- **Remediation (implemented):**
  * New `engine/transformation/figurative.py` is the single source of truth:
    canonical spelling → semantic kind, plus the fill character per kind.
    Deterministic tables and regular expressions only — no LLM.
  * New `ir.FigurativeConstant(kind, text)` node; `text` preserves the original
    spelling for source traceability. `_build_expression` produces it instead
    of a bogus `FieldReference`.
  * `map_cobol_expr_to_java` and `_map_cobol_expression_to_java` expand a
    constant to a Java literal, so `MOVE` fills the receiving item across its
    declared PIC width and `DISPLAY` prints the constant's value.
  * `map_cobol_condition_to_java` substitutes constants **before** the
    DASH_UNDERSCORE rewrite (which previously mangled `HIGH-VALUE` into
    `HIGH_VALUE`) and emits a **whole-field** test
    (`C.replace(" ", "").isEmpty()`) because `IF C = SPACES` is true only when
    every character is a space.
  * A sentinel marker makes substitution unambiguous (a real one-character
    literal `IF C = " "` is never confused with `= SPACES`) and a
    strip-on-fallback guard guarantees the marker can never leak into emitted
    Java on an unsupported condition shape.
  * Registry key `FIGURATIVE CONSTANT` at SUPPORTED with mapping evidence, a
    source pattern, and an analyzer IR walk that records the constant from the
    parsed IR (not from a source match alone), so a dropped instance still
    fails closed via `effective_source_level`.
- **Acceptance criteria / tests:**
  `tests/transformation/test_figurative_constants.py` (59 tests) — positive
  (every spelling canonicalises; parser emits `FigurativeConstant`; generated
  Java has no bare reserved-word identifier; fill spans the declared PIC width;
  comparison tests every character; verdict is IR-backed), negative
  (hyphenated identifiers such as `ZERO-COUNT`/`HIGH-VALUE-FLAG`, quoted
  literals spelling a word, and multi-character `ALL "ab"` are not constants;
  ordinary field operands stay `FieldReference`/`Literal`), and regression
  against the real `PAYROLL.cob` fixture that previously generated
  non-compiling Java.
  *(Correction 2026-10-12 — **BL-030**: the "multi-character `ALL "ab"` is not
  a constant" negative was **wrong**. GnuCOBOL replicates the pattern across
  the receiver (`ALL "AB"` → `ABABABABAB` for `PIC X(10)`), so refusing to
  parse it left the raw COBOL text leaking into generated Java. The test now
  asserts the oracle-verified repetition; the rest of the BL-018 contract is
  unchanged.)*
- **Known limitation (recorded, not hidden):** `LOW-VALUE`/`HIGH-VALUE` use the
  native ASCII collating sequence (NUL / 0xFF), which matches GnuCOBOL's
  default. A dialect with a different collating sequence needs an explicit
  mapping; this is recorded rather than guessed.
- **Verification level:** VERIFIED locally — focused suite 59 passed;
  `tests/transformation` + `tests/adversarial` + `tests/test_silent_loss_registry.py`
  unchanged at 1843 passed / 22 failed, with the 22 confirmed as the
  pre-existing environment-only `javac` `FileNotFoundError` failures by
  re-running the identical selection against a stashed (pristine) tree and
  observing the same 22. Full-suite and exact-SHA CI evidence pending on the
  commit that carries this fix (BL-010 applies: Docker/JDK validation is
  delegated to Linux CI).

### BL-020 — Inline statements on `WHEN` / `IF ... THEN` lines are swallowed into the condition
- **Type:** defect (silent semantic loss; mis-certified capability)
- **Status:** FIXED - 2026-10-11 (`7bba5cb`) - inline statements now parsed into the arm body
- **Remediation (implemented, `7bba5cb`):** `split_condition_from_inline_statements`
  separates the condition from a trailing inline statement using the same verb
  vocabulary `_parse_statement` dispatches on, masking quoted literals first. Inline
  text that still cannot be parsed is reported through a diagnostic, never discarded.
- **Verification:** `tests/transformation/test_scoped_construct_statements.py` (37 tests) - inline
  `WHEN`/`IF` bodies are preserved and appear in generated Java; multi-line behaviour is
  asserted unchanged; shipped fixture `workload-evaluate` arms are proven non-empty.
- **Premise correction (2026-10-11):** this item was originally filed as
  "the parser discards each `WHEN` arm's body statements". **That was wrong.**
  Re-reading `_parse_evaluate` (lines 1653-1666) shows `build()` *does* pass
  `then_body=body`, and probing confirms a **multi-line** arm works correctly:
  `WHEN 1 THRU 5` + `DISPLAY "IN-RANGE"` on the next line yields
  `IfStatement(condition='A >= 1 AND A <= 5', then_body=(DisplayStatement,))`
  and emits `if (A >= 1 && A <= 5) { println("IN-RANGE"); }`. All shipped
  fixtures (`workload-evaluate`, `workload_inventory`, `workload-level88`) use
  the multi-line form and are unaffected.
  The **real** defect is narrower and different: a statement written **inline
  on the same line as `WHEN`/`IF ... THEN`** is absorbed into the condition
  string and lost.
- **Observed behavior (verified):**
  | Source | Generated Java |
  |---|---|
  | `WHEN 1 THRU 5 DISPLAY "IN-RANGE"` | `if (A >= 1 && A <= 5) { }` — DISPLAY deleted |
  | `WHEN 1 DISPLAY "ONE"` | `if (A == 1 \|\| A == DISPLAY \|\| A == "ONE") { }` |
  | `IF A > 1 THEN DISPLAY "YES" END-IF` | `if (A > 1 THEN DISPLAY "YES" END_IF.) { }` — non-compiling |
  | `IF A > 1 DISPLAY "YES"` | `if (A > 1 DISPLAY "YES".) { }` — non-compiling |
  **No diagnostic is emitted in any case**, and `EVALUATE`/`IF` are certified
  SUPPORTED, so this is a false SUPPORTED *and* malformed Java.
- **Expected behavior:** Master README §60 (no silent loss), §16 (recognised
  constructs must produce explicit diagnostics), §17 (the IR models
  semantics), §53 (no silent semantic loss may remain at phase closure).
- **Root cause:** `_parse_evaluate` and `_parse_if` take everything after
  `WHEN ` / `IF ` on that line as the *spec/condition*, with no delimiter
  between the condition and an inline statement. The condition tokeniser then
  treats `DISPLAY`, `END-IF`, `THEN` etc. as comparison operands.
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_parse_evaluate`, `_parse_if`).
- **Impact:** silent deletion of executable statements plus non-compiling Java,
  reported as SUPPORTED. Highest-severity open item.
- **Remediation (NOT yet implemented):** split the line at the condition/statement
  boundary (stop the condition at `THEN`, `DISPLAY`, `MOVE`, `ADD`, ..., or
  `END-IF`), parse the remainder as real statements into the arm body, and
  emit an explicit diagnostic for any trailing text that still cannot be
  classified — never silently discard it.
- **Verification level:** VERIFIED by direct probing at `c312eb9` (multi-line
  correct; inline lossy), plus the code read at `_parse_evaluate` lines
  1621-1666.

### BL-021 — `EVALUATE ... WHEN ... ALSO` mis-lowered into nonsense
- **Type:** defect (silent semantic loss)
- **Status:** FIXED - 2026-10-11 (`7bba5cb`) - ALSO split into OR-ed alternatives
- **Remediation (implemented, `7bba5cb`):** the `WHEN` spec is split on `ALSO` and the real
  alternatives are OR-ed; a `THRU` range inside an ALSO group contributes both bounds. A
  malformed range is diagnosed rather than dropped.
- **Verification:** `TestWhenAlso` (5 tests) - 2- and 3-way `ALSO`, `ALSO` never a value,
  correct generated Java, range + ALSO combined.
- **Observed behavior:** `WHEN 1 ALSO 2 DISPLAY "X"` lowers to the condition
  string `A = 1 OR A = ALSO OR A = 2 OR A = DISPLAY OR A = "X"` — `ALSO`,
  `DISPLAY` and the arm body are all parsed as comparison operands. No
  diagnostic; verdict SUPPORTED.
- **Expected behavior:** §60; `ALSO` is standard COBOL multi-value `WHEN`.
  Roadmap P1-11 lists `EVALUATE` complex (ALSO/THROUGH) as an explicit item.
- **Affected files:** `engine/transformation/cobol_parser.py` (`_parse_evaluate`,
  `cond()`).
- **Remediation (NOT yet implemented):** split the `WHEN` spec on `ALSO` and
  lower each value into one comparison per alternative (OR-joined).
- **Verification level:** STATIC + reproduced locally.

### BL-022 — `EVALUATE ... WHEN OTHER` not lowered as a fallback branch
- **Type:** defect (silent semantic loss)
- **Status:** FIXED - 2026-10-11 (`7bba5cb`) - was a side effect of BL-020; now locked by tests
- **Premise correction:** the recorded symptom was a **side effect of BL-020**. The earlier
  probe used an inline `WHEN OTHER DISPLAY "X"`, whose trailing statement made the spec
  read `OTHER DISPLAY "OTHER"`. With BL-020 fixed, multi-line `WHEN OTHER` already lowered
  correctly; no separate code change was needed.
- **Verification:** `TestWhenOther` (4 tests) - else branch populated, standalone OTHER,
  inline OTHER generates an else branch, `OTHER` never compared as a value.
- **Observed behavior:** `WHEN OTHER DISPLAY "X"` is folded into the WHEN chain
  as an ordinary value (`A = DISPLAY OR A = "X"`) rather than becoming the
  `else` branch. No diagnostic; verdict SUPPORTED.
- **Affected files:** `engine/transformation/cobol_parser.py`.
- **Remediation (NOT yet implemented):** map the `OTHER` arm to
  `IfStatement.else_body`.
- **Verification level:** STATIC + reproduced locally.

### BL-023 — `COMPUTE A = 2 ** 3` exponentiation mis-parsed
- **Type:** defect (silent semantic loss; numeric semantics)
- **Status:** FIXED - 2026-10-11 (`7bba5cb`) - fails closed with an explicit diagnostic
- **Remediation (implemented, `7bba5cb`):** `**` is detected and represented as
  `ir.IntrinsicCall(name='**')` with an explicit `UNSUPPORTED_CONSTRUCT` diagnostic. It is
  no longer decomposed into two `*` operators with an empty-named operand.
- **Verification:** `TestUnmappedFormsFailClosed`; through real `ApplicationDiscovery` the
  program classifies **UNSUPPORTED**, never SUPPORTED.
- **Observed behavior:** `**` is parsed as two separate `*` operators, yielding
  `BinaryExpression(BinaryExpression(Literal(2), '*', FieldReference(name='')),
  '*', Literal(3))` — an operand that is an **empty-named field reference**.
  No diagnostic; verdict SUPPORTED.
- **Expected behavior:** §60; §18 (numeric correctness is a P0 risk area).
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_build_expression` operator table).
- **Remediation (NOT yet implemented):** recognise `**` as one operator, or
  fail closed with a diagnostic until it is mapped.
- **Verification level:** STATIC + reproduced locally.

### BL-024 — `COMPUTE` intrinsic functions (`FUNCTION MIN(...)`) become a field reference
- **Type:** defect (silent semantic loss)
- **Status:** FIXED - 2026-10-11 (`7bba5cb`) - new ir.IntrinsicCall, fails closed
- **Remediation (implemented, `7bba5cb`):** `FUNCTION NAME(...)` is recognised and represented
  as `ir.IntrinsicCall(name=..., arguments=<source text>)` with an explicit diagnostic. A
  field named `FUNCTION-CODE` (no parentheses) still parses as an ordinary field reference.
- **Verification:** same class as BL-023; UNSUPPORTED through real discovery.
- **Observed behavior:** `COMPUTE A = FUNCTION MIN(1, 2)` parses to
  `FieldReference(name='FUNCTION MIN(1, 2)')` — an identifier that cannot exist,
  mapping to an undeclared Java variable. No diagnostic; verdict SUPPORTED.
  This is structurally the *same* defect class as BL-018 (a non-field operand
  mis-modelled as a field), which is why it is filed explicitly rather than
  assumed covered.
- **Affected files:** `engine/transformation/cobol_parser.py` (`_build_expression`).
- **Remediation (NOT yet implemented):** `[SUPERSEDED — implemented in `7bba5cb`;
  Status above is authoritative. Retained as the record of the original
  acceptance criteria.]` recognise the `FUNCTION` prefix and
  either map the certified intrinsic subset or emit an explicit diagnostic;
  never fall through to a bare field reference.
- **Verification level:** STATIC + reproduced locally.

### BL-025 — generator leaks a Python dataclass repr into Java for unmapped expressions
- **Type:** defect (malformed generated output / fail-open fallthrough)
- **Priority:** P2 — important quality-gate / correctness-hardening gap.
  Rationale: the *capability verdict was already honest* (BL-023/BL-024 raise
  `UNSUPPORTED_CONSTRUCT` and classify `UNSUPPORTED`), so no silent semantic loss
  and no wrong runtime value was possible; impact was bounded to malformed
  output. It is **not** P0 because P0 requires incorrect business semantics, a
  false VERIFIED/certification, or data-loss risk, none of which applied.
  It is **not** P3 because a fail-open code-generation fallthrough undermines the
  required fail-closed behavior (§70) and would recur for every future
  expression node.
- **Severity:** medium — bounded by an already-correct verdict, but systemic in
  the mapper layer.
- **Status:** FIXED - 2026-10-11 (`6124e85` + collision hardening) - explicit
  fail-closed symbol replaces the `str(expr)` fallthrough
- **Last verified commit:** `bdb4c9a`
- **Found by:** the Phase 1 completion audit's fresh semantic-loss re-probe at
  `46c1cb7`, **not by CI and not by any test** — the same discovery mode as every
  other Phase 1 defect.
- **Observed behavior:** `_map_cobol_expression_to_java` ended with
  `return map_cobol_expr_to_java(str(expr))`. For an `ir.IntrinsicCall` (the
  BL-023/BL-024 node) that stringified the **dataclass repr** straight into the
  source:
  ```
  WS_A = Math.abs(IntrinsicCall(name='**', arguments='2 ** 3'));
  ```
  The `Math.abs(...)` wrapper comes from the unsigned-`PIC` compute path, so the
  repr was embedded inside an otherwise ordinary numeric statement.
- **Why this is a real defect despite the honest verdict:** BL-023/BL-024 already
  raise `UNSUPPORTED_CONSTRUCT` and classify the program `UNSUPPORTED`, so the
  *verdict* was not a lie and no silent semantic loss occurred. But the output was
  still malformed, and it failed closed **by accident** (`javac` cannot parse a
  repr) rather than by design. Worse, the fallthrough is **fail-open**: any
  future `Expression` node without a dedicated mapper branch would be silently
  stringified the same way, which is exactly the BL-018 / BL-023 defect class the
  phase exists to eliminate.
- **Root cause:** the mapper handled six `Expression` subclasses explicitly and
  relied on `str()` for everything else. `ir.IntrinsicCall` was the only
  unhandled subclass, so it was the only thing the fallthrough could reach —
  which is why the bug was invisible until an unmapped intrinsic was actually
  generated rather than only classified.
- **Expected behavior:** Master README Sections 16/17/60 — generated output must
  never contain implementation artefacts, and an unmapped construct must fail
  closed deliberately.
- **Affected files:** `engine/transformation/cobol_to_java_mapping.py`
  (`_map_cobol_expression_to_java`, new `_intrinsic_fail_closed_symbol`).
- **Remediation (implemented):** `IntrinsicCall` now maps to a deliberately
  undefined symbol — `UNSUPPORTED_INTRINSIC$POWER` for `**`,
  `UNSUPPORTED_INTRINSIC$MIN` for `FUNCTION MIN(...)`. This keeps a valid Java
  expression shape (so the statement structure stays well-formed) while making
  `javac` report the construct **by name**, and no wrong value can ever be
  produced. The fallthrough no longer stringifies: any other unhandled
  `Expression` yields `UNSUPPORTED_EXPRESSION$<NODE>` by the same rule.
- **Second-order defect found by adversarial re-verification (fixed in the same
  change):** the first version of the marker used a plain `_` separator. A
  COBOL user-defined word maps to Java by replacing hyphens with underscores, so
  a data item named `UNSUPPORTED-INTRINSIC-POWER` would have **declared** the
  marker and made it **resolve** — silently converting fail-closed back into
  fail-open and executing `WS_A = Math.abs(<field>)`, a wrong value with no
  diagnostic. Verified as a real reproduction, not a hypothetical. The separator
  is now `$`, which is a legal Java identifier character but can **never** occur
  in a COBOL data name, making the collision structurally impossible. This
  follows the existing `_FIGURATIVE_SENTINEL` precedent (a marker COBOL source
  cannot produce). Locked by a regression test that declares the colliding field
  and asserts the marker is still never declared.
- **Adjacent boundary checked:** `copybook_model._render_expression` has the same
  `str(expr)` fallthrough shape, but it is reachable only from data-description
  rendering and every expression it receives is a `JavaVariableRef`/`JavaLiteral`
  it built itself — a COBOL `IntrinsicCall` cannot reach it. Recorded as a latent
  observation, not a defect; deliberately left unchanged to keep scope minimal.
- **Verification:** `tests/transformation/test_scoped_construct_statements.py`
  asserts (a) no Python repr in generated Java, (b) the named fail-closed symbol
  is present, (c) the symbol is **never declared** (so it genuinely cannot
  resolve), (d) a supported `COMPUTE` is unaffected, and (e) an arbitrary
  unmapped `Expression` subclass fails closed instead of stringifying.
- **Impact:** bounded — the verdict was already honest, so this could not produce
  a wrong runtime value. It is filed rather than folded into BL-023/BL-024
  because it is a distinct layer (generator, not parser) and because the
  fail-open fallthrough would otherwise remain latent.
- **Verification level:** STATIC + reproduced locally.

### BL-026 — `GO TO` is lowered to a comment with no diagnostic (verdict is honest)
- **Type:** defect (diagnostic completeness / no-diagnostic unmapped statement)
- **Priority:** P2 — important hardening gap, not a trust defect.
  Rationale: the capability verdict is already honest — the registry key
  `GO TO` is UNSUPPORTED with a source pattern, real `ApplicationDiscovery`
  classifies a `GO TO` program **UNSUPPORTED**, and the planner then blocks it
  (`BlockingReason.UNSUPPORTED_CONSTRUCT`), so no false certification and no
  wrong runtime value is reachable through the platform. It is **not** P0/P1
  because no business semantics, verdict or trust boundary is violated. It is
  **not** P3 because §16 requires recognized-but-untransformable constructs to
  produce explicit diagnostics, and `SORT`/`INSPECT` in the same position do
  — `GO TO` alone is silently commented out.
- **Severity:** low-medium — bounded by an already-correct UNSUPPORTED verdict
  and the planner's blocking path.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 5, combined P2 cycle with
  BL-036/BL-037/BL-038/BL-039)** (see change-log entry (o)). Fix: `_parse_goto`
  emits an explicit `UNSUPPORTED_CONSTRUCT` warning naming `GO TO` (and its
  target) through the same diagnostic channel `SORT`/`INSPECT` use; the
  mapper comment stays for traceability and the verdict/planner behavior is
  unchanged (already `UNSUPPORTED`/`BLOCKED` via the registry). Verified by
  focused tests `tests/test_goto_diagnostic.py` (diagnostic named at parse
  and discovery level, verdict/planner unchanged, generated `// GO TO`
  comment kept, commented-out `GO TO` produces no diagnostic) and fresh E2E
  goto: plan `BLOCKED` with `GO TO` named, oracle truth captured.
- **Last verified commit:** `43bb9a0`.
- **Found by:** the BL-018…BL-025 re-probe, run in the Linux JDK audit
  container (`systemaops-audit`, javac 21) so that generated Java could be
  compiled rather than only inspected. 20/21 Part-1 cases were correct; the
  single failure was `GO TO` producing no diagnostic.
- **Observed behavior (verified, not assumed):** a program whose only
  executable statement is `GO TO MAIN-PARA` yields **zero diagnostics**; the
  mapper emits `JavaComment(text="// GO TO MAIN-PARA")`
  (`engine/transformation/cobol_to_java_mapping.py` ~L1777) and the generator
  emits `// GO TO MAIN-PARA (not implemented)`
  (`engine/transformation/java_generator.py` ~L1833). The executable jump is
  dropped from the generated program with no diagnostic, while `SORT` and
  `INSPECT` in the same position both raise `UNSUPPORTED_CONSTRUCT`.
- **Expected behavior:** Master README §16 ("Recognized-but-unparsed
  constructs must never disappear silently. They must produce explicit
  diagnostics") and §60 — an executable statement that cannot be transformed
  must be named in a diagnostic, not only marked by a comment in the emitted
  file.
- **Affected files:** `engine/transformation/cobol_to_java_mapping.py`
  (`map_cobol_statement` GO TO branch), `engine/transformation/java_generator.py`
  (GO TO rendering).
- **Impact:** bounded. Verified through the production path: a `GO TO`-only
  program classifies **UNSUPPORTED**, so §14/§15 fail-closed behavior holds.
  The gap is diagnostic completeness and consistency with the `SORT`/`INSPECT`
  precedent, not a false verdict. Consumers that read only diagnostics (rather
  than the capability report) would not learn that control flow was dropped.
- **Remediation (NOT yet implemented — deliberately deferred, see reason):**
  raise `UNSUPPORTED_CONSTRUCT` for a `GoToStatement` through the same
  diagnostic channel `SORT`/`INSPECT` use, keep the comment for traceability,
  and leave the verdict unchanged (already UNSUPPORTED). No mapper output and
  no registry level change.
- **Acceptance criteria:** (1) a program containing `GO TO` produces an
  explicit diagnostic naming `GO TO`; (2) its capability verdict remains
  UNSUPPORTED and the planner still blocks it; (3) the generated comment
  remains; (4) focused positive/negative tests are added to the fast
  `capability-truth` gate; (5) no existing test is weakened or skipped.
- **Verification level:** VERIFIED by direct probing (parser diagnostics,
  generated Java, and real-discovery verdict all observed at `bdb4c9a`).
- **Owner/role:** semantic transformation maintainer. **Target phase:**
  Phase 2 (parser/IR diagnostic completeness). **Dependency:** the existing
  `UNSUPPORTED_CONSTRUCT` diagnostic channel. **Residual risk:** until fixed,
  `GO TO`-bearing programs are blocked by capability classification but carry
  no parser/mapper-level diagnostic.
- **Why not fixed in this closure:** any change to
  `engine/transformation/cobol_to_java_mapping.py` requires a re-run of the
  serialized full suite to prove no regression; the Phase 1 verdict does not
  depend on this item (classification and blocking are already correct), so it
  is carried forward with explicit acceptance criteria instead of being folded
  into a green phase at the last moment.
- **Phase 3 disposition (2026-10-12, explicit — not silently closed):**
  **carried forward OPEN into Phase 3.** Phase 2 was declared
  `COMPLETE — VERIFIED` at `de8a808` with this item recorded as explicitly
  non-blocking (the verdict is honestly UNSUPPORTED and the planner blocks, so
  no false certification is reachable) and simultaneously named as the "next
  Phase 2 item" — that is the checkpoint inconsistency §1 required be resolved
  or documented. Resolution: Master README §53.10 permits closure *by
  explicit carry-forward* with ID, owner, reason, dependency, risk and
  acceptance criteria, all of which this entry and the carry-forward register
  already carry; the Phase 3 audit therefore adopts BL-026 as an open P2
  diagnostic-completeness item (target phase updated in the register) rather
  than reopening Phase 2 or waiving it. It remains eligible for the next
  implementation cycle in priority order behind the P0/P1 Phase 3 items.

### BL-027 — `STRING` delimiter and `WITH POINTER` are not modelled: wrong output with a `SUPPORTED` verdict
- **Type:** defect (silent semantic loss / wrong generated value)
- **Priority:** P0 — phase-blocking capability-truth defect. Rationale: Master README §54 lists
  `capability truth drift` as a P0 risk, and this is exactly that shape — the registry (§14's
  source of capability truth) claims `STRING` `SUPPORTED` while the generated program computes a
  wrong value for the `DELIMITED BY <literal>` and `WITH POINTER` forms, with no diagnostic. It
  also makes Master README §60 ("if a construct is recognized, partially parsed ... the system
  must expose that fact ... never silently discard source semantics") fail for a construct that is
  *partially parsed* at the Phase 1 parser/IR boundary, and it is the single counterexample to
  §53.9 ("no silent semantic loss remains") — which is why the Phase 1 verdict in `opencode.md`
  is `NOT COMPLETE` on this item alone (BL-026, whose verdict is honestly UNSUPPORTED and whose
  planner blocks, does not block §53.9).
- **Severity:** high — data-corrupting output is reachable through the supported path, and it
  defeats the fail-closed guarantee §14/§15 promise for the SUPPORTED subset.
- **Status:** **FIXED — VERIFIED (2026-10-12, via §53 re-audit)**. Opened by the Phase 1 closure
  audit at `bdb4c9a`; the fix was committed as **`13bdddd`** on top of `742e39d` and pushed (parser `StringStatement` delimiter/pointer/overflow fields, mapper fail-closed reasons +
  delimiter/pointer emission, analyzer walk, both generators, registry evidence text, a new
  30-case focused test file, and the focused-gate entry in `ci.yml`). Verified: the
  focused tests pass; the emitted Java compiles and executes in an isolated container and its
  output **matches the independent GnuCOBOL 3.1.2 oracle byte-for-byte** (`ORACLE_MATCH=YES`,
  computed by `%TEMP%\opencode\bl027_diff.py` from the two container captures — not asserted);
  identifier-delimiter and `ON OVERFLOW` forms fail closed. The serialized full suite
  **sits exactly at the 26-identity environmental baseline** (rerun: 26 failed / 3282 passed /
  12 skipped, zero new failures by identity vs the `bdb4c9a` clean run; the +30 passed are the
  new BL-027 tests, all passing). Exact-SHA CI is **green**: all four workflows SUCCESS at
  `6bfcbe4` (the push containing the fix `13bdddd`), all jobs green, `head_sha` verified via
  the GitHub API (run IDs in "Fix verification" below). Closing action completed
  **2026-10-12**: the §53 re-audit re-ran the original defect-finding tooling
  (`string_probe.py`, `nosilentloss_sweep.py`) in the same Linux audit container against an
  exact `bdb4c9a` worktree and the fixed tree — every STRING form the defect probes showed
  wrong at baseline is now correct, every other construct is byte-identical to baseline, and
  criterion 9 was re-scored (see the `⚑ §53 RE-AUDIT` block in `opencode.md`). The re-audit
  also found one sibling phrase still silently dropped (`STRING ... VARYING IN` — filed as
  **BL-029**, P0) and it was fixed fail-closed in the same cycle (`7dceec1`), so no silent
  STRING loss remains.
  *(Correction: an earlier draft of this entry claimed `FIXED — 2026-10-11` with a
  "Fix verification" block citing a fix commit SHA, CI run, `ORACLE_MATCH`, and container diffs.
  At that time none of those artifacts had been produced; the claim was fabricated and has been
  removed. The `ORACLE_MATCH`/container results recorded now were genuinely executed on
  2026-10-11 — see "Fix verification (executed 2026-10-11)" below.)*
- **Last verified commit:** **`7dceec1`** (BL-029 fail-closed fix on top of this BL-027 fix)
  — full suite at the 26-identity baseline with the BL-029 tests added; exact-SHA CI evidence
  recorded in the `⚑ §53 RE-AUDIT` block of `opencode.md`. This BL-027 fix's own verified
  push remains **`6bfcbe4`** (all 4 workflows green via the GitHub API: Push SystemaOps CI
  [#38159864669](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159864669),
  PR SystemaOps CI
  [#38159868523](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159868523),
  Supply chain [#38159864653](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159864653)
  / [#38159868476](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159868476)).
  The *defect* was last verified at `bdb4c9a` (probe evidence below).
- **Found by:** `string_probe.py`, run in the Linux JDK audit container, exercising the production
  mapper path with `STRING ... DELIMITED BY "," ...` and `STRING ... WITH POINTER WS_P`.
- **Observed behavior (verified, not assumed):**
  1. `STRING WS_A DELIMITED BY "," WS_B DELIMITED BY SIZE INTO WS_D` emits
     `WS_D = WS_A + "," + WS_B` — COBOL does **not** include the delimiter in the result; the
     delimiter only terminates each source segment.
  2. `STRING WS_A DELIMITED BY SIZE INTO WS_D WITH POINTER WS_P` emits `WS_D = WS_A` — `WS_P` is
     never read nor written, so the receiving field's running pointer is silently dropped.
  3. Both cases return verdict **SUPPORTED** with **zero diagnostics** — fail-open, not
     fail-closed.
  4. `DELIMITED BY SPACE` returns verdict `UNKNOWN` (conservative) even though the same
     literal-insertion emission path applies.
  Root cause: `_parse_string` (`engine/transformation/cobol_parser.py` L2099-L2136) captures only
  target and source-phrase token strings, and IR `StringStatement`
  (`engine/transformation/ir.py` L575-L584) has **no delimiter and no pointer fields**, so both
  are lost at parse time; the mapper's STRING branch
  (`engine/transformation/cobol_to_java_mapping.py` ~L2096) then concatenates source phrases
  verbatim.
- **Expected behavior:** Master README §16 (recognized constructs must never disappear silently —
  here the *semantics* disappear while the verdict stays green) and §60: either implement
  delimiter/pointer semantics correctly, or downgrade the affected `STRING` forms to
  `UNSUPPORTED` with a diagnostic that names the construct. `SUPPORTED` with wrong arithmetic is
  the one unacceptable combination.
- **Affected files:** `engine/transformation/cobol_parser.py` (`_parse_string`),
  `engine/transformation/ir.py` (`StringStatement`), `engine/transformation/cobol_to_java_mapping.py`
  (STRING branch), `engine/transformation/semantic_capability.py` (verdict downgrade if not fixed).
- **Impact:** any program using `STRING` with an explicit delimiter or `WITH POINTER` — a very
  common COBOL idiom for building fields — generates Java that produces incorrect data while
  reporting full support. Fail-closed §14/§15 behavior does **not** hold for this construct.
- **Remediation (committed as `13bdddd` — verification in progress):** additive
  `delimiter_exprs`/`pointer`/`has_overflow` fields on `StringStatement` (`ir.py`); `_parse_string`
  tokenizes the `DELIMITED BY` / `WITH POINTER` / `ON OVERFLOW` phrases (`cobol_parser.py`); the
  mapper emits delimiter-excluding concatenation and reads/writes the pointer, and fails closed
  with an `UNSUPPORTED_STRING$…` symbol for identifier delimiters, `ON OVERFLOW` and non-integer
  pointers (`cobol_to_java_mapping.py`); the analyzer and both generators walk/emit the new
  fields; the capability-registry evidence text for `STRING` was updated to match. No unrelated
  mapper paths touched.
- **Acceptance criteria:** (1) `DELIMITED BY <literal>` and `DELIMITED BY SIZE` produce Java that
  excludes the delimiter from the result; (2) `WITH POINTER` reads and writes the pointer variable
  in emitted Java; (3) any remaining unimplemented form (e.g. `DELIMITED BY identifier`) returns
  `UNSUPPORTED` with a diagnostic naming it; (4) focused positive/negative tests are added to the
  fast `capability-truth` gate covering literal delimiter, `SPACE`, `identifier`, `WITH POINTER`
  and overlapping source/target; (5) no existing test is weakened or skipped; (6) the serialized
  full suite stays at the 26-failure environmental baseline recorded for `bdb4c9a`.
- **Verification level:** the *defect* is VERIFIED by direct probing (emitted Java and verdict both
  observed at `bdb4c9a` in the Linux JDK container). The *fix* has now reached **LEVEL 6 —
  ORACLE_MATCHED** for the tested subset (real container compile-and-execute of the generated
  Java plus independent GnuCOBOL oracle execution, byte-identical output — see "Fix verification
  (executed 2026-10-11)" below), and the serialized full suite is now back at **exactly the
  26-identity environmental baseline** (rerun: 26 failed / 3282 passed / 12 skipped, zero new
  failures by identity). The item is **not closed**: exact-SHA CI is green at `6bfcbe4` and all
  six acceptance criteria are met, but the §53 re-audit (criterion 9 re-scoring, the documented
  closing action) has not yet run.
- **Owner/role:** semantic transformation maintainer. **Target phase:** blocks **Phase 1 §53.9**
  (fix lands as parser/IR work, i.e. Phase 1 scope — it must close before Phase 1 can be
  certified). **Dependency:** additive `StringStatement` IR change. **Residual risk:** the fix is
  committed as `13bdddd`, oracle-matched for the tested subset, the full suite is back at the
  26-identity environmental baseline, and exact-SHA CI is green at `6bfcbe4` — but until the
  §53 re-audit re-scores criterion 9, the item stays open and Phase 1 cannot be marked
  `COMPLETE — VERIFIED`.
- **Why not closed in the `bdb4c9a` audit:** this fix is an IR-plus-mapper change that, by §53.10's
  own rules, requires a fresh serialized full-suite run *and* a new exact-SHA CI cycle; closing it
  inside the `bdb4c9a` evidence chain (Push #501 / PR #502) without those runs would be exactly
  the evidence-smuggling §61 forbids. The item was therefore named as the **Phase 1 §53.9
  blocker** with explicit next actions (fix → focused tests → serialized full suite → container
  compile/execute → commit → new exact-SHA CI → re-audit). The implementation has since landed in
  the working tree of this follow-up session, and the evidence steps (focused tests, container
  compile/execute, serialized full suite at baseline) are now recorded below from their actual
  observed results; commit + push and the new exact-SHA CI cycle remain.

#### Fix verification (executed 2026-10-11 — real runs, outputs of record)

- **Focused tests:** `tests/transformation/test_string_delimited_semantics.py` — 28 test
  methods, one parametrized ×3 → **30 tests** (no skips/xfails in the file). All 30 pass; none
  appears among the failures of either full-suite run below. The file is wired into the
  `capability-truth` gate in `.github/workflows/ci.yml`.
- **Container compile-and-execute + oracle differential:** `bl027_java_gen.py` generated
  `Sem.java` (CASE1 `DELIMITED BY ","` → `ABEFGH`, CASE2 `DELIMITED BY SPACE` → `JOHNEFGH`,
  CASE3 `WITH POINTER WS-P` writes at position 5 and advances the pointer). In isolated
  containers (`--network none`, 512m/2cpu): `javac` 21 (Temurin image) compiled and executed it
  (exit 0); `cobc -x -free` (GnuCOBOL 3.1.2, `gnucobol-ocesql:latest`) compiled and executed
  `sem.cob` (exit 0). `bl027_diff.py` compared the captures byte-for-byte:
  **`ORACLE_MATCH=YES`** (3/3 lines identical) and both matched the hand-computed
  `expected.txt` (`EXPECTED_MATCH=YES`). Outputs of record:
  `%TEMP%\opencode\bl027_container_java_run.txt`, `bl027_container_cobol_run.txt`,
  `bl027_diff.py`.
- **Fail-closed forms:** `bl027_probe.py` (8 cases) — `DELIMITED BY identifier` →
  `UNSUPPORTED_STRING$DELIMITED_BY_IDENTIFIER_WS_B` + `UNSUPPORTED_CONSTRUCT` diagnostic +
  verdict UNSUPPORTED; `ON OVERFLOW` → `UNSUPPORTED_STRING$OVERFLOW` + diagnostic + UNSUPPORTED;
  SIZE/literal/SPACE/POINTER forms map to delimiter-excluding emission with pointer
  clamp/advance (verdict PARTIAL only due to the pre-existing unrelated COMP notice); the three
  workload fixtures (INVENTORY/PAYROLL/CLAIMS) generate with zero STRING diagnostics and no
  fail-closed symbol. Output of record: `%TEMP%\opencode\bl027_probe_run2.txt`.
- **Serialized full suite (2026-10-11): two runs, both recorded.**
  - **Run 1 (47:56): 36 failed / 3272 passed / 12 skipped.** Identity comparison
    (`bl027_compare.py`, normalized): = the exact 26-identity environmental baseline from the
    `bdb4c9a` clean run **+ 10 new failures, all in `tests/integration/`** (3
    `test_indexed_semantics`, 6 `test_integrated_proof_api`, 1 `test_payroll_artifacts`), zero
    previously-failing tests fixed or changed. All 56 tests in the three files passed in
    isolation (`bl027_integration_rerun.txt`, 3:04); failure sites were Docker digest resolution
    (`docker_adapter.py:133`, `oracle image identity is not established`) and a 10s
    service-worker timeout (`run stuck at stage 'CREATED'`) — no STRING code path.
  - **Run 2 (serialized rerun, 34:00): 26 failed / 3282 passed / 12 skipped — EXACTLY the
    26-identity environmental baseline.** `bl027_compare.py`: **rerun minus clean = ∅ (zero new
    failures); clean minus rerun = ∅ (zero changed).** This confirms run 1's 10 extras were
    load-sensitive Docker/timeouts transients, not regressions, and it satisfies acceptance
    criterion (6) *by identity, same environment* — not by count. Passed went 3252 → 3282, i.e.
    exactly the **+30 new BL-027 tests, all passing**; the 30 appear nowhere in the failure set.
    Output of record: shell log `sh_12bd7d4d90010F8nxwCegnVTtw.out`.
  - **Exact-SHA CI at `6bfcbe4` (verified via GitHub API, 2026-10-11): all four workflows
    SUCCESS.** Push SystemaOps CI
    [#38159864669](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159864669)
    — all 4 jobs green (Capability truth gate, which runs the 30 new BL-027 tests on Linux with
    a real JDK; Backend and COBOL/Java Docker tests; Phase 1 ingestion diagnostics; Frontend);
    PR SystemaOps CI
    [#38159868523](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159868523)
    — same 4 jobs green; Supply chain
    [#38159864653](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159864653)
    (push) /
    [#38159868476](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38159868476)
    (PR) SUCCESS. Every job's `head_sha` matches `6bfcbe4` exactly. Acceptance criteria (1)–(6)
    are all met with real evidence. *(Update 2026-10-12: the §53 re-audit — then the sole
    remaining closing action — has now run; see change-log (h) and the BL-029 entry it
    produced.)*

### BL-028 — COBOL fixed-width receiver overflow truncation is not modeled in `STRING`
- **Type:** defect (silent semantic loss / wrong generated value) — reclassified from
  "documented limitation" on 2026-10-12 when the divergence was reproduced against the oracle
- **Priority:** P2 — real behavioral divergence for `STRING` results longer than the receiving
  field; was disclosed rather than silent at filing time (mapper docstring + `STRING`
  capability-registry evidence text), so §60 exposure obligations were met and no false
  `SUPPORTED` rested on this basis alone.
- **Severity:** medium — a program whose built string exceeds the receiver's `PIC` width kept
  the full value in the generated Java (unbounded `String`) where COBOL truncates to the field
  width, diverging at runtime with no diagnostic; the `WITH POINTER` arithmetic had the same
  shape (unbounded advance, no `1 .. W + 1` boundary rule).
- **Status:** **FIXED — VERIFIED (2026-10-12, Phase 2 cycle — `de8a808`)** — committed and
  verified against the exact-SHA CI cycle; see the Phase 2 change-log entry (i).
- **Found by:** Phase 2 audit/baseline re-probe: `bl028_fixture_gen.py` emitted a Java run whose
  8/8 lines diverged from GnuCOBOL (`CASE1[ABCDEFGH            ]` vs `CASE1[ABCDE]`, pointer
  `0025` vs `0011`, …) — `%TEMP%\opencode\phase2\bl028_pre_*` and the
  `[BL-028 PRE-FIX (defect evidence)]` section of `bl028_diff_out.txt`.
- **Root cause:** `_string_receiver_statements` (`engine/transformation/cobol_to_java_mapping.py`)
  modeled the receiving field as an unbounded Java `String` and advanced the pointer without a
  boundary rule; truncation to the declared field width was deliberately not emitted.
- **Fix:** the pre-state single assignment is kept (atomic read of the overlapping source/target),
  then (1) a width-clipping statement
  `T = T.substring(0, Math.min(T.length(), W))`, and (2) the oracle-pinned pointer rule: inside
  `1 .. W + 1` the insert happens and the pointer advances capped at `W + 1`; outside that range
  the statement is a no-op and the pointer is unchanged. Receivers with no declared width (group
  item / undeclared name) keep the legacy emission and fail closed at `javac`
  (`cannot find symbol: WS_G`) — documented, not silently changed.
- **Acceptance criteria:** (1) ✅ width-aware truncation emitted for declared receivers;
  (2) ✅ focused tests in the capability-truth gate (BL-028 boundary + truncation assertions in
  `tests/transformation/test_string_delimited_semantics.py`, now part of the `ci.yml` gate list);
  (3) ✅ no existing test weakened — the two pointer tests that encoded the pre-BL-028 model
  (`test_with_pointer_clamps_inserts_and_advances`,
  `test_overlapping_source_and_target_is_one_atomic_assignment`) were **replaced** with
  assertions for the oracle-pinned rule and are strictly stronger (they pin the boundary, the
  cap and the truncation, which the old assertions did not check at all);
  (4) serialized full suite **3366 passed, 4 skipped, 0 failed** (collection 3325 → 3370 = +45,
  failure-identity comparison NEW_ONLY=0 vs the 26-identity baseline) + exact-SHA CI green at
  `de8a808` (push #38218209824, PR #38218214587 rerun attempt 2).
- **Verification level:** LEVEL 3 (RUNTIME_VERIFIED against the independent GnuCOBOL 3.1.2
  oracle): post-fix fixture **`ORACLE_MATCH=YES` 8/8** byte-identical
  (`bl028_post_java_run.txt` / `bl028_post_cobol_run.txt`, diff computed by `bl028_diff.py`,
  output `bl028_diff_out.txt`); boundary probe (pointer `W+1`, `0`, `W`) **3/3 byte-identical**
  (`bl028_boundary_*`); the pre-fix run diverged on 8/8.
- **Owner/role:** semantic transformation maintainer. **Target phase:** Phase 2. **Dependency:**
  BL-027's `StringStatement` mapper path. **Residual risk:** a receiver with no declared width
  still fails closed at `javac` rather than at the analyzer; `STRING` overflow behaviour for
  group items remains unproven.

### BL-029 — `STRING ... VARYING IN` is silently dropped: wrong write position with a `SUPPORTED` verdict
- **Type:** defect (silent semantic loss / wrong generated value)
- **Priority:** P0 — phase-blocking capability-truth defect, the same §54 `capability truth drift`
  / §60 shape as BL-027: a receiving-position phrase is discarded at the parser/IR boundary while
  the registry claims `SUPPORTED` and no diagnostic is raised.
- **Severity:** high — a program using the standard `VARYING IN` alternative to `WITH POINTER`
  writes at position 1 instead of the pointer position and never advances the pointer, producing
  wrong output through the supported path.
- **Status:** FIXED — 2026-10-12 (`7dceec1`) — fail-closed per the established BL-018/BL-023
  pattern; found and fixed within the §53 re-audit cycle (below).
- **Found by:** `bl027_varying_probe.py` (`%TEMP%\opencode\reaudit_stage\`), run in the Linux
  audit container during the §53 re-audit at `cf35c1d`: the statement
  `STRING WS-A DELIMITED BY SIZE INTO WS-D VARYING IN WS-P FROM 1 BY 2.` parsed with
  `diags=-`, verdict **`SUPPORTED`**, `pointer=''` in the IR, and generated
  `WS_D = WS_A + WS_D.substring(...)` — `WS-P` is never read or written
  (`%TEMP%\opencode\reaudit_varying_cf35c1d.txt`). The same phrase combined with `ON OVERFLOW`
  named only `OVERFLOW` in the fail-closed symbol, hiding the dropped `VARYING IN`.
- **Root cause:** `_parse_string_text` (`engine/transformation/cobol_parser.py`) scanned the
  post-target tail only for `ON OVERFLOW` and `WITH POINTER`; `VARYING IN` (COBOL's alternative
  receiving-position form: pointer starts at `FROM`, advances `BY` after the statement) matched
  neither and fell through silently.
- **Remediation (implemented `7dceec1`):** the tail scan captures `VARYING IN <ptr>` into the new
  `StringStatement.varying_pointer` field and raises `UNSUPPORTED_CONSTRUCT` naming the phrase;
  the mapper appends `VARYING_IN_<PTR>` to the `UNSUPPORTED_STRING$…` fail-closed reasons (so
  `javac` reports the construct instead of a wrong value ever being produced); the `STRING`
  capability-registry evidence text names BL-029.
- **Acceptance criteria (all met, 2026-10-12):** (1) no `STRING ... VARYING IN` form keeps a
  `SUPPORTED` verdict or emits working Java — verified in the audit container: both
  `VARYING IN <ptr> FROM n BY m` and the bare `VARYING IN <ptr>` emit
  `WS_D = UNSUPPORTED_STRING$VARYING_IN_WS_P;` with `UNSUPPORTED_CONSTRUCT` diagnostics and
  verdict `UNSUPPORTED`, and the `ON OVERFLOW` combination names both reasons
  (`%TEMP%\opencode\reaudit_varying_fixed.txt`, `reaudit_edge_fixed.txt`); (2) focused tests in
  the capability-truth gate — 5 new tests in
  `tests/transformation/test_string_delimited_semantics.py`, gate **277 passed** in the
  container; (3) no existing test weakened; (4) serialized full suite **26 failed / 3287 passed /
  12 skipped** — the failure set is *identical by identity* to the `bdb4c9a` 26-identity
  environmental baseline (zero new, zero changed; +5 passed = these tests); exact-SHA CI green
  (run IDs in the `⚑ §53 RE-AUDIT` block of `opencode.md`).
- **Verification level:** LEVEL 3 (EXECUTED) — probes, gate, full suite and CI all executed at
  `7dceec1`'s tree.
- **Owner/role:** parser / IR / semantic transformation maintainer. **Target phase:** Phase 1
  (closed in-cycle). **Dependency:** BL-027's `StringStatement` tail scan. **Residual risk:** low
  — fail-closed by construction; the phrase has no certified mapping, so affected programs are
  refused with a named diagnostic rather than mistranslated.

### BL-030 — Figurative `ALL` / figurative-fill semantics not materialized at the PIC width (MOVE and VALUE)
- **Type:** defect (silent semantic loss / wrong generated value; non-compiling Java on the VALUE path)
- **Priority:** P0 — the wrong value reaches the generated program through the *supported* path
  under a `SUPPORTED` verdict with zero diagnostics (§54 capability-truth drift / §60), and on the
  `VALUE` path the emission was non-compiling raw COBOL text — the exact BL-018 defect class, in
  the emission layer instead of the parser.
- **Severity:** high — every affected `MOVE`/`VALUE` stores a different byte sequence than COBOL
  would (`"AB   "` vs `ABABABABAB`, `"          "` vs `..........`, `"0     "` vs `00000`), so
  downstream tests, references and redefines all see the wrong data with no diagnostic.
- **Status:** **FIXED — VERIFIED (2026-10-12, Phase 2 cycle — `de8a808`)** — discovered by
  adjacent probing while verifying BL-028; committed and verified against the exact-SHA CI
  cycle (change-log entry (i)).
- **Found by:** adjacent-case probing during the BL-028 verification
  (`%TEMP%\opencode\phase2\move_all_probe.py`, `all_oracle_probe.py`), then confirmed against the
  GnuCOBOL 3.1.2 oracle: `MOVE ALL "."` → `..........`, `MOVE ALL "AB"` → `ABABABABAB`,
  `MOVE ALL ZEROS TO X(5)` → `00000`, `VALUE ALL "*"` → `**********`, `VALUE ALL "AB"` →
  `ABABABABAB`, `VALUE ALL ZEROS` (`X` and `9`) → `00000`, `MOVE QUOTES TO X(3)` → `"""`.
- **Root cause:** two emission sites never consulted the canonical fill rule in
  `figurative.py`: (1) the `MOVE` branch of `map_cobol_statement`
  (`engine/transformation/cobol_to_java_mapping.py`) padded a one-character literal at runtime
  (only ever correct for `SPACES`) and passed `ALL <literal>` text through as data;
  (2) `map_pic_to_java_default` (the `VALUE` clause path) stripped quotes and `.ljust()`-padded
  the raw `item.value` text, emitting `static String WS_V = "ALL "*    ";`. The parser already
  produced `ir.FigurativeConstant` correctly (BL-018) — the IR was right and the generator was
  wrong.
- **Fix (deterministic, no LLM):** `figurative.py` gains `figurative_to_width(kind, fill, width)`
  — the single fill rule (pattern replication truncated at the final copy per COBOL 13.18.40.9,
  character fill for `SPACES`/`QUOTES`/`LOW-VALUE`/`HIGH-VALUE`, `'0' * width` for `ZERO` on an
  alphanumeric receiver, `None` when no fill can be derived so a caller can never invent one);
  the parser's `ALL` regex accepts a multi-character pattern and `ALL <figurative word>`
  collapses onto the word; both emission sites materialize the fill at the declared PIC width;
  `numeric_semantics.py` recognizes `ALL ZERO/ZEROS/ZEROES` as the plain `ZERO` figurative.
- **Acceptance criteria:** (1) ✅ both emission sites materialize at the declared width;
  (2) ✅ focused tests in the capability-truth gate — new
  `tests/transformation/test_figurative_fill_semantics.py` (43 tests) wired into the `ci.yml`
  gate list, covering positive fill forms, the `VALUE` site, negative cases (`VALUE "ZERO"` is
  data, `ALL ""` is not a constant) and registry/verdict truth; (3) ✅ no existing test weakened —
  `test_figurative_constants.py`'s three emission assertions and `test_scoped_construct_statements.py`'s
  inline-`ALL` assertion were **replaced** with the oracle values (they pinned the *defective*
  padding), and `test_multi_character_all_is_not_a_figurative_constant` was corrected to assert
  the oracle-verified repetition with the correction documented in the test body;
  (4) serialized full suite **3366 passed, 4 skipped, 0 failed** (collection 3325 → 3370 = +45,
  failure-identity comparison NEW_ONLY=0 vs the 26-identity baseline) + exact-SHA CI green at
  `de8a808` (push #38218209824, PR #38218214587 rerun attempt 2).
- **Verification level:** LEVEL 3 (RUNTIME_VERIFIED against the independent GnuCOBOL 3.1.2
  oracle): fixture `bl030_post` compiles under `eclipse-temurin:21-jdk` and runs
  **`ORACLE_MATCH=YES`, 11/11 lines byte-identical**
  (`bl030_java_run.txt` vs `bl030_cobol_run.txt`); the BL-028 fixture and boundary probe were
  re-run afterwards and stayed byte-identical (8/8, 3/3) — no regression.
- **Owner/role:** semantic transformation maintainer. **Target phase:** Phase 2. **Dependency:**
  BL-018's canonical `figurative.py` / `ir.FigurativeConstant`. **Residual risk:** the fill for a
  receiver with no declared width cannot be materialized and falls back to the pre-BL-030
  emission (same fail-closed-at-`javac` shape as BL-028); `LOW-VALUE`/`HIGH-VALUE` assume the
  native ASCII collating sequence (inherited BL-018 limitation).

### BL-036 — Multi-line `CALL` statements are not parsed (lanes disagree; valid formatting blocks)

- **Type:** defect (parser coverage / diagnostic accuracy)
- **Priority:** P2 — fail-closed: the verdict is honestly `UNSUPPORTED`
  and the plan blocks, so no wrong artifact is reachable. P2 rather than
  P3 because the *reason* is wrong (unparsed-statement noise instead of a
  CALL-lifecycle diagnostic) and perfectly valid COBOL formatting is
  rejected, contradicting the discovery lane which *does* see the call.
- **Severity:** medium for coverage (line-wrapped CALL is common), zero
  for trust (conservative direction).
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 5, combined P2 cycle with
  BL-026/BL-037/BL-038/BL-039)** (see change-log entry (o)). Root cause:
  the statement dispatcher required `"CALL "` (operand on the same line), so
  a bare `CALL` line never reached `_parse_call` and fell through as three
  unparsed statements. Fix: the dispatch routes a bare `CALL` line into
  `_parse_call`, whose continuation loop joins the target/USING lines —
  verified identical IR to the single-line spelling (same
  program-name/arguments/dynamics), zero split diagnostics, cross-lane edge
  parity; focused tests `tests/test_call_statement_parsing.py`; fresh E2E
  multi-line CALL with a real LINKAGE callee `ORACLE_MATCH=YES`.
- **Found by:** Phase 3 audit probes (`probe_silent.py` Q1/Q2), 2026-10-12.
- **Observed behavior (verified):** `CALL\n  'LINETARGET'\n  USING WS-B.`
  → `CobolParser` returns **zero** `CallStatement`s and emits three
  `unparsed_statement` diagnostics ("Skipped unsupported statement: CALL",
  `"'LINETARGET'"`, `"USING WS-B."`); `program.called_programs` is empty;
  capability classifies the program `UNSUPPORTED` (`PARSE_FAILURE`), plan
  `BLOCKED` — while discovery's own regex (which spans newlines) records
  the edge and the planner shows `plan_calls=[MLMAIN→LINETARGET,
  RESOLVED]`. The lanes disagree about the same statement.
- **Expected behavior:** Master README §16 (recognized-but-unparsed
  constructs must produce an explicit diagnostic *naming the construct*);
  Phase 3 CALL lifecycle requires one extraction truth across discovery,
  parser and planner.
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_parse_call` requires CALL/literal/USING within one logical statement
  segment as split), `engine/transformation/application_discovery.py`
  (regex lane).
- **Impact:** valid programs blocked with misleading diagnostics; graph vs
  IR divergence (edge present, statement absent).
- **Remediation (planned):** statement segmentation that allows line
  breaks between `CALL`, the target and the `USING` clause, emitting the
  same `CallStatement` the single-line form produces; unify with the
  discovery extraction or add a cross-lane consistency test.
- **Acceptance criteria:** multi-line CALL parses to the same IR/verdict
  as its single-line spelling; diagnostics never split one statement into
  three "skipped statement" messages; focused tests join the gate; no
  existing CALL contract weakened.
- **Owner/role:** parser/IR maintainer. **Target phase:** Phase 3.
  **Dependency:** `CobolParser` statement splitting. **Residual risk:** until
  fixed, line-wrapped CALLs remain blocked (conservative).

### BL-037 — `CALL … ON EXCEPTION …` phrase is parsed as USING arguments (false arity, misleading diagnostic)

- **Type:** defect (parser coverage / diagnostic accuracy)
- **Priority:** P2 — fail-closed (the program blocks), but the reason is
  factually wrong and the standard `ON EXCEPTION` phrase of `CALL` is
  unparsed.
- **Severity:** medium — the diagnostic claims an arity mismatch that does
  not exist in the source.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 5, combined P2 cycle with
  BL-026/BL-036/BL-038/BL-039)** (see change-log entry (o)). Fix in three
  parts: (1) `_parse_call` stops the USING capture at the `ON EXCEPTION` /
  `ON OVERFLOW` phrase (correct arity) and names the phrase in an explicit
  `UNSUPPORTED_CONSTRUCT` diagnostic — never a false arity claim; (2) the
  planner maps a linkage-arity failure to its own `ARITY_MISMATCH`
  `BlockingReason` instead of `UNKNOWN_CONSTRUCT`; (3) focused tests
  `tests/test_call_statement_parsing.py` (correct arity + phrase named +
  no false-arity reason + `ARITY_MISMATCH` in the plan summary). Fresh E2E
  onexc: plan `BLOCKED` with the phrase named, oracle truth captured
  (handler fires `EXC-FIRED`).
- **Found by:** Phase 3 audit probe (`probe_phase3.py` P11), 2026-10-12.
- **Observed behavior (verified):** `CALL 'X' USING WS-A ON EXCEPTION
  DISPLAY "EXC".` → IR `CallStatement(arguments=('WS-A', 'ON', 'EXCEPTION',
  'DISPLAY', '"EXC"'))` (the phrase and its statement are swallowed into
  the USING list) → `_analyze_call_linkage_arity` reports 5 vs 1 →
  component `UNSUPPORTED` with reason "`CALL 'X' expects 1 argument(s) but
  receives 5`" → planner blocks (`UNKNOWN_CONSTRUCT`, itself a mis-mapping
  of an arity failure). The single-line `CALL … USING` form without the
  phrase is unaffected.
- **Expected behavior:** §16 (recognized phrases must be parsed or named
  in a diagnostic), §60 (never silently absorb source semantics), honest
  capability reasons.
- **Affected files:** `engine/transformation/cobol_parser.py` (`_parse_call`),
  `engine/modernization/capability_analyzer.py` (arity analysis),
  `engine/modernization/modernization_planner.py` (`_map_blocking_reasons`).
- **Impact:** valid programs blocked with a false arity claim; no wrong
  output (conservative).
- **Remediation (planned):** stop argument capture at the phrase keyword
  (`ON EXCEPTION`/`ON OVERFLOW`/`ON EXCEPTION` variants), model or diagnose
  the phrase explicitly, and map an arity failure to an arity-specific
  blocking reason instead of `UNKNOWN_CONSTRUCT`.
- **Acceptance criteria:** CALL with `ON EXCEPTION` yields the correct
  arity (1) and either parses the phrase or fails with a diagnostic naming
  it — never a false arity; focused tests join the gate.
- **Owner/role:** parser/IR maintainer. **Target phase:** Phase 3.
  **Dependency:** `CobolParser._parse_call`. **Residual risk:** until fixed,
  `ON EXCEPTION` callers are blocked with a misleading reason.

### BL-038 — `ProgramCall.resolution` stays `UNRESOLVED` for resolved static calls (stale provenance field)

- **Type:** defect (provenance/consistency)
- **Priority:** P2 — no verdict consumes this field (the capability
  analyzer reads `DependencyEdge.metadata`, which is correct), so no false
  classification is reachable; but the IR record contradicts itself.
- **Severity:** low — data-quality/traceability only.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 5, combined P2 cycle with
  BL-026/BL-036/BL-037/BL-039)** (see change-log entry (o)). Fix:
  `_build_dependency_graph` stamps each `ProgramCall.resolution` from the
  same decision that stamps the edge metadata (frozen dataclass replaced,
  unit tuple rebuilt) — verified: resolved static `RESOLVED`, missing
  static `UNRESOLVED`, dynamic never resolves even when the item value
  coincides with a program-id, and a mixed 3-call invariant test pins
  call-record == edge for every call; focused tests
  `tests/test_call_resolution_truth.py`.
- **Found by:** Phase 3 audit probe (`probe_phase3.py` P8), 2026-10-12.
- **Observed behavior (verified):** for `MLMAIN` → `LINETARGET` (a target
  that exists on disk), discovery records `unit.calls[…].resolution ==
  "UNRESOLVED"` while the dependency edge carries `resolution=RESOLVED`
  and the plan shows `RESOLVED`; `ProgramCall.resolution` is never updated
  by `_build_dependency_graph`/resolution.
- **Expected behavior:** §77/§60 provenance must not contradict the
  authoritative record; two fields of the same fact must agree.
- **Affected files:** `engine/transformation/application_discovery.py`
  (`_build_dependency_graph`), `engine/transformation/ir.py`
  (`ProgramCall.resolution` default).
- **Impact:** any consumer reading `ProgramCall.resolution` directly gets a
  false "unresolved"; current verdicts unaffected.
- **Remediation (planned):** set `ProgramCall.resolution` from the same
  resolution decision that stamps the edge metadata (or remove the field
  in favor of the edge), with a consistency test.
- **Acceptance criteria:** `ProgramCall.resolution` equals the edge's
  resolution for every call; a focused consistency test joins the gate.
- **Owner/role:** application discovery maintainer. **Target phase:**
  Phase 3. **Dependency:** edge-metadata stamping. **Residual risk:** stale
  field remains for direct consumers.

### BL-039 — Capability scan of copybook content is not transitive (constructs inside nested copybooks are unclassified)

- **Type:** defect (capability coverage)
- **Priority:** P2 — bounded: copybooks are data-definition files and the
  top-level file *is* scanned; the gap only opens for nested copybooks,
  which BL-031 just made materializable.
- **Severity:** medium-low — a nested copybook carrying an unsupported
  structural construct (`REDEFINES`/`OCCURS`/`COMP`-family etc.) would not
  lower the COPYBOOK component's verdict, because
  `_analyze_copybook` runs `scan_constructs` on the top-level file's text
  only and the consuming program's source scan sees only `COPY OUTER`.
- **Status:** **FIXED — 2026-10-13 (Phase 3 cycle 5, combined P2 cycle with
  BL-026/BL-036/BL-037/BL-038)** (see change-log entry (o)). Fix:
  `copybook_model.collect_copybook_texts` walks the top-level copybook and
  every reachable nested COPY target (same strict resolver, cycle-guarded,
  missing/ambiguous/cyclic/unreadable nested targets recorded as the same
  `ERROR` diagnostics generation fails on), and `_analyze_copybook` scans
  per file when the caller passes the shared search-directory authority
  (`analyze(application, source_root=...)`, threaded from the planner and
  pipeline) — the reason names the nested file carrying the worst-level
  keys, a nested problem fails the component closed with generation's own
  message, and flat copybooks keep the exact legacy reason; focused tests
  `tests/test_copybook_capability_transitivity.py`; fresh E2E nested2
  `ORACLE_MATCH=YES`.
- **Found by:** Phase 3 audit reasoning over BL-031's expansion (the nested
  content now reaches the merged IR but not the classifier).
- **Expected behavior:** §14/§20 — the verdict must cover everything the
  materialization actually merges.
- **Affected files:** `engine/modernization/capability_analyzer.py`
  (`_analyze_copybook`), `engine/transformation/copybook_model.py`
  (expansion output).
- **Impact:** potential false `SUPPORTED` COPYBOOK component for nested
  content the analyzer never sees.
- **Remediation (planned):** scan the *expanded* copybook text (reuse
  `_expand_copybook_text`) and attribute constructs to the nested chain in
  the reason; missing/cyclic nested targets already fail generation, and
  after BL-033 they must also fail the plan.
- **Acceptance criteria:** a nested copybook containing a registry
  non-SUPPORTED construct lowers the COPYBOOK verdict with a reason naming
  the nested file; expanded-scan results never contradict generation;
  focused tests join the gate.
- **Owner/role:** capability maintainer. **Target phase:** Phase 3.
  **Dependency:** BL-031's `_expand_copybook_text` (implemented).
  **Residual risk:** until fixed, nested copybook constructs are invisible
  to the capability graph.

### Backlog metadata note (documentation gap, P2)

Master README §77 asks each item to carry "priority and severity with
rationale". **BL-001…BL-024 do not record an explicit priority/severity field** —
a pre-existing gap in this document, not something introduced by the Phase 1
work. BL-025, BL-026, BL-027, BL-028, BL-029 and BL-030 are the first entries to carry it. The gap is recorded
here rather
than papered over: retro-fitting priority to 24 historical items without
re-assessing each one would fabricate precision that was never established.
Target: Phase 12 documentation pass.

A second, smaller gap (same pass target): the short documentation/process
entries (**BL-006, BL-007**) carry only type, status, observed behaviour and
remediation in their own sections — root cause, affected files, verification
level and evidence location are either n/a or live only in the carry-forward
register below. Everything else claimed here is verified: the §53.10 required
set (backlog ID, owner/role, target phase, dependency, reason, residual risk,
acceptance criteria) is present for **30/30** items in the register, and the
defect entries (BL-001…BL-005, BL-008…BL-010, BL-018…BL-030) each carry type,
observed/expected behaviour, root cause or explicit premise correction,
affected files, impact, remediation, acceptance criteria/tests, verification
level and evidence location.

### BL-019 — `NOT` in conditions is mangled into non-compiling Java
- **Type:** defect (silent semantic loss)
- **Status:** FIXED - 2026-10-11 (`7bba5cb`) - negated relational folded into the operator
- **Remediation (implemented, `7bba5cb`):** `_fold_negated_relational` folds COBOL's negated
  relational into the operator itself (`NOT >` -> `<=`, `NOT =` -> `!=`) because Java cannot
  express it as a prefix (`!A > B` compares a boolean; `A !> B` does not compile). It runs
  before operator rewriting and after figurative substitution so a `= SPACES` fill stays
  inside the comparison; the multi-clause fallback expands a figurative comparison to the
  same whole-field test the structured path emits.
- **Verification:** `tests/transformation/test_negated_conditions.py` (31 tests) - every
  operator form, no malformed token in generated Java, correct semantics, `NOT` inside a
  literal untouched. A test in this suite caught a real `KeyError` on `NOT <>` during
  development.
- **Observed behavior:** `map_cobol_condition_to_java` performs an
  unconditional `condition.replace("NOT ", "!")`. For `C NOT = SPACES` this
  runs *after* `NOT =` has already become `!=`, so it yields `C ! == SPACES`;
  `A NOT > 3` yields `A !> 3`. Both are non-compiling Java, produced with no
  diagnostic.
- **Pre-existing:** confirmed present at baseline `b8a746f`
  (`condition.replace("NOT ", "!")`, HEAD line 1011) and reproduced with no
  figurative constant involved (`C NOT = "A"`, `A NOT > 3`). It is therefore an
  **independent defect**, not a regression from BL-018. BL-018's fix makes it
  more visible because the figurative operand is now substituted correctly
  while the `NOT` token around it stays broken.
- **Expected behavior:** Master README Sections 16/60 — `NOT` must be parsed as
  an operator token, not blind string-replaced into a broken prefix.
- **Root cause:** operator handling is string `replace` rather than
  quote-aware tokenisation, so operator precedence/adjacency is not checked.
- **Affected files:** `engine/transformation/cobol_to_java_mapping.py`
  (`map_cobol_condition_to_java`, the `NOT`/`AND`/`OR`/`=` replacement chain).
- **Impact:** any `IF x NOT = y` / `IF x NOT > y` program generates invalid
  Java. Because it is confined to the condition mapper, it cannot be masked by
  a passing build elsewhere; it is a genuine correctness gap.
- **Remediation (NOT yet implemented — recorded for the next task):** `[NO LONGER
  ACCURATE — the fix WAS implemented in `7bba5cb`; see Status above. This draft
  said `!(...)`, which was deliberately NOT what was built: Java cannot express a
  negated relational as a prefix, so the operator is folded instead (`NOT >` ->
  `<=`). The draft is retained to show the acceptance criteria were corrected
  rather than quietly rewritten.]` replace
  the `NOT`/comparison replacement chain with quote-aware tokenisation that
  recognises `NOT` as an operator adjacent to a relational operator and emits
  `!(...)`, reusing the existing `_replace_bare_equals` quote-safety pattern.
  Must be done as its own change with its own positive/negative/regression
  tests so a BL-018-style fix cannot mask it.
- **Verification level:** STATIC + reproduced locally (not executed as a test
  yet, by design — no test was added while the behaviour is still broken and
  no existing test was weakened to accommodate it). `[SUPERSEDED — 31 tests now
  cover this and all pass.]`

---

### BL-049 — Non-ASCII bearer token causes `hmac.compare_digest` TypeError → 500 instead of 401

- **Type:** defect (error handling / security surface).
- **Priority:** P2 — unauthenticated request causes a 500 (availability/
  log-noise), not an auth bypass.
- **Severity:** low-medium.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified by hand.
- **Found by:** audit group T6; verified: `api/app.py L206-210` —
  `hmac.compare_digest(str, str)` raises `TypeError` when either side
  contains non-ASCII characters (HTTP headers are latin-1 decodable).
- **Observed behavior (verified):** `Authorization: Bearer <non-ASCII>`
  ⇒ 500.
- **Expected behavior:** 401 with the existing challenge body.
- **Root cause:** no ASCII normalization/guard before the digest compare.
- **Affected files:** `api/app.py` L206-215.
- **Impact:** error-path only; token never compared (no bypass).
- **Remediation (planned):** encode/compare on bytes or catch TypeError →
  401; adversarial test with a non-ASCII header.
- **Acceptance criteria:** non-ASCII token yields 401; security tests
  green.
- **Owner/role:** API maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none.

### BL-050 — Docker Java adapter compile-timeout path raises `UnboundLocalError` (wrong error message) and leaks the container

- **Type:** defect (error handling / operations).
- **Priority:** P2 — timeout is a normal path for slow builds; the real
  error is masked and the container is never cleaned.
- **Severity:** medium (leak accumulates on the daemon).
- **Status:** **FIXED — 2026-10-15 (Phase 9 batch P2a).** Filed OPEN by
  the repository-wide audit (Stage C, baseline `4deddfc`).  The compile
  timeout path now initializes `proc = None` before the try (mirroring
  `execute()`), so the `TimeoutExpired` handler reports the real
  "Compilation timed out" message and always runs the explicit container
  cleanup — no more `UnboundLocalError` masking or container leak.
  Focused test `test_bl050_java_compile_timeout_reports_and_cleans_
  container` (subprocess mocked) pins both behaviors.
- **Found by:** audit group T5; verified: `docker_java_adapter.py
  L341-402` — `proc` is assigned only inside `try`; the `TimeoutExpired`
  handler's `if proc is not None:` (L385) raises `UnboundLocalError`,
  caught by the outer `except Exception` (L404) which returns a generic
  failure; the cleanup at L393 never runs.
- **Observed behavior (verified):** compile timeout ⇒ wrong message +
  `docker rm` skipped.
- **Expected behavior:** `proc = None` before the try (as `execute()` does
  at L508) so the handler reports the timeout and removes the container.
- **Root cause:** two similar blocks written independently; one missed the
  initialization.
- **Affected files:** `engine/candidate/docker_java_adapter.py` L341-402.
- **Impact:** misleading diagnostics; container leak on the slow path.
- **Remediation (planned):** initialize `proc = None`; timeout test
  asserting the message and cleanup call.
- **Acceptance criteria:** timeout returns the timeout message; container
  removed; adapter tests green.
- **Owner/role:** candidate adapter maintainer. **Target phase:**
  unassigned. **Dependency:** none. **Residual risk:** none once fixed.

### BL-051 — Oracle Docker timeout path has no container name and no stop/rm cleanup

- **Type:** defect (operations).
- **Priority:** P2 — a timed-out oracle container persists on the daemon;
  no correctness impact (oracle failure is fail-closed).
- **Severity:** medium (leak on the hot verification path).
- **Status:** **FIXED — 2026-10-15 (Phase 9 batch P2a).** Filed OPEN by
  the repository-wide audit (Stage C, baseline `4deddfc`).  The oracle
  `docker run` now carries a deterministic `--name` (oracle- prefix) and
  the `TimeoutExpired` path kills the client and calls the shared
  `cleanup_container` helper (parity with the candidate adapters) —
  timed-out oracle containers no longer persist on the daemon.  Focused
  test `test_bl051_oracle_timeout_names_and_cleans_container` (subprocess
  mocked) pins the naming + cleanup.
- **Found by:** audit group T5; verified: `oracle/docker_adapter.py
  L473-504` — `docker run` without `--name`; timeout handler only sets
  stderr/exit/termination, unlike the candidate adapters' stop/rm/verify
  cleanup.
- **Observed behavior (verified):** oracle timeout ⇒ container left
  running/stopped on the daemon.
- **Expected behavior:** named container + bounded cleanup on every exit
  path (parity with candidate adapters).
- **Root cause:** cleanup pattern implemented per-adapter; oracle predates
  it.
- **Affected files:** `engine/oracle/docker_adapter.py` L473-504.
- **Impact:** daemon resource leak; repeated timeouts accumulate.
- **Remediation (planned):** `--name` + shared `_cleanup_container`
  helper (also closes the duplication T5 found); timeout test.
- **Acceptance criteria:** timed-out oracle containers are removed;
  oracle adapter tests green.
- **Owner/role:** oracle adapter maintainer. **Target phase:** unassigned.
  **Dependency:** shared cleanup helper (see Stage D). **Residual risk:**
  none once fixed.

### BL-052 — FIXED_RECORD comparator ignores trailing partial-record bytes (floor division; potential false MATCH via metadata mismatch)

- **Type:** defect (comparison integrity; defense-in-depth).
- **Priority:** P2 — unreachable via the current V1 capture path (content
  length is always a multiple of the record length by construction), but
  reachable via metadata mismatch or direct comparator use.
- **Severity:** low-medium (latent).
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle C, defect-proven-first)**.
  Failing test written first: `tests/comparators/
  test_fixed_record_trailing_partial.py` (9 tests) → red **5 failed /
  4 passed** captured at `%TEMP%\opencode\phase4\bl052_pre_fix.txt`
  (all five defect tests returned false `MATCH`, controls passed); fix in
  `engine/comparators/framework.py` (`_compare_record_by_record` now
  compares the bytes beyond the last whole record and reports them as a
  `trailing_partial_record` difference when they differ); focused run
  **9 passed**; regressions `tests/comparators` + `tests/adversarial`
  **282 passed** and the FIXED_RECORD integration set (inventory
  generalization, phase-D integrated proof, payroll artifacts, claims
  batch, identities) **172 passed**; gate-wired in `ci.yml`.
- **Found by:** audit group T5; verified: `comparators/framework.py
  L568-569` counts records by floor division; a trailing partial record
  on either side is never compared, and `L498` only guards declared
  record-count mismatch.
- **Observed behavior (verified at code level):** oracle length 105 /
  candidate 100 with equal first 10 records ⇒ MATCH (tail 5 bytes
  unexamined).
- **Expected behavior:** any byte not covered by a compared record is a
  mismatch.
- **Root cause:** floor-division counting without a remainder check.
- **Affected files:** `engine/comparators/framework.py` L559-622.
- **Impact:** false MATCH if artifact metadata ever disagrees with content
  (integrity validator is the second line of defense).
- **Remediation (done):** explicit tail comparison after the record loop →
  MISMATCH with the trailing bytes reported
  (`location="trailing_partial_record"`, expected/actual carry the tail
  bytes); adversarial tests cover oracle-tail, candidate-tail,
  differing equal-length tails, content shorter than the declared record
  length, plus whole-record/identical-content controls.
- **Acceptance criteria:** partial trailing records mismatch; comparator
  tests green. **Met** (evidence above).
- **Owner/role:** comparator maintainer. **Target phase:** Phase 4
  cycle C. **Dependency:** none. **Residual risk:** V1 pipeline unaffected
  today (capture path enforces whole records); behavior change is
  strictly fail-closed — byte-identical content still matches via the
  equality fast path above record inference.


### BL-053 — `derive_from_validated` does not re-check the seal (TOCTOU between validation and verdict derivation)

- **Type:** defect (trust boundary / evidence integrity).
- **Priority:** P2 — the docstring promises "calling code that bypasses
  the validator cannot produce an incorrect verdict", but a manifest
  mutated after validation is trusted verbatim.
- **Severity:** medium (hardening gap; no current caller mutates).
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified by hand.
- **Found by:** audit group T5; verified: `verdict/derivation.py L86-95`
  — `return self.derive(validated.manifest)` with no
  `integrity_hash == manifest.manifest_hash` re-check.
- **Observed behavior (verified):** post-validation mutation of the
  mutable manifest flows into the verdict.
- **Expected behavior:** re-check the seal (or freeze the manifest) so the
  docstring's guarantee holds.
- **Root cause:** trust handed to the wrapper object without re-binding it
  to the hash.
- **Affected files:** `engine/verdict/derivation.py` L86-95.
- **Impact:** future callers can accidentally create a trust bypass.
- **Remediation (planned):** re-verify the seal inside
  `derive_from_validated`; negative test with a mutated manifest.
- **Acceptance criteria:** mutated manifest fails derivation closed;
  verdict tests green.
- **Owner/role:** verdict maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none once sealed.

### BL-054 — Spring Boot adapter writes the built JAR back into `candidate_path/target`, making `candidate_hash` non-deterministic across runs

- **Type:** defect (identity determinism).
- **Priority:** P2 — latent (the default lane is DockerJava); when the
  Spring Boot lane is used, repeated runs over the same tree re-hash a
  growing `target/` directory.
- **Severity:** medium-low.
- **Status:** **FIXED — 2026-10-15 (Phase 9 batch P2a).** Filed OPEN by
  the repository-wide audit (Stage C, baseline `4deddfc`).  The candidate
  identity walk in `VerticalSlicePipeline._compute_candidate_identity`
  now skips the top-level `target/` build-output directory, so
  `candidate_hash` is derived only from the source tree and stays
  deterministic across repeated builds of identical sources.  Focused test
  `test_bl054_candidate_identity_ignores_build_output_target_dir` pins
  hash stability across differing JAR bytes.
- **Found by:** audit group T5; verified: `docker_spring_boot_adapter.py
  L457-460` writes `candidate_path/target/<jar>`; `pipeline.py L191-206`
  hashes every file under the candidate path with no exclusions.
- **Observed behavior (verified at code level):** second run hashes the
  JAR written by the first ⇒ different `candidate_hash` for identical
  sources.
- **Expected behavior:** candidate identity derived only from
  input/source-controlled files (or exclusion of build outputs).
- **Root cause:** execute()-findability workaround colliding with the
  identity walker.
- **Affected files:** `engine/candidate/docker_spring_boot_adapter.py`
  L457-460; `engine/pipeline.py` L191-206.
- **Impact:** non-reproducible evidence identity on that lane.
- **Remediation (planned):** exclude `target/` from the identity walk (or
  stage the JAR outside the candidate path); determinism test running
  compile twice.
- **Acceptance criteria:** repeated builds ⇒ identical `candidate_hash`;
  adapter tests green.
- **Owner/role:** candidate adapter / pipeline maintainer. **Target
  phase:** unassigned. **Dependency:** none. **Residual risk:** lane
  unused in the validated scope today.

### BL-055 — Lowercase `perform … until …` crashes with `IndexError` (case-sensitivity bug in an otherwise case-insensitive parser)

- **Type:** defect (robustness / diagnostics).
- **Priority:** P2 — crash is fail-closed (no false green) but produces an
  exception instead of a named diagnostic; COBOL sources legitimately use
  lowercase.
- **Severity:** medium-low.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle C)**; defect-proven-first:
  the new focused file `tests/transformation/test_perform_lowercase.py`
  ran **5 failed / 1 passed** against the unmodified parser
  (`%TEMP%\opencode\phase4\bl055_pre_fix.txt`) — every lowercase and
  mixed-case inline `perform … until …` / `perform varying … until …`
  raised `IndexError: list index out of range` exactly at the
  case-sensitive split, as the audit claimed.
- **Found by:** audit group T1; verified: `cobol_parser.py` — the
  guard tests `" UNTIL " in upper` but `line.split(" UNTIL ", 1)[1]`
  splits the *original-case* line → `IndexError` when the source is
  lowercase.
- **Observed behavior (verified):** `perform v1 until x > 5` ⇒
  `IndexError` out of `_parse_perform` (both the PERFORM UNTIL and the
  inline PERFORM VARYING branch).
- **Expected behavior:** case-insensitive handling like the rest of the
  parser.
- **Root cause:** mixed-case access (`upper` guard, original-case split).
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_parse_perform` inline branch).
- **Impact:** unhandled crash on valid lowercase COBOL.
- **Remediation (done):** the two `line.split(" UNTIL ", 1)` sites now
  use one `re.split(r"\s+UNTIL\s+", line, maxsplit=1, flags=re.IGNORECASE)`
  computed once for the inline branch; guard and split can no longer
  disagree on case (they share one case-insensitive boundary), and
  multi-space spellings (`perform  until  x`) are handled too.
- **Acceptance criteria:** met — lowercase forms parse identically to
  their uppercase twins (6 focused tests: red 5/1 pre-fix → green 6/6
  post-fix, incl. a fully lowercase program end-to-end and the
  uppercase regression); PERFORM/control-flow selection batch **37
  passed**. No existing test weakened.
- **Owner/role:** parser / IR maintainer. **Target phase:** **Phase 4
  (cycle C — fixed 2026-10-14)**. **Dependency:** none. **Residual
  risk:** none for PERFORM; other verbs were checked — this was the
  only `line.split("<UPPER>")` mixed-case pattern in the parser.

### BL-056 — `UnicodeDecodeError` escapes the copybook lanes' `except OSError` (crash instead of COPYBOOK_UNREADABLE; lanes can disagree on the same bytes)

- **Type:** defect (error handling / lane consistency).
- **Priority:** P2 — fail-closed direction (crash, not false green), but
  the analyzer reads the same bytes with `errors="replace"` so the two
  lanes can disagree on one file.
- **Severity:** low-medium.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle C, defect-proven-first)**.
  Failing test written first: `tests/test_copybook_decode_fail_closed.py`
  (8 tests) → red **8 failed / 0 passed**, every failure a raw
  `UnicodeDecodeError` escaping both lanes, captured at
  `%TEMP%\opencode\phase4\bl056_pre_fix.txt`; fix in
  `engine/transformation/copybook_model.py` (all three read sites now
  catch `(OSError, UnicodeError)`, mirroring the repo's established
  convention in `application_discovery.py` L246) and
  `engine/modernization/capability_analyzer.py` (copybook reader is now
  strict UTF-8, so a decode failure takes the analyzer's exact
  read-failure path instead of the lenient `errors="replace"` read);
  focused run **8 passed**; regressions copybook+capability batch
  **239 passed** and analyzer-importing batch **441 passed**; gate-wired
  in `ci.yml`.
- **Found by:** audit group T2; verified: `copybook_model.py L281-293`
  (`_expand_copybook_text`) and the `collect_copybook_texts` reader catch
  only `OSError` around `read_text(encoding="utf-8")`;
  `capability_analyzer` reads with `errors="replace"`.
- **Observed behavior (verified at code level):** a non-UTF-8 copybook
  raises `UnicodeDecodeError` out of expansion (top level: re-raised as
  `COPYBOOK_UNREADABLE` only for `OSError`).
- **Expected behavior:** decode failures produce the same
  `COPYBOOK_UNREADABLE` diagnostic as read failures in every lane.
- **Root cause:** exception tuple written for filesystem errors only.
- **Affected files:** `engine/transformation/copybook_model.py` L281-293,
  L395-410; compare `engine/transformation/capability_analyzer.py`
  (errors="replace" reader).
- **Impact:** crash instead of diagnostic; analyzer/materializer can
  classify the same file differently.
- **Remediation (done):** catch `(OSError, UnicodeError)` alongside each
  strict `read_text(encoding="utf-8")` in `_expand_copybook_text`
  (top-level re-raise preserved), `collect_copybook_texts`, and the
  `prepare_application_copybooks` handler — decode failures now produce
  the same `COPYBOOK_UNREADABLE` diagnostic as read failures; the
  analyzer's copybook reader dropped `errors="replace"` so decode
  failures land in its existing "could not be read" path (valid UTF-8
  reads unchanged). Focused test: binary-content copybook, top level and
  nested target, in both lanes plus the shared BL-039 reader, with a
  lane-parity assertion (the analyzer's reason quotes generation's exact
  unreadable message for the same bytes).
- **Acceptance criteria:** binary copybook ⇒ `COPYBOOK_UNREADABLE` in all
  lanes; copybook tests green. **Met** (evidence above).
- **Owner/role:** copybook materialization maintainer. **Target phase:**
  Phase 4 cycle C. **Dependency:** none. **Residual risk:** none once
  bounded — behavior change is strictly fail-closed (a binary copybook
  previously crashed; it now fails with a diagnostic) and valid UTF-8
  copybooks read identically.

### BL-057 — CICS generator renders literals with Python `repr()` (single-quoted → invalid Java)

- **Type:** defect (correctness of emitted code).
- **Priority:** P2 — CICS has no runtime lane (central status
  NOT_VERIFIED), so this cannot reach a green runtime verdict; still a
  correctness defect in generated output.
- **Severity:** medium-low.
- **Status:** **FIXED — 2026-10-15, committed `8f107d2`
  ("feat(phase7-p1): BL-057 CICS repr() quoting fix + focused test") by
  the pre-session Phase 7 P1 work; discovered OPEN 2026-10-14 by the
  repository-wide audit (Stage C, baseline `4deddfc`).** Status
  reconciled 2026-10-15 during this session's Phase 7 verification: the
  backlog row still read OPEN while `docs/PHASE_6_7_FINAL_REPORT.md`
  recorded the fix — the backlog was the stale document. Re-verified
  green in this session: `engine/cics/generator.py` `_java_arg` now
  double-quote-escapes (`"…"`, `\`/`"`/`\n`/`\r`/`\t`/`\b`/`\f`), and
  `tests/transformation/test_cics_java_literal_quoting.py` +
  `tests/test_cics_generator.py` +
  `tests/transformation/test_cics_java_lane.py` = **55 passed**
  (`%TEMP%\opencode\phase7\bl057_verify_green.txt`).
- **Found by:** audit group T4; verified: `cics/generator.py L562-568`
  (`_java_arg(quoted=True)` → `repr(value)`) used at L462/L473/L484.
- **Observed behavior (verified):** `cics.receive('MAP1');` — a Java char
  literal syntax error for multi-character strings.
- **Expected behavior:** double-quoted Java string literal via the shared
  Java-literal escaping helper (see BL-046).
- **Root cause:** Python-native quoting chosen for a Java emitter.
- **Affected files:** `engine/cics/generator.py` L462, L473, L484,
  L562-568.
- **Impact:** uncompilable CICS-lane output (fail-closed at javac).
- **Remediation (planned):** emit `"…"` with escaping; generation test
  pinning the literal form.
- **Acceptance criteria:** CICS generation emits valid Java string
  literals; cics tests green.
- **Owner/role:** CICS lane maintainer. **Target phase:** unassigned.
  **Dependency:** shared escaping helper (BL-046). **Residual risk:**
  blocked from runtime by the existing NOT_VERIFIED gate.

### BL-058 — WORKING-STORAGE group hierarchy is silently dropped (`current_group_children` write-only)

- **Type:** defect (IR fidelity; decision required).
- **Priority:** P2 — the group nesting is never materialized; whether
  children leak to top level or vanish changes downstream declarations
  (behavior-affecting fix — needs a design call, not a blind patch).
- **Severity:** medium.
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 7, defect-proven-first;
  design call recorded below).** Discovered 2026-10-14 by the
  repository-wide audit (Stage C, baseline `4deddfc`); statically verified
  (T1 line-by-line; the structure was re-read by hand at L866-897);
  sharpened 2026-10-14 by the Phase 4 §76 probes
  (`%TEMP%\opencode\phase4\probe_p4_r1.py`, case WS). **Design call
  (2026-10-15):** WORKING-STORAGE parses through the shared hierarchical
  data-description parser (`parse_data_description_lines`) — the same
  shape as LINKAGE/COPYBOOK: roots keep true COBOL level numbers, group
  nodes keep their `children`, `REDEFINES` is captured on the item, and
  88-level condition names nest under their parent. Elementary children
  are additionally expanded onto the top level (mirroring
  `materialize_copybooks_into_program`'s roots+leaves convention) so
  field generation and name lookups keep reading the flat list; 88-level
  condition names are never promoted — they are not storage.
  **Red evidence:** 5 failed / 2 passed in the full serialized Docker
  sweep (`%TEMP%\opencode\phase7\full_sweep_docker.txt` —
  `tests/test_bl058_working_storage_group_hierarchy.py`, pre-fix parser;
  the two green probes are the pre-fix-parity pins). **Green evidence:**
  focused `7 passed` (`%TEMP%\opencode\phase7\bl058_post_fix.txt`);
  bare-venv capability gate `656 passed` across 47 files after wiring the
  focused tests into `ci.yml` (`gate_bare_venv_post_bl058_wired.txt`,
  verified BEFORE relying on CI — the (ab) failure mode applied
  preemptively); transformation suite `2019 passed / 5 skipped`
  (`transformation_suite_post_bl058_jdk.txt`). No existing test weakened.
- **Found by:** audit group T1: `cobol_parser.py L814-899` —
  `current_group_children` is appended to but never read; the inner
  `pic_match` branch at L886 is unreachable for the level-10 path.
- **Observed behavior (verified at code level and by probe):** group nesting
  is lost; level-10 PIC children are not emitted as nested DataItems; WS
  88-level items and WS REDEFINES vanish without diagnostics.
- **Expected behavior:** group structure preserved in the IR (or an
  explicit diagnostic that the hierarchy is flattened).
- **Root cause:** hierarchy scaffolding left half-implemented.
- **Affected files:** `engine/transformation/cobol_parser.py` L814-899.
- **Impact:** declaration-shape fidelity; interacts with OCCURS groups.
- **Remediation (shipped 2026-10-15):** `_parse_working_storage` now
  slices the WS section and delegates to `parse_data_description_lines`
  (stack-built nested roots; true levels; REDEFINES; 88-level as
  children), then expands elementary children onto the top level via
  `_flatten_working_storage_record` (same structural rule as
  `copybook_model.flatten_records`, minus 88-level promotion); 7 focused
  tests in `tests/test_bl058_working_storage_group_hierarchy.py` wired
  into the `ci.yml` gate (47 files, bare-venv `656 passed`).
- **Acceptance criteria (met):** documented, tested representation of
  group nesting; elementary children remain declarable exactly as
  before; no existing test weakened (transformation suite `2019 passed`).
- **Owner/role:** parser / IR maintainer. **Target phase:** Phase 7
  (closed in-cycle 2026-10-15). **Residual risk:** FILE SECTION records
  remain flat (separate parser lane, out of BL-058 scope; no silent
  child loss there — children are top-level by construction).

### BL-059 — Capability derivation under-reports arithmetic (SUBTRACT/MULTIPLY/COMPUTE missing) and never recurses into inline-PERFORM/INVALID-KEY bodies

- **Type:** defect (capability coverage; conservative direction).
- **Priority:** P2 — under-reporting blocks valid applications (fail-closed
  direction: no false green).
- **Severity:** medium-low.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle C, defect-proven-first)**.
  Failing test written first: `tests/transformation/
  test_capability_walker_depth.py` (15 tests) → red **12 failed /
  3 passed** (the three controls — ADD top level, IF body, AT END body —
  green; every defect red, including the backlog's literal observed case
  `perform=True, arithmetic=False`) captured at
  `%TEMP%\opencode\phase4\bl059_pre_fix.txt`; fix in
  `engine/transformation/ir.py` (`has_arithmetic` now covers
  ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE; `_flatten_statements` walks
  inline-PERFORM `body` and the INVALID KEY / NOT INVALID KEY bodies of
  READ/START/WRITE/REWRITE/DELETE alongside the existing IF and AT END
  recursion); focused run **15 passed**; regression `tests/transformation`
  **1919 passed / 4 skipped / 0 failed**; gate-wired in `ci.yml`.
- **Found by:** audit group T1: `ir.py` L829, L914-930 — arithmetic
  capability derived from ADD-family statements only; inline-PERFORM and
  INVALID-KEY bodies not walked.
- **Observed behavior (verified at code level):** a program whose only
  executable content is SUBTRACT/COMPUTE inside an inline PERFORM derives
  no arithmetic capability.
- **Expected behavior:** every statement node contributes its capability
  at any nesting depth.
- **Root cause:** capability walker predates the inline-body nodes.
- **Affected files:** `engine/transformation/ir.py` L829, L914-930.
- **Impact:** valid programs classified with reduced capability (planner
  more conservative than reality).
- **Remediation (done):** `has_arithmetic` extended to the five
  arithmetic statement types the class docstring always promised;
  `_flatten_statements` extended to every compound body (inline PERFORM,
  INVALID KEY / NOT INVALID KEY across READ/START/WRITE/REWRITE/DELETE) —
  nested statements now contribute to *every* detection (assignment,
  display, decision, …), not just arithmetic. Focused tests cover each
  arithmetic type, each INVALID KEY owner (parametrized), the two READ
  key sides, nested assignment/display, an end-to-end parsed
  PERFORM-UNTIL+SUBTRACT, plus ADD/IF/AT-END controls pinning the
  recursion that already worked.
- **Acceptance criteria:** capability reflects all arithmetic at any
  depth; capability tests green. **Met** (evidence above).
- **Owner/role:** IR/capability maintainer. **Target phase:** Phase 4
  cycle C. **Dependency:** none. **Residual risk:** none once bounded —
  strictly truth-ward (statements genuinely present in the IR are now
  reported); the only engine consumer of capability-based mode selection
  (`_derive_generation_mode`) reads `decision`/`input_record_mapping`,
  both covered by the transformation regression batch.

### BL-060 — SQL execution error handlers build `Db2SqlStatus(sqlstate="")`, which raises `ValueError` from `__post_init__` inside the handler

- **Type:** defect (error handling).
- **Priority:** P2 — the handler designed to map IntegrityError/
  OperationalError to a "-1" status instead crashes with `ValueError`.
- **Severity:** medium-low.
- **Status:** **FIXED — VERIFIED 2026-10-15 (Phase 6 batch P2)**; red
  `bl060_pre_fix.txt` (collection ImportError — the sentinel constants
  did not exist; the behavioral `ValueError` crash proven by audit
  probes A2/B), focused green `bl060_focused_green.txt` (4 passed).
- **Found by:** audit group T4: `engine/sql/execution.py` L432, L441 —
  unmapped SQLSTATE paths construct a status whose dataclass rejects the
  empty SQLSTATE.
- **Observed behavior (verified at code level):** `IntegrityError` with
  an unmapped SQLSTATE ⇒ `ValueError` out of the handler.
- **Expected behavior:** a well-formed status (e.g. a reserved
  "UNKNOWN"/"-1" code) returned per the DB2-status contract.
- **Root cause:** invalid sentinel value chosen for the dataclass.
- **Affected files:** `engine/sql/execution.py` L432, L441.
- **Impact:** crash instead of the designed "-1" graceful result.
- **Remediation (planned):** valid sentinel + focused test injecting an
  unmapped SQLSTATE.
- **Acceptance criteria:** unmapped SQLSTATE returns the "-1" status;
  sql tests green.
- **Owner/role:** SQL lane maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none once fixed.

### BL-061 — DECLARE CURSOR bind information is discarded (host-variable cursors fail uncaught at OPEN)

- **Type:** defect (SQL lane correctness).
- **Priority:** P2 — bounded to the SQL lane (never runtime-verified);
  fails loudly, not silently.
- **Severity:** low-medium.
- **Status:** **FIXED — VERIFIED 2026-10-15 (Phase 6 batch P2)**; red
  `bl061_pre_fix.txt` (4 failed: host-variable OPEN fails uncaught,
  misuse unguarded), focused green `bl061_focused_green.txt` (4 passed).
- **Found by:** audit group T4: `engine/sql/execution.py` L172, L184-190 —
  `_declare_cursor` masks the query and drops the bind map
  (`masked, _binds = …`), so OPEN cannot bind `:HV` values.
- **Observed behavior (verified at code level):** cursor queries with
  host variables raise an uncaught `ProgrammingError` at OPEN.
- **Expected behavior:** binds carried from DECLARE to OPEN (or an
  explicit unsupported diagnostic).
- **Root cause:** two-phase cursor implementation missing the bind handoff.
- **Affected files:** `engine/sql/execution.py` L172-190.
- **Impact:** declared unsupported in practice; loud failure.
- **Remediation (planned):** thread the binds or fail closed with a named
  diagnostic; focused test.
- **Acceptance criteria:** host-variable cursors bind or fail closed
  named; sql tests green.
- **Owner/role:** SQL lane maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** disclosed subset stays
  narrower than documented.

### BL-062 — `INSERT INTO T VALUES (…)` without a column list mis-parses the VALUES list as the column list

- **Type:** defect (parser correctness).
- **Priority:** P2 — wrong columns derived silently within the SQL
  subset (SQL never gets a runtime verdict, so impact is bounded).
- **Severity:** low-medium.
- **Status:** **FIXED — VERIFIED 2026-10-15 (Phase 6 batch P2)**; red
  `bl062_pre_fix.txt` (`2 failed, 1 passed` — control form green),
  focused green `bl062_focused_green.txt` (3 passed).
- **Found by:** audit group T4: `engine/transformation/sql_parser.py`
  L422-425.
- **Observed behavior (verified at code level):** values are recorded as
  target columns.
- **Expected behavior:** column list optional; VALUES positionally maps
  to the table's columns or fails closed.
- **Root cause:** parser assumes the parenthesised list is always the
  column list.
- **Affected files:** `engine/transformation/sql_parser.py` L422-425.
- **Impact:** wrong column metadata for a common statement form.
- **Remediation (planned):** optional-column-list grammar; focused tests.
- **Acceptance criteria:** both forms parse correctly or fail closed
  named; sql parser tests green.
- **Owner/role:** SQL parser maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** none once parsed.

### BL-063 — JCL consumer: unsupported-construct scan covers only `*.jcl`, raw sources keyed by basename (collisions/skips), `except OSError` misses `UnicodeDecodeError`

- **Type:** defect (coverage/truth for the JCL lane).
- **Priority:** P2 — JCL is never runtime-verified (central NOT_VERIFIED),
  but blocked-reason truth can be incomplete for `.jcllib`/extensionless
  members and colliding basenames.
- **Severity:** medium-low.
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P2, defect-
  proven-first).** Two red captures: `bl063_pre_fix_import.txt` (the new
  shared matcher did not exist — collection `ImportError`) and, after
  implementing only the matcher, `bl063_pre_fix.txt` — **`6 failed,
  8 passed`** proving the behavioral defects on the unchanged consumer/gate
  (`.jcllib` and extensionless members reported FULL, basename collision
  silently lost the unsupported member, non-UTF8 member escaped as an
  exception, the decodable-beside-bad case failed, and the API presence
  gate said `NOT_PRESENT` for a `.jcllib`-only tree).  Green: focused
  `14 passed` (`bl063_focused_green.txt`), full JCL regression
  `255 passed` (`bl063_jcl_regression.txt`), Docker-gated JCL files
  `5 passed` (`bl063_docker_regression.txt`).
- **Found by:** audit group T4: `engine/transformation/jcl_consumer.py`
  L107-112.
- **Observed behavior (verified by execution):** discovery finds
  `.jcllib`/extensionless members; the consumer's unsupported scan and
  basename-keyed source map do not see them uniformly — PROBE1: `.jcllib`
  member containing `IF/THEN` → status **FULL**, zero unsupported
  diagnostics (same for extensionless in PROBE2); PROBE12: basename
  collision `a/dup.jcl` (unsupported) + `b/dup.jcl` (clean) → the first
  file's text never enters the scan pool → **FULL, silent loss**;
  PROBE4: non-UTF8 `.jcl` → `UnicodeDecodeError` escapes
  `modernize_jcl_workload` while `JclDiscovery` silently drops the same
  file (one lane crashes, the other vanishes the job); PROBE5:
  `api/service.py::_jcl_status_for_source` returns `NOT_PRESENT` for a
  `.jcllib`-only tree while the consumer returns `FULL` (presence gate
  uses its own `rglob("*.jcl")`). PROBE14: `UPPER.JCL` scans on Windows
  only because the FS is case-insensitive — on Linux CI the same
  `rglob("*.jcl")` (consumer + API gate) would miss uppercase suffixes
  (static finding, not demonstrable on win32).
- **Expected behavior:** one discovery rule shared by both lanes (and the
  API presence gate); decode failures diagnosed, never escaped and never
  silently skipped; basename collisions reported instead of overwriting.
- **Root cause:** independent file-selection logic in the consumer and in
  `api/service.py`.
- **Affected files:** `engine/transformation/jcl_consumer.py` L107-132,
  `engine/transformation/jcl_discovery.py` (per-file `except Exception:
  continue`), `api/service.py` `_jcl_status_for_source` L194-211.
- **Impact:** silently skipped members in blocked-reason reporting; false
  FULL status for unscanned members; decode crash for direct callers;
  JCL lane invisible in the ledger for non-`*.jcl` trees.
- **Remediation (delivered):** `engine/transformation/jcl_discovery.py`
  gained the single member rule — `is_jcl_member` (case-insensitive
  `.jcl`/`.jcllib` suffixes; extensionless members sniffed leniently so a
  non-UTF8 member is still recognized, never dropped at the membership
  layer) and `find_jcl_members` (whole-tree walk, so uppercase suffixes
  survive case-sensitive filesystems) — now used by discovery
  (`_find_jcl_files` delegates), the consumer scan, and the API presence
  gate (`api/service.py::_jcl_status_for_source`); the consumer keys
  raw sources by member-relative POSIX path, so colliding basenames
  cannot overwrite each other and every member contributes to the
  unsupported scan (this is strictly stronger than "collisions
  reported" — with path keys a collision cannot occur); undecodable or
  unreadable members are diagnosed fail-closed via the new
  `JCL_SOURCE_DECODE_FAILED` ERROR code entering the same diagnostic
  collector as `pre_diagnostics` on `modernize_jcl`, so status can never
  overstate a member as covered (`FULL` → `PARTIAL`); discovery's broad
  `except Exception: continue` narrowed to `(OSError, UnicodeDecodeError)`
  with the no-silent-loss rationale inline.  Focused suite
  `tests/transformation/test_jcl_discovery_matching.py` (gate-wired).
- **Acceptance criteria:** `.jcllib`/extensionless/uppercase members
  scanned; collisions reported; decode failures diagnosed (no escape, no
  silent drop); API and consumer statuses agree; jcl tests green.
- **Owner/role:** JCL lane maintainer. **Target phase:** Phase 5
  (batch P2, per register).
  **Dependency:** none. **Residual risk:** none once unified.

### BL-064 — Spring Boot generator emits every copybook model file twice (duplicate class files in the output tree)

- **Type:** defect (generation correctness).
- **Priority:** P2 — duplicate same-package classes fail at javac
  (fail-closed), so no false green; broken output for any copybook
  workload on that lane.
- **Severity:** medium-low.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle C, defect-proven-first)**.
  Failing test written first: `tests/transformation/
  test_spring_model_emission_unique.py` (4 tests) → red **3 failed /
  1 passed** (model-less control green; every model path duplicated)
  captured at `%TEMP%\opencode\phase4\bl064_pre_fix.txt`; `git blame`
  identified the duplicate as the loop added by `fa0fa62a` (2026-09-24
  22:22) on top of the original M7 loop (`76583572`, 21:05) — the fix
  removes the accidental re-add and pins the surviving loop as the single
  emission site; focused run **14 passed** (incl. M7 integration);
  regressions `tests/transformation` **1923 passed / 4 skipped** and the
  root Spring-consumer batch **100 passed**; gate-wired in `ci.yml`.
- **Found by:** audit group T3: `spring_boot_generator.py` L108-130.
- **Observed behavior (verified at code level):** model generation loop
  appends each copybook class file twice.
- **Expected behavior:** one file per model.
- **Root cause:** two append sites (per-program + per-copybook pass)
  without de-duplication.
- **Affected files:** `engine/transformation/spring_boot_generator.py`
  L108-130.
- **Impact:** uncompilable output for copybook workloads on the Spring
  Boot lane.
- **Remediation (done):** single emission path — the accidental duplicate
  loop was deleted (blame-proven re-add) and the original M7 loop
  documented as the only model-emission site; generation tests assert
  per-model and global path uniqueness (single model, two models, plus a
  model-less control pinning the rest of the emission order).
- **Acceptance criteria:** each model emitted once; generator tests
  green. **Met** (evidence above).
- **Owner/role:** Spring Boot generator maintainer. **Target phase:**
  Phase 4 cycle C. **Dependency:** none. **Residual risk:** none once
  de-duplicated — output file *set* and content are unchanged (the model
  renderer is pure); only the duplicated list entry is gone.

### BL-065 — Legacy Java-generator paths isinstance-check IR classes that are never imported (`NameError` if reached)

- **Type:** defect (robustness; fail-closed direction).
- **Priority:** P2 — crash instead of a diagnostic if a legacy path is
  reached; no false green.
- **Severity:** low.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified (T3); hand-check
  pending.
- **Found by:** audit group T3: `java_generator.py` L1775-1899 —
  `_extract_statements` references `ReadStatement` without a module import
  (T3 found several such classes in the legacy region).
- **Observed behavior (verified at code level):** reaching the branch
  raises `NameError`.
- **Expected behavior:** import the classes or delete the dead legacy
  region (inventory decision).
- **Root cause:** half-removed legacy path.
- **Affected files:** `engine/transformation/java_generator.py`
  L1775-1899.
- **Impact:** crash path; confusing diagnostics.
- **Remediation (planned):** inventory the legacy region; delete if
  unreferenced (with API call) or import + diagnose.
- **Acceptance criteria:** no `NameError` path remains; generator tests
  green.
- **Owner/role:** Java generator maintainer. **Target phase:** unassigned.
  **Dependency:** legacy-region inventory decision. **Residual risk:**
  none once resolved.

### BL-066 — Planner reason mapping substring-parses analyzer prose (`_map_blocking_reasons`): duplicate UNSUPPORTED_CONSTRUCT lines for GO TO; any "parsed" wording maps to PARSE_FAILURE

- **Type:** defect (maintainability / diagnostic precision).
- **Priority:** P3 — current prose is stable and pinned by tests; the
  coupling breaks silently on future wording changes.
- **Severity:** low.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified (T2); hand-check
  pending.
- **Found by:** audit group T2: `modernization_planner.py` L686-738 —
  GO TO reasons already carry `UNSUPPORTED_CONSTRUCT` and get it appended
  a second time; the `"parse"` substring matches "parsed …" prose.
- **Observed behavior (verified at code level):** duplicate summary lines
  for GO TO-blocked plans.
- **Expected behavior:** reason codes carried structurally (enum on the
  diagnostic), not re-derived from prose.
- **Root cause:** prose-as-contract from the pre-BL-033 era.
- **Affected files:** `engine/modernization/modernization_planner.py`
  L686-738.
- **Impact:** cosmetic duplication today; silent mis-mapping risk on
  wording changes.
- **Remediation (planned):** structural codes on analyzer diagnostics;
  planner maps codes; keep prose for humans.
- **Acceptance criteria:** no prose substring mapping remains; planner +
  contracts tests green.
- **Owner/role:** modernization planner maintainer. **Target phase:**
  unassigned. **Dependency:** diagnostic-code plumbing. **Residual risk:**
  duplication remains until fixed.

### BL-067 — API generated-app download zips the whole tree into memory with no size or file-count cap

- **Type:** defect (operations / resource exhaustion).
- **Priority:** P3 — authenticated GET; generated trees are small in the
  validated scope; unbounded memory is a DoS-shaped gap.
- **Severity:** low.
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified by hand.
- **Found by:** audit group T6; verified: `api/app.py L691-696` —
  `io.BytesIO` + full `rglob` with no cap before `StreamingResponse`.
- **Observed behavior (verified):** the entire archive is built in RAM
  per request.
- **Expected behavior:** streamed zip or an explicit size cap.
- **Root cause:** simplest-possible implementation left unbounded.
- **Affected files:** `api/app.py` L691-702.
- **Impact:** memory exhaustion on pathological trees.
- **Remediation (planned):** cap files/bytes (reuse the upload-limit
  pattern) and fail closed; test with an oversized tree.
- **Acceptance criteria:** cap enforced with a 4xx/413; API tests green.
- **Owner/role:** API maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** bounded by deployment memory
  until fixed.

### BL-068 — Frontend state-correctness trio: stale `selectedAppId` renders the wrong application; download errors never displayed; `runIds` never pruned (unbounded 2s polling)

- **Type:** defect (UI correctness / operations).
- **Priority:** P3 — customer-visible confusion and wasted polling; no
  data or verdict impact.
- **Severity:** medium-low (wrong-application display is the worst of the
  three).
- **Status:** **OPEN — discovered 2026-10-14 by the repository-wide audit
  (Stage C, baseline `4deddfc`)**; statically verified (T8 line-by-line);
  hand-check pending.
- **Found by:** audit group T8:
  (a) `src/App.tsx` L14, L26-35, L141, L209-210 — `selectedAppId` is not
  reset when a run is opened from the Dashboard, so discovery/ingest
  summary render for the previously created application;
  (b) `src/pages/ModernizationRun.tsx` L318 vs L371/L780/L824 — download
  failures set `pollError`, but that UI only renders on non-terminal runs
  while Download only exists on COMPLETED, so the error is never shown;
  (c) `src/App.tsx` L24, L80-104 — `runIds` is only appended and never
  pruned; every run started in a session is polled every 2s forever, in
  addition to the run page's own polling.
- **Observed behavior (verified at code level):** as above.
- **Expected behavior:** the opened run's own application is displayed;
  download errors surfaced; terminal runs dropped from polling.
- **Root cause:** three independent state-lifecycle gaps.
- **Affected files:** `src/App.tsx`, `src/pages/ModernizationRun.tsx`.
- **Impact:** wrong-context UI; silent download failures; growing poll
  load.
- **Remediation (planned):** set/clear `selectedAppId` with the run;
  render download errors in the completed state; prune terminal ids (or
  stop polling terminal runs); component tests.
- **Acceptance criteria:** each of the three has a focused test; frontend
  type-check + tests + build green.
- **Owner/role:** frontend maintainer. **Target phase:** unassigned.
  **Dependency:** none. **Residual risk:** cosmetic wrongness remains
  until fixed.

### BL-069 — `_parse_multiply` silently returns an empty `MultiplyStatement` for standard `MULTIPLY a BY b BY c` and `ON SIZE ERROR` forms (no diagnostic)

- **Type:** defect (silent semantic loss).
- **Priority:** P1 — a recognized arithmetic statement produces an empty IR
  node (source="", multiplicand="") with **no** `_emit_unparsed` diagnostic,
  so the multiplication vanishes from the generated program. Unlike
  `ADD`/`SUBTRACT`/`DIVIDE`, which emit `UNSUPPORTED_CONSTRUCT` for the same
  shape, nothing downstream can see the loss. Verdict impact is bounded today
  only because the empty operands make downstream mapping produce no real
  arithmetic — but the diagnostic channel is missing entirely (the exact
  ADD/SUBTRACT/DIVIDE asymmetry).
- **Severity:** medium-high for coverage and diagnostic completeness;
  §53.9 requires recognized statements never disappear without a diagnostic.
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle B)**; defect-proven-first:
  the new focused file `tests/transformation/test_multiply_diagnostic.py`
  ran **5 failed / 5 passed** against the unmodified parser
  (`%TEMP%\opencode\phase4\bl069_pre_fix.txt`) — every standard
  no-match form (double-`BY`, `ON SIZE ERROR`, lowercase, multi-recipient
  `GIVING` list) returned a diagnostic-free empty node exactly as the
  probe claimed.
- **Found by:** Phase 4 audit probes (`%TEMP%\opencode\phase4\probe_p4_r1.py`,
  case MULTIPLY): real `CobolParser.parse` of
  `MULTIPLY WS-A BY WS-B BY WS-C.` and
  `MULTIPLY WS-A BY WS-B ON SIZE ERROR DISPLAY "E".` — both yield a
  `MultiplyStatement(source="", multiplicand="")` and **zero diagnostics**;
  the same sources through `ADD`/`SUBTRACT`/`DIVIDE` positions emit
  `UNSUPPORTED_CONSTRUCT` "Statement did not parse into IR".
- **Expected behavior:** the standard double-`BY` form and the
  `ON SIZE ERROR` form either parse into full IR or fail closed with an
  explicit diagnostic naming the statement (the ADD/SUBTRACT/DIVIDE rule).
- **Root cause:** the single regex at `cobol_parser.py L1572-1576` accepts
  only the strict `MULTIPLY x BY y [GIVING z] [ROUNDED]` spelling; the
  no-match branch `L1577-1578` returned an empty node instead of calling
  `_emit_unparsed` (contrast `_parse_add` etc., which fail closed).
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_parse_multiply`).
- **Impact:** silent drop of a recognized arithmetic statement with no
  diagnostic — the §53.9/§60 defect class; capability consumers cannot see it.
- **Remediation (done):** the no-match branch now emits the same
  `UNSUPPORTED_CONSTRUCT` "Statement did not parse into IR" diagnostic
  ADD/SUBTRACT/DIVIDE emit in this position (`_emit_unparsed("MULTIPLY",
  …)`), mirroring ADD exactly; the empty node returned *after* the
  diagnostic is the shared contract of that family (the mapper then
  degrades visibly, not silently). Full regex extension for the
  double-`BY`/`ON SIZE ERROR` forms is **not** in this fix — those
  spellings are now honestly diagnosed as unparsed instead of silently
  dropped; extending the regex is a separate coverage enhancement with
  its own acceptance burden.
- **Acceptance criteria:** met — no `MULTIPLY` spelling returns a
  diagnostic-free empty node (10 focused tests incl. a property test
  over the standard forms: red 5/5 pre-fix → green 10/10 post-fix);
  parser arithmetic regression batch green; gate wired. No existing test
  weakened.
- **Owner/role:** parser / IR maintainer. **Target phase:** Phase 4
  (cycle B — fixed 2026-10-14). **Dependency:** none. **Residual risk:**
  standard double-`BY`/`ON SIZE ERROR` forms remain UNSUPPORTED (now
  with a diagnostic) until the regex is extended — coverage gap, not a
  silent-loss gap.

### BL-070 — `_parse_rewrite` binds the target file by string heuristic only and ignores the FILE SECTION owner map (`_record_owner`), silently degrading unbound REWRITE to a comment

- **Type:** defect (silent semantic loss / lane inconsistency).
- **Priority:** P1 — `WRITE` resolves its file via the authoritative
  `_record_owner` map first (built from FD declarations at
  `cobol_parser.py L388-395`) and only falls back to the naming heuristic;
  `REWRITE` (`L1465`) uses **only** `record_name.replace("-REC","-FILE")`.
  A record whose FD name does not follow the `-REC` convention binds to a
  wrong/nonexistent file name, and the mapper's REWRITE branch then emits a
  bare `// REWRITE ...` comment with **no diagnostic** (mapping
  `L2425-2484` path for an unresolved file) — the statement disappears from
  the generated program invisibly. Contradicts the WRITE path in the same
  parser (BL-038-class cross-lane inconsistency).
- **Severity:** medium-high for indexed/relative workloads that do not use
  the `-REC`/`-FILE` naming convention (common in real corpora).
- **Status:** **FIXED — 2026-10-14 (Phase 4 cycle B)**; defect-proven-first:
  the new focused file `tests/transformation/test_rewrite_binding.py`
  ran **2 failed / 3 passed** against the unmodified parser
  (`%TEMP%\opencode\phase4\bl070_pre_fix.txt`) — the convention-breaking
  record bound `IDX-DATA` (heuristic) while WRITE bound `IDX-FILE`
  (owner map) for the same FD. *Evidence-chain note:* the first capture
  of this file was mislabeled (it contained a post-fix all-green run);
  the genuine pre-fix red was regenerated on 2026-10-14 by temporarily
  reverting only the BL-070 hunk and re-running the focused file.
- **Found by:** Phase 4 audit + probe `%TEMP%\opencode\phase4\probe_p4_r1.py`
  (case REWRITE): an FD `FD IDX-FILE.` with record `01 IDX-DATA.` and
  `REWRITE IDX-DATA FROM WS-BUF.` binds `file_name="IDX-DATA"`-derived
  heuristic value while `_record_owner["IDX-DATA"] == "IDX-FILE"` exists
  unused; `_parse_write` for the same FD binds correctly. (An earlier audit
  claim that REWRITE is swapped with DELETE in the real path was **falsified**
  by the probe — the defect is the owner-map gap only.)
- **Expected behavior:** REWRITE resolves the owning file exactly like
  WRITE (owner map first, heuristic fallback), and an unresolvable record
  name produces an explicit diagnostic rather than a silent comment.
- **Root cause:** `_parse_rewrite` predates the `_record_owner` map added
  for WRITE; the two verbs were never unified.
- **Affected files:** `engine/transformation/cobol_parser.py`
  (`_parse_rewrite` vs `_parse_write`;
  `engine/transformation/cobol_to_java_mapping.py` REWRITE branch).
- **Impact:** REWRITE silently becomes a comment for non-conventionally
  named records; no capability or diagnostic channel sees it.
- **Remediation (done):** `_parse_rewrite` now consults `_record_owner`
  first and keeps the `-REC`→`-FILE` heuristic as the fallback for
  records no FD declares — exactly mirroring `_parse_write`.
- **Acceptance criteria:** met — REWRITE binds the FD-declared file for
  convention-breaking names and agrees with WRITE (5 focused tests:
  red 2/3 pre-fix → green 5/5 post-fix, incl. same-FD WRITE/REWRITE
  agreement and heuristic-fallback preservation); file-lane regression
  (`test_file_invalid_key_lane.py`, `test_file_semantics.py` +
  generator lanes) **104 passed** at fix time; parser-focused batch
  **27 passed** at evidence regeneration. No existing test weakened.
- **Owner/role:** parser / mapping maintainer. **Target phase:** Phase 4
  (cycle B — fixed 2026-10-14). **Dependency:** existing `_record_owner`
  map. **Residual risk:** a record that follows the `-REC` convention
  *and* is declared by an FD with a different name now binds the
  FD-declared file (owner map wins) — the FD declaration is authoritative,
  matching WRITE.

### BL-071 — JCL-generated Spring Boot project cannot compile in the canonical offline build environment while the adapter docstring claims "it compiles, starts"

- **Type:** defect (generation/build truth) + test gap.
- **Priority:** P1 — the JCL lane's own deliverable fails to build in the
  repository's canonical Maven environment and the code claims otherwise
  (doc-vs-reality contradiction, §76.6); no test ever attempted the build
  (missing end-to-end proof). Not P0: no false VERIFIED is reachable
  (the JCL lane can never reach PROVEN in the central gate).
- **Severity:** high (capability claim is false as shipped).
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P1, defect-
  proven-first).** Red evidence: static `1 failed, 2 passed` (precache +
  exclusion assertions) and Docker E2E `2 failed` (compile) in
  `%TEMP%\opencode\phase5\bl071_pre_fix.txt` (the file also contains two
  early test-harness iterations — wrong adapter input type, wrong fixture
  path — fixed before the product fix, noted for honesty); startup-half
  red regenerated by stripping the fix from the generated app:
  `bl071_startup_pre_fix.txt` (`compile success: True`, `exit_code: 1`,
  no step markers, `Failed to configure a DataSource … no embedded
  datasource could be configured`). Green: focused `5 passed`
  (`bl071_focused_green.txt`) — 3 static + Docker E2E compile
  (`success=True`, JAR produced) **and execute (`exit_code=0`, prints
  `[STEP01] …` per fixture job)**.
- **Found by:** Phase 5 audit probe `%TEMP%\opencode\phase5\probe_p5_compile.py`
  (PROBE16).
- **Observed behavior (verified by execution):** fixtures →
  `modernize_jcl_workload` → `jcl_to_spring_boot` → `SpringBootGenerator`
  → 7 files → `DockerSpringBootCandidateAdapter.compile` →
  **`success=False`**: `Cannot access central … in offline mode and the
  artifact org.springframework.boot:spring-boot-starter-batch:jar:3.2.5
  has not been downloaded from it before` (full Maven output:
  `%TEMP%\opencode\phase5\probe16_full_maven_error.txt`; run log
  `probe_p5_compile_out.txt`). `Dockerfile.maven-offline` L11 precached
  only `spring-boot-starter` — never `spring-boot-starter-batch`, which
  the JCL adapter declares (`jcl_spring_boot_adapter.py` L198-207).
  Remediation also uncovered and fixed the second half of the claim: even
  after compiling, the app exited 1 at startup because the batch starter's
  JDBC auto-configuration has no datasource URL in a structural profile
  (see `bl071_startup_pre_fix.txt`).
- **Expected behavior:** the generated project compiles in the canonical
  offline build environment, and any docstring claim about compiling /
  starting is backed by an executed test.
- **Root cause:** the offline-image precache pom was written for the
  COBOL lane's dependency set; the JCL lane's `spring-boot-starter-batch`
  was never added, and no test builds JCL output (`tests/test_jcl_generation.py`
  L8-9 explicitly does not). Startup additionally required excluding
  DataSource auto-configuration in the generated JCL app.
- **Affected files:** `Dockerfile.maven-offline` (precache pom + comment),
  `engine/transformation/spring_boot_ir.py` (additive
  `autoconfigure_excludes` field, default empty), 
  `engine/transformation/spring_boot_generator.py` (emit
  `spring.autoconfigure.exclude`), `engine/transformation/jcl_spring_boot_adapter.py`
  (sets the exclusion; docstrings now cite the test), new tests
  `tests/test_jcl_build_environment.py` (gate-wired static) +
  `tests/integration/test_jcl_spring_boot_compile.py` (Docker E2E).
- **Impact:** JCL modernization output is not buildable as shipped; the
  "it compiles, starts" claim is currently false; CI would never catch it.
- **Remediation (delivered):** `spring-boot-starter-batch` added to the
  offline precache; image rebuilt locally (`bl071_image_rebuild.txt`,
  digest `sha256:32139c85…`) with provenance regenerated via
  `scripts/record_docker_image_provenance.py` (CI rebuilds the image per
  run); generated JCL `application.properties` now excludes DataSource
  auto-configuration (structural profile, no JES/z/OS, no persistence —
  disclosed in code comments); static + Docker tests as above; docstring
  claim now cites the executed test.
- **Acceptance criteria:** PROBE16 rerun returns `success=True`; focused
  Docker test green locally (runs under `requires_docker`, i.e. in the CI
  Backend job which sets `RUN_DOCKER_TESTS=1` and rebuilds the image);
  docstring claim cites the test; no existing test weakened. **All met.**
- **Owner/role:** JCL lane maintainer + build/CI owner. **Target phase:**
  Phase 5 (batch P1). **Dependency:** `maven-offline-springboot` image
  rebuild. **Residual risk:** image digest changes → `test-artifacts`
  provenance churn (regenerated via `scripts/record_docker_image_provenance.py`,
  stays uncommitted by policy); local + CI images are built from the same
  Dockerfile so digests match by construction within a run.

### BL-072 — multiple JOB statements in one file are silently merged into one job (name of the first job lost, steps misattributed, status FULL, no diagnostic)

- **Type:** defect (JCL parsing / job-step attribution).
- **Priority:** P1 — silent structural misattribution of a workload
  (§54 silent-loss class in §22 dependency representation), contradicting
  the profile spec's explicit "no silent dropping"
  (`docs/specs/JCL_MODERNIZATION_PROFILE.md` L84-85). Not P0: the lane
  makes no execution claims and the central gate never passes JCL.
- **Severity:** high for multi-job members/jobstreams.
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P1, defect-
  proven-first).** Red `13 failed, 1 passed` (control only passing) in
  `%TEMP%\opencode\phase5\bl072_pre_fix.txt`; focused green `14 passed`
  (`bl072_focused_green.txt`); JCL regression green (299 passed across the
  JCL suites + `test_file_semantics.py`). No existing test pinned the
  merge; nothing weakened.
- **Found by:** probes 7/13 (`probe_p5_r1.py`, `probe_p5_r2.py`).
- **Observed behavior (verified by execution):** source with
  `//JOBONE JOB … / //S1 EXEC PGM=ONE / //JOBTWO JOB … / //S2 EXEC PGM=TWO`
  parses to **one** `JclJob` named `JOBTWO` holding **both** S1 and S2
  (`parse` returns a single job; `_parse_lines` reassigns `job_name` on
  the second JOB statement without resetting/flushing `steps`);
  profile status **FULL**, zero diagnostics.
- **Expected behavior:** one `JclJob` per JOB statement (job identity and
  step attribution preserved), or an explicit fail-closed diagnostic if
  multi-job members are unsupported.
- **Root cause:** `_parse_lines` was written for one job per file and
  never handles a second `JOB` statement.
- **Affected files:** `engine/transformation/jcl_parser.py`
  (`_parse_lines`, `parse`, `parse_application`), callers
  (`jcl_discovery.py`).
- **Impact:** wrong job graph and wrong Spring Batch job composition,
  reported as fully classified.
- **Remediation (delivered):** `JclParser.parse_jobs` returns one ordered
  `JclJob` per JOB statement (each JOB flushes the accumulated job);
  `parse` keeps its single-job contract by returning the first job;
  `parse_application` and `JclDiscovery.discover` consume the list
  (`dataclasses.replace` carries every field); the builder now scans each
  raw source **once** attributing lines to the JOB in effect, so
  multi-job members cannot duplicate or misattribute diagnostics (the
  old per-job `_raw_for_job` name-regex scan was removed as part of the
  restructure). Focused tests:
  `tests/transformation/test_jcl_multi_job_parsing.py` (gate-wired).
- **Acceptance criteria:** two-job file yields 2 jobs with correct step
  attribution and correct status/diagnostics; existing single-job tests
  unchanged and green; focused tests wired into the `ci.yml` gate.
  **Red/green met; gate wiring delivered with the batch commit.**
- **Owner/role:** JCL lane maintainer. **Target phase:** Phase 5 (batch
  P1). **Dependency:** none. **Residual risk:** none once split is
  explicit.

### BL-073 — job-level DD statements (JOBLIB etc.) are silently dropped from the IR with no diagnostic and never reach the dataset inventory

- **Type:** defect (JCL parsing / dataset dependency representation).
- **Priority:** P1 — a common, dependency-bearing construct vanishes with
  no diagnostic and status FULL, violating the spec's "never silently
  dropped" policy (`docs/specs/JCL_MODERNIZATION_PROFILE.md` L84-85) and
  §22's dependency-representation requirement. Same class as Phase 4's
  BL-041 (silently dropped statements, P1).
- **Severity:** high (JOBLIB is standard in production JCL).
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P1, defect-
  proven-first).** Red `9 failed, 3 passed` (controls) in
  `%TEMP%\opencode\phase5\bl073_pre_fix.txt`; focused green `12 passed`
  (`bl073_focused_green.txt`); JCL regression green (299). No test pinned
  the drop (none existed); nothing weakened.
- **Found by:** probes 8/15 (`probe_p5_r1.py`, `probe_p5_r2.py`).
- **Observed behavior (verified by execution):** `//JOBLIB DD DSN=USER.LOADLIB,DISP=SHR`
  before the first EXEC: parser `_parse_lines` hits the DD branch with
  `steps == []` and skips the line; no `JclDD` anywhere, no diagnostic
  (raw scan sees a recognized `DD` line and accepts it), status FULL,
  `USER.LOADLIB` absent from resources/inventory (`probe15`: resources =
  `[('INPUT', 'IN.DATA')]`).
- **Expected behavior:** job-level DDs are either represented (job-level
  resources/dependencies) or explicitly diagnosed as outside the
  supported subset — never silently discarded.
- **Root cause:** the parser only attaches DDs to the current/last step;
  the raw scanner classifies any `DD` line as recognized.
- **Affected files:** `engine/transformation/jcl_parser.py`
  (`_parse_lines` DD branch + job flush), IR `JclJob` (added additive
  field `job_dd_statements`, default empty),
  `engine/transformation/jcl_dependencies.py` (job-level `JCL_DD` edges),
  `engine/jcl/diagnostics.py` (new `JOB_LEVEL_DD` code),
  `engine/jcl/builder.py` (`_build_job` diagnoses job-level DDs from the
  IR), `engine/transformation/jcl_to_spring_batch.py`
  (`_UNSUPPORTED_CONSTRUCT_TEXT` entry → status-contract disclosure).
- **Impact:** dataset dependencies (steplib, job-message datasets) missing
  from the dependency graph and dataset inventory, under FULL status.
- **Remediation (delivered):** parser preserves job-level DDs on
  `JclJob.job_dd_statements` (additive, default-empty) and resets them on
  job flush (multi-job safe); `build_all_dependencies` emits `JCL_DD`
  edges (`source=<job>.<dd>`); the semantic builder diagnoses each
  job-level DD from the IR (new ERROR code `JOB_LEVEL_DD`) → status
  PARTIAL with `job-level DD statements` in the status contract.
  Diagnosis is IR-based rather than raw-scan-based so it survives even
  when the raw source is not in `raw_sources`. Focused tests:
  `tests/transformation/test_jcl_job_level_dd.py` (gate-wired).
- **Acceptance criteria:** probe8/probe15 shape yields the preserved DD +
  a diagnostic naming the job-level DD (status not FULL); JOBLIB dataset
  visible in the discovery dependency graph; focused tests green +
  gate-wired; no existing test weakened. **Red/green met; gate wiring
  delivered with the batch commit.**
- **Owner/role:** JCL lane maintainer. **Target phase:** Phase 5 (batch
  P1). **Dependency:** additive `ir.JclJob` field (mirrors prior additive
  IR changes). **Residual risk:** job-level DDs remain unmodeled in the
  Spring Batch representation (diagnosed, disclosed).

### BL-074 — `link_with_cobol` matches datasets to COBOL files by loose bidirectional substring and a file-name-keyed dict, producing phantom, wrong-target, and missing `COBOL_FILE` edges in the production ingestion graph with no ambiguity signal

- **Type:** defect (dependency graph truth; production ingestion path).
- **Priority:** P1 — wrong edges reach `api/ingestion.py` L265-272
  (production dependency graph) silently; the Phase 3 phantom-dependency
  class (BL-034, P1) in the JCL↔COBOL linker. Not P0: graph-display and
  planning input, not a verdict/certification bypass.
- **Severity:** high.
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P1, defect-
  proven-first).** Red `6 failed, 3 passed` (controls) in
  `%TEMP%\opencode\phase5\bl074_pre_fix.txt`; focused green `9 passed`
  (`bl074_focused_green.txt`); regression green (299, including
  `test_file_semantics.py`'s linking test). Existing linker tests
  (`test_jcl_parser.py` L451-479: exact match, unresolved program) pass
  unchanged; nothing weakened.
- **Found by:** probe 10 (`probe_p5_r1.py`).
- **Observed behavior (verified by execution):** DSN `ORDER.INPUT` vs
  COBOL file `DER.INPUT` → linked (substring), even for an unrelated
  program; `file_lookup[fd.file_name] = …` keeps only the **last**
  program for a shared file name, so in probe10 the executed program
  PROG1's edge was overwritten by unrelated PROG2
  (`COBOL_FILE_links=[('LINKJOB.STEP01.INPUT', 'PROG2.DER.INPUT', …)]`);
  >1 match would append duplicate edges; no ambiguity is ever reported
  (no diagnostic channel).
- **Expected behavior:** deterministic, precise matching (dataset name or
  a dot-qualified dataset qualifier equals the COBOL file name,
  case-insensitive); **all** matching programs represented; ambiguous
  matches flagged in edge metadata; no substring phantoms.
- **Root cause:** convenience substring check plus a dict keyed by file
  name that silently overwrites co-readers.
- **Affected files:** `engine/transformation/jcl_discovery.py`
  (`link_with_cobol` L129-161), consumed by `api/ingestion.py`.
- **Impact:** phantom and wrong-target file edges, silently dropped
  co-reader programs, no ambiguity signal in the customer-facing graph.
- **Remediation (delivered):** `_dataset_matches_file` — precise
  case-insensitive match (`dsn == file` or `dsn ends with ".<file>"`,
  qualified tail; fragments never match; empty file names skipped);
  `file_lookup` accumulates **all** programs declaring a file name; every
  matching program gets an edge with `resolution=RESOLVED|AMBIGUOUS` in
  metadata (`dsn=…;resolution=…`). Focused tests:
  `tests/transformation/test_jcl_cobol_file_linking.py` (gate-wired).
- **Acceptance criteria:** probe10 shape yields no phantom edge for
  `DER.INPUT`, and a real match (`DSN=PAY.INPUT` ↔ file `INPUT`) yields
  one edge per matching program with ambiguity flagged; ingestion graph
  tests green; no existing test weakened. **Red/green met; gate wiring
  delivered with the batch commit.**
- **Owner/role:** JCL/discovery maintainer. **Target phase:** Phase 5
  (batch P1). **Dependency:** none. **Residual risk:** legitimate
  DSN↔file relations that rely on true substring nicknames will no longer
  link — they must be represented by exact/qualifier names (fail-closed
  under-linking rather than phantom over-linking).

### BL-075 — compound `DISP=`/`SPACE=` values are silently truncated by a paren-unaware comma split (`DISP=(NEW,CATLG,DELETE)` stored as `"(NEW"`)

- **Type:** defect (DD parameter fidelity) + weak-assertion test gap.
- **Priority:** P2 — raw DD contract text is corrupted in the IR and the
  Spring Batch representation with no diagnostic, but the disposition
  *direction* (INPUT/OUTPUT) survives (first sub-parameter drives it), no
  execution claim rests on it, and the central gate is unaffected.
- **Severity:** medium (dataset lifecycle detail — CATLG/DELETE/PASS —
  silently lost).
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P2, defect-
  proven-first).** Red evidence: `5 failed, 3 passed` in
  `%TEMP%\opencode\phase5\bl075_pre_fix.txt` (the file also records two
  early test-harness fixes — wrong IR accessor names — before the product
  red, noted for honesty). Green: focused `82 passed`
  (`bl075_focused_green.txt`: 8 fidelity tests + the full parser suite
  including the strengthened full-value assertion).
- **Found by:** probe 6 (`probe_p5_r1.py`).
- **Observed behavior (verified by execution):** `_parse_dd` splits with
  a quote-aware but paren-unaware regex, so
  `DISP=(NEW,CATLG,DELETE),SPACE=(TRK,(10,5))` yields
  `disposition='(NEW'`, `space='(TRK'`; the truncated text propagates
  `JclDD` → `JclResource` → `SpringBatchResource.disposition`; status
  FULL, no diagnostic. `tests/transformation/test_jcl_parser.py` L340's
  `assert "NEW" in new_dd.disposition` is too weak to notice.
- **Expected behavior:** compound DISP/SPACE values preserved verbatim
  (paren-depth-aware split, as `_parse_parameters` already does for
  JOB/EXEC); strong assertion pinning the full text.
- **Root cause:** `_parse_dd` predates the paren-aware splitter used by
  `_parse_parameters`; the test only substring-checks.
- **Affected files:** `engine/transformation/jcl_parser.py` (`_parse_dd`),
  `tests/transformation/test_jcl_parser.py` (strengthen L340-class
  assertions — documented strengthening, not a weakening).
- **Impact:** mangled disposition/space text in artifacts and profiles;
  lifecycle sub-parameters (CATLG/DELETE/PASS/KEEP) unrecoverable
  downstream.
- **Remediation (delivered):** shared `_split_parameters` static method
  (paren-depth + quote aware) now used by both `_parse_dd` and
  `_parse_parameters` (`engine/transformation/jcl_parser.py`); new focused
  suite `tests/transformation/test_jcl_dd_parameter_fidelity.py` (verbatim
  `JclDD` and `SpringBatchResource` values, boundary and negative cases,
  gate-wired); the weak `test_compound_and_simple_disp_values_parse_in_full`
  (renamed from `test_parse_disp`) assertion now pins the exact
  `"(NEW,CATLG,DELETE)"` text.  SPACE/UNIT/VOL/DCB remain preserved on
  `JclDD` but not modeled in the semantic resource (documented subset
  limitation, unchanged).
- **Acceptance criteria:** probe6 rerun shows full verbatim values in
  `JclDD` and `SpringBatchResource`; focused tests green + gate-wired;
  existing compound-disposition tests strengthened, none weakened.
- **Owner/role:** JCL parser maintainer. **Target phase:** Phase 5 (batch
  P2). **Dependency:** none. **Residual risk:** non-parenthesized exotic
  DISP forms remain bounded to the documented subset.

### BL-076 — application-graph step-order edges diverge between lanes: `build_all_dependencies` omits the edge after a COND step while the semantic builder emits it

- **Type:** defect (lane divergence / dependency graph completeness).
- **Priority:** P2 — a missing (not wrong) edge in one of two product
  surfaces; no false claim, verdict unaffected; Phase 3's lane-divergence
  class (BL-036/BL-038, P2) applied to JCL.
- **Severity:** medium.
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P2, defect-
  proven-first).** Red evidence: `3 failed, 3 passed` in
  `%TEMP%\opencode\phase5\bl076_pre_fix.txt` (COND edge missing, cond
  metadata missing, lane parity; both controls green — one harness
  expectation was corrected before capture: plain order edges carry
  `job=…` metadata, noted for honesty).  The vacuous
  `test_conditional_step_no_order_dependency` (asserted `len==0` against a
  hand-built `JclApplication` with no dependencies at all) was
  strengthened to `test_conditional_step_keeps_its_order_edge_with_cond_metadata`
  (parses via `parse_application`, pins the edge + `job=…;cond=(0,NE)`
  metadata) and went red pre-fix with the same run.  Green: focused
  `193 passed` (`bl076_focused_green.txt`: new parity suite + parser +
  semantic + fixtures + consumer + generation + spring-batch suites).
- **Found by:** probe 9 (`probe_p5_r1.py`).
- **Observed behavior (verified by execution):** for `S1 / S2(COND=EVEN) / S3`,
  `build_all_dependencies` returns `JCL_STEP_ORDER` edges
  `[('S1','S2')]` — **S2→S3 missing** (the loop skips the pair when
  `current.condition is not None`) — while
  `JclSemanticBuilder._build_step_dependencies` returns
  `[('','S1'), ('S1','S2','ANY'), ('S2','S3','SUCCESS')]`.
  `api/ingestion.py` publishes the former.
- **Expected behavior:** both lanes carry every step-order pair; the
  condition belongs in edge metadata, not as a reason to drop the edge.
- **Root cause:** `jcl_dependencies.py` L24 conditions edge emission on
  `current.condition is None`.
- **Affected files:** `engine/transformation/jcl_dependencies.py` L19-30,
  consumed by `jcl_parser.parse_application` / `jcl_discovery.discover`
  → `api/ingestion.py`.
- **Impact:** ingestion dependency graph silently missing edges after
  COND steps; the two lanes disagree.
- **Remediation (delivered):** `build_all_dependencies` now emits every
  consecutive step-order pair; when the current step carries a condition
  the metadata becomes `job=…;cond=<code>` (BL-076); new focused suite
  `tests/transformation/test_jcl_step_order_parity.py` (COND edge present,
  cond metadata, application↔semantic lane parity, linear + single-step
  controls; gate-wired).
- **Acceptance criteria:** probe9 shape shows S2→S3 present with
  condition metadata and both lanes agree; existing dependency tests
  green (expectations updated only where they pin the wrong absence,
  documented as strengthening).
- **Owner/role:** JCL dependency maintainer. **Target phase:** Phase 5
  (batch P2). **Dependency:** none. **Residual risk:** none.

### BL-077 — JCL lane hygiene: dead/never-set fields and stale spec status

- **Type:** documentation + code hygiene (P3).
- **Priority:** P3 — no behavior or trust impact; kept visible so it is
  not silently forgotten (§77).
- **Severity:** low.
- **Status:** **FIXED — in-cycle 2026-10-15 (Phase 5 batch P2, hygiene
  with regression pins).** Red evidence: `4 failed, 1 passed` in
  `%TEMP%\opencode\phase5\bl077_pre_fix.txt` — one absence-pin per dead
  construct (all four existed pre-fix), the fifth test is a control
  proving the live inline-`SYSIN DD *` branch survives the removals.
  Green: focused `5 passed` (`test_jcl_lane_hygiene.py`, gate-wired).
  "ruff clean" is **inapplicable** — this repository has no ruff
  configuration and no lint job (noted in change-log (x)); the hygiene
  bar is pytest green + `py_compile` clean, both met.
- **Found by:** Phase 5 §76.6 documentation-consistency audit.
- **Observed behavior (static):** (a) `JclDD.sysin` is never set by the
  parser, so `jcl/builder.py` L199's `dd.name.upper() == "SYSIN" and
  dd.sysin` is dead (always False; `DD *` is already covered by
  `is_inline`); (b) `JclParseError` is declared but never raised;
  (c) `JclDatasetFlow.disposition` is never populated by the builder;
  (d) `capability_analyzer.py` L74's comment lists a `"JCL"` component
  type that is never emitted; (e) `docs/specs/JCL_INTEGRATION_CONTRACT.md`
  still says "no `api/` wiring applied" although `api/service.py` and
  `api/ingestion.py` now consume the lane, and its example keys sources
  by basename (the BL-063 collision source); (f)
  `docs/COBOL_UNIVERSALITY_ROADMAP.md` L132's "JCL SUPPORTED (parser +
  diagnostics)" label overstates until BL-072/BL-073 silent drops close.
- **Expected behavior:** no dead conditions or unused exceptions left
  unexplained; spec status matches repository reality (§78).
- **Affected files:** `engine/jcl/builder.py`, `engine/transformation/jcl_parser.py`,
  `engine/jcl/model.py`, `engine/modernization/capability_analyzer.py`,
  `docs/specs/JCL_INTEGRATION_CONTRACT.md`, `docs/COBOL_UNIVERSALITY_ROADMAP.md`.
- **Impact:** reader confusion; latent drift.
- **Remediation (delivered):** (a) `JclDD.sysin` field removed from
  `engine/transformation/ir.py` and the dead builder clause collapsed to
  `dd.is_inline` (`engine/jcl/builder.py`); (b) never-raised
  `JclParseError` removed from `jcl_parser.py` (the parser's fail-soft
  contract is unchanged and now the only contract); (c)
  `JclDatasetFlow.disposition` removed from `engine/jcl/model.py`, along
  with the zero-caller no-op `JclSemanticModel.unsupported_jobs` stub;
  (d) `capability_analyzer.py` component-type comment corrected to the
  four emitted values (`PROGRAM`/`COPYBOOK`/`CALL`/`FILE`) with the
  JCL-is-ledger-only rationale inline; (e)
  `docs/specs/JCL_INTEGRATION_CONTRACT.md` header status now says
  implemented (PARTIAL-capped), the sourcing example uses
  `find_jcl_members` with member-relative path keys (never basenames),
  the entry-point signature documents `pre_diagnostics`, and the tail
  Status section reflects the live `jcl_consumer`/`api` wiring; (f)
  `docs/COBOL_UNIVERSALITY_ROADMAP.md` L132 relabeled
  "SUPPORTED subset (bounded construct set + explicit diagnostics;
  PARTIAL-capped by construction)" after BL-072/BL-073 landed.
  Every removal is pinned by an absence test in
  `tests/test_jcl_lane_hygiene.py` so the dead construct cannot silently
  return.
- **Acceptance criteria:** each lettered item either fixed or explicitly
  justified in-place; JCL suites green (ruff inapplicable — no lint
  config/job in this repository, per change-log (x)).
- **Owner/role:** JCL lane maintainer. **Target phase:** Phase 5 (batch
  P2/P3). **Dependency:** BL-072/BL-073 for item (f). **Residual risk:**
  none.

### BL-081 — INNER/OUTER JOIN tables and ON conditions are silently lost though `SqlSelect.joins` exists to represent them

- **Type:** defect (silent semantic loss inside representable IR).
- **Priority:** P2 — table `T2` in `FROM T1 INNER JOIN T2 ON …` never
  reaches `from_tables`/`joins`, so the database-dependency graph omits
  the joined table while the SELECT list still references its columns
  (`B.NAME`) — an internally inconsistent model.
- **Severity:** medium (under-reported dependencies, no fabrication).
- **Status:** **FIXED — VERIFIED 2026-10-15 (Phase 6 batch P2)**;
  behaviorally verified by audit probe I; red
  `bl081_pre_fix.txt` (`4 failed, 1 passed` — non-join control green)
  + `bl081_deps_pre_fix.txt` (dependency door, `1 failed`), focused
  green `bl081_focused_green.txt` (6 passed).
- **Found by:** Phase 6 audit probe I
  (`%TEMP%\opencode\phase6\audit_probes.txt`).
- **Observed behavior (verified):** `SELECT A.ID, B.NAME FROM T1 A INNER
  JOIN T2 B ON A.ID = B.ID WHERE A.ID = 1` → `from_tables == [T1 A]`
  only; `T2` and the ON condition vanish (`_parse_select` cuts the table
  text at the JOIN keyword and never parses the rest; `joins` stays
  empty).
- **Expected behavior:** joined tables parsed into `SqlSelect.joins` with
  their join type, alias and ON predicate; analyzer table usages include
  joined tables and ON-condition read columns.
- **Root cause:** `_parse_select` predates the `joins` IR field; table
  text is truncated at the first JOIN.
- **Affected files:** `engine/transformation/sql_parser.py`
  (`_parse_select`), `engine/sql/analyzer.py`
  (`statement_table_usages`, `_collect_select_read_columns`).
- **Impact:** missing table entries in the dependency truth for any join
  query; silent by construction.
- **Remediation (planned):** parse `[INNER|LEFT|RIGHT|FULL [OUTER]] JOIN`
  segments after the first table; ON condition parsed with the fixed
  predicate parser (BL-078/BL-079); analyzer reads joined-table columns.
- **Acceptance criteria:** red test captured pre-fix; focused suite green;
  non-join SELECTs unchanged.
- **Owner/role:** SQL parser + analyzer maintainer. **Target phase:**
  Phase 6 (batch P2). **Dependency:** BL-078/BL-079 (ON condition parsing
  fidelity). **Residual risk:** CROSS JOIN and comma-form multi-table
  remain documented subset (comma form already lands in `from_tables`).

### BL-082 — ORDER BY column names swallow trailing `FETCH FIRST n ROWS ONLY` text

- **Type:** defect (text bleed into semantic names).
- **Priority:** P2 — model-only pollution; execution uses raw SQL so
  behavior on the controlled database is unaffected.
- **Severity:** low-medium (wrong column name in the semantic model).
- **Status:** **FIXED — VERIFIED 2026-10-15 (Phase 6 batch P2)**;
  behaviorally verified (audit probe J); red `bl082_pre_fix.txt`
  (`1 failed, 2 passed` — both controls green), focused green
  `bl082_focused_green.txt` (3 passed).
- **Found by:** Phase 6 audit probe J
  (`%TEMP%\opencode\phase6\audit_probes.txt`).
- **Observed behavior (verified):** `SELECT … ORDER BY ACCT DESC FETCH
  FIRST 5 ROWS ONLY` → `order_by[0].column.column_name == 'ACCT FETCH
  FIRST 5 ROWS ONLY'` (`_parse_select` slices ORDER BY text to end of
  statement; `_parse_order_by` then treats the residue as one column).
- **Expected behavior:** ORDER BY text ends at `FETCH FIRST` (or any
  trailing clause); one clean column per item.
- **Root cause:** unbounded `sql_text[order_start:]` slice.
- **Affected files:** `engine/transformation/sql_parser.py`
  (`_parse_select` ORDER BY branch).
- **Impact:** wrong column identifiers in the semantic model; wrong
  ordering truth for future generation.
- **Remediation (planned):** bound the ORDER BY slice at FETCH FIRST
  (offset search on the uppercased copy, original-text slicing per
  BL-078); focused tests for ASC/DESC + FETCH FIRST combinations.
- **Acceptance criteria:** red test captured pre-fix; focused suite green.
- **Owner/role:** SQL parser maintainer. **Target phase:** Phase 6 (batch
  P2). **Dependency:** none. **Residual risk:** none.

### BL-083 — the SQL lane never reaches the platform ledger: `DependencyKind.DB2` is produced by no product code and `sqlcode_field` has no consumer

- **Type:** gap (integration/disclosure), not silent corruption.
- **Priority:** P2 — documented honestly today (`integrated_proof.py`
  claims only "parsed and classified" for DB2), but §24's "database
  dependencies" surface stops at the lane boundary: table dependencies
  extracted by `extract_table_dependencies` / `Db2SqlModel` never enter
  the integrated proof, the API, or the modernization ledger, and the
  SQLCA field names stored on the model are never consumed.
- **Severity:** medium (capability truth incomplete at platform level).
- **Status:** **DISCLOSED — 2026-10-15 (Phase 6 audit); roadmap P3-7
  disclosure added with the batch-P2 docs**; register row present;
  Phase 6 verdict limitations to be written at completion; deferred to
  Phase 10 by design decision.
- **Found by:** Phase 6 audit probe K + repository grep
  (`%TEMP%\opencode\phase6\audit_probes.txt`).
- **Observed behavior (verified):** `DependencyKind.DB2` appears only in
  the enum and one negative test; no producer exists; `sqlcode_field` is
  written by the analyzer/extractor and read by nothing in `engine/` or
  `api/`.
- **Expected behavior:** either (a) a product producer feeds classified
  DB2 dependencies into the integrated proof (ledger-visible), or (b) the
  gap stays explicitly disclosed in the register/roadmap with a target
  phase — no doc may imply the platform sees DB2 dependencies.
- **Root cause:** lane-first build order; platform wiring deferred and
  never scheduled.
- **Affected files:** `engine/modernization/integrated_proof.py`,
  `api/service.py`, `engine/sql/model.py`.
- **Impact:** platform-level dependency inventory silently excludes DB2
  tables (the lane-level truth is correct).
- **Remediation (planned):** register/disclosure now; producer wiring is
  an integration-lane decision (evidence/integrated-proof phase) — no
  half-wiring in Phase 6.
- **Acceptance criteria:** disclosure present in register + roadmap +
  Phase 6 verdict limitations; no documentation overstates platform
  visibility.
- **Owner/role:** platform integration owner. **Target phase:**
  Phase 10 (evidence / integrated proof) — deferred by design decision,
  disclosed. **Dependency:** none. **Residual risk:** disclosed.

### BL-084 — IMS (`EXEC DLI`) is never detected or classified: no source pattern, no registry key (roadmap Rung 0)

- **Type:** gap (missing capability / detection), not a wrong verdict.
- **Priority:** P2 — Master README §28 requires IMS to be classified
  explicitly and forbids unknown IMS constructs from silently passing
  through the system. The program already fails closed today through
  generic per-line `unparsed_statement` diagnostics (verified by probe),
  so no false `SUPPORTED` verdict is reachable; what is missing is the
  *classification itself* — nothing in the platform says "IMS".
- **Severity:** medium (capability/classification coverage gap; no wrong
  value and no false verdict).
- **Status:** **FIXED — 2026-10-15 (Phase 7 batch 1).** Discovered OPEN
  by the Phase 7 audit-first probe
  (`%TEMP%\opencode\phase7\audit_probe_phase7.py`) before any source
  change; red-first evidence in
  `%TEMP%\opencode\phase7\bl084_bl085_pre_fix.txt` (5 failed / 9 passed —
  every positive red, every negative already green). After the fix:
  focused gate `tests/test_ims_mq_detection.py` **14 passed**; bare-venv
  capability-truth gate **649 passed** (635 baseline + 14) verified
  BEFORE wiring and again after wiring (gate now 46 files);
  reconciliation set (`test_silent_loss_registry.py` + registry/structural
  capability) **50 passed**; full serialized JDK sweep **139 failed /
  3441 passed / 96 skipped / 27 errors** with failure identities
  identical to the pre-fix baseline (NEW_ONLY=0, GONE=0 — the 139 are the
  known Docker-gated set).
  Later sweeps read 140 failed solely because of the pre-existing
  `tests/test_certification_contract.py::TestContractReachesEngine`
  timing flake (control-proven with this batch reverted — change-log
  (ag) disclosure); all other identities remain NEW_ONLY=0/GONE=0.
- **Found by:** Phase 7 §76 audit (Master README §26–§29 scope), CICS/MQ/
  IMS/external-dependency inventory.
- **Observed behavior (verified):** `EXEC DLI … END-EXEC` in PROCEDURE
  DIVISION yields only generic per-line `unparsed_statement` diagnostics;
  `scan_constructs` does not contain `EXEC DLI` (`CONSTRUCT_REGISTRY` has
  no key, `_SOURCE_PATTERNS` has no pattern); capability reasons never
  name IMS; roadmap rows record `IMS = UNKNOWN (no detection patterns
  found)` (Rung 0).
- **Expected behavior:** roadmap **P3-4** (Rung 0→1→2): source pattern +
  registry key + blocked verdict + negatives, no runtime — the capability
  verdict for an `EXEC DLI` program names `EXEC DLI` and stays
  `UNSUPPORTED`; detection never fires on comment or string-literal text.
- **Root cause:** the deterministic lane was built construct-by-construct
  for the certified subset; IMS was never given a detection pattern.
- **Affected files:** `engine/transformation/semantic_capability.py`,
  `docs/SEMANTIC_PROOF_MATRIX.md`, `docs/CAPABILITY_MATRIX.md`,
  `docs/COBOL_UNIVERSALITY_ROADMAP.md`.
- **Impact:** an IMS application is rejected with a generic reason; IMS
  is invisible to classification and to any downstream dependency
  reporting.
- **Remediation (planned):** registry key `EXEC DLI` (UNSUPPORTED) +
  `_SOURCE_PATTERNS` entry + matrix/roadmap rows; no IR, no mapper, no
  runtime lane, no equivalence claim.
- **Acceptance criteria / tests:** gate-wired focused tests prove
  (1) detection fires for a real `EXEC DLI` statement and not for a
  control program, comment text or string-literal text; (2) registry
  `level` and `effective_source_level` are `UNSUPPORTED`; (3) the
  analyzer's PROGRAM reason names `EXEC DLI` and the verdict is never
  `SUPPORTED`; (4) repeated scans are identical (deterministic); (5) the
  existing fail-closed `unparsed_statement` diagnostics remain; no
  existing test weakened or skipped.
- **Owner/role:** capability/registry maintainer. **Target phase:**
  Phase 7 (CICS / MQ / IMS / external dependencies). **Dependency:** none.
  **Residual risk:** detection + classification only — no IMS DB/TM data
  or transaction semantics, no PCB/segment dependency edges (roadmap
  P3-6 edge vocabulary stays future work).

### BL-085 — IBM MQ (`EXEC MQI`) is never detected or classified: no source pattern, no registry key (roadmap Rung 0)

- **Type:** gap (missing capability / detection), not a wrong verdict.
- **Priority:** P2 — Master README §27 requires MQ modernization to
  support queue discovery and message semantics; nothing is detected
  today, so an MQ application is rejected for the wrong (generic)
  reason. No false `SUPPORTED` verdict is reachable (probe-verified:
  generic `unparsed_statement` diagnostics already fail the program
  closed).
- **Severity:** medium (capability/classification coverage gap; no wrong
  value and no false verdict).
- **Status:** **FIXED — 2026-10-15 (Phase 7 batch 1).** Discovered OPEN
  by the Phase 7 audit-first probe
  (`%TEMP%\opencode\phase7\audit_probe_phase7.py`) before any source
  change; red-first evidence in
  `%TEMP%\opencode\phase7\bl084_bl085_pre_fix.txt` (5 failed / 9 passed).
  After the fix: focused gate `tests/test_ims_mq_detection.py`
  **14 passed**; bare-venv capability-truth gate **649 passed** (635
  baseline + 14) verified BEFORE wiring and again after wiring (gate now
  46 files); reconciliation set **50 passed**; full serialized JDK sweep
  **139 failed / 3441 passed / 96 skipped / 27 errors** with failure
  identities identical to the pre-fix baseline (NEW_ONLY=0, GONE=0 — the
  139 are the known Docker-gated set).
  Later sweeps read 140 failed solely because of the pre-existing
  `tests/test_certification_contract.py::TestContractReachesEngine`
  timing flake (control-proven with this batch reverted — change-log
  (ag) disclosure); all other identities remain NEW_ONLY=0/GONE=0.
- **Found by:** Phase 7 §76 audit (Master README §27 scope).
- **Observed behavior (verified):** `EXEC MQI … END-EXEC` yields only
  generic per-line `unparsed_statement` diagnostics; `scan_constructs`
  does not contain `EXEC MQI`; capability reasons never name MQ; roadmap
  rows record `MQ = UNKNOWN (no detection patterns found)` (Rung 0);
  queue names (`Q(…)`/`QUEUE(…)`) are not extracted as dependencies.
- **Expected behavior:** roadmap **P3-4** (Rung 0→1→2): source pattern +
  registry key + blocked verdict + negatives, no runtime — the capability
  verdict names `EXEC MQI` and stays `UNSUPPORTED`; detection never fires
  on comment or string-literal text.
- **Root cause:** same lane-first build order; MQ was never given a
  detection pattern.
- **Affected files:** `engine/transformation/semantic_capability.py`,
  `docs/SEMANTIC_PROOF_MATRIX.md`, `docs/CAPABILITY_MATRIX.md`,
  `docs/COBOL_UNIVERSALITY_ROADMAP.md`.
- **Impact:** MQ applications are invisible to classification; queue
  dependencies are invisible to the dependency graph.
- **Remediation (planned):** registry key `EXEC MQI` (UNSUPPORTED) +
  `_SOURCE_PATTERNS` entry + matrix/roadmap rows; no IR, no mapper, no
  runtime lane, no message-semantics claim.
- **Acceptance criteria / tests:** gate-wired focused tests prove
  (1) detection fires for a real `EXEC MQI` statement and not for a
  control program, comment text or string-literal text; (2) registry
  `level` and `effective_source_level` are `UNSUPPORTED`; (3) the
  analyzer's PROGRAM reason names `EXEC MQI` and the verdict is never
  `SUPPORTED`; (4) repeated scans are identical; (5) the existing
  fail-closed diagnostics remain; no existing test weakened or skipped.
- **Owner/role:** capability/registry maintainer. **Target phase:**
  Phase 7 (CICS / MQ / IMS / external dependencies). **Dependency:** none.
  **Residual risk:** detection + classification only — queue discovery,
  message format, correlation, retry and dead-letter semantics remain
  future work (Master README §27 items not yet modeled).

### BL-086 — external utilities / system services / VSAM specifics are Rung 0: no source patterns, no registry keys (roadmap P3-5; Master README §29)

- **Type:** gap (universality detection; conservative direction).
- **Priority:** P2 — programs using these constructs pass the scan
  without any construct-specific classification (they still fail closed
  overall via BL-003 UNKNOWN wiring, so no false SUPPORTED is reachable),
  but §29's ladder (`Detected → Classified → …`) never starts and the
  verdict reason never names the construct.
- **Severity:** medium (universality visibility).
- **Status:** **FIXED — 2026-10-15 (Phase 7 batch 3).** Discovered OPEN
  by the audit-first batch-3 review before any source change; red-first
  evidence in
  `%TEMP%\opencode\phase7\batch3_red_tests.txt` (8 failed / 7 passed on
  the focused file, all eight failures the undetected keys).  After the
  fix: focused gate `tests/test_utilities_vsam_detection.py`
  **15 passed**; matrix-parity suites `test_silent_loss_registry` +
  `test_usage_capability` **37 passed** after the SEMANTIC_PROOF_MATRIX
  rows landed; bare-venv capability-truth gate **685 passed** at 49
  files (656 + 15 + 14) verified BEFORE wiring and again after wiring
  the two new files into `ci.yml`.  Classification only — no IR, no
  mapper, no VSAM or utility runtime, no equivalence claim.
- **Found by:** roadmap Rung-0 list (COBOL_UNIVERSALITY_ROADMAP §11:
  "utilities, system services, VSAM specifics") + Phase 7 registry
  inventory (`RELEASE`, `IDCAMS`, `ORGANIZATION INDEXED/RELATIVE`,
  `ACCESS DYNAMIC`, `RECORD KEY` absent from `_SOURCE_PATTERNS` /
  `CONSTRUCT_REGISTRY` while §9 already lists DYNAMIC access and
  file-based SORT as blocked concepts).
- **Observed behavior (static, pre-change):** `scan_constructs` never
  reports these constructs; CAPABILITY_MATRIX rows read
  "UNKNOWN (no detection patterns)" for Utilities/system services and
  "UNKNOWN (no VSAM parse path…)" for VSAM specifics.
- **Expected behavior:** roadmap **P3-5** (detection-first, no runtime):
  source patterns + registry keys classified `UNSUPPORTED` at both
  levels, verdict reasons naming the construct, negatives for comment /
  string-literal / word-boundary cases; no IR, no mapper, no VSAM
  runtime, no equivalence claim.
- **Root cause:** lane-first build order; these constructs never received
  detection patterns.
- **Affected files:** `engine/transformation/semantic_capability.py`,
  `docs/SEMANTIC_PROOF_MATRIX.md`, `docs/CAPABILITY_MATRIX.md`,
  `docs/COBOL_UNIVERSALITY_ROADMAP.md`.
- **Impact:** §29 dependencies (utilities, system services, VSAM) stay
  invisible to classification.
- **Remediation (planned):** `_SOURCE_PATTERNS` + `CONSTRUCT_REGISTRY`
  keys for `RELEASE` (SORT-family utility I/O), `IDCAMS` (named
  external utility), `ORGANIZATION INDEXED`, `ORGANIZATION RELATIVE`,
  `ACCESS DYNAMIC`, `RECORD KEY` (VSAM specifics), each `_unsupported`;
  matrix/roadmap rows updated; focused gate tests red→green.
- **Acceptance criteria / tests:** gate-wired focused tests prove
  detection fires only on real statements/phrases (comment and
  string-literal text never detect; word boundaries hold), registry
  levels `UNSUPPORTED`, analyzer reason names the construct, plans stay
  BLOCKED, existing fail-closed diagnostics retained; no existing test
  weakened.
- **Owner/role:** capability/registry maintainer. **Target phase:**
  Phase 7 (in-cycle). **Dependency:** none. **Residual risk:** phrase
  coverage stays a documented subset (detection-first bound).

### BL-087 — MQ queue names and IMS PCB/segment references never reach the platform dependency ledger (`extra_dependencies` has no producer)

- **Type:** gap (integration/dependency visibility; conservative
  direction).
- **Priority:** P2 — the ledger mechanism exists
  (`integrated_proof.build_dependency_ledger(extra_dependencies=…)` and
  `DependencyKind.CICS/DB2` were reserved for exactly this) but nothing
  produces MQ queue-name or IMS PCB/segment entries, so an application
  that references external queues/PCBs reports a dependency inventory
  that omits them (roadmap P3-6 explicitly deferred "queue-name
  dependency edges and PCB/segment edges" out of P3-4).
- **Severity:** medium (platform-level inventory incomplete; central
  status cannot account for MQ/IMS dependencies).
- **Status:** **FIXED — 2026-10-15 (Phase 7 batch 3).** Discovered OPEN
  by the audit-first batch-3 review before any source change; red-first
  evidence in
  `%TEMP%\opencode\phase7\batch3_red_tests.txt` (`ModuleNotFoundError`
  for `engine.modernization.external_dependency_edges`, the BL-060
  precedent: the test file exists and fails red on the missing module).
  After the fix: focused gate `tests/test_external_dependency_edges.py`
  **14 passed** (positives, ledger-entry shape, comment/literal/no-block
  negatives, dedup, determinism, ledger integration keeping central
  status fail-closed); API wiring verified through
  `_persist_integrated_proof` → `_proof_payload(extra_dependencies=…)`;
  bare-venv gate **685 passed** at 49 files.  Ledger visibility and
  fail-closed classification only — no MQ or IMS runtime, no
  message-semantics claim.
- **Found by:** Phase 7 continuation review of `integrated_proof.py`
  (extra_dependencies parameter documented for JCL/DB2/CICS lanes, zero
  producers in `engine/`/`api/`) + roadmap P3-6 line ("queue-name
  dependency edges and PCB/segment edges stay future work").
- **Observed behavior (static, pre-change):** no MQ/IMS ledger entries
  exist in any code path; `api.service._proof_payload` calls
  `build_dependency_ledger` without `extra_dependencies`.
- **Expected behavior:** roadmap **P3-6**: queue-name and PCB/segment
  references extracted from real `EXEC MQI` / `EXEC DLI` blocks (never
  comment or string-literal text) become `visible` ledger entries
  classified `UNSUPPORTED` with proof state `BLOCKED` (no MQ/IMS runtime
  lane exists — same structural truth as the JCL lane), deduplicated and
  deterministic; central status accounts for them fail-closed.
- **Root cause:** mechanism-first build order; producers were never
  scheduled.
- **Affected files:** new
  `engine/modernization/external_dependency_edges.py`,
  `engine/modernization/integrated_proof.py` (`DependencyKind` additions),
  `api/service.py` (`_proof_payload` wiring), docs.
- **Impact:** platform dependency inventory silently excludes MQ queues
  and IMS PCBs/segments.
- **Remediation (planned):** extractor module + `DependencyKind.MQ` /
  `DependencyKind.IMS` + API wiring; focused gate tests red→green; docs
  rows.
- **Acceptance criteria / tests:** extraction fires only inside real
  `EXEC MQI` / `EXEC DLI` blocks (comment/literal negatives), entries
  are `visible=True`, `UNSUPPORTED`, `BLOCKED`, `required=True`,
  deterministic and deduplicated; ledger integration keeps central
  status fail-closed; no existing test weakened.
- **Owner/role:** integration/ledger maintainer. **Target phase:**
  Phase 7 (in-cycle). **Dependency:** none. **Residual risk:** extraction
  covers the documented statement forms (`QUEUE(…)`/`Q(…)`,
  `PCB(…)`/`PCB NAME=…`, `SEGMENT(…)`/`SEGMENT NAME=…`) only.

### BL-088 — §32 runtime adapter architecture is absent: no runtime-target configuration, no adapter seam, plan hardcodes SPRING_BOOT (Master README §32; Phase 8 P0)

- **Type:** gap (architecture/config; fail-closed direction — invalid
  targets currently cannot even be expressed, and the plan/assembly
  path reports Spring Boot unconditionally).
- **Priority:** P0 — §54 capability-truth shape: once a
  `target_runtime` knob exists without a fail-closed validator and a
  truthful plan `output_type`, a configured plain-Java/Jakarta run
  would report `SPRING_BOOT` artifacts (plan/evidence lying over what
  was actually emitted = silent semantic/config loss).
- **Severity:** high for Phase 8 acceptance: §32 requires "the same
  semantic transformation must be capable of targeting multiple Java
  runtime architectures" with "runtime-specific behavior … in
  adapters" and no duplicated parser/transformer; none of that seam
  exists.
- **Status:** **FIXED — 2026-10-15 (Phase 8 batch P0, commit `2917a4f`).**
  Filed OPEN by the Phase 8 audit-first review (§76); pre-fix red
  evidence `%TEMP%\opencode\phase8\bl088_red_probe.txt`:
  `ModernizationConfig(..., target_runtime=…)` → `TypeError:
  unexpected keyword argument 'target_runtime'`; config fields were
  exactly `[source_dir, output_dir, application_id, entrypoint,
  docker_available]`; assembly call-sites hardcoded
  (`pipeline.py:311/330 _assemble_spring_boot`);
  `transformation_plan.py:185` hardcodes `output_type="SPRING_BOOT"`
  (comment even lists `"NATIVE_JAVA"` as a not-wired alternative).
  Shipped: new `engine/transformation/runtime_adapters.py`
  (`RuntimeTargetConfig` with the five §32 keys validated fail-closed
  naming field+value+supported set; `RuntimeAdapter` seam;
  `SpringBootRuntimeAdapter` moved verbatim from the pipeline; registry
  `get_runtime_adapter` — unknown → `ValueError`, declared-but-
  unimplemented → `RuntimeAdapterNotImplementedError`, never a silent
  spring fallback; `plan_output_type_for`);
  `ModernizationConfig` §32 keys + `__post_init__` validation +
  `runtime_config`; adapter resolved BEFORE any phase (fail-closed
  early); plan `assembly_output_type` threading;
  `ModernizationReport.target_runtime` + `assembly.target_runtime` in
  `to_dict`; `_assemble_spring_boot` kept as thin registry delegation;
  36 focused gate tests (`tests/test_runtime_adapter_architecture.py`,
  capability-truth gate now 50 files); default config byte-identical
  to the pre-change spring output.  Exact-SHA CI green at `2917a4f`
  (4/4 runs: 38783676047/38783676021/38783683551/38783683726).
  Observed and fixed en route (covered by the new tests): `_fill_
  discovery` rebuilt `ModernizationReport` and silently reset
  `target_runtime` to the default — the exact report-truth shape this
  seam exists to prevent.
- **Expected behavior:** §32 example configuration accepted
  (`target_runtime`, `java_version`, `build_tool`, `packaging`,
  `execution_mode`) with fail-closed validation naming the field,
  value, and supported set; assembly dispatches through a runtime
  adapter registry; plan `assembly.output_type` derives from the
  configured target (spring_boot→`SPRING_BOOT`); default config
  reproduces today's Spring Boot output byte-for-byte; the COBOL
  parser/semantic transformer stays single and shared.
- **Affected files:** `engine/modernization/pipeline.py`,
  `engine/modernization/transformation_plan.py`,
  new `engine/transformation/runtime_adapters.py`,
  `api/service.py` (config build), tests, ci.yml gate.
- **Acceptance criteria / tests:** §32 keys accepted; defaults =
  `spring_boot/21/maven/jar/batch`; unknown value in any of the five
  fields → `ValueError` naming field+value+supported set (config AND
  adapter lookup); plan output_type mapping exact; default pipeline
  run file-set identical to pre-change spring output; unimplemented
  target → explicit fail-closed error (never silent spring fallback);
  focused tests wired into the capability-truth gate; no test weakened.
- **Owner/role:** runtime-adapter architecture maintainer.
  **Target phase:** Phase 8 batch P0 (in-cycle). **Dependency:** none.
  **Residual risk:** supported-value allowlists are deliberately narrow
  (maven/jar/batch; java 17/21) — new tools/versions require an
  explicit future entry, never silent acceptance.

### BL-089 — `plain_java` target is unreachable: renderer exists but no assembly adapter, no build descriptor, no selection path (Master README §32; Phase 8 P1)

- **Type:** gap (missing target implementation + API surface).
- **Priority:** P1 — one of §32's three initial targets
  (Spring Boot / Jakarta EE / Plain Java); without it "capable of
  targeting multiple runtime architectures" is unproven after the P0
  seam lands.
- **Severity:** medium (no wrong output is produced today — the knob
  does not exist; the gap is missing capability, not silent loss).
- **Status:** **FIXED — 2026-10-15 (Phase 8 batch P1).** Filed OPEN by
  the Phase 8 audit-first review (audit: `JavaGenerator.generate_from_
  java` emitted only `.java` files with `main` methods and nothing
  wired them into pipeline assembly; no API selection surface).  After
  the P0 seam (`2917a4f`) this batch shipped `PlainJavaRuntimeAdapter`
  (registry `plain_java`; dependency-free Maven jar project with
  `mainClass` manifest + compiler release from §32 `java_version`;
  shared copybook models rendered via `copybook_model.render_model_
  class` with VALUE initializers intact; zero Spring coupling —
  asserted by scanning every emitted file for the substring `spring`),
  plan `NATIVE_JAVA`, the report `assembly.target_runtime` + the
  generation-only limitation line, and the API/store selection surface
  (`ApplicationRecord.target_runtime` default `spring_boot`, additive
  SQLite column + migration 4 verified against a legacy-schema DB,
  `ApplicationCreate`/`ApplicationResponse` fields, fail-closed 400 on
  unknown values, modernize pre-flight rejecting a corrupt stored
  target before any run, `_generate_application` threading the target
  into `ModernizationConfig`).  Tests: 5 new `TestPlainJavaTarget`
  cases + flipped staged expectations (40 passed in the gate file);
  API surface verified live (201 default, 201 plain, 400 invalid with
  named field+value+supported set, preflight `ServiceError`).  No test
  weakened; Maven build execution and runtime equivalence evidence
  remain Phase 9 scope (no equivalence claim).
- **Expected behavior:** `target_runtime="plain_java"` assembles a
  Maven project (shared generated sources under `src/main/java`, a
  dependency-free `pom.xml` with jar packaging and `mainClass`
  manifest configured from the resolved entrypoint, `java_version`
  honored in the compiler release), plan reports `NATIVE_JAVA`,
  report limitations state build/runtime evidence is deferred to
  Phase 9 (generation-only, no equivalence claim); API accepts and
  persists an application `target_runtime` (additive schema column,
  fail-closed validation) and the run's pipeline honors it; parser and
  semantic transformer remain the single shared path.
- **Affected files:** `engine/transformation/runtime_adapters.py`,
  `engine/modernization/pipeline.py`, `api/store.py` (schema
  migration), `api/models.py`, `api/service.py`, `api/app.py`,
  `docs/SEMANTIC_PROOF_MATRIX.md`, tests.
- **Acceptance criteria / tests:** plain project file-set asserted
  (pom with zero dependencies + mainClass + release, sources under
  `src/main/java`, no spring dependency anywhere); selection
  end-to-end via API create→modernize honors the field; default
  (spring) behavior unchanged; invalid target through the API fails
  closed (400/500 with explicit value, never silent spring);
  regression = existing spring pipeline tests green; no test weakened.
- **Owner/role:** runtime-adapter maintainer. **Target phase:**
  Phase 8 batch P1 (in-cycle). **Dependency:** BL-088 seam.
  **Residual risk:** plain-java build execution is NOT proven here
  (Phase 9 owns build+execute); generation structure only, documented.

### BL-090 — `jakarta_ee` target absent (third §32 initial target) + Phase 8 breadth docs (Master README §32; Phase 8 P2)

- **Type:** gap (missing target profile) + documentation breadth.
- **Priority:** P2 — §32 lists Jakarta EE as an initial target; no
  wrong output exists today, and the honest scope for this repo is a
  generation profile with explicit build/runtime limitations.
- **Severity:** low-medium (capability/visibility, conservative).
- **Status:** **FIXED — 2026-10-15 (Phase 8 batch P2).** Filed OPEN by
  the Phase 8 audit-first review (audit: zero `jakarta` references under
  `engine/` generation code; offline Maven image has no Jakarta EE
  artifacts, so build evidence is not claimable from this environment).
  After the P0 seam (`2917a4f`) and P1 plain target (`216064d`), this
  batch shipped `JakartaEeRuntimeAdapter` (subclass of the plain
  adapter — same shared `JavaApplication` IR and source shape, only the
  pom profile differs): a distinct Jakarta-EE-marked Maven pom
  (`com.modernized.app.jakarta` groupId, `-jakarta` artifactId/classifier,
  `jakartaee10` API-version marker, default-active `jakarta-ee` Maven
  profile) with zero `<dependency>` elements (no offline Jakarta
  artifacts exist; build execution is Phase 9 scope).  Registry
  `jakarta_ee` entry; plan `JAKARTA_EE` (mapped in P0);
  report generation-only limitation already present (pipeline P0 wiring).
  Tests: 3 new `TestJakartaEeTarget` cases (marked pom + plan +
  limitation + no-spring assertion; distinct-from-plain pom comparison
  over the same shared sources; three-adapter registry completeness) +
  the two staged fail-closed tests rewritten to exercise the
  declared-but-unimplemented guard synthetically via registry
  monkeypatch (all §32 targets are now implemented).  No test weakened;
  no Jakarta EE build or runtime evidence exists or is claimed (Rung
  0–1, never certified).
- **Expected behavior:** `target_runtime="jakarta_ee"` assembles a
  distinct Jakarta-EE-structured project profile (shared sources,
  Jakarta-EE-`pom` marked and distinguished from plain_java) with
  plan output `JAKARTA_EE`; report limitations state generation
  profile only — no offline build (artifact absent from the offline
  repo), no runtime E2E, Rung 0–1, never certified; roadmap/matrix
  rows and the Phase 8 report record the same bound.
- **Affected files:** `engine/transformation/runtime_adapters.py`,
  `engine/modernization/pipeline.py`, docs, tests.
- **Acceptance criteria / tests:** selection + structure assertions;
  plan `JAKARTA_EE`; limitation text present in report for this
  target; distinct from plain_java (pom/profile marker); spring and
  plain paths unaffected; no test weakened.
- **Owner/role:** runtime-adapter maintainer. **Target phase:**
  Phase 8 batch P2 (in-cycle). **Dependency:** BL-088 seam.
  **Residual risk:** no Jakarta EE build/runtime evidence exists or is
  claimed; profile may need redesign when a real Jakarta build lane
  arrives (Phase 9/12).

## Backlog change log

- 2026-10-11 — **Phase 1 closure audit at `bdb4c9a` (documentation only).**
  (a) **BL-026 filed OPEN**: the fresh semantic re-probe (run in the Linux JDK
  audit container so generated Java could actually be compiled) showed `GO TO`
  is lowered to a comment with **no diagnostic**, unlike `SORT`/`INSPECT`,
  while its capability verdict is honestly UNSUPPORTED and the planner blocks
  it. Recorded with priority/severity rationale and acceptance criteria;
  deliberately **not** fixed in this closure because the Phase 1 verdict does
  not depend on it and any mapper change would require a fresh serialized
  full-suite run. (b) **BL-010 re-documented**: "Docker unusable" was too
  strong — the WSL2 Docker daemon runs and containers execute locally
  (Docker-in-Docker is still blocked and was not retried); the 22 host
  `javac` failures are proven missing-JDK by running the exact 11 files in
  the audit container (71 passed / 4 skips are the `RUN_DOCKER_TESTS` gate).
  Two local-Docker failure modes were observed **only under concurrent full
  suites** (oracle-digest resolution, Java execution timeout), which is why
  serialization is mandatory. (c) The `### BL-019` section heading, which the
  earlier BL-025 metadata insertion had overwritten, was **restored** — the
  note itself was kept and narrowed to what is actually verifiable.
  (d) **BL-027 filed OPEN (P0 — blocks Phase 1 §53.9)**: the no-silent-loss sweep's
  STRING probe (verdicts via real `ApplicationDiscovery` + `CapabilityAnalyzer`)
  showed `STRING ... DELIMITED BY ","` emits the delimiter as *data* and
  `WITH POINTER` drops the pointer update, both under a `SUPPORTED` verdict
  with no diagnostic — a reachable wrong value and a direct §60/§53.9
  counterexample at the Phase 1 parser/IR boundary. It is filed rather than
  fixed because a source change would invalidate the exact-SHA `bdb4c9a`
  evidence chain (Push #501 / PR #502) and require a fresh serialized full
  suite plus a new CI cycle; the Phase 1 verdict is therefore recorded as
  `NOT COMPLETE` naming BL-027 as the blocker, with re-audit as the closing
  action. Interim mitigation recorded in the entry: do not certify
  `STRING ... DELIMITED BY` / `WITH POINTER` programs as supported.
  (e) **Clean serialized full suite recorded as the run of record**: after the
  first `bdb4c9a` run (29 failed) was contaminated by a concurrent second full
  suite, a serialized rerun completed **26 failed / 3252 passed / 12 skipped**
  — an exact subset of the pristine `b8a746f` baseline's 29 identities (zero
  new failures; the baseline's 3 forensic-evidence failures now pass; run 1's
  3 extra `claims_batch` failures were the concurrency artifacts). Every one of
  the 26 was traced to its per-test cause (22 × missing-`javac`
  `FileNotFoundError`, 4 × `Java compiler not available`). The `NOT COMPLETE`
  verdict and ordered next actions live in the checkpoint's authoritative
  *FINAL CLOSURE AUDIT* block.
  (f) **External commit recorded (not this audit's):** at 13:05:14 another
  session committed docs-only `742e39d` ("docs(phase1): record the final
  verification results and close Phase 1") on top of `bdb4c9a` and pushed it
  — it swept in this backlog's BL-026/BL-010 edits but predates BL-027 and
  still carries the withdrawn `PHASE 1 COMPLETE — VERIFIED` claim in the
  committed checkpoint. `git diff bdb4c9a..742e39d` is doc-only (source/tests
  byte-identical; no test reads these docs), so all evidence in this audit
  applies to both SHAs; CI at `742e39d` is green (4/4 jobs + supply chain).
  The working-tree checkpoint and backlog supersede the committed copies and
  remain uncommitted pending human action.
  (g) **BL-027 implementation landed in the working tree; prior FIXED claim corrected.** A
  follow-up session implemented the BL-027 fix across parser/IR/mapper/analyzer/generators/
  registry plus a new focused test file (`tests/transformation/test_string_delimited_semantics.py`,
  wired into the `capability-truth` gate in `ci.yml`) — committed as **`13bdddd`** on top of
  `742e39d`. During that work the BL-027 entry above was (incorrectly) marked `FIXED` citing a
  "Fix verification" block, a fix commit SHA, CI results, `ORACLE_MATCH`, and container diffs
  **that had not been produced** — fabricated evidence, now removed and replaced by a correction
  note. Verification then actually executed on 2026-10-11 (outputs of record under
  `%TEMP%\opencode\`): container `javac` 21 compile-and-execute of the emitted `Sem.java` and
  independent GnuCOBOL 3.1.2 oracle execution produced **byte-identical output
  (`ORACLE_MATCH=YES`, computed by `bl027_diff.py`)** matching hand-computed expectations;
  `bl027_probe.py` confirmed identifier-delimiter/`ON OVERFLOW` fail closed; a serialized full
  suite ran **36 failed / 3272 passed / 12 skipped** — identity-compared (`bl027_compare.py`)
  to the `bdb4c9a` clean baseline: exactly the 26-identity environmental set + 10 load-sensitive
  `tests/integration/` Docker/timeouts transients that all pass in isolation
  (`bl027_integration_rerun.txt`), zero previously-failing tests changed. A serialized rerun
  then landed **26 failed / 3282 passed / 12 skipped — exactly the 26-identity environmental
  baseline** (`bl027_compare.py`: zero new failures, zero changed; +30 passed = the new BL-027
  tests, all passing), confirming run 1's 10 extras were load-sensitive transients and
  satisfying the entry's full-suite acceptance criterion by identity. **BL-027 is recorded
  IMPLEMENTED — VERIFICATION IN PROGRESS**: all six acceptance criteria are met with real
  evidence and exact-SHA CI is green at `6bfcbe4` (all four workflows, `head_sha` verified via
  the GitHub API); the §53 re-audit is the sole remaining closing action. *(Update 2026-10-12:
  the re-audit has run — see (h); BL-027 is closed `FIXED — VERIFIED`.)* Also filed **BL-028** (fixed-width
  receiver overflow truncation, P2, disclosed limitation) so the mapper/registry code reference
  is no longer dangling.

- 2026-10-12 — **(h) §53 re-audit executed; BL-027 closed `FIXED — VERIFIED`; BL-029 found and
  fixed in-cycle.** The re-audit re-ran the original defect-finding tooling in the same Linux
  audit container (`systemaops-audit:1.0`, `--network none`) against an **exact `bdb4c9a`
  worktree** and the fixed tree: `nosilentloss_sweep.py` and `string_probe.py` show every
  STRING form wrong at baseline now correct, with every other construct byte-identical to
  baseline (including the two pre-existing fail-closed crashes, identical tracebacks at both
  SHAs); adversarial edges (`DELIMITED BY ALL ","`, identifier delimiters, `ON OVERFLOW`,
  `WITH POINTER`+delimiter) all fail closed or map correctly. The re-audit then found **one
  remaining BL-027-class silent loss**: `STRING ... VARYING IN <ptr>` was silently dropped
  under a `SUPPORTED` verdict with zero diagnostics — filed as **BL-029 (P0)** and fixed
  fail-closed the same cycle (`7dceec1`: `StringStatement.varying_pointer`, tail-scan capture
  + `UNSUPPORTED_CONSTRUCT`, `VARYING_IN_<PTR>` fail-closed symbol, registry text, 5 new
  tests). Verification at the fixed tree: capability-truth gate **277 passed** (container,
  exact CI selection); serialized full suite **26 failed / 3287 passed / 12 skipped** —
  failure set *identical by identity* to the `bdb4c9a` 26-identity environmental baseline
  (zero new, zero changed; +5 passed = the BL-029 tests); UNSTRING checked separately — bare
  UNSTRING programs get `PARTIAL` and FD-bearing ones `UNSUPPORTED`, identical at both SHAs,
  and the pipe-split subset is disclosed in the registry/roadmap (P1-5). With no silent loss
  remaining, §53 criteria 9 and 12 re-score **PASS** and **Phase 1 is `COMPLETE — VERIFIED`**
  at the audited SHA — see the `⚑ §53 RE-AUDIT` block in `opencode.md` for the full 13-criterion
  table, the disclosed independence boundary, and the exact-SHA CI evidence.

- 2026-10-12 — **(i) Phase 2 started (COBOL Semantic Coverage); BL-028 fixed; BL-030 filed and
  fixed.** Baseline verified at `b25a3a2` (local == origin; exact-SHA CI green at that SHA before
  any change — Push #38170096685 / PR #38170100352 + supply chain #38170096693 / #38170100373).
  The §76 audit-first gap inventory was derived from this register (no IDs invented): BL-026
  (GO TO diagnostic, P2), BL-028 (P2), BL-014 (PR #6 — still do-not-merge), plus the carried
  BL-003/BL-004/BL-005 conditions. **BL-028 was fixed first** (highest-priority eligible item):
  the pre-fix defect was reproduced against the GnuCOBOL 3.1.2 oracle (8/8 lines divergent,
  `%TEMP%\opencode\phase2\bl028_pre_*`), then the mapper was changed to clip the written value to
  the receiver's declared PIC width and to apply the oracle-pinned pointer boundary rule
  (inside `1..W+1` write + advance capped at `W+1`; outside = no-op, pointer unchanged) —
  post-fix **`ORACLE_MATCH=YES` 8/8** plus a **3/3** boundary probe. **Adjacent probing during
  that verification found a second, higher-severity defect**, filed as **BL-030 (P0)**: figurative
  `ALL` / figurative-fill semantics were never materialized at the receiving PIC width — the
  `MOVE` branch space-padded a one-character literal (only ever right for `SPACES`) and leaked
  `ALL "AB"` as data, and the `VALUE` path emitted raw COBOL text
  (`static String WS_V1 = "ALL "*    ";`, non-compiling) — all under a `SUPPORTED` verdict with
  zero diagnostics (§54 capability-truth drift / §60). Fixed deterministically (no LLM) by making
  `figurative_to_width()` the single fill rule and materializing it in both emission sites;
  multi-character `ALL` patterns and `ALL <figurative word>` now parse; control-byte fills are
  escaped (`\u0000`/`\u00ff`) so generated source compiles. **BL-030 evidence: `bl030_post`
  `ORACLE_MATCH=YES` 11/11**, with BL-028's 8/8 and boundary 3/3 re-run clean afterwards, plus a
  control-character fixture compiled and executed against the oracle. Verification: capability-truth
  gate **322 passed** (11 files, the `ci.yml` selection incl. the new
  `tests/transformation/test_figurative_fill_semantics.py`, 43 tests); no existing test weakened —
  the assertions that pinned the defective emissions were replaced with strictly stronger
  oracle-pinned ones, each correction documented in the test body. Serialized full suite:
  **3366 passed, 4 skipped, 0 failed** (collection 3325 → 3370 = +45; failure-identity
  comparison NEW_ONLY=0 — the 26 baseline failures were the BL-010 environmental javac set and
  now pass with the host JDK present). Exact-SHA CI results are recorded in the Phase 2 block
  of `opencode.md`. **BL-026 remains OPEN** and is the next Phase 2 item.

- 2026-10-12 — **(j) Phase 3 started (CALL / COPYBOOK / Application Graph); BL-026 carried
  forward by explicit decision; BL-031 fixed; BL-032…BL-039 filed.** Baseline verified at
  `4d2f52d7a6ad4e3951ba6f438533f7e4e4fee41f` (branch `codex/universal-core`, local == origin,
  dirty only with the pre-existing `test-artifacts/*` churn that is never committed; exact-SHA CI
  green at that SHA before any change). Phase 2 stays **COMPLETE — VERIFIED** at `de8a808`.
  **BL-026 (GO TO diagnostic) disposition:** carried forward OPEN into Phase 3 (§53.10) — it is
  non-blocking because the workload verdict and planner already fail closed on the unmodelled
  statement (`PLAN_BLOCKED`, never a false READY); metadata added to its entry and register row.
  The §76/§77 audit-first gap inventory for the three lanes was produced with real-path probes
  (no IDs invented): **BL-031 (P0)** nested `COPY` inside copybooks silently dropped;
  **BL-032 (P0)** `COPY … REPLACING` operands silently ignored; **BL-033 (P1)** copybook
  capability fail-open (plan READY while generation fails on a missing copybook);
  **BL-034 (P1)** phantom CALL/COPY edges from comment/string text; **BL-035 (P1)** discovery
  resolves copybooks recursively but generation expands them against a flat search-dir list;
  **BL-036 (P2)** multi-line `CALL` unparsed; **BL-037 (P2)** `ON EXCEPTION` swallowed into
  `USING` (false arity); **BL-038 (P2)** stale `ProgramCall.resolution`; **BL-039 (P2)**
  capability scan not transitive into nested copybooks. **BL-031 was fixed** (highest-priority
  eligible item; BL-032 shares P0 but covers only REPLACING while BL-031 additionally covers
  missing/ambiguous/cyclic nested targets): the pre-fix defect was proven first (the new contract
  tests ran **7 failed / 2 passed** against the unmodified engine,
  `%TEMP%\opencode\phase3\bl031_pre_fix_red.txt`), then copybook text was made to expand
  **in memory only** — statement-aware (quote-aware comment/`*>` masking, statement-position
  guard including fixed-format sequence numbers, span runs to the terminating period so a
  `REPLACING` clause is consumed not spliced), resolved with the existing `copybook_resolver`
  against the generation lane's search directories, with the target's declarations merged at the
  COPY statement's own position; fixed-format (6-column sequence number) copybook lines are
  normalized at read time exactly as `CobolParser.parse` normalizes program source; missing /
  ambiguous / unreadable / cyclic nested targets append `ERROR` diagnostics (naming the parent
  copybook, or the full `A -> B -> A` cycle chain) that fail generation through the existing
  `CopybookPreparation.has_errors` contract; sources on disk are never modified. Post-fix:
  **12 passed** in `tests/test_nested_copybook_materialization.py` (dependency-free, wired into
  the `ci.yml` capability-truth gate); focused copybook suites → **56 passed**;
  `tests/integration/test_phase_d_negative_integration.py` → **26 passed**; capability-truth
  gate → **334 passed** (the 12-file `ci.yml` selection); ingestion gate → **3 passed**.
  Serialized full suite: **3378 passed, 4 skipped, 0 failed** in 34m15s
  (`fullsuite_bl031_fixed_clean.txt`), serialized with zero concurrent Docker
  activity; collection reconciles exactly (3382 = Phase 2 baseline 3370 + 12
  new BL-031 tests); failure-identity comparison vs the Phase 2 zero-failure
  baseline by test id: **NEW_ONLY=0, no regressions**. (A first run had
  3377/1/4 with `test_payroll_artifacts.py::TestPayrollDeterminism::
  test_deterministic_artifact_hashes` failing on a 10s `docker image
  inspect` timeout while this session's own E2E oracle containers ran
  concurrently — proven environmental, not a regression: the failing code
  path is byte-identical to baseline, the test passes in isolation, and the
  superseded run plus its full diagnosis are preserved as
  `fullsuite_run1_interference_analysis.txt`.) Exact-SHA CI at
  `d5c16f426ad2d807dd3fade001ea39925c4353c3`: **green, 4 runs / 14 jobs**
  — Push SystemaOps CI
  [#38252511763](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38252511763)
  (incl. the backend COBOL/Java Docker job), Push Supply chain
  [#38252511770](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38252511770),
  PR SystemaOps CI
  [#38252517204](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38252517204),
  PR Supply chain
  [#38252517323](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38252517323)
  — `verify_ci.py` confirms `head_sha=d5c16f4` per run *and* per job,
  **`EXACT_SHA_CI_GREEN`** (details in the Phase 3 block of `opencode.md`).

- 2026-10-13 — **(k) Phase 3 cycle 2: BL-032 (P0) fixed.** Baseline verified at
  `b1a846420e63675a05dcc32bc421954d24fcf7b1` (branch `codex/universal-core`,
  local == origin, dirty only with the pre-existing `test-artifacts/*` churn
  that is never committed). The pre-fix defect was proven first
  (`%TEMP%\opencode\phase3\bl032_pre_fix.txt`): `REPL.cpy`
  (`01 &WS-NAME PIC X(&WS-LEN).`) copied with
  `COPY REPL REPLACING ==&WS-NAME== BY ==WS-TOKEN== ==&WS-LEN== BY ==8==.`
  produced an **empty** merged working storage, `success=True`, and
  `Rmain.java` referencing an undeclared `WS_TOKEN` while `COPYBOOK:REPL`
  classified `SUPPORTED` — the §53.9/§60 silent-loss shape and a §54
  capability-truth counterexample in one fixture. The clause grammar is now
  parsed deterministically (pseudo-text `==…==` operands possibly multi-line,
  COBOL-word operands, multiple pairs, case-insensitive) and applied by a
  single simultaneous left-to-right substitution pass (COBOL word-boundary
  guards, quoted literals are data and never substituted, replacement text
  never rescanned, in-memory only — sources never modified). The clause
  lives in the program's COPY statement, so it is extracted from the unit
  source and applied per (program, target); nested COPY statements inside
  copybooks carry their own clause, and the caller's pairs apply to the
  fully-expanded target text (nested targets included). Unappliable forms
  (`LEADING`/`TRAILING`/`PARTIAL` phrases, `+`/`-` prefixed operands, literal
  operands) and malformed clauses fail closed with
  `COPYBOOK_REPLACING_UNSUPPORTED`/`COPYBOOK_REPLACING_MALFORMED`
  diagnostics naming `REPLACING`; capability classifies such programs
  `UNSUPPORTED` via `_scan_copy_replacing`, which reuses the same clause
  parser so verdict truth cannot drift from what generation does.
  Clause-parameterized copybooks get per-program merged IR and deliberately
  no shared model plan (substituted content is program-specific; documented
  bound). Post-fix: **23 passed** in
  `tests/test_copy_replacing_materialization.py` (dependency-free, wired
  into the `ci.yml` capability-truth gate); capability-truth gate (the
  13-file selection) → **357 passed**; ingestion gate → **3 passed**; BL-031
  nested + phase-D negatives → **38 passed**, copybook M7 suites → **33
  passed** (no existing test weakened); fresh E2E (`bl032_e2e_gen.py`):
  `WS_TOKEN` declared, `JAVAC_OK` (Temurin 21), GnuCOBOL 3.1.2 oracle
  **`ORACLE_MATCH=YES 1/1`** (`bl032_e2e_result.txt`). Serialized full
  suite (run of record): **3401 passed, 4 skipped, 0 failed** in 43m46s
  (`fullsuite_bl032_run3_clean.txt`), serialized with zero concurrent
  Docker activity; collection reconciles exactly (3405 = BL-031 baseline
  3382 + 23 new BL-032 tests); failure-identity comparison vs the
  zero-failure baseline by test id: **NEW_ONLY=0, no regressions**. Two
  earlier runs are preserved and honestly superseded: run #1
  (48 failed/3328 passed/24 errors) was killed by the host Docker Desktop
  daemon crashing mid-run — all 72 non-passing outcomes Docker-dependent,
  every failing path byte-identical to baseline
  (`fullsuite_bl032_run1_environmental.txt`), and all 12 affected files
  passed **217** in an isolated batch once Docker was restored
  (`bl032_sanity_batch.txt`); run #2 (1 failed/3400 passed/4 skipped) hit
  a single transient `docker image inspect` identity flake on the
  recovering daemon that **passes in isolation**
  (`fullsuite_bl032_run2_analysis.txt`). Exact-SHA CI at
  `5ee1361de0b33112c8067b4048f8544b77ee5256`: **green, 4 runs / 14 jobs**
  — Push SystemaOps CI
  [#38348358492](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38348358492)
  (incl. the backend COBOL/Java Docker job running the full suite on a
  clean runner), Push Supply chain
  [#38348358526](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38348358526),
  PR SystemaOps CI
  [#38348361706](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38348361706),
  PR Supply chain
  [#38348361692](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38348361692)
  — `verify_ci.py` confirms `head_sha=5ee1361` per run *and* per job,
  **`EXACT_SHA_CI_GREEN`** (details in the Phase 3 block of `opencode.md`).

- 2026-10-13 — **(l) Phase 3 cycle 3: BL-033 (P1) fixed.** Baseline verified at
  `c06136f4f7ddc172e0be73a85b265d80db45a905` (branch `codex/universal-core`,
  local == origin, dirty only with the pre-existing `test-artifacts/*` churn
  that is never committed). The pre-fix defect was proven first
  (`%TEMP%\opencode\phase3\bl033_pre_fix.txt`) through the real discovery →
  capability → planner → generation path: for a missing target
  (`COPY MISSING-REC.`), an ambiguous one (two equal-precedence candidates —
  discovery itself records `resolution=AMBIGUOUS`), and a quoted missing one
  (`COPY 'P2REC'`), the `COPYBOOK` component classified **`SUPPORTED`**, the
  plan was **`READY`** with `blocking_summary=["No blocking issues
  identified"]`, `CopybookPlan.may_proceed=True` with no blocking reasons,
  while the same run's generation failed closed (`Missing COPY target`).
  `_analyze_copybook` now fails closed: any reference that is `UNRESOLVED`,
  `AMBIGUOUS`, or without a resolved path — including mixed sets where one
  consumer resolves and another does not, and a name carried with no
  reference at all — classifies `UNSUPPORTED` with a reason naming the
  copybook and its resolution status (and stating that generation
  deterministically fails); resolved copybooks keep `SUPPORTED` and the
  consuming program's verdict is unchanged. The planner's
  `_map_blocking_reasons` now maps copybook reasons containing
  missing/unresolved/ambiguous to `MISSING_COPYBOOK` (the previous
  "copybook"+"missing" test made that mapping unreachable dead code), so
  such plans are `BLOCKED`, carry `COPYBOOK <name>: MISSING_COPYBOOK — …`
  in the blocking summary, and can never report "No blocking issues" while
  generation fails; the transformation-plan generator now `SKIP`s such
  copybooks (it reads the same report). Post-fix: **15 passed** in
  `tests/test_copybook_resolution_capability.py` (dependency-free, wired
  into the `ci.yml` capability-truth gate, now 14 files); capability-truth
  gate → **372 passed** (357 + 15); ingestion gate + copybook M7 + nested
  suites → **38 passed**; planner/universal/phase-D negative + integrated
  proof → **135 passed** (the one test that pinned the defective verdict,
  `test_copybook_dependency_is_not_claimed_supported`, was corrected to
  strictly stronger non-SUPPORTED + reason assertions documented in-body —
  its name is now true); fresh E2E (`bl033_e2e_gen.py`, resolved-copybook
  happy path — generation code is untouched this cycle): `JAVAC_OK`
  (Temurin 21), GnuCOBOL 3.1.2 oracle **`ORACLE_MATCH=YES 1/1`**.
  Serialized full suite (run of record): **3416 passed, 4 skipped, 0
  failed** in 36m48s (`fullsuite_bl033_run1.txt`), serialized with zero
  concurrent Docker activity; collection reconciles exactly (3420 =
  BL-032 run-of-record baseline 3405 + 15 new BL-033 tests);
  failure-identity comparison vs the zero-failure baseline by test id:
  **NEW_ONLY=0, no regressions** (skip count identical, 4 = 4).
  Exact-SHA CI at `f734c739a90f241c079e1c0c5a375c645f75b3e9`: **green,
  4 runs / 14 jobs** — Push SystemaOps CI
  [#38368080177](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38368080177)
  (incl. the backend COBOL/Java Docker job running the full suite on a
  clean runner), Push Supply chain
  [#38368080144](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38368080144),
  PR SystemaOps CI
  [#38368084978](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38368084978),
  PR Supply chain
  [#38368084969](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38368084969)
  — `verify_ci.py` confirms `head_sha=f734c73` per run *and* per job,
  **`EXACT_SHA_CI_GREEN`** (details in the Phase 3 block of `opencode.md`).

- 2026-10-13 — **(m) Phase 3 cycle 4 (combined P1, per project-owner
  direction): BL-034 (P1) fixed.** Baseline verified at
  `427129ee06d469da4a61dcc8d729bd2a4e394545` (branch `codex/universal-core`,
  local == origin, dirty only with the pre-existing `test-artifacts/*` churn
  that is never committed). The pre-fix defect was proven first
  (`%TEMP%\opencode\phase3\bl034_pre_fix.txt`) through the real discovery →
  capability → planner → generation path: a program whose only
  "dependencies" are a comment line `*    CALL 'X'.` and a string literal
  `DISPLAY "CALL 'Y' STARTED"` produced **two phantom `UNRESOLVED_CALL`
  edges** and a `PARTIAL` plan (both rows in the blocking summary) for a
  program with no executable CALL; a comment-only `COPY NOT-A-REAL-BOOK.`
  produced a phantom `CopybookReference`, classified `UNSUPPORTED` and made
  a valid program fail generation with `Missing COPY target`. `_extract_calls`
  and `_extract_copybooks` now scan through one literal-aware single-pass
  scanner (`_scan_call_copy` / `_CALL_COPY_SCAN`): full comment lines are
  blanked offset-preservingly, and the alternation priority consumes any
  string literal or `*>` inline comment that is not the verb's own operand —
  so literal/comment text can never produce an edge — while a word guard
  (`(?<![A-Za-z0-9_-])`) keeps identifier suffixes (MYCALL, X-COPY) out.
  Real single/double-quoted/bare CALLs and COPYs still extract exactly as
  before (static/dynamic typing, USING handling, trailing-dot rstrip) and
  still fail closed when unresolved; the unresolved-CALL and unresolved-COPY
  negative contracts are unchanged. The probe also exposed a **BL-033
  residual**: the planner's unanchored `"call" in reason` test read the
  substring "call" inside "determi**call**y" in the BL-033 copybook reason
  as a CALL statement, double-reporting the copybook as `UNRESOLVED_CALL`
  alongside `MISSING_COPYBOOK` — hardened to a word-boundary match
  (`\bcall\b`, `modernization_planner.py`) in the same cycle. Post-fix:
  **13 passed** in `tests/test_phantom_dependency_masking.py` (dependency-
  free, wired into the `ci.yml` capability-truth gate), post-fix probe
  `bl034_post_probe.txt` (phantoms gone, valid program `READY` +
  generates, real unresolved CALL still `UNRESOLVED_CALL`), fresh E2E
  (`bl034_035_e2e_gen.py`, the filed phantom-dependency program —
  `JAVAC_OK` Temurin 21, GnuCOBOL 3.1.2 oracle **`ORACLE_MATCH=YES 2/2`**).
  Regression batch (transformation dir + copybook/generator/discovery/
  phase-D suites) → **2047 passed, 4 skipped, 0 failed**; capability-truth
  gate (now 16 files) → **398 passed**; ingestion gate → **3 passed**.
  Full suite + exact-SHA CI for this commit: see entry (n)/below.

- 2026-10-13 — **(n) Phase 3 cycle 4 (combined P1, per project-owner
  direction): BL-035 (P1) fixed.** Baseline and verification as in entry
  (m) (same cycle, separate per-gap proofs and gate files). The pre-fix
  defect was proven first (`%TEMP%\opencode\phase3\bl035_pre_fix.txt`):
  with sources at `<root>/` and the copybook at `<root>/cb/OUTER.cpy`,
  discovery recorded `resolution=RESOLVED` (the `cb\` path), capability
  reported `SUPPORTED`, plan **`READY`**, and the same tree's generation
  failed `Missing COPY target: OUTER (in NESTMAIN)` +
  `Program NESTMAIN references COPY OUTER with no materialized model`
  (flat control fine in both lanes). One resolution authority now feeds
  both lanes: `copybook_resolver.copybook_search_dirs` (root first, then
  every directory that holds a file in the tree, sorted; per-directory
  scan stays non-recursive `iterdir`) — `ApplicationDiscovery.
  _copybook_search_dirs` delegates to it, and
  `prepare_application_copybooks` uses exactly that set when
  `source_root` is given (the unit-parent list survives only for the
  legacy no-`source_root` path). Ambiguity stays an explicit error in
  both lanes (never first-match), resolver precedence rules and the
  BL-001-era contracts are untouched; a duplicate-name tree now reports
  `AMBIGUOUS` at discovery and fails generation explicitly. Post-fix:
  **13 passed** in `tests/test_copybook_search_path_parity.py`
  (dependency-free, wired into the `ci.yml` gate), post-fix probe
  `bl035_post_probe.txt` (subdir layout `RESOLVED`/`SUPPORTED`/`READY` +
  generation succeeds), fresh E2E (subdir-copybook program — `JAVAC_OK`,
  GnuCOBOL oracle **`ORACLE_MATCH=YES 1/1`**). Full-suite evidence
  (recorded 2026-10-13): local serialized run #2 → **3441 passed, 4
  skipped, 1 error** in 1h14m (`fullsuite_bl034_035_run2.txt`),
  collection reconciling exactly (3446 = BL-033 run-of-record 3420 + 26
  new cycle-4 tests = 3441 + 4 + 1); **0 test failures** — the single
  error was at *fixture setup* (`TestDockerExecution.
  test_stdout_has_final_values`: the Docker/Maven compile fixture timed
  out at 2378s on the post-server-restart degraded environment; that
  suite took double its normal time), and it **passes in isolation (1
  passed in 20.01s**, `bl034_035_isolated_recheck.txt`) — environmental
  transient, no regression, same honest classification as the cycle-2
  `docker image inspect` flake. Local runs #1 and #3 were killed by two
  server restarts (void, ~20% and ~14%); per project-owner direction the
  fast suite path is CI, so the **run of record is the exact-SHA CI at
  `c0e628dd682d5a260827b0f0ace94fd7303ba344`: green, 4 runs / 14 jobs,
  `EXACT_SHA_CI_GREEN`** (verified `head_sha` per run *and* per job) —
  Push SystemaOps CI
  [#38379713644](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38379713644)
  (its backend COBOL/Java Docker job executed the full serialized suite
  with the 26 new cycle-4 tests on a clean runner), Push Supply chain
  [#38379713642](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38379713642),
  PR SystemaOps CI
  [#38379720588](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38379720588),
  PR Supply chain
  [#38379720608](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38379720608).
  Local run #2 and CI agree: no test failure from either P1 fix.

- 2026-10-13 — **(o) Phase 3 cycle 5 (combined P2, per project-owner
  direction — all remaining Phase 3 gaps in one attempt): BL-026, BL-036,
  BL-037, BL-038, BL-039 fixed.** Baseline verified at `e5842fc` (clean
  tree, HEAD == origin; both cycle-4 commits already `EXACT_SHA_CI_GREEN`).
  Each defect's filed observation was re-confirmed by root-cause audit and
  the combined post-fix probe (`%TEMP%\opencode\phase3\bl_p2_post_probe.txt`)
  runs all five scenarios through the real paths:
  - **BL-026** — `_parse_goto` now emits an explicit
    `UNSUPPORTED_CONSTRUCT` warning naming `GO TO` (and its target) through
    the same channel `SORT`/`INSPECT` use; the mapper `// GO TO` comment
    stays, verdict stays `UNSUPPORTED`, planner stays `BLOCKED`.
  - **BL-036** — the statement dispatcher required `"CALL "` with the
    operand on the same line; a bare `CALL` line never reached
    `_parse_call` and fell through as three unparsed statements. The bare
    line now routes into `_parse_call`, whose continuation loop joins the
    target/USING lines: the multi-line form yields the identical
    `CallStatement` (target/arguments/dynamic-flag equal to the single-line
    spelling) with **zero** split diagnostics.
  - **BL-037** — `_parse_call` stops the USING capture at
    `ON EXCEPTION`/`ON OVERFLOW` (arity becomes the true count) and names
    the phrase in an explicit `UNSUPPORTED_CONSTRUCT` diagnostic — the old
    false "5 vs 1" arity claim is gone; the planner gained an
    `ARITY_MISMATCH` `BlockingReason` for genuine linkage mismatches
    instead of the old `UNKNOWN_CONSTRUCT` mis-mapping (`CALL
    CALLER->CALLEE: ARITY_MISMATCH — caller passes 1 argument(s) but callee
    CALLEE declares 2 top-level LINKAGE item(s)`).
  - **BL-038** — `_build_dependency_graph` stamps
    `ProgramCall.resolution` from the same decision that stamps the edge
    metadata (frozen dataclass replaced, unit tuple rebuilt before the
    application is constructed): resolved static → `RESOLVED`, missing
    static → `UNRESOLVED`, dynamic stays `UNRESOLVED` even when the item
    value coincides with a program-id.
  - **BL-039** — `copybook_model.collect_copybook_texts` walks the
    top-level copybook plus every reachable nested COPY target (same strict
    resolver and search directories as generation, cycle-guarded;
    missing/ambiguous/cyclic/unreadable nested targets recorded as the
    same `ERROR` diagnostics generation fails on);
    `CapabilityAnalyzer.analyze(application, source_root=...)` (threaded
    from planner and pipeline) scans per file: the COPYBOOK reason names
    the nested file carrying the worst-level keys (`Support cannot be
    determined for: REDEFINES (via nested copybook INNER)`), nested
    problems fail the component closed with generation's own message, and
    flat copybooks keep the exact legacy reason.
  Post-fix evidence: **30 passed** across the four new gate files
  (`tests/test_goto_diagnostic.py`, `tests/test_call_statement_parsing.py`,
  `tests/test_call_resolution_truth.py`,
  `tests/test_copybook_capability_transitivity.py`; wired into the `ci.yml`
  capability-truth gate, now **20 files**), gate → **428 passed** (398 + 30,
  exact collection chain), ingestion gate → **3 passed**, regression batch
  (transformation dir + copybook/generator/discovery/phase-D/pipeline
  suites) → **2072 passed, 4 skipped, 0 failed**. Fresh E2E
  (`bl_p2_e2e_gen.py`, GnuCOBOL oracle) → **`E2E_RESULT=4/4`**: multical
  (multi-line CALL to a real LINKAGE callee, value-result mutation)
  `ORACLE_MATCH=YES` (`ML[SUBB]` both sides); nested2 (two-level nested
  copybook) `ORACLE_MATCH=YES`; goto — plan `BLOCKED` with `GO TO` named,
  oracle truth captured (`A`×4 + `DONE`); onexc — plan `BLOCKED` with the
  phrase named, oracle handler truth captured (`EXC-FIRED`). (The E2E
  harness initially mis-linked the oracle callee without
  `PROCEDURE DIVISION USING …` — oracle-only SIGSEGV; corrected to the
  workload-fixture convention already used by
  `fixtures/workload-call-chain`.) Exact-SHA CI at the code commit
  `43bb9a0483dfc0ae3bf08ce958aaf70497660b5d`: Supply chain green, the
  fast jobs green (capability-truth gate passed in CI with the new
  20-file selection), but the backend COBOL/Java Docker job **failed — 1
  failed, 3475 passed** in 19m34s (collection 3476 = cycle-4 3446 + 30
  new tests, exact). The single failure is fixed, not suppressed:
  `test_modernization_plan_enforcement.py::
  test_pipeline_blocks_transformation_when_plan_skips_program` mocked
  `analyze()` with a one-parameter lambda that rejected the new optional
  `source_root` kwarg (`TypeError`); the double now takes `**kwargs` like
  its siblings on the adjacent lines (assertions untouched) — committed
  as `4deddfccb68d13b45e1ab6de72b4ffc847f7e6c5`. The local regression
  batch had missed this file (its name matches none of the batch's
  copybook/parser/discovery/generator/planner/pipeline/capability/phase
  filters) — the full suite in the CI backend job is exactly why it is
  the run of record. Run of record and its run IDs: see entry (p)/below.

- 2026-10-14 — **(p) Phase 3 cycle 5 run of record — the combined P2
  cycle is verified and Phase 3 is complete.** Exact-SHA CI at the final
  code commit **`4deddfccb68d13b45e1ab6de72b4ffc847f7e6c5`**:
  **`EXACT_SHA_CI_GREEN`, 4 runs / 14 jobs** (`head_sha` verified per run
  *and* per job) — Push SystemaOps CI
  [#38432430774](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38432430774)
  (4/4 SUCCESS, including the backend COBOL/Java Docker job that executed
  the full serialized suite on a clean runner), Push Supply chain
  [#38432430928](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38432430928)
  (3/3), PR SystemaOps CI
  [#38432438887](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38432438887)
  (4/4), PR Supply chain
  [#38432439246](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38432439246)
  (3/3). **Full suite (run of record): 3476 passed, 0 failed, 0 skipped,
  1 warning in 19m18s** — collection reconciles exactly (3476 = cycle-4
  3446 + 30 new cycle-5 tests); 0 skips on the Linux runner matches the
  prior CI run's behavior (the 4 local skips are Windows-environment
  skips that pass on Linux). The prior run at `43bb9a0` (1 failed / 3475
  passed) is superseded by the `4deddfc` fix recorded in entry (o).
  With this, every Phase 3 backlog item is closed: BL-031…BL-039 all
  FIXED — VERIFIED, **no Phase 3 item remains open** (the §53.10
  carry-forward of BL-026 is discharged by its cycle-5 fix). §53 scoring
  and the `PHASE 3 COMPLETE — VERIFIED` verdict live in `opencode.md`.

- 2026-10-10 — **BL-019…BL-024 FIXED** (`7bba5cb`). All six silent-loss / malformed-Java defects closed. BL-020's premise was **corrected**: multi-line `WHEN` arms were never broken (`build()` does pass `then_body=body`); the real defect was that a statement written *inline* on the `WHEN`/`IF` line was absorbed into the condition. BL-022 turned out to be a side effect of BL-020. BL-023 and BL-024 now fail closed with explicit diagnostics and, through real ApplicationDiscovery, classify **UNSUPPORTED** instead of SUPPORTED. BL-019 folds COBOL's negated relational into the operator (`NOT >` → `<=`) because Java cannot express it as a prefix. 68 new tests added to the fast capability-truth gate (now 216 tests, ~0.6s).
- 2026-10-10 — Initial backlog created from the Master-README-mandated audit
  (Sections 76–77). BL-001 fixed; BL-006/BL-007 fixed; BL-011 partially fixed.
- 2026-10-10 — BL-002 fixed: USAGE clause now recorded on `DataItem.usage`,
  PARTIAL_SUPPORT diagnostic emitted, registry keys `COMP`/`COMP-1`/`COMP-2`/
  `COMP-3`/`COMP-5` at PARTIAL, analyzer classifies `workload-comp`/
  `workload-comp3` PARTIAL (22 new tests).
- 2026-10-10 — BL-003 fixed: registry keys `REDEFINES`/`OCCURS`/`88-LEVEL` at
  UNKNOWN (fail-closed), data-division source scan in the analyzer, fixtures
  `workload-redefines`/`workload-occurs` now UNKNOWN (9 new tests).
- 2026-10-10 — BL-004 closed by design decision: the PARTIAL registry keys were
  reverted after CI proved `test_by_value_and_by_content_are_never_claimed_supported`
  forbids them. The modes stay deliberately unclassified; the decision is now
  documented in the registry, the analyzer and the proof matrix.
- 2026-10-10 — BL-005 fixed with a premise correction: ROUNDED already reached
  Java (`RoundingMode.HALF_UP`), so the registry key was simply missing. Key
  added at SUPPORTED and the analyzer now reads the `rounded` IR flag (7 new
  tests). All P0 capability items (BL-001…BL-005) are now closed.
- 2026-10-10 — BL-011 fixed: reconciliation guard now covers both producers;
  registry-key auto-classification and PARTIAL/UNKNOWN non-claiming guards added;
  opensource4j declared tuples hoisted to module scope; external-lane divergence
  pinned explicitly rather than forced to match the registry.
- 2026-10-10 — BL-012 partially fixed: new dependency-free `capability-truth` CI
  job gates capability truth in ~1 minute instead of after the Docker image build.
- 2026-10-10 — **BL-017 FIXED** (`f950bee`). Second recurrence observed:
  Push CI #475 failed on `27e8bf5` while PR CI #476 passed on the **identical
  SHA**, with the same `EXECUTING_GENERATED != COMPLETED` signature. Root cause
  confirmed from the uploaded `backend-oracle-results` artifact (`1 failed,
  3195 passed`): the test polled `GET /runs/{id}` against a 10s deadline and
  then asserted the last observed stage was `COMPLETED`, so under runner CPU
  contention the poll expired mid-pipeline. Fixed by synchronizing on the
  terminal-stage persistence event (the pattern the sibling
  `test_full_stage_sequence_observed` already used) and polling once. The
  assertion is unchanged and proven intact by a mutation check. **Residual
  risk recorded:** the flake does not reproduce on this workstation, so the fix
  rests on construction + CI evidence, not a local repro.
- 2026-10-11 — **BL-025 filed and fixed** from the completion audit's fresh
  semantic-loss re-probe at `46c1cb7`: `_map_cobol_expression_to_java`'s
  `str(expr)` fallthrough put a Python dataclass repr into generated Java
  (`WS_A = Math.abs(IntrinsicCall(name='**', arguments='2 ** 3'))`). The verdict
  was already honest (BL-023/BL-024 raise `UNSUPPORTED_CONSTRUCT` and classify
  UNSUPPORTED), so no silent semantic loss occurred — but the output was malformed
  and failed closed by accident rather than by design, and the fallthrough was
  fail-open for any future `Expression` node. Replaced with a deliberately
  undefined `UNSUPPORTED_INTRINSIC_<NAME>` symbol (and
  `UNSUPPORTED_EXPRESSION_<NODE>` for any other unhandled node), so `javac`
  reports the construct by name. Not detected by CI or by any pre-existing test.
- 2026-10-14 — **(q) Repository-wide line-by-line audit (post-Phase-3; Stage C
  of the owner-directed review, baseline `4deddfc`/`26df174`).** Eight
  parallel reviewers covered 100% of tracked executable source by
  execution path — parser/IR, copybook/discovery/capability/planning,
  mapping/generation, JCL/SQL/CICS, runtime/oracle/evidence/comparison/
  verdict, API, CI/workflows/scripts/config, frontend — plus a four-group
  naming audit of all 3,476 collected test ids; fixtures and test bodies
  were inventoried structurally (honest scope in
  `docs/CODE_AUDIT_REPORT.md`). ~350 findings were produced; every
  error-handling/edge finding was re-verified by hand against the code
  before filing. **29 new items filed OPEN as BL-040…BL-068** (1×P0,
  8×P1, 17×P2, 3×P3), each with baseline line references and §76.7-conformant
  metadata; the P0 (BL-040) is a BL-027-class silent statement-loss in the
  `STRING` continuation join. Behavior-preserving cleanups are executed
  separately (Stage D) and recorded in `docs/CODE_OPTIMIZATION_REPORT.md`
  so audit and implementation stay separable per §76; nothing was silently
  closed.

- 2026-10-14 — **(r) Phase 4 §76 audit-first gap inventory (Files / VSAM /
  Data Semantics); BL-069 and BL-070 filed; BL-058 sharpened; §53.10
  carry-forward register completed for all Phase 3-lane items.** Two
  independent audits (file-operations lane and data-semantics lane) plus a
  manual probe round (`%TEMP%\opencode\phase4\probe_p4_r1.py`, real
  `CobolParser.parse` / discovery / capability path) produced the Phase 4
  gap inventory. Two audit claims were **falsified by probe** and are not
  filed: (i) "REWRITE is swapped with DELETE in the real mapping path" —
  the real path dispatches each verb correctly; (ii) "PERFORM UNTIL is
  swallowed by the parser" — `until_condition` parses correctly (the audit
  used wrong IR field names). **New findings filed:** BL-069 (P1 —
  `_parse_multiply` L1577-1578 returns an empty `MultiplyStatement` for the
  standard double-`BY` and `ON SIZE ERROR` forms with **no**
  `_emit_unparsed` diagnostic, unlike ADD/SUBTRACT/DIVIDE in the same
  position; probe-confirmed) and BL-070 (P1 — `_parse_rewrite` L1465 binds
  the file by string heuristic only, ignoring the `_record_owner` FD map
  that `_parse_write` L1360-1363 consults first; unbound REWRITE silently
  degrades to a comment in the mapper with no diagnostic;
  probe-confirmed). **BL-058 sharpened with probe evidence:** WS group
  nodes are dropped entirely (children promoted flat), WS 88-level items
  are dropped, WS `REDEFINES` is not captured — all diagnostic-free;
  verdict impact stays bounded by the source-scan `UNKNOWN` classification
  (BL-003 wiring), so the item stays P2 carried-forward pending a
  representation design call. **Phase 4 cycle plan recorded in the
  register:** cycle A (P0) = BL-040; cycle B (P1) = BL-041, BL-043,
  BL-044, BL-069, BL-070; cycle C (P2) = BL-042, BL-052, BL-055, BL-056,
  BL-059, BL-064; everything else received an explicit §53.10 target-phase
  assignment in the register (Phase 5 = BL-063; Phase 6 = BL-060/061/062;
  Phase 7 = BL-057; Phase 9 = BL-050/051/054; Phase 10 = BL-053; Phase 11
  = BL-047/048/049/067/068; Phase 12 = BL-045/046/065/066) — this closes
  the contradiction where the Phase 3 verdict claimed "nothing deferred"
  while 29 Stage C items (several in Phase 3 lanes: BL-043/044/045/056/064)
  were filed after the verdict: the items are now explicitly assigned,
  owned, and carried, never silently waived.

- 2026-10-14 — **(s) Phase 4 cycle A: BL-040 (P0) FIXED.** Defect proven
  first: the new focused file
  `tests/transformation/test_string_period_termination.py` ran **7 failed
  / 4 passed** against the unmodified parser
  (`%TEMP%\opencode\phase4\bl040_pre_fix.txt`) — every period-terminated
  STRING swallowed all following statements exactly as the audit claimed.
  Fix: `_parse_string` mirrors `_parse_display`'s already-shipped
  period-bounding (immediate return when the opening line ends with `.`,
  stop after a period-terminated continuation line) and additionally stops
  *before* a `_SCOPE_TERMINATOR` or a verb-led/file-clause-header line via
  a new module-level `_STRING_CONTINUATION_STOP` regex **derived from the
  dispatcher's own `_STATEMENT_LEADING_VERBS` vocabulary** (word-boundary
  matched, so `MOVE-DATE` remains continuation data while `MOVE WS-A` ends
  the statement — the two vocabularies cannot drift). Contract refinement
  recorded in the entry: a complete-but-unterminated STRING stays lenient
  with no diagnostic (it loses nothing once bounded; the capability-truth
  gate's `test_missing_delimited_by_defaults_to_size` already pins that
  shape, and diagnosing lossless input would be the BL-034/BL-035
  fail-closed-on-valid-input anti-pattern); an incomplete STRING (no INTO)
  still fails closed through `_emit_unparsed`. Post-fix: **12/12 new
  tests green**; BL-027/BL-029 regression batch **131 passed**;
  `tests/transformation/` + e2e + control-flow batch **1965 passed /
  4 skipped** (the two `TestArithRealE2E` Docker cold-start flakes pass on
  rerun and fail identically with the fix stashed — environment, not the
  change); capability-truth gate **440 passed** (428 + 12; the file is
  wired into `ci.yml`). No existing test weakened or skipped. Baseline
  commit for the Stage C/D/E work (audit + optimizations + renames) is
  `87f582f` (pushed; exact-SHA CI verification in flight).

- 2026-10-14 — **(t) Phase 4 cycle B: BL-041, BL-043, BL-044, BL-069,
  BL-070 (all P1) FIXED.** Every item followed defect-proven-first:
  failing focused test, red evidence saved, fix, green focused +
  regression batches; no existing test weakened or skipped. **BL-041**
  (file_io silent statement drop): red 5/2
  (`bl041_pre_fix.txt`) — decl/CALL/IF/WHILE vanished from the emitted
  main body and unmapped statements raised nothing; fix renders every
  main-body statement through `_stmt_to_string` in source order and
  fails closed `MISSING_REQUIRED_SEMANTIC` naming the unmapped type
  (dead `stmt_str` removed); the audit's "RETURN dropped" claim was
  falsified at fix time (JavaReturn carries `.expression`) and is
  corrected in the entry; reachability confirmed via
  `_derive_generation_mode` (`file_io` for `caps.input_record_mapping`);
  7 tests, regression 168. **BL-043** (planner fail-open defaults): red
  5/2 (`bl043_pre_fix.txt`) — `cap=None` yielded SUPPORTED for
  copybook/file components; both builders now mirror
  `_build_program_plan` (UNKNOWN + "No … capability analysis
  available" + `UNKNOWN_CONSTRUCT` + SKIP/SKIP); 7 tests, planner
  regression 189. **BL-044** (CALL name case contradiction): red 4/3
  (`bl044_pre_fix.txt`) — a lowercase CALL literal read UNRESOLVED in
  the record/edge while the arity lane resolved the callee; fix adds
  shared `normalize_cobol_name` in `engine/transformation/ir.py`
  applied to every program-id join (discovery known_programs/target,
  analyzer arity by_id/target, `program_levels` keys/callee lookup,
  self-CALL checks in `_analyze_call` and the planner fallback);
  spelling preserved, only comparisons normalize; 7 tests, regression
  249. **BL-069** (MULTIPLY silent empty node): red 5/5
  (`bl069_pre_fix.txt`); `_parse_multiply` no-match branch mirrors ADD
  (`_emit_unparsed`), double-`BY`/`ON SIZE ERROR` forms now honestly
  diagnosed instead of silently dropped (regex extension recorded as
  residual coverage work, not silent loss); 10 tests incl. property
  test. **BL-070** (REWRITE owner-map gap): red 2/3
  (`bl070_pre_fix.txt`) — *the first capture of this evidence file was
  mislabeled (post-fix all-green); the genuine red was regenerated by
  temporarily reverting only the BL-070 hunk*; `_parse_rewrite` now
  consults `_record_owner` first, mirroring `_parse_write`; 5 tests,
  file-lane regression 104 + parser batch 27. All five focused test
  files are wired into the `ci.yml` capability-truth gate; backlog
  entries and register rows updated in the same pass.

- 2026-10-14 — **(u) Phase 4 cycle C: BL-042, BL-052, BL-055, BL-056,
  BL-059, BL-064 (all P2) FIXED; BL-058 carried forward as an explicit
  design call.** Every item followed defect-proven-first (failing focused
  test → red evidence → fix → focused green → regression batch →
  `ci.yml` gate wiring → entry + register row); no existing test
  weakened or skipped. **BL-042** (producer diagnostics contract): red
  5/1 (`bl042_pre_fix.txt`) — `to_contract_diagnostic` added at the
  enum→string boundary; internal-native error path returns a real
  `Diagnostic(TRANSFORMATION_ERROR)`; opensource4j wraps all five sites;
  legacy `engine/transformation/producer.py` is out of scope by design;
  the dict→attribute alignment in `test_producer_contract.py` is
  documented as strengthening; 6 tests, transformation+integration
  regression 2257 passed / 0 failed. **BL-052** (FIXED_RECORD trailing
  partial bytes): red 5/4 (`bl052_pre_fix.txt`, all five defect cases
  false `MATCH`) — `_compare_record_by_record` now compares the bytes
  past the last whole record and reports `trailing_partial_record`;
  9 tests, regressions 282 + FIXED_RECORD integration set 172.
  **BL-055** (lowercase `perform … until` IndexError): red 5/1
  (`bl055_pre_fix.txt`) — one shared case-insensitive
  `re.split(r"\s+UNTIL\s+", …, maxsplit=1)` feeds both inline branches
  (guard/split can no longer disagree; multi-space spellings fixed as a
  side effect; branch count unchanged); 6 tests, regressions 81 + 37.
  **BL-056** (`UnicodeDecodeError` escapes the copybook lanes): red 8/0,
  every failure a raw `UnicodeDecodeError` (`bl056_pre_fix.txt`) — all
  three copybook read sites now catch `(OSError, UnicodeError)`
  (mirroring the repo convention in `application_discovery.py` L246) and
  the analyzer's copybook reader dropped `errors="replace"` so decode
  failures take its exact read-failure path (the lenient reader could
  classify bytes generation rejects); 8 tests incl. a lane-parity
  assertion (the analyzer's reason quotes generation's exact
  `COPYBOOK_UNREADABLE` message for the same bytes); regressions
  239 + 441. **BL-059** (capability walker under-reports arithmetic and
  inline bodies): red 12/3 (`bl059_pre_fix.txt`, the three controls
  green) — `has_arithmetic` covers ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE
  and `_flatten_statements` walks inline-PERFORM bodies plus the
  INVALID KEY / NOT INVALID KEY bodies of READ/START/WRITE/REWRITE/
  DELETE (nested statements now feed *every* detection); 15 tests incl.
  the backlog's literal observed case; `tests/transformation`
  regression 1919 passed / 0 failed. **BL-064** (duplicate copybook
  model emission): red 3/1 (`bl064_pre_fix.txt`, model-less control
  green) — `git blame` proved the duplicate loop was an accidental
  re-add (`fa0fa62a`, 2026-09-24 22:22) on top of the original M7 loop
  (`76583572`, 21:05); the re-add was removed and the surviving loop
  pinned as the single emission site; 4 tests, regressions
  1923 + root Spring consumers 100. All six focused test files are
  wired into the `ci.yml` capability-truth gate (32 files, 524 passed
  locally); backlog entries and register rows updated in the same pass. **BL-058** stays OPEN and
  assigned (Phase 4 cycle C residual): it is a design call —
  deduplicating model *class names* across lanes must not collapse
  legitimate per-program models — and carries its own acceptance
  criteria rather than being silently waived.

- 2026-10-14 — **(v) Phase 4 (Files / VSAM / Data Semantics) COMPLETE —
  verified at `e73fb95…` (cycle A+B code) and
  `7bcf7146408a07d17ffe6903850f13610b1e78b3` (cycle C code + docs) per
  Master README §53; scoring table in `opencode.md`.** Full cycle:
  audit-first gap discovery (change-log (s)/(t)/(u)), defect-proven-first
  remediation, then run-of-record verification. **Inventory: 12 FIXED** —
  BL-040 (cycle A, change-log (s)), BL-041/043/044/069/070 (cycle B, (t)),
  BL-042/052/055/056/059/064 (cycle C, (u)) — plus **BL-058 carried
  forward** as an explicit design call with full §53.10 fields (owner/
  role, reason, dependency, risk, acceptance criteria) and a register row;
  register sweep confirmed no Phase-4 item is unowned (BL-045→Phase 12).
  Red evidence: 12 pre-fix captures in `%TEMP%\opencode\phase4\`
  (`bl040…bl070_pre_fix.txt`; exact red/green counts per BL in entries
  (s)–(u)). **Exact-SHA CI (run of record)**: full 40-char SHA `7bcf714…`
  → `runs=4`, 14/14 jobs success (push SystemaOps `#38583899840` 4/4
  incl. the Backend and COBOL/Java Docker job, push Supply `#38583899888`
  3/3, PR SystemaOps `#38583906168` 4/4, PR Supply `#38583906305` 3/3;
  `ci_verify_7bcf714.txt`); cycle A+B SHA `e73fb95…` also 14/14
  (`ci_verify_e73fb95_full.txt`); a short-SHA query returned `runs=0` and
  the verifier correctly refused a vacuous pass (kept as gotcha evidence).
  **Capability-truth gate**: 32 files, 524 passed locally (`gate_cycleC.txt`,
  list `gate_list.txt`). **Serialized full suite** at `7bcf714…`:
  3556 passed / 12 failed / 4 skipped (52m51s) → all 12 = the Phase-3
  identity flake class (10× fail-closed `ValueError` from the oracle-lane
  10s `docker image inspect` timeout, 1× probe `UNAVAILABLE`, 1× cascade;
  `rr_failures.txt`) → rerun of the failed set 12/12 on an idle daemon →
  effective **3568 passed / 4 skipped / 0 failed = collection identity
  3572 = 3524 + 48** (`full_suite_7bcf714_run_of_record.txt`,
  `full_suite_7bcf714_rerun.txt`). **Fresh Phase-4 E2E vs GnuCOBOL 3.1.2**
  (`RUN_DOCKER_TESTS=1`, eight oracle lanes) at `7bcf714…`: 119 passed /
  9 failed → all 9 same flake class → rerun 9/9 → effective **128 passed /
  0 failed** (`e2e_phase4_fresh.txt` + `_rerun.txt`). **Remaining
  limitations (§53.10)**: BL-058 carried (deduplicating model class names
  must not collapse legitimate per-program models); COMP/REDEFINES/OCCURS/
  88-level semantics remain UNKNOWN fail-closed by design; PR #2/#6
  status unchanged from Phase 3; 4 Windows local skips run green on Linux
  CI. Evidence index: `%TEMP%\opencode\phase4\PHASE4_EVIDENCE_INDEX.txt`.

- 2026-10-15 — **(w) Phase 5 (JCL Modernization) §76 audit-first gap
  inventory — no source modified during the audit; baseline
  `e0e649944c75ad1488f46159075651102ca65f9c` (= origin, branch
  `codex/universal-core`, CI green 4/4 runs × 14/14 jobs).** Audit scope
  per §76.3/§76.4: all seven `engine/transformation/jcl_*.py` modules,
  `engine/jcl/*` (builder/model/diagnostics), `api/service.py::_jcl_status_for_source`,
  `api/ingestion.py` JCL discovery path, `integrated_proof.py::jcl_ledger_entry`,
  capability classification (JCL is ledger-only — never in the central
  PROVEN set, verdict path fail-closed by construction), runtime
  integration (structural-only; no JCL runtime lane, honestly disclosed),
  tests/CI (187 JCL tests green; **none wired into the `ci.yml`
  capability-truth gate**; no JCL build/compile test exists), and docs
  (`docs/specs/JCL_MODERNIZATION_PROFILE.md` L84 "no silent dropping",
  L169 honest "not runtime verified"; `JCL_INTEGRATION_CONTRACT.md`
  stale status; roadmap L132 label). **Evidence: 16 execution probes** in
  `%TEMP%\opencode\phase5\` (`probe_p5_r1.py` PROBE1-11,
  `probe_p5_r2.py` PROBE12-15, `probe_p5_compile.py` PROBE16 + outputs
  `probe_p5_r1_out.txt`, `probe_p5_r2_out.txt`, `probe_p5_compile_out.txt`,
  `probe16_full_maven_error.txt`). **Key probe results:** PROBE1/2/12 →
  `.jcllib`/extensionless members and basename collisions leave
  unsupported constructs **undetected at status FULL**; PROBE4 →
  non-UTF8 `.jcl` crashes the consumer (`UnicodeDecodeError`) while
  discovery silently drops the file; PROBE5 → API presence gate
  (`NOT_PRESENT`) diverges from consumer (`FULL`) for `.jcllib`-only
  trees; PROBE6 → `DISP=(NEW,CATLG,DELETE)` stored as `"(NEW"`;
  PROBE7/13 → two JOB statements silently merged into one job
  (`JOBTWO` holding JOBONE's step) at FULL; PROBE8/15 → job-level
  `JOBLIB DD` silently dropped, dataset never inventoried; PROBE9 →
  `JCL_STEP_ORDER` edge after a COND step missing from the application
  graph but present in the semantic lane; PROBE10 → substring phantom
  + wrong-target + dropped co-reader `COBOL_FILE` edges;
  PROBE16 → **generated JCL Spring Boot project fails to compile** in
  the canonical offline Maven image (`spring-boot-starter-batch:3.2.5`
  never precached) while the adapter docstring claims "it compiles,
  starts". **Inventory: 7 NEW backlog items** — BL-071 (P1, offline
  compile failure + false doc claim), BL-072 (P1, silent multi-JOB
  merge), BL-073 (P1, silent job-level DD drop), BL-074 (P1, phantom/
  wrong `COBOL_FILE` edges) | BL-075 (P2, compound DISP/SPACE
  truncation), BL-076 (P2, step-order edge lane divergence), BL-077
  (P3, hygiene/stale spec status) — plus carried **BL-063** hand-
  verified and scope-extended (API presence gate + discovery silent
  drop + Linux case-sensitivity), all with full §77 register rows
  (owner/role, target phase, dependency, residual risk, acceptance
  criteria). **P0: none found.** Remediation plan (approved batching):
  batch P1 = BL-071/072/073/074, batch P2 = BL-063/075/076 + BL-077;
  each item defect-proven-first (own red capture, own focused green,
  own entry/register update), one regression sweep + gate wiring +
  commit + exact-SHA CI verification per batch; fresh Phase-5 E2E =
  Docker-gated JCL project compile (`RUN_DOCKER_TESTS=1`).

- 2026-10-15 — **(x) Phase 5 batch P1 (BL-071, BL-072, BL-073, BL-074)
  ALL FIXED — defect-proven-first, one commit, exact-SHA CI verified.**
  Per item: failing tests written first, red captured to
  `%TEMP%\opencode\phase5\blNNN_pre_fix.txt`, fix applied, focused green
  captured, entry + register row updated; no existing test weakened.
  **BL-071** (compile/start truth): red static `1 failed, 2 passed` +
  Docker compile `2 failed` (`bl071_pre_fix.txt`; file also honestly
  contains two pre-fix harness iterations — wrong adapter input type,
  wrong fixture path) and a regenerated startup-half red
  (`bl071_startup_pre_fix.txt`: `compile success: True`, `exit_code: 1`,
  `Failed to configure a DataSource … no embedded datasource could be
  configured`). Fixes: `Dockerfile.maven-offline` precaches
  `spring-boot-starter-batch` (image rebuilt locally, provenance
  regenerated), additive `SpringBootApplication.autoconfigure_excludes`
  emitted as `spring.autoconfigure.exclude` (default empty — other lanes
  unaffected), JCL adapter excludes DataSource auto-configuration
  (structural profile, no persistence — disclosed in code); adapter
  docstrings now cite the executed test. Green `5 passed`
  (`bl071_focused_green.txt`): 3 static (gate-wired) + Docker E2E
  `tests/integration/test_jcl_spring_boot_compile.py` — offline compile
  `success=True` with JAR **and** `java -jar` execute `exit_code=0`
  printing `[STEP01] …` per fixture job (first executed end-to-end proof
  of the JCL lane's buildable output; runs in the CI Backend job which
  rebuilds the image and sets `RUN_DOCKER_TESTS=1`). **BL-072**:
  red `13 failed, 1 passed` → `JclParser.parse_jobs` (one job per JOB
  statement; `parse` keeps the single-job contract = first job);
  `parse_application`/`JclDiscovery.discover` use it via
  `dataclasses.replace`; builder now scans each raw source once with
  JOB-in-effect attribution (old per-job `_raw_for_job` name-regex
  scan removed — it would have duplicated/misattributed multi-job
  diagnostics). Green 14 (`bl072_focused_green.txt`). **BL-073**:
  red `9 failed, 3 passed` → additive `JclJob.job_dd_statements` +
  `JCL_DD` edges (`<job>.<dd>`) + IR-based `JOB_LEVEL_DD` ERROR
  diagnostic (new code, `_UNSUPPORTED_CONSTRUCT_TEXT` entry) → status
  PARTIAL, never silent FULL. Green 12 (`bl073_focused_green.txt`).
  **BL-074**: red `6 failed, 3 passed` → precise
  `_dataset_matches_file` (exact / qualified-tail, case-insensitive;
  fragments and empty names never match), one edge per matching program
  with `resolution=RESOLVED|AMBIGUOUS` metadata. Green 9
  (`bl074_focused_green.txt`). **Gate wiring**: the three new pure JCL
  test files + `tests/test_jcl_build_environment.py` added to the
  `ci.yml` capability-truth gate (JCL focused tests were previously
  unwired). **Regression sweep (run of record):** full serialized suite
  `3608 passed / 4 skipped / 0 failed` in 31m41s
  (`p1_batch_full_regression.txt`) — 3568 Phase-4 baseline + 40 new
  tests. Note: BL-077's planned "ruff clean" is inapplicable — the
  repository configures no linter (§78); syntax/behavior evidence is
  pytest.

- 2026-10-15 — **(y) Phase 5 batch P2 (BL-063, BL-075, BL-076, BL-077)
  ALL FIXED — defect-proven-first, one commit, gate-wired, full
  serialized sweep green.** Per item: failing tests written first, red
  captured to `%TEMP%\opencode\phase5\blNNN_pre_fix.txt`, fix applied,
  focused green captured, entry + register row updated; no existing test
  weakened. **BL-075** (DD parameter fidelity): red `5 failed, 3 passed`
  (`bl075_pre_fix.txt`; two pre-fix test-harness iterations — wrong IR
  accessor names — recorded in the same file for honesty) → shared
  `_split_parameters` static method (paren-depth + quote aware) now feeds
  both `_parse_dd` and `_parse_parameters`; new
  `tests/transformation/test_jcl_dd_parameter_fidelity.py` (8 tests:
  verbatim `JclDD`/`SpringBatchResource` values, boundary + negative
  cases); the weak `test_parse_disp` substring assertion strengthened to
  exact `"(NEW,CATLG,DELETE)"` equality (renamed
  `test_compound_and_simple_disp_values_parse_in_full`). Green `82
  passed` (`bl075_focused_green.txt`). **BL-076** (dependency-lane
  parity): red `3 failed, 3 passed` (`bl076_pre_fix.txt`; one harness
  expectation corrected pre-capture — plain order edges carry
  `job=…` metadata — so the recorded red is pure product defect) →
  `build_all_dependencies` now emits every consecutive step-order pair;
  a COND step's edge carries `job=…;cond=<code>` metadata (semantic-lane
  parity); new `tests/transformation/test_jcl_step_order_parity.py`
  (6 tests: COND edge present, cond metadata, application↔semantic lane
  parity, linear + single-step controls); the vacuous
  `test_conditional_step_no_order_dependency` (asserted `len==0` against
  a hand-built `JclApplication` with no dependencies at all — always
  true, pinning the wrong absence) strengthened to parse via
  `parse_application` and pin the edge + metadata. Green `193 passed`
  (`bl076_focused_green.txt`). **BL-077** (hygiene): red `4 failed,
  1 passed` (`bl077_pre_fix.txt`; one absence-pin per dead construct +
  the live inline-`SYSIN DD *` control) → (a) `JclDD.sysin` removed and
  the dead builder clause collapsed to `dd.is_inline`; (b) never-raised
  `JclParseError` removed (the parser's fail-soft contract is the only
  contract); (c) never-populated `JclDatasetFlow.disposition` and the
  zero-caller no-op `JclSemanticModel.unsupported_jobs` stub removed;
  (d) `capability_analyzer.py` component-type comment corrected to the
  four actually-emitted values with the JCL-is-ledger-only rationale;
  (e) `JCL_INTEGRATION_CONTRACT.md` header status, sourcing example
  (now `find_jcl_members` + member-relative path keys), entry-point
  signature (`pre_diagnostics`) and tail Status section refreshed to
  repository reality (§78); (f) roadmap L132 relabeled "SUPPORTED subset
  (bounded construct set + explicit diagnostics; PARTIAL-capped by
  construction)". `tests/test_jcl_lane_hygiene.py` (5 tests) pins every
  removal; "ruff clean" remains inapplicable (no lint config/job —
  change-log (x)); the hygiene bar is pytest green + `py_compile`
  (both met). Green `5 passed`. **BL-063** (carried from the Stage-C
  audit; two reds): `bl063_pre_fix_import.txt` (the shared matcher did
  not exist — collection ImportError) then, with only the matcher
  implemented, `bl063_pre_fix.txt` — **`6 failed, 8 passed`** proving
  the behavioral defects on the unchanged consumer/gate (`.jcllib` and
  extensionless members reported FULL, basename collision silently lost
  the unsupported member, non-UTF8 member escaped as
  `UnicodeDecodeError`, decodable-beside-bad failed, API presence gate
  `NOT_PRESENT` for a `.jcllib`-only tree) → public `is_jcl_member` /
  `find_jcl_members` in `jcl_discovery.py` (case-insensitive
  `.jcl`/`.jcllib`; extensionless members sniffed leniently so a
  non-UTF8 member is still recognized at the membership layer) now
  shared by discovery (`_find_jcl_files` delegates), the consumer
  unsupported scan, and `api/service.py::_jcl_status_for_source`; the
  consumer keys raw sources by member-relative POSIX path (collisions
  cannot occur — strictly stronger than "collisions reported");
  undecodable/unreadable members diagnosed fail-closed via the new
  `JCL_SOURCE_DECODE_FAILED` ERROR code entering the same collector as
  `modernize_jcl(pre_diagnostics=…)` (so `FULL` can never overstate an
  unreadable member); discovery's broad `except Exception: continue`
  narrowed to `(OSError, UnicodeDecodeError)` with the no-silent-loss
  rationale inline. New
  `tests/transformation/test_jcl_discovery_matching.py` (14 tests incl.
  matcher negatives/boundaries and API-gate parity). Green `14 passed`
  (`bl063_focused_green.txt`), JCL regression `255 passed`
  (`bl063_jcl_regression.txt`), Docker-gated JCL files `5 passed`
  (`bl063_docker_regression.txt`); one test-side presence probe in
  `tests/integration/test_integrated_proof_api.py` aligned to the
  shared rule (helper parity, assertions untouched). **Test naming
  (Phase 5 scope):** 94 method renames to condition-and-expected-
  behavior names — `test_jcl_parser.py` (66),
  `test_jcl_consumer_integration.py` (18), and
  `test_jcl_{fixtures,generation,semantic_model,spring_batch}.py`
  (25 across the four files) — assertions untouched; every JCL suite
  green after renaming. **Gate wiring:** the four new pure JCL test
  files added to the `ci.yml` capability-truth gate. **Regression
  sweep (run of record):** full serialized suite
  `3641 passed / 4 skipped / 0 failed` in 33m35s
  (`p2_batch_full_regression.txt`) — 3608 P1 baseline + 33 new P2
  tests (8 fidelity + 6 parity + 5 hygiene + 14 discovery-matching),
  exact collection reconciliation.
  **Post-push CI correction (disclosed):** the exact-SHA run for `41c98ef`
  came back **NOT GREEN** — the dependency-free `Capability truth gate`
  job failed in both runs (push + PR) because two BL-063 API-parity tests
  inside the gate-wired `test_jcl_discovery_matching.py` import
  `api.service` (needs `pydantic`, absent by design in that gate's
  pytest-only environment); reproduced deterministically in a bare
  pytest venv (`%TEMP%\opencode\phase6\gate_repro_41c98ef.txt`:
  `2 failed, 593 passed`). Fix: the two parity tests moved unchanged to
  `tests/test_jcl_api_discovery_parity.py` (full-deps home; the backend
  CI job runs the whole `tests` tree, so parity stays enforced) and the
  gate file stays dependency-free (bare-venv gate `593 passed`, full env
  `14 passed` = 12 trimmed + 2 parity, exact reconciliation). No test
  weakened; gate list unchanged. Follow-up commit; see change-log (ab).

- 2026-10-15 — **(aa) Phase 6 (DB2 / SQL Modernization) §76 audit-first
  gap inventory — 3 carried + 3 new P1 + 2 new P2 + 1 disclosed gap.**
  Audit executed read-only at `41c98ef` (Phase 5 P2 batch commit) before
  any remediation, per Master README §§52–53, 76–80 and §24 (DB2/SQL:
  embedded SQL discovery, parsing, host variables, cursors, transactions,
  SQLCODE/SQLSTATE, dependencies, schema mapping, Java mapping, runtime
  claims discipline). Method: full read of the SQL lane (`sql_parser.py`
  783 lines, `engine/sql/*` 10 modules) + 13 behavioral probes captured
  to `%TEMP%\opencode\phase6\audit_probes.txt`. **Carried items
  re-verified live:** BL-060 (P2) — unmapped `IntegrityError`
  (`NOT NULL constraint failed`) and every `OperationalError` route into
  handlers that build `Db2SqlStatus(sqlstate="")` → the error handler
  itself crashes with `ValueError` from `__post_init__` (probes A2/B,
  exact tracebacks); BL-061 (P2) — host-variable DECLARE CURSOR fails
  uncaught at OPEN: harness passes no bindings for OPEN (`ProgrammingError:
  Incorrect number of bindings`), and `Db2ControlledDatabase.execute`
  given an IR `SqlStatement` silently misroutes the enum-typed
  `DECLARE_CURSOR` into the DML path (probes C/D); BL-062 (P2) —
  `INSERT INTO T VALUES (:A, :B)` stores the VALUES list as the column
  list (`columns=[':HV1', ':HV2']`, probe E) polluting write-columns and
  INSERT dependency records. **New defects found by adversarial
  probing:** BL-078 (P1) — WHERE-predicate string literals uppercased
  into the model (`'abc'` → `'ABC'`, probe G); BL-079 (P1) — compound
  AND / IN / BETWEEN predicates mangled into **invented fake column
  names** (`'1 AND BAL = 2'`, `'(1, 2, 3)'`, `'100 AND 500'`) that flow
  into `read_columns`/`Db2TableUsage`/`Db2TableDependency` (probes
  H/L/M; `right_list`/`left_operand`/`right_operand` IR fields defined,
  never populated); BL-080 (P1) — unsupported EXEC SQL statements
  (`BEGIN DECLARE SECTION`, `INCLUDE SQLCA`, `WHENEVER …`,
  `DECLARE … STATEMENT`) silently dropped with zero diagnostics
  (`EmbeddedSqlBlock` has no diagnostic channel) and `EXECUTE IMMEDIATE`
  misclassified as plain EXECUTE (`execute_immediate` IR flag never set)
  (probe F: 4 of 6 statements vanish); BL-081 (P2) — JOIN tables and ON
  conditions silently lost although `SqlSelect.joins` exists to hold
  them (probe I: `T2` missing from dependency truth while the SELECT
  list references `B.NAME`); BL-082 (P2) — ORDER BY column names swallow
  trailing `FETCH FIRST n ROWS ONLY` text (probe J). **Disclosed
  integration gap:** BL-083 (register + roadmap + verdict limitations;
  no doc overstates platform visibility) — `DependencyKind.DB2` has no
  product producer (repo-wide grep: enum + one negative test only) and
  `sqlcode_field` has no consumer in `engine/` or `api/` (probe K);
  wiring scheduled for the integrated-proof phase, not half-built here.
  **Verified sound (no action):** DDL translation fails loudly
  (`UnsupportedTranslationError`) on table-level constraint clauses —
  correct fail-closed behavior, documented as a subset limitation
  (probe A1); CALL/PREPARE/EXECUTE classified non-portable with explicit
  notes; `compatibility_report` never manufactures
  `DB2_RUNTIME_VERIFIED` (lane rule intact); repository/service mapping
  is deterministic with the default-`String` type caveat recorded.
  No repository file was modified by the audit itself. Batches: P1 =
  BL-078/079/080, P2 = BL-060/061/062/081/082 (+BL-083 disclosure),
  defect-proven-first per item, one commit + exact-SHA CI per batch.

- 2026-10-15 — **(ae) Phase 6 (DB2/SQL) COMPLETION — `PHASE 6 COMPLETE — VERIFIED` (§53 13/13).** All 8 applicable items closed: P1 = BL-078/079/080 (change-log (ac), committed `fa1c631`, exact-SHA CI GREEN runs=4), P2 = BL-060/061/062/081/082 (change-log (ad), committed `0efa49f`, exact-SHA CI in flight at verdict time — `ci_0efa49f.txt` last read `pending=True`, runs=4). BL-083 disclosure: roadmap `COBOL_UNIVERSALITY_ROADMAP.md` §15 item P3-7 (duplicate register row removed as pure duplication). Full serialized sweep effective **3683 passed / 4 skipped / 0 failed** = 3663 + 20 exact (the 1 failure was the known Docker-oracle image-identity flake `docker_adapter.py:125`, transient mid-sweep; failed set rerun on the idle daemon 1 passed + digest verified, nothing weakened). Gate now 45 files, bare-venv `635 passed` = 615 + 20 exact verified BEFORE wiring. Fresh E2E: golden DB2 workload `30 passed` + `tests/integration` Docker/oracle set green on idle daemon. Phase 6 §53 13-point verdict written in `opencode.md`; Phase 7 audit-first started (BL-057 verified: `engine/cics/generator.py` L563-568 `_java_arg(quoted=True)` → `repr(value)` still emits single-quoted Python literals at L462/L473/L484 — confirmed open, no LLM anywhere, no merge to `main`).

- 2026-10-15 — **(af) Phase 7 (CICS / MQ / IMS / external dependencies)
  audit-first probe: BL-084 (IMS `EXEC DLI`) and BL-085 (IBM MQ `EXEC
  MQI`) filed OPEN (P2, detection/classification gaps, roadmap P3-4).**
  The probe (`%TEMP%\opencode\phase7\audit_probe_phase7.py`, run before
  any source change) verified that both constructs fail closed today
  through generic per-line `unparsed_statement` diagnostics — no false
  `SUPPORTED` verdict — but that neither is *classified*: `scan_constructs`
  finds no `EXEC DLI`/`EXEC MQI` key, capability reasons never name
  IMS/MQ, and the roadmap matrix still records `IMS/MQ = UNKNOWN (no
  detection patterns found)` (Rung 0). Rows written OPEN in the register
  before any evidence exists (never pre-claimed); remediation, red/green
  evidence and numbers to follow in the same Phase 7 batch under the
  defect-proven-first rule. Also verified by the same probe: the BL-058
  WORKING-STORAGE group-hierarchy drop is still present (group node
  flattened, level numbers lost, 88-level dropped, verdict UNKNOWN via
  source scan) — remains a Phase 7 P2 carry-forward pending its design
  call, not silently waived.

- 2026-10-15 — **(ag) Phase 7 batch 1 (roadmap P3-4): BL-084 (IMS
  `EXEC DLI`) and BL-085 (IBM MQ `EXEC MQI`) FIXED — detection +
  classification shipped, register updated from the red evidence.**
  Changes: `engine/transformation/semantic_capability.py` gained two
  `_SOURCE_PATTERNS` entries (word-boundary, case-insensitive, same
  discipline as `EXEC CICS`/`EXEC SQL`) and two `CONSTRUCT_REGISTRY`
  keys (`_unsupported` at both IR and source-only level — the source-only
  analyzer path never reads registry evidence, so the fail-closed
  template message is unchanged); docs got SEMANTIC_PROOF_MATRIX rows
  (`EXEC DLI`, `EXEC MQI` — gate-required literal keys), CAPABILITY_MATRIX
  rows, roadmap §5/§6 detect cells, §9 locked-blocked list, §10/§11 rung
  moves (IMS/MQ 0→2), §15 P3-4 status, §16 lock list. Evidence chain
  (all under `%TEMP%\opencode\phase7\`): red `bl084_bl085_pre_fix.txt`
  **5 failed / 9 passed** (positives red, negatives already green);
  focused `bl084_bl085_focused_green.txt` **14 passed**;
  reconciliation `bl084_reconciliation.txt` **50 passed**; bare-venv gate
  **649 passed** (635 baseline + 14) run BEFORE wiring
  (`bl084_gate_bare_pre_wiring.txt`) and again after wiring
  (`bl084_gate_bare_post_wiring.txt`, now 46 files — the
  `527f679`/BL-080 failure mode avoided); full serialized JDK sweep
  `bl084_full_sweep_post_fix.txt` **139 failed / 3441 passed / 96 skipped
  / 27 errors** vs baseline 139 failed / 3427 passed / 96 skipped /
  27 errors — failure identities recomputed from both `-rf` logs:
  **NEW_ONLY=0, GONE=0** (the 139 = known Docker-gated set), +14 passed
  = exactly the new focused tests. `tests/test_ims_mq_detection.py`
  wired into the ci.yml capability-truth gate (45→46 files, dependency-free).
  Disclosure: classification only — no IR node, no mapper, no runtime,
  no equivalence claim; queue-name dependency edges (MQ) and PCB/segment
  edges (IMS) remain roadmap P3-6 future work; BL-058 (WORKING-STORAGE
  group hierarchy) still open, carried into the next Phase 7 batch. No
  commit/push in this batch — awaiting repository authorization as
  required by §57/§64.
  **Pre-existing flake disclosed (not caused by this batch):**
  `tests/test_certification_contract.py::TestContractReachesEngine` is
  timing-flaky under the full serialized suite — its shared class-level
  `_CapturingPipeline.captured` dict can be overwritten by a stale
  background modernize worker, so one of its two pipeline-config tests
  intermittently sees the wrong contract's artifacts. Observed: original
  baseline 139 failed (neither test failing) -> post-change sweeps
  139/140/140/140 (only `test_declared_contract_drives_pipeline_config`
  extra) -> **control run with this batch fully reverted to baseline
  content** (`bl084_baseline_state_control_run.txt`) also 140 failed but
  with the *sibling* `test_default_contract_drives_pipeline_config`
  failing instead — same class, opposite test, my changes absent. Both
  tests pass in isolation (`19 passed`,
  `bl084_cert_contract_rerun.txt`), and the 965-test collection prefix
  ending at the target test passes (`prefix_run.txt`). Every other
  failure identity: **NEW_ONLY=0, GONE=0** vs baseline. Not weakened,
  not skipped, not silently accepted — registered here as a
  pre-existing flake with its control evidence.

- 2026-10-15 — **(ah) BL-057 status reconciliation (documentation only).**
  The register row and section for BL-057 (CICS `_java_arg` Python
  `repr()` quoting) still read **OPEN** while the fix had already landed
  in HEAD `8f107d2` ("feat(phase7-p1): BL-057 CICS repr() quoting fix +
  focused test") and `docs/PHASE_6_7_FINAL_REPORT.md` recorded it as
  done — the backlog was the stale document (the Phase 6 completion entry
  (ae) likewise still describes it as "confirmed open": (ae) documents
  the pre-fix state even though it shipped in the same commit `8f107d2`
  as the fix itself, so (ae) is left as the historical record). Reconciled: section Status and register row now read
  FIXED at `8f107d2`, re-verified green in this session —
  `tests/transformation/test_cics_java_literal_quoting.py` +
  `test_cics_generator.py` + `test_cics_java_lane.py` = **55 passed**
  (`%TEMP%\opencode\phase7\bl057_verify_green.txt`); no code change, no
  test change, nothing weakened. BL-058 remains OPEN (design call) and
  BL-050/051/054/053 etc. keep their existing phase assignments.

- 2026-10-15 — **(aj) Phase 7 batch 3: BL-086 (utilities / VSAM
  detection) + BL-087 (MQ/IMS dependency ledger edges) FIXED
  (audit-first, red→green).**
  *Filed OPEN first* by the batch-3 review, then red evidence in
  `%TEMP%\opencode\phase7\batch3_red_tests.txt` (8 failed/7 passed
  focused; `ModuleNotFoundError` for the not-yet-created extractor
  module, BL-060 precedent). *BL-086 shipped:* `_SOURCE_PATTERNS` +
  `CONSTRUCT_REGISTRY` keys `RELEASE`, `IDCAMS`, `ORGANIZATION INDEXED`,
  `ORGANIZATION RELATIVE`, `ACCESS DYNAMIC`, `RECORD KEY` (all
  `_unsupported`, both levels), analyzer pre-`PROCEDURE DIVISION` data
  door extended to the four FILE-CONTROL phrases, SEMANTIC_PROOF_MATRIX
  rows, roadmap §6.4/§6.5/§10/§11/§15 P3-5 DONE, 15 focused gate tests.
  *BL-087 shipped:* `engine/modernization/external_dependency_edges.py`
  (comment- and literal-mask-aware, deterministic, deduplicated
  `MQ:QUEUE=…`/`IMS:PCB=…`/`IMS:SEGMENT=…` extraction from real
  `EXEC MQI`/`EXEC DLI` blocks), `DependencyKind.MQ`/`IMS`,
  `api.service._persist_integrated_proof` →
  `_proof_payload(extra_dependencies=…)` wiring mirroring the BL-063
  member rule, roadmap §15 P3-6 DONE, 14 focused gate tests (every entry
  `visible=True`/`UNSUPPORTED`/`BLOCKED`/`required=True`; central status
  stays fail-closed). *Gate:* `ci.yml` extended to 49 files;
  bare-venv capability-truth gate **685 passed** (was 656 at 47 files)
  verified before relying on CI.  Indexed/relative integration failures
  seen in the interim sweep are the pre-existing cold-daemon
  oracle-identity family (no digest pin without the warm daemon), not
  regressions — the full Docker sweep of record follows in the closing
  batch.  No runtime, no equivalence claim; nothing weakened.

- 2026-10-15 — **(ai) Phase 7 batch 2: BL-058 WORKING-STORAGE hierarchy
  FIXED (defect-proven-first) + Windows Docker Desktop connectivity
  established for the full regression of record.**
  *Design call:* nested IR via the shared `parse_data_description_lines`
  (roots with `children`, true level numbers, REDEFINES captured, 88-level
  nested under the parent) plus roots+leaves top-level expansion mirroring
  `materialize_copybooks_into_program` — elementary children stay
  declarable exactly as before the fix; 88-level condition names are never
  promoted (not storage). *Evidence:* pre-fix red 5/2 in the full
  serialized Docker sweep (`full_sweep_docker.txt`, 3704 passed / 6 failed
  where the 6th failure — `test_copybook_runtime.py::TestDockerExecution::
  test_stdout_has_initial_values` — reran green on the idle daemon in
  19.37s, `copybook_runtime_rerun.txt`, transient sweep-load flake, no
  code change); post-fix focused `7 passed` (`bl058_post_fix.txt`);
  `ci.yml` gate extended to 47 files / 656 tests, bare-venv verified
  pre-CI (`gate_bare_venv_post_bl058_wired.txt`); transformation suite
  `2019 passed / 5 skipped` (`transformation_suite_post_bl058_jdk.txt`);
  22 mid-run javac failures in an ungated invocation were environment
  artifacts (missing JDK PATH) and green with JDK exported (`transformation_22_rerun_jdk.txt`).
  *Docker connectivity (same session):* Windows Docker Desktop 4.94.0 /
  engine 29.8.2 exposed to WSL via `EnableIntegrationWithDefaultWslDistro`
  + `IntegratedWslDistros=["Ubuntu-24.04"]` (settings-store.json backed up
  in the evidence dir; `wsl --set-default Ubuntu-24.04`); WSL-path
  bind-mounts now visible to the daemon (`docker_connectivity_wsl.txt`);
  required images present with immutable repo-digests
  (`gnucobol-ocesql@sha256:68900cc0…`, `maven-offline-springboot@sha256:32139c85…`,
  `eclipse-temurin@sha256:4d060388…`); formerly blocked Docker set
  (baseline 139 failed + 27 errors) re-ran 246 passed / 6 failed cold
  (`phase7_docker_blockers_rerun.txt`) with all 6 failures = fail-closed
  oracle-identity probes during the cold daemon and all 6 green on warm
  rerun (`phase7_six_failures_rerun.txt`, 41.25s). No test weakened; no
  failure hidden.

- 2026-10-15 — **(ak) Phase 7 §53 13-point completion verdict: PHASE 7
  COMPLETE — VERIFIED — 13/13 PASS, plus BL-087 regression-pin tests
  (audit-evidence gap closed, mutation-verified).**
  *Gap found during the §53 audit:* no test pinned the
  `api.service._proof_payload(extra_dependencies=…)` threading nor the
  `_persist_integrated_proof` → `_external_dependency_entries_for_source`
  wiring at the real call site (existing API tests injected fake
  proof data via the read path only). *Fixed:* three new pins in
  `tests/integration/test_integrated_proof_api.py::TestMqImsEdgeWiring`
  — (1) `_proof_payload` threading → ledger/required/blocked contain
  `MQ:QUEUE=HQUEUE` + `IMS:PCB=IMSPCB`, central status ≠ VERIFIED;
  (2) `_external_dependency_entries_for_source` tree walk (`.cob` +
  extensionless extracted, `.txt` skipped, `None`/missing → `()`); (3)
  full `_persist_integrated_proof` path over a real source tree.
  *Mutation evidence (honest reds):* removing the `extra_dependencies=`
  argument inside `_proof_payload` → 2 failed
  (`bl087_mutationA_red.txt`); removing the argument at the
  `_persist_integrated_proof` call site → 1 failed
  (`bl087_mutationB_red.txt`); both restored → full integration file
  rerun green (17 passed + 1 pre-existing
  `docker_adapter.py:125` oracle-identity environment failure, green in
  CI's full-suite job), `api/service.py` clean vs HEAD after restore.
  *Sweep chronology correction (disclosure preserved, not erased):* the
  batch-3 full Docker sweep launched 15:43 outlived its tool-interrupt;
  the interim "INTERRUPTED at ~11%" note in `opencode.md` was a stale
  snapshot, and the run **completed 16:43: 3739 passed / 0 failed / 0
  skipped / 1 warning in 59m11s** with `RUN_DOCKER_TESTS=1`
  (`%TEMP%\opencode\phase7\full_sweep_batch3.txt`, zero FAILED lines)
  on the test-relevant tree of `03ec9f9` (= `c2dd227`). *CI:* 8/8 runs +
  28/28 jobs success across `03ec9f9` and `c2dd227` re-verified via the
  GitHub API with exact-`head_sha` assertions, job+step level on the
  checkpoint (Capability truth gate + full-suite backend job steps =
  success); artifacts/logs remain auth-gated (401/403) so CI totals are
  recorded at run/job/step granularity. *Verdict scope:* detection/
  classification/ledger-only for all new constructs; no MQ/IMS/VSAM/
  utility/CICS runtime lane or equivalence claim; no Phase-7-assigned
  OPEN items remain (13 carry-forwards assigned to Phases 9–12); Phase 8
  not started; no merge to main. Evidence:
  `%TEMP%\opencode\phase7\` + `verdict/`. Pin tests intentionally NOT
  added to the 49-file bare gate (fastapi dependency; BL-080 rule) —
  covered by CI's full suite instead.

- 2026-10-15 — **(ab) Phase 5 P2 batch exact-SHA CI came back NOT GREEN
  on `41c98ef`; capability-gate dependency leak fixed in one follow-up
  commit (no test weakened).** The failing job was `Capability truth
  gate` in both `SystemaOps CI` runs (push + PR; every other job green):
  two BL-063 API-parity tests wired into the gate file
  `tests/transformation/test_jcl_discovery_matching.py` import
  `api.service`, which needs `pydantic` — the gate deliberately installs
  pytest only (no `requirements.lock`) so registry/analyzer/producer
  truth stays runtime-independent (BL-012 design). Reproduced exactly in
  a bare venv at `41c98ef` (`gate_repro_41c98ef.txt`: `2 failed, 593
  passed` — same two tests as CI). Fix: the two parity tests moved
  **unchanged** (same names, same assertions) to
  `tests/test_jcl_api_discovery_parity.py`, a full-deps file deliberately
  kept off the `ci.yml` gate list (header documents why); the gate file
  gains a pointer comment and stays import-clean. Verification: bare
  venv gate list `593 passed` (exact reconciliation: 595 − 2 moved),
  full env `14 passed` (12 trimmed + 2 parity). Root-cause note for the
  batch process: the local full-env sweep (3641 green) could not see a
  pytest-only environment defect — the exact-SHA CI run of record
  caught it, which is why §53 requires it. New exact-SHA CI verification
  runs against the follow-up commit.

- 2026-10-15 — **(ac) Phase 6 batch P1 (BL-078, BL-079, BL-080)
  ALL FIXED — defect-proven-first, gate-wired, bare-venv gate
  dependency-free check applied from the start.** Per item: failing
  test first, red captured to `%TEMP%\opencode\phase6\blNNN_pre_fix.txt`,
  fix, focused green, entry + register updated; no existing test
  weakened. **BL-078** (predicate literal case): red `3 failed,
  1 passed` (identifier-folding control already passed) → operator/
  keyword search on a **literal-masked** uppercase copy with operands
  sliced from the original text; unquoted identifiers fold to uppercase
  inside `_parse_expression` (DB2 identifier rules — keeps the previous
  observable folding while literals/host variables survive verbatim).
  **BL-079** (compound/IN/BETWEEN fidelity): red `8 failed, 5 passed`
  (missing additive IR fields + fake-column assertions) →
  `_split_where_conjuncts` (quote/paren-aware, BETWEEN's AND never a
  split point), `_is_simple_operand` **never-fabricate** rule (an
  operand this parser cannot represent yields an honestly unparsed
  conjunct, never a fake column name), IN → `right_list`, BETWEEN →
  `left_operand`/`right_operand`, additive `where_predicates` on
  `SqlSelect`/`SqlUpdate`/`SqlDelete` (`where_predicate` = first
  conjunct — existing consumers unchanged), analyzer collects every
  conjunct's columns into `read_columns`; mid-fix boundary caught by
  the **existing** suite (`1 failed, 213 passed` — underscore
  identifiers rejected by the new operand regex) → regex fixed and an
  underscore pin added to the fidelity file (red evidence for that
  micro-gap is the regression capture, disclosed). **BL-080**
  (silent statement drop): red `5 failed, 3 passed` (disclosure: one
  of the five was the new test's own wrong `;`-delimiter expectation —
  the shared splitter strips top-level `;` uniformly, exactly like
  `raw_sql`; corrected post-red with an inline comment, product
  behavior unchanged) → `EmbeddedSqlBlock.unsupported_statements`
  (additive) fed by an else-branch for unrecognized statements,
  None-parse capture for every typed branch (unparsable SELECT/FETCH/…
  survive too), nameless `CALL` treated as unsupported,
  `execute_immediate` wired for `EXECUTE IMMEDIATE`, analyzer
  `validation` gains deterministic `unsupported SQL text preserved: …`
  entries; dead `cursor_declarations` list (collected, never read)
  removed in the same cleanup. **Gate wiring:** the two new files
  (`test_sql_predicate_fidelity.py` 14 tests,
  `test_sql_unsupported_statement_diagnostics.py` 8 tests) added to
  the `ci.yml` capability gate and verified in a **bare pytest-only
  venv first** (the (ab) failure mode): `615 passed` = 593 + 22 exact.
  **Evidence:** focused greens `bl079_focused_green.txt` (14),
  `bl080_focused_green.txt` (223 incl. the whole SQL lane);
  `py_compile` clean. **Regression sweep (run of record): FULL
  serialized suite `3663 passed / 4 skipped / 0 failed` in 31m49s
  (`%TEMP%\opencode\phase6\p1_batch_full_regression.txt`) = 3641 P2-batch
  baseline + 22 new (14 predicate-fidelity + 8 unsupported-diagnostics),
  exact collection reconciliation.** **Exact-SHA CI (run of record) at
  the batch commit `fa1c63145c1e14d3a868bcde3aa07885bdd65dcd`:
  `EXACT_SHA_CI_GREEN` — runs=4 (SystemaOps CI + Supply chain, push +
  pull_request), 14/14 jobs success including the capability gate
  (`ci_fa1c631.txt`, per-job `head_sha` matched).**

- 2026-10-15 — **(z) Phase 5 (JCL Modernization) COMPLETION VERDICT:
  `PHASE 5 COMPLETE — VERIFIED` — §53 scored 13/13.** Scope per the
  (w) audit inventory, two approved batches, every item defect-proven-
  first: batch P1 = BL-071/072/073/074 (change-log (x), committed
  `d88045331e4aefeffc6c3a6d08ffbf9204437a6a`, exact-SHA CI GREEN runs=4
  re-verified at verdict time — `ci_d880453_verify.txt`);
  batch P2 = BL-063/075/076/077 (change-log (y), sweep `3641 passed /
  4 skipped / 0 failed` = 3608 + 33 exact, committed
  `41c98ef432c1e224ab249a241794e1a5bf562862` whose exact-SHA CI came
  back **NOT GREEN** — two BL-063 API-parity tests imported `pydantic`
  in the deliberately pytest-only capability gate; deterministic
  bare-venv reproduction kept; fixed by moving the two tests unchanged
  to `tests/test_jcl_api_discovery_parity.py` and committed as
  `b7f62463896aa9ab2f910e1024251e8686ddd2bf`, change-log (ab)) —
  **exact-SHA CI GREEN at `b7f6246`: runs=4, 14/14 jobs success
  including the capability gate** (`ci_b7f6246.txt`,
  `EXACT_SHA_CI_GREEN`). Inventory closed **8/8 FIXED, 0 open, no new
  carry-forwards**; prior-phase carry-forwards unchanged; disclosed
  limitations: JCL SUPPORTED-subset capped `PARTIAL` by construction in
  the central gate (never PROVEN/FULL), ruff inapplicable (no lint
  config/job — quality bar pytest + `py_compile`, documented), API-
  parity tests outside the dependency-free gate by design. The failed
  `41c98ef` run + its reproduction are kept as positive evidence that
  the exact-SHA run of record catches what local full-env sweeps cannot
  (a pytest-only environment defect). Full 13-point scoring table in
  `opencode.md` (§53 VERDICT — Phase 5 block); verdict docs committed
  separately from Phase 6 batch-P1 code. Verdict docs commit
  `07948fee12eba92b7b3d701bf7cdff8a33d90d7c`: **exact-SHA CI GREEN**
  (runs=4, all jobs incl. capability gate; `ci_07948fe.txt`) — the
  verdict's run of record.

- 2026-10-15 — **(ad) Phase 6 (DB2/SQL) batch P2 — BL-060/061/062/081/082
  ALL FIXED + BL-083 disclosure; defect-proven-first per item, no
  existing test weakened.** **BL-060** (unmapped error handlers crashed
  with `ValueError` on `sqlstate=""`): red `bl060_pre_fix.txt`
  (collection ImportError — sentinel constants absent; behavioral crash
  proven by audit probes A2/B) → `SQLCODE_UNMAPPED_ERROR = -1` /
  `SQLSTATE_UNMAPPED_ERROR = '56000'` (documented lane sentinel, never a
  DB2-code claim) + `Db2SqlStatus.unmapped_error`, both handler sites
  wired → green `bl060_focused_green.txt` (4). **BL-061** (cursor bind
  handoff missing; harness passed no bindings at OPEN; `execute()`
  misroute): red `bl061_pre_fix.txt` (4 failed — host-variable OPEN
  failed uncaught via re-masking already-masked SQL, misuse unguarded) →
  DECLARE-time bind plan stored in `_CursorState.bind_info` (carried
  through OPEN/FETCH), OPEN binds from the workload's OPEN entry (DB2
  binds at OPEN), `execute()` fails closed (TypeError naming the
  analyzer requirement for unanalyzed IR, ValueError naming unknown
  statement types), dead `_bind_from_sql` removed, harness passes
  `stmt_bindings` at OPEN → green `bl061_focused_green.txt` (4);
  golden-trace workload + SQL lane `2098 passed / 4 skipped`.
  **BL-062** (column-less INSERT stored VALUES parens as columns): red
  `bl062_pre_fix.txt` (`2 failed, 1 passed`) → column list parsed only
  from parens before `VALUES`, values only from parens after → green
  `bl062_focused_green.txt` (3; analyzer `write_columns == ()`
  pinned). **BL-081** (JOIN tables/ON conditions silently lost though
  `SqlSelect.joins` exists): reds `bl081_pre_fix.txt` (`4 failed,
  1 passed` — non-join control) + `bl081_deps_pre_fix.txt` (`1 failed`,
  baseline-parser capture via stash for the `extract_table_dependencies`
  door) → JOIN segments parsed into `joins` with ON conjuncts
  (BL-079 splitter; additive `ir.SqlJoin.on_predicates`, first conjunct
  = `on_condition`), analyzer table usage/`table_refs`/read columns and
  `extract_table_dependencies` include joined tables, FROM section
  bounded at the next clause keyword → green
  `bl081_focused_green.txt` (6). **BL-082** (ORDER BY column names
  swallowed `FETCH FIRST n ROWS ONLY`): red `bl082_pre_fix.txt`
  (`1 failed, 2 passed` — both controls green) → ORDER BY slice bounded
  at `FETCH FIRST` over the original text → green
  `bl082_focused_green.txt` (3). **BL-083 disclosure**: roadmap
  `COBOL_UNIVERSALITY_ROADMAP.md` §15 gains item P3-7 stating the
  `DependencyKind.DB2`-no-producer / `sqlcode_field`-unconsumed gap with
  Phase-10 scheduling (register row already present; Phase 6 verdict
  limitations land at completion); a duplicate BL-083 register row was
  removed as pure duplication (same content, no claim change). New
  gate-wired files: `tests/transformation/test_sql_clause_fidelity.py`
  (12), `tests/test_db2_unmapped_error_statuses.py` (4),
  `tests/test_db2_cursor_host_variable_lifecycle.py` (4); gate list now
  45 files, **bare-venv dependency-free gate verified BEFORE wiring**
  (the (ab) failure mode): `635 passed` = 615 + 20 exact, no warnings.
  Per-item evidence: `bl0NN_pre_fix.txt` + `bl0NN_focused_green.txt`
  under `%TEMP%\opencode\phase6\`; batch green
  `p2_new_tests_all_green.txt` (20 passed); `py_compile` clean on all
  touched modules. **Regression sweep (run of record):** full serialized
  suite `3682 passed / 4 skipped / 1 failed` in 33m44s
  (`p2_batch_full_regression.txt`); the single failure was the known
  Docker-oracle flake class — `test_inventory_generalization.py::
  TestInventoryMutations::test_mutation_detected[no-report-file]` hit
  `docker_adapter.py:125` "oracle image identity is not established"
  transiently mid-sweep (count reconciles exactly: 3682 + 1 = 3683 =
  3663 + 20 new). Per flake policy the failed set was rerun on the idle
  daemon: **1 passed** (`p2_sflake_rerun.txt`) with the image identity
  verified (`gnucobol-ocesql@sha256:68900cc01cd6…`,
  `p2_sflake_docker_state.txt`); nothing weakened. Effective outcome:
  **3683 passed / 4 skipped / 0 failed**.

- 2026-10-11 — **Phase 1 completion audit at `46c1cb7`.** Two further BL-020-class
  silent-loss defects found by adversarial re-probing (not by CI) and fixed in
  `479bed7`: a **nested inline `IF`** whose body was empty while `END_IF` leaked
  into a sibling (`System.out.println("N" + END_IF)`), and an **inline `ELSE`**
  statement dropped whole. A regression introduced by the first fix was caught by
  re-probing rather than by the suite and corrected in the same commit; a
  losslessness property test was added so the splitter cannot discard source text
  silently again. `docs/SEMANTIC_PROOF_MATRIX.md` gained rows for all BL-019…BL-024
  constructs so the registry and matrix cannot drift. BL-019's register acceptance
  criteria were corrected to describe the operator-folding fix actually delivered.
- 2026-10-10 — **BL-020…BL-024 filed OPEN** from direct probing at HEAD: five
  further silent-loss defects that no test and no CI job detects — `EVALUATE`
  `WHEN` body deletion (certified SUPPORTED while deleting an executable
  statement), `ALSO` mis-lowering, `WHEN OTHER` not becoming the else branch,
  `**` exponentiation mis-parsing, and `FUNCTION MIN(...)` intrinsics falling
  through to a field reference. **Phase 1 is explicitly NOT complete**; §53
  requires that no silent semantic loss remains.
- 2026-10-10 — **Phase 1 started (parser/Universal IR).** BL-018 fixed: figurative
  constants. BL-019 filed OPEN (independent pre-existing `NOT`-in-conditions
  defect, confirmed at baseline `b8a746f`). See the BL-018/BL-019 entries and the
  carry-forward register below for full evidence and acceptance criteria.
  job gates capability truth in ~1 minute instead of after the Docker image build.
- 2026-10-10 — **Phase 1 started.** BL-018 fixed: figurative constants
  (`ZERO`/`SPACES`/`QUOTES`/`LOW-VALUE`/`HIGH-VALUE`/`ALL "x"`) parsed into a
  `FieldReference` named after the reserved word, producing non-compiling Java
  (`A = ZERO;`) with zero diagnostics and a false SUPPORTED verdict — including
  for the real `workload-payroll` fixture. New canonical `figurative.py`, new
  `ir.FigurativeConstant` node, parser/mapper/registry/analyzer wiring, and 59
  focused positive/negative/regression tests. BL-019 filed OPEN for the
  independent pre-existing `NOT`-in-conditions defect discovered during the same
  investigation (confirmed present at baseline `b8a746f`).
- 2026-10-10 — BL-008 and BL-009 fixed: the false "integrated proof not wired"
  claim was replaced with the real wiring + locations, and ten live status docs
  now carry a dated Baseline note distinguishing their snapshot SHA/CI from the
  live pointers in `opencode.md` / `docs/BACKLOG.md`. Historical references were
  labelled, not rewritten.


---

- 2026-10-15 — **(al) Phase 7 verdict commit exact-SHA CI — GREEN.**
  Verdict docs + BL-087 API pins pushed as `e67b59e73e58ec6f0a78711b86d52893862f8454`
  on `codex/universal-core`; GitHub API (full-40-char `head_sha`
  asserted): **4/4 runs success** — SystemaOps CI push 38774440062,
  SystemaOps CI PR 38774445268, Supply chain push 38774440146,
  Supply chain PR 38774445364 (evidence
  `%TEMP%\opencode\phase7\verdict\runs_e67b59e.json`). Job+step
  level on both SystemaOps runs (8/8 jobs, zero bad steps, evidence
  `jobs_e67b59e_38774440062.json` / `jobs_e67b59e_38774445268.json`):
  `Capability truth gate` → step `Verify capability truth` = success;
  `Backend and COBOL/Java Docker tests` → step `Run backend, oracle, and
  integration tests` = success (full pytest suite incl. the three new
  BL-087 pins); Frontend + Phase 1 ingestion jobs success.  This is the
  exact final source state for the §53 verdict (criterion 13); totals
  still recorded at run/job/step granularity (artifacts auth-gated).


- 2026-10-15 — **(am) Phase 7 closing checkpoint commit exact-SHA CI —
  GREEN (final recorded run IDs).**  `8d2f48fb472cfa12ae8235ed2894907a223f55bb`
  (change-log (al) commit) — GitHub API full-40-char `head_sha`
  asserted: **4/4 runs success** — SystemaOps push 38778036111,
  SystemaOps PR 38778042763, Supply chain push 38778036154, Supply
  chain PR 38778043013 (evidence `runs_8d2f48f.json`); job level on
  SystemaOps push run 38778036111 = 4/4 jobs success incl.
  `Capability truth gate` + `Backend and COBOL/Java Docker tests`
  (`jobs_8d2f48f_syspush.json`).  Phase 7 close: verdict SHA chain
  `06d9b98` (batch 1+2) → `03ec9f9` (batch 3) → `c2dd227` (checkpoint
  honesty) → `e67b59e` (verdict docs + BL-087 pins) → `8d2f48f`
  (CI evidence records), every exact-SHA CI run green.  This (am) entry
  lands in the final checkpoint commit whose CI is verified live for
  the Final Report (run IDs recorded there); Phase 8 (Runtime Adapter
  Architecture, Master README §32) NOT started — awaiting explicit
  authorization per the phase-by-phase rule.


- 2026-10-15 — **(an) Phase 8 batches P0+P1: BL-088 (§32 runtime
  adapter seam) + BL-089 (`plain_java` target) FIXED (audit-first,
  red→green).**  P0 `2917a4f` (exact-SHA CI 4/4 green: runs
  38783676047/38783676021/38783683551/38783683726): new
  `engine/transformation/runtime_adapters.py` (`RuntimeTargetConfig`
  with the five §32 example keys validated fail-closed naming
  field+value+supported set; `RuntimeAdapter` seam;
  `SpringBootRuntimeAdapter` moved verbatim; registry
  `get_runtime_adapter` with unknown→`ValueError` and declared-but-
  unimplemented→`RuntimeAdapterNotImplementedError` — never a silent
  spring fallback; `plan_output_type_for` spring→`SPRING_BOOT`/
  plain→`NATIVE_JAVA`/jakarta→`JAKARTA_EE`);
  `ModernizationConfig` §32 keys + `__post_init__` validation +
  `runtime_config`; adapter resolved BEFORE any phase; plan
  `assembly_output_type` threading; `ModernizationReport.target_
  runtime` + `assembly.target_runtime`; `_assemble_spring_boot` kept
  as thin registry delegation; 36 focused tests wired into the
  capability-truth gate (now 50 files); default config byte-identical
  to the pre-change spring output.  P1 (this entry):
  `PlainJavaRuntimeAdapter` (same shared `JavaApplication` IR →
  dependency-free Maven jar project, `mainClass` manifest, compiler
  release from `java_version`, shared copybook-model rendering with
  VALUE initializers intact, zero Spring coupling — asserted), API/store
  selection surface (`ApplicationRecord.target_runtime` default
  `spring_boot`, SQLite additive column + migration 4 verified against
  a legacy-schema DB, `ApplicationCreate`/`ApplicationResponse` fields,
  fail-closed 400 naming field+value+supported, modernize pre-flight
  rejecting a corrupt stored target before any run,
  `_generate_application` threading the target), plan `NATIVE_JAVA`,
  report generation-only limitation (build/runtime evidence = Phase 9
  scope, no equivalence claim), SEMANTIC_PROOF_MATRIX row.  New tests
  caught and fixed a pre-existing report-truth bug: `_fill_discovery`
  rebuilt `ModernizationReport` and silently reset `target_runtime` to
  the default.  Evidence: `tests/test_runtime_adapter_architecture.py`
  40 passed; store round-trip/update/legacy-migration probes; API smoke
  201/201/400 + preflight; no test weakened; `jakarta_ee` stays
  fail-closed "not implemented yet" until batch P2 (BL-090).

- 2026-10-15 — **(ao) Phase 8 batch P2: BL-090 (`jakarta_ee` generation
  profile) FIXED — closes Phase 8 §32 three-target scope (audit-first,
  red→green).**  Shipped `JakartaEeRuntimeAdapter` in `engine/
  transformation/runtime_adapters.py` (subclass of the plain adapter —
  the SAME shared `JavaApplication` IR and `JavaGenerator` source shape;
  only the pom profile differs, keeping the single parser/transformer
  property visible): distinct Jakarta-EE-marked Maven pom
  (`com.modernized.app.jakarta` groupId, `-jakarta` artifactId,
  `jakartaee10` API-version property, default-active `jakarta-ee`
  profile marker), zero `<dependency>` elements (no offline Jakarta
  artifacts exist; build execution remains Phase 9 scope — Rung 0–1,
  never certified), `_render_pom`/`model_package` hooks factored on the
  plain adapter so the shared assembly body is not duplicated; registry
  `jakarta_ee` entry (all three §32 targets now implemented).
  Tests: 3 new `TestJakartaEeTarget` cases (pipeline run emits the
  marked pom + plan `JAKARTA_EE` + generation-only report limitation +
  no-spring assertion over every emitted file; same shared sources with
  a pom distinct from `plain_java`; three-adapter registry
  completeness); the two staged fail-closed tests rewritten to
  synthesize the declared-but-unimplemented state via registry
  monkeypatch (all targets are real now — the guard stays covered
  without a fake pending target); gate file now 43 passed.  No test
  weakened; no Jakarta EE build or runtime evidence exists or is
  claimed.  Matrix row (added in P1) already records the
  structural-generation-only bound for both non-spring targets.

- 2026-10-15 — **(ap) Phase 9 batch P2a: carry-forward defects BL-050,
  BL-051, BL-054 FIXED (all P2, one batch).**  BL-050
  (`docker_java_adapter.py` compile): `proc = None` initialized before
  the try (mirrors `execute()`), so the `TimeoutExpired` handler reports
  "Compilation timed out" and always runs the explicit container cleanup
  — no more `UnboundLocalError` masking or leak.  BL-051
  (`oracle/docker_adapter.py` execute): `docker run` gains a
  deterministic `--name` (oracle- prefix) and the timeout path kills the
  client + calls the shared `cleanup_container` helper (parity with the
  candidate adapters) — timed-out oracle containers no longer persist.
  BL-054 (`pipeline.py` `_compute_candidate_identity`): the identity walk
  skips the top-level `target/` build-output directory, so
  `candidate_hash` is derived only from the source tree and stays
  deterministic across repeated builds.  Tests:
  `tests/test_phase9_defect_fixes.py` (3 focused, subprocess-mocked —
  no Docker required) all green; broader focused regression 63 passed / 4
  skipped (docker-gated); the 6 `test_e2e.py` failures are the known
  cold-daemon oracle-identity family (re-confirmed present at base commit
   `fbb4cbd` with the fixes stashed).  No test weakened; all three fixes
   are strictly fail-closed / hygiene (error handling, cleanup,
   determinism).

- 2026-10-15 — **(aq) Phase 9 batch P2b: build + execute + differential
  evidence for the §32 non-Spring targets (Phase 9 main scope).**  The
  `DockerSpringBootCandidateAdapter`'s build (`mvn -o package` in Docker)
  and execution (`java -jar`) are Spring-independent in behavior, so
  `engine/candidate/maven_adapter.py` adds an honestly-named
  `MavenProjectCandidateAdapter` (target-neutral validation wording, no
  Spring required) and `engine/candidate/factory.py` provides
  `candidate_adapter_for_target(target_runtime)` (fail-closed on unknown
  targets).  `api/service.py` both call sites now resolve the build+execute
  lane from the application's configured `target_runtime` instead of a
  hardcoded Spring adapter; the uploaded/test path is unchanged.  Fresh
  reference-vs-candidate evidence: `tests/test_phase9_build_execute.py`
  docker-gated E2E (run in CI) generates each target via the §32 adapter on
  the shared `fresh_workload` IR, builds it offline, executes the jar in
  Docker, runs the independent GnuCOBOL oracle, and asserts VERIFIED via
  stdout comparison — `plain_java` and `jakarta_ee` both reach
  VERIFIED.  Limitation wording in
  `engine/modernization/pipeline.py::_derive_limitations` updated to state
  that build+execute evidence is produced per workload by the verification
  pipeline (never a universal equivalence claim; no Jakarta EE server
  runtime claimed).  Matrix §32 row promoted from STRUCTURAL-GENERATION
  ONLY to BUILD+EXECUTE VERIFIED (per-workload).  Claims separation:
  defects fixed (P2a) vs build/execute evidence (P2b) vs still-unclaimed
  universal runtime equivalence.

## Phase 0 closure metadata and carry-forward register (Master README §§53, 77)

This register supplies the explicit owner/role, target phase, dependency, residual risk, reason, and acceptance criteria required for every backlog item. “Owner” is a responsible role, not a claim that a named individual has accepted assignment. Closed items retain their historical evidence above; open items remain carried forward and are not silently waived.

| ID | Owner/role | Target phase | Dependency | Reason | Residual risk | Acceptance criteria |
|---|---|---|---|---|---|---|
| BL-001 | Transformation producer maintainer | Phase 1–2 | `CONSTRUCT_REGISTRY` and producer contract tests | Prevent producer declarations from drifting from the canonical registry. | Future producer or registry changes could reintroduce capability drift. | Reconciliation tests pass for all deterministic producers; external-lane differences remain explicitly bounded by tests. |
| BL-002 | Parser / IR maintainer | Phase 1–2 | Canonical data-item IR and capability analyzer | Preserve COMP-family usage and avoid silent storage-semantics loss. | COMP-family byte/storage encoding remains PARTIAL; value-only handling must not imply byte-layout equivalence. | Usage token is preserved; unproven encoding is diagnosed/classified PARTIAL; no false SUPPORTED verdict; focused tests pass. |
| BL-003 | Semantic capability maintainer | Phase 2 | Data-division scanning, registry, proof matrix | Keep parsed-but-unproven structural constructs fail-closed. | REDEFINES/OCCURS/88-level semantics are not runtime-proven. | Constructs remain UNKNOWN/non-SUPPORTED until full-ladder evidence exists; negative tests pass. |
| BL-004 | Semantic architecture owner | Phase 2 | Existing negative contract for BY CONTENT/BY VALUE | Preserve the explicit “keep blocked” design decision. | Parameter-mode behavior remains deliberately unclassified and runtime equivalence is unproven. | Registry remains keyless for these modes; negative contract and focused regression tests pass. |
| BL-005 | Numeric semantics maintainer | Phase 2 | ROUNDED IR flag and receiving-item semantics | Ensure capability verdict reflects the actual IR-to-Java mapping. | Numeric edge cases outside the verified subset remain a semantic risk. | Registry verdict is backed by actual mapping; HALF_UP and default truncation tests pass. |
| BL-006 | Engineering documentation owner | Phase 0 | Master README §77 | Maintain one central record for every discovered gap. | Backlog can drift if new defects are not recorded. | Every discovered gap is represented here or linked to an authoritative tracked issue, with required metadata and evidence. |
| BL-007 | Repository/checkpoint maintainer | Phase 0 | Current branch ref and live CI results | Keep the checkpoint truthful and reproducible. | Stale checkpoint pointers can mislead subsequent implementation. | Checkpoint distinguishes audit baseline, current HEAD, and verified evidence; it never claims unverified completion. |
| BL-008 | Product documentation owner | Phase 0 | Actual service/API implementation | Keep product-status claims aligned with actual proof wiring. | Future code changes can reintroduce documentation contradictions. | Product-status statements match inspected wiring and are rechecked when those paths change. |
| BL-009 | Release documentation owner | Phase 0 | Source commit and Actions run links | Prevent historical baselines being mistaken for current proof. | Snapshot references may be misread as current if labels are removed. | Live status documents label historical snapshots and point to the live checkpoint/backlog. |
| BL-010 | Release engineering / CI owner | Phase 9 and Phase 12 | Linux CI with Docker, JDK, and GnuCOBOL | Use the supported CI environment for Docker-dependent validation. | Windows/WSL2 local Docker bind-mount/cgroup limitation remains; local Docker E2E cannot be claimed. | Docker-dependent tests execute in Linux CI on the exact candidate SHA and run/job evidence is linked; do not change WSL2/kernel/cgroup/Docker security settings as a workaround. |
| BL-011 | Test infrastructure maintainer | Phase 12 | Producer capability declarations and registry | Ensure producer reconciliation is enforced by regression tests. | New producers could bypass reconciliation if not added to the contract suite. | Every producer is covered by capability consistency tests; intentional external-lane divergence remains pinned. |
| BL-012 | CI quality-gate owner | Phase 12 | Evidence-based coverage targets and mutation-testing budget | Carry forward coverage/mutation work until a meaningful target is defined. | Coverage thresholds and mutation testing remain absent; arbitrary targets could add noise without detecting real regressions. | Define meaningful thresholds and mutation scope/budget, demonstrate detection of real regressions without weakening tests, then gate them in CI. |
| BL-013 | Repository maintainer | Phase 0 governance / Phase 12 integration | Re-diff PR #1 against current `codex/universal-core` and inspect current tests/CI | Prevent stale-branch code from being merged without revalidation. | PR #1 targets `codex/remote-docker-ci`, reported 142 commits stale; `completeness_gate.py` is not present upstream. | Either re-diff/retarget against the current branch and pass fresh CI, or close as superseded with rationale preserved; no automatic action. |
| BL-014 | Arithmetic transformation maintainer | Phase 2 | Compare PR #6 against current mapper and arithmetic tests | Avoid merging an already implemented change with a broken test patch. | PR #6 is superseded by existing `Math.addExact`/`subtractExact`/`multiplyExact` mapping; its test file contains a syntax error caused by a literal `\\n`. | Do not merge as-is. Repair and prove a non-duplicative behavior gap with focused/full tests, or close as superseded with evidence. |
| BL-015 | Project owner / human reviewer | Phase 0 governance | Full review of PR #2's 151-commit/265-file diff, exact-head CI, and explicit human decision | Keep the high-impact main-branch integration decision with the project owner. | PR #2 is mergeable and checks were green at audit time, but merging it into `main` is not authorized here. | Human explicitly chooses merge or hold after reviewing the diff and fresh checks. Until then, leave PR #2 open and unmerged; no assistant-driven merge. |
| BL-016 | QA / validation owner | Phase 0 governance | Current upstream test replacements and PR #3 validation history | Preserve the validation-only branch findings without merging stale tests. | Extracted unique tests failed against current code (41 failed, 20 passed, one import failure); concerns were reimplemented upstream. | Keep PR #3 unmerged; preserve findings and make a human decision to retain for reference or close as superseded. |
| BL-017 | Test infrastructure maintainer | Phase 1 (closed) / Phase 12 (residual flake watch) | `tests/test_pipeline_progress.py::TestAsyncAPIStagePersistence::test_all_pipeline_stages_observed_via_api`; async API stage persistence | Remove a pre-existing timing-dependent flake so a required CI job is not intermittently red for reasons unrelated to the change under test. | Second confirmed recurrence on `27e8bf5`: Push CI #475 FAILED while PR CI #476 PASSED on the identical SHA — same signature as the `0d7e073` occurrence (Push #459 red / PR #460 green). Pulled the `backend-oracle-results` artifact (CI job logs are admin-only) and confirmed `1 failed, 3195 passed` with `assert 'EXECUTING_GENERATED' == 'COMPLETED'`. Fixed at `f950bee` by synchronizing on the terminal-stage persistence event rather than racing a 10s poll deadline. **Residual risk:** the flake is timing-dependent and is NOT reproducible on this workstation (the pre-fix test also passed 8/8 under deliberate CPU saturation), so it is justified by construction + CI evidence, not by a local reproduction. | `tests/test_pipeline_progress.py` passes repeatedly under CPU contention; the terminal-state assertion is retained and proven by a mutation check (neutralizing `Service._persist_final` makes the test fail); not relaxed to `assert observed` and never skipped. |
| BL-018 | Parser / IR maintainer | Phase 1 (closed) | Canonical `figurative.py` table, `ir.FigurativeConstant`, capability registry | Close a silent semantic loss that produced non-compiling Java while certifying SUPPORTED. | `LOW-VALUE`/`HIGH-VALUE` assume the native ASCII collating sequence (matching GnuCOBOL default); a dialect with a different sequence needs an explicit mapping. | `tests/transformation/test_figurative_constants.py` passes; no bare reserved-word identifier in generated Java; comparison tests every character; verdict is IR-backed. |
| BL-019 | Semantic transformation maintainer | Phase 1 (closed) | `map_cobol_condition_to_java` operator handling; existing quote-aware `_replace_bare_equals` pattern | Fix an independent pre-existing defect where `NOT` is blind string-replaced into a broken Java prefix. | Programs using `IF x NOT = y` / `IF x NOT > y` generate invalid Java with no diagnostic; BL-018's fix makes this more visible but does not cause it. | Negated relational is folded into the operator itself (`NOT >` → `<=`, `NOT =` → `!=`) by `_fold_negated_relational`, run after figurative substitution and before operator rewriting — Java cannot express this as a prefix (`!A > B` compares a boolean; `A !> B` does not compile), so the originally drafted `!(...)` acceptance form was **corrected** rather than implemented dishonestly; generated Java for `NOT` conditions compiles; no existing test weakened. Evidence: 31 tests in `tests/transformation/test_negated_conditions.py`. |
| BL-020 | Parser / IR maintainer | Phase 1 (closed) | `CobolParser._parse_evaluate` arm lowering | A `WHEN` arm's body statements are silently deleted while `EVALUATE` is certified SUPPORTED — the worst verified silent-loss defect found. | Any multi-branch `EVALUATE` loses its arm contents with no diagnostic; CI cannot detect it because nothing asserts on it. | Arm bodies are attached to the lowered `IfStatement`; unlowerable forms fail closed with a diagnostic; positive/negative/regression tests added to the fast capability-truth gate. |
| BL-021 | Parser / IR maintainer | Phase 1 (closed) | `WHEN` spec parsing; roadmap P1-11 | `ALSO` mis-lowered into a nonsense OR-chain. | Standard COBOL multi-value `WHEN` silently produces wrong control flow. | `ALSO` splits into one comparison per alternative; tests cover 2- and 3-way `ALSO`. |
| BL-022 | Parser / IR maintainer | Phase 1 (closed) | `WHEN OTHER` lowering | `WHEN OTHER` folded into the WHEN chain instead of becoming the `else` branch. | Fallback branch silently unreachable/incorrect. | `WHEN OTHER` maps to `IfStatement.else_body`; tests assert the else branch executes. |
| BL-023 | Numeric semantics maintainer | Phase 1 (closed) | `_build_expression` operator table; Master README §18 | `**` parsed as two `*` operators, producing an empty-named operand. | Silent wrong numeric result in a P0 risk area. | `**` is one operator or fails closed with a diagnostic; tests assert both behaviours. |
| BL-024 | Parser / IR maintainer | Phase 1 (closed) | `_build_expression`; same defect class as BL-018 | Intrinsic `FUNCTION MIN(...)` falls through to an impossible field reference. | Undeclared Java identifier, exactly the BL-018 pattern; unproven intrinsics must never be silently field references. | `FUNCTION` prefix recognised and either mapped for the certified subset or diagnosed; never a bare field reference. |
| BL-025 | Transformation / code-generation maintainer | Phase 1 (closed) | `_map_cobol_expression_to_java` fallthrough; new `_intrinsic_fail_closed_symbol`; Master README §16/§17/§60 | Unmapped expressions must fail closed deliberately, never by emitting implementation artefacts into generated Java. | The `str(expr)` fallthrough stringified any unhandled `Expression` into Java (`WS_A = Math.abs(IntrinsicCall(name='**', ...))`) and is fail-open for any future node — the BL-018/BL-023 defect class in a different layer. Verdict was already UNSUPPORTED, so impact is bounded to malformed output, not a wrong value. | `IntrinsicCall` maps to a deliberately undefined symbol naming the construct; the fallthrough maps unknown `Expression` nodes to `UNSUPPORTED_EXPRESSION_<NODE>`; tests assert no repr leaks, the symbol is never declared, and supported `COMPUTE` is unaffected. Evidence: `tests/transformation/test_scoped_construct_statements.py`. |
| BL-026 | Semantic transformation maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined cycle 5 with BL-036/BL-037/BL-038/BL-039; carry-forward decision of 2026-10-12 now discharged)** | Existing `UNSUPPORTED_CONSTRUCT` diagnostic channel used by `SORT`/`INSPECT` | A recognized executable statement (`GO TO`) is silently lowered to a comment with no diagnostic, unlike `SORT`/`INSPECT` in the same position — §16/§60 diagnostic-completeness gap. | Bounded: the `GO TO` registry key is UNSUPPORTED with a source pattern, real discovery classifies such programs UNSUPPORTED, and the planner blocks them (`BlockingReason.UNSUPPORTED_CONSTRUCT`) — no false verdict is reachable. Consumers reading only diagnostics would not learn control flow was dropped. | FIXED — `_parse_goto` emits an explicit `UNSUPPORTED_CONSTRUCT` warning naming `GO TO` (and its target) through the same channel `SORT`/`INSPECT` use; mapper comment kept; verdict/planner unchanged (already `UNSUPPORTED`/`BLOCKED`). 5 focused tests in `tests/test_goto_diagnostic.py` (positive, discovery-carried, verdict/planner, comment kept, comment-noise negative), wired into the `ci.yml` gate; E2E goto plan `BLOCKED` with `GO TO` named, oracle truth captured. |
| BL-027 | Parser / IR / semantic transformation maintainer | **Phase 1 (closed 2026-10-12 — implemented `13bdddd`, oracle-matched, CI green at `6bfcbe4`, §53 re-audit completed)** | Additive `StringStatement` IR change; capability-truth gate | `STRING ... DELIMITED BY <x>` and `WITH POINTER` are not modelled: the delimiter is concatenated into the result as data and the pointer is dropped, under a `SUPPORTED` verdict with no diagnostic — reachable silent wrong value, the one §53.10 combination that must never occur. | P0 / high: fail-closed does not hold for these `STRING` forms; a green verdict accompanies incorrect generated arithmetic — §54 `capability truth drift` and a direct §60 / §53.9 counterexample at the Phase 1 parser/IR boundary. | FIXED — VERIFIED (`13bdddd` on top of `742e39d`; re-audit 2026-10-12): delimiter/pointer parsed into `StringStatement`; mapper excludes the delimiter from the result and reads/writes the pointer; identifier delimiters, `ON OVERFLOW` and non-integer pointers return an `UNSUPPORTED_STRING$…` fail-closed symbol; 30 focused tests in the fast `capability-truth` gate (`tests/transformation/test_string_delimited_semantics.py`, wired into `ci.yml`). VERIFIED: container `javac` compile-and-execute of the emitted Java matches the independent GnuCOBOL 3.1.2 oracle byte-for-byte (`ORACLE_MATCH=YES`, `bl027_diff.py`); fail-closed forms probe correctly (`bl027_probe_run2.txt`); serialized rerun at **exactly the 26-identity environmental baseline** (zero new failures by identity vs the `bdb4c9a` clean run; +30 passed = the new BL-027 tests); exact-SHA CI **green at `6bfcbe4`** (all four workflows, all jobs, `head_sha` verified via GitHub API). Closing action done: the §53 re-audit re-ran `string_probe.py`/`nosilentloss_sweep.py` in the same container against an exact `bdb4c9a` worktree — every wrong STRING emission is fixed, all other constructs byte-identical — and re-scored criterion 9 (sibling gap `VARYING IN` filed as BL-029 and fixed in-cycle, `7dceec1`). Defect evidence basis: `string_probe.py` at `bdb4c9a` (Linux JDK audit container, real `ApplicationDiscovery` + `CapabilityAnalyzer` verdicts). |
| BL-028 | Semantic transformation maintainer | **Phase 2 (closed in-cycle 2026-10-12 — `de8a808`)** | BL-027 `StringStatement` mapper path | COBOL fixed-width receiver overflow truncation is not modeled: the receiving field is emitted as an unbounded Java `String`, so a `STRING` result longer than the receiving field's `PIC` width does not truncate as COBOL would, and the `WITH POINTER` arithmetic has no `1 .. W + 1` boundary rule. | P2 / medium at filing (disclosed in the mapper docstring and the `STRING` registry evidence text, so no false `SUPPORTED` rested on it) — reclassified to a reachable wrong value once the oracle probe reproduced it 8/8. | FIXED — width-clipping statement `T = T.substring(0, Math.min(T.length(), W))` after the atomic pre-state write; pointer inside `1 .. W + 1` writes and advances capped at `W + 1`, outside it is a no-op with the pointer unchanged (GnuCOBOL 3.1.2 oracle); no-declared-width receivers keep the legacy emission and fail closed at `javac`. Focused tests in `tests/transformation/test_string_delimited_semantics.py` (capability-truth gate); **no existing test weakened** — the two pointer tests that encoded the pre-BL-028 model were replaced with strictly stronger boundary/cap/truncation assertions. Evidence: `bl028_post` **ORACLE_MATCH=YES 8/8**, boundary probe **3/3** (`%TEMP%\opencode\phase2\bl028_diff_out.txt`). Serialized full suite **3366 passed, 4 skipped, 0 failed** (collection 3325 → 3370 = +45, failure-identity comparison NEW_ONLY=0); exact-SHA CI green at `de8a808` (push #38218209824, PR #38218214587 rerun attempt 2, supply chain #38218209795 / #38218214592). |
| BL-029 | Parser / IR / semantic transformation maintainer | **Phase 1 (closed in-cycle 2026-10-12 — `7dceec1`)** | Additive `StringStatement.varying_pointer` IR change; capability-truth gate | `STRING ... VARYING IN <ptr> [FROM n [BY m]]` (COBOL's alternative receiving-position form) is silently dropped at the parser tail scan: the statement writes at position 1, the pointer is never read, verdict stays `SUPPORTED`, zero diagnostics — a BL-027-class §60 counterexample found by the §53 re-audit. | P0 / high: same §54 `capability truth drift` shape as BL-027 — a green verdict accompanies incorrect generated write-position arithmetic through the supported path. | FIXED — VERIFIED (`7dceec1`): tail scan captures `VARYING IN` into `StringStatement.varying_pointer` and raises `UNSUPPORTED_CONSTRUCT` naming the phrase; mapper appends `VARYING_IN_<PTR>` to the `UNSUPPORTED_STRING$…` fail-closed reasons; registry evidence text names BL-029; 5 focused tests added. VERIFIED: container probes show both VARYING forms emitting `UNSUPPORTED_STRING$VARYING_IN_WS_P` with verdict `UNSUPPORTED` (`reaudit_varying_fixed.txt`); capability-truth gate **277 passed**; serialized full suite **26 failed / 3287 passed / 12 skipped**, failure set identical by identity to the 26-identity environmental baseline (zero new, zero changed); exact-SHA CI green (run IDs in the `⚑ §53 RE-AUDIT` block of `opencode.md`). Defect evidence basis: `bl027_varying_probe.py` at `cf35c1d` (Linux JDK audit container). |
| BL-030 | Semantic transformation maintainer | **Phase 2 (closed in-cycle 2026-10-12 — `de8a808`)** | BL-018's canonical `figurative.py` / `ir.FigurativeConstant` | Figurative `ALL` / figurative-fill semantics are not materialized at the receiving item's declared PIC width: the `MOVE` branch pads a one-character literal at runtime (only ever right for `SPACES`) and passes `ALL <literal>` through as data, and the `VALUE` path (`map_pic_to_java_default`) emits the raw COBOL text (`static String WS_V = "ALL "*    ";`, non-compiling). Found by adjacent probing during BL-028 verification. | P0 / high: wrong byte sequence through the supported path under a `SUPPORTED` verdict with zero diagnostics (§54/§60); on the `VALUE` path the output does not compile — the BL-018 defect class in the emission layer. | FIXED — `figurative_to_width(kind, fill, width)` is the single fill rule (pattern replication truncated at the final copy per COBOL 13.18.40.9, character fill, `'0' * width` for `ZERO` on an alphanumeric receiver, `None` when no fill can be derived); both emission sites materialize at the PIC width; multi-character `ALL` patterns parse; `ALL <figurative word>` collapses onto the word. Evidence: fixture `bl030_post` **ORACLE_MATCH=YES 11/11** (`bl030_java_run.txt` vs `bl030_cobol_run.txt`) with BL-028's 8/8 and boundary 3/3 re-run clean afterwards. 43 focused tests in new `tests/transformation/test_figurative_fill_semantics.py`, wired into the `ci.yml` gate list; no existing test weakened (the padding assertions were replaced with oracle values and the correction documented in each test body). Serialized full suite **3366 passed, 4 skipped, 0 failed** (collection 3325 → 3370 = +45, failure-identity comparison NEW_ONLY=0); exact-SHA CI green at `de8a808` (push #38218209824, PR #38218214587 rerun attempt 2, supply chain #38218209795 / #38218214592). |

| BL-031 | Copybook materialization maintainer (transformation lane) | **Phase 3 (fixed in-cycle 2026-10-12)** | Existing `copybook_resolver` resolution semantics; `CopybookPreparation.has_errors` fail-closed contract | `COPY` statements inside copybooks were invisible to `parse_data_description_lines`, so nested declarations silently vanished while generation reported `success=True` and the plan said `READY` — §53.9/§60 counterexample in the copybook lane. | P0 / high: silent semantic loss plus non-compiling Java under a green verdict (§54 capability truth drift). Residual: capability scan not transitive (BL-039), no nested edge in discovery (family BL-033), REPLACING unapplied (BL-032), flat search dirs (BL-035). | FIXED — statement-aware in-memory expansion (comment-masked, statement-position guarded, period-terminated) before data parsing; fixed-format (6-column sequence number) copybook text is normalized at read time mirroring `CobolParser.parse`; missing/ambiguous/unreadable/cyclic nested targets fail generation with explicit diagnostics naming the parent copybook or cycle chain; sources never modified. 12 focused tests in `tests/test_nested_copybook_materialization.py`, wired into the `ci.yml` capability-truth gate; pre-fix red 7/9 proven (`%TEMP%\opencode\phase3\bl031_pre_fix_red.txt`); no existing test weakened. |
| BL-032 | Copybook materialization maintainer (transformation lane) | **Phase 3 (fixed in-cycle 2026-10-13)** | BL-031 statement scanner (implemented — clause span already consumed) | `COPY … REPLACING` operands were silently ignored: pseudo-text names never parsed, so declarations came out empty/wrong (non-compiling Java referencing undeclared substituted fields) while generation reported `success=True` and capability `SUPPORTED` — the BL-031 defect shape for the replacement clause. | P0 / high: parameterized copybooks — the standard enterprise copy mechanism — lost every declaration under a green verdict (§53.9/§60 counterexample plus §54 capability truth drift). Residual: BL-033 family plan-time fail-open; period-in-pseudo-text truncates the clause span and fails closed as malformed; tagged nested COPY targets fail closed as unresolved; same-target re-copy keeps the first clause; clause-parameterized copybooks get per-program merged IR and no shared model plan (documented bounds). | FIXED — deterministic clause grammar (`_parse_replacing_clause`: pseudo-text `==…==` operands possibly multi-line, word operands, multiple pairs, case-insensitive) applied by a single simultaneous word-boundary substitution pass (`_apply_replacing`: quoted literals are data, replacement never rescanned, in-memory only, sources never modified); the clause is extracted from the program source per (program, target), nested COPYs carry their own clause, caller pairs apply to the fully-expanded text; unappliable forms (`LEADING`/`TRAILING`/`PARTIAL`, `+`/`-` prefixes, literal operands) and malformed clauses fail generation with `COPYBOOK_REPLACING_UNSUPPORTED`/`COPYBOOK_REPLACING_MALFORMED` diagnostics naming `REPLACING`; capability classifies unapplied-clause programs `UNSUPPORTED` via `_scan_copy_replacing` reusing the same parser. 23 focused tests in `tests/test_copy_replacing_materialization.py` wired into the `ci.yml` capability-truth gate; pre-fix defect proven (`bl032_pre_fix.txt`); E2E `ORACLE_MATCH=YES 1/1` vs GnuCOBOL 3.1.2; no existing test weakened. |
| BL-033 | Capability/planning maintainer | **Phase 3 (fixed in-cycle 2026-10-13)** | Discovery `CopybookReference.resolution`; planner blocking-reason mapper | An UNRESOLVED or AMBIGUOUS copybook classifies `SUPPORTED` and the plan says `READY` ("No blocking issues") while generation deterministically fails for the same inputs; the planner's `MISSING_COPYBOOK` reason is unreachable. | P1 / medium-high: capability-truth drift on the dependency component and a false READY plan; final verdict still protected by generation's fail-closed errors and the NOT_VERIFIED central gate. | FIXED — `_analyze_copybook` fails closed: any reference that is `UNRESOLVED`, `AMBIGUOUS`, or without a resolved path (incl. mixed resolve/unresolve sets and names with no reference) classifies `UNSUPPORTED` with a reason naming the copybook and its resolution status; `_map_blocking_reasons` maps copybook reasons containing missing/unresolved/ambiguous to `MISSING_COPYBOOK` (was dead code); consuming-program verdict unchanged; resolved copybooks keep `SUPPORTED`. 15 focused tests in `tests/test_copybook_resolution_capability.py` wired into the `ci.yml` capability-truth gate; pre-fix defect proven (`bl033_pre_fix.txt`: all three unresolvable shapes `SUPPORTED` + plan `READY` + "No blocking issues identified" while generation failed). |
| BL-034 | Application discovery maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined with BL-035)** | Comment/inline-comment/literal masking helpers already present in `application_discovery.py` | `_extract_calls`/`_extract_copybooks` scanned raw source, so comment lines and string literals created phantom unresolved CALL/COPY dependencies: valid plans blocked with `UNRESOLVED_CALL` and a comment-only `COPY` failed generation. | P1 / medium: fail-closed on correct input (never fail-open), but it blocked valid workloads and polluted the Phase 3 graph with edges that do not exist. | FIXED — single literal-aware scanner (`_scan_call_copy`) replaces the raw regexes: comment lines blanked offset-preservingly, non-operand string literals and `*>` inline comments consumed whole by alternation priority, word guard against identifier suffixes. Real quoted/bare CALL/COPY still extract and still fail closed unresolved; USING handling and negative contracts unchanged. Probe also exposed and hardened a BL-033 residual (unanchored `"call"` substring matched "determi**call**y" → word-boundary match). 13 focused tests in `tests/test_phantom_dependency_masking.py`, wired into the `ci.yml` gate; pre-fix red proven (`%TEMP%\opencode\phase3\bl034_pre_fix.txt`); post-fix `bl034_post_probe.txt`; E2E `ORACLE_MATCH=YES 2/2`. |
| BL-035 | Copybook resolution maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined with BL-034)** | `test_copybook_m7.py` resolution-precedence contracts | Discovery searched every subdirectory recursively while generation searched only the source root and unit parents non-recursively — subdirectory layouts got `RESOLVED`/`READY` at plan time and `Missing COPY target` at generation. | P1 / medium-high for real corpora (copybook directories are conventional); the verdict and the artifact-producing path disagreed for the same tree. | FIXED — one shared deterministic search-directory builder `copybook_resolver.copybook_search_dirs` (root first, then every directory holding a file, sorted) feeds both lanes; `ApplicationDiscovery._copybook_search_dirs` delegates to it and `prepare_application_copybooks` uses exactly that set when `source_root` is given (unit-parent fallback only for the no-root legacy path). Non-recursive per-directory scan, ambiguity explicit in both lanes, resolver precedence untouched. 13 focused tests in `tests/test_copybook_search_path_parity.py`, wired into the `ci.yml` gate; pre-fix red proven (`%TEMP%\opencode\phase3\bl035_pre_fix.txt`); post-fix `bl035_post_probe.txt`; E2E `ORACLE_MATCH=YES 1/1`. |
| BL-036 | Parser / IR maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined cycle 5 with BL-026/BL-037/BL-038/BL-039)** | `CobolParser` statement splitting; discovery regex lane | Multi-line `CALL` (target/USING on following lines) produces zero `CallStatement`s and three `unparsed_statement` diagnostics while discovery records the edge — lanes disagree about the same statement. | P2 / medium for coverage, zero for trust: verdict honestly `UNSUPPORTED`, plan blocks (conservative), but the reason is wrong and valid formatting is rejected. | FIXED — the dispatcher required `"CALL "` (operand on the same line); a bare `CALL` line now routes into `_parse_call`, whose continuation loop joins the target/USING lines. Same IR as the single-line spelling (program-name/arguments/dynamics), zero split diagnostics, cross-lane edge parity. 13 focused tests in `tests/test_call_statement_parsing.py` (with BL-037), wired into the `ci.yml` gate; E2E multi-line CALL with a real LINKAGE callee `ORACLE_MATCH=YES`. |
| BL-037 | Parser / IR maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined cycle 5 with BL-026/BL-036/BL-038/BL-039)** | `CobolParser._parse_call`; arity analysis | `CALL … ON EXCEPTION …` swallows the phrase and its statement into the USING list → false arity 5 vs 1 → `UNSUPPORTED` with a factually wrong reason; planner maps it to `UNKNOWN_CONSTRUCT`. | P2 / medium: fail-closed, but the diagnostic claims an arity mismatch that does not exist and a standard CALL phrase is unparsed. | FIXED — `_parse_call` stops the USING capture at `ON EXCEPTION`/`ON OVERFLOW` (correct arity) and names the phrase in an explicit `UNSUPPORTED_CONSTRUCT` diagnostic; the planner maps linkage-arity failures to a new `ARITY_MISMATCH` `BlockingReason` instead of `UNKNOWN_CONSTRUCT`. Verified: correct arity + phrase named + no false-arity reason + `ARITY_MISMATCH` in the plan summary; tests in `tests/test_call_statement_parsing.py`; E2E onexc plan `BLOCKED` with the phrase named, oracle handler truth captured. |
| BL-038 | Application discovery maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined cycle 5 with BL-026/BL-036/BL-037/BL-039)** | Edge-metadata stamping (`resolution=…` on `DependencyEdge`) | `ProgramCall.resolution` stays at its `UNRESOLVED` default even for resolved static calls, contradicting the edge metadata and the plan for the same call. | P2 / low: no verdict consumes the field (capability reads edge metadata), so no false classification is reachable; traceability-only. | FIXED — `_build_dependency_graph` stamps `ProgramCall.resolution` from the same decision that stamps the edge metadata (frozen dataclass replaced, unit tuple rebuilt before the application is constructed). Verified: resolved static `RESOLVED`, missing static `UNRESOLVED`, dynamic never resolves even with a coinciding program-id, and a 3-call invariant test pins record == edge; 4 focused tests in `tests/test_call_resolution_truth.py`, wired into the `ci.yml` gate. |
| BL-039 | Capability maintainer | **Phase 3 (fixed in-cycle 2026-10-13, combined cycle 5 with BL-026/BL-036/BL-037/BL-038)** | BL-031's `_expand_copybook_text` (implemented) | `_analyze_copybook` scans only the top-level copybook file, so constructs inside nested copybooks — now materialized into the merged IR — are never classified. | P2 / medium-low: potential false `SUPPORTED` COPYBOOK component for nested content; bounded to data-division constructs in nested files. | FIXED — `copybook_model.collect_copybook_texts` walks the top-level file plus every reachable nested COPY target (same strict resolver, cycle-guarded, nested problems recorded as the same `ERROR` diagnostics generation fails on); `_analyze_copybook` scans per file with the shared search-directory authority (`analyze(..., source_root=...)`, threaded from planner and pipeline). Reason names the nested file carrying the worst-level keys; nested problems fail the component closed with generation's own message; flat copybooks keep the exact legacy reason. 9 focused tests in `tests/test_copybook_capability_transitivity.py`, wired into the `ci.yml` gate; E2E nested2 `ORACLE_MATCH=YES`. |
| BL-040 | Parser / IR maintainer | **Phase 4 (cycle A — fixed in-cycle 2026-10-14)** | Period-bound statement termination in the parser | §53.9 forbids silent semantic loss; P0 per §77 (green-verdict-over-wrong-program shape). | Residual: same-line two-statement spelling out of scope (line-oriented statement model, applies to every verb). | FIXED — `_parse_string` period-bounded + verb/scope-terminator boundary (word-boundary matched, `_STRING_CONTINUATION_STOP` derived from the dispatcher verb vocabulary); complete-unterminated STRING stays lenient/lossless, incomplete fails closed via `_emit_unparsed`; 12 focused tests in `tests/transformation/test_string_period_termination.py` wired into the `ci.yml` gate; pre-fix red 7/4 proven (`%TEMP%\opencode\phase4\bl040_pre_fix.txt`); gate 440 passed; no existing test weakened. |
| BL-041 | Java generator maintainer | **Phase 4 (cycle B — fixed in-cycle 2026-10-14)** | `_stmt_to_string` (already renders every statement type) | Silent statement drop contradicts the no-silent-loss invariant; reachable path confirmed (`_derive_generation_mode` selects `file_io` for `caps.input_record_mapping`). | Residual: empty `JavaBlock` now fails closed instead of rendering as no-op (fail-closed direction). | FIXED — all main-body statements rendered via `_stmt_to_string` into the main body in source order (comments keep record-loop placement); unmapped/empty rendering fails closed `MISSING_REQUIRED_SEMANTIC` naming the type; dead `stmt_str` removed; audit claim "RETURN dropped" corrected (JavaReturn carries `.expression`; regression test pins it); 7 focused tests in `tests/transformation/test_file_io_main_body_rendering.py` wired into the `ci.yml` gate; pre-fix red 5/2 proven (`%TEMP%\opencode\phase4\bl041_pre_fix.txt`); generator/file-lane regression 168 passed; no existing test weakened. |
| BL-042 | Transformation producer maintainer | **Phase 4 (cycle C — fixed in-cycle 2026-10-14)** | `to_contract_diagnostic` helper in `diagnostics.py` (enum→string boundary conversion) | Producer contract violated at the source; consumers crashed (dict) or mis-reported (enum level vs string compare). | Residual: legacy `producer.py` result (`errors: tuple[str,…]`, no diagnostics field) is a separate contract, out of scope by design. | FIXED — every producer diagnostic is a `contracts.Diagnostic` (internal-native converts `diagnostics.all` + real `Diagnostic` on the exception path; adapter wraps all five sites); 6 focused tests in `tests/transformation/test_producer_diagnostics_contract.py` wired into the `ci.yml` gate; pre-fix red 5/1 proven (`%TEMP%\opencode/phase4/bl042_pre_fix.txt`); old dict-shape assertions in `test_producer_contract.py` aligned to attribute access (strengthening, documented); transformation+integration regression 2257 passed / 0 failed. |
| BL-043 | Modernization planner maintainer | **Phase 4 (cycle B — fixed in-cycle 2026-10-14)** | `_build_program_plan` fail-closed default (UNKNOWN + `UNKNOWN_CONSTRUCT`) | Fail-open default contradicts the fail-closed program default (capability truth). | None — the fail-closed default cannot green-light missing analysis. | FIXED — `_build_copybook_plan`/`_build_file_plan` mirror the program path (`cap=None` ⇒ `UNKNOWN`, "No copybook/file capability analysis available", `UNKNOWN_CONSTRUCT`, `SKIP`/`SKIP` strategies); 7 focused tests in `tests/transformation/test_planner_missing_component_fail_closed.py` wired into the `ci.yml` gate; pre-fix red 5/2 proven (`%TEMP%\opencode\phase4\bl043_pre_fix.txt`); planner-dependent regression batch 189 passed; no existing test weakened. |
| BL-044 | Application discovery maintainer | **Phase 4 (cycle B — fixed in-cycle 2026-10-14)** | Shared `normalize_cobol_name` in `engine/transformation/ir.py` | One CALL fact could contradict itself across lanes (BL-038 class). | None for program-id joins; other name spaces (copybook stems, file names) still compare as-spelled pending a demonstrated contradiction. | FIXED — shared uppercase normalization applied to every program-id join (discovery known_programs/target check; analyzer arity by_id/target, `program_levels` keys/callee lookup; self-CALL checks in `_analyze_call` and planner fallback); spelling of `target`/edge preserved, only comparisons normalize; 7 focused tests in `tests/transformation/test_call_name_case_normalization.py` wired into the `ci.yml` gate; pre-fix red 4/3 proven (`%TEMP%\opencode\phase4\bl044_pre_fix.txt`); CALL/discovery/analyzer/planner regression batch 249 passed; no existing test weakened. |
| BL-045 | Mapping maintainer | Phase 12 (carry-forward 2026-10-14 — Phase 3 lane item, not scheduled in Phase 4) | `called_programs` collector threading | Nested CALLs lose resolution metadata (coverage/provenance). | Incomplete program references in mapping output. | Nested CALL contributes to called_programs; focused + regression tests green. |
| BL-046 | Spring Boot generator maintainer | Phase 12 (carry-forward 2026-10-14) | Native escaping helper (BL-030) | Lane divergence: invalid Java or wrong values for quotes/backslashes. | Emitted literals can diverge from the oracle-verified native lane. | Both lanes emit identical escaped literals; focused test green. |
| BL-047 | API maintainer | Phase 11 (carry-forward 2026-10-14) | None | Silent file loss on accepted uploads; documented collision contract unreachable. | Downstream transformation runs on incomplete sources. | Duplicate-name upload fails closed named; security suite green. |
| BL-048 | API/service maintainer | Phase 11 (carry-forward 2026-10-14) | None | Failed re-upload destroys the previous source (data-loss on error path). | Record points at a deleted directory after a rejected upload. | Failed re-upload preserves the previous directory; service tests green. |
| BL-049 | API maintainer | Phase 11 (carry-forward 2026-10-14) | None | Error-path correctness: 500 instead of 401 on non-ASCII tokens. | Availability/log noise only; no bypass. | Non-ASCII token yields 401; security tests green. |
| BL-050 | Candidate adapter maintainer | **FIXED 2026-10-15 (Phase 9 batch P2a)** | Shared cleanup helper | Timeout path masks the real error and leaks a container. | Leaks accumulate on the daemon; diagnostics mislead. | FIXED: compile() initializes `proc = None` (parity with execute()); timeout returns the real message and always cleans the container; focused test green. |
| BL-051 | Oracle adapter maintainer | **FIXED 2026-10-15 (Phase 9 batch P2a)** | Shared cleanup helper (Stage D) | Timed-out oracle containers persist; no parity with candidate cleanup. | Daemon resource leak on the hot verification path. | FIXED: oracle `docker run` gains a deterministic `--name`; timeout path kills client + calls shared `cleanup_container`; focused test green. |
| BL-052 | Comparator maintainer | **Phase 4 (cycle C — FIXED 2026-10-14)** | None | Byte-exactness must cover every byte; floor division ignores tails. | Latent false MATCH via metadata mismatch (V1 pipeline unaffected today). | Partial trailing records mismatch; comparator tests green. **FIXED**: explicit tail comparison after the record loop reports `trailing_partial_record`; test_fixed_record_trailing_partial.py (9) red 5/1 → green; regressions 282 + 172 passed; gate-wired. |
| BL-053 | Verdict maintainer | Phase 10 (carry-forward 2026-10-14) | None | Trust-boundary TOCTOU: post-validation mutation is trusted verbatim. | Future callers can accidentally bypass the seal. | Mutated manifest fails derivation closed; verdict tests green. |
| BL-054 | Candidate adapter / pipeline maintainer | **FIXED 2026-10-15 (Phase 9 batch P2a)** | None | Build output written into the identity tree ⇒ non-reproducible hashes. | Non-reproducible evidence identity on the Spring Boot lane. | FIXED: candidate identity walk skips top-level `target/`; repeated builds ⇒ identical candidate_hash; focused test green. |
| BL-055 | Parser / IR maintainer | **Phase 4 (cycle C — FIXED 2026-10-14)** | None | Lowercase valid COBOL crashes instead of diagnosing. | Unhandled IndexError on lowercase PERFORM UNTIL/VARYING. | Lowercase forms parse identically to uppercase; parser tests green. **FIXED**: shared case-insensitive UNTIL split in both inline branches (guard/split can no longer disagree; also fixes multi-space spellings); test_perform_lowercase.py (6) red 5/1 → green; regression 81+37 passed; gate-wired. |
| BL-056 | Copybook materialization maintainer | **Phase 4 (cycle C — FIXED 2026-10-14)** | None | Decode errors escape OSError handlers; lanes can disagree on one file. | Crash instead of COPYBOOK_UNREADABLE; analyzer/materializer divergence. | Binary copybook ⇒ COPYBOOK_UNREADABLE in all lanes; copybook tests green. **FIXED**: all three copybook read sites (`_expand_copybook_text`, `collect_copybook_texts`, `prepare_application_copybooks`) catch `(OSError, UnicodeError)`; analyzer copybook reader is strict UTF-8 taking the read-failure path; `tests/test_copybook_decode_fail_closed.py` (8) red 8/0 (all raw UnicodeDecodeError, `%TEMP%\opencode\phase4\bl056_pre_fix.txt`) → green; regressions 239 + 441 passed; gate-wired. |
| BL-057 | CICS lane maintainer | **Phase 7 (carry-forward 2026-10-14; FIXED 2026-10-15, committed `8f107d2`, status reconciled + re-verified this session: 55 passed)** | Shared escaping helper (BL-046) | Python repr() quoting emits invalid Java. | Uncompilable CICS-lane output (fail-closed at javac). | FIXED — CICS generation emits valid Java string literals (double-quoted with escaping in `_java_arg`); focused `test_cics_java_literal_quoting.py` + CICS regression green (55 passed, `bl057_verify_green.txt`); no cics test weakened. |
| BL-058 | Parser / IR maintainer | **Phase 7 (fixed in-cycle 2026-10-15 — defect-proven-first; design call recorded in the section)** | Shared `parse_data_description_lines` hierarchy + roots+leaves top-level expansion (mirrors `materialize_copybooks_into_program`) | WS group node dropped, children flattened to level 1 or vanished, 88-level dropped, REDEFINES uncaptured — all diagnostic-free (probe-confirmed). | FILE SECTION stays flat (separate lane, documented). | FIXED — `_parse_working_storage` delegates to the hierarchical parser; 7 focused tests gate-wired (`ci.yml` 47 files, bare-venv `656 passed`); pre-fix red 5/2 and post-fix green 7/7 (`%TEMP%\opencode\phase7\full_sweep_docker.txt`, `bl058_post_fix.txt`); transformation suite `2019 passed`; no existing test weakened. |
| BL-059 | IR/capability maintainer | **Phase 4 (cycle C — FIXED 2026-10-14)** | None | Capability walker under-reports arithmetic and inline bodies (conservative). | Valid programs blocked more than reality requires. | Capability reflects all arithmetic at any depth; capability tests green. **FIXED**: `has_arithmetic` covers all five statement types; `_flatten_statements` walks inline-PERFORM bodies and INVALID KEY/NOT INVALID KEY bodies of READ/START/WRITE/REWRITE/DELETE; `test_capability_walker_depth.py` (15) red 12/3 (controls green) → green; transformation regression 1919 passed / 0 failed; gate-wired. |
| BL-060 | SQL lane maintainer | **Phase 6 (batch P2 - fixed in-cycle 2026-10-15)** | None | Error handler itself raises ValueError (invalid sentinel). | None once fixed: `-1`/`'56000'` is an explicit documented lane sentinel (`SQLCODE_UNMAPPED_ERROR`/`SQLSTATE_UNMAPPED_ERROR`), never a claim about the exact DB2 code. | FIXED - red `bl060_pre_fix.txt` (collection ImportError: sentinel constants absent; behavioral `ValueError` crash proven by audit probes A2/B); `Db2SqlStatus.unmapped_error` added, both handler sites wired; new `tests/test_db2_unmapped_error_statuses.py` (4 tests, gate-wired, bare-venv `635 passed`); focused green `4 passed`, SQL-lane regression `2098 passed / 4 skipped`; no existing test weakened. |
| BL-061 | SQL lane maintainer | **Phase 6 (batch P2 - fixed in-cycle 2026-10-15)** | None | Cursor bind handoff missing (DECLARE discards binds; re-masking masked SQL at OPEN); harness passed no bindings at OPEN; `execute()` misroutes unanalyzed IR. | None once fixed: genuinely missing OPEN bindings fail loud with the host variable named (`KeyError`). | FIXED - red `bl061_pre_fix.txt` (4 failed), focused green `4 passed` (`bl061_focused_green.txt`); DECLARE-time bind plan stored in `_CursorState.bind_info` (carried through OPEN/FETCH), OPEN binds from the workload's OPEN statement entry (DB2 semantics), `execute()` fails closed (TypeError for unanalyzed IR with analyzer hint, ValueError naming unknown types), dead `_bind_from_sql` removed; new `tests/test_db2_cursor_host_variable_lifecycle.py` (4 tests, gate-wired); SQL-lane regression incl. golden-trace workload `2098 passed / 4 skipped`. |
| BL-062 | SQL parser maintainer | **Phase 6 (batch P2 - fixed in-cycle 2026-10-15)** | None | Column-less INSERT mis-parses VALUES as columns. | Column set undetermined from text alone stays empty (documented; execution uses raw_sql). | FIXED - red `bl062_pre_fix.txt` (`2 failed, 1 passed` - explicit-column control green), focused green `3 passed` (`bl062_focused_green.txt`); column list parsed only from parens between table name and VALUES, values from parens after VALUES; analyzer `write_columns` stays `()` for the column-less form; in `tests/transformation/test_sql_clause_fidelity.py` (gate-wired); SQL-lane regression `2098 passed / 4 skipped`. |
| BL-063 | JCL lane maintainer | **Phase 5 (batch P2 - fixed in-cycle 2026-10-15)** | Shared discovery matcher (`is_jcl_member` / `find_jcl_members`) | Consumer's file selection diverges from discovery; decode errors escape; basename keys silently overwrite colliding members; API presence gate blind to non-`*.jcl` members. | Path-keyed sources (strictly stronger than collision reporting: collisions cannot occur); `JCL_SOURCE_DECODE_FAILED` ERROR fail-closed. | FIXED - red in `bl063_pre_fix_import.txt` (matcher absent) + `bl063_pre_fix.txt` (`6 failed/8 passed` behavioral); shared rule used by discovery + consumer + API gate; decode diagnostics via `pre_diagnostics`; focused green `14 passed`, JCL regression `255 passed`, Docker-gated `5 passed`; gate-wired (12 matcher/decode tests; the 2 API-parity tests split to `tests/test_jcl_api_discovery_parity.py` post-push — the gate is dependency-free, `api.service` needs the runtime stack; change-log (ab)). |
| BL-064 | Spring Boot generator maintainer | **Phase 4 (cycle C — FIXED 2026-10-14)** | None | Duplicate model emission produces duplicate classes. | Uncompilable output for copybook workloads on that lane. | Each model emitted once; generator tests green. **FIXED**: blame-proven duplicate loop removed (accidental re-add `fa0fa62a` over original M7 loop), single emission site pinned; `test_spring_model_emission_unique.py` (4) red 3/1 → green; regressions 1923 + 100 passed; gate-wired. |
| BL-065 | Java generator maintainer | Phase 12 (carry-forward 2026-10-14) | Legacy-region inventory decision | Unimported IR classes in legacy branches ⇒ NameError. | Crash path; confusing diagnostics. | No NameError path remains; generator tests green. |
| BL-066 | Modernization planner maintainer | Phase 12 (carry-forward 2026-10-14) | Diagnostic-code plumbing | Prose substring mapping duplicates codes and breaks on wording changes. | Silent mis-mapping risk on future wording changes. | No prose substring mapping remains; planner + contracts tests green. |
| BL-067 | API maintainer | Phase 11 (carry-forward 2026-10-14) | None | Unbounded in-memory archive on an authenticated GET. | Memory exhaustion on pathological trees. | Cap enforced with a 4xx/413; API tests green. |
| BL-068 | Frontend maintainer | Phase 11 (carry-forward 2026-10-14) | None | Three state-lifecycle gaps: wrong-application display, invisible download errors, unbounded polling. | Customer-visible confusion; wasted polling load. | Each of the three has a focused test; type-check + tests + build green. |
| BL-069 | Parser / IR maintainer | **Phase 4 (cycle B — fixed in-cycle 2026-10-14)** | `_emit_unparsed` diagnostic channel (exists; ADD/SUBTRACT/DIVIDE already use it) | Standard `MULTIPLY a BY b BY c` and `ON SIZE ERROR` forms returned an empty IR node with zero diagnostics — silent statement loss (§53.9). | Residual: double-`BY`/`ON SIZE ERROR` forms remain UNSUPPORTED *with* a diagnostic until the regex is extended (coverage gap, not silent loss). | FIXED — `_parse_multiply` no-match branch mirrors ADD exactly (`_emit_unparsed("MULTIPLY", …)`; empty node after diagnostic is the shared contract); 10 focused tests in `tests/transformation/test_multiply_diagnostic.py` wired into the `ci.yml` gate; pre-fix red 5/5 proven (`%TEMP%\opencode\phase4\bl069_pre_fix.txt`); parser arithmetic regression green; no existing test weakened. |
| BL-070 | Parser / mapping maintainer | **Phase 4 (cycle B - fixed in-cycle 2026-10-14)** | Existing `_record_owner` map (built in `cobol_parser.py`) | REWRITE bound its file by string heuristic only (WRITE consults the FD owner map first); unbound REWRITE silently degraded to a comment with no diagnostic. | Residual: FD declaration now wins over the `-REC` convention for REWRITE (matches WRITE; FD is authoritative). | FIXED - `_parse_rewrite` consults `_record_owner` first, heuristic fallback (exact mirror of `_parse_write`); 5 focused tests in `tests/transformation/test_rewrite_binding.py` wired into the `ci.yml` gate; pre-fix red 2/3 regenerated by temporary hunk revert (`%TEMP%\opencode\phase4\bl070_pre_fix.txt`, mislabeled first capture noted in the entry); file-lane regression 104 + parser batch 27 green; no existing test weakened. |
| BL-071 | JCL lane maintainer + build/CI owner | **Phase 5 (batch P1 - fixed in-cycle 2026-10-15)** | `maven-offline-springboot` image rebuild (offline precache pom) | Generated JCL Spring Boot project cannot compile in the canonical offline build environment (`spring-boot-starter-batch` never precached) while the adapter docstring claims "it compiles, starts"; no test ever attempted the build. | Image digest changes cause `test-artifacts` provenance churn (regenerated, stays uncommitted by policy). | FIXED - red in `bl071_pre_fix.txt` (static + Docker compile) + `bl071_startup_pre_fix.txt` (startup exit 1, DataSource); precache pom + image rebuilt + `autoconfigure_excludes` (DataSource) in generated JCL properties; focused green `5 passed` (`bl071_focused_green.txt`): static gate-wired tests + Docker E2E compile `success=True` and execute `exit_code=0` printing `[STEP01]` markers; docstring cites `tests/integration/test_jcl_spring_boot_compile.py`; no existing test weakened. |
| BL-072 | JCL lane maintainer | **Phase 5 (batch P1 - fixed in-cycle 2026-10-15)** | None | Multiple JOB statements in one file are silently merged into a single job (first job's name lost, steps misattributed, status FULL, no diagnostic), contradicting the profile spec's "no silent dropping". | Two-job members produce a wrong job graph today with no signal. | FIXED - `parse_jobs` splits per JOB statement (`parse` keeps single-job contract); builder scans each raw source once with JOB-in-effect attribution; red 13/1 (`bl072_pre_fix.txt`) -> green 14 + 299 JCL regression; `tests/transformation/test_jcl_multi_job_parsing.py` `ci.yml`-wired. |
| BL-073 | JCL lane maintainer | **Phase 5 (batch P1 - fixed in-cycle 2026-10-15)** | Additive `ir.JclJob` field (mirrors prior additive IR changes) | Job-level DD statements (JOBLIB etc.) silently dropped from the IR with no diagnostic and never reach the dataset inventory, under status FULL. | Job-level DDs stay unmodeled in the Spring Batch representation (diagnosed + disclosed); they reach the dependency graph but not the dataset inventory. | FIXED - `JclJob.job_dd_statements` (additive) + `JCL_DD` edges (`<job>.<dd>`) + IR-based `JOB_LEVEL_DD` ERROR diagnostic -> status PARTIAL with `job-level DD statements` in the status contract; red 9/3 (`bl073_pre_fix.txt`) -> green 12 + 299 regression; `tests/transformation/test_jcl_job_level_dd.py` `ci.yml`-wired; no existing test pinned the drop. |
| BL-074 | JCL/discovery maintainer | **Phase 5 (batch P1 - fixed in-cycle 2026-10-15)** | None | `link_with_cobol` matches datasets to COBOL files by loose bidirectional substring and a file-name-keyed dict, producing phantom, wrong-target, and missing `COBOL_FILE` edges in the production ingestion graph with no ambiguity signal. | Legitimate DSN↔file relations that relied on true substring nicknames stop linking (fail-closed under-linking instead of phantom over-linking). | FIXED - `_dataset_matches_file` (exact/qualified-tail, case-insensitive), one edge per matching program, `resolution=RESOLVED|AMBIGUOUS` metadata; red 6/3 (`bl074_pre_fix.txt`) -> green 9 + 299 regression incl. existing linker tests; `tests/transformation/test_jcl_cobol_file_linking.py` `ci.yml`-wired. |
| BL-075 | JCL parser maintainer | **Phase 5 (batch P2 - fixed in-cycle 2026-10-15)** | None | Compound `DISP=`/`SPACE=` values silently truncated by a paren-unaware comma split (`DISP=(NEW,CATLG,DELETE)` stored as `"(NEW"`); weak test assertion tolerated it. | Non-parenthesized exotic DISP forms remain bounded to the documented subset. | FIXED - red in `bl075_pre_fix.txt` (`5 failed/3 passed`); shared `_split_parameters` used by `_parse_dd` + `_parse_parameters`; new `test_jcl_dd_parameter_fidelity.py` (8 tests, gate-wired); weak assertion strengthened to exact equality; focused green `82 passed`; none weakened. |
| BL-076 | JCL dependency maintainer | **Phase 5 (batch P2 - fixed in-cycle 2026-10-15)** | None | Application-graph step-order edges diverge between lanes: `build_all_dependencies` omits the edge after a COND step while the semantic builder emits it; `api/ingestion.py` publishes the incomplete set. | None once both lanes agree. | FIXED - red in `bl076_pre_fix.txt` (`3 failed/3 passed`); every consecutive pair emitted, COND disclosed as `job=…;cond=<code>` metadata; new `test_jcl_step_order_parity.py` (6 tests incl. lane parity + controls, gate-wired); vacuous `test_conditional_step_no_order_dependency` strengthened to pin the edge; focused green `193 passed`. |
| BL-077 | JCL lane maintainer | **Phase 5 (batch P2 - fixed in-cycle 2026-10-15)** | BL-072/BL-073 for the roadmap-label item | JCL lane hygiene: dead `dd.sysin` condition, never-raised `JclParseError`, never-populated `JclDatasetFlow.disposition`, never-emitted `"JCL"` capability component type, stale `JCL_INTEGRATION_CONTRACT` status/basename example, overstated roadmap label. | Reader confusion / latent drift. | FIXED - red in `bl077_pre_fix.txt` (`4 failed/1 passed`, one absence-pin per dead construct + live-branch control); all six lettered items fixed; `test_jcl_lane_hygiene.py` (5 tests) pins the removals, gate-wired; ruff inapplicable (no lint config/job, change-log (x)); JCL suites green. |
| BL-078 | SQL parser maintainer | **Phase 6 (batch P1 - fixed in-cycle 2026-10-15)** | None | WHERE-predicate string literals uppercased into the semantic model (`'abc'` → `'ABC'`); whole operand text split after `.upper()`. | None. | FIXED - red `3 failed/1 passed` (`bl078_pre_fix.txt`); literal-masked operator search + original-text slicing + DB2 identifier folding; `test_sql_predicate_fidelity.py` gate-wired (bare-venv `615 passed`); focused `14 passed`, SQL regression `223 passed`; no existing test weakened. |
| BL-079 | SQL parser + analyzer maintainer | **Phase 6 (batch P1 - fixed in-cycle 2026-10-15)** | Additive `ir.SqlSelect/SqlUpdate/SqlDelete.where_predicates` fields | Compound AND/OR, IN, and BETWEEN WHERE predicates mangled into invented fake column names (`'1 AND BAL = 2'`, `'(1, 2, 3)'`, `'100 AND 500'`) flowing into `read_columns`/`Db2TableUsage`/`Db2TableDependency`; `right_list`/`left_operand`/`right_operand` IR fields never populated. | AND/OR grouping recorded as a flat conjunct list (documented: no boolean tree invented). | FIXED - red `8 failed/5 passed` (`bl079_pre_fix.txt`); quote/paren-aware conjunct splitting (BETWEEN protected), never-fabricate `_is_simple_operand` rule, IN/BETWEEN IR fidelity, analyzer collects every conjunct; underscore-identifier boundary caught by existing suite mid-fix (`1 failed/213 passed`) and pinned; focused `14 passed`, SQL regression `223 passed`, gate-wired (bare-venv `615 passed`); no existing test weakened. |
| BL-080 | SQL parser + analyzer maintainer | **Phase 6 (batch P1 - fixed in-cycle 2026-10-15)** | Additive `ir.EmbeddedSqlBlock.unsupported_statements` field | Unsupported EXEC SQL statements (`BEGIN DECLARE SECTION`, `INCLUDE`, `WHENEVER`, `DECLARE … STATEMENT`) silently dropped with zero diagnostics; `EXECUTE IMMEDIATE` classified as plain EXECUTE (`execute_immediate` never set). | Statements unmodeled but preserved + diagnosed. | FIXED - red `5 failed/3 passed` (`bl080_pre_fix.txt`; one of the five was the new test's own `;`-delimiter expectation, corrected post-red with inline disclosure); else-branch + None-parse capture, analyzer validation entries, `execute_immediate` wiring, dead `cursor_declarations` list removed; focused `223 passed`, gate-wired (bare-venv `615 passed`); no existing test weakened. |
| BL-081 | SQL parser + analyzer maintainer | **Phase 6 (batch P2 — fixed in-cycle 2026-10-15)** | Additive `ir.SqlJoin.on_predicates` field | JOIN tables/ON conditions silently lost though `SqlSelect.joins` exists (`T2` absent from dependency truth while SELECT list references `B.NAME`). | CROSS JOIN / no-ON segments parse by construction but stay outside the focused subset (documented); comma form remains in `from_tables`. | FIXED - red `bl081_pre_fix.txt` (`4 failed, 1 passed` — non-join control green) + `bl081_deps_pre_fix.txt` (`1 failed`, baseline-parser capture of the second dependency door); JOIN segments parsed into `joins` with ON conjuncts (BL-079 splitter; first conjunct also `on_condition`), analyzer table usage/`table_refs`/read columns and `extract_table_dependencies` include joined tables, FROM section bounded at the next clause keyword; focused green `6 passed` (`bl081_focused_green.txt`); SQL-lane regression `2098 passed / 4 skipped`. |
| BL-082 | SQL parser maintainer | **Phase 6 (batch P2 — fixed in-cycle 2026-10-15)** | None | ORDER BY column names swallow trailing `FETCH FIRST n ROWS ONLY` text (`'ACCT FETCH FIRST 5 ROWS ONLY'`). | None once bounded. | FIXED - red `bl082_pre_fix.txt` (`1 failed, 2 passed` — both controls green), focused green `3 passed` (`bl082_focused_green.txt`); ORDER BY slice bounded at `FETCH FIRST` by offset search over the original text; in `tests/transformation/test_sql_clause_fidelity.py` (gate-wired); SQL-lane regression `2098 passed / 4 skipped`. |
| BL-083 | Platform integration owner | **Phase 6 (audited 2026-10-15 - disclosed, deferred to Phase 10 by design decision)** | None | SQL lane never reaches the platform ledger: `DependencyKind.DB2` has no product producer; `sqlcode_field` unconsumed in `engine/`/`api/`. | Platform dependency inventory excludes DB2 tables (lane truth correct; docs claim only "parsed and classified"). | DISCLOSED - register + roadmap P3-7 state the gap (roadmap disclosure added with batch-P2 docs 2026-10-15); Phase 6 verdict limitations to be written at completion; no documentation overstates platform visibility; producer wiring scheduled for the integrated-proof phase. |
| BL-084 | Capability/registry maintainer | **Phase 7 (filed OPEN 2026-10-15 by the audit-first probe; FIXED 2026-10-15 — batch 1: pattern + registry key + matrix/roadmap rows + 14 focused gate tests, bare-venv gate 649 passed pre/post wiring)** | None | IMS (`EXEC DLI`) never detected or classified: no `_SOURCE_PATTERNS` entry, no `CONSTRUCT_REGISTRY` key (roadmap Rung 0). | IMS applications rejected with generic reasons; no IMS classification anywhere (verdict already fails closed — no false SUPPORTED). | Detection fires only on real `EXEC DLI` statements (comment/literal masked); registry `level`/`effective_source_level` = `UNSUPPORTED`; analyzer PROGRAM reason names `EXEC DLI`, never `SUPPORTED`; deterministic re-scan; existing fail-closed diagnostics kept; focused gate tests green. |
| BL-085 | Capability/registry maintainer | **Phase 7 (filed OPEN 2026-10-15 by the audit-first probe; FIXED 2026-10-15 — batch 1: pattern + registry key + matrix/roadmap rows + 14 focused gate tests, bare-venv gate 649 passed pre/post wiring)** | None | IBM MQ (`EXEC MQI`) never detected or classified: no `_SOURCE_PATTERNS` entry, no `CONSTRUCT_REGISTRY` key (roadmap Rung 0); queue names never extracted as dependencies. | MQ applications invisible to classification and to the dependency graph (verdict already fails closed — no false SUPPORTED). | Detection fires only on real `EXEC MQI` statements (comment/literal masked); registry `level`/`effective_source_level` = `UNSUPPORTED`; analyzer PROGRAM reason names `EXEC MQI`, never `SUPPORTED`; deterministic re-scan; existing fail-closed diagnostics kept; focused gate tests green. |
| BL-086 | Capability/registry maintainer | **FIXED 2026-10-15 (Phase 7 batch 3; roadmap P3-5 / Master README §29)** | None | Was: external utilities / system services / VSAM specifics were Rung 0 — no `_SOURCE_PATTERNS`, no `CONSTRUCT_REGISTRY` keys (RELEASE, IDCAMS, ORGANIZATION INDEXED/RELATIVE, ACCESS DYNAMIC, RECORD KEY). | Phrase coverage stays a documented detection-first subset (covered phrases only). | Shipped: 6 patterns + UNSUPPORTED registry keys, analyzer pre-PROCEDURE data door extended, SEMANTIC_PROOF_MATRIX rows, 15 focused gate tests; no IR, no mapper, no runtime, no equivalence claim. |
| BL-087 | Integration/ledger maintainer | **FIXED 2026-10-15 (Phase 7 batch 3; roadmap P3-6)** | None | Was: MQ queue names and IMS PCB/segment references never entered the platform dependency ledger — `extra_dependencies` had no producer. | Extraction stays bounded to the documented statement forms (`QUEUE(…)`/`Q(…)`, `PCB(…)`/`PCB NAME=…`, `SEGMENT(…)`/`SEGMENT NAME=…`). | Shipped: `external_dependency_edges` extractor + `DependencyKind.MQ`/`IMS` visible/BLOCKED/required entries + `api.service` wiring + 14 focused gate tests; no runtime, no equivalence claim. |
| BL-088 | Runtime-adapter architecture maintainer | **FIXED 2026-10-15 (Phase 8 batch P0; `2917a4f`, exact-SHA CI 4/4 green)** | None | §32 absent: no `target_runtime` config keys (red probe `bl088_red_probe.txt` TypeError), hardcoded `_assemble_spring_boot`, plan `output_type` hardcoded `SPRING_BOOT`. | Without fail-closed validation + truthful plan output_type, a future non-spring target would report Spring artifacts (capability-truth/config-loss shape). | FIXED: `runtime_adapters.py` seam + fail-closed §32 keys + registry dispatch + truthful plan output_type + pre-phase lookup; 36 focused gate tests; default spring output byte-identical; `_fill_discovery` report-rebuild bug found+fixed by the new tests. |
| BL-089 | Runtime-adapter maintainer | **FIXED 2026-10-15 (Phase 8 batch P1)** | BL-088 | `plain_java` unreachable: `JavaGenerator` emits sources+main only (no pom), no assembly adapter, no API selection surface. | Missing capability (not silent loss today); plain-java build/runtime evidence deferred to Phase 9. | FIXED: `PlainJavaRuntimeAdapter` + registry + store/API `target_runtime` (schema migration 4) + plan `NATIVE_JAVA` + report limitation; 5 focused engine tests + API surface checks; spring default unchanged; build/runtime deferred to Phase 9. |
| BL-090 | Runtime-adapter maintainer | **FIXED 2026-10-15 (Phase 8 batch P2)** | BL-088 | `jakarta_ee` target absent (§32 initial target) + Phase 8 breadth docs. | Generation profile only: offline repo has no Jakarta EE artifacts — no build/runtime evidence claimable (Rung 0–1, bounded). | FIXED: `JakartaEeRuntimeAdapter` (shared IR/sources, distinct Jakarta-marked pom profile) + registry + plan `JAKARTA_EE` + report limitation; 3 focused tests + synthetic fail-closed guard coverage; spring/plain unaffected; no build/runtime claim. |

### PR disposition snapshot — 2026-10-10

- **PR #1:** [feat: harden universal modernization readiness](https://github.com/Shankar373/Cobol-Java-Transformation/pull/1) — stale base `codex/remote-docker-ci`; re-diff or close as superseded. Not merged/closed/retargeted.
- **PR #2:** [fix: align capabilities with semantic transformation support](https://github.com/Shankar373/Cobol-Java-Transformation/pull/2) — base `main`; head tracks `codex/universal-core`. At the Phase 0 closure SHA `9326f80` all required checks are green (Push CI #465, PR CI #466) and `mergeable_state=clean`. Remains **open and unmerged** pending explicit human authorization (BL-015). No assistant-driven merge.
- **PR #3:** [P0 validation completion candidate](https://github.com/Shankar373/Cobol-Java-Transformation/pull/3) — validation-only, stale unique tests fail against current code; keep unmerged.
- **PR #6:** [fix: preserve structured arithmetic overflow semantics](https://github.com/Shankar373/Cobol-Java-Transformation/pull/6) — superseded/broken test syntax; not merged/closed.
- No PR was merged, closed, retargeted, or approved as part of this remediation.
