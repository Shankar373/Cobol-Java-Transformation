# Enterprise Data Contracts

All contracts are in `enterprise/contracts.py`: frozen pydantic models, `extra="forbid"`,
each carrying `schema_version` (currently `1.0`). Large objects are referenced by
`ObjectRef` (key, size, SHA-256, version), never embedded.

| Contract | Purpose |
|---|---|
| SourceSnapshot | Application, source type, repository, requested ref, resolved commit, manifest, archive ref |
| SourceFileManifest | Files (path, size, SHA-256, type) and ignored files with reasons |
| IngestionJob | Idempotency key, state, attempts, error, correlation id, engine version |
| ApplicationInventory | Programs, copybooks, other files, discovery state |
| ApplicationDiscovery | Entry programs, calls, copy edges, file definitions, VSAM datasets, unsupported items |
| DatasetManifest | Dataset object and record count |
| VsamRecordLayout | FIXED or VARIABLE_RDW, record length bounds, key offset and length, code page |
| VsamExportManifest | Organization (KSDS, ESDS, RRDS), layout, duplicate semantics, alternate keys, counts, SHA-256, export provenance |
| MigrationJob | Manifest, input object, state, bytes and records processed, output, error |
| MigrationCheckpoint | Input identity and offset, output offset, records processed, last key, layout and options digests, engine version |
| ArtifactObject | Published artifact reference and publication status |
| ValidationEvidence | Source checksum, engine and runtime versions, commands, comparison result, oracle used |
| CertificationResult | Commit SHA, workflow, run id, required, passed and skipped jobs; `certified` is false without a run id or with any skip |

## Job states
CREATED, QUEUED, RUNNING, RETRYING, VALIDATING, PUBLISHING, SUCCEEDED, FAILED, REFUSED,
CANCELLED, EXPIRED. SUCCEEDED requires `CompletionEvidence(processed, validated,
checksum_verified, published)` all true. Terminal states have no exits.

Evolution: bump `schema_version` and add a migration; readers must reject unknown versions.
