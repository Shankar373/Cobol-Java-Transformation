# Enterprise Ingestion Architecture

Status: Phase 0 design. Code lives in `enterprise/`. Deterministic and rule-based; no LLM.

## Flow
Control plane (FastAPI + React) holds job and application metadata in PostgreSQL.
Acquisition (GitHub fetch or multipart ZIP) writes an immutable source snapshot to
object storage. Workers (Celery on Redis) run inventory, discovery, VSAM migration,
Java generation, validation and evidence publication. The API never performs large
ingestion or transformation work synchronously.

## Decisions (see ADR-0012)
| Topic | Choice |
|---|---|
| Metadata store | PostgreSQL in enterprise deployments; SQLite remains the local development store behind the same store interface |
| Object storage | Provider-neutral interface; local filesystem adapter and S3-compatible adapter |
| Queue | Redis + Celery workers |
| Git provider | GitHub only |
| Large datasets | Streaming, bounded memory |

## Service boundaries
- `enterprise/jobs.py`: job state machine. SUCCEEDED only via PUBLISHING with complete evidence.
- `enterprise/contracts.py`: versioned immutable contracts.
- `enterprise/quotas.py`: per-workflow limits from the environment.
- `enterprise/storage/`: object storage interface and adapters (Phase 1).
- Workers own heavy work; the API only creates jobs, reports state and authorizes downloads.

## Reliability rules
Idempotency keys on job creation. Bounded retries with backoff. Worker leases with
stale-job recovery. A job is never SUCCEEDED while output is partial.

## Current limits being replaced
The existing 50 MiB request / 10 MiB file / 50 MiB ZIP limits (`api/app.py`,
`api/ingestion.py`) stay for the in-memory legacy upload path. The new workflows use
`enterprise/quotas.py`; the figures there are engineering defaults, not approved
production quotas.
