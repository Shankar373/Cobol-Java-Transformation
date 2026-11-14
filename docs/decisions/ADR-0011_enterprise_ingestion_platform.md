# ADR-0011 Enterprise Ingestion Platform

Status: accepted for implementation (autonomous run, branch `codex/autonomous-stage1-enterprise-completion`).

## Context
The control plane uses SQLite, in-process threads and local files. ZIP ingestion holds
the archive in memory (`api/ingestion.py`). There is no VSAM migration engine, no
GitHub ingestion and no streaming path.

## Decision
- New package `enterprise/`, separate from `api/` and `engine/`, so the existing certified engine is untouched.
- PostgreSQL for enterprise metadata; SQLite stays for local development behind one store interface. No two production sources of truth.
- Provider-neutral object storage with local and S3-compatible adapters.
- Redis + Celery for workers, with idempotency keys, bounded retries and leases.
- GitHub is the only Git provider.
- Per-workflow quotas replace one global limit for the new workflows.
- No LLM use. Modernization stays deterministic and rule-based.

## Consequences
- New dependencies (S3 client, Celery, Redis client, PostgreSQL driver) must be hash-locked like the existing requirements.
- Redis, PostgreSQL and S3 integration cannot be verified locally (no servers installed); those suites run in Docker or CI and stay uncertified until they do.
- The legacy upload path keeps its current limits.
