# Current Architecture

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

Baseline: fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4 (Phase A trust hardening)
Lifecycle, persistence and API security hardening applied on top of that baseline.

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

Control-plane state lives in SQLite; persisted payloads are versioned JSON envelopes
with strict field validation and no pickle. Evidence payloads carry the engine seal,
so corrupted, legacy or tampered rows fail closed as controlled 500 responses instead
of being coerced into benign defaults (`CREATED`, `None`, `()`), and a database written
by a newer schema version is refused.

The run lifecycle is a forward-only state machine enforced by the store: backward
transitions are rejected, terminal states are final, and the only terminal -> CREATED
path is an explicit revalidation reset that atomically clears the previous
verdict/evidence and increments `validation_generation`, so a stale background worker
can never write over a newer attempt. Runs left non-terminal by a process restart are
failed at startup.

Background work runs in in-process daemon threads bounded by
`CONTROL_PLANE_MAX_CONCURRENT_JOBS` (HTTP 429 when full; slots are released even when
a worker crashes). A run is created only after its job slot and certification contract
are secured, and terminal state is persisted on every exit path.

Certification contracts are resolved for every (re)validation from the repository
fixture registry (`fixtures/*/workload.py`, trusted repo code) or the explicit default
STDOUT + EXIT_STATUS contract. Workloads that require staged fixture inputs are
rejected instead of being silently downgraded, and the contract id used is recorded on
the run and reported by the verdict endpoint.

API security controls: opt-in bearer authentication via `CONTROL_PLANE_API_TOKEN`
(constant-time comparison, `/health` exempt for probes), bounded request/file/file
count upload limits, upload path sanitization (traversal and drive letters rejected,
colliding paths rejected, hierarchy preserved, writes confined to the per-application
workspace) and typed errors mapped to explicit HTTP statuses without tracebacks or
filesystem paths in client responses.

FastAPI owns orchestration/state retrieval; React presents state. The frontend is not
the semantic authority.

Remaining production gaps: a durable job queue with resume (restarts fail interrupted
runs rather than re-queue them), retention/TTL policies, per-client rate limiting,
audit logging, external secret management for the API token, TLS/egress policy at the
deployment boundary, and multi-node coordination (SQLite is single-node).
