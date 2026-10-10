# Known Issues

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

Known-issues baseline: fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4 (Phase A), Push CI #417 / PR CI #418 GREEN.
Lifecycle/persistence/API security hardening has since been applied on top of this baseline.

## Open material issues

### P0 — Capability truth can drift
Capability classifications are manually maintained and can become inconsistent with parser,
IR, mapper, generator and runtime evidence. Contradictory classifications must be eliminated.

### P0 — Numeric semantic risk
PIC/sign/V, COMP/COMP-3, precision/scale, truncation, rounding, overflow and formatting
remain high-risk areas requiring broader differential proof.

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

### P1 — Enterprise runtime boundaries
JCL, CICS, DB2 and indexed/relative file semantics remain outside broad behavioral certification
until their runtime semantics are proven.

### P2 — CI depth
CI is green but can be strengthened with coverage thresholds, lint/type checks, security and
dependency scanning, contract/schema checks and mutation testing.

## Resolved / historical

### TypeScript JSX build blocker — RESOLVED
The old TypeScript JSX fragment/build issue is no longer an active CI blocker. Push CI #417 / PR CI #418 passes
the frontend production build.

### Docker-unavailable local verification — HISTORICAL
Earlier reports described Docker as unavailable locally. Current CI successfully exercises the
Docker backend/oracle path, so those reports are not current project state.

Historical forensic reports remain evidence of what was true at their recorded time.
