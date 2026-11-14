# ADR-0011: VSAM migration API with file-based artifacts (interim)

**Date**: 2026-11-13
**Status**: proposed (interim design; owner review pending)
**Deciders**: engineering (autonomous Stage 1 execution)

## Context

The VSAM migration engine was library-only. The product workflow needs a way to submit a dataset for a file the application
declares, read the result and download the converted data, using the control plane's existing upload bounds, roles and
workspace conventions.

## Decision

`api/vsam_migration.py` plus three routes: `POST /applications/{id}/vsam/migrate`, `GET .../vsam/migrations/{id}` and
`GET .../vsam/migrations/{id}/download`. Layout, keys and organization are derived from the application's own discovered FD
(the `organization` option may only pick a compatible one). The migration id is a hash of the application, options, dataset,
source and target layout identities, the dataset definition, the platforms and `ENGINE_VERSION`, so equal ids mean equal
results. Artifacts are two files per id (`report.json` written last, `output.dat`) under the workspace root, written
atomically, never overwritten with a different result, and the download is served only for a RECONCILED result whose stored
bytes still match their hash and only to the operator role (converted data is customer data).

## Alternatives Considered

- **Rows in the sqlite Store**: the right end state (restart-safe job state, listing, audit, run-active coordination), but it
  needs a schema migration and job-slot integration that were not designed in this stage. Not chosen now.
- **A background job with polling**: needed for large datasets and for resume/cancel; the synchronous bounded request (10 MB per file by default, `CONTROL_PLANE_MAX_FILE_BYTES`; hard backstop `MAX_DATASET_BYTES` 50 MB
  per file by default, two concurrent migrations) is the smaller step.
- **Letting the request supply layout and keys**: rejected, it would let a caller migrate data under a layout the
  application does not declare.

## Consequences

Positive: refusals are stored, named and never downloadable; ids cannot collide across layouts or engine versions; no new
dependency or database.

Negative / open (interim limits): no resume or cancel endpoint, no listing, no audit events, no cleanup of old artifacts, no
coordination with re-ingest or run state (a migration reads the live source directory), a per-process concurrency limit, an
integrity hash that is not signed, and the assessment (`engine/vsam/assess.py`) and the API plan separately so discovery can
disagree with the API (for example group RECORD KEYs and multi-record FDs). Moving the planning into `engine/vsam/` and the
records into the Store is the follow-up before this is relied on beyond Stage 1.

Related: ADR-0010 (platform, FD COPY, RDW) supersedes the statement in ADR-0009 that binary bytes are copied and never reordered.

## Review corrections and accepted Stage 1 limits (2026-11-14)

An independent architecture / persistence review of head b754599 found no correctness blocker for a bounded, synchronous
Stage 1 subset and drove these changes and statements:

- **Fixed.** A torn or corrupt `report.json` is treated as absent (404 on read, rewritten by an identical request) instead of
  wedging the id with a 500. A failed write removes its temporary file. A per-application cap
  (`MAX_MIGRATIONS_PER_APP = 200`) refuses further *new* migrations with a named reason; an existing id stays idempotent.
  Reports are customer data (rejection reasons quote field values), so **reading a report now needs the operator role**,
  like the download; only `GET` of other resources stays viewer.
- **Corrected claims.** Only *engine-level* refusals (`success == false`) are stored. Planning refusals (unknown file,
  ambiguous FD, discovery errors, missing platforms) are 400 responses and are not stored. "Not overwritten with a different
  result" is enforced by comparing the output hash for a deterministic id, not by an exclusive create; the check/write window
  is harmless because equal ids have equal content and temporary names are per writer.
- **Accepted for Stage 1, required before wider use.**
  - No coordination with re-ingestion: do not re-ingest an application while a migration for it runs. A stale report is not
    marked as predating the current source (it records the layout hash, not a source identity).
  - No listing, delete, retention or audit events; storage shares the workspace volume (cap above bounds growth only).
  - The concurrency bound (`MAX_CONCURRENT = 2`) is per process and independent of the job pool; the upload is read into
    memory (bounded by the dataset limit) before a slot is tried.
  - Files are not fsynced; directory modes follow the umask above the migration directory; without
    `CONTROL_PLANE_WORKSPACE_DIR` the fallback is a fixed temporary path (development only; production pins the variable).
  - The integrity hash is unsigned.
  - Moving records into the sqlite Store (listing, audit, retention, run and ingest coordination) remains the follow-up.
