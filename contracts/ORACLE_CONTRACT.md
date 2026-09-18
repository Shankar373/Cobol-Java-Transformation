# ORACLE CONTRACT — V1

> **Status:** AUTHORITATIVE (approved via ADR-0001 / PD-01). This contract is drafted
> and validated; implementation is a later phase. Contract version: **1.0**.
> Authority chain: [PHASE1B_OWNER_APPROVALS.md](../decisions/PHASE1B_OWNER_APPROVALS.md)
> → [ADR-0001](../decisions/ADR-0001_0004.md) → this contract.

---

## 1. Purpose and Authority

The COBOL Oracle is the authoritative behavioral reference for the original COBOL
application. This contract defines how the platform executes the oracle, what evidence
it must produce, and the hard rules that make oracle evidence trustworthy.

**V1 authoritative oracle [CONFIRMED — ADR-0001]:** GnuCOBOL 3.1.2.0 +
Open-COBOL-ESQL 1.4, executed in a Docker image **pinned by digest**.

**Never claimed:** z/OS equivalence. Verdicts are scoped to the oracle identity, always.

## 2. Oracle Identity

Every oracle execution carries an identity that MUST appear in evidence and in every
verdict derived from it:

| Field | Requirement |
|---|---|
| `oracle_id` | Adapter identity (V1: `gnucobol-3.1.2`) |
| `image_digest` | **Digest pin (e.g., `sha256:…`) — NEVER a mutable tag** |
| `compiler_version` | Captured `cobc --version` output (from execution, not assumption) |
| `preprocessor_version` | OCESQL version where used |
| `base_image` | Base image identity (Alpine 3.19 lineage) |

Rule: an oracle identity without a digest is **schema-invalid**. Reference by `:latest`
is prohibited (predecessor defect: mutable tags silently changed the oracle).

## 3. Adapter Status Model (mandatory, observed)

Every adapter invocation explicitly reports exactly one of:

| Status | Meaning | Evidence requirement |
|---|---|---|
| `AVAILABLE` | Probed and ready | Probe observation record |
| `UNAVAILABLE` | Infrastructure absent/down | Probe failure observation |
| `FAILED` | Invoked and failed | Execution record with exit/stderr |
| `SUCCEEDED` | Invoked and completed | Full execution record |

Status is derived **only from observed state** — probed, executed, captured. It is
NEVER inferred from configuration presence, environment variables, or file existence
(predecessor defect: `PGHOST` env var → "VERIFIED_POSTGRESQL" claim literal).

## 4. Execution Requirements

### 4.1 Isolation (per ADR-0008 / DR-18)

- **Container-per-execution** — each oracle run gets a fresh container.
- **Read-only staged source copy** — the workload source is staged into an isolated
  workspace; the original source tree is **never mounted writable**; the staged copy is
  the only thing the oracle sees.
- **Source immutability verification** — the original source tree hash is recorded
  before execution and verified **unchanged** after execution. A changed source tree
  invalidates the run (predecessor defect D-2: repo bind-mounted read-write, committed
  fixtures corrupted between runs).
- **`network none`** — V1 has no SQL (ADR-0007); the oracle container gets no network.
- **Resource limits** — memory, CPU, pids limits per container.
- **Hard timeout** — a platform-enforced execution timeout. Timeout is a platform
  failure (`ERROR` verdict state), never PASS.
- **Cleanup** — the execution workspace is removed after evidence capture.

### 4.2 Compilation and execution

- Compilation and execution happen **inside** the digest-pinned container (the host has
  no `cobc`).
- Compile command, flags, and environment are recorded verbatim as evidence.
- The executable and its runtime environment are part of the execution record.

## 5. Oracle Evidence Obligations

Every `SUCCEEDED`/`FAILED` oracle execution produces an execution record containing:

| Field | Notes |
|---|---|
| `execution_id` | Platform-assigned, globally unique |
| `workload_id` | Binding to the workload |
| `oracle_id` + `image_digest` | Per §2 |
| `command` | Verbatim compile + run commands |
| `environment` | Environment variables (explicit set), working directory |
| `input` | Controlled input identity (stdin content/hash, input file hashes) |
| `start_time` / `end_time` | Timestamps |
| `exit_code` | Observed process exit code |
| `stdout` | Captured bytes |
| `stderr` | Captured bytes |
| `generated_files` | Every file the execution produced, with per-file SHA-256 |
| `source_tree_hash_before/after` | Immutability proof |
| `termination_status` | `normal` / `timeout` / `nonzero_exit` / `error` |

Missing mandatory evidence → the evidence manifest is incomplete → the verdict cannot be
`VERIFIED` (see VERDICT_CONTRACT). Evidence is **never** fabricated or defaulted
(missing exit code is NOT "0"; missing stderr is NOT "empty-success").

## 6. Hard Rules (normative)

1. **Never fabricate oracle execution.** If the oracle did not run, there is no oracle
   evidence; the verdict cannot exceed `UNAVAILABLE`/`UNPROVEN`.
2. **Never mutate the original source repository.** All execution against staged,
   read-only-verified copies.
3. **Never treat configuration presence as evidence of execution.**
4. **Never report a status that was not observed.**
5. **Digest pinning is mandatory** for the oracle image identity.
6. Oracle execution evidence is content-addressed (SHA-256) per ADR-0008 / DR-16.

## 7. V1 Limitations (must surface in verdicts)

The following are limitations of the V1 oracle, explicitly stated in every verdict's
scope block so no verdict is misread as mainframe equivalence:

- GnuCOBOL is not IBM Enterprise COBOL; dialect coverage differs.
- GnuCOBOL ISAM containers are not z/OS VSAM (no CI/CA splits; different alternate-index
  behavior) — consistent with ADR-0002 (INDEXED/RELATIVE content excluded from V1).
- No DB2 for z/OS, no CICS, no JCL runtime semantics in V1.
- Verdicts read: *"equivalent to GnuCOBOL 3.1.2.0 (image digest …) under the declared
  environment."*

## 8. Future Adapters (out of V1 scope)

z/OS (real mainframe), z390, Hercules remain FUTURE (DR-27). No adapter may be claimed
to exist until it exists in this repository with execution evidence. Adding an adapter
is a versioned contract extension, not silent growth.

## 9. Test-First Requirements (for the implementation phase)

| Test | Expected |
|---|---|
| Oracle unavailable (image absent, Docker down) | `UNAVAILABLE` verdict state; no fabricated evidence |
| Source tree changed after run | Run invalidated; explicit diagnostic |
| Digest missing from identity | Schema-invalid; run refused |
| Evidence field missing | Manifest incomplete; verdict capped below `VERIFIED` |
| Timeout | `ERROR` verdict state; never PASS |
| Status inferred from config (negative test) | Prohibited — status only from observation |

## 10. Change Control

This contract is versioned (1.0). Changes require an ADR. Any change to the oracle
identity (version, digest, base image) invalidates existing baselines derived under the
previous identity (per ADR-0005 invalidation rules) — in V1, per ADR-0008/DR-17, every
run re-executes the oracle fresh, so no stale baseline can survive this transition.
