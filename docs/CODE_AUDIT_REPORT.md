# Repository-Wide Code Audit Report — Cobol-Java-Transformation
> > **HISTORICAL REPORT (Master README §78, labeled 2026-10-21):** this document is evidence of the repository state at its own recorded commit/date only. It is not a current status claim — current status lives in `opencode.md`, `docs/BACKLOG.md` and the current capability/verification documents. Content is unchanged; only this label was added.

Status: **audit in progress** (Stage C of the post-Phase-3 review; findings
sections are filled from the completed per-group review reports).
Baseline: `docs/CODE_OPTIMIZATION_REPORT.md` §Baseline — HEAD
`26df174` (docs) / `4deddfc` (code, run of record), branch `codex/universal-core`.

## 1. Scope and method

- Review basis: repository at `codex/universal-core` @ `4deddfc` (code) —
  the exact commit of the Phase-3-closing exact-SHA CI-green run.
- Method: line-by-line review of every tracked source, configuration, test
  selection and workflow file, organized by execution path (Section 2).
  Each reviewer recorded per-file: purpose, findings with exact line numbers
  (tags D/U/S/C/E/P/X, Section 3), and the must-not-change public surface.
- Invariants enforced during review (from `MASTER_IMPLEMENTATION_README.md`
  and `opencode.md`): deterministic no-LLM pipeline; fail-closed negative
  contracts (unresolved CALL/COPY, BY VALUE/BY CONTENT keyless, unsupported
  constructs); capability truth (never SUPPORTED when generation fails);
  backward-compatible public APIs; evidence integrity; no test weakened.
- Honest scope statement: "line-by-line" applies to executable source
  (Python/TypeScript/YAML/config, 100% of tracked files in those classes).
  Test files were reviewed for naming, assertions strength and selection
  wiring (see `docs/TEST_NAMING_AUDIT.md`) plus group-level spot checks —
  not every assertion line of all 3,476 tests was re-derived. Fixture files
  (176 workload data files) were inventoried structurally (existence,
  purpose, referenced-by mapping), not semantically re-audited line by line.

## 2. File inventory (982 tracked files — reconciliation table)

| Area | Files | Review group | Review depth |
|------|-------|--------------|--------------|
| engine/transformation (parser/IR/copybook/discovery/mapping/generation/JCL/SQL/CICS) | 35 | T1 (parser+IR), T2 (copybook+discovery+capability), T3 (mapping+generation), T4 (JCL/SQL/CICS) | line-by-line |
| engine/modernization + engine/pipeline.py | 7 | T2 | line-by-line |
| engine/candidate, oracle, execution, evidence, comparators, contracts, verdict, domain, other engine/* | ~52 | T5 | line-by-line |
| api/ | 10 | T6 | line-by-line |
| .github/workflows, scripts/, root configs, deployment/ | ~19 | T7 | line-by-line |
| frontend/src + configs (excluding lock/build artifacts) | 42 | T8 | line-by-line |
| tests/ (520 files, 3,476 collected ids) | 520 | N1–N4 naming + assertion review | naming/assertion audit + spot checks |
| fixtures/ (47 workloads: 59 .cob, 58 .java, 39 .py harnesses, 5 .cpy, 5 .jcl, 4 .dat, 2 .sql, 1 .csv, 1 .trace, 2 extensionless) | 176 | inventory | structural inventory |
| docs/ + contracts/*.md | 70 | T7 (contracts) + reconciliation | read for authority/status consistency |
| test-artifacts/ (tracked artifacts) | 40 | inventory | not source; churn policy: never committed |

Per-group file-by-file reconciliation: see Section 5.

## 3. Finding taxonomy

- **[D]** dead code / unused import / unused variable / unreachable branch
- **[U]** duplicated logic extractable into a shared helper (both call sites + the helper's contract recorded)
- **[S]** safe simplification (before/after sketch; must preserve semantics and error behavior; any test at risk named)
- **[C]** excessive complexity / nesting / unclear control flow
- **[E]** error-handling or edge-case risk (audit finding, not automatically a defect — rationale recorded)
- **[P]** repeated parsing or filesystem/process work that could be safely reused
- **[X]** unclear naming

Every proposed change must be behavior-preserving; anything touching
observable output (diagnostics, verdicts, emitted Java, JSON contracts) is
excluded from the optimization pass and recorded as a finding only.

## 4. Findings by group

Every finding carries an exact file + line range and was verified against the
file content before being recorded. Full per-finding detail (evidence lines,
root cause, must-not-change surface) lives in the per-group reports under
`%TEMP%/opencode/phase3/audit/`.

| Group | Area | D | U | S | C | E | P | X | Total |
|---|---|---|---|---|---|---|---|---|---|
| T1 | parser + IR + figurative | 21 | 12 | 2 | 5 | 19 | 4 | 2 | 65 |
| T2 | copybook + discovery + capability + pipeline | 10 | 6 | 2 | 2 | 17 | 10 | 4 | 51 |
| T3 | mapping + generation (c2j, java, spring, CICS lanes) | 12 | 19 | 1 | 1 | 13 | 4 | 2 | 52 |
| T4 | JCL + SQL/DB2 + CICS mapper | 19 | 13 | 10 | 1 | 13 | 9 | 13 | 78 |
| T5 | candidate + oracle + execution + evidence + comparators + contracts + verdict | 8 | 15 | 0 | 0 | 20 | 1 | 12 | 56 |
| T6 | api/ | 5 | 5 | 3 | 1 | 9 | 9 | 2 | 34 |
| T7 | workflows + scripts + root config + nginx | 11 | 10 | 1 | 14 | 21 | 4 | 2 | 63 |
| T8 | frontend | 21 | 9 | 5 | 3 | 16 | 5 | 7 | 66 |
| | **Total** | **107** | **89** | **24** | **27** | **128** | **37** | **44** | **465** |

Highest-impact findings per group (all filed in `docs/BACKLOG.md` with §77
fields; status OPEN):

- **T1** — `perform … until` case-sensitivity `IndexError` (BL-055);
  WORKING-STORAGE group hierarchy silently dropped (BL-058).
- **T2** — planner defaults *missing* copybook/file components to SUPPORTED,
  fail-open (BL-043); CALL resolution stamped case-sensitively but matched
  case-insensitively (BL-044); `UnicodeDecodeError` escapes the copybook
  lanes' `except OSError` (BL-056).
- **T3** — Spring generator emits unescaped String literals (BL-046, shared
  root of BL-057); CICS generator renders literals with Python `repr()`
  (BL-057); every copybook model file emitted twice (BL-064); legacy paths
  isinstance-check never-imported IR classes (BL-065).
- **T4** — **P0 BL-040**: valid `STRING … INTO T.` without `END-STRING`
  silently loses subsequent PROCEDURE DIVISION statements; SQL execution
  error handlers raise `ValueError` from inside their own `except`
  (BL-060); DECLARE CURSOR bind info discarded (BL-061); `INSERT … VALUES`
  without column list mis-parses (BL-062); JCL consumer scan/keying gaps
  (BL-063); `file_io` mode drops `.text`-less statements (BL-041); producer
  diagnostics dict-shaped vs `Diagnostic` (BL-042).
- **T5** — Docker Java compile-timeout path raises `UnboundLocalError` and
  leaks the container (BL-050); Oracle timeout path has no container name
  and no cleanup (BL-051); FIXED_RECORD comparator ignores trailing
  partial-record bytes (BL-052); `derive_from_validated` TOCTOU seal gap
  (BL-053); JAR written back into `candidate_path` → non-deterministic
  `candidate_hash` (BL-054).
- **T6** — duplicate upload filenames silently collapse (BL-047); upload
  deletes previous source before validating the new one — data loss (BL-048);
  non-ASCII bearer token → 500 instead of 401 (BL-049); generated-app
  download zips the whole tree in memory, uncapped (BL-067).
- **T7** — `pip_audit | tee` / `npm audit | tee` run without `pipefail` so
  the documented supply-chain gate can never fail; `verify-production.sh`
  probe ends in `; rm -f` → always exits 0 (false PASS); mount check greps
  compose env instead of `docker inspect --format`; `backup.sh`/`restore.sh`
  mishandle absolute paths; `test-artifacts/**` upload can carry committed
  stale artifacts as fresh.
- **T8** — state-correctness trio: stale `selectedAppId` renders the wrong
  application; download errors never displayed; run-state race (BL-068);
  Inter font loaded twice (`index.html` + `index.css`).

`[E]` taxonomy note: `[E]` marks error-handling/edge-case **risk**, not
automatically a defect. Of the 128 `[E]` findings, 29 rose to confirmed
defects/gaps and were filed as BL-040…BL-068 (§5); the remainder carry an
in-report rationale (why the risk is bounded, already covered, or requires a
product decision before any change).

## 5. Inventory reconciliation

982 tracked files (see §2 table). Reconciliation rule: every tracked file in
a reviewed class appears in exactly one group report, either with findings
(file-by-file sections) or explicitly marked clean. Clean-file confirmations
recorded by the reviewers:

- T3: 10 of 13 engine files carry findings; `spring_boot_ir.py`,
  `producers/__init__.py`, `file_io_support_template.py` clean.
- T7: all 21 files reviewed; `.env.production.example` clean ("no
  findings"); no finding proposes changing the capability-truth selection
  (ci.yml L37-57 = exactly 20 test files, all verified present).
- T1/T2/T4/T5/T6/T8: per-file clean/dirty status recorded in the respective
  report's file sections; no tracked file was skipped.

`fixtures/` (176 files) were inventoried structurally (existence, purpose,
referenced-by mapping) — labeled honestly as inventory-level, not
semantically re-audited. `test-artifacts/` (40 tracked artifacts) is not
source and stays churn-uncommitted per policy.

## 5a. Defects and gaps (P0/P1/P2/P3)

As of the original 2026-10-14 audit state, all 29 confirmed defects/gaps were
OPEN in `docs/BACKLOG.md` (2026-10-16 correction, Phase 12 F-02: **25 FIXED,
4 OPEN** — BL-045, BL-046, BL-065, BL-066 — per the register, which is
authoritative) with full §77
fields (ID, type, priority/severity + rationale, observed vs expected, root
cause, affected lines, reproduction/evidence, impact, proposed remediation,
acceptance criteria, verification level, status, residual risk):

- **P0 (1):** BL-040 — `STRING` without `END-STRING` silently swallows the
  rest of the PROCEDURE DIVISION (BL-027-class silent statement loss).
- **P1 (8):** BL-041, BL-042, BL-043, BL-044, BL-047, BL-048, BL-052,
  BL-060.
- **P2 (17):** BL-045, BL-046, BL-049, BL-050, BL-051, BL-053, BL-054,
  BL-055, BL-056, BL-057, BL-058, BL-059, BL-061, BL-062, BL-063, BL-064,
  BL-067.
- **P3 (3):** BL-065, BL-066, BL-068.

## 6. Reviewed vs modified

Strictly separated lists (Stage D/E edits are itemized in
`docs/CODE_OPTIMIZATION_REPORT.md` and `docs/TEST_NAMING_AUDIT.md`):

- **Reviewed, not modified:** the overwhelming majority of the 982 files.
  Modification was restricted to (a) `[D]/[U]/[P]/[S]` items whose
  equivalence was proven, and (b) test-name renames from the N1–N4 audits.
- **Modified in Stage D (code):** 21 Python files + 8 frontend files
  (Batch 1), 14 Python files + 5 new shared modules (Batch 2), 16 Python
  files (Batch 3). The exact per-edit list is the batch scripts' edit log in
  `docs/CODE_OPTIMIZATION_REPORT.md` §3–§5.
- **Modified in Stage E (tests):** 136 method renames across the N1–N4 areas
  + `ids=` labels at 7 parametrized sites (5 files). No assertion, fixture,
  or selection changed; collection identity re-proven at 3476.
- **Not modified anywhere:** all 29 BL-040…BL-068 defect sites (audit-found
  defects are deliberately left untouched this pass), all capability labels,
  all contract/evidence formats, all workflow test selections.


## 7. Required audit deliverables (§76.7)

### 7.1 Exact baseline and audit scope

- Baseline commit (code, run of record): `4deddfc` (CI green, 3476/0/0);
  docs commit: `26df174`; branch `codex/universal-core` (PR #2 open,
  **unmerged** — merge requires human authorization).
- Scope: all 982 tracked files. Executable classes (Python, TypeScript,
  YAML, config, shell, nginx conf): 100% line-by-line. Tests: naming +
  assertion-strength audit (N1-N4) + group spot checks. Fixtures: structural
  inventory only (stated in §1). Review groups T1-T8 + N1-N4, 465 findings.

### 7.2 Architecture / data-flow map with real entry points

Real entry points (verified in code, not assumed):

1. **API daemon** - `api/app.py` (FastAPI app; service/store wiring at
   module level; recovery sweep for non-terminal runs) with routers
   `api/ingestion.py` (upload, zip extraction with size/entry caps),
   `api/service.py` (modernize orchestration, run reporting),
   `api/name_derivation.py` (application naming).
2. **Pipeline orchestrator** - `engine/pipeline.py` (source identity hash,
   staged transform: parse -> IR -> capability analysis -> plan ->
   generation; emits evidence).
3. **Transformation core** - `engine/transformation/*` (parser, copybook,
   discovery, mapping, generators, JCL/SQL/CICS lanes).
4. **Runtime lanes** - `engine/candidate/*` (Java compile/run, Docker
   variants), `engine/oracle/*` (GnuCOBOL oracle), `engine/execution/*`
   (sandbox, docker runner), `engine/evidence/*` + `engine/comparators/*` +
   `engine/verdict/*` (evidence -> comparison -> verdict chain).
5. **Frontend** - `frontend/src` (Vite/React SPA; talks to the API).
6. **CI** - `.github/workflows/ci.yml` (capability-truth gate with exactly
   20 files; full backend+Docker suite with `RUN_DOCKER_TESTS=1`; frontend
   build+tests) and `supply-chain.yml` (pip/npm audit, manifest).
7. **Operational scripts** - `scripts/` (record provenance, verify
   production, backup/restore/rollback) and `deployment/nginx`.

Data flow: upload -> ingestion (validated extraction) -> service ->
pipeline (parse/analyze/plan/generate, deterministic no-LLM) -> candidate +
oracle execution (sandboxed, evidenced) -> comparators -> verdict -> API
JSON -> frontend rendering; every stage writes evidence artifacts consumed
by the verdict and downloadable as a zip.

### 7.3 Findings matrix

Section 4 (per-group counts + highest-impact findings) and the per-group
reports under `%TEMP%/opencode/phase3/audit/` (every finding with severity
tag, evidence lines, affected file/line range, root cause, impact).
Severity mapping: P0/P1/P2/P3 confirmed defects -> Section 5a / BACKLOG;
risk findings (`[E]` not promoted) -> in-report rationale.

### 7.4 Requirement-to-code-to-test-to-evidence traceability matrix

| Capability area (requirement) | Primary code | Tests (representative, all real) | Evidence / contract |
| --- | --- | --- | --- |
| COBOL parse -> IR, fail-closed diagnostics | `engine/transformation/cobol_parser.py`, `ir.py` | `tests/transformation/test_agent2_control_flow.py`, `test_scoped_construct_statements.py` | diagnostics objects; IR in `TransformationResult` |
| Copybook resolution | `copybook_resolver.py`, `copybook_model.py` | `tests/transformation/test_copybook_*.py` | COPYBOOK_UNREADABLE diagnostics (BL-056 risk) |
| Capability truth (never SUPPORTED when generation fails) | `engine/modernization/*`, `engine/sql/analyzer.py` | CI capability gate: `test_capability_registry_reconciliation.py`, `test_producer_capability_consistency.py`, `test_usage_capability.py` | capability report JSON; planner status (BL-043 risk) |
| Java / Spring Boot generation | `java_generator.py`, `spring_boot_generator.py`, `jcl_to_spring_batch.py` | `test_single_mapping_pass_p0.py`, `test_jcl_generation.py`, `test_source_driven_generation.py` | generated source zip; POM |
| JCL lane | `jcl_parser.py`, `jcl_discovery.py`, `engine/jcl/*` | `tests/test_jcl_*.py` | `JclConsumerResult`, dependency edges |
| SQL / DB2 lane | `engine/sql/*` | `test_db2_*.py`, `test_sql_semantics.py` | `Db2SqlExecutionResult`, translated SQL |
| CICS lane | `engine/cics/*` | `test_cics_package.py`, `test_cics_java_lane.py` | CICS IR + issues |
| Candidate compile/execute | `engine/candidate/*` | `tests/candidate`, `tests/execution/test_candidate.py` | `CandidateContract`; image provenance JSON |
| Oracle (GnuCOBOL) | `engine/oracle/*` | `tests/execution/test_oracle.py` | `OracleContract`; digest identity |
| Evidence integrity | `engine/evidence/integrity.py`, `models.py` | `tests/evidence`, `tests/adversarial/*` | ARTIFACT contract; integrity hash |
| Comparators | `engine/comparators/*` | `tests/comparators`, `test_comparators.py` | comparison records (MATCH/MISMATCH) |
| Verdict (fail-closed) | `engine/verdict/*` | `tests/verdict`, `tests/adversarial/test_verdict_*.py` | VERDICT contract |
| Producer contract | `engine/transformation/producer.py` | `tests/transformation/test_producer_capability_consistency.py` | PRODUCER contract; producer attestation |
| API surface | `api/*` | `tests/test_e2e.py`, `tests/integration/*` | OpenAPI JSON; run reports |
| Frontend rendering | `frontend/src` | vitest 122 tests (CI `frontend-results`) | junit artifacts |
| Supply chain | `.github/workflows/supply-chain.yml` | n/a (audit steps) | `supply-chain-*` artifacts (gate currently cannot fail - T7 finding) |

### 7.5 Defects and gaps grouped by P0/P1/P2/P3

Section 5a above: 29 entries BL-040..BL-068 (1xP0, 8xP1, 17xP2, 3xP3) were
OPEN at the 2026-10-14 audit state (2026-10-16 correction, Phase 12 F-02: 25
FIXED, 4 OPEN per the register), each with full §77 fields in `docs/BACKLOG.md`.

### 7.6 Proposed phase assignment and dependencies

- **Next remediation cycle (P0 first):** BL-040 (period-bound statement
  termination) - parser change; needs regression corpus of STRING/COMP-3
  statements; blocks nothing else but is the top silent-data-loss risk.
- **Shared-helper first:** BL-046 (Java literal escaping helper) before
  BL-057 (CICS repr literals) - BL-057 depends on the same helper.
- **Independent P1s:** BL-041/042 (file_io reachability, producer
  diagnostics shape), BL-043/044 (planner fail-open, CALL case
  contradiction - capability-truth adjacent), BL-047/048 (ingestion
  collisions + pre-validation deletion - fix together, same code path),
  BL-052 (fixed-record floor division), BL-060 (sqlstate in error handlers;
  pairs with BL-061 cursor binds).
- **Ops/CI cycle:** T7 pipefail/verify-production/backup-path/artifact
  staleness fixes (workflows + scripts only; no engine code).
- **Frontend cycle:** BL-068 trio + double font load (T8).
- Every remediation lands behind the unchanged 3476-test gate; new
  regression tests are required by each BL entry's acceptance criteria.

### 7.7 Regression risks and green-baseline protection plan

- The 3476-test suite + exact-SHA CI (fresh run on the final commit) is the
  green-baseline gate; Stage D was applied in three independently validated
  batches, each re-proven against the full suite before the next batch.
- Highest regression risk areas for future fixes: parser termination
  (BL-040 - broad blast radius), planner fail-open defaults (BL-043 -
  capability labels are public surface and must not silently flip),
  ingestion deletion order (BL-048 - data loss path), evidence sealing
  (BL-053 - verdict trust).
- Protection rules applied and to stay applied: no assertion weakened; no
  skip added; collection identity 3476 by exact identity; capability labels
  and evidence formats changed only with explicit owner decision.

### 7.8 Items requiring a human / product / legal / security decision

1. Merge of PR #2 (and any `main` integration) - explicit human
   authorization required.
2. BL-053 remediation design (TOCTOU seal re-check) - affects verdict trust
   semantics; product/security decision on re-validation policy.
3. BL-067 (uncapped in-memory download zip) - needs a product-set size cap.
4. Scope language: no universal-COBOL, runtime-equivalence, or
   production-readiness claims are made anywhere; any future such claim
   needs owner sign-off against the capability registry.
5. T7 supply-chain gate fix prioritization - security-relevant (audit exit
   codes currently swallowed).

### 7.9 Explicit unknowns that could not be verified

- The 4 Docker-gated tests (`RUN_DOCKER_TESTS=1`) were not executed locally
  (Docker daemon unavailable in this environment); they are covered by the
  CI Docker job, which runs them green. Local runs record them as the
  pre-existing 4 skips.
- `fixtures/` (176 files) are structurally inventoried, not semantically
  re-audited line-by-line.
- `forensic_proof.py`'s 6 functions are never collected by pytest (naming);
  recorded as a finding, deliberately not renamed (would change the CI test
  set).
- Runtime equivalence of generated Java vs COBOL is NOT claimed and was not
  measured; only the deterministic pipeline invariants and test evidence are
  asserted.
- T4's hand-check items (sql/execution.py:432/441 + 172/188,
  sql_parser.py:422-425, jcl_consumer.py:107-112, ir.py capability
  829/914-930, T8 App.tsx/ModernizationRun trio) were verified at the
  finding level during Stage C; line-exact re-verification against the
  post-Stage-D line numbers is deferred to the BL remediation cycle (the
  defect sites themselves were not modified).

### 7.10 Next-step recommendation

1. Review and triage BL-040..BL-068 (owner assignment per §76-phase map).
2. Fix BL-040 (P0) with a dedicated regression corpus in the next cycle.
3. Land the T7 workflow/script hardening (pipefail, verify-production,
   backup paths, artifact staleness) as an isolated ops PR.
4. Keep `codex/universal-core` unmerged until a human authorizes; then
   merge with the exact-SHA CI-green run attached as evidence.
5. Do not close any BL entry without evidence; backlog entries are resolved
   only with a verified commit reference.
