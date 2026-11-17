# Known limitations (2026-11-18)

Read with `FEATURE_STATUS.md`. None of these is hidden by a passing test.

## What is not proven

- **No IBM evidence.** Every equivalence claim is against GnuCOBOL 3.1.2 for recorded inputs. Nothing is `IBM_RUNTIME_VERIFIED`; no IBM Enterprise COBOL,
  z/OS, JES, IDCAMS, VSAM, Db2, CICS, IMS or MQ was run. The Linux s390x image is not z/OS.
- **Certification is self-attested.** The `exact-run-certification-summary` artifact is produced by the same workflow that runs the jobs; it is not signed.
  Corpus certification runs only on manual dispatch or a `[certify]` commit, so most commits (including this baseline's) carry no fresh four-runtime
  certification; the certified SHA is `b2455cedd87c3611f8b4586a9189156f0fd18c21` for the Stage 1 subset.
- **Quarkus and Micronaut** are certified in command mode only; **Jakarta EE** is not certified.

## Functional limits

- VSAM migration: key at offset 0, no duplicate primary keys, no binary fields, single-byte code pages, KSDS alternate keys only for fixed records
  (up to three, DISPLAY leaf, unique-key check bounded to 5,000,000 records). RRDS equivalence with IBM, ESDS RBA and IDCAMS catalog commands are blocked.
- The generated Java runtime keeps small keyed files, and every `OUTPUT`, `I-O` and `EXTEND` open, in memory. Sequential `READ NEXT` on RELATIVE files is unsupported.
- Refused layouts: `OCCURS DEPENDING ON`, `SYNCHRONIZED`, unselected `REDEFINES`, `COMP-1`/`COMP-2` migration.
- JCL: not JES; no `RESTART`, no `IF/THEN/ELSE` evaluation, `PARM` not passed to programs, and the parser drops several statements and DD keywords
  without a diagnostic (fix pending on the unmerged branch `codex/stage2-jcl-policy-wip`).
- Db2: portable SQL subset only; no SQLCODE/SQLSTATE model, indicators, cursors, `WHENEVER`, dynamic SQL or Db2 runtime.
- CICS, IMS and MQ: simulators only, blocked in the product.
- Source ingestion: the GitHub snapshot core (`enterprise/ingest/`) remains a library. Estate discovery (`enterprise/discovery/`) has its own ZIP, local Git and remote
  https Git ingestion with API and UI, but no resumable upload sessions, no private-repository support through the API, and no external worker queue. Discovery is lexical;
  its limits are listed in `docs/discovery/DISCOVERY.md`.
- Durable jobs: PostgreSQL, leases and recovery exist for VSAM migration jobs only; the main run store is SQLite with in-process threads. No S3 adapter, no
  Redis/Celery (the database is the queue and workers poll), no retention or cleanup, no backup tests.

## Operational limits

- Shared bearer-token authentication, no tenant isolation, no rate limiting, no audit trail for the new routes; the production compose file mounts the Docker socket.
- Trivy findings on the production image are not gating (see `SECURITY_STATUS.md`).
- A single timing-sensitive test, `tests/test_certification_contract.py::TestContractReachesEngine::test_default_contract_drives_pipeline_config`, failed once
  in a local sliced run under heavy memory pressure and passed in three reruns (alone, with its neighbours, and in the full slice); it polls a background run for
  up to 30 seconds. It is a suspected flake, not a proven one, and it has not failed in CI.
- Starlette's `TestClient` warns that `httpx` is deprecated in favour of `httpx2`; harmless today, a future dependency task.
- Local development on Windows: Git-ignored leftovers (`tmp/`, `%TEMP%/`) from earlier sessions are present and untouched.
