# Known Issues

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

Known-issues baseline (dated snapshot of 2026-10-10; corrected 2026-10-16, Phase 12 F-02): fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4 (Phase A), Push CI #417 / PR CI #418 GREEN — live baseline/CI: `opencode.md`.
Lifecycle/persistence/API security hardening has since been applied on top of this baseline.

## Open material issues

> **Reconciliation note (BL-120, 2026-10-21 universal requirements audit):** the two
> `P0` headings below are Master README §54 **high-risk areas**, not filed P0 defects.
> Under the §77 priority contract a P0 is an *item* with incorrect business semantics,
> a false VERIFIED/certification, a trust-boundary bypass, critical security exposure
> or data-loss risk. As of `a6f4dad` the register (`docs/BACKLOG.md`) contains **no open
> P0 row**: the verdict path is fail-closed (single `VERIFIED` site
> `engine/verdict/derivation.py:265`, integrity clamp `engine/pipeline.py:653-657`),
> so capability drift cannot reach a false VERIFIED today. The concrete drift found by
> the 2026-10-21 audit is filed as **BL-108** (registry rows contradicting shipped code,
> FIXED) and **BL-109** (three-way indexed/relative contradiction, FIXED) at P2 with
> the §54 risk rationale recorded; numeric risk stays covered by **BL-002/BL-003** plus
> carried decision **D-6** (COMP/COMP-3 certification). This section and `opencode.md` must
> quote the same set — the register is the priority authority.

### P0 area — Capability truth can drift
Capability classifications are manually maintained and can become inconsistent with parser,
IR, mapper, generator and runtime evidence. Contradictory classifications must be eliminated.
*Live instances as of 2026-10-21: BL-108, BL-109 (both FIXED 2026-10-21 — no false VERIFIED
was produced because planning fails closed). See the reconciliation note above.*

### P0 area — Numeric semantic risk
PIC/sign/V, COMP/COMP-3, precision/scale, truncation, rounding, overflow and formatting
remain high-risk areas requiring broader differential proof.
*Tracked as BL-002/BL-003 + carried decision D-6 (COMP/COMP-3 certification approach);
DISPLAY arithmetic is oracle-proven for the documented subset, COMP/COMP-3 byte encoding
is explicitly PARTIAL and never claimed as certified.*

### P1 — Planning semantics
Copybook planning and entrypoint selection require continued review so plans cannot include
non-transformable units or select an entrypoint that cannot execute.

### P1 — CALL and lifecycle proof
CALL chains, multi-program behavior and lifecycle transitions need broader end-to-end testing.

### P1 — Evidence/verdict hardening
The evidence validator and verdict engine exist, but production-path coverage, tamper/replay
testing and mutation proof should be expanded.

### P1 — Persistence/security
Control-plane persistence now uses versioned JSON payloads (no pickle) with seal checks,
a fail-closed lifecycle state machine with single-flight revalidation, bounded and
optionally token-authenticated API endpoints, and startup reconciliation of interrupted
runs. Still open for production: a durable job queue with resume across restarts,
per-client rate limiting, retention/TTL, audit logging, external secret management for
`CONTROL_PLANE_API_TOKEN` (the token is an env-var deployment control, not a user/role
model), TLS and egress policy at the deployment boundary, and multi-node coordination
(SQLite is single-node).

### P1 — Deferred production gaps (owner-approved 2026-10-21)
The following production requirements are **explicitly deferred** by owner decision;
they are not claimed to exist and no document may claim them before enforcement:

- **Time-based evidence staleness (BL-113, D-7 approved):** evidence timestamps are
  recorded but no wall-clock TTL is enforced. Staleness is enforced generation-wise
  only. A TTL policy interacts with clock skew and re-validation flows; the value is
  a policy decision deferred.
- **Rate limiting (BL-114, D-7 approved):** no request rate limiting exists. The only
  429 is the concurrency-slot limit. Adding throttling can break legitimate
  batch/polling clients (the SPA polls every 1.5-2 s); the policy is deferred.
- **Cancellation/retry/deadline (BL-115, D-8 approved):** runs execute in daemon
  threads with no cancellation, retry, or whole-run deadline; only per-step Docker
  timeouts exist. Cancellation interacts with evidence integrity (a half-finished
  run must not produce a verdict); the design is deferred.
- **JCL/CICS/DB2 artifact materialization (BL-116):** transform results for these
  lanes are computed in memory but never written to `java_candidate_path`, so no
  artifact from those lanes is ever built or compared. Fail-closed today (plan
  SKIP → FAILED); it is a missing deliverable, not a trust breach. The decision
  to materialize or document as analysis-only is deferred.
- **Enterprise security scope (BL-122, D-9 approved):** RBAC, tenant isolation,
  tamper-evident audit logging, external secret management, TLS/egress control,
  multi-node coordination, SBOM and vulnerability scanning are documented as
  future requirements but have no enforcement. The single shared token grants
  global read/write. Scope is deferred; no document may claim these controls
  exist before enforcement.

### P1 — Enterprise runtime boundaries
JCL, CICS, DB2 and indexed/relative file semantics remain outside broad behavioral certification
until their runtime semantics are proven.

### P2 — CI depth
CI is green but can be strengthened with coverage thresholds, lint/type checks, security and
dependency scanning, contract/schema checks and mutation testing.

## Resolved / historical

### TypeScript JSX build blocker — RESOLVED
The old TypeScript JSX fragment/build issue is no longer an active CI blocker. Push CI #417 / PR CI #418 (2026-10-10 snapshot) passed
the frontend production build; current CI runs are tracked in `opencode.md`.

### Docker-unavailable local verification — HISTORICAL
Earlier reports described Docker as unavailable locally. Current CI successfully exercises the
Docker backend/oracle path, so those reports are not current project state.

### Universal-runtime-proof audit fixes — RESOLVED locally 2026-10-19 (pending CI via R-1)
The 2026-10-19 audit found and fixed red-first: frontend Authorization integration (BL-094),
`docker_available=True` hardcode in `api/service.py` (BL-095), dashboard "Verified" overclaim
(BL-096), and platform-canonical ZIP ingestion + source-tree hashing (BL-097). Red-first
evidence and regression results: `docs/BACKLOG.md` change-log (bd)/(be). Not yet
CI-validated (no push authorization); roadmap R-1 in
`UNIVERSAL_RUNTIME_PROOF_AUDIT_AND_IMPLEMENTATION_PLAN.md` covers commit + exact-SHA CI.

Historical forensic reports remain evidence of what was true at their recorded time.
