# Current Architecture

Baseline: 4513881bc3dff50df4e81910dbc2d28fe5308dbc

## System shape

The implementation is a deterministic modernization pipeline plus an evidence-driven
verification/control plane.

Secure ingestion -> discovery -> dependency and capability analysis -> semantic COBOL IR ->
transformation planning -> deterministic COBOL to Java mapping -> Java generation ->
candidate assembly -> Docker Java execution -> GnuCOBOL oracle execution -> artifact capture ->
contract-aware comparison -> evidence integrity validation -> deterministic verdict ->
persistence/API -> React presentation.

## Trust boundaries

- Uploaded COBOL is untrusted input.
- Generated Java is untrusted candidate input.
- Producer metadata is provenance, not evidence.
- Execution artifacts become evidence only after identity, completeness, hash and binding checks.
- Verdicts derive from validated evidence, not generator claims.

## Deterministic transformation

The transformation path does not require an LLM. Parser, IR, capability analysis, mapping
and generation are deterministic code paths.

A capability claim must be supported by:
parser -> IR -> capability -> plan -> mapping -> generation -> compile -> execute.

## Execution boundary

Docker is the authoritative execution path used by the CI backend/oracle job. Host-only
fallbacks must not silently turn unavailable execution into a successful verdict.

## Mainframe boundaries

JCL, CICS, DB2, indexed/relative files and other enterprise constructs may be modeled or
partially transformed, but broad runtime equivalence is not currently proven.

## Evidence boundary

Evidence is bound to workload, source, candidate, execution, role, artifact identity,
content hashes, environment/runtime identity and comparison result. Missing, malformed,
stale or mismatched evidence must fail closed.

## Persistence and API

SQLite and filesystem-backed artifacts are functional. Production deployment still requires
stronger serialization, authorization, retention, migration, concurrency, rate limiting and
audit controls.

FastAPI owns orchestration/state retrieval; React presents state. The frontend is not the
semantic authority.
