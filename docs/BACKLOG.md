# SystemaOps Defect and Gap Backlog

**Status:** live backlog (authoritative per Master README Section 77).
**Audit date:** 2026-10-10
**Audited repository:** `Shankar373/Cobol-Java-Transformation`
**Audited branch:** `codex/universal-core`
**Audited HEAD:** `81e795584e42437e4194bcb317ca20594c621adc` ("docs: strengthen master implementation audit and backlog contract")
**CI for audited HEAD:** Push CI #427 SUCCESS, PR CI #428 SUCCESS, Supply chain #9/#10 SUCCESS.

Authority hierarchy (Master README Section 78):
`MASTER_IMPLEMENTATION_README.md` > `opencode.md` > registries/contracts > current
verification/status reports > historical reports.

Priority guidance (Master README Section 77): P0 = incorrect business semantics,
false VERIFIED/certification, trust-boundary bypass, critical security exposure, or
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
- **Status:** OPEN
- **Observed behavior:** Fixtures `workload-redefines`, `workload-occurs`,
  `workload-level88` parse, but no mapping-output or runtime evidence was found and
  the registry has no keys for `REDEFINES`, `OCCURS`, or 88-level conditions.
- **Expected behavior:** Master README Sections 19/60; roadmap P0-3. A construct that
  parses but is unproven must not be presented as supported.
- **Affected files:** `engine/transformation/semantic_capability.py`,
  `engine/transformation/cobol_to_java_mapping.py`,
  `docs/SEMANTIC_PROOF_MATRIX.md`.
- **Source:** roadmap §10 / §12 P0-3.
- **Impact:** Parsed-but-unproven constructs invite false confidence.
- **Remediation (proposed):** Add registry keys at UNKNOWN/UNSUPPORTED until proven;
  verify overlay/table/condition lowering or scope it; add positive runtime proof plus
  negative tests (e.g., OCCURS DEPENDING ON blocked).
- **Verification level:** STATIC only.

### BL-004 — BY CONTENT / BY VALUE capability hole
- **Type:** defect (capability truth)
- **Status:** OPEN
- **Observed behavior:** Mapper implements sync-in/no-sync-out for BY CONTENT/BY VALUE;
  fixtures exist; no registry key means capability UNKNOWN, and no dedicated runtime
  comparison was found.
- **Expected behavior:** roadmap P0-4; honest classification of parameter modes.
- **Affected files:** `engine/transformation/semantic_capability.py`, mapper.
- **Impact:** Parameter-mode divergence is a classic silent-divergence source.
- **Remediation (proposed):** Add keys (PARTIAL with lost-write note) or keep blocked;
  add mode-specific runtime comparisons + arity/literal-by-reference negatives.
- **Verification level:** STATIC only.

### BL-005 — ROUNDED flag consumption unverified
- **Type:** defect (capability truth)
- **Status:** OPEN
- **Observed behavior:** `ROUNDED` is parsed into IR on arithmetic statements but no
  mapping evidence found; no registry key.
- **Expected behavior:** roadmap P0-5 — prove the flag reaches Java or mark mapping
  UNKNOWN with a negative test.
- **Affected files:** parser IR flags + `engine/transformation/cobol_to_java_mapping.py`,
  `engine/transformation/semantic_capability.py`.
- **Impact:** Rounding is a numeric-semantics risk area (Master README Section 18).
- **Verification level:** STATIC only.

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
- **Status:** OPEN
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
- **Remediation (proposed):** Update the status doc to reflect the wired proof path,
  citing the API route and tests.
- **Verification level:** VERIFIED by static read of `api/service.py` lines 164, 230,
  986–1016, 1142–1160 and `api/app.py` line 615.

### BL-009 — Live status documents cite a stale baseline commit / CI run
- **Type:** documentation contradiction
- **Status:** OPEN
- **Observed behavior:** `README.md`, `docs/PROJECT_STATUS.md`,
  `docs/SYSTEMAOPS_PRODUCT_STATUS.md`, `docs/CURRENT_DELIVERY_STATUS.md`,
  `docs/VERIFICATION_STATUS.md`, `docs/ARCHITECTURE.md`, `docs/CONTRACT_STATUS.md`,
  `docs/KNOWN_ISSUES.md`, `docs/COBOL_UNIVERSALITY_ROADMAP.md` all cite baseline
  `fedb7dd` / Push CI #417 / PR CI #418, while the current HEAD is `81e7955` with
  Push CI #427 / PR CI #428 green.
- **Expected behavior:** Master README Section 78 — every live status report must
  identify its verified commit and audit date.
- **Impact:** Readers cannot tell which commit the status describes; drift risk.
- **Remediation (proposed):** Bump live status docs' recorded baseline/CI to the
  audited commit, or explicitly label the older references as of their date. Do not
  rewrite historical reports.
- **Verification level:** VERIFIED by static read; CI status VERIFIED via GitHub API.

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
- **Status:** PARTIALLY FIXED — 2026-10-10
- **Observed behavior:** roadmap §16 recommends a reconciliation test; BL-001 now adds
  one for the internal native producer. A generic guard that every producer's declared
  lists agree with the registry is still not present.
- **Remediation (proposed):** Extend the reconciliation test across all
  `TransformationProducer` implementations under `engine/transformation/producers/`.
- **Verification level:** VERIFIED for the internal native producer.

### BL-012 — CI depth below roadmap target
- **Type:** test/quality
- **Status:** OPEN
- **Observed behavior:** CI runs ingestion, backend/oracle/Docker, frontend tests/build.
  No coverage thresholds, mutation testing, or capability-reconciliation gate.
- **Source:** Master README Sections 51/54 (P2), `docs/KNOWN_ISSUES.md` P2.
- **Remediation (proposed):** Add reconciliation gate (BL-011) and targeted coverage
  thresholds after P0 items.
- **Verification level:** STATIC only.

---

## Backlog change log

- 2026-10-10 — Initial backlog created from the Master-README-mandated audit
  (Sections 76–77). BL-001 fixed; BL-006/BL-007 fixed; BL-011 partially fixed.
- 2026-10-10 — BL-002 fixed: USAGE clause now recorded on `DataItem.usage`,
  PARTIAL_SUPPORT diagnostic emitted, registry keys `COMP`/`COMP-1`/`COMP-2`/
  `COMP-3`/`COMP-5` at PARTIAL, analyzer classifies `workload-comp`/
  `workload-comp3` PARTIAL (22 new tests).
