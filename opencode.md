# opencode.md — SystemaOps Live Implementation Checkpoint

Checkpoint authority (Master README §64): `MASTER_IMPLEMENTATION_README.md`
defines what must be built; this file records **where implementation currently is**.
It must never contradict repository reality (§68) and must never be left misleading.

---

## Session 2026-10-10 (current)

### Baseline (verified this session)
- Repository: `https://github.com/Shankar373/Cobol-Java-Transformation.git`
- Branch: `codex/universal-core`
- HEAD: `81e795584e42437e4194bcb317ca20594c621adc`
  ("docs: strengthen master implementation audit and backlog contract")
- Base branch: `main` (`a923c65`)
- Working tree: dirty by design — untracked `opencode.md`, `test-artifacts/*`
  evidence, and a modified `test-artifacts/docker-image-provenance.json`
  (pre-existing, preserved). No tracked source files were modified before this session.
- Local branch was one commit behind `origin` at session start; fast-forwarded
  `7ae5873 → 81e7955` (docs-only). No reset, no force-push, no user files discarded.

### CI status for the exact audited HEAD `81e7955` (verified via GitHub API)
- Push CI #427 — SUCCESS
- PR CI #428 — SUCCESS
- Supply chain #9 (push) / #10 (PR) — SUCCESS
- Last known green commit: `81e7955`.

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

### Files changed this session
- `engine/transformation/producers/internal_native.py` (capability lists now
  registry-derived).
- `engine/transformation/ir.py` (`DataItem.usage`).
- `engine/transformation/semantic_capability.py` (COMP registry keys,
  `canonical_usage`, `USAGE_TO_CONSTRUCT`, source patterns).
- `engine/transformation/cobol_parser.py` (USAGE extraction + PARTIAL_SUPPORT).
- `engine/modernization/capability_analyzer.py` (usage walk).
- `engine/transformation/application_discovery.py` (loss-channel filter).
- `tests/transformation/test_capability_registry_reconciliation.py` (new; 11 tests).
- `tests/transformation/test_usage_capability.py` (new; 22 tests).
- `tests/transformation/test_structural_capability.py` (new; 9 tests).
- `docs/BACKLOG.md` (new; BL-002/BL-003 now FIXED).
- `docs/SEMANTIC_PROOF_MATRIX.md` (COMP-family + REDEFINES/OCCURS/88-level rows).
- `opencode.md` (rewritten live checkpoint; now intended to be tracked).

### Tests run this session
- Focused: `pytest -q tests/transformation/test_capability_registry_reconciliation.py
  tests/transformation/test_producer_contract.py` → **29 passed** (2026-10-10).
- BL-002: `pytest -q tests/transformation/test_usage_capability.py` → **22 passed**.
- BL-003: `pytest -q tests/transformation/test_structural_capability.py` → **9 passed**;
  `workload-redefines`/`workload-occurs` → UNKNOWN.
- Regression: `pytest -q tests/transformation tests/adversarial
  tests/test_silent_loss_registry.py tests/test_copybook_m7.py
  tests/test_db2_fixture.py tests/test_universal_modernization.py` → **1897 passed,
  11 skipped, 22 failed**; all 22 failures are environment-only `FileNotFoundError`
  from a missing `javac` (no JDK on this host), not regressions.
- Full local non-Docker backend regression: `pytest -q tests` (RUN_DOCKER_TESTS
  unset) → result appended below when complete. Docker tests are skipped/blocked
  locally (see environment blocker).

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

### Next exact OpenCode action
1. Commit BL-003 + tests + docs + checkpoint and push to `codex/universal-core`;
   then verify GitHub Actions for the pushed commit.
2. Continue the P0 backlog: implement BL-004 (BY CONTENT/BY VALUE) and BL-005
   (ROUNDED) as scoped.
3. Keep `docs/BACKLOG.md` and this checkpoint current at each checkpoint.

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
