# Documentation & Product Readiness Audit

Date: 2026-10-07. Auditor: repository inspection at HEAD `90efdca` on `codex/universal-core`.
In-progress parallel work (cobol_parser/cobol_to_java_mapping/java_generator/java_ir/numeric_semantics/spring_boot_generator plus numeric tests) is UNCOMMITTED working-tree change and was not relied upon.

## Executive Summary

The core safety posture of the documentation is honest: the README and status docs
already refuse to claim universal COBOL modernization, z/OS equivalence, DB2/VSAM/JCL/CICS
runtime equivalence, or "LLM-based reasoning" as a goal. However, the top-level baseline
identity in every user-facing doc is STALE (all pin `4513881bc…` / CI Run #306, while HEAD is
`90efdca` and CALL/copybook/linkage runtime proof now exists). Capability labels for CALL and
COPYBOOK remain at "Partial" even though Phase-D Task 2 added an A→B→C Spring-Boot runtime
proof (6b5a866) and linkage-arity hardening (90efdca). Runtime-success-vs-VERIFIED boundary
and verdict-model descriptions are accurate. LLM-free claims match the implementation.

## Current Proven Capabilities

PROVEN (executable evidence + runtime proof):
- Secure ZIP ingestion, traversal/extraction limits (Phase A/B hardening, commits 1aeb73d, 507230e).
- Application discovery, CALL/COPY/FILE dependency edges, deterministic verdict states.
- CALL A→B→C static chain: discovery edges → capability → plan → Java bean DI → Docker Maven compile → JAR run → GnuCOBOL 3-module oracle → behavioral equivalence → VERIFIED (`tests/integration/test_call_chain_runtime.py`, 6b5a866).
- CALL failure modes: unresolved→PARTIAL, dynamic→UNSUPPORTED, cyclic→blocked, linkage arity mismatch→UNSUPPORTED (`tests/test_call_linkage_mismatch.py`, 90efdca).
- COPYBOOK: deterministic `.cpy/.cbl/.cob` resolution, case-insensitive stem, ambiguity/missing fail-closed, shared Java model class, Spring Service field materialization, runtime equivalence proof (`tests/integration/test_copybook_runtime.py` re-run today: VERIFIED).
- Numeric semantics contract per `numeric_semantics.py` (tails still being hardened by a parallel task; do not over-claim).

## Partial / Limited Capabilities

PARTIALLY PROVEN:
- CALL/COPYBOOK: proven for the static, single-threaded, literal-target subset only; GOBACK/EXIT PROGRAM edge paths partial.
- Byjes: BY REFERENCE/BY CONTENT/BY VALUE supported where tests exist; mode-compat determinism is UNKNOWN (not a runtime-ABI claim).
- Indexed/relative files: parser+mapping subset only; no certified runtime equivalence.
- DIVIDE/COMPUTE precision edges are residual.
- Evidence/verdict integrity: implemented and tested at the engine level; production-path tamper/replay coverage still incomplete.

## Unsupported Capabilities

UNSUPPORTED (documented and enforced fail-closed):
- Dynamic CALL as a silent success (classified UNSUPPORTED).
- Recursive/self CALL reproduction (out of scope).
- GO TO Java mapping, CALL-target GOBACK/EXIT PROGRAM source-only markers, INVALID KEY / START / REWRITE / DELETE parser-level source-level UNSUPPORTED in the deterministic mapper.
- z/OS, DB2, VSAM, JCL, CICS runtime equivalence — modeled only.

## Unavailable Capabilities

UNAVAILABLE (infrastructure-dependent, downgraded in capability report):
- Docker/oracle availability → UNAVAILABLE rather than silent PASS. Host-only fallbacks never upgrade a verdict.
- Production hardening (TLS, multi-node, durable queue): not available.

## Claims That Must Not Be Made

- Universal COBOL modernization or z/OS equivalence.
- DB2 runtime equivalence from SQLite seams.
- VSAM equivalence from Java Map fallbacks.
- JCL/JES equivalence without runtime evidence.
- CICS TS equivalence from a seam/profile.
- Unsupported constructs are equivalent.
- Runtime success alone proves VERIFIED (verdict derives from validated evidence).
- LLM-based reasoning anywhere in transformation.

## Stale Documentation

- README.md, PROJECT_STATUS.md, CURRENT_DELIVERY_STATUS.md, ARCHITECTURE.md, VERIFICATION_STATUS.md, KNOWN_ISSUES.md, CONTRACT_STATUS.md, REMEDIATION_MATRIX.md: baseline SHA `4513881bc…` and CI Run #306 are stale; must reference HEAD `90efdca` lineage and the Phase-D milestones.
- CAPABILITY_MATRIX.md rows: CALL and Copybooks still say "Partial", should cite the Phase-D runtime proofs and arity hardening for the static subset.
- PROJECT_STATUS.md "CALL and lifecycle proof" P1 and "Copybooks YELLOW" remain defensible only for the broader (non-static-subset) boundary.
- SEMANTIC_PROOF_MATRIX.md is current as of today (08:44) but needs a CALL/linkage arity row referencing 90efdca.

## Security Documentation Gaps

- `CONTROL_PLANE_API_TOKEN` documented only as env-var deployment control; no TLS, rate-limit, retention/TTL, audit-log, secret-rotation, or multi-node guidance at the deployment boundary (KNOWN_ISSUES P1 partially covers this).
- No dependency-vulnerability scanning / SBOM policy documented.
- No STIG/compliance mapping for container images (digest pinning is provenance-tested but not certified).

## Demo Documentation Gaps

- No single canonical demo script path documented for the current baseline; `demo_workflow.py`, `demo_continue.py`, `run_final_demo_check.py`, `verify_demo.py` exist at repo root but are not indexed in README.
- Frontend/results artifacts (`frontend/results.txt`) not described as evidence sources.

## API / Frontend Documentation Gaps

- API endpoints documented only through README pipeline sentence + contracts; no OpenAPI/endpoint catalog.
- Frontend control-plane pages/workflows not documented; no component contract documentation.
- No documented error-model (fail-closed 500 semantics) for API consumers.

## Installation / Deployment Gaps

- README lacks a reproducible install steps section (Docker images, env vars, Maven/Node requirements, CI-only Docker assumption).
- Deployment guide for SQLite production placement, backups, schema-version upgrade, and token rotation missing.

## CI / Release Documentation Gaps

- README/STATUS pin CI Run #306; current run artifacts (`test-artifacts/backend-junit.xml`, `baseline-junit.xml`) are not wired into docs.
- No release-tag policy, SemVer stance, or artifact publishing process documented.
- No branch-protection/required-checks documentation.

## Recommended Corrections

1. Update every doc's baseline/CI identity to HEAD `90efdca` and describe Phase-D status separately.
2. CAPABILITY_MATRIX.md: CALL and Copybooks rows → "Supported subset (static CALL chain + copybook model), with Phase-D runtime proof"; add a row note for linkage-arity diagnostics.
3. SEMANTIC_PROOF_MATRIX.md: add CALL linkage-arity row (90efdca) and the four classified CALL failure modes.
4. Add docs/ audits entry for Phase-D D2 and a forward pointer to Phase-E.
5. Add install/deployment/release sections to README (see gaps above).
6. Add security deployment-boundary section (TLS, rate limiting, retention, audit, secret management).

## Phase-D Documentation Readiness

Documentation is NOT Phase-D-ready: it does not yet reflect 6b5a866 (CALL A→B→C proof) or
90efdca (linkage arity hardening), and top-level baseline/CI references are stale. No claim
currently overstates capability; the risk is under-statement and stale provenance, not
false advertising.

## Final Verdict

Documentation policy (deterministic, fail-closed, subset-certified, no-LLM) is accurate.
Identity/freshness of provenance is stale. Root-line docs must be refreshed before a Phase-D
release tag; no code or architecture changes are required.
