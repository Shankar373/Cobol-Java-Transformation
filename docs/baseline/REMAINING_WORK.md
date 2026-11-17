# Remaining work (2026-11-18)

Ordered by dependency. Nothing below has been started in this baseline, except where noted.

## A. Decide before more building

1. **Which branch is the base.** Three lines exist: PR #28 (`stage1/vsam-completion`, open, unmerged), the certified Stage 1 commit `b2455cedd87c3611f8b4586a9189156f0fd18c21`
   on `codex/stage1-alt-key-browsing`, and the continuation branch `codex/enterprise-phases-continuation` (which contains the certified commit). The owner decides what PR #28 becomes.
2. **Docker CLI version in the production image** (security finding, see `SECURITY_STATUS.md`) and whether Trivy should gate the build.
3. **LGPL licence of `psycopg`.**
4. **Whether to pursue IBM evidence** (free route: IBM Z Xplore, owner registers; pack in `docs/vsam/IBM_EVIDENCE_REQUEST_PACK.md`).

## B. Stage 2: JCL and Db2 (not started in the baseline)

- JCL: land the statement and parameter policy (local branch `codex/stage2-jcl-policy-wip`, commit `9d8fab1`: parser keeps unmodelled statements and DD keywords, a policy table gives each
  an explicit treatment, `plan_job` refuses or notes them; 212 JCL tests passed with it; it needs its own negative tests and the `PARM` decision), then `IF/THEN/ELSE` evaluation,
  durable per-step records, `RESTART`, abnormal-end dispositions.
- Db2: SQLCODE/SQLSTATE model, indicator variables, cursors, transactions, `COMP-3` and decimal mapping, each with OCESQL differential tests; keep `WHENEVER` and dynamic SQL refused.
- An end-to-end COBOL + JCL + `EXEC SQL` fixture with reconciliation and an evidence manifest.

## C. Enterprise platform

- Phase 1: S3-compatible `ObjectStore` adapter (MinIO service container in CI), cross-process worker tests on PostgreSQL, API setting for external workers, quotas, retention, backup and restore tests.
- Phase 2: GitHub ingestion endpoint, durable job, snapshot persistence, shared rate-limit state, a large-repository test.
- Phase 3: multipart upload sessions with resume, whole-archive checksum, expiry cleanup, API, frontend flow, a multi-gigabyte memory measurement.
- Phase 4: incremental inventory and dependency graph (COBOL, copybooks, JCL, datasets, SQL, CICS/IMS/MQ references) with unknown and unsupported states.
- Phase 6: bounded-memory writes and `OUTPUT`/`I-O`/`EXTEND` in the Java runtime, index consistency, locking, crash recovery, EOF versus I/O error.
- Phase 7: real authentication and authorization, tenant isolation, rate limits, audit trail, metrics, cancellation, backup and restore, retention, threat model, runbooks.

## D. Later stages

Stage 3 (CICS, IMS, MQ) and Stage 4 (mainframe dependency elimination) need Stage 2 first and, for any IBM claim, external evidence.

## E. Housekeeping

- Decide whether a fresh four-runtime certification should run on the final baseline commit (about an hour per runtime on the free allowance).
- Replace `httpx` with the successor the test client asks for when the dependency policy allows.
