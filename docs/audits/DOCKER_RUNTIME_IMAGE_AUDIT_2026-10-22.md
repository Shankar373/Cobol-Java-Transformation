# Docker Runtime Image Audit — 2026-10-22

**Type:** Runtime-proven modernization / Docker image provenance audit
**Scope:** images genuinely required to execute original COBOL and generated
Java for the indexed-files, DB2/SQL, MQ, JCL, CICS and IMS lanes, plus the
three already-verified images.
**Host:** Windows dev host, Docker Desktop (containerized) 29.8.2,
`x86_64`, WSL2 backend (default distro `Ubuntu-24.04`, WSL 2).
**Working tree:** branch `codex/universal-core`, HEAD `2e2f4ca` + preserved
uncommitted in-flight changeset. **Nothing was committed, pushed, deployed,
branched or deleted. No existing image, container, volume or cache was
pruned, removed or cleaned.** Every file listed under
`test-artifacts/runtime-image-audit-2026-10-22/` is new; every pre-existing
`test-artifacts/*` file is untouched.

**Method (evidence-backed, no assumptions):**

1. Read `MASTER_IMPLEMENTATION_README.md`, `opencode.md`, the three
   Dockerfiles, `docker-compose.production.yml`, the runtime adapters,
   `docs/verification/RUNTIME_PROOF_MATRIX.md` and the recorded image
   provenance.
2. Verified Docker/WSL health and free disk **before** any container start
   or download (rule 5).
3. Smoke-tested each existing image with real work (rule 2/6).
4. Enumerated every image reference reachable from tests, `engine/`, and
   CI (rule 3): a test-driven requirement matrix decides what must exist.
5. Probed candidate mainframe registries **read-only** (manifest metadata
   only, no layers pulled) for availability, architecture and access
   (rule 3/4) — no login, no entitlement key, no license bypass.
6. Executed the repository's real runtime-proof harness (original COBOL in
   the oracle container vs. generated/hand-written Java in the candidate
   container, differential comparison, evidence persistence).

Evidence directory: `test-artifacts/runtime-image-audit-2026-10-22/`
(junit XMLs, per-image smoke logs, registry probes, docker inventory,
docker event capture of the harness run, exit codes).

---

## 1. Environment health (checked before every download/run)

| Check | Result | Evidence file |
|---|---|---|
| Docker daemon | 29.8.2, Docker Desktop (containerized), x86_64, 8 images / 3 containers | `docker-version.txt`, `docker-info.json` |
| WSL | WSL 2, default distro Ubuntu-24.04 | `wsl-status.txt` |
| Free disk (C:) | 151.5 GB free / 323.2 GB used | `psdrive.txt` |
| `docker system df` before run | images 4.519 GB, containers 7.982 GB, volumes 2.003 GB, build cache 3.401 GB — **left untouched** | `docker-system-df.txt` |

No prune, `rmi`, `system cleanup`, volume removal or cache clear was run at
any point.

## 2. Existing verified images — reuse first (rule 2)

| # | Image | Purpose | Repo digest (identity) | Size | License | Smoke test | Remaining dependency |
|---|---|---|---|---|---|---|---|
| 1 | `gnucobol-ocesql:latest` | COBOL **oracle** lane: compiles + executes the original COBOL in an isolated container (`engine/oracle/docker_adapter.py`) | `sha256:68900cc01cd615039fcd36fa0b619242ad2961a6aaa818fb1a2372dfd507e354` (matches `test-artifacts/docker-image-provenance.json` and the recorded baseline) | 414 MB (414,288,622 B) | GnuCOBOL GPL-3.0 (compiler) / LGPL (runtime), Ubuntu 22.04 package licenses, base `ubuntu:22.04@sha256:5ec03bb3…` digest-pinned | **PASS** — `cobc (GnuCOBOL) 3.1.2.0`; compile+run of a WORKING-STORAGE program (`ORACLE-SMOKE-OK NUM=0042`); **real indexed-file probe** (ORGANIZATION INDEXED WRITE/READ/INVALID KEY → `INDEXED-SMOKE-OK`, file status 00); **real relative-file probe** (`RELATIVE-SMOKE STATUS=00`). Log: `smoke-oracle.log` | None for the existing suite. **Gap:** no `ocesql` executable (verified below) → `EXEC SQL` COBOL cannot be compiled here |
| 2 | `maven-offline-springboot:latest` | Candidate **build** lane (`engine/candidate/docker_spring_boot_adapter.py`, offline Maven) | `sha256:32139c85749826f0790acf02224113fed7498c2f3160d70e6467c18c1b5d7eb1` (matches provenance record) | 952 MB (951,846,688 B) | Maven Apache-2.0, Temurin GPLv2+Classpath Exception, Spring Boot Apache-2.0, base `maven:3.9-eclipse-temurin-21@sha256:99e61abc…` digest-pinned | **PASS** — Maven 3.9.16 / Temurin 21.0.12.1; `spring-boot-starter-parent:3.2.5` precache present; **offline** (`mvn -o -q package`) Spring Boot jar built: `target/smoke-0.0.1.jar`. Log: `smoke-maven.log` | None — offline build proven without network |
| 3 | `eclipse-temurin:21-jdk` | Candidate **execution** lane, digest-pinned in `DockerSpringBootConfig.runtime_digest` | `sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026` (equals the adapter's pinned digest **and** the provenance record) | 726 MB (720,669,727 B) | GPLv2 + Classpath Exception (Eclipse Temurin) | **PASS** — `openjdk 21.0.12.1 LTS`, `javac 21.0.12.1`, run under `--network none --memory 512m --cpus 1.0`. Log: `smoke-java.log` | None |

Full machine-readable metadata: `image-inspect.json` (RepoTags, RepoDigests,
ID, size, created, os/arch per image).

Other locally present images (inventory only, **not** part of the runtime
proof lanes, left untouched): `systemaops-audit:1.0`,
`systemaops-audit-pytest:1.0`, `systemaops-dind:1.0`,
`docker:29.8.2-dind`, `alpine:3.20`.

### 2.1 The `ocesql` gap is real (rule 4, verified — not assumed)

Inside `gnucobol-ocesql:latest` (network disabled):

- `command -v ocesql` → **not found**; `find / -name 'ocesql*'` → nothing.
- `cobc --help | grep -iE 'sql|db2|mysql|postgre'` → **no SQL options**
  (this GnuCOBOL build has no `-fcobol-sql*` support compiled in).
- `ldconfig -p | grep -iE 'ocesql|cobsql|db2|odbc'` → **no SQL/ODBC
  libraries**.
- Installed compiler: Ubuntu packages `gnucobol3 3.1.2-5`,
  `libcob4 3.1.2-5`.

So the image name is historical (`docs/decisions/PHASE1_DECISION_REPORT.md`
E1 records a predecessor image "GnuCOBOL 3.1.2.0 + OCESQL 1.4"), but the
**current** digest-pinned image ships only GnuCOBOL. The real consequence:
`fixtures/workload-db2/cobol/ACCOUNT-DB2.cob` (EXEC SQL) cannot be compiled
or executed by this oracle — it is preprocessed/analysed only by the
in-repo DB2 lane.

**Decision — do not rebuild `gnucobol-ocesql:latest` to add `ocesql`.**
Reasons (all evidence-based):

1. **No test requires it.** `ocesql` is referenced nowhere in `tests/` or
   `engine/`; no existing test executes `EXEC SQL` COBOL.
2. Rebuilding that tag would change the pinned identity of the oracle the
   whole suite fail-closed-verifies against (`68900cc0…`), invalidating the
   recorded provenance and the baseline evidence of the 4006-test sweep —
   an avoidable regression risk to preserved work.
3. OCESQL supports **PostgreSQL only** (upstream README of
   `opensourcecobol/Open-COBOL-ESQL`, GPL-3.0/LGPL-3.0); it would not make
   a *DB2* runtime claim possible anyway.

If an EXEC-SQL runtime lane is ever authorized, the legitimate path is a
**separate** digest-pinned image (new tag, PostgreSQL + OCESQL v1.4 tarball
SHA-256 verified, per the E1 precedent) so the existing oracle identity
never moves.

## 3. Which images do the real tests actually require? (rule 3)

Exhaustive search of `tests/`, `engine/`, `.github/workflows/` for image
references found **exactly three** runtime images: `gnucobol-ocesql:latest`,
`maven-offline-springboot:latest`, `eclipse-temurin:21-jdk` (the only other
image strings in tests are deliberate `nonexistent-image:latest`
UNAVAILABLE-path fixtures). There is **no** test anywhere that skips, xfails
or fails for want of a DB2, MQ, CICS, IMS or JCL executor image.

Requirement matrix by lane (real tests only):

| Lane | Real test(s) | Image(s) they need | Required? | Status |
|---|---|---|---|---|
| **Indexed files** | `tests/integration/test_indexed_semantics.py` (13), `test_relative_semantics.py` (10), plus `workload-indexed-rewrite-delete-start`, `workload-start-invalidkey`, `workload-relative-file` fixtures | oracle + build + runtime (the three) | Yes | **Satisfied** — original `ORGANIZATION IS INDEXED` COBOL really runs (Berkeley DB ISAM) in the existing oracle image; independent probe in `smoke-oracle.log` confirms `INDEXED-SMOKE-OK` |
| **Relative files** | `tests/integration/test_relative_semantics.py` | the three | Yes | **Satisfied** (probe: `RELATIVE-SMOKE STATUS=00`) |
| **JCL** | `tests/integration/test_jcl_spring_boot_compile.py` (2) — build/start only, labelled PARTIAL | build + runtime (the three) | Yes | **Satisfied** for what the test claims. *Behavioural* JCL execution has **no test and no runtime** (see §4.3) |
| **DB2 / SQL** | `tests/test_db2_{status,semantics,mapping,execution,compatibility,fixture}.py`, `tests/test_db2_compatibility.py` | **none** — controlled in-process SQLite harness (`engine/sql/db2_sqlite.py`) | No image required | Satisfied as designed; `DB2_RUNTIME_VERIFIED` stays empty by contract (`engine/sql/README.md`) |
| **MQ** | classification only (`tests/test_external_dependency_edges.py`, platform-ledger edges) | none | No image required | No runtime lane exists (see §4.4) |
| **CICS** | `tests/test_cics_*.py`, `tests/transformation/test_cics_java_lane.py`, fixture declaration `fixtures/workload-cics/workload.py` ("NOT executed on CICS TS") | none | No image required | Mapping/generation only (see §4.5) |
| **IMS** | classification edges only | none | No image required | Blocker documented (see §4.6) |

**The one non-obvious image reference in executable code** is the
benchmark/reference producer
`opensourcecobol/opensourcecobol4j:2.1.0`
(`engine/transformation/producers/opensource4j.py:130`). It is **not**
required by any test: `tests/transformation/test_producer_diagnostics_contract.py`
drives it with `use_docker=False`, and `tests/test_r1_security_hardening.py`
asserts the `docker run` argv via monkeypatch without executing a
container. It is a reference/benchmark-only lane (explicit scope decision
in `docs/BACKLOG.md`, BL-098) and belongs to none of the six audited lanes.
→ **not installed** (no test would run it).

**Conclusion of rule 3:** the set of additional images required by real
tests is **empty**. Therefore **no new image was downloaded or built** —
downloading DB2/MQ/CICS/IMS images would have been exactly the
"download every image blindly" behaviour the task forbids, since no test
would execute them.

## 4. Registry / licence / architecture due diligence (read-only, rule 3/4)

Evidence: `registry-probes.txt` (manifest metadata only — no layer was
pulled, no login performed, no license accepted).

| Candidate | Registry probe | Arch | License / terms | Decision |
|---|---|---|---|---|
| IBM CICS Transaction Server (`icr.io/cics/dev/cics-ts`) | **`UNAUTHORIZED`** — `{"code":"UNAUTHORIZED","detail":"Authorization required…"}` | n/a | Proprietary IBM (paid entitlement) | **BLOCKED — no bypass attempted** (rule 4). No CICS runtime claim is possible |
| IBM IMS (`icr.io/ims/dev/ims-db1`) | **`UNAUTHORIZED`** (same response) | n/a | Proprietary IBM (paid entitlement) | **BLOCKED — no bypass attempted**. No IMS runtime claim is possible |
| IBM MQ Developer (`ibmcom/mq:latest`) | accessible anonymously; manifest list `sha256:417f17642b70…`, `linux/amd64` + `linux/s390x`; Docker Hub metadata: 553.37 MB compressed (amd64), last pushed ~5 years ago (**repo marked deprecated/unmaintained** — 9.2.4) | amd64 available | **IBM MQ Advanced for Developers** — free but *license-restricted*: requires `LICENSE=accept` at container start, "does not permit further distribution", usage restricted to a developer machine (Docker Hub / IBM docs) | **Not downloaded** — no MQ runtime test exists in this repository; an image nothing executes adds supply-chain surface, not proof. Maintained replacement `icr.io/ibm-messaging/mq:9.4.5.1-r1` also probed anonymously accessible (recorded) for when a real MQ test is written |
| IBM Db2 Community (`ibmcom/db2:latest`, `icr.io/db2_community/db2:latest`) | accessible anonymously; amd64 manifests `sha256:220c15de7eba…` / `sha256:e48ca934c29a…`, both `linux/amd64`+`ppc64le`+`s390x` | amd64 available | Free **Db2 Community Edition** (`LICENSE=accept` required; non-production, 16 GB / 4-core enforced limits) | **Not downloaded** — two hard gaps remain even with the image (see §4.2); no test executes COBOL-against-DB2 |

Nothing was pulled, tagged, retagged or removed. Registry responses were
recorded verbatim.

### 4.1 Indexed/relative files — no extra image needed

GnuCOBOL's native `ORGANIZATION INDEXED` / `ORGANIZATION RELATIVE` (Berkeley
DB ISAM, `libdb` already installed in the oracle image) executes the real
fixture programs. The 23 Docker-gated indexed/relative tests use exactly
the three verified images, so **maximum genuine coverage for this lane is
already reachable with zero downloads** (independently re-probed today).

### 4.2 DB2/SQL — what a genuine `DB2_RUNTIME_VERIFIED` would still need

1. A **COBOL ESQL preprocessor + runtime** inside the oracle image
   (absent — §2.1). OCESQL (the documented predecessor tool) speaks
   **PostgreSQL only**, not DB2.
2. A DB2 client stack (CLI/ODBC driver) — DB2 images ship the server, not a
   GnuCOBOL-bound client, and the driver's redistributable pinning would
   need its own review.
3. A test that actually executes `ACCOUNT-DB2.cob` against the server and
   compares DB **state** (the evidence model currently has no
   database-state artifact comparison).

All three are absent → the lane honestly stays `PORTABLE_EXECUTABLE`
(controlled SQLite), never `DB2_RUNTIME_VERIFIED`. Blocked and documented;
not faked.

### 4.3 JCL — behavioural execution blocked

The only JCL test builds and starts the generated Spring Boot job
(`PARTIAL` in `docs/verification/RUNTIME_PROOF_MATRIX.md`). Running z/OS JCL
itself needs an MVS-class system; the only free options (Hercules +
MVS 3.80 Turnkey, z390) are not available as digest-pinned official
registry images (Hercules/z390 were audited as scaffolding in
`docs/decisions/PHASE1_DECISION_REPORT.md` E1). Pulling an unofficial
third-party "MVS" image would fail the supply-chain rules. → documented
blocker, no download.

### 4.4 MQ — free image exists, but no runtime test exists

`ibmcom/mq` is anonymously readable and genuinely free for development, but
the repository has **no MQ execution lane and no MQ runtime test** (MQ
appears only in dependency classification). Per rule 3 ("only images
required by real tests") it was **not** installed. It is the cheapest
future win: when an MQ PUT/GET differential test is written, this image is
pullable without any entitlement.

### 4.5 CICS — mapping-only lane, runtime blocked by licensing

`engine/cics` maps EXEC CICS commands to Spring services; fixtures declare
themselves as "NOT executed on CICS TS". A genuine CICS TS runtime requires
the UNAUTHORIZED IBM registry → blocked, no bypass (rule 4).

### 4.6 IMS — same class of blocker

No IMS runtime test exists; IBM IMS registry returns `UNAUTHORIZED`.
Blocker documented.

## 5. Runtime-proof harness execution (rule 6/7)

### 5.1 How the harness works (verified in code, file:line)

- **Original COBOL (oracle):** `engine/oracle/docker_adapter.py` — one
  disposable container, image `gnucobol-ocesql:latest` (overridable via
  `SYSTEMAOPS_ORACLE_IMAGE`, digest via `SYSTEMAOPS_ORACLE_DIGEST`),
  `docker run --rm … --network none --memory 512m --cpus 1.0
  --pids-limit 256` (`docker_adapter.py:463-466`), source mounted `:ro`,
  `cobc -x` compile + run inside the container. Container start is refused
  when the image has no immutable digest identity or the resolved digest
  ≠ the declared pin (fail-closed identity at
  `docker_adapter.py:311-360`, `engine/candidate/image_provenance.py:153-193`).
- **Generated Java (candidate):** `engine/candidate/docker_spring_boot_adapter.py`
  — build in `maven-offline-springboot:latest` (`mvn -o -B … package`, all
  containers `--network none`), run in `eclipse-temurin:21-jdk` pinned to
  `sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026`
  (lines 69-72), with a pre-run re-probe that fails closed if an identity
  changes mid-run; plain-Java lane `docker_java_adapter.py` uses the same
  sandbox flags and digest resolution.
- **Comparison:** `engine/comparators/framework.py` — STDOUT, STDERR,
  EXIT_STATUS, TEXT_FILE and FIXED_RECORD comparators (record-count,
  record-by-record and trailing-partial-record checks for fixed records);
  normalization is fail-closed (only `crlf_to_lf`). Side effects (written
  files) are captured from the adapters' output directory by
  `engine/pipeline.py::_extract_artifact_content` and compared per the
  workload's declared contract — so a run only reaches PROVEN when the
  declared file artifacts were actually compared and matched.
- **Evidence:** `engine/evidence/{models,integrity}.py` — manifest with a
  construction-time `sealed_hash`, run/workload/source-binding, oracle
  image-identity binding, source-mutation detection, EXIT_STATUS
  completeness and seal re-verification; production persists the manifest
  as versioned JSON in SQLite (`api/store.py`), CI records image
  provenance under `test-artifacts/`.
- **Gate:** `RUN_DOCKER_TESTS=1` with no Docker runtime **fails** the
  runtime-proof tests instead of skipping them
  (`tests/integration/test_file_write_read_runtime_proof.py:79-125`).

### 5.2 This session's execution

A `RUN_DOCKER_TESTS=1` run of the real harness was already in flight when this
audit resumed (started 2026-10-22 18:07:12 +05:30, python PID 26144). It was
**monitored, not duplicated** — no second run was started.

Exact command (Windows PowerShell):

```powershell
$env:RUN_DOCKER_TESTS = '1'
python -m pytest -q -ra --junitxml="test-artifacts/runtime-image-audit-2026-10-22/runtime-proof-integration.junit.xml" tests/integration tests/execution
```

Result (from the JUnit XML and the recorded exit code, not from console
memory):

| Field | Value | Evidence |
|---|---|---|
| Exit code | **0** | `runtime-proof-exit.txt` (`exit_code=0`, `duration_ms=1997310`, `2026-10-22T18:40:29.7175851+05:30`) |
| Tests | **453** | `runtime-proof-integration.junit.xml` (`<testsuite tests="453">`) |
| Failures / errors / skipped | **0 / 0 / 0** | same XML: zero `<failure>`, `<error>`, `<skipped>` elements; `-ra` printed no skip/xfail lines |
| Duration | 1996.45 s (33 m 16 s) | XML `duration_ms=1997310`; log final line `453 passed, 1 warning in 1996.45s` |
| Timestamps | 18:07:12 → 18:40:29 +05:30 | XML timestamps + exit record |
| Distinct test classes | 125 | XML `classname` attributes |

What these 453 tests actually prove (they are differential runs, not smoke
tests): the original COBOL executes in the digest-pinned GnuCOBOL oracle
container and the candidate Java executes in the digest-pinned Temurin
container (Spring Boot candidates built by the digest-pinned offline-Maven
lane), the declared artifacts are compared by the registered comparators, and
an evidence manifest is sealed and integrity-validated. Included in the run:
arithmetic (33), payroll (29), claims batch (42), copybook runtime (29),
indexed semantics (13), relative semantics (10), file write/read runtime proof
(15), call chain (14), numeric oracle (6), Phase-D integrated (22) and negative
(26), inventory (41), multiprogram oracle (11), JCL Spring Boot build/start (2),
forensic evidence (34), integrated-proof API (18), vertical slice (19) and
sandbox/execution tests. See `phase1-run-record.md` for the per-lane list.

Image identity during the run:

- `docker-images.txt` (before, 18:07:06) and `docker-images-after.txt` (after,
  18:40:29) are **byte-identical**: SHA-256
  `F0D0D92580CE13AB45293EAD3AEC4F8F428B2F43EB3C754855AEB6BE6C4A2393`.
- `docker-system-df.txt` and `docker-system-df-after.txt` are also
  byte-identical (SHA-256
  `E689B06F601A9A918353E3A634338D7713A04C518C4FAFCD7969E63A87CFBB71`): no
  image pull/build/remove, no prune and no cache growth attributable to the
  run.
- `docker-events-posthoc-2026-10-22.log` (256 retained daemon events,
  18:38:52 → 18:40:29) shows `container start` for
  `gnucobol-ocesql@sha256:68900cc0…7e354` and
  `eclipse-temurin@sha256:4d060388…b7026`, plus the pre-existing `alpine:3.20`
  used by long-standing timeout-forensics tests. The in-run `docker events`
  capture (`docker-events.log`, 0 bytes) failed at launch on PowerShell
  argument quoting; the empty file is retained and the post-hoc replay is the
  superseding evidence.

Caveats (scope honesty):

- The run executed the engine state as of 18:07:12. It predates the
  verification-layer work described below and the post-run CALL callee
  duplicate-method fix (`phase1-run-record.md` records the same caveat). It is
  **not** evidence for those newer changes.
- The three smoke logs (`smoke-oracle.log`, `smoke-maven.log`,
  `smoke-java.log`) are environment probes and are **not** counted in the 453.
- The 71 new Docker-free `tests/verification` tests (runtime catalog + business
  invariants) were run separately and are reported in
  `docs/verification/RUNTIME_PROOF_MATRIX.md`; they do not change the 453 count.

## 6. Evidence index (all new files, nothing overwritten)

Everything below was created new under
`test-artifacts/runtime-image-audit-2026-10-22/`. No pre-existing
`test-artifacts/*` file was modified, moved or deleted.

| File | Purpose | Notes |
|---|---|---|
| `phase1-run-record.md` | Run identity, command, result, per-lane coverage, caveats | Human-readable companion to the JUnit XML |
| `runtime-proof-integration.junit.xml` | Machine-readable result of the 453-test run | `tests="453" failures="0" errors="0" skipped="0"` |
| `runtime-proof-integration.log` | Console output of the same run | Progress dots + warnings; final `453 passed` |
| `runtime-proof-exit.txt` | Exit code, duration, timestamp | `exit_code=0` |
| `docker-images.txt` / `docker-images-after.txt` | Image inventory before/after | Byte-identical (SHA-256 `F0D0D925…A2393`) |
| `docker-system-df.txt` / `docker-system-df-after.txt` | Docker disk usage before/after | Byte-identical (SHA-256 `E689B06F…FBB71`) |
| `docker-containers-after.txt` | Container inventory after the run | Contains only pre-existing containers (a 2-day-old `oracle-9315cc4764dd` in `Created`, plus two long-stopped audit containers); no container created by this run remained |
| `docker-events.log` | In-run event capture | **Empty by cause** (see §5.2); retained, not evidence |
| `docker-events.pid.txt` | PID of the failed capture process | Explains the empty file |
| `docker-events-posthoc-2026-10-22.log` | Post-hoc `docker events` replay | 256 events, 18:38:52 → 18:40:29; supersedes the empty log |
| `docker-version.txt`, `docker-info.json` | Daemon/engine identity and configuration | Docker 29.8.2, x86_64 |
| `wsl-status.txt` | WSL backend identity | WSL 2, Ubuntu-24.04 |
| `psdrive.txt` | Free disk before the run | 151.5 GB free |
| `image-inspect.json` | RepoTags, RepoDigests, IDs, sizes for the three images | Identity source for §2 |
| `registry-probes.txt` | Read-only registry manifest probes (DB2/MQ/CICS/IMS) | No login, no layer pull, no license acceptance |
| `smoke-oracle.log` | GnuCOBOL smoke + indexed/relative file probes | `cobc 3.1.2.0`, `INDEXED-SMOKE-OK`, `RELATIVE-SMOKE STATUS=00` |
| `smoke-maven.log` | Offline Maven build smoke | Maven 3.9.16, `mvn -o` Spring Boot jar built |
| `smoke-java.log` | Temurin execution smoke | `openjdk 21.0.12.1`, run under sandbox flags |
| `git-head.txt`, `git-status.txt` | Tree identity at audit time | HEAD `2e2f4ca`, dirty working tree |

Cross-reference: `test-artifacts/docker-image-provenance.json` (pre-existing,
untouched) matches the three `RepoDigests` above; the catalog layer added later
in this session lives in `engine/verification/` and is documented in
`docs/verification/RUNTIME_PROOF_MATRIX.md`.

## 7. Non-actions / invariants held

- No commit, push, deploy, branch switch, merge, or tag.
- No file deleted; no `test-artifacts/*` removed, overwritten or staged
  (the pre-existing `docker-image-provenance.json` and the one-by-one sweep
  directories are untouched; this audit only **added** files under a new
  `test-artifacts/runtime-image-audit-2026-10-22/` directory).
- No `docker image rm`, `docker system prune/volume prune/builder prune`,
  or cache cleanup of any kind.
- No registry login, no entitlement key, no license acceptance, no
  auth-bypass attempt against `icr.io`.
- No LLM, model API or generated-content dependency introduced; every
  number in this document comes from a command executed on this host and
  saved under the evidence directory.
