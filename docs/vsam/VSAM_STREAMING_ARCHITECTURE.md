# VSAM Streaming Architecture

```
upload (PUT, raw body) -> input file on disk
   -> iter_frames (bounded buffer, FIXED / RDW / RRN framing)
   -> decode + representability check
   -> KSDS key checks (duplicate, order, collation) / RRDS RRN order
   -> text image writer -> <out>.part, incremental SHA-256 of input and output
   -> checkpoint every N records (fsync, then atomic checkpoint file)
   -> verify record count, byte count, SHA-256 against the manifest
   -> atomic rename to the published name
```

Code: `enterprise/vsam/reader.py` (framing), `migrate.py` (pipeline),
`jobs.py` (durable jobs and worker), `layout_check.py` (SELECT/FD validation),
`api/vsam_routes.py` (HTTP).

## Memory
O(read chunk + one record): no whole-file read, no record list, no
dataset-sized buffer. The key check keeps only the previous key. Measured peak
memory is in `docs/operations/CERTIFICATION_EVIDENCE.md`.

## Checkpoint and resume
A checkpoint (`MigrationCheckpoint`) is written at a record boundary after the
partial output has been fsynced. It holds the input offset, output offset,
records processed, last key, the SHA-256 of the input prefix, and digests of
the layout and options plus the engine version. Resume re-hashes the input
prefix and compares it with the checkpoint, checks layout, options, engine
version and file size, truncates the partial output to the recorded offset,
and continues. Anything that does not match is refused (`RESUME_REJECTED`),
never silently restarted. Output is published only after the final checks.

## Job lifecycle
Jobs use the Phase 0 state machine. SUCCEEDED is reachable only through
VALIDATING and PUBLISHING with processed, validated, checksum-verified and
published evidence all true. Creation is idempotent per `(application,
idempotency key)` and the key covers the manifest and the COBOL source. After a
restart, `recover_interrupted()` re-queues QUEUED, RUNNING and RETRYING jobs,
and the migration resumes from its checkpoint; a job whose input is gone
becomes FAILED (`INPUT_LOST`). Downloads re-hash the artifact and refuse a
tampered file.

## What is not streaming
The generated Java runtime (`CobolFileIo`) loads a KSDS `.idx` or RRDS `.rel`
image into memory. Fixed-length ESDS is read record by record.

## Current limits of this implementation
- Jobs run in a thread pool in the API process, backed by SQLite. The Redis/Celery and PostgreSQL deployment targeted by ADR-0011 is not built yet, so a multi-process or multi-host deployment is not supported.
- The input is stored on the local filesystem of the API host; the object-storage adapters are not built yet.
