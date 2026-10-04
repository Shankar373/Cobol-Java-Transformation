# Known Issues

Current baseline: 4513881bc3dff50df4e81910dbc2d28fe5308dbc
CI Run #306: GREEN

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
SQLite/filesystem persistence is functional but is not yet a production-grade security boundary.
Unsafe serialization, authorization, retention, audit logging, rate limiting, migration and
concurrency controls require hardening.

### P1 — Enterprise runtime boundaries
JCL, CICS, DB2 and indexed/relative file semantics remain outside broad behavioral certification
until their runtime semantics are proven.

### P2 — CI depth
CI is green but can be strengthened with coverage thresholds, lint/type checks, security and
dependency scanning, contract/schema checks and mutation testing.

## Resolved / historical

### TypeScript JSX build blocker — RESOLVED
The old TypeScript JSX fragment/build issue is no longer an active CI blocker. Run #306 passes
the frontend production build.

### Docker-unavailable local verification — HISTORICAL
Earlier reports described Docker as unavailable locally. Current CI successfully exercises the
Docker backend/oracle path, so those reports are not current project state.

Historical forensic reports remain evidence of what was true at their recorded time.
