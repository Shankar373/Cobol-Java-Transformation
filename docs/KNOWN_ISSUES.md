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
runs. The 2026-10-26 readiness batch added a durable workspace root (BL-139), a `/ready`
readiness probe (BL-140), structured logging with request/run correlation (BL-141),
bounded-retry terminal writes (BL-143) and a 32-character production token floor
(BL-144). Still open for production: a durable job queue with resume across restarts,
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
JCL, CICS and DB2 remain outside behavioral certification until their runtime
semantics are proven (no MVS/CICS/DB2 runtime exists — see the runtime
capability catalog: all three BLOCKED). Indexed/relative file semantics were
proven for a **certified subset** on 2026-10-22 (BL-134: runtime + generated
Java byte-identical to the GnuCOBOL oracle for primary RECORD KEY at offset 0,
ACCESS MODE DYNAMIC, no ALTERNATE RECORD KEY); everything outside that subset,
and any VSAM file-image/on-disk equivalence, remains uncertified.

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

### Production-hardening batch BL-135..BL-138 — RESOLVED, committed `c0c4f9b` / `62e647f` 2026-10-26
- **BL-135** all ten `docker run` sites now share
  `engine/execution/container_hardening.py::container_run_hardening_flags`
  (`no-new-privileges`, `--cap-drop ALL`, non-root `--user 10001:10001`);
  drift guard `tests/test_container_hardening.py`.
- **BL-136** `CONTROL_PLANE_ENV` is a fail-closed production gate: `production`
  requires `CONTROL_PLANE_API_TOKEN` at import and on every route except the
  probes (`/health`, `/ready`) and CORS preflight `OPTIONS`, and an unknown
  environment value raises at startup.
- **BL-137** upload path validation (strict `application_id` regex before
  `mkdtemp`, workspace discarded on rejection) plus the generated-artifact seal
  (`api/artifact_seal.py`, schema version 6): changed bytes, added/removed files
  or a missing/malformed seal all answer 409 at download/approval.
  **Disclosed behavior change:** runs completed before sealing exist with
  `generated_seal NULL` and fail closed (409) at approval/export until
  re-validated — intentional, not a regression. `verify_generated_seal` returns
  `None` on success and raises `ConflictError` on mismatch.
- **BL-138** the Docker capability-truth suite is in the fast ci.yml gate, which
  explicitly `--deselect`s its single API-layer test (needs pydantic; still
  enforced by the backend job's whole-suite run).

### Production-readiness batch (BL-139..BL-147) — SHIPPED 2026-10-26
- **Durable workspace root** (BL-139): `CONTROL_PLANE_WORKSPACE_DIR`, pinned to
  the `control-plane-work` volume in compose/Dockerfile — uploads and generated
  apps now survive restarts, backups and restores (previously written to a
  `/app/tmp` tmpfs the volume never saw).
- **Readiness probe** (BL-140): `GET /ready` returns 503 when database,
  workspace or sandbox staging is unusable (Docker reported but non-gating),
  wired into the compose healthcheck, image `HEALTHCHECK`, nginx and
  `verify-production.sh`; `/health` stays liveness-only.
- **Structured logging** (BL-141/BL-143): `CONTROL_PLANE_LOG_LEVEL` /
  `CONTROL_PLANE_LOG_FORMAT` (JSON in production), `X-Request-Id` correlation,
  one access line per request (method/path/status/duration — never tokens) and
  run lifecycle events; terminal writes retry boundedly and log failure loudly.
- **Secrets handling** (BL-144): production rejects tokens under 32 characters
  at startup, and `npm run build` fails if `VITE_CONTROL_PLANE_API_TOKEN` would
  be inlined into public assets (`ALLOW_BUNDLED_API_TOKEN=1` acknowledges with a
  warning).
- **Deployment validation** (BL-145/BL-146): `start-production.sh` preflights
  `docker info` + `docker compose config --quiet` before `up`;
  `verify-production.sh` derives the api container id from compose; all six
  shell scripts corrected CRLF to LF with `.gitattributes` enforcement and a
  contract suite (they were unrunnable on Linux, and CI never executes `.sh`).
- **Backup verification** (BL-147): `backup.sh` now fails unless
  `scripts/backup/verify_backup.py` confirms the SQLite copy opens, passes
  `integrity_check` and holds a non-newer schema, and the workspaces archive is
  a non-empty gzip tar.

Approved deferrals are unchanged and remain open: D-7 (evidence TTL, BL-113),
D-7 (rate limiting, BL-114), D-8 (cancellation/retry/deadline, BL-115), D-9
(enterprise scope, BL-122), BL-116 materialization, D-4 — see "P1 — Deferred
production gaps" above; nothing in this batch claims them.

### Universal-runtime-proof audit fixes — RESOLVED locally 2026-10-19 (pending CI via R-1)
The 2026-10-19 audit found and fixed red-first: frontend Authorization integration (BL-094),
`docker_available=True` hardcode in `api/service.py` (BL-095), dashboard "Verified" overclaim
(BL-096), and platform-canonical ZIP ingestion + source-tree hashing (BL-097). Red-first
evidence and regression results: `docs/BACKLOG.md` change-log (bd)/(be). Not yet
CI-validated (no push authorization); roadmap R-1 in
`UNIVERSAL_RUNTIME_PROOF_AUDIT_AND_IMPLEMENTATION_PLAN.md` covers commit + exact-SHA CI.

Historical forensic reports remain evidence of what was true at their recorded time.
