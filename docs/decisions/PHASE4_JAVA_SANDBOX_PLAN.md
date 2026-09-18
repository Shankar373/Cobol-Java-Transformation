# PHASE 4 — JAVA SANDBOX ARCHITECTURE / EVIDENCE PLAN

> **Date:** 2026-09-14
> **Phase:** PHASE 4A — Architecture / Evidence Gate (NO IMPLEMENTATION)
> **Status:** PLAN COMPLETE — AWAITING OWNER REVIEW BEFORE IMPLEMENTATION

---

## 1. Current-State Baseline

### 1.1 What Phase 3 Proved

Phase 3 established the core validation loop with real execution:

```
COBOL source
  → Real GnuCOBOL Docker Oracle (sha256-pinned, --network none)
  → Real artifacts (STDOUT, STDERR, EXIT_STATUS)
  → Real host Java execution (javac 25.0.3, java 25.0.3 via subprocess.run)
  → Typed comparators
  → Evidence manifest
  → Evidence-derived verdict
```

### 1.2 Current Java Execution Path

The current `RealJavaCandidateAdapter` (`engine/candidate/java_adapter.py`) executes Java **directly on the host system**:

- **Compilation**: `subprocess.run([javac, -d, class_dir, ...])` (line 121)
- **Execution**: `subprocess.run([java, -cp, compiled_path, entrypoint])` (line 192)
- **Timeout**: `subprocess.TimeoutExpired` caught (line 206)
- **No Docker container** for Java execution
- **No network isolation** (host network)
- **No resource limits** (host cgroups)
- **No read-only staging** (host filesystem)

### 1.3 Existing Docker Infrastructure

The repository already has Docker execution infrastructure:

| Component | File | Purpose |
|---|---|---|
| `DockerRunner` | `engine/execution/docker_runner.py` | Generic Docker execution engine |
| `DockerOracleAdapter` | `engine/oracle/docker_adapter.py` | Docker-backed GnuCOBOL oracle |
| `ExecutionPolicy` | `engine/execution/abstractions.py` | Policy enums (CONTAINER_PER_EXECUTION, etc.) |
| `ResourceLimits` | `engine/execution/abstractions.py` | CPU/memory/pids/timeout config |
| `NetworkPolicy` | `engine/execution/abstractions.py` | Network enable/disable config |
| `FilesystemPolicy` | `engine/execution/abstractions.py` | Read-only path config |

### 1.4 CandidateAdapter Abstraction

The `CandidateAdapter` ABC (`engine/candidate/adapter.py`) defines:

```python
class CandidateAdapter(ABC):
    def validate_candidate(candidate_path, manifest) -> list[str]
    def compile(candidate_path, manifest) -> CompilationResult
    def execute(run_id, compiled_path, manifest, input_data) -> CandidateExecutionResult
```

The `CandidateExecutionResult` dataclass includes:
- `termination_status`: normal, timeout, nonzero_exit, error
- `timeout_applied`: bool
- `timeout_duration`: int | None
- `exit_code`: int | None
- `stdout`, `stderr`: bytes

This abstraction already supports the Docker adapter pattern.

---

## 2. Phase 3 Limitations Being Addressed

| # | Limitation | Current State | Target State |
|---|---|---|---|
| 1 | Java container-per-execution | NOT PROVEN (host execution) | PROVEN (Docker container) |
| 2 | Java network isolation | NOT PROVEN (host network) | PROVEN (--network none) |
| 3 | Java resource limits | NOT PROVEN (no cgroup) | PROVEN (--memory, --cpus, --pids-limit) |
| 4 | Java read-only staging | NOT PROVEN (host filesystem) | PROVEN (read-only bind mount) |
| 5 | Java cleanup | NOT PROVEN (tempfile only) | PROVEN (--rm container flag) |
| 6 | Ruff clean | NOT PROVEN (14 lint errors) | NOT ADDRESSED (deferred) |

---

## 3. Security / Threat Model for Executing Generated Java

### 3.1 Threat Categories

| Threat | Risk | Mitigation |
|---|---|---|
| Arbitrary code execution | Candidate Java may contain malicious code | Container isolation prevents host access |
| Network exfiltration | Candidate may phone home or fetch payloads | `--network none` disables all networking |
| Resource exhaustion | Candidate may fork bomb or consume all memory | `--memory`, `--cpus`, `--pids-limit` enforce caps |
| Filesystem escape | Candidate may read/write host files | Read-only bind mount + no host RW mounts |
| Source tampering | Candidate may modify its own source | Read-only staging prevents writes |
| Timeout bypass | Candidate may hang indefinitely | Hard timeout kills container |
| Supply chain | Docker image may be tampered | sha256 digest pinning |
| Credential exposure | Candidate may read secrets | No host env vars passed; no default credentials |

### 3.2 Trust Boundaries

```
┌─────────────────────────────────────────────┐
│  HOST SYSTEM (validation engine)            │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  DOCKER CONTAINER (disposable)      │    │
│  │                                     │    │
│  │  - Platform-controlled JDK          │    │
│  │  - Read-only candidate source       │    │
│  │  - No network                       │    │
│  │  - Resource-limited                  │    │
│  │  - Hard timeout                     │    │
│  │                                     │    │
│  │  OUTPUT: stdout, stderr, exit code  │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  EVIDENCE: artifact hashes, termination     │
└─────────────────────────────────────────────┘
```

The container is the trust boundary. The host never executes candidate code directly.

---

## 4. Exact Sandbox Requirements

Per ADR-0008 DR-18 and JAVA_CANDIDATE_CONTRACT §5:

| # | Requirement | Enforcement |
|---|---|---|
| S1 | Container-per-execution | Fresh `docker run --rm` per execution |
| S2 | Read-only staged source | `-v host_path:container_path:ro` |
| S3 | Network disabled | `--network none` |
| S4 | CPU limit | `--cpus 1.0` |
| S5 | Memory limit | `--memory 512m` |
| S6 | Process count limit | `--pids-limit 256` |
| S7 | Hard timeout | `subprocess.run(timeout=...)` + container termination |
| S8 | No host RW mounts | Only read-only bind mounts |
| S9 | No chmod 777 | Not applicable (no writable paths) |
| S10 | No hardcoded credentials | No env vars passed; no host secrets |
| S11 | Cleanup after execution | `--rm` flag guarantees container removal |
| S12 | Deterministic execution metadata | ExecutionId, timestamps, hashes captured |

---

## 5. Proposed Java Container Execution Architecture

### 5.1 Design Principle

**Replace the host execution implementation behind the existing CandidateAdapter abstraction.**

```
Existing validation engine
        +
Secure Java execution adapter (DockerJavaCandidateAdapter)

NOT:

new validation engine
        +
second comparator
        +
second evidence pipeline
```

### 5.2 Component Map

```
engine/candidate/
  adapter.py              # CandidateAdapter ABC (UNCHANGED)
  java_adapter.py         # RealJavaCandidateAdapter (KEEP as fallback)
  docker_java_adapter.py  # NEW: DockerJavaCandidateAdapter

engine/oracle/
  docker_adapter.py       # DockerOracleAdapter (REFERENCE PATTERN)

engine/execution/
  docker_runner.py        # DockerRunner (REUSE for container management)
  artifacts.py            # ArtifactCapturer (UNCHANGED)
  abstractions.py         # ResourceLimits, NetworkPolicy (REUSE)

engine/pipeline.py        # MODIFY: accept adapter injection
```

### 5.3 Compilation Boundary — Explicit Decision

**Security principle:** Generated Java source is untrusted candidate material. Executing `javac` against untrusted source on the host violates the trust boundary established by ADR-0008 DR-18.

**Decision: Both compilation AND execution occur inside Docker containers.**

```
Candidate source files (untrusted)
  → Staged read-only into temp directory
  → docker run --rm --network none [options]
      -v staged_source:/workspace/src:ro
      -v staged_output:/workspace/classes
      eclipse-temurin:21-jdk
      javac -d /workspace/classes /workspace/src/*.java
  → .class files extracted from output volume
  → docker run --rm --network none [options]
      -v staged_classes:/workspace/classes:ro
      eclipse-temurin:21-jdk
      java -cp /workspace/classes Entrypoint
  → stdout/stderr/exit captured
```

**Rationale:**
- Candidate source is untrusted; `javac` processes untrusted input
- A compromised `javac` could execute arbitrary code during compilation
- Compilation inside container maintains the trust boundary
- Matches the oracle pattern (oracle compiles COBOL inside Docker)

**Contract impact:** None. The `CandidateAdapter` ABC defines `compile()` and `execute()` as separate methods. The Docker adapter implements both methods using Docker containers. The `CompilationResult` dataclass is unchanged. The `CandidateExecutionResult` dataclass is unchanged.

**If owner approves host-side compilation as exception:** Document the security exception explicitly. The plan would then show:
- `compile()`: host javac (with documented security exception)
- `execute()`: Docker container
This remains the fallback if Docker compilation proves impractical.

### 5.4 Pipeline Modification

The pipeline currently hardcodes `RealJavaCandidateAdapter`. Change to accept adapter injection:

```python
class VerticalSlicePipeline:
    def __init__(self, config: PipelineConfig, candidate_adapter: CandidateAdapter | None = None) -> None:
        self._candidate_adapter = candidate_adapter or RealJavaCandidateAdapter(...)
```

This preserves backward compatibility while enabling Docker execution.

---

## 6. Component Responsibilities

| Component | Responsibility | Changes |
|---|---|---|
| `CandidateAdapter` ABC | Interface contract | NONE |
| `RealJavaCandidateAdapter` | Host-based execution (fallback) | NONE |
| `DockerJavaCandidateAdapter` | Container-per-execution | NEW |
| `DockerRunner` | Generic Docker container management | REUSE |
| `ArtifactCapturer` | Artifact capture from execution output | NONE |
| `EvidenceManifest` | Evidence recording | NONE |
| `VerdictDeriver` | Verdict from evidence | NONE |
| `VerticalSlicePipeline` | Orchestration | MODIFY (adapter injection) |

---

## 7. Trust Boundaries

| Boundary | Enforcement |
|---|---|
| Host ↔ Container | Docker runtime isolation |
| Container ↔ Network | `--network none` |
| Container ↔ Filesystem | Read-only bind mount only |
| Container ↔ Resources | `--memory`, `--cpus`, `--pids-limit` |
| Container ↔ Time | `subprocess.run(timeout=...)` |
| Container ↔ Cleanup | `--rm` flag |

---

## 8. Input / Source Staging Model

### 8.1 Compilation Stage

```
Host: candidate source files
  → Copy to temp directory
  → Mount temp dir as read-only into container
  → Container: javac -d /workspace/classes *.java
  → Extract .class files from container
  → Cleanup container
```

### 8.2 Execution Stage

```
Host: compiled .class files
  → Copy to temp directory
  → Mount temp dir as read-only into container
  → Container: java -cp /workspace/classes Entrypoint
  → Capture stdout, stderr, exit code
  → Cleanup container
```

### 8.3 Source Hash

Source hash computed BEFORE staging. Staged copy hash verified against original. Read-only mount prevents modification.

---

## 9. Container Lifecycle

```
1. CREATE: docker run --rm [options] IMAGE COMMAND
2. EXECUTE: process runs inside container
3. CAPTURE: stdout/stderr/exit code captured by subprocess.run()
4. TERMINATE: container exits naturally OR timeout kills it
5. CLEANUP: --rm flag ensures container is removed
```

No persistent containers. No container reuse. No manual cleanup needed.

---

## 10. Network Isolation Model

| Aspect | Implementation |
|---|---|
| Docker flag | `--network none` |
| Evidence | Docker command recorded in ExecutionEvidence.command |
| Verification | Test: candidate attempts network access → connection refused |
| Failure mode | Network access attempt fails silently (no crash, no evidence of access) |

---

## 11. Resource-Limit Model

### 11.1 Approved V1 Resource Values

| Resource | Value | Purpose | Enforcement | Evidence | Failure Behavior | Adversarial Test |
|---|---|---|---|---|---|---|
| CPU | 1.0 cores | Prevent CPU exhaustion | `--cpus 1.0` | Requested/Configured; not directly observable at runtime | Candidate runs slower; no crash | CPU-intensive candidate (busy loop) — should complete within timeout |
| Memory | 512 MB | Prevent memory exhaustion | `--memory 512m` | Requested/Configured; OOM kill observable | Container killed with OOM exit code | Memory pressure candidate (large allocation) — should OOM kill |
| Processes | 256 PIDs | Prevent fork bomb | `--pids-limit 256` | Requested/Configured; fork failure observable | Container cannot fork beyond limit | Process explosion candidate (recursive fork) — should hit PID limit |
| Execution duration | 30 seconds | Prevent infinite hang | `subprocess.run(timeout=35)` | Observed (TimeoutExpired) | Timeout → ERROR verdict | SlowArithmetic.java (60s sleep) — already proven |
| Filesystem | Read-only source | Prevent source tampering | `-v :ro` mount | Requested/Configured; source hash verification proves integrity | Write attempt fails inside container | Candidate attempts to modify own source — should fail |

### 11.2 Policy Decision Status

| Value | Status | Rationale |
|---|---|---|
| CPU = 1.0 | **Approved V1** | Matches oracle adapter; sufficient for V1 single-workload |
| Memory = 512m | **Approved V1** | Matches oracle adapter; sufficient for V1 plain Java |
| PIDs = 256 | **Approved V1** | Matches oracle adapter; prevents fork bombs |
| Timeout = 30s | **Approved V1** | Matches oracle adapter; already proven in Phase 3 |
| Read-only source | **Approved V1** | Required by ADR-0008 DR-18 |

**No open resource decisions for V1.** Values match the oracle adapter (already proven). If a legitimate candidate needs more resources, the owner must approve a change to these values.

### 11.3 Adversarial Test Strategy

Each resource limit has a corresponding adversarial test:

| Test | Candidate Behavior | Expected Outcome |
|---|---|---|
| `test_cpu_intensive_candidate` | Infinite busy loop | Completes within timeout (CPU limit throttles, doesn't kill) |
| `test_memory_pressure_candidate` | Allocates >512MB | OOM kill; termination_status="nonzero_exit" |
| `test_pid_explosion_candidate` | Recursive fork | PID limit hit; fork fails; process may hang or exit |
| `test_timeout_candidate` | Thread.sleep(60000) | Timeout; termination_status="timeout" |
| `test_readonly_violation_candidate` | Attempts file write | Write fails inside container; no host impact |

---

## 12. Filesystem Permissions / Read-Only Model

### 12.1 Filesystem Policy

| Container Path | Mode | Host Source | Purpose | Candidate Writable? |
|---|---|---|---|---|
| `/workspace/src` | Read-only mount | Staged candidate source | Source for compilation | No |
| `/workspace/classes` | Writable (container-local) | None — container tmpfs | javac output directory | Yes (container-local only) |
| `/workspace` | Writable (container-local) | None — container tmpfs | Working directory | Yes (container-local only) |
| `/tmp` | Writable (container-local) | None — container tmpfs | Java temp files | Yes (container-local only) |

### 12.2 Distinguished Storage Types

| Type | Location | Persistence | Host Access | Candidate Access |
|---|---|---|---|---|
| **Host-mounted read-only** | Bind mount with `:ro` | Persistent on host | Yes (read-only) | Read-only |
| **Container-local writable** | Container filesystem layer | Disposable with container | No | Full read/write |
| **Host-mounted writable** | NOT USED in V1 | N/A | N/A | N/A |

**V1 model:**
- HOST SOURCE → mounted read-only into container
- HOST OUTPUT → no writable candidate mount (artifacts captured from stdout/stderr only)
- CONTAINER WORKSPACE → disposable writable layer (cleaned up with container)
- CONTAINER /tmp → disposable writable layer (cleaned up with container)

### 12.3 What Happens to Container-Local Writes

Candidate-controlled writes inside the container (to `/workspace`, `/tmp`, or `/workspace/classes`) are:
- Visible during execution
- Lost when container exits
- Never persisted to host
- Never captured as evidence (only stdout/stderr/exit are V1 artifacts)

This is the correct behavior: the candidate's internal filesystem activity is untrusted and irrelevant to validation.

### 12.4 Read-Only Verification

Source read-only mount is verified by:
1. Source hash before execution == source hash after execution (proves no modification)
2. Adversarial test: candidate attempts to write to source path → write fails

### 12.5 Explicit Non-Permissions

The following are NOT permitted inside the container:
- No host-mounted writable volumes
- No symlink escapes (container isolation prevents)
- No chmod 777 (no writable paths need it)
- No access to host filesystem beyond mounted read-only source
- No access to host environment variables
- No access to host credentials or secrets

---

## 13. Timeout / Termination Model

### 13.1 Three Distinct Concepts

| Concept | Meaning | Evidence |
|---|---|---|
| **Timeout of docker client process** | `subprocess.run(timeout=...)` raises `TimeoutExpired` | Python exception |
| **Termination of container** | Docker kills container when parent process is killed | Container exit code; `docker inspect` shows exited state |
| **Cleanup/removal of container** | `--rm` flag causes Docker to remove container after exit | `docker inspect` returns not-found after removal |

These are NOT the same thing. `subprocess.run(timeout=...)` timing out does NOT guarantee the container is terminated or cleaned up. The implementation MUST explicitly handle each.

### 13.2 Timeout Lifecycle — Explicit Steps

```
1. START:   docker run --rm [options] IMAGE COMMAND
            → subprocess.Popen launched
            → Container created and started

2. EXECUTE: Java process runs inside container
            → stdout/stderr piped to subprocess

3. DETECT:  subprocess.run(timeout=configured_timeout + 5)
            → If timeout exceeded: subprocess.TimeoutExpired raised

4. KILL:    On TimeoutExpired:
            → proc.kill()  # Kill the docker client process
            → proc.wait()  # Wait for process to exit
            → This sends SIGKILL to docker run, which terminates the container

5. VERIFY:  Attempt to inspect container (if container ID available)
            → docker inspect <container_id> should return "not found"
            → If container still exists: docker rm -f <container_id> (forced removal)

6. EVIDENCE:
            → termination_status = "timeout"
            → timeout_applied = True
            → timeout_duration = configured_timeout
            → stdout = b"" (or partial output if available)
            → stderr = b"Java execution timeout" (or Docker kill message)

7. CLEANUP: --rm flag ensures container is removed after exit
            → Verify removal if possible (docker inspect returns error)
            → If forced removal was needed: cleanup_verified = True
            → If --rm handled it: cleanup_verified = True (by Docker)
```

### 13.3 Timeout Implementation Pattern

```python
try:
    proc = subprocess.run(
        docker_cmd,
        capture_output=True,
        timeout=configured_timeout + 5,  # Grace period for Docker overhead
    )
    # Normal termination
    termination = "normal" if proc.returncode == 0 else "nonzero_exit"

except subprocess.TimeoutExpired:
    # Step 1: Kill the docker client process
    proc.kill()
    proc.wait()

    # Step 2: Attempt to verify container cleanup
    container_removed = True
    if container_id:
        try:
            inspect_result = subprocess.run(
                ["docker", "inspect", container_id],
                capture_output=True,
                timeout=5,
            )
            if inspect_result.returncode == 0:
                # Container still exists — force remove
                subprocess.run(
                    ["docker", "rm", "-f", container_id],
                    capture_output=True,
                    timeout=5,
                )
                container_removed = True
        except Exception:
            pass  # Best-effort verification

    # Step 3: Capture timeout evidence
    stdout = proc.stdout or b""
    stderr = proc.stderr or b"Java execution timeout"
    termination = "timeout"
    cleanup_verified = container_removed
```

### 13.4 Timeout Evidence

| Field | Value | Classification |
|---|---|---|
| termination_status | "timeout" | Observed |
| timeout_applied | True | Observed |
| timeout_duration | configured_timeout | Requested/Configured |
| container_removed | True/False | Observed (best-effort) |
| cleanup_flag_present | True (--rm) | Requested/Configured |

### 13.5 Existing Proof Preserved

The existing `test_real_timeout_produces_error_verdict` test remains valid. Under Docker, the timeout mechanism changes from host subprocess timeout to container kill, but the evidence chain is identical: `termination_status="timeout"`, `timeout_applied=True`.

---

## 14. Artifact Collection Model

Artifacts are collected from `subprocess.run()` output, NOT from container filesystem:

| Artifact | Source | Hash |
|---|---|---|
| STDOUT | proc.stdout | SHA-256 of bytes |
| STDERR | proc.stderr | SHA-256 of bytes |
| EXIT_STATUS | proc.returncode | SHA-256 of string |

No filesystem extraction from container. No mounted output directories. Clean separation.

---

## 15. Cleanup Guarantees

| Scenario | Cleanup Mechanism |
|---|---|
| Success | `--rm` flag; container removed on exit |
| Compilation failure | `--rm` flag; container removed on exit |
| Runtime failure | `--rm` flag; container removed on exit |
| Timeout | subprocess killed; Docker `--rm` removes container |
| Unexpected exception | `--rm` flag; container removed on exit |
| Docker daemon crash | Container消失 with daemon; no orphaned containers |

The `--rm` flag is Docker's native cleanup guarantee. No manual cleanup code needed.

---

## 16. Failure Modes

| Failure | Detection | Response | Verdict Impact |
|---|---|---|---|
| Docker unavailable | `_check_docker()` returns False | Return UNAVAILABLE | UNAVAILABLE |
| Image unavailable | `docker image inspect` fails | Return UNAVAILABLE | UNAVAILABLE |
| Image digest mismatch | Compare digest after pull | Fail-closed refusal | ERROR |
| Container startup failure | Non-zero exit from docker run | Capture stderr | ERROR |
| Timeout | subprocess.TimeoutExpired | Kill + capture | ERROR |
| Resource violation | OOM kill / PID limit | Capture exit code | ERROR |
| Artifact capture failure | Exception during capture | Return ERROR | ERROR |
| Cleanup failure | --rm should prevent this | Log warning | ERROR |
| Unexpected exception | Generic exception handler | Return ERROR | ERROR |

All failures produce evidence. No silent failures. No swallowed exceptions.

---

## 17. Evidence That Must Be Captured

### 17.1 Evidence Classification Model

Every sandbox property is classified as one of:

| Classification | Meaning | Evidentiary Strength |
|---|---|---|
| **Requested/Configured** | Value passed to Docker in the command | Weakest — proves intent, not enforcement |
| **Observed** | Value observed in execution output or Docker inspection | Medium — proves what Docker received |
| **Directly Tested** | Value verified by a test that exercises the property | Strong — proves behavior under test |
| **Not Directly Observable** | Property enforced by Docker runtime, not exposed to caller | Cannot be evidenced beyond configuration |

The raw Docker command is **supporting evidence** (requested/configured). It alone does not prove enforcement. Structured metadata and tests provide stronger evidence.

### 17.2 Structured Sandbox Evidence

The `DockerJavaCandidateAdapter` MUST produce structured sandbox metadata as part of execution evidence:

```python
@dataclass(frozen=True)
class DockerSandboxEvidence:
    """Structured evidence of sandbox properties."""
    # Container identity
    container_image: str            # e.g., "eclipse-temurin:21-jdk"
    container_image_digest: str     # e.g., "sha256:abc123..."
    container_id: str | None        # Docker container ID (if observable)

    # Requested configuration (classified: requested/configured)
    requested_network_mode: str     # "none"
    requested_memory_limit: str     # "512m"
    requested_cpu_limit: str        # "1.0"
    requested_pids_limit: int       # 256
    requested_timeout_seconds: int  # 30
    requested_mounts: tuple[str, ...]  # ("-v /host:/container:ro",)

    # Observed execution properties (classified: observed)
    observed_exit_code: int | None
    observed_termination_status: str  # normal, timeout, nonzero_exit, error
    observed_stdout_size: int
    observed_stderr_size: int
    observed_duration_ms: int

    # Sandbox verification (classified: directly tested)
    compilation_occurred_in_container: bool
    execution_occurred_in_container: bool
    host_java_invocation_detected: bool  # True = security violation

    # Cleanup (classified: observed)
    cleanup_flag_present: bool      # --rm in Docker command
    container_removed: bool         # Verified by docker inspect after execution
```

### 17.3 Per-Execution Evidence (Structured)

| Property | Classification | How Evidenced |
|---|---|---|
| Container image reference | Requested/Configured | Docker command |
| Resolved image digest | Observed | `docker inspect` or manifest lookup before execution |
| Container ID | Observed | Docker output (if available) |
| Network mode | Requested/Configured | `--network none` in Docker command; directly tested by network access test |
| CPU limit | Requested/Configured | `--cpus 1.0` in Docker command; not directly observable at runtime |
| Memory limit | Requested/Configured | `--memory 512m` in Docker command; OOM kill observable if exceeded |
| PID limit | Requested/Configured | `--pids-limit 256` in Docker command; fork failure observable if exceeded |
| Mount configuration | Requested/Configured | `-v :ro` in Docker command; source hash verification proves read-only |
| Timeout configuration | Requested/Configured | `timeout=35` in subprocess.run; directly tested by timeout test |
| Exit code | Observed | `proc.returncode` from subprocess.run |
| Termination status | Observed | Derived from exit code and timeout detection |
| Cleanup outcome | Observed | `--rm` flag present; `docker inspect` confirms container removed |

### 17.4 Evidence NOT Fabricated

The following are **not directly observable** and must not be claimed as observed:

| Property | Why Not Observable | Honest Classification |
|---|---|---|
| Actual network packets blocked | Docker does not expose packet logs | Requested/Configured + directly tested |
| Actual memory usage during execution | Docker does not expose real-time memory to subprocess caller | Requested/Configured |
| Actual CPU usage during execution | Docker does not expose real-time CPU to subprocess caller | Requested/Configured |
| Filesystem access attempts blocked | Docker does not expose access-denied logs | Requested/Configured + read-only mount verified |

**Honest claim:** "Docker was invoked with `--network none`, and a direct test confirmed network access was refused." Not: "Network was observed to be blocked."

---

## 18. Reproducibility Requirements

| Aspect | Requirement |
|---|---|
| Same candidate + same inputs | Identical stdout/stderr/exit (deterministic program) |
| Artifact content hashes | Identical across runs |
| Comparison outcomes | Identical |
| Verdict state | Identential |
| Execution timestamps | Different (intentionally variable) |
| Execution IDs | Different (contain timestamps) |
| Manifest hash | Different (contains timestamps) |

---

## 19. Test Strategy

### 19.1 Unit Tests

| Test | Purpose |
|---|---|
| `test_docker_adapter_available` | Verify Docker adapter probes correctly |
| `test_docker_adapter_compile` | Verify compilation inside Docker |
| `test_docker_adapter_execute` | Verify execution inside Docker |
| `test_docker_adapter_timeout` | Verify timeout produces ERROR |
| `test_docker_adapter_network_none` | Verify --network none in command |
| `test_docker_adapter_resource_limits` | Verify --memory/--cpus/--pids-limit in command |
| `test_docker_adapter_readonly_mount` | Verify -v :ro in command |
| `test_docker_adapter_cleanup` | Verify --rm flag present |
| `test_docker_adapter_unavailable` | Verify graceful handling when Docker unavailable |

### 19.2 Integration Tests

| Test | Purpose |
|---|---|
| `test_valid_candidate_verifies_via_docker` | End-to-end: valid candidate → VERIFIED |
| `test_mutated_candidate_fails_via_docker` | End-to-end: mutated candidate → FAILED |
| `test_timeout_produces_error_via_docker` | End-to-end: timeout → ERROR |
| `test_candidate_compilation_in_container` | Prove javac runs inside Docker, not on host |
| `test_candidate_execution_in_container` | Prove java runs inside Docker, not on host |
| `test_candidate_never_executes_on_host` | Architectural test: no host-side java/javac invocation for candidate code |
| `test_network_access_refused` | Candidate attempts network → connection refused |
| `test_memory_limit_enforced` | Candidate exceeds memory → OOM kill |
| `test_pid_limit_enforced` | Candidate forks excessively → PID limit hit |
| `test_cleanup_verified` | Container removed after execution (docker inspect returns error) |
| `test_artifact_hashes_match_host_vs_docker` | Reproducibility across execution modes |

### 19.3 Existing Tests Preserved

All 175 existing tests remain unchanged. The Docker adapter is additive, not replacement.

---

## 20. Exit Criteria

| # | Criterion | Binary Evidence Rule |
|---|---|---|
| 1 | Valid Java candidate compiles inside Docker | Docker command contains `javac`; compilation evidence from container output |
| 2 | Valid Java candidate executes inside Docker | Docker command contains `java`; execution evidence from container output |
| 3 | Candidate never executes directly on host | Adapter code path contains no host `subprocess.run` for `java` or `javac` against candidate source/classes; architectural test verifies execution boundary |
| 4 | Container is disposable per execution | `--rm` flag present in Docker command; `docker inspect` confirms removal |
| 5 | Java source is staged read-only | `-v :ro` present in Docker command; source hash unchanged after execution |
| 6 | Network is disabled | `--network none` present in Docker command; network access test confirms refusal |
| 7 | CPU/resource limits actually applied | `--cpus`, `--memory`, `--pids-limit` present in Docker command; adversarial tests confirm limits |
| 8 | Hard timeout actually enforced | timeout_applied=True when timeout occurs; container terminated and cleaned up |
| 9 | Timeout produces real termination evidence | termination_status="timeout" in evidence; container removed |
| 10 | Artifacts come from container execution | stdout/stderr hashes from subprocess.run output of docker run |
| 11 | Container cleanup occurs | `--rm` flag present; `docker inspect` confirms container removed |
| 12 | Failure paths captured in evidence | All error scenarios produce evidence with structured sandbox metadata |
| 13 | Repeated executions preserve deterministic artifact content | Artifact hashes match across runs |
| 14 | Existing comparator behavior unchanged | All 156 Phase-2 tests pass |
| 15 | Existing VERIFIED path remains VERIFIED | Valid candidate → VERIFIED via Docker |
| 16 | Existing mutation test remains FAILED | Mutated candidate → FAILED via Docker |
| 17 | No test bypasses production execution path | All tests use CandidateAdapter interface |
| 18 | No fabricated sandbox evidence | Evidence classified as requested/observed/tested; no unobservable claims |

---

## 21. Explicit Non-Goals

The following are explicitly OUT OF SCOPE for Phase 4:

| Non-Goal | Reason |
|---|---|
| Redesign validation engine | Engine works; only adapter changes |
| Redesign comparator framework | Comparators work; only execution changes |
| Redesign evidence model | Model works; only execution evidence changes |
| Add frontend | Not in Phase 4 scope |
| Add FastAPI | Not in Phase 4 scope |
| Add PostgreSQL | Not in Phase 4 scope |
| Add LLM integration | Not in Phase 4 scope |
| Add COBOL transformation | Not in Phase 4 scope |
| Add producer functionality | Not in Phase 4 scope |
| Custom Java Docker image | Use standard eclipse-temurin:21-jdk; custom image is a future optimization |
| Volume caching | Not needed for V1 single-workload-at-a-time |

---

## 22. Risks and Unresolved Questions

### 22.1 OPEN Decisions Requiring Owner Approval

| # | Question | Options | Recommendation |
|---|---|---|---|
| O1 | Java Docker image | A: eclipse-temurin:21-jdk (standard) B: custom image | A (simpler, proven) |
| O2 | Compilation boundary | A: javac inside Docker (preferred) B: host javac with security exception | A (maintains trust boundary) |
| O3 | Resource limits per-workload configurable? | A: Fixed limits B: Configurable per PipelineConfig | A for V1 |
| O4 | Should CandidateExecutionResult gain sandbox fields? | A: No (evidence in structured metadata) B: Yes (explicit fields) | B (Correction 2 requires structured evidence) |
| O5 | Digest pinning strategy for Java image | A: Pin at implementation time B: Configurable | A (matches oracle pattern) |

### 22.2 Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Docker not available on host | Cannot execute Java | Graceful UNAVAILABLE; host adapter as fallback |
| Image pull latency | Slow first execution | Pre-pull in setup; document requirement |
| Windows Docker path differences | subprocess flags differ | Use creationflags pattern from oracle adapter |
| Container timeout kill may not propagate exit code | Evidence incomplete | Capture what subprocess.run provides |
| Digest mismatch across environments | Reproducibility concern | Pin digest at implementation time |

---

## 23. Rollback / Failure Containment Strategy

| Scenario | Rollback |
|---|---|
| Docker adapter introduces regression | Pipeline accepts adapter injection; revert to host adapter |
| Docker adapter breaks existing tests | All 175 existing tests use host adapter; Docker tests are separate |
| Docker image unavailable | Adapter returns UNAVAILABLE; host adapter remains available |
| Evidence model incompatible | Evidence model unchanged; only execution path changes |

**Rollback is trivial**: the pipeline's adapter injection means reverting to `RealJavaCandidateAdapter` is a one-line change.

---

## 24. Files Proposed for Later Implementation

| File | Action | Purpose |
|---|---|---|
| `engine/candidate/docker_java_adapter.py` | CREATE | Docker-backed Java candidate adapter |
| `engine/pipeline.py` | MODIFY | Accept adapter injection parameter |
| `tests/integration/test_docker_java.py` | CREATE | Integration tests for Docker Java execution |
| `docs/PHASE3_COMPLETION_REPORT.md` | MODIFY | Update status after Phase 4 completion |

No other files require modification. The change is surgical.

---

## 25. Summary

### What Changes

- ONE new file: `engine/candidate/docker_java_adapter.py`
- ONE modification: `engine/pipeline.py` (adapter injection)
- ONE new test file: `tests/integration/test_docker_java.py`

### What Does NOT Change

- `engine/candidate/adapter.py` (ABC)
- `engine/candidate/java_adapter.py` (host fallback)
- `engine/evidence/models.py` (evidence model)
- `engine/verdict/derivation.py` (verdict logic)
- `engine/comparators/framework.py` (comparators)
- `contracts/` (all contracts)
- `docs/decisions/ADR-*` (all ADRs)
- All 175 existing tests

### Architectural Integrity

The engine remains the sole semantic trust boundary. The Docker adapter is an execution-boundary concern only. No evidence model changes. No verdict logic changes. No contract changes.

---

**PHASE 4A — JAVA SANDBOX ARCHITECTURE / EVIDENCE PLAN COMPLETE**

**NO PHASE 4 IMPLEMENTATION YET.**

**WAIT FOR EXPLICIT AUTHORIZATION AFTER REVIEW OF THE PLAN.**
