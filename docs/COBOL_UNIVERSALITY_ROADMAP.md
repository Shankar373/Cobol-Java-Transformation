# COBOL Universality Roadmap

Workstream 7 — COBOL coverage / universality readiness.
Branch: `codex/universal-core`. Baseline: `fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4`.

This document is an **audit and planning artifact only**. It changes no engine
behavior, no registry, no verdict logic, and creates no speculative support.
Every status below was read from implementation source, tests, or fixtures —
never inferred from parser acceptance alone.

Companion machine-readable snapshot: `docs/cobol_coverage_registry.json`.
That file is a **report**, versioned and dated. It is NOT consumed by the
transformation lane and does NOT compete with the authoritative registry
(`engine/transformation/semantic_capability.py`), which remains the sole
source of capability truth for the analyzer and producers.

Determinism contract (preserved by this roadmap): deterministic parsing,
deterministic capability classification, deterministic transformation,
deterministic runtime proof, deterministic verdicts. No LLM anywhere.

Status vocabulary (used in every matrix cell):

| Value | Meaning in this document |
|---|---|
| SUPPORTED | Implemented on this layer AND backed by tests/evidence cited |
| PARTIAL | Bounded subset implemented; remainder explicitly out of scope |
| UNSUPPORTED | Known to be absent; lane fails closed (diagnostic / blocked verdict) |
| UNAVAILABLE | Requires infrastructure or an external system that is not present |
| UNKNOWN | Could not be determined from implementation/tests in this audit; must be verified before any claim |

A cell marked UNKNOWN is a task, not a claim.

---

## 1. Baseline

- Baseline commit `fedb7dd` ("fix: restore complete numeric semantic closure")
  verified present: `git cat-file -t fedb7dd…` → `commit`, log shows
  `fedb7dd / cf8c193 / 2272841`.
- HEAD at audit time: `e70ccbf` ("docs: align product status with current
  baseline fedb7dd and CI #417/#418"), one commit ahead of
  `origin/codex/universal-core`.
- Working tree is dirty with other workstreams' changes (api/, frontend/,
  tests/, untracked scratch files). This workstream touched none of them.
- Authoritative references reconciled: `docs/CAPABILITY_MATRIX.md`,
  `docs/SYSTEMAOPS_PRODUCT_STATUS.md`,
  `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` (dated 2026-09-21,
  describes an older dirty tree — treated as historical, not current truth),
  `docs/SEMANTIC_PROOF_MATRIX.md`.

## 2.Audit method

Read-only inspection of: `cobol_parser.py`, `ir.py`, `semantic_capability.py`,
`capability_analyzer.py`, `cobol_to_java_mapping.py`, `java_generator.py`,
`numeric_semantics.py`, `copybook_resolver.py` / `copybook_model.py`, CALL
handling (mapper + analyzer + planner), file lane (parser + mapper
`CobolFileIo` calls + `file_io_support_template.py`), JCL lane (`engine/jcl/`),
DB2 lane (`engine/sql/`), CICS lane (`engine/cics/` + `cics_parser.py` +
`cics_java_mapping.py`), oracle adapters (GnuCOBOL host + Docker),
`comparators/framework.py`, `evidence/`, `verdict/derivation.py`,
`integrated_proof.py`, producers (`internal_native.py`, `opensource4j.py`),
133 test files under `tests/`, 46 fixture dirs under `fixtures/`.

Executed verification (no engine changes): targeted pytest runs —
`test_parser.py` + `test_numeric_semantics.py` (103 passed),
`test_file_invalid_key_lane` + `test_file_semantics` + `test_cics_subset` +
`test_db2_status` + `test_jcl_semantic_model` + `test_copybook_m7`
(170 passed), `test_phase_d_negative_integration` +
`test_program_capabilities` + `test_call_linkage_mismatch` (93 passed);
plus a parse probe confirming `workload-comp`, `workload-comp3`,
`workload-occurs`, `workload-redefines`, `workload-level88` all parse
(4/4/3/4/3 working-storage items respectively).

## 3. Universality principle (adopted)

```
Universal analysis  !=  Universal transformation
                    !=  Universal runtime equivalence
                    !=  Universal certification
```

The correct behavior for an untransformable construct is the full chain:

```
EXEC CICS detected (source scan)
  -> Capability = CICS / UNSUPPORTED (registry)
  -> Reason = runtime equivalence unavailable (no CICS runtime lane)
  -> VERIFIED blocked (integrated_proof gate downgrades to NOT_VERIFIED)
```

This chain works today for EXEC CICS (negative scenario 8), EXEC SQL
(negative scenario 7), and PARTIAL/unsupported JCL (negative scenario 6),
proven by `tests/integration/test_phase_d_negative_integration.py`.
The roadmap extends this pattern: **detect and classify first, transform and
certify only with proof**. Anything in the matrix marked UNSUPPORTED with a
detection mechanism is a working universality feature, not a failure.

## 4. Current COBOL coverage (summary)

Proven subset (parser → IR → registry SUPPORTED → mapper → Java → GnuCOBOL
oracle → comparison → evidence → verdict, with targeted or end-to-end tests):

MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE (precision edges remain),
IF/ELSE, PERFORM (incl. TIMES/VARYING bounded loops), EVALUATE (lowered to
IF/ELSE), STRING, DISPLAY, STOP RUN, EXIT PROGRAM, static resolved CALL,
sequential LINE SEQUENTIAL files (OPEN INPUT/OUTPUT, READ loop, WRITE,
CLOSE), START/REWRITE/DELETE on indexed/relative with INVALID KEY branch,
COPY resolution/consumption, numeric DISPLAY PIC value semantics, 88-level
parse/IR (mapping unverified — see P0-3).

Bounded/partial: UNSTRING (certified delimited subset only), OPEN I-O/EXTEND
(detected, not reproduced), COMP/COMP-3 value semantics (storage encoding
explicitly out of scope per `numeric_semantics.py` boundary note), JCL/DB2/
CICS structural modeling without runtime equivalence.

Detected-but-blocked (universality working as designed): GO TO, SORT, MERGE,
ACCEPT, INITIALIZE, INSPECT, SEARCH, SET, ALTER, NEXT SENTENCE, GOBACK,
SIZE ERROR, EXEC CICS, EXEC SQL, dynamic/unresolved/cyclic CALL, arity
mismatch, non-sequential files outside boundary, sequential REWRITE,
DYNAMIC access, multi-file CLOSE, relational-word START, unresolved/
ambiguous/missing COPY.

## 5. Current enterprise dependency coverage

| Dependency | Detect | Classify | Transform | Runtime proof | Certify |
|---|---|---|---|---|---|
| COPY | SUPPORTED (deterministic resolver, fail-closed ambiguous/missing) | SUPPORTED (relationship, not standalone class) | SUPPORTED (consumed as source context; shared Java model) | SUPPORTED (`test_copybook_runtime`) | SUPPORTED subset |
| CALL static resolved | SUPPORTED | SUPPORTED | SUPPORTED (value-result linkage) | SUPPORTED (Phase-D A→B→C proof) | SUPPORTED subset, fail-closed negatives |
| CALL dynamic/unresolved/cyclic/arity-mismatch | SUPPORTED | SUPPORTED (UNSUPPORTED/PARTIAL + reason) | UNSUPPORTED (blocked) | UNSUPPORTED | Blocked by design |
| Sequential files | SUPPORTED | SUPPORTED (certified boundary) | SUPPORTED | SUPPORTED (integrated workload, 4 artifacts MATCH) | SUPPORTED subset |
| Indexed / relative files | SUPPORTED | PARTIAL (detected, rejected outside boundary) | PARTIAL (INVALID KEY lane only) | PARTIAL (fail-closed negatives) | NOT certified |
| JCL | SUPPORTED (parser + diagnostics) | PARTIAL (max PARTIAL by construction) | PARTIAL (Spring Batch structure) | UNAVAILABLE (no runtime lane) | NOT_VERIFIED by construction |
| DB2 / EXEC SQL | SUPPORTED (extractor + analyzer) | UNSUPPORTED for central lane (`runtime_verified_features()` empty by construction) | PARTIAL (SQLite harness = controlled semantics, not DB2 equivalence) | UNAVAILABLE (no DB2 subsystem) | NOT_VERIFIED by construction |
| CICS / EXEC CICS | SUPPORTED (parser recognizes superset of subset) | UNSUPPORTED outside subset v1.0.0; subset structural only | PARTIAL (boundaries/request-response, never runtime logic) | UNAVAILABLE (no CICS runtime; RESP/commarea/isolation out of scope) | NOT_VERIFIED by construction |
| IMS | UNKNOWN (no detection patterns found) | UNSUPPORTED | UNSUPPORTED | UNAVAILABLE | NOT certified |
| MQ | UNKNOWN (no detection patterns found) | UNSUPPORTED | UNSUPPORTED | UNAVAILABLE | NOT certified |
| External utilities / SORT | PARTIAL (SORT detected; utilities not modeled) | UNSUPPORTED | UNSUPPORTED | UNAVAILABLE | NOT certified |
| System services | UNKNOWN | UNSUPPORTED | UNSUPPORTED | UNAVAILABLE | NOT certified |
| VSAM specifics | PARTIAL (JCL model carries a type string; no VSAM file semantics) | UNSUPPORTED | UNSUPPORTED | UNAVAILABLE | NOT certified |

## 6. Coverage matrix

Columns: Parser | IR | Capability (registry) | Mapping | JavaGen | Runtime
(JVM lane) | Oracle (GnuCOBOL) | Comparison | Evidence | Certification.
"—" means not applicable at that layer for the row.

### 6.1 Data

| Feature | Parser | IR | Capability | Mapping | JavaGen | Runtime | Oracle | Comparison | Evidence | Certification |
|---|---|---|---|---|---|---|---|---|---|---|
| PIC X(n) / 9(n) | SUPPORTED (`_parse_pic`) | SUPPORTED (`DataItem`) | SUPPORTED (via statement proof) | SUPPORTED (`map_pic_to_java_type`) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (numeric tests) | SUPPORTED subset |
| PIC S (signed) | SUPPORTED (S stripped, `signed` flag) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| PIC V (decimals) | SUPPORTED (`_parse_pic_details`) | SUPPORTED (`decimal_places`) | SUPPORTED | SUPPORTED (truncate, no round) | SUPPORTED | PARTIAL (double-backed; high-precision caveat documented) | SUPPORTED | SUPPORTED | SUPPORTED | PARTIAL (precision edges remain) |
| VALUE (numeric) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (`normalize_value_for_pic`) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| Numeric DISPLAY | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (`display_format_spec`) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| COMP (BINARY) | PARTIAL (USAGE clause silently ignored — no diagnostic) | PARTIAL (no usage/encoding field) | UNKNOWN (no registry key) | PARTIAL (value semantics via int/long) | PARTIAL | UNKNOWN (no COMP workload runtime proof found) | SUPPORTED (GnuCOBOL executes COMP) | UNKNOWN | PARTIAL (fixtures parse; `workload-comp`) | UNKNOWN (must not claim) |
| COMP-3 (PACKED-DECIMAL) | PARTIAL (same silent-ignore) | PARTIAL | UNKNOWN (no registry key) | PARTIAL (value semantics via double) | PARTIAL | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (fixtures parse; `workload-comp3`) | UNKNOWN (must not claim) |
| Edited pictures (Z, $, ., etc.) | UNSUPPORTED (`CobolParseError`, fail-closed) | UNSUPPORTED | UNKNOWN (no key; unreachable) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | PARTIAL (rejection path) | UNSUPPORTED |
| REDEFINES | SUPPORTED (parsed to `DataItem.redefines`; fixture parses) | SUPPORTED | UNKNOWN (no registry key) | UNKNOWN (no overlay handling found in mapper audit) | UNKNOWN | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (parse-level; `workload-redefines`) | UNKNOWN (must not claim) |
| OCCURS (fixed tables) | SUPPORTED (parsed; fixture parses) | SUPPORTED (`is_table`) | UNKNOWN (no registry key) | UNKNOWN (no table-index codegen found in mapper audit) | UNKNOWN | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (parse-level; `workload-occurs`) | UNKNOWN (must not claim) |
| 88-level condition names | SUPPORTED (`is_condition_name`) | SUPPORTED (`BooleanCondition`) | UNKNOWN (no registry key; conditions flow via IF/ELSE) | UNKNOWN (condition lowering path unverified) | UNKNOWN | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (parse-level; `workload-level88`) | UNKNOWN (must not claim) |
| Group items / hierarchy | SUPPORTED | SUPPORTED (`children`) | SUPPORTED (via programs using them) | SUPPORTED (field mapping skips groups structurally) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |

### 6.2 Procedural

| Feature | Parser | IR | Capability | Mapping | JavaGen | Runtime | Oracle | Comparison | Evidence | Certification |
|---|---|---|---|---|---|---|---|---|---|---|
| MOVE | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| ADD (incl. GIVING) | SUPPORTED (ROUNDED parsed) | SUPPORTED (`rounded` flag) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (`test_arithmetic_giving`) | SUPPORTED subset |
| SUBTRACT (incl. GIVING, multisource) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (verified fixtures) | SUPPORTED subset |
| MULTIPLY (incl. GIVING) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (verified fixtures) | SUPPORTED subset |
| DIVIDE (incl. INTO/GIVING) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (verified fixtures) | SUPPORTED subset |
| COMPUTE | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset (precision edges remain) |
| ROUNDED phrase | SUPPORTED (flag only) | SUPPORTED | UNKNOWN (no key) | UNKNOWN (flag consumption unverified) | UNKNOWN | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (parse-level) | UNKNOWN |
| SIZE ERROR / ON SIZE ERROR | SUPPORTED (detected via source scan) | UNSUPPORTED (registry: not in arithmetic IR) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked-behavior tests) | Blocked by design |
| IF / ELSE | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (`String.equals` for string compare) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| EVALUATE | SUPPORTED (lowered to nested IF) | SUPPORTED (via `IfStatement`; `CONSTRUCT_IR_COVERAGE`) | SUPPORTED | SUPPORTED (via IF/ELSE) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (phase-4 oracle) | SUPPORTED subset |
| PERFORM (para/section) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| PERFORM TIMES / VARYING | SUPPORTED (into `PerformStatement`) | SUPPORTED (`PerformTimesStatement` legacy node explicitly UNSUPPORTED) | SUPPORTED | SUPPORTED (bounded Java loop) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (phase-4 oracle) | SUPPORTED subset |
| PERFORM THRU / unresolved | SUPPORTED (detected) | PARTIAL | PARTIAL/UNSUPPORTED (structure finding) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| GO TO | SUPPORTED (node built) | SUPPORTED (`GoToStatement`) | UNSUPPORTED (no Java control-flow mapping) | UNSUPPORTED (`STATEMENT_CAPABILITY_UNSUPPORTED`) | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| STRING | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| UNSTRING | SUPPORTED (delimited subset) | SUPPORTED | PARTIAL (certified delimited subset) | PARTIAL | PARTIAL | PARTIAL | SUPPORTED | PARTIAL | PARTIAL (targeted) | PARTIAL |
| INSPECT | UNKNOWN (no parse path found; scan-detected) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| INITIALIZE | UNKNOWN (scan-detected) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| SET | UNKNOWN (scan-detected) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| SEARCH (incl. ALL) | UNKNOWN (scan-detected) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| SORT / MERGE | SUPPORTED (detected; producers advertise `SORT_STATEMENTS` only for opensource4j) | UNSUPPORTED (native lane) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| ACCEPT | UNKNOWN (scan-detected) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| ALTER / GOBACK / NEXT SENTENCE / CONTINUE scope ends | SUPPORTED (scope-terminator recognition; not semantics) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design (legacy control flow) |
| DISPLAY | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| STOP RUN | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| EXIT PROGRAM | SUPPORTED | SUPPORTED | SUPPORTED (source-only→UNSUPPORTED) | SUPPORTED (Java return) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |

### 6.3 Program structure

| Feature | Parser | IR | Capability | Mapping | JavaGen | Runtime | Oracle | Comparison | Evidence | Certification |
|---|---|---|---|---|---|---|---|---|---|---|
| CALL static literal | SUPPORTED | SUPPORTED (`ProgramCall`) | SUPPORTED | SUPPORTED (value-result) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (A→B→C proof) | SUPPORTED subset |
| CALL USING (positional) | SUPPORTED (`_parse_procedure_using`) | SUPPORTED (`using_parameters`) | SUPPORTED (arity-checked) | SUPPORTED (sync-in all modes) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| LINKAGE SECTION | SUPPORTED | SUPPORTED | SUPPORTED (arity walk) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| BY REFERENCE | SUPPORTED | SUPPORTED | SUPPORTED (write-back path) | SUPPORTED (sync-out) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| BY CONTENT | SUPPORTED (parsed) | SUPPORTED | UNKNOWN (no registry key; matrix known-gap) | SUPPORTED-subset (sync-in, no sync-out per mapper comments) | SUPPORTED-subset | UNKNOWN (dedicated runtime proof not found) | SUPPORTED | UNKNOWN | PARTIAL (fixture + linkage-mismatch tests) | UNKNOWN (must not claim) |
| BY VALUE | SUPPORTED (parsed) | SUPPORTED | UNKNOWN (no registry key; matrix known-gap) | SUPPORTED-subset (same as BY CONTENT) | SUPPORTED-subset | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (fixture + tests) | UNKNOWN (must not claim) |
| ENTRY (multi-entry) | PARTIAL (quoted-form regex only) | PARTIAL (`entry_points`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | SUPPORTED | UNKNOWN | PARTIAL (discovery-level) | UNKNOWN |
| Nested programs | UNKNOWN (single PROGRAM-ID flow) | UNSUPPORTED | UNKNOWN | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | UNKNOWN (no tests found) | UNKNOWN |
| Dynamic CALL | SUPPORTED (detected, `DYNAMIC`) | SUPPORTED | UNSUPPORTED | UNSUPPORTED (blocked) | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| Unresolved / cyclic / arity-mismatch CALL | SUPPORTED (detected) | SUPPORTED | PARTIAL/UNSUPPORTED + reason | UNSUPPORTED (blocked) | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |

### 6.4 Files

| Feature | Parser | IR | Capability | Mapping | JavaGen | Runtime (`CobolFileIo`) | Oracle | Comparison | Evidence | Certification |
|---|---|---|---|---|---|---|---|---|---|---|
| Sequential (LINE SEQUENTIAL) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (integrated workload) | SUPPORTED subset |
| OPEN INPUT/OUTPUT | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| OPEN I-O / EXTEND | SUPPORTED | SUPPORTED | PARTIAL (not reproduced) | PARTIAL | PARTIAL | UNSUPPORTED | SUPPORTED | — | PARTIAL (classified, not run) | NOT certified |
| CLOSE (single-file) | SUPPORTED | SUPPORTED | SUPPORTED (source-only→UNSUPPORTED) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| CLOSE (multi-file) | PARTIAL (dropped) | UNSUPPORTED | UNSUPPORTED (source-only) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked via source scan) | Blocked by design |
| READ (+AT END) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| WRITE | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| REWRITE (indexed/relative) | SUPPORTED | SUPPORTED | SUPPORTED (source-only→UNSUPPORTED) | SUPPORTED (indexed/relative) | SUPPORTED | SUPPORTED (`rewrite`/`rewriteRelative`) | SUPPORTED | SUPPORTED | SUPPORTED (INVALID KEY lane) | SUPPORTED subset (indexed/relative only) |
| REWRITE (sequential) | SUPPORTED | SUPPORTED | UNSUPPORTED (explicit) | UNSUPPORTED (comment-emitted) | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| DELETE (indexed/relative) | SUPPORTED | SUPPORTED | SUPPORTED (source-only→UNSUPPORTED) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| START (symbolic ops) | SUPPORTED | SUPPORTED | SUPPORTED (source-only→UNSUPPORTED) | SUPPORTED (cursor position) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| START (relational words) | PARTIAL (diagnostic, fail-closed to status 23) | PARTIAL (`UNSUPPORTED` operator) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| INVALID KEY / NOT INVALID KEY | SUPPORTED (clause bodies) | SUPPORTED (`invalid_key_body`) | SUPPORTED (sentinel `InvalidKeyScope`) | SUPPORTED (status branch) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (`test_file_invalid_key_lane`) | SUPPORTED subset |
| Indexed organization | SUPPORTED (detected: RECORD KEY, ALTERNATE KEY) | SUPPORTED (`FileKey`, alternate keys) | UNSUPPORTED outside INVALID KEY lane (rejected boundary) | PARTIAL | PARTIAL | PARTIAL (`CobolFileIo` keyed ops) | SUPPORTED | PARTIAL | PARTIAL (indexed fixtures + fail-closed negatives) | NOT certified (general case) |
| Relative organization | SUPPORTED (RELATIVE KEY) | SUPPORTED | UNSUPPORTED outside lane | PARTIAL | PARTIAL | PARTIAL | SUPPORTED | PARTIAL | PARTIAL (relative fixtures + negatives) | NOT certified (general case) |
| DYNAMIC access | SUPPORTED (detected) | SUPPORTED | UNSUPPORTED (explicit) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | SUPPORTED (blocked) | Blocked by design |
| FILE STATUS | SUPPORTED (field capture) | SUPPORTED | SUPPORTED (status-bound branches) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED subset |
| VSAM | UNKNOWN (no VSAM parse path; JCL type string only) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | UNKNOWN | NOT certified |

### 6.5 Dependencies (see also §5)

| Feature | Parser | IR | Capability | Mapping | JavaGen | Runtime | Oracle | Comparison | Evidence | Certification |
|---|---|---|---|---|---|---|---|---|---|---|
| COPY (resolution) | SUPPORTED | SUPPORTED (`CopybookReference`, RESOLVED/AMBIGUOUS/UNRESOLVED) | SUPPORTED (relationship) | SUPPORTED (source context) | SUPPORTED (shared model; no standalone class) | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED (`test_copybook_m7`, runtime test) | SUPPORTED subset |
| COPY REPLACING | UNKNOWN (no REPLACING path found) | UNSUPPORTED | UNKNOWN | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | — | UNKNOWN | UNKNOWN |
| JCL job stream | SUPPORTED (+own diagnostics) | SUPPORTED (`jcl/*` model) | PARTIAL (max, by construction) | PARTIAL (Spring Batch structure) | PARTIAL | UNAVAILABLE | UNAVAILABLE (no JCL oracle) | UNAVAILABLE | PARTIAL (model/gen tests; negative scenario 6) | NOT_VERIFIED by construction |
| DB2 / EXEC SQL | SUPPORTED (extractor/parser) | SUPPORTED (`SqlStatement`, harness) | UNSUPPORTED for central lane | PARTIAL (SQLite controlled semantics) | PARTIAL | UNAVAILABLE (no DB2 subsystem; `runtime_verified_features()` empty) | UNAVAILABLE | UNAVAILABLE | PARTIAL (db2 tests; negative scenario 7) | NOT_VERIFIED by construction |
| CICS (subset v1.0.0) | SUPPORTED (parser recognizes superset) | SUPPORTED (commands/operands/conditions) | PARTIAL-subset / UNSUPPORTED rest | PARTIAL (structure only) | PARTIAL | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | PARTIAL (cics tests; negative scenario 8) | NOT_VERIFIED by construction |
| IMS / MQ / utilities / system services | UNKNOWN (no detection patterns) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNAVAILABLE | SUPPORTED (COBOL side only) | — | UNKNOWN | NOT certified |

### 6.6 Proof-lane components (apply wherever the runtime lane runs)

| Component | Status | Evidence |
|---|---|---|
| GnuCOBOL oracle (host + Docker, digest-pinned) | SUPPORTED | `engine/oracle/adapter.py`, `docker_adapter.py`; `test_oracle*`, `test_numeric_oracle_proof` |
| Docker Java candidate execution | SUPPORTED | `engine/candidate/*`; `test_docker_java`, `test_candidate` |
| Contract-aware comparison | SUPPORTED | `engine/comparators/framework.py`; `test_comparators`, adversarial comparator attacks |
| Evidence manifest + integrity | SUPPORTED | `engine/evidence/*`; `test_evidence`, tampering/trust-boundary suites |
| Deterministic verdict derivation | SUPPORTED | `engine/verdict/derivation.py`; `test_verdict*` (incl. trust boundary) |
| Integrated proof gate (only-downgrades) | SUPPORTED | `engine/modernization/integrated_proof.py`; Phase-D positive + 8 negatives |

## 7. Proven capabilities (may be claimed)

Exactly the §6 rows whose Certification cell is SUPPORTED subset / PARTIAL
with cited evidence: core arithmetic + COMPUTE, IF/ELSE, PERFORM family,
EVALUATE-via-IF, STRING, UNSTRING-delimited-subset, DISPLAY, STOP RUN,
EXIT PROGRAM, static resolved CALL with USING/LINKAGE/BY REFERENCE,
sequential files + CLOSE/INVALID KEY branches, indexed/relative
START/REWRITE/DELETE INVALID KEY lane, COPY resolution/consumption, PIC
X/9/S/V + VALUE + numeric DISPLAY, FILE STATUS branches, and the full
oracle→comparison→evidence→verdict→integrated-gate proof chain.

## 8. Partial capabilities (bounded; never silently upgrade)

UNSTRING (delimited only), PIC V precision on double, OPEN I-O/EXTEND,
COMP/COMP-3 value semantics (encoding excluded), multi-file CLOSE handling
absent, relational-word START (fail-closed to 23), indexed/relative general
case, JCL/DB2/CICS structural lanes, ENTRY quoted-form, ROUNDED flag
carriage, BY CONTENT/BY VALUE mapping without capability key.

## 9. Unsupported capabilities (detected, classified, blocked — correct)

GO TO, SORT, MERGE, ACCEPT, INITIALIZE, INSPECT, SEARCH, SET, ALTER,
NEXT SENTENCE, GOBACK, SIZE ERROR, EXEC CICS, EXEC SQL, dynamic/unresolved/
cyclic/arity-mismatched CALL, sequential REWRITE, DYNAMIC access,
relational-word START, ambiguous/missing COPY, edited pictures (parse
rejection), nested programs (no path).

## 10. Missing runtime proof (explicit)

- COMP/COMP-3: no workload-level oracle-vs-candidate comparison found.
- REDEFINES / OCCURS / 88-level conditions: parse-level fixtures only; no
  mapping-output or runtime comparison evidence found in audit.
- BY CONTENT / BY VALUE: mapping implements sync-in; no dedicated runtime
  proof; no registry key (capability UNKNOWN).
- ROUNDED: flag parsed; consumption unverified.
- Indexed/relative general case: INVALID KEY lane only; full cursor/keyed
  semantics uncertified (fail-closed negatives are the evidence).
- JCL/DB2/CICS: no runtime lane exists (UNAVAILABLE oracle/comparison/
  evidence); certification structurally impossible today.
- IMS/MQ/utilities/system services/VSAM/COPY REPLACING/nested programs:
  not even detection patterns — UNKNOWN, the lowest universality rung.

## 11. Universality gaps (detection ladder)

Rung 0 — undetectable (no patterns): IMS, MQ, utilities, system services,
VSAM specifics, COPY REPLACING, nested programs, edited-picture usage
beyond rejection. Gaps: add source-scan patterns + registry keys so these
classify instead of passing silently.
Rung 1 — detected, unclassified: COMP/COMP-3 usage, ROUNDED, ENTRY forms,
BY CONTENT/BY VALUE modes. Gaps: registry keys with honest PARTIAL/UNKNOWN.
Rung 2 — classified, unmapped: all §9 rows (working as designed).
Rung 3 — mapped, unproven: REDEFINES/OCCURS/88-mapping, COMP runtime,
BY CONTENT/BY VALUE runtime. Gaps: positive + negative tests before claims.
Rung 4 — proven, uncertified-at-application-level: JCL/DB2/CICS lanes
(structural impossibility until runtime lanes exist).

## 12. P0 roadmap — critical gaps affecting currently claimed support

P0-1 Producer/registry contradiction.
Symptom: `producers/internal_native.py` lists COMPUTE, SUBTRACT, MULTIPLY,
CALL, EVALUATE as `unsupported_constructs` while the registry and matrix
claim them SUPPORTED. Parser work: none. IR: none. Semantic: reconcile which
list is authoritative (registry should win; producer list looks stale).
Mapper/Java: none. Oracle: re-run affected workloads after doc/code
reconciliation. Evidence: positive proof per construct + test asserting
producer lists ⊆ registry. Negative tests: none new. Positive tests:
existing arithmetic/CALL/EVALUATE suites re-run. Risk: low (reporting bug),
but any user reading producer metadata gets a false UNSUPPORTED — fix the
claim, not the engine, then verify.

P0-2 COMP/COMP-3 USAGE silently ignored.
Symptom: `PIC S9(4) COMP` parses with zero diagnostics; encoding semantics
dropped without a trace (numeric value path only). Parser: emit explicit
diagnostic or record usage on `DataItem` (IR: new optional usage field;
no behavior change). Semantic: add registry keys `COMP`, `COMP-3` at
PARTIAL with "value semantics only; byte encoding excluded". Mapper/Java/
runtime: unchanged. Oracle: available (GnuCOBOL). Evidence: positive
COMP/COMP-3 oracle-vs-candidate comparisons; negative: edited/overflow
cases fail closed. Tests: parse-diagnostic tests + runtime comparison
tests on `workload-comp`/`workload-comp3`. Risk: medium — silent narrowing
is the exact failure mode the capability rule forbids.

P0-3 REDEFINES / OCCURS / 88-level mapping unverified.
Symptom: fixtures parse; no mapping-output or runtime evidence found; no
registry keys. Parser/IR: done. Semantic: add keys at UNKNOWN until proven.
Mapper: verify overlay/table/condition lowering exists or scope it.
Java/runtime: verify `workload-occurs`, `workload-redefines`,
`workload-level88` end-to-end. Oracle: available. Evidence: full-ladder
proof per fixture or explicit PARTIAL/UNSUPPORTED with negatives. Tests:
positive runtime tests + negative (e.g., OCCURS DEPENDING ON blocked).
Risk: medium — fixtures that parse but never prove invite false confidence.

P0-4 BY CONTENT / BY VALUE capability hole.
Symptom: mapper implements sync-in/no-sync-out and fixtures exist, but no
registry key means capability UNKNOWN (matrix known-gap). Parser/IR: done.
Semantic: add keys (PARTIAL + mode LoseSemantics note) or keep blocked —
either is honest once written. Mapper/Java: unchanged. Oracle: available.
Evidence: dedicated mode-specific runtime comparisons. Tests: positive per
mode + negative (literal-by-reference-write, arity mismatch — partially
exists). Risk: medium — parameter modes are a classic silent-divergence
source.

P0-5 ROUNDED flag consumption.
Symptom: parsed into IR on five statement types; no mapping evidence found.
Either prove the flag reaches Java or mark mapping UNKNOWN with a negative
test (ROUNDED program stays uncertified). Oracle available. Risk: low-medium.

## 13. P1 roadmap — high-value enterprise COBOL

P1-1 INITIALIZE (bounded): parser (statement + REPLACING/ALL variants
detection first), IR node, registry PARTIAL, mapper to field-default
assignment reusing `map_pic_to_java_default`, Java trivially, oracle
available, evidence full-ladder, negatives (REPLACING forms blocked until
proven). Risk: low.
P1-2 INSPECT (TALLYING/REPLACING counted subset): parser, IR, PARTIAL,
mapper to string ops, Java stdlib, oracle available, evidence full-ladder,
negatives for CONVERTING. Risk: low-medium (tally semantics).
P1-3 SEARCH linear (serial only; ALL stays blocked): parser section
detection already stubbed (`_parse` lookup-section comment), IR, PARTIAL,
mapper to loop, oracle available, negatives for SEARCH ALL/binary.
Risk: medium (index handling — coordinate with P0-3 OCCURS proof).
P1-4 SET (index + condition-name + mnemonic subsets, sequenced): detection
exists; add IR + PARTIAL keys per sub-form; mapper; oracle; negatives per
unproven sub-form. Risk: medium (index ↔ OCCURS coupling).
P1-5 UNSTRING broadening (POINTER, OVERFLOW, multi-delimiter): extend IR
beyond current delimited subset; PARTIAL stays; oracle; negatives for each
excluded clause. Risk: medium.
P1-6 STRING overflow + POINTER: same pattern as P1-5. Risk: low.
P1-7 COPY REPLACING: detection (Rung 0→1), IR, mapper text-substitution
before parse with provenance, oracle, negatives (partial REPLACING).
Risk: medium (provenance tracking).
P1-8 FILE STATUS completeness + sequential boundary review (OPEN I-O/
EXTEND, sequential REWRITE runtime): parser done; needs `CobolFileIo`
runtime work + oracle + negatives. Risk: medium (file-state machine).
P1-9 Indexed/relative general runtime (cursor, keyed READ, START variants):
largest P1; parser/IR/mapper exist; runtime + oracle + extensive negatives
(status-23 matrix). Risk: high — keep INVALID KEY lane certified while the
general case stays blocked.
P1-10 COMP-3 decimal-exact runtime (decimal type instead of double):
parser/IR done; Java runtime work (BigDecimal-backed pictured decimals);
oracle; evidence incl. precision comparisons; negatives for overflow.
Risk: medium-high, high value (money arithmetic).
P1-11 EVALUATE complex (ALSO/THROUGH ranges): parser lowering extension;
registry stays SUPPORTED-subset with explicit boundary; oracle; negatives
for unlowerable forms. Risk: medium.
P1-12 PERFORM inline + THRU resolution: structure findings exist; resolve or
keep blocked with better diagnostics. Risk: low-medium.

## 14. P2 roadmap — broader language coverage

Edited pictures (display formatting, P2-1); multi-dimensional OCCURS +
OCCURS DEPENDING ON (blocked until P0-3 proven; P2-2); nested programs
(detection first — Rung 0; P2-3); ENTRY full forms incl. USING (P2-4);
SORT/MERGE file-based (producer capability exists only for opensource4j —
verify or keep UNSUPPORTED; P2-5); ACCEPT (console/special-registers;
likely stays UNSUPPORTED with detection — P2-6); condition-name hierarchies
and 88 ranges (after P0-3; P2-7); reference modification (detection +
slicing semantics; P2-8); intrinsic functions (CURRENT-DATE etc.,
detection first; P2-9); permanent-UNSUPPORTED coda — ALTER, GOBACK-as-
control-flow, NEXT SENTENCE: keep detected-and-blocked forever, with tests
locking the behavior (P2-10). Each item: parser → IR → semantic key →
mapper → Java → oracle (available for all: GnuCOBOL) → evidence ladder →
positive + negative tests. Risk: low-medium individually; sequence after P0.

## 15. P3 roadmap — mainframe ecosystem integrations

P3-1 JCL runtime lane: define what "running a job stream" means without a
mainframe (ordered step execution harness); parser/IR/mapper exist at
PARTIAL; needs runtime + oracle-substitute (step-level comparison contracts)
+ evidence + negatives. Risk: high (scope definition first).
P3-2 DB2 verification against a real subsystem (containerized Db2): harness
exists (SQLite = controlled semantics, explicitly not equivalence);
needs dialect fidelity work (see `dialect.py` compatibility levels),
real-DB2 oracle adapter, evidence, negatives per untranslatable construct.
Risk: high (licensing/ops) — until then, `runtime_verified_features()`
stays empty and central status stays NOT_VERIFIED (correct).
P3-3 CICS runtime equivalence: subset v1.0.0 is structural; needs RESP/
commarea/transactional semantics model + harness; until then, structural
mapping only, never certified. Risk: very high — recommend detection-first
investment (recognize more commands explicitly) over premature runtime.
P3-4 IMS/MQ detection + classification (Rung 0→1→2): source patterns,
registry keys, blocked verdicts, negatives. No runtime. Risk: low, pure
universality gain.
P3-5 SORT utilities / system services / VSAM specifics: same detection-
first pattern. Risk: low.
P3-6 External dependency modeling (call-graph edges to non-COBOL targets):
visible → classified → BLOCKED ledger entries via integrated_proof
`extra_dependencies`. Mostly exists; extend edge vocabulary. Risk: low.

## 16. Test strategy (no fake coverage)

- Every P0–P3 item ships positive tests (proves the claimed behavior runs)
  AND negative tests (proves the unclaimed remainder stays blocked).
- Matrix cells change SUPPORTED→ only with full-ladder evidence; PARTIAL
  only with bounded proof + explicit boundary tests; UNKNOWN never ships.
- Lock blocked behavior: GO TO/SORT/ACCEPT/ALTER/GOBACK/NEXT SENTENCE/
  SIZE ERROR/EXEC CICS/EXEC SQL/dynamic CALL negatives must keep passing.
- Reconciliation tests: producer capability lists ⊆ registry; matrix doc
  claims ⊆ test names (audit hook: fail CI if a SUPPORTED row lacks a
  cited test).
- No LLM in any lane: tests assert determinism (same input → same output,
  same verdict) where it matters.

## 17. Proven capabilities (claimable)

See §7. Each item has parser + IR + registry SUPPORTED + mapper + Java +
runtime + oracle + comparison + evidence + targeted/end-to-end tests.

## 18. Partial capabilities

See §8. Bounded subsets with explicit boundaries and tests; certification
at most PARTIAL, central VERIFIED only when the integrated gate allows.

## 19. Unsupported capabilities

See §9. Detected, classified, blocked — the universality chain working.

## 20. Missing runtime proof

See §10. The honest backlog: COMP/COMP-3, REDEFINES, OCCURS, 88-level
mapping, BY CONTENT/BY VALUE, ROUNDED, indexed/relative general case,
JCL/DB2/CICS lanes, and all Rung-0 items.

## 21. Universality gaps

See §11 ladder (Rung 0–4). Sequencing rule: close Rung 0 (detection) before
Rung 3 (proof) for any new construct — a construct that cannot be detected
cannot be blocked, and an undetectable construct is worse than an
unsupported one.

## 22. Files changed (this workstream)

- `docs/COBOL_UNIVERSALITY_ROADMAP.md` (this file) — new.
- `docs/cobol_coverage_registry.json` — new machine-readable snapshot.

## 23. Files NOT changed (scope protection honored)

`engine/transformation/ir.py`, `engine/transformation/semantic_capability.py`,
`engine/modernization/capability_analyzer.py`,
`engine/modernization/transformation_plan.py`,
`engine/modernization/integrated_proof.py`, `engine/evidence/*`,
`engine/verdict/*`, `api/service.py`, `frontend/*` — untouched, verified via
`git status` before commit (only the two new docs files staged).

## 24. Parallel conflicts

Other workstreams hold dirty changes in `api/`, `frontend/`,
`tests/adversarial/test_phase_a_trust_hardening.py`, plus untracked scratch
artifacts at repo root, `test-artifacts/`, `tmp/`, and fixture subdirs
(`fixtures/workload-comp/cobol/p`, `fixtures/workload-comp3/cobol/p`).
This commit adds only the two new files above; no other paths staged,
no deletions, no renames, no engine changes — conflict surface is nil by
construction. If parallel agents create `docs/COBOL_UNIVERSALITY_ROADMAP.md`,
last-writer coordination is needed (no such file existed at audit time).

## 25. Recommendations

1. Fix P0-1 and P0-2 first: both are claim-integrity issues (false metadata,
   silent narrowing), not feature work.
2. Adopt the Rung 0→4 ladder as the intake rule for every new construct:
   detection pattern + registry key before any mapping code.
3. Add the reconciliation test (§16): producer lists ⊆ registry, SUPPORTED
   rows cite tests — the audit hook that keeps this roadmap true.
4. Keep JCL/DB2/CICS certification at NOT_VERIFIED until runtime lanes exist;
   invest P3 effort in detection breadth (cheap, high universality value)
   before runtime depth (expensive).
5. Re-run this audit per baseline: the JSON snapshot carries its baseline
   SHA so drift is detectable.

## 26. Commit

One focused commit adding the two artifacts; message:

`docs: COBOL universality audit and roadmap (workstream 7, baseline fedb7dd)`
