# SystemaOps - Prototype Handoff

Branch: `impl/enterprise-platform` (never merged into `main`). Written 2026-11-11 from the repository state and the
evidence cited below; nothing here is asserted without a commit, a workflow run or a command output behind it.

**Verdict: READY WITH DOCUMENTED LIMITATIONS (prototype).** **Production readiness: NOT READY** (section 9).
The prototype verdict applies to the certified commit `407e601` (section 1), whose three required workflows are green
(section 3); the earlier certified commit `cefa768` is green too.

## 0. Final audit addendum (2026-11-12)

A repository-wide audit of `4c11615` found the certified subset sound and the roadmap far from complete. Read
[FINAL_MASTER_AUDIT_REPORT.md](FINAL_MASTER_AUDIT_REPORT.md), [FINAL_GAP_REGISTER.md](FINAL_GAP_REGISTER.md) and
[FINAL_DOCUMENTATION_COVERAGE.md](FINAL_DOCUMENTATION_COVERAGE.md). Verdict: **READY FOR CONTROLLED PILOT - DOCUMENTED
LIMITATIONS**; production NOT READY. Metrics (judgement-based, weights stated there): certified subset 74/100, full
enterprise roadmap about 45 %, documentation coverage 81 % strict. `4c11615` is docs-only on top of `407e601`; the
corpus certification of record for both is run 43083693133 (45/55 VERIFIED x 4 runtimes, AGREE 45/45). The audit's own
changes are documentation-only, so that code-certification evidence carries over from the ancestor.

## 1. What this is

A deterministic, rule-based COBOL to Java modernization platform with **no LLM anywhere in the pipeline**. It parses a
supported COBOL / VSAM subset, generates a Java project for one of four runtimes (Plain Java, Spring Boot, Quarkus,
Micronaut), runs the original COBOL under GnuCOBOL 3.1.2 and the generated Java in sandbox containers, and compares
stdout, stderr and exit status. Anything it cannot prove is refused by name, not approximated.

* **Certified commit: `407e601`** - all three required workflows succeeded on it (section 3). It contains everything in section 2:
  the CORRESPONDING feature (`8a9f6ac`), the runtime-selection and deployment fixes, and the documentation reconciliation.
  `cefa768` (before CORRESPONDING) is also fully green. `a3bb8cd` and `0d61f2c` have no workflow run of their own; they are
  covered by `407e601`.
* This file records those results, so it is committed afterwards in a documentation-only commit with its own workflow runs;
  read that commit's conclusions in GitHub Actions (the branch head).
* Evidence classes used: `VERIFIED` (GnuCOBOL 3.1.2 differential), SQL via OCESQL + PostgreSQL 14, and
  `SIMULATOR_VERIFIED` (in-repo simulators). **There is no IBM runtime evidence, so no IBM equivalence is claimed.**

## 2. Commits of this stage (oldest first, on top of `f0418a1`)

| Commit | Purpose |
|---|---|
| `442d5f5` | image builds report runner DNS, retry five times, host-network retry |
| `c221fb1` | **the user must choose the runtime**: required API field, no default in service / store, UI starts on "Select a runtime", frontend wait budget and test timeout widened |
| `8fc2999` | `build-production.sh` builds through the retrying `build-image.sh` |
| `dbbadc9` | `HTTPS_BIND` selects the edge interface (default unchanged) |
| `ff4fce2` | apt mirror fallback (first version, `azure.archive.ubuntu.com`) |
| `e6215db` | UI placeholder ellipsis stored as UTF-8 (a Windows edit wrote cp1252 and broke a CI test) |
| `7c5f8f6` | fixes from the first real staging deployment (provenance mount, executable scripts, nginx healthcheck, standalone verify, env LF, e2e script) |
| `1b14dcb` | temporary network-probe workflow (removed in `6c51c61`) |
| `6c51c61` | mirror fallback changed to `mirrors.edge.kernel.org` after the probe showed every `*.ubuntu.com` name failing on the runners |
| `3461769`, `fc419cb` | backup records the deployed tag; WSL path translation only for `/mnt/<drive>`; rollback ignores an inherited `IMAGE_TAG`; a stray CR byte fixed |
| `cefa768` | dependency map regenerated from the committed tree |
| `91648d7`, `cfe2064`, `f61d205` | pushed by another session: remove `docs/CURRENT_DELIVERY_STATUS.md`, `docs/reports/CURRENT_PROJECT_STATE.md` and `docs/reports/EXECUTION_LEDGER.md` as superseded duplicates (kept in git history) |
| `8a9f6ac` | MOVE / ADD / SUBTRACT CORRESPONDING (section 7) |
| `a3bb8cd` | `staging_e2e.py`: checks the approval gate and requires a `VERIFIED` verdict |
| `0d61f2c` | untrack the generated `tsbuildinfo` cache, fix archived README links, correct the RBAC statement in `ENVIRONMENT.md` |

Earlier in the same effort (already green, see `docs/audits/EXECUTION_LEDGER.md`): `db153e8`, `3162d6e`, `8dca85d`,
`f0ac5f4`, `5cacad3` (alternate-key browsing gate and position rules), numeric-edited PIC (`b756493`, `2c2ff0a`,
`eecbaad`, fast-forwarded in as `c8cdc98`), `24cf522` (VSAM capability docs), `14736fa` (NEXT SENTENCE),
`f0418a1` (nested IF / EVALUATE CONTINUE parser fix).

## 3. CI, supply chain and certification (exact commits)

All runs: <https://github.com/Shankar373/Cobol-Java-Transformation/actions>

| Commit | SystemaOps CI | Supply chain | Four-runtime certification |
|---|---|---|---|
| `fc419cb` | run 43049525627: **every job green except the Linux Capability truth gate**, which failed only because `DEPENDENCY_MAP.md` was stale (fixed by `cefa768`) | run 43049525619 success | run 43049525614 success |
| **`407e601` (certified, includes CORRESPONDING)** | run 43071564188: **success, all 10 jobs** | run 43071563913: **success** | run 43071563815: **success, all four runtime jobs** |
| `8a9f6ac` (CORRESPONDING) | run 43071267633: **success, all 10 jobs** | run 43071267644: success | run 43071267672: success |
| `cefa768` (previous certified commit) | run 43061320217: **success, all 10 jobs** | run 43061320347: **success** | run 43061320287: **success, all four runtime jobs** |

Run URLs: `https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/<id>` for 43071564188 (CI), 43071563913 (supply chain),
43071563815 (certification) of `407e601`; 43071267633, 43071267644, 43071267672 (`8a9f6ac`); 43061320217, 43061320347, 43061320287
(`cefa768`); 43049525627, 43049525619, 43049525614 (`fc419cb`, red only on the stale dependency map, fixed by `cefa768`).

Test evidence on `407e601` (run 43071564188, read from the job logs):

* Docker lane (backend + GnuCOBOL / Java oracle suites): **6187 passed**, 1 h 11 min (6176 on `cefa768`; the difference is the CORRESPONDING tests).
* Backend hermetic (Linux): 5575 passed, 612 skipped; (Windows): 5565 passed, 622 skipped.
* Capability truth gate: 1313 passed, 89 skipped, 3 deselected on Linux and on Windows; coverage floor job green; lint and
  the type check ratchet (209 known errors, no new class) green.
* Frontend: 22 files, **192 tests passed** on Linux and Windows, TypeScript clean, production build and bundle-secret guard OK.
* Certification (each of spring_boot, plain_java, quarkus, micronaut, run 43071563815): 55 applications, **45 `VERIFIED`,
  1 `UNAVAILABLE`, 9 with no verdict (refused by name)**; independent verifier **AGREE 45/45**; `CERTIFIED`.
* GnuCOBOL differential sweeps run during this effort: alternate-key browsing 18 seeds / 450 programs / 0 mismatches
  (`docs/audits/evidence/alternate_key_browse_sweep_2026-11-11.json`); NEXT SENTENCE 100 programs / 0 mismatches; CONTINUE
  fix 60 programs / 0 mismatches; CORRESPONDING 7 seeds / 140 programs / 0 mismatches
  (`docs/audits/evidence/corresponding_sweep_2026-11-11.json`).
* Local checks before the CORRESPONDING commit: hermetic transformation + capability + CORRESPONDING suites 2308 passed,
  55 skipped (Docker-only); ruff clean; type ratchet clean.

CI infrastructure note: runs of `f0418a1`, `442d5f5`, `ff4fce2` failed because the GitHub runner resolver
(168.63.129.16) could not resolve `archive.ubuntu.com`, `security.ubuntu.com` or `azure.archive.ubuntu.com` during the
GnuCOBOL image build. A probe (run 43045798482) showed `mirrors.edge.kernel.org` resolves and serves the archive; the build
now falls back to it from the second attempt, only when `archive.ubuntu.com` does not resolve. Pins are unchanged
(`ubuntu:22.04@sha256:5ec03bb3...`, `gnucobol3=3.1.2-5`, smoke test `cobc (GnuCOBOL) 3.1.2.0`); default and mirror builds
were compared and have the identical 144-package set.

## 4. Runtime selection (explicit, no default, no substitution)

* `POST /applications` requires `target_runtime` in `plain_java | spring_boot | quarkus | micronaut`; absent or empty is
  422, unknown or uncertified (for example `jakarta_ee`) is rejected, and the value is stored and returned unchanged.
* The service parameter and the stored record have no default; the UI starts on "Select a runtime", Start is disabled until
  a runtime is chosen, and a choice the server stops offering is cleared, never replaced.
* Pinned by `tests/test_runtime_selection.py` (rejects, stores unchanged, and generation produces the selected runtime's
  project and no other) and by the frontend tests.
* Staging proof: all four runtimes ran the whole workflow over HTTPS with a `VERIFIED` verdict, and each downloaded project
  contained only its own runtime (`pom.xml` markers: spring-boot / quarkus / micronaut; Plain Java has none).
* Existing rows created before the column existed keep `spring_boot` (migration default); this is historical data, not a
  fallback for new requests.

## 5. Staging deployment (real, isolated, localhost only)

Deployed from an exact LF export of `7c5f8f6` inside Ubuntu 24.04 (WSL2, Docker 29.8.2), production Compose, edge bound to
`127.0.0.1:8443`, TLS (self-signed, SAN `localhost` / `127.0.0.1`, trusted by path, never `-k`), a 64-character
random token, `CONTROL_PLANE_ENV=production`. Recipe: `docs/deployment/PRODUCTION.md` (section "Staging / evaluation").

| Check | Result |
|---|---|
| Compose refuses to render without token / oracle digest / `DOCKER_GID` | yes (fail closed) |
| `verify-production.sh` | **20 / 20 PASS**: containers healthy, TLS `/health` and `/ready`, 401 without token, provenance mounted, candidate adapter AVAILABLE, sandbox `--network none`, staging writable as uid 10001, frontend routing |
| Listener | `127.0.0.1:8443` only; both containers `healthy` |
| `scripts/deploy/staging_e2e.py` per runtime | auth (no token 401, wrong token 401), create without runtime 422, uncertified 400, ingest, modernize, **`VERIFIED`**, download 409 until approval, approve, download 200, project matches the chosen runtime: quarkus, spring_boot, micronaut, plain_java all `E2E: OK` |
| Restart | API container restarted (start time changed), ready again, 10 / 10 applications retained |
| Backup (`QUIESCE=1`) + self-verification | OK; records `api-image.json` (deployed tag) and the provenance file |
| Restore | marker record created after the backup is gone after the restore (11 to 10); post-restore verify OK |
| Rollback / roll forward | API switched `stg-7c5f8f6` to `stg-ff4fce2` and back, verify OK each time, data intact |

Defects this drill found and fixed (each pinned by `tests/test_deploy_staging_contracts.py`): the Java candidate adapter was
always `UNAVAILABLE` in the shipped topology because the image-provenance record never reached the container (every run ended
`ERROR`); deploy / backup / CI shell scripts were committed non-executable; the nginx healthcheck was always unhealthy;
`verify-production.sh` could not render compose standalone; backup recorded no release identity for a tagged release; `wslpath`
translation broke backup / restore against a Linux daemon; an exported `IMAGE_TAG` made rollback a silent no-op.

Not verified: the staging stack ran `7c5f8f6`, three script fixes (`backup.sh`, `restore.sh`, `rollback.sh`) were copied into
it from `3461769` / `fc419cb` for the drills; no staging redeploy of `cefa768` was done. No public exposure was made.

## 6. Supported COBOL / VSAM subset (summary; authoritative: `docs/CAPABILITY_MATRIX.md`, `docs/SEMANTIC_PROOF_MATRIX.md`, `docs/audits/CAPABILITY_STATUS.md`)

Proven against GnuCOBOL 3.1.2 (seeded fuzz and fixture corpora): sequential / indexed / relative file I-O with the file-status
surface; indexed alternate keys (random access; **browsing certified for one shape only**: ACCESS DYNAMIC, two alternate keys
- one WITH DUPLICATES, one unique -, PIC X(2) fields, FILE STATUS only, OPEN OUTPUT / I-O, START `= > >=` on an alternate key and
`= > >= <` on the primary); numeric-edited PICTURE; qualified names; intrinsic functions; EVALUATE ALSO; GO TO DEPENDING ON;
SEARCH / SET INDEX; STRING / UNSTRING / INSPECT (alphanumeric operands); SIZE ERROR; NEXT SENTENCE as the last statement of a
branch of a single `IF ... ELSE` sentence; CALL and copybooks; binary and packed fields. SQL via OCESQL + PostgreSQL 14 (not DB2).
JCL, IMS, MQ and CICS exist as simulators or runners with limited coverage and are `SIMULATOR_VERIFIED` at most.

## 7. Known limitations (refused by name, not silently approximated)

* **No IBM evidence.** GnuCOBOL 3.1.2 is the oracle; behavior that differs from IBM Enterprise COBOL is not detected.
* Alternate-key browsing outside the one shape above, ESDS and RRDS, EBCDIC data and collation, INSPECT with data-name operands,
  SORT INPUT / OUTPUT PROCEDURE with RELEASE / RETURN, OCCURS DEPENDING ON, NEXT SENTENCE in nested / EVALUATE / END-IF shapes.
* DB2 is only checked through PostgreSQL; CICS, IMS and MQ are simulators; Levels 2 to 4 of the roadmap are not done.
* **CORRESPONDING (MOVE / ADD / SUBTRACT)** is committed as `8a9f6ac`, separately from this documentation. Supported and
  proven: a single-line statement between two groups, pairing by name and qualification in source order, nested same-name
  subgroups, alphanumeric / unsigned / signed / decimal items (140 programs, 7 seeds including 3 held out, 0 mismatches). Refused by
  name: OCCURS / REDEFINES, ROUNDED / SIZE ERROR, wrapped or nested statements, non-group operands, ambiguous names. Unverified:
  COMP / COMP-3 / edited members, more than three levels or groups, IBM behaviour. CI, supply chain and certification are green on
  `8a9f6ac` and `407e601`. The original uncommitted work is still backed up on branch
  `backup/corresponding-wip-2026-11-10` (`48e4226`).
* Real customer programs have not been tested; the corpus is the repository's own fixtures.
* Local keyed-file Docker suites were never run on the development machine (memory); the CI Docker lane (6176 passed) is the evidence.
* Frontend: no browser-level (end to end) test; the UI was exercised through component tests and the API through `staging_e2e.py`.

## 8. Open pull requests - audit of all 22 (nothing was merged or closed)

Method: `gh pr list`, `gh pr view` (state, checks), `gh pr diff`; ancestry with `git merge-base --is-ancestor` against
`impl/enterprise-platform`; Dependabot patches tested with `git apply --check` on `cefa768`; the tests of #1, #3 and #6 run
against the current code. All 18 Dependabot PRs target `main`, which this branch has diverged from; none has a complete green
CI (most runs were cancelled by newer pushes). Branches survive a PR close, so closing loses no commit.

| PR | Base <- head | What it is | Evidence | Recommendation |
|---|---|---|---|---|
| #8 | fix/false-success-baseline <- feat/phase2-e2e-validation | Phase 2 end-to-end validation (52 files) | head `6072460` **is an ancestor** of `impl/enterprise-platform`; CI green | **Close** (fully included); needs owner OK |
| #6 | codex/universal-core <- codex/arithmetic-overflow-fix | `Math.multiplyExact` for COBOL multiply | DIRTY; its CI failed; the PR's own test file has a syntax error (`\n` inside an assertion); current code follows GnuCOBOL size-error / truncation semantics (differentially proven) which a throwing multiply would contradict | **Close** as superseded and incorrect for COBOL semantics |
| #1 | codex/remote-docker-ci <- codex/universal-hardening | readiness gate (`completeness_gate.py`) + discovery diagnostics | CI failed (old base); discovery diagnostics already exist (`discovery_errors`); the gate is a self-contained module whose 5 tests **pass against the current code** but it is not wired in | **Keep open / extract**: only the gate module and its test are unique; decide whether to wire it in (owner) |
| #3 | main <- codex/p0-validation-check | "P0 validation completion candidate": 212 commits, 96 files, +16956/-1856 | DIRTY vs `main`; its CI green on its own base; 212 commits not in this branch; of its 15 files absent here, the 12 test files fail against the current code because they target APIs that do not exist here (`discovery_complete`, `compiler_matches_declared`, `BLOB_FORMAT`, `UploadLimitError`, `source_name=`, `partial_constructs`) or expect UNSTRING to be UNSUPPORTED (now implemented and proven) | **Keep open, do not merge**: a divergent parallel lineage; the intents (fail-closed provenance, oracle identity, discovery completeness, safe persistence, upload limits) are covered here by other mechanisms (oracle digest pin, `CONTROL_PLANE_MAX_*` limits, capability gates) but **equivalence is not proven**; owner review needed before closing |
| #10 | main <- ubuntu 26.04 | base image of `Dockerfile.gnucobol` | applies; CI 4 failures | **Close**: would break the oracle pin (`gnucobol3=3.1.2-5` exists for jammy) |
| #11 | main <- python 3.15-slim | base image of `Dockerfile.production` | applies; CI 2 failures | **Close**: changes the digest-pinned runtime base to an unvalidated Python version; revisit only as a deliberate, tested upgrade |
| #12 | main <- maven temurin 26 | `Dockerfile.maven-offline` | applies | **Close**: changes the pinned Java runtime (21); runtime pins are not to be changed without approval |
| #13 #14 #19 #25 | main <- uvicorn / starlette / pydantic / fastapi | raise lower bounds in `requirements.txt` | apply; no usable CI | **Defer**: dependencies are hash-locked in `requirements*.lock`; bump together in one re-locked PR against this branch with full CI and supply-chain scan, then close these |
| #20 #22 | main <- pyyaml / httpx | `requirements-dev.txt` bounds | apply; no usable CI | **Defer**: same single re-lock PR |
| #15 #16 #18 #26 | main <- setup-python / setup-node / checkout / upload-artifact | GitHub Actions bumps | **conflict** with this branch's workflows | **Close and let Dependabot recreate** against this branch once it is the base (or one manual PR); do not merge into `main` |
| #17 | main <- typescript 7.0.2 | major frontend bump | **conflicts** (lockfile) | **Defer**: major version; evaluate separately with the frontend suite |
| #21 #23 | main <- vitest / jsdom 30 | frontend test tooling | **conflict** (lockfile) | **Defer**: re-test with the widened timeouts in `frontend/vite.config.ts`; jsdom 30 is a major bump |
| #24 #27 | main <- plugin-react 6 / react | frontend runtime / plugin | apply; no usable CI | **Defer**: validate together with the frontend lockfile on this branch |

Preservation: the only unique, unreviewed content is #1's gate module and #3's lineage; both stay reachable (open PR and
branch). Nothing else in the 22 carries work that is missing from this branch.

## 9. Production readiness: NOT READY (reasons)

* Single host, single replica, SQLite, in-process workers: no HA, no horizontal scale (documented in `docs/deployment/PRODUCTION.md`).
* Sandbox execution needs the Docker socket inside the API container (accepted risk, `docs/security/PRODUCTION_SECURITY.md`).
* Authentication is one shared bearer token by default; an optional role mode (`CONTROL_PLANE_ROLE_TOKENS`: viewer / operator /
  approver, `api/rbac.py`) exists, but the approver name on an approval is caller-supplied text, not a verified identity, the UI
  has no login, and there is no OIDC (owner decision).
* TLS in staging is self-signed; a real certificate, DNS name and renewal are not provisioned. No public deployment was made.
* Secrets management, log shipping / alerting, scheduled backups (the script exists, no scheduler), disk and retention
  policy, capacity limits under load, and a security review of the staged topology are not done.
* Coverage is a subset proven against GnuCOBOL only; see section 7.

## 10. Owner decisions needed

1. Approve (or refuse) merging `impl/enterprise-platform` into `main`; it has **not** been done.
2. CORRESPONDING: run its sweep and commit it, or keep it as an unfinished backup.
3. PR dispositions in section 8, in particular #3 (keep or close) and #1 (wire in the gate or drop).
4. Provide a real certificate / DNS / secrets store if a non-local deployment is wanted.
5. Decide whether IBM runtime evidence will be obtained; until then no IBM equivalence is claimed.
6. Whether to broaden the narrow alternate-key / NEXT SENTENCE shapes (needs wider generators and sweeps) before Levels 2 to 4.

## 11. Setup, build and test (commands verified in this effort)

Prerequisites: Python 3.11, Node 22 + npm, Docker (the GnuCOBOL oracle and the Java candidates run in containers), Linux or WSL2 for
the production Compose stack.

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python -m uvicorn api.app:app --port 8000                       # backend
(cd frontend && npm ci && npm run dev)                          # UI at http://localhost:5173/app/
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .        # GnuCOBOL 3.1.2 oracle image
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .
python scripts/record_docker_image_provenance.py                # after rebuilding the Maven image
python -m pytest -q                                             # hermetic backend suite
RUN_DOCKER_TESTS=1 python -m pytest -q tests/integration        # Docker / oracle suites (needs both images)
(cd frontend && npm test && npm run lint && npm run build)      # frontend tests, tsc, production build
ruff check . && python tools/mypy_gate.py && python tools/dependency_map.py --check   # lint, type ratchet, map
```

Corpus certification (four runtimes) runs in GitHub Actions for commits tagged `[certify]` and on manual dispatch of
`certification.yml`; deployment: `docs/deployment/PRODUCTION.md`.

## 12. Next recommended engineering actions

1. Read the conclusions of the workflows on the branch head (the documentation commit that records these results) in GitHub Actions.
2. Owner review of the PR audit (section 8), then close #8, #6, #10, #11, #12 and the four Actions bumps; fold the Python and frontend
   bumps into one re-locked, fully tested dependency PR against this branch; decide #1 and #3.
3. Remaining Level 1 work: INSPECT with data-name operands, SORT procedures with RELEASE / RETURN, OCCURS DEPENDING ON, EBCDIC,
   ESDS / RRDS; widen the alternate-key and NEXT SENTENCE shapes behind new sweeps.
4. Production blockers in section 9, starting with a real certificate and a decision on identity (OIDC) and secrets storage.
5. Only then Levels 2 to 4 (JCL / DB2 depth, CICS / IMS / MQ, runtime-dependency elimination).
