# JAVA CANDIDATE CONTRACT — V1

> **Status:** AUTHORITATIVE on the platform side; **producer-binding force gated on
> LLM-integration-owner co-approval** (PD-04 is a joint decision — platform half
> approved, co-approval PENDING). Contract version: **1.0**. Implementation is a later
> phase. Authority chain:
> [PHASE1B_OWNER_APPROVALS.md](../decisions/PHASE1B_OWNER_APPROVALS.md) →
> [Phase-1 report PD-04](../decisions/PHASE1_DECISION_REPORT.md) → this contract.

---

## 1. Purpose

Defines the single V1 shape of a Java candidate — the externally produced Java the
platform builds, executes, and validates — and the execution rules the platform applies.
This contract is consumed by the engine's candidate execution layer; it binds the
producer interface only after co-approval (see TRANSFORMATION_PRODUCER_CONTRACT §7).

## 2. V1 Candidate Shape [CONFIRMED, platform side]

A V1 Java candidate is a **plain Java source tree**:

- Java source files in a conventional package directory layout (or default package),
  plus the candidate manifest (§3).
- **No build system** — no `pom.xml`, no Gradle files, no wrapper scripts. The platform
  compiles with its own **platform-controlled `javac`** inside a pinned execution
  environment.
- **Zero external dependencies** — no network fetches, no dependency resolution, no
  framework requirements. Any helper/runtime code the candidate needs must be **vendored
  inside the tree** as plain source.
- **Entrypoint via manifest** — a single declared main class; no scanning, no guessing.
- **Batch/console execution model** — stdin/stdout/stderr/files; no servers, no ports,
  no listening sockets (sandbox forbids networking anyway per ADR-0008).

**Deferred to V2 (explicitly):** Maven/Spring Boot candidate adapter (the second
observed shape). Adding it is a versioned contract extension with its own build/execution
and sandbox rules — not a V1 concern.

## 3. Candidate Manifest (mandatory fields)

The candidate package carries a manifest declaring:

| Field | Requirement |
|---|---|
| `candidate_id` | Identity (platform-assigned at intake if absent) |
| `workload_id` / source binding | Which COBOL workload this candidate targets, with source hash(es) |
| `source_hash` | Hash of the COBOL source the candidate was generated from (checkable binding) |
| `generated_files` | Complete list of source files, **each with its own hash** |
| `entrypoint` | Main class (fully qualified); argument convention; stdin convention |
| `java_version` | Target Java version (e.g., 17) |
| `dependencies` | Must be **empty or vendored-declared** in V1 |
| `runtime_requirements` | Expected working directory; output-path conventions; required environment variables (if any) |
| `producer` | Producer identity + version (branding only — **never evidence**) |
| `generation_timestamp` + transformation metadata | Informational only |
| `mutation_regeneration` | Capability declaration for mutation validation (see TRANSFORMATION_PRODUCER_CONTRACT §6) |

**Intake rule:** a candidate package missing mandatory manifest fields is **refused**
(fail-closed). The platform never guesses an entrypoint, never infers dependencies,
never defaults absent fields. Undeclared files outside `generated_files` are flagged;
mismatched hashes are refused.

## 4. Candidate Identity & Content-Addressing

- The candidate tree is hashed at intake (SHA-256 over the declared file list + hashes;
  manifest itself included) — this is the `candidate_hash` bound into evidence and
  verdict scope (VERDICT_CONTRACT §4).
- Candidate content is content-addressed per ADR-0008/DR-16.
- Identity change ⇒ new verdict run required (ADR-0005 invalidation). The platform never
  reuses a verdict across candidate identities.

## 5. Execution Rules (platform side)

Per ADR-0008 / DR-18 (normative for the execution layer):

1. **Container-per-execution** — each candidate run gets a fresh, disposable container.
2. **Platform-controlled compile** — the platform compiles the source tree with its own
   pinned JDK via `javac`; compilation failures are candidate-build failures
   (recorded; verdict cannot be `VERIFIED`), never retried loosely or patched.
3. **Sandbox:** read-only staged candidate copy; `network none`; memory/CPU/pids
   limits; **hard timeout** (timeout ⇒ `ERROR`, never PASS).
4. **Working directory / environment:** exactly as declared in the manifest; nothing
   implicit.
5. **Input model:** the controlled workload inputs (stdin bytes, input files) staged
   read-only into the workspace — identical inputs to the oracle side (differential
   requirement).
6. **Output capture:** stdout, stderr, exit code, generated files (with per-file
   SHA-256), timing, termination status — all captured as execution evidence per the
   same obligations as ORACLE_CONTRACT §5.
7. **No host RW mounts; no chmod 777; no hardcoded credentials** (ADR-0008).
8. **Cleanup:** workspace removed after evidence capture.

**Four concepts never conflated:** Java compilation ≠ Java execution ≠ functional
behavior ≠ business equivalence (a verdict may never skip levels).

## 6. Candidate Provenance vs Evidence (trust boundary)

- Producer metadata (identity, version, claims about quality) is **provenance** —
  recorded, displayed, never treated as validation evidence.
- The candidate is **untrusted input**: the platform observes what it actually does
  under controlled conditions. Compilation success proves nothing about equivalence.

## 7. Test-First Requirements

| Test | Expected |
|---|---|
| Missing manifest field | Intake refusal (fail-closed) |
| Entrypoint class absent from tree | Build failure; verdict capped; diagnostic |
| Undeclared extra files | Flagged; intake anomaly |
| Hash mismatch in `generated_files` | Refusal |
| Compilation failure | Recorded; verdict not `VERIFIED` |
| Runtime file/network access attempt | Sandbox violation recorded (network blocked; behavior observed) |
| Timeout | `ERROR`; never PASS |
| Candidate identity drift between runs | Distinct verdict runs; no reuse |

## 8. Change Control

Version 1.0. The V2 Maven/Spring adapter, additional entrypoint conventions, or any
dependency-resolution allowance requires: new contract version + ADR + sandbox review +
mutation-proof coverage before any verdict rests on it.
