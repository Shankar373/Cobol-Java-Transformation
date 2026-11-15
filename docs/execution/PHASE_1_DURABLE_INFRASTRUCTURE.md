# Enterprise Phase 1: durable infrastructure (status 2026-11-15)

Branch `codex/enterprise-phases-continuation`. Status: **PARTIALLY COMPLETE**. Nothing below is certified; CI evidence is recorded
at the end only for SHAs that have a finished run.

## Built and tested

| Item | Evidence |
|---|---|
| Database layer for SQLite and PostgreSQL (`enterprise/db.py`), rows as dicts, `?` placeholders on both | `tests/enterprise/test_database.py` (20 tests on each backend) |
| Versioned migrations with rollback (`enterprise/migrations/NNNN_name.up.sql` / `.down.sql`, `schema_migrations`, advisory lock on PostgreSQL, a failed migration records nothing, both files required) | same file; run against PostgreSQL 16 |
| `BIGINT` counters (a 10 GiB job overflows a 32-bit integer) | `test_big_byte_counters_do_not_overflow` |
| Atomic job state transitions: compare-and-set on the state read; a stale writer gets `WrongState` and writes nothing | stale-read and two-thread race tests; exactly one winner |
| Idempotent submission (same key and request returns the same job; different request is a conflict) | existing API tests plus `test_the_job_service_runs_on_this_database` |
| Leased workers (`claim_next`, `heartbeat`, `process`, `VsamWorker`, `python -m enterprise.vsam.worker`): one conditional UPDATE decides the owner, so racing workers claim a job exactly once | `tests/enterprise/test_vsam_worker.py`: 6 racing threads, one winner |
| Worker crash recovery: a dead worker's lease expires, another worker resumes from the checkpoint and produces the output with the same SHA-256 as an uninterrupted run | `test_a_crashed_worker_is_recovered_from_its_checkpoint` |
| Bounded retries: a job claimed more than `1 + max_retries` times fails with `RETRIES_EXHAUSTED` | `test_a_job_that_never_finishes_is_failed_not_retried_forever` |
| Lost lease: the worker stops at its next checkpoint and keeps the partial output; it never publishes | `test_a_worker_that_loses_its_lease_...` |
| A separate OS process worker finishes a job queued by another process | `test_a_separate_worker_process_...` (SQLite file only) |
| A job is never marked successful after partial execution: SUCCEEDED needs VALIDATING, PUBLISHING and full evidence (Phase 0 state machine) | `tests/enterprise/test_phase0_jobs_quotas_contracts.py` |
| CI runs a free PostgreSQL service container (pinned by digest) in the Docker lane, and a no-skip gate fails the job if the database or worker tests were skipped | `.github/workflows/ci.yml` |

Local runs: the 34 database and worker tests pass on SQLite and on `postgres:16-alpine` in Docker; the cross-process test passes on
SQLite.

## Not built

- **Redis/Celery.** Queueing is the database itself (leases), not a broker. This is a deliberate substitution: it needs no extra
  service, is testable here and gives the same recovery properties for one database, but it is not Redis/Celery and has no push
  wake-up (workers poll). Adding Celery needs new hash-pinned dependencies and a Redis service container.
- **S3-compatible `ObjectStore` adapter.** Not written. It cannot be tested locally (anonymous Docker pulls of MinIO are refused
  here); a MinIO container started in CI is the free route, and each change would cost a full CI cycle.
- **Cross-process worker test on PostgreSQL** (the in-process race and recovery tests do run on PostgreSQL).
- **Storage quotas and retention cleanup** for job directories; **multipart resume tests through the API**.
- The API process still defaults to inline workers; configuring it for external workers (`inline_workers=False`) is not wired to an
  environment setting yet.

## Licence note for the owner

`psycopg` and `psycopg-binary` are LGPL-3.0-only (`docs/THIRD_PARTY_NOTICES.md`). Using an LGPL library unmodified from Python is
normally acceptable, but confirm it against your distribution policy.
