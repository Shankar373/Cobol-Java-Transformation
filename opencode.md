# opencode.md — SystemaOps Live Implementation Checkpoint

## Phase 0 closure audit — 2026-10-10

### Current verification state
- Repository: `Shankar373/Cobol-Java-Transformation`
- Branch: `codex/universal-core`
- Audit baseline: `55f885dae77bd415fc60db6d90e59ef26fc47944` (`docs(checkpoint): record final local regression and CI job status`)
- Closure remediation commits (docs only, applied on top of that baseline): `87b0c9b` (backlog + checkpoint contract), `55324b8` (explicit backlog metadata), `0d7e073` (Phase 0 baseline evidence links). **Current HEAD at this checkpoint edit: `0d7e0732ef25844b968ba5975e4be9f1bfa7572a`.**
- Baseline CI: [Push #453](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045547063) and [PR #454](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045549842) passed all jobs, including ingestion diagnostics, capability truth, frontend tests/TypeScript/build, backend COBOL/Java Docker tests, and supply-chain checks. Docker tests ran in Linux CI; no Docker-in-Docker or WSL2/cgroup/security workaround was attempted.
- **Final Phase 0 closure commit: `9326f80c8a72790f76710dae60bd9ac2b339f99a`** (`docs(phase0): record final exact-SHA CI evidence at f8b8488`). Its own exact-SHA CI is green: Push [#465](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060676341) SUCCESS and PR [#466](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060679478) SUCCESS, all four required jobs green in both; Supply chain [#47](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060676233) / [#48](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060679429) SUCCESS.
- Predecessor `f8b8488`: Push [#463](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38058893785) SUCCESS and PR [#464](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38058897089) SUCCESS.
- Intermediate commit `0d7e073`: Push [#459](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38047651675) FAILED on one pre-existing flake (BL-017) while PR [#460](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38047656074) passed on the identical SHA. Investigated, not ignored; see BL-017.
- Audit verdict before remediation: `INCOMPLETE` — the backlog did not explicitly record the §53.10 / §77 owner/role, target phase, dependency, residual risk, and acceptance fields for carried items.
- Remediation scope: documentation only. No transformation source, tests, registry, capability claims, PR state, or merge state changed.
- This checkpoint is the live status record. The old session notes below are retained as historical context and must not override this block.

### Phase 0 closure work in this remediation
1. Add a carry-forward metadata register for BL-001…BL-016 in `docs/BACKLOG.md`, including owners by role, target phase, dependencies, reasons, residual risks, and explicit acceptance criteria.
2. Record dispositions and safeguards for PRs #1, #2, #3, and #6. PR #2 remains unmerged pending an explicit human decision. PR #3 remains validation-only and unmerged. PRs #1 and #6 remain open pending human disposition.
3. Correct the checkpoint filename in the Master README to the actual canonical repository path, `opencode.md`, to remove the competing `open code.md` specification.
4. Keep Phase 0 status provisional until fresh CI for the remediation commit completes successfully. The prior green baseline is not substituted for exact-commit CI.

### Acceptance evidence and limitations
- Phase 0 architecture/specification, no-LLM policy, phase roadmap, backlog, documentation consistency, and baseline protection were audited against the Master README and current source.
- The audit's Windows test result was 3,091 passed, 12 skipped, 26 environment-only failures due to missing local `javac`/Docker; Linux CI on the exact baseline SHA passed the Docker/JDK/GnuCOBOL-dependent jobs. Do not describe the local run as fully green.
- No fresh local E2E is claimed. Exact-SHA Linux CI is the evidence for Docker-dependent validation.
- Phase 0 does not certify universal COBOL support, z/OS/JCL/DB2/CICS equivalence, production readiness, or security certification.
- **Status at this checkpoint edit:** **`COMPLETE — VERIFIED`** for Phase 0 scope (§52 Architecture + Master README Freeze), evidenced at exact SHA `9326f80` (Push CI #465, PR CI #466, Supply chain #47/#48 — all green). See the acceptance matrix and scope boundary above. Phase 1 is **not** started.

### Phase 0 acceptance matrix (Master README §§52–53, 64–80)

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | Master architecture/specification and phase roadmap authoritative and internally consistent | `MASTER_IMPLEMENTATION_README.md` §9–10 canonical architecture + one canonical pipeline; §52 phase list; §53 13-point completion rule; `docs/ARCHITECTURE.md` pipeline matches §10 | PASS |
| 2 | Checkpoint path is consistently `opencode.md`; no competing checkpoint file | Master README §64/65/67/68/75/78/80 all renamed from `open code.md` to `opencode.md` in `0d7e073`; repo contains exactly one checkpoint (`opencode.md`); no `open code.md` / `open_code.md` / `OPENCODE.md` exists | PASS |
| 3 | Project-wide NO-LLM rule preserved | `requirements.txt` + `requirements.lock` contain no AI/ML package; no `openai`/`langchain`/`anthropic`/`genai`/`ollama`/`huggingface`/`litellm`/`haystack`/`llamaindex`/`bedrock` reference in `api/`, `engine/`, `scripts/`, `.github/`, `frontend/`. The 7 grep hits are the English word "coherent" matching a `cohere` prefix — false positives per §79 | PASS |
| 4 | Deterministic pipeline, capability boundaries, evidence/verdict trust accurately documented | §10 (one canonical pipeline), §14 (registry is source of capability truth), §38 evidence, §39 verdict, §41 integrated proof; `engine/transformation/semantic_capability.py` is the single registry; CI `capability-truth` job enforces it | PASS |
| 5 | Backlog records all open/carry-forward items with owner/role, target phase, dependency, reason, residual risk, testable acceptance criteria | `docs/BACKLOG.md` §"Phase 0 closure metadata and carry-forward register", table covering BL-001…BL-017 with all required columns | PASS |
| 6 | Closed items have valid supporting evidence; unresolved items not mislabeled complete | BL-001…BL-009, BL-011 cite named files/tests/commit evidence; BL-004 explicitly "RESOLVED BY DESIGN DECISION — no code change"; BL-012 "PARTIALLY FIXED"; BL-010 "BLOCKED (environment)"; BL-013…BL-017 OPEN carry-forward | PASS |
| 7 | Tests, security, integration gates and fresh E2E evidence accurately recorded | Local `pytest -q tests`: 3,091 passed / 12 skipped / 26 failed, all 26 verified environment-only (`javac`/`java` missing, Docker unavailable) — explicitly **not** described as green. Linux CI executes the full 3,129-test suite with GnuCOBOL 3.1.2 + temurin:21. Security suites: `tests/adversarial/` (13 files), `tests/test_api_security.py`, `tests/verdict/test_verdict_trust_boundary.py`. **No fresh local E2E is claimed.** | PASS (with E2E limitation stated) |
| 8 | Documentation matches live repository, PRs and CI | BL-008 (false "integrated proof not wired") and BL-009 (stale `fedb7dd`/CI #417–418) fixed and re-verified against `api/service.py` and `api/app.py`; this block replaces the earlier stale HEAD pointer | PASS |
| 9 | Exact-SHA CI gate green | **PASS at `9326f80`.** Push CI [#465](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060676341) and PR CI [#466](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060679478) both SUCCESS with all four required jobs green (ingestion, capability truth, frontend, backend COBOL/Java Docker); Supply chain [#47](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060676233) / [#48](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060679429) SUCCESS. Green was also confirmed on the two preceding closure commits `f8b8488` (#463/#464) and `ef42b82` (#461/#462). The commit before those, `0d7e073`, had Push CI #459 red on one pre-existing flake while PR CI #460 passed on the *identical* SHA — see BL-017; the flake did not recur and no test was weakened, skipped, or relaxed to obtain these results | PASS |
| 10 | No tests weakened; no LLM introduced; no fabricated evidence | Only `.md` files changed in this closure. No test file, assertion, skip marker, or dependency touched. No LLM dependency added | PASS |
| 11 | All §53 criteria satisfied | All eleven criteria above PASS | PASS |

### Phase 0 verdict

**`COMPLETE — VERIFIED`** — for the scope defined by Master README §52 (*Architecture + Master README Freeze*).

All eleven acceptance criteria pass on current evidence at the exact audited SHA. This verdict is bounded:

- It rests on **exact-SHA CI**, not on the earlier green baseline. The prior baseline `55f885d` (#453/#454) is cited as provenance only and was not substituted for current evidence.
- The one intermediate red run (`0d7e073` Push CI #459) was investigated rather than ignored: identical SHA passed on PR CI #460, no code had changed since the green baseline, and the failure did not recur on any of the three subsequent closure commits. It is filed as **BL-017** and remains **OPEN** — Phase 0 does not claim that flake is fixed.
- Green was never manufactured: no test was modified, skipped, or relaxed. Every change in this closure is a `.md` edit.
- Phase 0 completion does **not** close BL-010, BL-012, BL-013…BL-017. Those remain carried forward with owner, dependency, residual risk, and acceptance criteria in `docs/BACKLOG.md`.

**Scope boundary:** this verdict certifies documentation accuracy, architecture/specification freeze, capability-truth governance, and the CI gate — nothing more.

### Not claimed by Phase 0
Phase 0 closure certifies **documentation, architecture freeze, and capability-truth governance only**. It does **not** certify universal COBOL support, z/OS / JCL / DB2 / CICS behavioural equivalence, production readiness, or security certification. A green CI run means the certified subset's gates passed — never semantic equivalence.

### Live links
- [Master Implementation README](https://github.com/Shankar373/Cobol-Java-Transformation/blob/codex/universal-core/MASTER_IMPLEMENTATION_README.md)
- [Central backlog and carry-forward register](https://github.com/Shankar373/Cobol-Java-Transformation/blob/codex/universal-core/docs/BACKLOG.md)
- [PR #2 — capability truth change](https://github.com/Shankar373/Cobol-Java-Transformation/pull/2)
- [PR #3 — validation-only candidate](https://github.com/Shankar373/Cobol-Java-Transformation/pull/3)
- **Phase 0 closure exact-SHA CI (`9326f80`): [Push #465](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060676341) · [PR #466](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060679478) · [Supply chain #47](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060676233) · [#48](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38060679429)** — all required jobs SUCCESS
- Predecessor `f8b8488` (provenance): [Push #463](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38058893785) · [PR #464](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38058897089)
- Predecessor `ef42b82` (provenance): [Push #461](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38049461830) · [PR #462](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38049465043)
- Prior green baseline `55f885d` (provenance only): [Push #453](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045547063) · [PR #454](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38045549842)
- Intermediate `0d7e073` (flake evidence, BL-017): [Push #459](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38047651675) · [PR #460](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/38047656074)

### Phase 0 handoff (next phase — not started)

Phase 0 is closed; Phase 1 (*Parser / Universal IR Expansion*) has **not** begun. On starting it:

1. Read `MASTER_IMPLEMENTATION_README.md` §§52–53, 64–68, 76–80, then this checkpoint, then `docs/BACKLOG.md`.
2. Confirm the live HEAD and its exact-SHA CI before editing; preserve `test-artifacts/*` and any untracked user files.
3. Take open backlog items in order: **BL-017** (test reliability, Phase 12 target but blocks nothing), **BL-013/BL-014** (PR dispositions), **BL-012** (CI quality gates, Phase 12), **BL-010** (Docker validation, Phase 9/12). Closed items BL-001…BL-009, BL-011 must not be re-implemented; their evidence is in `docs/BACKLOG.md`.
4. Before adding any COBOL construct capability, check for an existing negative contract first — BL-004 is the precedent where the repository deliberately chose to keep a capability *unclassified* and a registry key would have been an over-claim.
5. Do not regress the capability-truth gate (`Capability truth gate` CI job, ~1 min, dependency-free) or weaken any test to obtain green.

---


Checkpoint authority (Master README §64): `MASTER_IMPLEMENTATION_README.md`
defines what must be built; this file records **where implementation currently is**.
It must never contradict repository reality (§68) and must never be left misleading.

---

## Historical session 2026-10-10 (superseded by Phase 0 closure audit above)

### Baseline (verified this session)
- Repository: `https://github.com/Shankar373/Cobol-Java-Transformation.git`
- Branch: `codex/universal-core`
- Session start HEAD: `81e795584e42437e4194bcb317ca20594c621adc`
  ("docs: strengthen master implementation audit and backlog contract")
- **Historical checkpoint reference only:** `ca38321` and the older CI runs below are retained for provenance; the current audit baseline and live CI links are in the Phase 0 closure block above.
- Base branch: `main` (`a923c65`)
- Working tree: dirty by design — untracked `opencode.md`, `test-artifacts/*`
  evidence, and a modified `test-artifacts/docker-image-provenance.json`
  (pre-existing, preserved). No tracked source files were modified before this session.
- Local branch was one commit behind `origin` at session start; fast-forwarded
  `7ae5873 → 81e7955` (docs-only). No reset, no force-push, no user files discarded.

### Historical CI status for the earlier audited HEAD `81e7955` (not the current baseline)
- Push CI #427 — SUCCESS
- PR CI #428 — SUCCESS
- Supply chain #9 (push) / #10 (PR) — SUCCESS
- This is historical evidence only; current baseline is `55f885d` and fresh remediation CI is required.

### Environment
- OS: Windows 11 Home (Build 26200); git 2.55.0 at `C:\Program Files\Git\bin\git.exe`
  (not on PATH).
- Python 3.11.9 available; test venv `.venv-audit` (Windows; `uvloop` excluded
  because it does not build on Windows).
- Node/npm: NOT installed. Java/Maven: NOT installed.
- Docker CLI present, but the Windows/WSL2 Docker bind-mount + cgroup issue remains an
  environment blocker. Per instruction, do NOT retry Docker-in-Docker and do NOT change
  WSL2/kernel/cgroup/Docker security settings; use Linux CI for Docker-dependent gates.

### Current phase / status
- No Master README phase is marked **VERIFIED COMPLETE** under §53 acceptance rules.
- De facto coverage spans Phases 0–3 for the certified subset (secure ingestion,
  discovery, parser/IR, deterministic COBOL→Java, CALL/copybook, sequential files),
  with Phases 4–7 partial/modeled-only and Phases 8–12 partial or unverified.
- **Current focus:** Phase 1–3 capability-truth remediation (roadmap P0 backlog),
  which is the highest-priority confirmed-defect work. Reference:
  `docs/BACKLOG.md`.

### Completed this session
- Ran the Master-README-mandated independent audit (§76) and produced the central
  backlog (§77): `docs/BACKLOG.md` (BL-001 … BL-012). No-LLM gate (§79) checked —
  no model-provider integration found in executable code/config; only documentation
  references the prohibition.
- **BL-001 (P0) FIXED:** `engine/transformation/producers/internal_native.py` declared
  stale capability lists that contradicted the authoritative registry (`GO TO`
  supported; `COMPUTE`/`SUBTRACT`/`MULTIPLY`/`CALL`/`EVALUATE` unsupported). Both lists
  are now derived from `CONSTRUCT_REGISTRY` by level, so contradiction is impossible by
  construction; PARTIAL constructs are claimed by neither list.
- **Regression test added:** `tests/transformation/test_capability_registry_reconciliation.py`.
- **BL-006 FIXED:** created `docs/BACKLOG.md` (no central backlog existed).
- **BL-007 FIXED:** rewrote this stale checkpoint.
- **BL-011 PARTIALLY FIXED:** reconciliation test now covers the internal native
  producer (not yet all producers).
- **BL-002 (P0) FIXED:** COMP/COMP-3 USAGE is no longer silently ignored.
  `DataItem.usage` records the canonical token; the parser emits a non-blocking
  `PARTIAL_SUPPORT` diagnostic; registry keys `COMP`/`COMP-1`/`COMP-2`/`COMP-3`/
  `COMP-5` classify at PARTIAL; the analyzer walks `DataItem.usage` so
  `workload-comp`/`workload-comp3` are PARTIAL (never SUPPORTED); discovery filters
  `PARTIAL_SUPPORT` out of the loss channel so it never forces UNSUPPORTED.
  Mapper/runtime behavior unchanged.
- **BL-003 (P0) FIXED:** REDEFINES/OCCURS/88-level are no longer reported
  SUPPORTED.  Registry keys at UNKNOWN (fail-closed); the analyzer scans the
  DATA DIVISION explicitly (the procedure-restricted scan cannot see these);
  `workload-redefines`/`workload-occurs` now classify UNKNOWN and
  `workload-level88` stays non-SUPPORTED.  No mapper/runtime change.
- **BL-004 (P0) CLOSED BY DESIGN DECISION — no code change, premise corrected.**
  I first added `BY CONTENT`/`BY VALUE` registry keys at PARTIAL.  **CI rejected
  it**: runs #435/#436/#437/#438 failed on
  `test_by_value_and_by_content_are_never_claimed_supported`, a pre-existing
  negative contract that forbids these modes from ever being registry keys.  That
  is the repository's deliberate choice of the roadmap P0-4 option "keep
  blocked".  I reverted the keys and the analyzer classification, and instead
  documented the decision (registry comment, analyzer note, proof-matrix row
  "deliberately unclassified (blocked)").  No key ⇒ no consumer can read a
  support verdict out of these modes.  Mapper behavior was never changed.
  **Lesson recorded:** CI caught an over-claim that the local suite could not,
  because the guard lives in a Docker-gated integration test.
- **BL-005 (P0) FIXED, premise corrected:** the recorded symptom ("ROUNDED
  parsed but no mapping evidence") was **false**.  The flag already reaches Java
  as `RoundingMode.HALF_UP` (default stays `DOWN` truncation) and the pre-existing
  `test_decimal_arithmetic_semantics.py` already asserted it.  Only the registry
  key was missing: added at SUPPORTED, and the analyzer now reads the `rounded`
  IR flag so the verdict is backed by the parsed flag rather than a source match.
- **P0 capability backlog (BL-001…BL-005) is now closed.** BL-004 closed by an
  explicit, documented design decision (see above). No mapper/runtime behavior was
  changed in this whole sequence; every item was a capability/classification
  defect.
- **BL-008 FIXED (documentation contradiction):** `docs/SYSTEMAOPS_PRODUCT_STATUS.md`
  §18 claimed the integrated proof was "not yet wired into `api/service.py`". The
  code contradicts that: `api/service.py` builds it via `runtime_evidence_from_result`
  during validation and persists it as `run.modernization_report["integrated_proof"]`,
  `get_integrated_proof` serves it with a recompute fallback, and `api/app.py`
  exposes the route. The false claim was replaced with the real wiring and its
  concrete locations (Master README Section 78 — actual repository state wins).
- **BL-009 FIXED (stale baseline references):** ten live status documents
  (`README.md`, `docs/{PROJECT,CURRENT_DELIVERY,VERIFICATION,ARCHITECTURE,CONTRACT,
  SYSTEMAOPS_PRODUCT_STATUS,REMEDIATION_MATRIX,KNOWN_ISSUES}.md`,
  `docs/reports/CURRENT_PROJECT_STATE.md`) all pinned baseline `fedb7dd` and
  CI #417/#418. Each now carries a dated **Baseline note** marking those SHA/run IDs
  as a snapshot and pointing to `opencode.md` / `docs/BACKLOG.md` for the live
  pointer. Historical references were labelled, not rewritten. The universality
  roadmap was deliberately left alone: its `fedb7dd` references are historical audit
  narrative and rewriting them would destroy provenance.
- **BL-012 PARTIALLY FIXED:** added a dedicated `capability-truth` CI job that
  runs the capability gates (81 tests) with **only pytest installed** — no
  `requirements.lock`. A producer/registry contradiction now fails in ~1 minute
  instead of after the full COBOL/Java Docker image build, and the
  dependency-free install proves the registry/analyzer/producer surface has no
  hidden third-party coupling. Coverage thresholds and mutation testing are
  deliberately left open (no evidence-based target yet).
- **BL-011 FIXED:** the reconciliation guard now covers **both** producers under
  `engine/transformation/producers/`.  Deterministic-lane producers must agree
  with the registry in both directions; every producer must declare a non-empty
  capability surface, never claim a construct both ways, and only use registry
  keys or declared structural vocabulary.  Every registry key must also resolve
  to a verdict automatically, so the BL-002…BL-005 keys could not have been
  added without the producer noticing.  The opensource4j adapter's inline
  capability tuples were hoisted to module scope so its claims are inspectable
  without running the external compiler.  Scope decision: the external lane
  (requires `libcobj.jar`) legitimately claims `GO TO`/`SORT`; its divergence
  from the deterministic registry is now **pinned by an explicit test** instead
  of being forced to match, which would have falsified its real behaviour.

### Files changed this session
- `engine/transformation/producers/internal_native.py` (capability lists now
  registry-derived).
- `engine/transformation/ir.py` (`DataItem.usage`).
- `engine/transformation/semantic_capability.py` (COMP/REDEFINES/OCCURS/88-LEVEL/
  ROUNDED registry keys, `canonical_usage`, `USAGE_TO_CONSTRUCT`, source patterns,
  documented BL-004 keyless decision).
- `engine/transformation/cobol_parser.py` (USAGE extraction + PARTIAL_SUPPORT).
- `engine/modernization/capability_analyzer.py` (usage walk, data-division scan,
  ROUNDED IR-flag read, documented BL-004 decision).
- `engine/transformation/application_discovery.py` (loss-channel filter).
- `.github/workflows/ci.yml` (new dependency-free `capability-truth` job).
- `tests/transformation/test_capability_registry_reconciliation.py` (new; 11 tests).
- `tests/transformation/test_usage_capability.py` (new; 22 tests).
- `tests/transformation/test_structural_capability.py` (new; 9 tests).
- `tests/transformation/test_rounded_capability.py` (new; 7 tests).
- `tests/transformation/test_producer_capability_consistency.py` (new; 16 tests).
- `engine/transformation/producers/opensource4j.py` (declared tuples hoisted).
- `README.md` + 9 status docs (dated Baseline note; BL-009).
- `docs/SYSTEMAOPS_PRODUCT_STATUS.md` (integrated-proof claim corrected; BL-008).
- `docs/BACKLOG.md` (new; BL-002…BL-005, BL-008, BL-009, BL-011 fixed,
  BL-012 partially fixed).
- `docs/SEMANTIC_PROOF_MATRIX.md` (COMP-family + REDEFINES/OCCURS/88-level +
  ROUNDED rows; BY VALUE/BY CONTENT documented as deliberately unclassified).
- `opencode.md` (rewritten live checkpoint; now intended to be tracked).

### Tests run this session
- Focused: `pytest -q tests/transformation/test_capability_registry_reconciliation.py
  tests/transformation/test_producer_contract.py` → **29 passed** (2026-10-10).
- BL-002: `pytest -q tests/transformation/test_usage_capability.py` → **22 passed**.
- BL-003: `pytest -q tests/transformation/test_structural_capability.py` → **9 passed**;
  `workload-redefines`/`workload-occurs` → UNKNOWN.
- BL-004: reverted after CI failure (see above); the previously failing contract
  test now passes: `pytest -q tests/integration/test_phase_d_negative_integration.py`
  → **26 passed**.
- BL-005: `pytest -q tests/transformation/test_rounded_capability.py` → **7 passed**.
- BL-011: `pytest -q tests/transformation/test_producer_capability_consistency.py
  tests/transformation/test_capability_registry_reconciliation.py
  tests/transformation/test_producer_contract.py tests/execution/test_sandbox_paths.py`
  → **67 passed**.
- Regression: `pytest -q tests/transformation tests/adversarial
  tests/test_silent_loss_registry.py tests/test_copybook_m7.py
  tests/test_db2_fixture.py tests/test_universal_modernization.py tests/execution`
  → **2004 passed, 11 skipped, 22 failed**; all 22 failures are environment-only
  `FileNotFoundError` from a missing `javac` (no JDK on this host), not regressions.
- **Authoritative result is CI, not this host.** Push CI #447 / PR CI #448 on
  `842bfce`: every job SUCCESS (ingestion, frontend, backend COBOL/Java Docker,
  capability truth gate) — the Docker-gated backend job ran the full suite with
  GnuCOBOL + JDK available and passed. Local `javac`/Docker gaps are superseded
  by that evidence.
- Full local non-Docker regression (final, on `1371485`): `pytest -q tests`
  (RUN_DOCKER_TESTS unset) → **3091 passed, 12 skipped, 26 failed**. All 26 are
  the environment-only `FileNotFoundError` cases from the missing JDK/Docker on
  this host (`javac`/`java` in `subprocess.run`, and the Docker Java path) —
  confirmed by inspecting the failure text, not just the count. The BL-004
  contract test that previously failed here is now green.

### Push / CI status (2026-10-10)
- The earlier push blocker is **resolved**: Git Credential Manager has stored
  credentials, so `git push` now succeeds non-interactively.
- `f069498` ("fix(capability): derive internal producer constructs from
  authoritative registry (P0-1)") pushed to `codex/universal-core`:
  `81e7955..f069498`. CI for `f069498`: Push CI #429 SUCCESS, PR CI #430
  SUCCESS, Supply chain #11/#12 SUCCESS.
- `dfcc725` ("fix(capability): record USAGE on DataItem and classify
  COMP/COMP-3 as PARTIAL (P0-2)") pushed: `f069498..dfcc725`. CI for
  `dfcc725`: Push CI #431 SUCCESS, PR CI #432 SUCCESS, Supply chain #13/#14
  SUCCESS.
- `490eb5a` ("fix(capability): classify REDEFINES/OCCURS/88-level as UNKNOWN
  (P0-3)") pushed: `dfcc725..490eb5a`. CI for `490eb5a`: Push CI #433
  SUCCESS, PR CI #434 SUCCESS, Supply chain #15/#16 SUCCESS.
- `92cd314`, `a63e359`, `09375b2`, `f7c2e10` — pushed; CI runs #435–#442. The
  **Backend and COBOL/Java Docker tests** job FAILED on #435–#438 and #441/#442
  with `test_by_value_and_by_content_are_never_claimed_supported`. Root cause: the
  BL-004 registry keys violated a pre-existing negative contract (see above).
  Ingestion and frontend jobs were green throughout.
- `24540f6` ("fix(capability): revert BY CONTENT/BY VALUE registry keys; honour
  negative contract (BL-004)") pushed: `f7c2e10..24540f6`. Supply chain #25/#26
  SUCCESS; Push CI #443 and PR CI #444 in progress at time of writing. This is
  the first run of the full P0 sequence against the corrected baseline.

### CI failure analysis (2026-10-10) — reusable finding
- **Symptom:** "Backend and COBOL/Java Docker tests" failed on 4 consecutive runs
  while every other job (ingestion, frontend, supply chain) stayed green.
- **Root cause:** a single assertion —
  `tests/integration/test_phase_d_negative_integration.py::
  TestUnsupportedParameterContract::test_by_value_and_by_content_are_never_claimed_supported`.
  It asserts no registry key contains "BY VALUE"/"BY CONTENT", i.e. the repo had
  deliberately chosen the roadmap P0-4 option "keep blocked". My BL-004 change
  added exactly those keys.
- **Why the local suite missed it:** the guard lives in an integration test
  inside the Docker-gated job; my local run also never exercises that file's full
  context. **Local green is not sufficient for capability claims** — the Docker
  job is the authority for this class of defect.
- **Correction applied:** reverted the keys and the analyzer classification,
  documented the decision in registry/analyzer/matrix, deleted the test that
  encoded the wrong expectation.
- **Method note (reusable):** CI job logs are admin-only via the API, but the run's
  uploaded `backend-oracle-results` artifact contains `backend-tests.log` with the
  exact failing assertion; fetching that artifact with the stored GCM credential
  is the fastest path to root cause.

### Blockers
- Environment blocker (BL-010): Docker-dependent and Java/Node validation cannot run
  locally. Not to be worked around by changing virtualization/Docker security.
- Local full-suite runs are slow on this host; full Docker oracle/candidate/E2E proof
  is delegated to Linux CI.

### Known limitations / non-claims (unchanged, must be preserved)
- Subset-certified, NOT universal COBOL / z/OS / JCL / DB2 / CICS equivalence.
- GnuCOBOL oracle ≠ proof of complete z/OS behavioral equivalence.
- COMP/COMP-3 storage encoding, REDEFINES/OCCURS/88-level mapping, BY CONTENT/BY VALUE
  runtime, and ROUNDED consumption remain unproven (BL-002…BL-005).
- Production gaps: durable queue/resume, retention/TTL, audit logging, TLS/egress at
  boundary, multi-node coordination (SQLite single-node).

### Architectural / open-source decisions
- No architecture change this session. The canonical pipeline is preserved.
- Fix follows the Master README rule "registry is the single source of capability
  truth" and the roadmap instruction "registry should win".
- No open-source component added or replaced.

### Fresh E2E status
- Not run locally (Docker blocked). Last recorded fresh/E2E evidence is historical
  (PHASE7D report + CI run #427 backend/oracle job). No new fresh E2E claimed.

### Do-not-redo list
- Do not re-implement the parser/IR/mapper/generator/evidence/verdict architecture.
- Do not re-do PHASE5–7D work absent a detected regression.
- Do not retry Docker-in-Docker or alter WSL2/cgroup/Docker security settings.
- Do not weaken/skip tests to obtain green.

- `ee6fc92` ("docs(checkpoint): record CI failure analysis and reusable method
  note") pushed: `24540f6..ee6fc92`. CI #445/#446 SUCCESS.
- `842bfce` ("ci: add dependency-free capability-truth gate job (BL-012)")
  pushed: `ee6fc92..842bfce`. **ALL JOBS GREEN**: Push CI #447 and PR CI #448
  SUCCESS, with every job passing —
  `Phase 1 ingestion diagnostics`, `Frontend tests, TypeScript, and production
  build`, `Backend and COBOL/Java Docker tests`, and the new
  **`Capability truth gate`**. Supply chain #29/#30 SUCCESS. This is the first
  fully green run of the complete P0 sequence and confirms the BL-004 revert
  restored the Docker-gated suite.
- `ca38321` ("docs(checkpoint): record fully green CI on 842bfce and P0 closure")
  pushed: `842bfce..ca38321`. Supply chain #31/#32 SUCCESS; Push CI #449 and
  PR CI #450 SUCCESS.
- `1371485` ("docs(checkpoint): record CI green on ca38321") pushed:
  `ca38321..1371485`. Supply chain #33/#34 SUCCESS; the new `Capability truth
  gate`, ingestion and frontend jobs all SUCCESS on both Push CI #451 and
  PR CI #452, with only the long-running backend Docker job still in progress at
  time of writing.

### Historical next-action note (superseded)
1. The old instruction to commit the checkpoint and verify only `842bfce` is obsolete; follow the Phase 0 closure block at the top of this file.
2. The P0 backlog is closed and fully verified in CI. Next candidates, in
   roadmap §13 order and lowest-risk first: **P1-1 INITIALIZE (bounded)**,
   P1-2 INSPECT (TALLYING subset), P1-3 SEARCH (linear only). Before each, grep
   for an existing negative contract — BL-004 proved some capability claims are
   deliberately blocked, and over-claiming is the exact failure mode to avoid.
3. Docker-dependent and Java/Node validation remain delegated to Linux CI (BL-010).
4. Keep `docs/BACKLOG.md` and this checkpoint current at each checkpoint.

---

## Historical: initial setup session (2026-10-10, before this audit)

> Retained as history. Superseded by the session above; many statements here are no
> longer current (e.g., Python is now installed and used).

### Repository state at that time
- Remote: https://github.com/Shankar373/Cobol-Java-Transformation.git
- Branch: codex/universal-core
- HEAD: 7ae5873 "docs: add master implementation README"
- Working tree: clean (no uncommitted changes; tmp/ contains historical artifacts)
- opencode.md: created 2026-10-10

### Environment (at that time)
- OS: Windows 11 Home 64-bit (Build 26200)
- Git: 2.55.0.windows.5 (C:\Program Files\Git\bin\git.exe)
- Docker CLI: not found (checked after install)
- WSL: wsl.exe present, but wsl --status gave a registration error initially
- Node.js/npm: not found
- Python: Windows Apps python alias detected; real Python reported not installed
- Java (JAVA_HOME/java): not found
- Maven: not found
- Hyper-V/Virtualization: CPU virtualization firmware enabled False; HypervisorPresent True

### Key docs confirmed present
- MASTER_IMPLEMENTATION_README.md, README.md, requirements.txt, requirements.lock,
  .github/workflows/ci.yml, Dockerfile.gnucobol/.maven-offline/.production,
  docker-compose.production.yml, scripts/deploy/*.sh,
  engine/candidate/docker_spring_boot_adapter.py, scripts/record_docker_image_provenance.py

### Setup plan (at that time)
1. Inspect repo state — done. 2. Install prerequisites — pending.
3. Clone/fetch safely — done. 4. Configure Docker images — pending.
5. Install deps and verify — pending. 6. Report status — pending.
