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

### BL-010 — Docker-dependent validation blocked on this host
- **Type:** operations/environment
- **Status:** BLOCKED (environment)
- **Observed behavior:** The Windows/WSL2 Docker bind-mount and cgroup issue prevents
  Docker-in-Docker binding on this workstation. Java/Node are also absent locally.
- **Expected behavior:** Master README Sections 34/50 — Docker is authoritative and
  fresh E2E must run; blocked Docker validation must use the Linux CI environment.
- **Impact:** Docker-backed backend/oracle/fresh-E2E gates cannot be re-run locally.
- **Remediation:** Do not retry Docker-in-Docker or change WSL2/kernel/cgroup/Docker
  security settings (explicit instruction). Run Python-only regression locally and
  rely on Linux CI for Docker-dependent validation.
- **Verification level:** environment-observed.

---

## P2 — coverage, quality, documentation

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
- **Status:** OPEN — verified by direct probing at HEAD `c312eb9`, **not fixed**
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
- **Status:** OPEN — verified by direct probing, **not fixed**
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
- **Status:** OPEN — verified by direct probing, **not fixed**
- **Observed behavior:** `WHEN OTHER DISPLAY "X"` is folded into the WHEN chain
  as an ordinary value (`A = DISPLAY OR A = "X"`) rather than becoming the
  `else` branch. No diagnostic; verdict SUPPORTED.
- **Affected files:** `engine/transformation/cobol_parser.py`.
- **Remediation (NOT yet implemented):** map the `OTHER` arm to
  `IfStatement.else_body`.
- **Verification level:** STATIC + reproduced locally.

### BL-023 — `COMPUTE A = 2 ** 3` exponentiation mis-parsed
- **Type:** defect (silent semantic loss; numeric semantics)
- **Status:** OPEN — verified by direct probing, **not fixed**
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
- **Status:** OPEN — verified by direct probing, **not fixed**
- **Observed behavior:** `COMPUTE A = FUNCTION MIN(1, 2)` parses to
  `FieldReference(name='FUNCTION MIN(1, 2)')` — an identifier that cannot exist,
  mapping to an undeclared Java variable. No diagnostic; verdict SUPPORTED.
  This is structurally the *same* defect class as BL-018 (a non-field operand
  mis-modelled as a field), which is why it is filed explicitly rather than
  assumed covered.
- **Affected files:** `engine/transformation/cobol_parser.py` (`_build_expression`).
- **Remediation (NOT yet implemented):** recognise the `FUNCTION` prefix and
  either map the certified intrinsic subset or emit an explicit diagnostic;
  never fall through to a bare field reference.
- **Verification level:** STATIC + reproduced locally.

### BL-019 — `NOT` in conditions is mangled into non-compiling Java
- **Type:** defect (silent semantic loss)
- **Status:** OPEN — found during BL-018 remediation, deliberately not fixed here
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
- **Remediation (NOT yet implemented — recorded for the next task):** replace
  the `NOT`/comparison replacement chain with quote-aware tokenisation that
  recognises `NOT` as an operator adjacent to a relational operator and emits
  `!(...)`, reusing the existing `_replace_bare_equals` quote-safety pattern.
  Must be done as its own change with its own positive/negative/regression
  tests so a BL-018-style fix cannot mask it.
- **Verification level:** STATIC + reproduced locally (not executed as a test
  yet, by design — no test was added while the behaviour is still broken and
  no existing test was weakened to accommodate it).

---

## Backlog change log

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
| BL-019 | Semantic transformation maintainer | Phase 1 | `map_cobol_condition_to_java` operator handling; existing quote-aware `_replace_bare_equals` pattern | Fix an independent pre-existing defect where `NOT` is blind string-replaced into a broken Java prefix. | Programs using `IF x NOT = y` / `IF x NOT > y` generate invalid Java with no diagnostic; BL-018's fix makes this more visible but does not cause it. | Replace the `NOT`/comparison replacement chain with quote-aware tokenisation emitting `!(...)`; add focused positive/negative/regression tests; generated Java for `NOT` conditions compiles; no existing test weakened. |
| BL-020 | Parser / IR maintainer | Phase 1 (highest priority) | `CobolParser._parse_evaluate` arm lowering | A `WHEN` arm's body statements are silently deleted while `EVALUATE` is certified SUPPORTED — the worst verified silent-loss defect found. | Any multi-branch `EVALUATE` loses its arm contents with no diagnostic; CI cannot detect it because nothing asserts on it. | Arm bodies are attached to the lowered `IfStatement`; unlowerable forms fail closed with a diagnostic; positive/negative/regression tests added to the fast capability-truth gate. |
| BL-021 | Parser / IR maintainer | Phase 1 | `WHEN` spec parsing; roadmap P1-11 | `ALSO` mis-lowered into a nonsense OR-chain. | Standard COBOL multi-value `WHEN` silently produces wrong control flow. | `ALSO` splits into one comparison per alternative; tests cover 2- and 3-way `ALSO`. |
| BL-022 | Parser / IR maintainer | Phase 1 | `WHEN OTHER` lowering | `WHEN OTHER` folded into the WHEN chain instead of becoming the `else` branch. | Fallback branch silently unreachable/incorrect. | `WHEN OTHER` maps to `IfStatement.else_body`; tests assert the else branch executes. |
| BL-023 | Numeric semantics maintainer | Phase 1 | `_build_expression` operator table; Master README §18 | `**` parsed as two `*` operators, producing an empty-named operand. | Silent wrong numeric result in a P0 risk area. | `**` is one operator or fails closed with a diagnostic; tests assert both behaviours. |
| BL-024 | Parser / IR maintainer | Phase 1 | `_build_expression`; same defect class as BL-018 | Intrinsic `FUNCTION MIN(...)` falls through to an impossible field reference. | Undeclared Java identifier, exactly the BL-018 pattern; unproven intrinsics must never be silently field references. | `FUNCTION` prefix recognised and either mapped for the certified subset or diagnosed; never a bare field reference. |

### PR disposition snapshot — 2026-10-10

- **PR #1:** [feat: harden universal modernization readiness](https://github.com/Shankar373/Cobol-Java-Transformation/pull/1) — stale base `codex/remote-docker-ci`; re-diff or close as superseded. Not merged/closed/retargeted.
- **PR #2:** [fix: align capabilities with semantic transformation support](https://github.com/Shankar373/Cobol-Java-Transformation/pull/2) — base `main`; head tracks `codex/universal-core`. At the Phase 0 closure SHA `9326f80` all required checks are green (Push CI #465, PR CI #466) and `mergeable_state=clean`. Remains **open and unmerged** pending explicit human authorization (BL-015). No assistant-driven merge.
- **PR #3:** [P0 validation completion candidate](https://github.com/Shankar373/Cobol-Java-Transformation/pull/3) — validation-only, stale unique tests fail against current code; keep unmerged.
- **PR #6:** [fix: preserve structured arithmetic overflow semantics](https://github.com/Shankar373/Cobol-Java-Transformation/pull/6) — superseded/broken test syntax; not merged/closed.
- No PR was merged, closed, retargeted, or approved as part of this remediation.
