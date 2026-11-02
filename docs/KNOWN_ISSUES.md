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

### Phase 5 certification findings (2026-11-02)
Certification (`docs/reports/PHASE5_FINAL_CERTIFICATION.md`) re-proved every
SUPPORTED construct against GnuCOBOL (`tests/test_phase5_certification.py`) and
found two over-claims, both fail-closed in generation (no false VERIFIED):
- **REPLACE** was registry-SUPPORTED without GnuCOBOL proof; a two-pair
  `REPLACE` fails generation (only the first pair is applied). Lowered to
  PARTIAL. Programs containing REPLACE were and stay UNSUPPORTED.
- **UNSTRING WITH POINTER / TALLYING IN** were described as "implemented and
  oracle-proven"; generation refuses both. Evidence text corrected; GnuCOBOL's
  output is pinned for a future implementation.
- **Unit oracle only** (no certified corpus application exercises them):
  ACCEPT, UNSTRING, PERFORM … TIMES, REDEFINES digit views — proven by
  oracle-pinned tests, not by an end-to-end application.
- **Release:** making `DOCKER_GID` required (Phase 4) broke `rollback.sh`,
  `restore.sh` and a standalone `verify-production.sh` (compose interpolates it
  on every command); fixed by `scripts/deploy/lib-docker-gid.sh`, sourced by all
  four entry points (guard test). Rebuilding a reused image tag destroys the
  rollback target — PRODUCTION.md now builds a new tag per release.
- **CI false pass (found and fixed the same day):** the first run of the new
  certification workflow passed although the independent verifier had crashed
  (sandbox-owned files on Linux; `cmd | tee` without `pipefail`). Not counted;
  verifier and workflow fixed, guard test on every workflow (`tests/test_phase5_certification.py`).
- **Performance:** first deterministic budgets (`tests/test_phase5_performance.py`:
  corpus generation, API read latency). Docker build/execution time is
  host-dependent and reported, not asserted.

### False-success baseline (2026-11-01, branch `fix/false-success-baseline`)
A 41-program differential corpus run against GnuCOBOL 3.1.2 found 28 false
successes at `b79f348` (translation reported success, Java behaved
differently).  After this batch: 0 false successes — 33 byte-identical,
8 fail closed.  Report: `docs/reports/FALSE_SUCCESS_BASELINE_2026-11-01.md`.
Still open, all fail closed today (no false VERIFIED path known):
- **Database state capture:** no comparator observes database effects;
  programs with non-declarative `EXEC SQL` / `EXEC DLI` derive `UNSUPPORTED`.
- **Real shared group storage:** groups are lowered as views; OCCURS,
  REDEFINES, COMP, signed/scaled leaves, reference modification and group
  operands of STRING/UNSTRING/INSPECT/READ/WRITE/CALL are refused.  A file
  record (FD 01) is a view only when it is its FD's sole record, every leaf
  is named and the use is MOVE/DISPLAY; any other use of a record name is
  refused (it reached the Java as an undeclared name before Phase 3).
- ~~**Spring Boot application path entry**~~ — fixed in Phase 2: the runner
  calls `RUN_UNIT$ENTRY` (fall-through chain, EXIT PROGRAM no-op), oracle-pinned
  through the Maven build in `tests/integration/test_spring_entry_semantics.py`.
- **Run-unit control flow beyond the fall-through chain:** STOP RUN/GOBACK in
  PERFORMed or nested positions, STOP RUN in CALLed programs, procedure
  SECTIONs, GO TO.
- **Qualified data names (`OF`/`IN`):** duplicated names are refused.
- **`WITH NO ADVANCING`, level 66, JUSTIFIED, BLANK WHEN ZERO, COPY in the
  single-source producer:** refused with named diagnostics.  ~~ON SIZE
  ERROR~~ is lowered since Phase 3 increment 8 (`tests/test_size_error.py`)
  for single-receiver ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE; with several
  receivers or with DIVIDE … REMAINDER it is still refused.
- ~~**Division by zero without ON SIZE ERROR**: the generated Java threw
  `ArithmeticException`~~ — since increment 9 a zero divisor anywhere in a
  DIVIDE/COMPUTE leaves every receiver (REMAINDER too) unchanged and the run
  continues, as GnuCOBOL 3.1.2 does (`tests/test_size_error.py`).
- **STDERR** is compared only when the source writes to it (`UPON STDERR` /
  `SYSERR`); otherwise GnuCOBOL runtime messages and JVM diagnostics differ by
  design and are not compared.

### Application end-to-end validation (Phase 2, 2026-11-01)
Every `fixtures/*/cobol` application was run through the real API (ZIP
ingest → discovery → generation → Docker build → execution → GnuCOBOL
differential) and every VERIFIED result was re-checked by an independent
harness (direct `cobc` and `java -jar`, every file in the working directory).
Report: `docs/reports/PHASE2_E2E_VALIDATION_2026-11-01.md`.  Open items:
- ~~**Indexed/relative file images are not compared**~~ — INDEXED files are
  compared by records since Phase 3 (`tests/test_indexed_record_comparison.py`);
  RELATIVE files by (RRN, record) since increment 5
  (`tests/test_relative_record_comparison.py`).  Still INCONCLUSIVE (PARTIAL):
  a RELATIVE image with no live record or an ambiguous slot layout, and any
  INDEXED/RELATIVE file the program reads without creating it in the same
  run (the Java emulation does not load an existing image).
- ~~**Record SEQUENTIAL files** fail closed~~ — fixed-length record
  SEQUENTIAL files are certified since increment 6
  (`tests/test_record_sequential_files.py`).  Still refused: variable-length
  records (several record descriptions, VARYING, CONTAINS n TO m, RECORDING
  MODE), LINAGE, OPEN I-O/REWRITE/DELETE/START on sequential files, and
  record layouts outside the group-view subset.
- **WRITE … AFTER/BEFORE [ADVANCING] / END-OF-PAGE** fail closed (they were
  silently dropped before increment 6); `WRITE … FROM` on a continuation
  line is refused (skipped-statement diagnostic).
- **Numeric fields holding spaces** (a record READ whose numeric field is
  blank): GnuCOBOL keeps the spaces, the Java field is a number — the run
  stops or differs, it never verifies.
- **`SELECT OPTIONAL`** fails closed (increment 5): a missing optional file
  opens with status 05 and reads empty, which the generated runtime does not
  model; it was silently ignored before.  A missing non-optional file opens
  with status 35 in both runtimes.
- ~~**Signed numeric STRING sources** fail closed~~ — reproduced since Phase 3
  increment 10 (overpunched last digit, `tests/test_signed_storage_text.py`);
  **COMP STRING sources** still fail closed (binary bytes).
- ~~**Referenced COMP / COMP-3 items** keep programs PARTIAL~~ — since Phase 3
  a standalone COMP/BINARY/COMP-3/PACKED-DECIMAL item used only by value is
  SUPPORTED (`workload-comp`, `workload-comp3`, `workload-binary-values`
  VERIFIED; `tests/test_binary_usage_values.py`).  Still PARTIAL: an item a
  statement can see as bytes (CALL USING, reference modification,
  STRING/INSPECT, LENGTH OF, REDEFINES, inside a group), and COMP-5,
  COMP-1, COMP-2.  `workload-relative`/`workload-relative-file` now generate
  and, since increment 5, are VERIFIED.
- **MOVE alphanumeric → numeric** is certified for digit-only content; any
  other content (spaces, signs, letters — GnuCOBOL applies rules not
  reproduced) stops the Java run with `NumberFormatException`, so the run
  FAILS instead of storing a guessed value.
- ~~**Found by the Phase 3 binary-values application, refused today:** signed
  literals in conditions, ZERO in a numeric comparison~~ — supported since
  increment 7, together with sign conditions (`IS [NOT] POSITIVE/NEGATIVE/
  ZERO`, which used to generate the undeclared Java name `NEGATIVE` while
  classified SUPPORTED) and decimal literals in conditions
  (`tests/test_condition_operands.py`).  Still refused: abbreviated combined
  relations (`A = 1 OR 2`; on numeric items this generated `A == 1 || 2`,
  which does not compile, while classified SUPPORTED), ordering comparisons
  against an alphanumeric ZERO (`A > ZERO` on PIC X).  ~~An IF/ELSE on a
  single source line~~ is lowered since increment 10 (an `ELSE stmt END-IF`
  line also used to swallow the following statements silently).
- **Tables and overlays** (Phase 3 increment 10): element-only OCCURS tables
  and digit REDEFINES overlays are certified (`workload-occurs` VERIFIED;
  `tests/test_occurs_elements.py`, `tests/test_redefines_digit_views.py`).
  Still refused: whole-table references, multi-dimension tables, INDEXED BY /
  SEARCH / DEPENDING ON; REDEFINES of signed, scaled or COMP items, nested
  groups, and non-digit bytes written under a numeric view
  (`workload-redefines`: GnuCOBOL decodes them compiler-specifically).  A
  numeric REDEFINES view whose bytes become non-digits at run time stops
  the Java run.  **CALL BY VALUE** (`workload-by-value`, GnuCOBOL 3.1.2
  implementation unfinished) stays refused.
- **Runtimes**: `spring_boot`, `plain_java`, `quarkus` and `micronaut` are
  proven end to end on the whole corpus (Phase 3 §3.11, §3.12).  Quarkus and
  Micronaut are command-mode applications only: no HTTP/REST endpoints, no
  native image.  `jakarta_ee` is a plain jar under a Jakarta-marked pom (no
  server runtime).  Application servers (a Jakarta EE server, WildFly, Open
  Liberty, Payara, TomEE) are **not supported**: deferred by decision, the
  names are refused as unknown targets.
- **Infrastructure failures are ERROR, not UNAVAILABLE** (audit B4, fixed
  2026-11-03 from FAILED): a candidate build that could not run at all (no
  Docker, build image unavailable or its identity changed - e.g. a locally
  rebuilt Maven image without re-running
  `scripts/record_docker_image_provenance.py`) is now recorded as an
  infrastructure `error` and derives ERROR; it used to be compared as the
  program's nonzero exit and derive FAILED. The derivation's error check
  precedes its UNAVAILABLE check (`engine/verdict/derivation.py`, a
  do-not-regress area, left unchanged). Still open: Docker's own exit codes
  125/126/127 at run time are classified as the program's nonzero exit -
  a COBOL program can legitimately end with RETURN-CODE 125..127, so the
  exit code alone cannot tell them apart.
- **Undefined data names** are not resolved by the parser: a program GnuCOBOL
  rejects (e.g. a name cut at column 72) still fails, but at Java compile time.
- **Plain Java entry selection** falls back to the first program when no entry
  is given, while the oracle requires an unambiguous entry; the service always
  passes the resolved entry, but the two rules should be unified.

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
runs. The 2026-10-26 readiness batch added a durable workspace root (BL-146), a `/ready`
readiness probe (BL-147), structured logging with request/run correlation (BL-148),
bounded-retry terminal writes (BL-150) and a 32-character production token floor
(BL-151). Phase 4 (2026-11-02, `docs/reports/PHASE4_SECURITY_PRODUCTION_READINESS.md`)
added: sandbox output read without following links (symlink exfiltration closed), the
generated bundle in the durable workspace, fail-closed production image, per-client rate
limits at nginx (default values), an append-only approval trail plus `auth.failed` /
`approval.decided` / `run.downloaded` events, server paths withheld from production
responses, hash-verified Python installs and a report-only image/Java scan. Still open for
production: a durable job queue with resume across restarts, retention/TTL and deletion,
encryption at rest, external secret management for `CONTROL_PLANE_API_TOKEN` (the token is
an env-var deployment control, not a user/role model — the approver is recorded input, not
a verified identity, and the trail is append-only but not tamper-evident), artifact
signing, TLS and egress policy at the deployment boundary, metrics/alerting, and
multi-node coordination (SQLite is single-node).

### P1 — Deferred production gaps (owner-approved 2026-10-21)
The following production requirements are **explicitly deferred** by owner decision;
they are not claimed to exist and no document may claim them before enforcement:

- **Time-based evidence staleness (BL-113, D-7 approved):** evidence timestamps are
  recorded but no wall-clock TTL is enforced. Staleness is enforced generation-wise
  only. A TTL policy interacts with clock skew and re-validation flows; the value is
  a policy decision deferred.
- **Rate limiting (BL-114, D-7 approved):** Phase 4 added per-client limits at nginx
  with default values sized for SPA polling (50 r/s burst 100; POST 30/min burst 10;
  429). The policy values remain the owner's (D-7); there is no per-user or per-token
  limit, and the API process itself only enforces the concurrency-slot limit.
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
  multi-node coordination are documented as future requirements but have no
  enforcement (SBOMs and vulnerability scanning exist since workstream 5 / Phase 4;
  the image and Java-tree scan is report-only). The single shared token grants
  global read/write, including approval and export. Scope is deferred; no document may claim these controls
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

### Production-readiness batch (BL-146..BL-154) — SHIPPED 2026-10-26
> Filed as BL-139..BL-147 in the 2026-10-26 working tree; renumbered 2026-10-28
> to BL-146..BL-154 when the concurrent file-level audit batch claimed the
> BL-139..BL-145 ids in the register.
- **Durable workspace root** (BL-146): `CONTROL_PLANE_WORKSPACE_DIR`, pinned to
  the `control-plane-work` volume in compose/Dockerfile — uploads and generated
  apps now survive restarts, backups and restores (previously written to a
  `/app/tmp` tmpfs the volume never saw).
- **Readiness probe** (BL-147): `GET /ready` returns 503 when database,
  workspace or sandbox staging is unusable (Docker reported but non-gating),
  wired into the compose healthcheck, image `HEALTHCHECK`, nginx and
  `verify-production.sh`; `/health` stays liveness-only.
- **Structured logging** (BL-148/BL-150): `CONTROL_PLANE_LOG_LEVEL` /
  `CONTROL_PLANE_LOG_FORMAT` (JSON in production), `X-Request-Id` correlation,
  one access line per request (method/path/status/duration — never tokens) and
  run lifecycle events; terminal writes retry boundedly and log failure loudly.
- **Secrets handling** (BL-151): production rejects tokens under 32 characters
  at startup, and `npm run build` fails if `VITE_CONTROL_PLANE_API_TOKEN` would
  be inlined into public assets (`ALLOW_BUNDLED_API_TOKEN=1` acknowledges with a
  warning).
- **Deployment validation** (BL-152/BL-153): `start-production.sh` preflights
  `docker info` + `docker compose config --quiet` before `up`;
  `verify-production.sh` derives the api container id from compose; all six
  shell scripts corrected CRLF to LF with `.gitattributes` enforcement and a
  contract suite (they were unrunnable on Linux, and CI never executes `.sh`).
- **Backup verification** (BL-154): `backup.sh` now fails unless
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
