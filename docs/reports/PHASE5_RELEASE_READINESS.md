# Phase 5 — Release Readiness

Date 2026-11-02, branch `feat/phase3-coverage`, after Phase 4 acceptance
(`32cf586`). Companion to `PHASE5_FINAL_CERTIFICATION.md` (what is proven).
This report answers: can a release be built, deployed, verified and rolled
back from this repository, and what still stands between it and production?

## Verdict

**Releasable as a controlled pilot of a certified COBOL subset — not
certified for production use.** The release mechanics below work and are
tested; the remaining gaps are owner decisions, listed with their owner.
Universal COBOL compatibility is not claimed.

## 1. What a release is

| Artifact | Built by | Verified by |
|---|---|---|
| API image `systemaops-api:<tag>` | `scripts/deploy/build-production.sh <tag>` | fail-closed start without a token; `/ready`; hash-verified Python install; Trivy report (CI `image-scan`) |
| Oracle image `gnucobol-ocesql` | same script | evidence records its identity per run; Trivy report |
| Offline Maven image `maven-offline-springboot` | same script | provenance record (`scripts/record_docker_image_provenance.py`); strict Maven checksums; Trivy report |
| Java runtime `eclipse-temurin:21-jdk` | pulled by digest | digest enforced in code |
| Frontend `frontend/dist` | `npm ci && npm run build` (bundle-secret guard) | CI `frontend` job; `verify-production.sh` checks it is present |
| SBOMs (Python, npm), audit reports, dependency manifest | CI `supply-chain.yml` | pip-audit / npm audit gate CI |

The release manifest now records `productVersion` (`engine.__version__`,
equal to the API and frontend version — test-enforced) and `imageTag`.

## 2. Release process (corrected in Phase 5)

`docs/deployment/PRODUCTION.md`: build the frontend, build the images under a
**new tag per release** (rebuilding a reused tag destroyed the only rollback
target), set `IMAGE_TAG`, `start-production.sh` (preflights token, TLS,
`DOCKER_GID`, staging, compose render), `verify-production.sh`,
`rollback.sh <previous tag>`. Every script that calls compose resolves
`DOCKER_GID` through `scripts/deploy/lib-docker-gid.sh` (Phase 4 made it
required; rollback and restore had not been updated — fixed, guard test).

## 3. CI on every push

`ci.yml`: capability-truth gate (≈85 test files, pytest only), ingestion
diagnostics, backend + GnuCOBOL/Java Docker suite (builds the oracle and
Maven images, records provenance), frontend tests and build.
`supply-chain.yml`: pip-audit + SBOM, npm audit + SBOM, release manifest,
Trivy image + Java-tree scan (report-only, stated reason).
`certification.yml` (new, dispatched per release candidate): the whole
corpus on all four runtimes through the API plus the independent re-check,
failing on any verdict change against the accepted evidence.

Not exercised by CI (operator drills): a full compose up with TLS, the
deploy/rollback/restore scripts end to end (statically checked: LF, shebang,
`bash -n`, compose entry points resolve `DOCKER_GID`), frontend end-to-end
tests, pushing images to a registry.

## 4. Gaps before production (owner decisions)

| Gap | Why it blocks production | Owner action |
|---|---|---|
| One shared API token; no user identity, roles or tenancy; approver is free text | anyone holding the token can approve and export | choose an identity provider and role model (BL-122 / D-9) |
| No artifact or image signing / provenance attestation | releases cannot be verified by a third party | key custody decision (L3_7 decision record) |
| ~~No project LICENSE~~ | resolved 2026-11-03 | Apache-2.0 (`LICENSE`, `NOTICE`) |
| Generated frameworks past support (Spring Boot 3.2.5, Quarkus 3.15.1, Micronaut 4.6.3); image OS/package findings (first Trivy run) | generated applications and images carry known CVEs | approve upgrades — generator, precache, full corpus re-proof (J1, J3); image refresh changes evidence identities (J2) |
| Docker socket in the API container | root-equivalent on the host | socket proxy or host-run API (accepted risk today) |
| No retention/deletion, encryption at rest, backup encryption | customer source and generated code accumulate unencrypted | policy and storage decision |
| No metrics/alerting/error tracking | failures are visible only in logs | choose a stack |
| No version/tag scheme, CHANGELOG or registry | releases are not addressable | choose `vX.Y.Z` tags, use them as `IMAGE_TAG` |
| Single-node SQLite, in-process jobs, no cancellation (BL-115) | no HA, a crashed run is reconciled, not resumed | architecture decision |

## 5. Phase 5 release fixes

- `DOCKER_GID` resolution shared by start, verify, rollback and restore.
- PRODUCTION.md: frontend build step, unique tag per release; compose header
  points to the preflighted start script.
- BACKUP_RECOVERY.md schema ceiling (≤ 8); rate-limit mentions updated in
  ARCHITECTURE, SUBMISSION_GUIDE, PRODUCTION; `--require-hashes` in every
  install instruction; broken links in `contracts/*.md`; stray heredoc
  markers; historical banners on the two 2026-10-30/31 readiness verdicts and a
  superseded-items note on the WS4 gate; current-truth banners on the status
  documents and a new `opencode.md` block.
- Release manifest: `productVersion`, `imageTag`; version consistency test.
