# Repository-Wide File-Level Audit Report — Cobol-Java-Transformation

> **Reconciliation note (2026-10-27):** the first draft of this document
> (committed `cb89b46`) was generated from the historical `CODE_AUDIT_REPORT.md`
> snapshot without checking the authoritative register (`docs/BACKLOG.md`).
> It misreported BL-040 as OPEN (register: FIXED 2026-10-14), misreported
> BL-045/BL-046/BL-054 as open Java-literal/hash defects (register: all FIXED,
> and BL-045 is actually the nested-CALL defect, not escaping), misattributed
> IDs BL-110/BL-111 (those register rows are the contract-V2 and mutation-gate
> decisions — the real supply-chain/verify-production defects were
> *unregistered* T7 findings, now filed as **BL-143/BL-144**), and quoted the
> stale 3,476-test count. This revision reconciles every finding against the
> register and the code at the baseline below. Where this document and the
> register disagree, **the register wins**.

## A. Baseline and scope

| Field | Value |
|---|---|
| Branch | `codex/universal-core` |
| HEAD at audit start | `cb89b460b257c31e5de709723e73d4d910687d97` |
| Working tree at start | clean (0 modified, 0 staged, 0 untracked) |
| User changes to preserve | none present; `test-artifacts/*` untouched throughout |
| Python | 3.12.3 (`.venv`), dependencies per `requirements.lock` |
| Docker | 29.8.2 available (daemon live) |
| Node | v20 (`/mnt/c/Program Files/nodejs`) |
| Tests collected (baseline) | **4,303** (the old 3,476 figure was stale) |
| Full-suite baseline run | started at `cb89b46`, JUnit at `/tmp/opencode/audit/baseline-junit.xml` (checkpoint run; see §G) |
| Method | line-by-line executable-source review, defect verification against `docs/BACKLOG.md` + code probes, red-first remediation |
| Invariants held | deterministic NO-LLM pipeline; fail-closed capability/evidence; no test weakened; no unjustified skip; no commit/push/merge |

**Scope:** all 982 tracked files (executable classes line-by-line; tests via
naming/assertion audit + spot checks; fixtures structural). Delivery is
group-by-group — this document records what has been *verified fixed in the
working tree* versus *verified already fixed in the register* versus
*documented limitation*.

## B. File inventory and per-file findings (reconciled)

Every cell below was re-verified against the file content and the register
at the baseline. **Bugs** cells only list defects that were *open* at audit
start (or proven by probe); register-FIXED ids are shown with their true
status, not re-claimed as open.

### B.1 Core engine — `engine/modernization/` (7 files)

| File | Limitations | Gaps | Issues | Bugs at audit start | Notes |
|---|---|---|---|---|---|
| `modernization_planner.py` | planning limited to supported constructs | no multi-program lifecycle mgmt | overall-status derivation ignored UNKNOWN (see BL-139(2)) | **BL-139(2)** FIXED this session | BL-043 fail-open default already FIXED 2026-10-14 (cap=None→UNKNOWN, verified in code) |
| `capability_analyzer.py` | static analysis only | no runtime emergence detection | `_analyze_call` treated missing callee as SUPPORTED | **BL-139(1)** FIXED this session | probe-proven red before fix |
| `transformation_plan.py` | immutable plans | no runtime self-adaptation | — | none found (BL-053 lives in `engine/verdict`, FIXED 2026-10-16) | old draft's BL-053 cell was wrong-file |
| `integrated_proof.py` | sequential verification | no parallel proof checking | — | none found | fail-closed BLOCKED for runtime-less lanes |
| `application_assembler.py` | Spring Boot templates only | other frameworks unsupported | — | none found | design scope |
| `external_dependency_edges.py` | classification only | no runtime validation | — | none found | all entries UNSUPPORTED/BLOCKED fail-closed (verified) |
| `pipeline.py` (modernization) | sequential | — | — | none found | discovery incomplete → fail-closed |

### B.2 Core engine — `engine/transformation/` (35 files)

| Area | Limitations | Gaps | Issues | Bugs at audit start | Notes |
|---|---|---|---|---|---|
| `cobol_parser.py` | line-oriented statement model (same-line two-statement spelling out of scope) | residual UNSUPPORTED-with-diagnostic coverage gaps only | — | **none open** — BL-040 FIXED 2026-10-14, re-verified green this session (27 passed: `test_string_period_termination.py` + `test_silent_loss_registry.py`) | BL-055/BL-058 also register-FIXED |
| `java_generator.py` / `spring_boot_generator.py` | generated-lane subset | — | — | **none open** — BL-046 FIXED 2026-10-16; both lanes use canonical `JavaGenerator._escape_java_string` (verified lines 858/693-708) | old draft's "BL-045/046 open" cell was stale |
| `cics_parser.py` (in transformation/) | supported CICS subset only | no CICS runtime (BL-132 entitlement) | newline split dropped wrapped operands | **BL-142** FIXED this session | probe-proven red before fix |
| `cics/generator.py` (engine/cics) | mapping/generation only | no CICS TS execution | — | none open — BL-057 FIXED 2026-10-15 (`_java_arg` escaping + test) | fixtures declare "NOT executed on CICS TS" |
| copybook lanes (`copybook_*.py`) | deterministic search-path subset | REPLACING corner cases documented | — | none open — BL-031/032/035/056 register-FIXED | decode failures fail closed |
| mapper (`cobol_to_java_mapping.py`) | supported construct subset | — | — | none open — BL-045 (nested CALL `called_programs`) FIXED 2026-10-16 | note: BL-045 is *not* an escaping defect |

### B.3 Core engine — candidate / evidence / verdict / pipeline

| File | Limitations | Gaps | Issues | Bugs at audit start | Notes |
|---|---|---|---|---|---|
| `engine/pipeline.py` | sequential stages | no parallel processing | candidate identity derives from source tree only | none open — BL-054 FIXED 2026-10-15 (identity walk skips top-level `target/`, code verified line 221) | old draft's BL-054 cell was stale |
| `engine/candidate/docker_spring_boot_adapter.py` | offline Maven only | network builds unsupported | writes build JAR back to `candidate_path/target` (by design; excluded from identity) | none open | JAR write-back is intentional for execute(); identity excludes it |
| `engine/candidate/docker_java_adapter.py` | digest-pinned runtime | — | — | none open — BL-050 FIXED (proc=None init) | hardening flags per BL-135 |
| `engine/evidence/*` | sealing + integrity | no TTL (BL-113 deferred) | — | none open — BL-053 FIXED 2026-10-16 (verdict seal re-check) | |
| `engine/verdict/derivation.py` | single derivation path | mutation gate deferred (BL-111/D-11) | — | none open | single VERIFIED site, fail-closed |
| `engine/oracle/docker_adapter.py` | GnuCOBOL oracle lane | no ESQL (BL-130) | — | none open — BL-051 FIXED | digest identity fail-closed |

### B.4 API layer (10 files)

| File | Limitations | Gaps | Issues | Bugs at audit start | Notes |
|---|---|---|---|---|---|
| `api/artifact_seal.py` | per-file SHA-256 seal | approval-gate TOCTOU acceptable (state change, re-verified at download) | verify→package window in download path | **BL-140** FIXED this session | `read_verified_bundle` now reads-and-verifies once |
| `api/service.py` | single-worker orchestration | no retry/cancel (BL-115 deferred) | full-row RMW writes; ingest deleted previous source pre-update | **BL-141** FIXED this session | column-scoped writes + delete-after-update ordering |
| `api/store.py` | SQLite single-node | multi-node deferred (BL-122) | full-row `update_application` clobbered concurrent writers | **BL-141** FIXED (new `update_application_fields`) | legacy full-row kept for fixtures |
| `api/ingestion.py` | zip caps (50 MB default) | chunked upload absent | — | none open — BL-047/048/137 register-FIXED | hostile-path suite green |
| `api/app.py` | in-memory download archive (capped) | uncapped? no — 5000 files/50 MB caps | double-read after seal verify | **BL-140** FIXED | caps enforced during single read |
| `api/name_derivation.py` | simple naming | no locale rules | — | none found | |

### B.5 Frontend (42 files)

T8 group findings from `CODE_AUDIT_REPORT.md` (state-correctness trio etc.)
are register-FIXED (BL-066/BL-068). No new frontend defects opened this
session; frontend build verification recorded in §G.

### B.6 Tests (520 files → 4,303 baseline collected)

| Finding | Disposition |
|---|---|
| No assertion-less test files (sweep) | verified |
| `test_unknown_level_blocking_is_expected_but_unasserted` (body `pass`) | **BL-145** FIXED — replaced with 2 asserting tests |
| `test_stdout_has_iterations` (body `pass`) | **BL-145** FIXED — replaced with DISPLAY-trace ordering test |
| 20 files with `skipif` | all Docker/environment-gated with reasons — justified, untouched |
| Remaining 4 bare `pass` | idiomatic (class bodies / no-op branches) — not defects |
| Commented assertions (4) | historical notes documenting *strengthened* assertions (BL-017/BL-075) — not regressions |
| Status-code-only spots | sampled critical files (`test_api.py` 50 asserts, `test_e2e.py` 74) — body assertions present |

### B.7 CI, deployment, configuration

| File | Limitations | Gaps | Issues | Bugs at audit start | Notes |
|---|---|---|---|---|---|
| `.github/workflows/supply-chain.yml` | — | — | `| tee` without `pipefail` → audits could never fail | **BL-143** FIXED this session | `ci.yml` already had pipefail everywhere it pipes |
| `.github/workflows/ci.yml` | fixed capability-gate file list | coverage thresholds absent | — | none open — BL-138 register-FIXED | gate = 58 files (3 added this session: BL-139/142/145 suites), 1 deselect by design; exact gate command re-run green (834 passed, 1 deselected, exit 0) |
| `scripts/deploy/verify-production.sh` | requires live production stack | — | `; rm false-PASS masking` on visibility probe | **BL-144** FIXED this session | behavioral proof recorded in test |
| `scripts/deploy/*.sh` (others) | ops-only | — | no masking patterns found | none | `bash -n` clean |
| `docker-compose.production.yml` | production-only | dev config lives elsewhere | — | none open — BL-099/136 register-FIXED | token `:?` required |
| `Dockerfile.production` | production-only | — | — | none found | non-root per BL-135 lanes |

### B.8 Documented limitations (not defects — owner-approved or external)

DB2 lane `PORTABLE_EXECUTABLE` only (BL-130 BLOCKED); CICS/IMS mapping-only
(BL-132 entitlement); JCL build/start PARTIAL (BL-133 MVS); MQ no lane
(BL-131); rate limiting/TTL/cancel/enterprise-security deferred
(BL-113/114/115/122 with D-7..D-9 waivers); mutation gate deferred
(register BL-111/D-11); single-token auth (BL-122).

## C. Remediation checklist (traceable: finding → file → fix → test → verification)

All fixes are **red-first** (failing test/probe captured before the change).
All work is in the **working tree only** — no commit, push, or merge
(authorization not granted).

| ID | File(s) | Root cause | Pri | Fix | Regression test | Verification result |
|---|---|---|---|---|---|---|
| **BL-139(1)** | `engine/modernization/capability_analyzer.py` (`_analyze_call`) | `callee is None or callee is SUPPORTED → SUPPORTED` treated an unanalyzed callee as fully transformable | P1 | missing callee → `UNKNOWN` with reason naming the target | `tests/transformation/test_call_capability_fail_closed.py` (new, 6 tests) | **red 2 failed/4 passed → 6 passed**; capability regression **215 passed**; broader batch **239 passed** |
| **BL-139(2)** | `engine/modernization/modernization_planner.py` (`_derive_overall_status`, `ProgramPlan.is_blocked`) | UNKNOWN components ignored → READY whenever ≥1 SUPPORTED (probe: UNKNOWN+SUPPORTED → READY) | P1 | `unknown_count > 0 → BLOCKED`; `is_blocked` includes UNKNOWN; blocking summary includes UNKNOWN programs | `test_unknown_component_never_yields_ready_overall_status` (new) | **probe red READY → green BLOCKED**; planner suite **39 passed** (incl. new `test_unknown_level_blocks_program_plan` replacing the `pass` placeholder) |
| **BL-140** | `api/artifact_seal.py`, `api/app.py` (`download_generated`) | seal verified, then files re-read from disk for `ZipFile.write` (verify-then-zip TOCTOU) | P1 | `read_verified_bundle`: single read → hash those bytes vs seal → `ZipFile.writestr` same buffers; caps enforced during read | `tests/test_evidence_substitution.py` +4 (swap-mid-request behavioral test, 3 unit) | **red 4 failed → 29 passed**; download/approval batch **63 passed** |
| **BL-141** | `api/store.py`, `api/service.py` (ingest, upload_cobol, upload_java, _generate_application) | full-row RMW clobbers concurrent column writes; ingest deleted previous source before the store update | P1 | `update_application_fields` column-scoped writes (validate columns; encode lists; NotFound); service paths write only changed columns; delete-after-successful-write ordering | `tests/test_application_lost_updates.py` (new, 9 tests; concurrent-rename hijack via `get_application`) | **red 9 failed → 9 passed**; API/ingestion/persistence/e2e-support batch **140 passed** |
| **BL-040 (verify)** | `engine/transformation/cobol_parser.py` | register says FIXED 2026-10-14; old audit said OPEN | — | no change needed | `tests/transformation/test_string_period_termination.py`, `tests/test_silent_loss_registry.py` | **27 passed** — register confirmed, audit corrected |
| **BL-142** | `engine/transformation/cics_parser.py` (`_split_statements`) | split on every top-level newline → wrapped operand lines identify no command → dropped (`from_field=''` probe) | P1 | period-split first; line-merge starts a new statement only when balanced **and** next line begins a known CICS verb | `tests/transformation/test_cics_multiline_parsing.py` (new, 13 tests) | **red 8 failed/4 passed → 13 passed**; full CICS regression **241 passed** |
| **BL-143** | `.github/workflows/supply-chain.yml` | default GH `run` shell is `bash -e` (no pipefail); `audit \| tee` exits with tee → gate never fails | P2 | `set -o pipefail` first in every `| tee` block (5 blocks), matching `ci.yml` convention | `tests/test_ci_deployment_security.py` (new, structural PyYAML assertions) | **red 1 failed → supply-chain tests green (8/8 file)**; `yaml.safe_load` OK |
| **BL-144** | `scripts/deploy/verify-production.sh` | `bash -c "… \| grep -q probe; rm -f …"` exits with rm's 0 → `check()` false PASS (behaviorally proven) | P1 | capture `rc=$?`, cleanup unconditionally, `exit $rc` | same file: no-masking-idiom assertion + behavioral idiom propagation proof | **red 2 failed → 8/8 passed**; `bash -n` OK |
| **BL-145** | `tests/transformation/test_modernization_planner.py`, `tests/integration/test_copybook_runtime.py` | two tests passed with body `pass` (zero coverage presented as coverage) | P2 | replaced with asserting tests (UNKNOWN blocking contract ×2; DISPLAY-trace ordering) | the replacements themselves | **39 passed planner**; copybook test Docker-gated — covered by full-suite run (§G) |

### Reconciled stale findings (no code change — audit corrected)

| Old audit claim | Register/code truth | Action |
|---|---|---|
| BL-040 OPEN (P0) | FIXED 2026-10-14 (period-bounded `_parse_string`) | status corrected; fix re-verified green |
| BL-045 "Java literal escaping OPEN" | BL-045 = nested-CALL `called_programs`, FIXED 2026-10-16; escaping = BL-046, FIXED 2026-10-16 | status + characterization corrected |
| BL-046 OPEN | FIXED 2026-10-16 (canonical `_escape_java_string` in both lanes) | status corrected |
| BL-054 OPEN (JAR write-back) | FIXED 2026-10-15: identity walk skips top-level `target/` (`pipeline.py:221` verified) | status corrected; write-back itself is intentional |
| "BL-110 supply-chain pipefail" | Register BL-110 = contract V2 (FIXED D-10) — different defect | real defect filed as **BL-143** |
| "BL-111 verify-production rm" | Register BL-111 = verdict mutation gate (DEFERRED D-11) — different defect | real defect filed as **BL-144** |
| 3,476 tests collected | **4,303** at baseline (+ new tests this session) | count corrected; see §G |
| BL-053 attributed to `transformation_plan.py` | BL-053 = verdict `derive_from_validated` seal re-check, in `engine/verdict`, FIXED 2026-10-16 | attribution corrected |

## D. Architectural patterns (unchanged, re-affirmed)

- **Fail-closed security model:** negative contracts for unresolved
  CALL/COPY, BY VALUE/BY CONTENT, unknown capability, missing seals,
  unanalyzed callees (BL-139), UNKNOWN components (BL-139(2)).
- **Deterministic NO-LLM pipeline:** no model calls anywhere in
  transformation/verification paths; all probes this session were
  deterministic Python/bash.
- **Capability truth:** never SUPPORTED when generation or analysis fails —
  now also never SUPPORTED for an *absent* callee and never READY overall
  while any component is UNKNOWN.
- **Evidence integrity:** manifest seal (verdict path) + generated-bundle
  seal (export path, now TOCTOU-free per BL-140).
- **Owner-approved deferrals:** BL-113 TTL, BL-114 rate limit, BL-115
  cancel/retry, BL-116 lane materialization, BL-122 enterprise scope —
  unchanged, still explicitly deferred.

## E. Runtime gaps (unchanged — no unsupported equivalence claimed)

| Lane | State | Authority |
|---|---|---|
| DB2/SQL | `PORTABLE_EXECUTABLE` (SQLite harness); `DB2_RUNTIME_VERIFIED` empty **by contract** | BL-130 BLOCKED (no ESQL preprocessor/client/DB-state comparator) |
| CICS | mapping/generation only; fixtures "NOT executed on CICS TS" | BL-132 BLOCKED (IBM entitlement UNAUTHORIZED) |
| JCL | build/start PARTIAL | BL-133 BLOCKED (no provenance-verifiable MVS image) |
| MQ | classification only | BL-131 BLOCKED (no execution lane/test) |
| IMS | classification only | BL-132 |
| Indexed/relative files | certified subset PROVEN (primary key offset 0, DYNAMIC, no ALTERNATE) | BL-134; VSAM file-image equivalence **not claimed** |

No document updated this session claims DB2/CICS/JCL/MQ/IMS runtime
equivalence or production readiness.

## F. Compliance and policy adherence

- **Supply chain:** BL-143 restores the documented gate (audits can fail).
  SBOM steps also pipefail-protected. No dependency changed.
- **Evidence integrity:** BL-140 closes the export-window substitution
  path; approval gate unchanged; store remains the trust boundary
  (documented).
- **Test integrity:** no assertion weakened, no skip added; two
  zero-assertion tests *strengthened* (BL-145); new tests added red-first.
- **Secrets:** no secrets/keys introduced; no logging of tokens.
- **Historical docs:** `CODE_AUDIT_REPORT.md` (labeled historical) left
  untouched; live corrections confined to this audit + BACKLOG.

## G. Verification results and explicit unknowns

### G.1 Focused results (this session, exact)

| Suite | Result |
|---|---|
| BL-040 + silent-loss registry (`test_string_period_termination.py`, `test_silent_loss_registry.py`) | **27 passed** |
| BL-139 red-first (`test_call_capability_fail_closed.py`) | red **2 failed/4 passed** → green **6 passed** |
| Capability regression batch (10 files incl. registry reconciliation, producer consistency, docker truth, planner) | **215 passed** |
| BL-140 red-first additions (`test_evidence_substitution.py -k TestDownloadServesVerifiedBytes`) | red **4 failed** → green (file **29 passed**) |
| Download/approval batch (evidence_sub + phase11 + phase12 approval) | **63 passed** |
| BL-141 red-first (`test_application_lost_updates.py`) | red **9 failed** → green **9 passed** |
| API/ingestion/persistence batch (test_api, ingestion_diagnostics, control_plane_persistence, async_modernize, upload_hostile_paths, evidence_sub, lifecycle_state_machine, modernization_p0) | **140 passed** (100.65 s) |
| BL-142 red-first (`test_cics_multiline_parsing.py`) | red **8 failed/4 passed** → green **13 passed** |
| Full CICS regression (all `*cics*` test files) | **241 passed** |
| BL-139(2)/BL-145 planner suite (`test_modernization_planner.py`) | **39 passed** |
| Modernization/capability batch after UNKNOWN→BLOCKED (13 files) | **239 passed** |
| BL-143/BL-144 red-first (`test_ci_deployment_security.py`) | red **3 failed/5 passed** → green **8 passed** |
| New/changed focused batch (all 8 touched test files + BL-040 pair) | **130 passed** |
| CI capability-truth gate (exact `ci.yml` command, now including BL-139/142/145 files) | **834 passed, 1 deselected, exit 0** (pre-session: 777+1) |
| Frontend `tsc --noEmit` (lint) | **exit 0** |
| Frontend `tsc -b && vite build` | **exit 0** (vite 6.4.3, 53 modules, dist emitted) |
| Frontend vitest | **160 passed (15 files), exit 0** — matches the (bh) baseline |
| `docker compose -f docker-compose.production.yml config` (rendered, with `.env.production` from example + dummy token; temp file removed) | **exit 0**, 134 lines; `CONTROL_PLANE_ENV: production` + required token interpolated; 6 hardening references present; render **fails closed** without the token (BL-099/136 gate proven) |
| `bash -n` on all four `scripts/deploy/*.sh` | syntax OK |
| `yaml.safe_load(.github/workflows/supply-chain.yml)` | parses OK |
| Full-suite baseline (4,303 collected @ `cb89b46`; final tree collects **4,343**) | JUnit `/tmp/opencode/audit/final-junit.xml` — run in flight at §G write time; final counts to be quoted from that artifact (see final report) |

### G.2 Explicit unknowns / not verified this session

- **Full 4,343-test outcome** and the Docker-gated runtime-proof lanes
  depend on the background full-suite/JUnit completion — quoted only from the
  artifact, never estimated.
- **`tests/integration/test_copybook_runtime.py`** ordering test is
  Docker/Maven-gated; it did not complete when run concurrently with the
  earlier baseline (timeout) — covered by the running full-suite (Docker
  available on this host, so its `skipif` passes and it executes); not
  claimed green until the artifact says so.
- **Live-stack deployment behavior** (TLS handshake, nginx serving, real
  `/health` over HTTPS) was not exercised end-to-end — verification here is
  script syntax, structural tests, and the *rendered* compose config
  (`docker compose config` exit 0 + fail-closed token gate proven).
- **Runtime equivalence of generated Java vs COBOL** is NOT claimed and was
  not measured beyond the existing certified-subset evidence.
- Fixtures (176) remain structurally inventoried, not semantically
  re-audited.

### G.3 Findings register status after this session

- **New, FIXED in working tree:** BL-139, BL-140, BL-141, BL-142, BL-143,
  BL-144, BL-145 (rows added to `docs/BACKLOG.md`, change-log **(bi)**).
- **Verified already FIXED (register):** BL-040, BL-045, BL-046, BL-053,
  BL-054, BL-057 and the rest of the BL-040..BL-068 family per register.
- **Still BLOCKED/deferred (unchanged):** BL-093 (D-4), BL-130/131/132/133
  (runtime lanes), BL-113/114/115/116/122 (D-7..D-9), register-BL-111/112
  (D-11), BL-015 (PR merge — human only).
- **Open P0:** none (register authority; this session introduced none).

## Production-readiness statement

**Not production-ready, and not claimed.** This session closed seven
actionable defects (fail-open capability paths, export TOCTOU, lost
updates, CICS operand loss, two false-PASS shell gates, two zero-assertion
tests) with red-first evidence, but the deferred controls (BL-113/114/115/
122), single-token auth, blocked runtime lanes (BL-130..133), and the
pending full-suite/JUnit + frontend-build checkpoints remain exactly as
documented. No capability label was made more favourable anywhere.

---

*Report generated 2026-10-27; reconciled against `docs/BACKLOG.md` (register
= priority authority) and code probes at `cb89b46` + working tree.*
*Scope: repository-wide file-level audit. Methodology: line-by-line
executable-source review, defect verification, red-first remediation.*
