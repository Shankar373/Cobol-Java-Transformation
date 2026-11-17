# Architecture (as built, 2026-11-18)

This describes what exists in the repository at the baseline commit, read from the code layout and tests, not from plans.
The product is a deterministic, rule-based COBOL-to-Java modernization pipeline. It contains no LLM and no probabilistic step.

## Components

| Area | Path | What it is |
|---|---|---|
| Control plane API | `api/` | FastAPI service: applications, runs, ingestion of uploaded sources, validation summaries, VSAM migration routes (`api/vsam_migration.py`, the synchronous in-memory Stage 1 route, `api/vsam_routes.py` streaming route), shared bearer-token RBAC, body-size limiting middleware. SQLite run store. |
| Modernization engine | `engine/` | COBOL parser and IR (`engine/transformation/`), capability gates, Java generators for plain Java, Spring Boot, Quarkus, Micronaut and Jakarta EE (the last not certified), runtime support templates (`CobolFileIo`, SQL support), JCL lane (`engine/jcl/`, orchestrator that renders a Java job launcher), SQL lane (`engine/sql/`, bounded portable `EXEC SQL` subset), VSAM model and migration (`engine/vsam/`), simulators for CICS, IMS and MQ (`engine/simulators/`, `engine/cics/`; blocked in the product). |
| Enterprise platform | `enterprise/` | Versioned contracts, job state machine, quotas, database layer for SQLite and PostgreSQL with migrations, leased workers, streaming VSAM migration (`enterprise/vsam/`), safe ZIP extraction, source manifests and GitHub ingestion core (`enterprise/ingest/`), `ObjectStore` interface with a local store (`enterprise/storage/`). |
| Frontend | `frontend/` | React + TypeScript (Vite, Vitest). Includes the VSAM migration page. |
| Oracles and images | `docker/`, `Dockerfile.*` | GnuCOBOL 3.1.2 reference images (plus an s390x image and an OCESQL + PostgreSQL image), a project Maven image, the production API image. |
| CI | `.github/workflows/` | `ci.yml` (10 jobs), `supply-chain.yml` (SBOM and scans), `certification.yml` (four-runtime corpus certification; manual dispatch or a `[certify]` commit marker). |
| Tools and docs | `tools/`, `scripts/`, `docs/` | dependency map generator, notice generator, benchmark scripts, evidence and decision records. |

## Main flows

1. **Modernization run.** Uploaded COBOL (and copybooks) -> discovery and inventory -> parser and IR -> capability analysis (SUPPORTED, PARTIAL,
   UNSUPPORTED, UNAVAILABLE, UNKNOWN; UNKNOWN is never treated as supported) -> Java generation for the chosen runtime -> compile -> run the
   COBOL under GnuCOBOL and the Java in Docker -> compare stdout, FILE STATUS, exit code and files -> validation summary with a verdict.
2. **JCL job.** JCL members -> expansion of procedures and symbolics -> plan (refusals by name) -> generated `Job<Name>Runner` that runs the steps
   with COND, dispositions, GDGs and a few native utilities. It is not JES.
3. **VSAM dataset migration (certified subset).** Client uploads a logical export and its manifest -> API stores it as a stream -> a worker reads it
   in bounded chunks, validates keys, order and collation, writes the image the generated Java runtime reads (`.idx`, `.rel`, sequential), hashes
   input and output incrementally, checkpoints, and publishes only after count, size and SHA-256 all match -> download re-hashes the artifact.
4. **Durable jobs.** A job is a row (SQLite or PostgreSQL) moved by compare-and-set transitions; workers lease jobs, extend leases with a heartbeat, and
   a job whose worker died is picked up again from its checkpoint, at most `1 + max_retries` times.
5. **Estate discovery.** ZIP upload or https Git URL -> safe staging -> immutable sealed checkpoint pinned to the exact commit -> COBOL, copybook, JCL, BMS, SQL, build
   and runtime scanning from the checkpoint -> dependency graph with unresolved tracking -> deterministic report and completeness gate (`enterprise/discovery/`, `api/discovery_routes.py`,
   `docs/discovery/DISCOVERY.md`). No Java transformation is triggered.
6. **GitHub ingestion core.** GitHub URL (strict pattern) -> metadata -> branch/tag/SHA resolved to a commit -> ZIP snapshot streamed under a size
   limit -> safe extraction -> deterministic manifest. No API endpoint, job or UI uses this yet.

## Decisions on record

`docs/decisions/` (ADR-0009 to ADR-0012) covers VSAM record layout derivation, the Stage 1 platform presets, the migration API and file artifacts, and
the enterprise ingestion platform. The enterprise queue is database-leased, not Redis/Celery, by choice (see `docs/execution/PHASE_1_DURABLE_INFRASTRUCTURE.md`).

## Evidence classes used everywhere

`GnuCOBOL-verified` means the reference is GnuCOBOL 3.1.2. `IBM_RUNTIME_VERIFIED` means output captured from a real IBM system; nothing in this
repository has that status. Simulators (CICS, IMS, MQ, JCL runner) are verified only against their own specifications.
