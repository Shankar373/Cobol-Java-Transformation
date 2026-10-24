# JAVA CANDIDATE CONTRACT — V2 EXTENSION (Spring Boot / Maven lane)

> **Status:** AUTHORITATIVE for the Spring Boot/Maven candidate lane. Extends V1
> (`JAVA_CANDIDATE_CONTRACT.md`). Contract version: **2.0**. Authority chain:
> D-10 (approved 2026-10-21) → this extension → V1 baseline for plain-Java shape.

---

## 1. Purpose

V1 defines the plain-Java candidate shape (no build system, zero external
dependencies, platform-controlled `javac`). The repository also ships a Spring
Boot/Maven lane that emits `pom.xml` and builds with Maven inside a pinned
container. This extension defines the V2 candidate shape for that lane without
weakening V1's plain-Java guarantees.

## 2. V2 Candidate Shape [CONFIRMED, D-10 approved 2026-10-21]

A V2 Spring Boot candidate is a **Maven project tree**:

- Java source files in a conventional Maven `src/main/java` package layout,
  plus the candidate manifest (§3, extending V1 §3).
- **Maven build system** — a `pom.xml` declaring `spring-boot-starter-batch`
  (or equivalent) as the sole dependency group. The platform builds with its
  own **platform-controlled Maven** inside a pinned execution environment
  (`maven-offline-springboot` image).
- **Offline dependency resolution** — all Maven artifacts are precached in the
  pinned image; no network fetches at build time. Any additional dependency
  requires an image rebuild and provenance re-record (BL-071).
- **Entrypoint via manifest** — a single declared main class; no scanning, no
  guessing (same as V1).
- **Batch/console execution model** — stdin/stdout/stderr/files; no servers,
  no ports, no listening sockets (sandbox forbids networking per ADR-0008).

## 3. V2 Manifest Extensions

The V2 manifest adds the following fields to the V1 mandatory set:

| Field | Requirement |
|---|---|
| `build_system` | `"maven"` (V2 only; V1 omits or declares `"none"`) |
| `maven_pom_hash` | SHA-256 of `pom.xml` (bound into candidate identity) |
| `spring_profile` | Spring Boot profile (default: `default`) |
| `offline_repo_digest` | Digest of the pinned Maven offline image |

**Intake rule:** a V2 candidate missing any V2 field is refused (fail-closed),
mirroring V1 §3.

## 4. V2 Execution Rules

Per ADR-0008 / DR-18 (same sandbox guarantees as V1 §5):

1. **Container-per-execution** — fresh, disposable container per run.
2. **Platform-controlled build** — the platform runs `mvn -o package` inside
   the pinned offline image; build failures are candidate-build failures
   (recorded; verdict cannot be `VERIFIED`).
3. **Sandbox:** read-only staged candidate copy; `network none`; memory/CPU/
   pids limits; **hard timeout** (timeout ⇒ `ERROR`, never PASS).
4. **Working directory / environment:** exactly as declared in the manifest.
5. **Input model:** identical to oracle side (differential requirement).
6. **Output capture:** stdout, stderr, exit code, generated files (per-file
   SHA-256), timing, termination status — captured as execution evidence.
7. **No host RW mounts; no chmod 777; no hardcoded credentials** (ADR-0008).
8. **Cleanup:** workspace removed after evidence capture.

## 5. V2 Test-First Requirements

| Test | Expected |
|---|---|
| Missing `pom.xml` in V2 candidate | Intake refusal (fail-closed) |
| Missing `maven_pom_hash` | Intake refusal |
| Maven build failure | Recorded; verdict not `VERIFIED` |
| Network fetch attempt at build time | Sandbox violation recorded (offline repo) |
| Timeout during Maven build | `ERROR`; never PASS |
| Candidate identity drift between runs | Distinct verdict runs; no reuse |

## 6. Change Control

Version 2.0. Any further extension (additional build systems, network-enabled
builds, runtime dependency resolution) requires: new contract version + ADR +
sandbox review + mutation-proof coverage before any verdict rests on it.
