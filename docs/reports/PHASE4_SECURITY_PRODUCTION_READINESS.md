# Phase 4 — Security and Production Readiness

> Scope: a hardening report. It does not certify the product for production
> use; the owner-dependent items in §2 remain open.

**Phase 4 accepted 2026-11-02** on `32cf586` (CI run 41473111446: 5,080 backend
tests; supply-chain run 41473111346), after `5cabbb9` (CI 41468080026, supply
chain 41468080031).

Branch `feat/phase3-coverage`, started 2026-11-02 after Phase 3 was accepted
(`7e1a0d1`, CI run 41445001799). Method: Audit → Plan → Implement → Test →
Verify → Document → Commit → Push → exact-SHA CI. Deterministic, no LLM; no
security check was weakened or bypassed.

## 1. Audit

Four read-only audits of the repository, each finding then checked against
the code before it was acted on:

| Area | Scope |
|---|---|
| API | authentication, authorization, every route, uploads/ZIP ingest, limits, errors, CORS, headers |
| Isolation and deployment | every `docker run`, images, Docker socket, compose, nginx, deploy/backup scripts |
| Data | secrets, storage and retention, logging, audit trail, monitoring |
| Supply chain | CI workflows, Python/npm/Maven pins, scanning, signing, licences |

Already solid (kept as is): constant-time token check with a fail-closed
production mode and 32-character floor; ZIP ingest guards (traversal,
symlinks, duplicates, entry/size/ratio caps); bounded uploads and bodies;
every engine `docker run` carries `--network none`, `--cap-drop ALL`,
`no-new-privileges`, non-root `--user`, memory/cpu/pids limits, timeouts and
cleanup; base images and actions pinned by digest/SHA; read-only CI token;
`pip-audit` and `npm audit` gate CI; no secret found anywhere in git history.

## 2. Findings and resolution

Severity: P1 high, P2 medium, P3 low (no P0 found).

### Fixed in this push

| # | Sev | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | P1 | The API read sandbox output with `is_file()` / `read_bytes()`, following symlinks: a COBOL program could link `/proc/self/environ` (the API token) or the SQLite database into its output mount and the API would read it as program output. No size cap. | `engine/execution/workspace_files.py`: `lstat` + `O_NOFOLLOW` + `fstat` re-check; links, special files and linked directories raise `UnsafeSandboxOutput` (the run fails closed); 64 MiB per file, 256 MiB total. Used by the oracle (incl. compile diagnostics), javac and Maven lanes. | `tests/test_phase4_security.py` unit tests; Docker lane: real COBOL `CALL "SYSTEM"` planting `ln -s /etc/passwd` → oracle FAILED, named reason, no content |
| 2 | P1 | Generated bundles were created by `tempfile.mkdtemp()` without a directory — in `$TMPDIR` (a 1 GB tmpfs in production) instead of the durable run output directory: lost on restart (approval/download then 404), never cleaned (9,295 leftover dirs on the dev host), not in backups. A test mocked the pipeline and hid it. | Runtime adapters take `output_root`; the pipeline passes its output directory. | real-pipeline test for spring_boot, plain_java, quarkus |
| 3 | P2 | Production image ran unauthenticated when started outside compose (`CONTROL_PLANE_ENV` unset). | `ENV CONTROL_PLANE_ENV=production` in `Dockerfile.production`. | image built: refuses to start without a token |
| 4 | P2 | ZIP ingest and uploads ran blocking extraction/discovery on the event loop and outside the job limit: a few large archives stalled `/health` and `/ready`. | `run_in_threadpool`; ingest takes a job slot (429 when full). | `test_ingest_counts_against_the_job_limit` |
| 5 | P2 | Responses carried absolute server paths and raw exception text (paths, Docker/Maven output) — contradicting PRODUCTION_SECURITY.md. | Production responses map server roots to `<server>/…`; unexpected background exceptions surface as type + run id (full text in the log); ZIP and discovery errors drop server paths. | tests; image check |
| 6 | P2 | No rate limiting (BL-114, deferred under D-7 for lack of values). | nginx per-client limits with defaults sized for SPA polling: 50 r/s (burst 100), POST 30/min (burst 10), 429. Values remain owner-tunable (D-7). | `nginx -t` on the pinned image |
| 7 | P2 | No audit trail: approvals overwrote the previous decision; no event for approvals, downloads or failed authentication. | Append-only `approval_events` table (decisions and resets), `history` on the approval response; structured `approval.decided`, `run.downloaded`, `auth.failed` events (never the credential). | `TestApprovalAuditTrail`, 401 test |
| 8 | P2 | Untrusted programs could fill the host disk through writable mounts. | `--ulimit fsize=128 MiB` on every container (hardening contract). Total quota: operator (below). | `tests/test_container_hardening.py` |
| 9 | P2 | Independent verifier ran untrusted programs as root without limits; values unquoted in `sh -c`. | Own hardening flags (non-root, cap-drop, no-new-privileges, limits, named + removed on timeout), `shlex.quote`; script still shares no code with the platform. | re-run: AGREE on two apps |
| 10 | P2 | Python installs not hash-verified; CI tools unpinned; no image / Java-tree scanning; no update automation; Maven precache checksums only warned. | `requirements.lock` hashed for every pin + `--require-hashes` (CI, image); tools pinned; report-only Trivy job over the three images; `dependabot.yml`; `mvn -C`. | lock resolves for Linux py3.11 under `--require-hashes`; image rebuilt with `-C` |
| 11 | P3 | `/ready` (unauthenticated) leaked paths, OS error text and load; 401s lacked security headers; `/docs` and OpenAPI served in production. | Anonymous production `/ready` gets `ok` per check; 401 carries headers; docs off in production. | tests; image check |
| 12 | P3 | `java_entrypoint` reached `sh -c` unquoted; free-text fields unbounded; NUL / `:` in upload names gave 500 / ADS. | Name pattern + length bounds; `shlex.quote` in the Java lanes; control characters and `:` rejected. | tests |
| 13 | P3 | `DOCKER_GID` silently defaulted to 0 (root group); API had capabilities; nginx ran with the default set. | `:?` with detection in `start-production.sh`; `cap_drop: ALL` for the API; nginx `cap_drop: ALL` + `CHOWN SETUID SETGID NET_BIND_SERVICE` (verified to serve). | topology tests |
| 14 | P3 | Text-mode logs could be forged with a newline in a request path; engine `print()` calls bypassed logging. | CR/LF escaped; `logging`. | test |
| 15 | P3 | Backups and the rollback env copy (contains the token) used the default umask; `checkout` left the token in `.git/config`. | `umask 077` / `chmod 700`; `persist-credentials: false`. | tests |
| 16 | P3 | Docs wrong or stale: PRODUCTION_SECURITY (paths, tmpfs, rate limits), DOCKER_SOCKET_HARDENING (`group_add`), DEPENDENCY_AUDIT (npm advisories closed since), THIRD_PARTY_NOTICES (Berkeley DB, GMP, libcob LGPL, bundled Java frameworks missing), PROJECT_LICENSE_DECISION §4, stray `EOF`/`PY` lines. | Corrected. | — |

### Accepted, deferred or owner-dependent (not claimed as done)

| Item | Status | Why it is not fixed here |
|---|---|---|
| Identity and authorization: one shared token, no per-user identity, roles, tenant scoping or approver verification (anyone with the token can approve and export) | **owner decision** (BL-122 / D-9) | needs an identity provider, a role model and tenancy rules |
| Docker socket in the API container (root-equivalent) | **accepted risk**, documented | a socket proxy limited to the sandbox images, or running the API on the host, is an infrastructure decision |
| Artifact / image / SBOM signing and provenance attestation | **owner decision** (L3_7 decision record: BLOCKED) | key custody (file / secret manager / KMS), algorithm, rotation, legacy-seal policy |
| Generated framework versions: Spring Boot 3.2.5, Quarkus 3.15.1, Micronaut 4.6.3 past support | **owner decision** (J1, J3) | generator + precache + full corpus re-proof; the new image scan reports them (report-only until then) |
| Image scan findings (OS packages of all three images, Maven build-plugin jars, Docker CLI binary, base-image pip tooling) — see "First image scan" | **owner decision** | each fix changes a pinned identity recorded in evidence/provenance (oracle image, base digests, Docker CLI pin) |
| Project LICENSE | **decided 2026-11-03: Apache-2.0** | `LICENSE`, `NOTICE` committed (architecture audit) |
| Berkeley DB (Sleepycat) in the oracle image | legal review **if the image is distributed** | built locally today, not shipped |
| Retention / deletion of uploaded and generated data; encryption at rest; backup encryption | **owner decision** | policy and storage choice |
| Rate-limit values; evidence TTL (BL-113); cancellation (BL-115) | **owner decisions** (D-7, D-8) | defaults set for rate limits only |
| Metrics, alerting, error tracking | **owner decision** | choice of stack; logs are structured JSON with request ids |
| Total disk quota for sandbox staging | operator | own filesystem or quota for `SANDBOX_HOST_STAGING_DIR` |
| uvicorn trusts forwarded headers from all RFC1918 ranges | open (P3) | narrowing needs the deployment's proxy network range |
| Production image includes test-only packages (pytest, Pygments) | open (P3) | needs a separate runtime lock |
| 58 tracked evidence files contain a developer's local paths | open (P3) | low sensitivity; untracking or a history rewrite is the owner's call |
| `engine/execution/docker_runner.py` (deprecated, no importers, allows bridge networking) | deferred to the architecture audit (D1) | unreachable; removal is scheduled there |

### First image scan (supply-chain run 41468080031, `5cabbb9`)

The new report-only job's first results, HIGH / CRITICAL only:

| Image | Target | HIGH | CRITICAL | Nature |
|---|---|---|---|---|
| oracle `gnucobol-ocesql` | Ubuntu 22.04 packages | 516 | 18 | base OS never refreshed since the 2026-10-08 digest pin; `-dev` packages stay in the image |
| offline Maven | Ubuntu 24.04 packages | 3 | 0 | base OS |
| offline Maven | jars in the offline repository | 59 | 5 | mostly **build-time** Maven plugin dependencies pulled by `dependency:go-offline` (old `maven-core`, `plexus-utils`, `dom4j`, `velocity`, `freemarker`, `jsoup`) — run only inside the network-isolated build container; **runtime** findings in what generated jars ship: `spring-boot` 3.2.5 / `spring-core` 6.1.6, `jackson`, `micrometer`, `micronaut-context` 4.6.6 |
| production API | Debian 12 packages | 49 | 2 | base OS (`python:3.11-slim` digest pin) |
| production API | Python packages outside the lock | 2 | 0 | `wheel` 0.45.1 (CVE-2026-24049), `jaraco.context` 5.3.0 (CVE-2026-23949, vendored in setuptools): packaging tools of the base image, unused at runtime — **fixed in the follow-up commit**: both are uninstalled from the image (app import and `/ready` verified without them) |
| production API | Docker CLI binary | 25 | 1 | static `docker` client at the pinned `DOCKER_CLI_VERSION` |

None of these is introduced by Phase 4 — the scan makes them visible for
the first time. Remediation is outside "safely actionable" here because each
one changes a pinned, evidence-bearing identity: framework upgrades (J1, J3:
generator + precache + full corpus re-proof), refreshing the oracle image
(the oracle's image identity is recorded in every verdict's evidence),
base-image and Docker CLI digest bumps (provenance and runtime-digest pins,
J2). They are listed as owner-dependent below; making the scan a gate
belongs to the same decision.

## 3. Verification

- New: `tests/test_phase4_security.py` (41 + Docker-lane exploit test);
  updated: container-hardening, compose topology/render, async modernize
  (error contract).
- Built locally: offline Maven image (`-C`), production image
  (`--require-hashes`, fail-closed start, `/ready`, `/docs`, 401 headers
  checked inside it); nginx config `nginx -t` on the pinned image; nginx
  capability set served a page.
- Full hermetic, gate and Docker suites and exact-SHA CI: see §4.

## 4. Acceptance criteria

| Criterion | Status |
|---|---|
| Repository-wide audit across all listed areas, findings prioritised | met (§1, §2) |
| Every safely actionable fix implemented in one consolidated change | met (§2 "Fixed") |
| No security check bypassed or weakened | met — existing gates unchanged; the new image scan is additive and report-only by stated reason |
| Focused tests per fix; full security, regression, integration and Docker suites | met (CI 41468080026 / 41473111446; local hermetic, gate and Docker-lane runs §3) |
| Documentation updated | met (§2 #16) |
| Owner-dependent blockers documented honestly | met (§2 "Accepted, deferred or owner-dependent") |
| Exact-SHA CI green | met (`5cabbb9`, `32cf586`) |
