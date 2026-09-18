"""Docker-backed Java candidate adapter with container-per-execution.

Both javac compilation AND java execution occur inside disposable Docker
containers. Candidate Java code NEVER executes directly on the host.

Security model:
- Container-per-execution (--rm)
- Network disabled (--network none)
- Resource limits (--memory, --cpus, --pids-limit)
- Read-only staged source (-v :ro)
- Hard timeout with explicit termination/cleanup lifecycle
- Structured sandbox evidence
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.candidate.adapter import (
    CandidateAdapter,
    CandidateExecutionResult,
    CandidateManifest,
    CompilationResult,
)
from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    RunId,
)

# ---------------------------------------------------------------------------
# Structured sandbox evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DockerSandboxEvidence:
    """Structured evidence of sandbox properties for a single execution."""

    # Container identity
    container_image: str
    container_image_digest: str
    container_id: str | None

    # Requested configuration
    requested_network_mode: str
    requested_memory_limit: str
    requested_cpu_limit: str
    requested_pids_limit: int
    requested_timeout_seconds: int
    requested_mounts: tuple[str, ...]

    # Observed execution properties
    observed_exit_code: int | None
    observed_termination_status: str
    observed_stdout_size: int
    observed_stderr_size: int
    observed_duration_ms: int

    # Sandbox verification
    compilation_occurred_in_container: bool
    execution_occurred_in_container: bool

    # Cleanup
    cleanup_flag_present: bool
    container_removed: bool


# ---------------------------------------------------------------------------
# Docker Java adapter configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DockerJavaConfig:
    """Configuration for Docker-backed Java candidate adapter."""
    image: str = "eclipse-temurin:21-jdk"
    digest: str = ""  # Resolved at init; fail-closed if empty
    timeout_seconds: int = 30
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    pids_limit: int = 256


# ---------------------------------------------------------------------------
# Docker Java candidate adapter
# ---------------------------------------------------------------------------

class DockerJavaCandidateAdapter(CandidateAdapter):
    """Docker-backed Java candidate adapter. Container-per-execution.

    Both compilation and execution occur inside disposable Docker containers.
    Candidate Java code NEVER executes directly on the host.
    """

    def __init__(self, config: DockerJavaConfig | None = None) -> None:
        super().__init__()
        self._config = config or DockerJavaConfig()
        self._docker_available = self._check_docker()
        self._resolved_digest: str = ""
        self._java_version: str = ""

        if self._docker_available:
            self._resolved_digest = self._resolve_image_digest()
            self._java_version = self._detect_java_version()
            if self._config.digest and self._resolved_digest != self._config.digest:
                self._status = AdapterStatus.UNAVAILABLE
            elif self._resolved_digest:
                self._status = AdapterStatus.AVAILABLE
            else:
                self._status = AdapterStatus.UNAVAILABLE
        else:
            self._status = AdapterStatus.UNAVAILABLE

    def _check_docker(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _resolve_image_digest(self) -> str:
        """Resolve the image to an immutable digest. Fail-closed if unable."""
        try:
            # First try docker inspect on the local image
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", self._config.image],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                output = result.stdout.decode(errors="replace").strip()
                if "sha256:" in output:
                    return output

            # Try docker image inspect
            result = subprocess.run(
                ["docker", "image", "inspect", self._config.image],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                if data and "RepoDigests" in data[0]:
                    for digest_ref in data[0]["RepoDigests"]:
                        if "sha256:" in digest_ref:
                            return digest_ref

            return ""
        except Exception:
            return ""

    def _detect_java_version(self) -> str:
        """Detect Java version inside the container."""
        try:
            result = subprocess.run(
                [
                    "docker", "run", "--rm", "--network", "none",
                    self._config.image, "java", "-version",
                ],
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                stderr = result.stderr.decode(errors="replace")
                # Parse version string like: openjdk version "21.0.4" ...
                for line in stderr.splitlines():
                    if "version" in line:
                        return line.strip()
            return ""
        except Exception:
            return ""

    @property
    def available(self) -> bool:
        return self._status == AdapterStatus.AVAILABLE

    @property
    def resolved_digest(self) -> str:
        return self._resolved_digest

    @property
    def java_version(self) -> str:
        return self._java_version

    @staticmethod
    def _cleanup_container(container_name: str) -> tuple[bool, str]:
        """Explicitly stop and remove a container by name.

        Returns (removed, detail) where removed indicates success and
        detail provides forensic information about what happened.
        """
        _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        # Step 1: Stop the container (SIGTERM, then SIGKILL after grace)
        try:
            stop_result = subprocess.run(
                ["docker", "stop", "--time", "5", container_name],
                capture_output=True,
                timeout=15,
                creationflags=_flags,
            )
            stop_ok = stop_result.returncode == 0
        except Exception:
            stop_ok = False

        # Step 2: Remove the container (force remove)
        try:
            rm_result = subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
                creationflags=_flags,
            )
            rm_ok = rm_result.returncode == 0
        except Exception:
            rm_ok = False

        # Step 3: Verify removal
        try:
            inspect_result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                timeout=10,
                creationflags=_flags,
            )
            exists = inspect_result.returncode == 0
        except Exception:
            exists = True  # Assume it exists if we can't check

        removed = rm_ok and not exists
        detail = f"stop={stop_ok}, rm={rm_ok}, exists_after={exists}"
        return removed, detail

    def probe(self) -> AdapterStatus:
        return self._status

    def validate_candidate(self, candidate_path: str, manifest: CandidateManifest) -> list[str]:
        """Validate candidate package."""
        violations = []
        missing = manifest.validate()
        if missing:
            violations.append(f"Missing manifest fields: {', '.join(missing)}")
        if manifest.dependencies:
            violations.append("V1 does not allow external dependencies")
        if not manifest.generated_files:
            violations.append("No generated files declared")
        if not manifest.entrypoint:
            violations.append("No entrypoint declared")

        candidate_dir = Path(candidate_path)
        for rel_path in manifest.generated_files:
            full_path = candidate_dir / rel_path
            if not full_path.exists():
                violations.append(f"Declared file not found: {rel_path}")

        return violations

    def compile(self, candidate_path: str, manifest: CandidateManifest) -> CompilationResult:
        """Compile candidate Java source inside a Docker container.

        javac runs INSIDE the container. Candidate source is mounted read-only.
        """
        if not self.available:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=("Docker or Java image not available",),
            )

        start_time = datetime.now(timezone.utc)
        _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Stage candidate source
                candidate_dir = Path(candidate_path)
                staged_source = Path(tmpdir) / "source"
                staged_source.mkdir()

                java_files = []
                for rel_path in manifest.generated_files:
                    src = candidate_dir / rel_path
                    if src.suffix == ".java":
                        dest = staged_source / rel_path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(src.read_bytes())
                        java_files.append(f"/workspace/source/{rel_path}")

                if not java_files:
                    return CompilationResult(
                        success=False,
                        class_files={},
                        compilation_errors=("No .java files found",),
                    )

                # Output directory (container-local, writable)
                staged_output = Path(tmpdir) / "classes"
                staged_output.mkdir()

                # Build javac command
                javac_args = " ".join(java_files)
                compile_cmd = f"javac -d /workspace/classes {javac_args}"

                # Deterministic container name for cleanup tracking
                container_name = f"javac-{uuid.uuid4().hex[:12]}"

                # Docker command: compile inside container
                docker_cmd = [
                    "docker", "run", "--rm",
                    "--name", container_name,
                    "--network", "none",
                    "--memory", self._config.memory_limit,
                    "--cpus", self._config.cpu_limit,
                    "--pids-limit", str(self._config.pids_limit),
                    "--workdir", "/workspace",
                    "-v", f"{os.path.abspath(staged_source)}:/workspace/source:ro",
                    "-v", f"{os.path.abspath(staged_output)}:/workspace/classes",
                    self._config.image,
                    "sh", "-c", compile_cmd,
                ]

                try:
                    proc = subprocess.run(
                        docker_cmd,
                        capture_output=True,
                        timeout=self._config.timeout_seconds + 5,
                        creationflags=_flags,
                    )

                    if proc.returncode != 0:
                        return CompilationResult(
                            success=False,
                            class_files={},
                            compilation_errors=(proc.stderr.decode(errors="replace"),),
                            compilation_time_ms=int(
                                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                            ),
                        )

                    # Collect compiled class files
                    class_files = {}
                    for f in staged_output.rglob("*.class"):
                        rel = f.relative_to(staged_output)
                        class_files[str(rel)] = f.read_bytes()

                    if not class_files:
                        return CompilationResult(
                            success=False,
                            class_files={},
                            compilation_errors=("Compilation produced no .class files",),
                            compilation_time_ms=int(
                                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                            ),
                        )

                    return CompilationResult(
                        success=True,
                        class_files=class_files,
                        compilation_time_ms=int(
                            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                        ),
                    )

                except subprocess.TimeoutExpired:
                    # Kill docker client process
                    if proc is not None:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except Exception:
                            pass

                    # Explicit container cleanup (do not rely on --rm alone)
                    self._cleanup_container(container_name)

                    return CompilationResult(
                        success=False,
                        class_files={},
                        compilation_errors=("Compilation timed out",),
                        compilation_time_ms=int(
                            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                        ),
                    )

        except Exception as e:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=(str(e),),
                compilation_time_ms=int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                ),
            )

    def execute(
        self,
        run_id: RunId,
        compiled_path: str,
        manifest: CandidateManifest,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> CandidateExecutionResult:
        """Execute compiled candidate inside a Docker container.

        java runs INSIDE the container. Compiled classes are mounted read-only.
        Full timeout/termination/cleanup lifecycle implemented.

        On timeout:
        1. Kill docker client process
        2. Explicitly stop the container by name
        3. Explicitly remove the container by name
        4. Verify container is gone
        5. Record cleanup outcome
        """
        execution_id = ExecutionId(
            value=f"candidate-{run_id.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        start_time = datetime.now(timezone.utc)
        _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        if not self.available:
            end_time = datetime.now(timezone.utc)
            return CandidateExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                status=AdapterStatus.UNAVAILABLE,
                exit_code=None,
                stdout=b"",
                stderr=b"Docker or Java image not available",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Stage compiled classes
                staged_classes = Path(tmpdir) / "classes"
                staged_classes.mkdir()

                compiled_dir = Path(compiled_path)
                for f in compiled_dir.rglob("*.class"):
                    rel = f.relative_to(compiled_dir)
                    dest = staged_classes / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(f.read_bytes())

                entrypoint_class = manifest.entrypoint.removesuffix(".java")

                # Java command inside container
                java_cmd = f"java -cp /workspace/classes {entrypoint_class}"

                # Output directory (container-local, writable)
                output_dir = Path(tmpdir) / "output"
                output_dir.mkdir()

                # Input files (optional, mounted read-only)
                input_mount_args: list[str] = []
                if input_files:
                    input_dir = Path(tmpdir) / "input"
                    input_dir.mkdir()
                    for name, content in input_files.items():
                        (input_dir / name).write_bytes(content)
                    input_mount_args = [
                        "-v", f"{os.path.abspath(input_dir)}:/workspace/input:ro",
                    ]

                # Deterministic container name for explicit cleanup
                container_name = f"java-{uuid.uuid4().hex[:12]}"

                # Docker command: execute inside container
                docker_cmd = [
                    "docker", "run", "--rm",
                    "--name", container_name,
                    "--network", "none",
                    "--memory", self._config.memory_limit,
                    "--cpus", self._config.cpu_limit,
                    "--pids-limit", str(self._config.pids_limit),
                    "--workdir", "/workspace",
                    "-v", f"{os.path.abspath(staged_classes)}:/workspace/classes:ro",
                    "-v", f"{os.path.abspath(output_dir)}:/workspace/output",
                    *input_mount_args,
                    self._config.image,
                    "sh", "-c", java_cmd,
                ]

                # Execute with timeout lifecycle
                proc = None
                stdout = b""
                stderr = b""
                exit_code: int | None = None
                termination = "error"

                try:
                    proc = subprocess.run(
                        docker_cmd,
                        capture_output=True,
                        timeout=self._config.timeout_seconds + 5,
                        creationflags=_flags,
                    )
                    stdout = proc.stdout
                    stderr = proc.stderr
                    exit_code = proc.returncode
                    termination = "normal" if exit_code == 0 else "nonzero_exit"

                except subprocess.TimeoutExpired:
                    # Step 1: Kill the docker client process
                    if proc is not None:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except Exception:
                            pass

                    stdout = proc.stdout if proc else b""

                    # Step 2: Explicitly stop and remove the container
                    # Do NOT rely on --rm alone — proc.kill() kills the client
                    # but the container persists on the daemon.
                    _cleanup_removed, cleanup_detail = self._cleanup_container(
                        container_name
                    )

                    stderr = (
                        b"Java execution timeout; "
                        + f"cleanup={cleanup_detail}".encode()
                    )
                    exit_code = None
                    termination = "timeout"

                except Exception as e:
                    stdout = b""
                    stderr = str(e).encode()
                    exit_code = None
                    termination = "error"

                generated_files: dict[str, bytes] = {}
                if output_dir.is_dir():
                    for f in sorted(output_dir.rglob("*")):
                        if f.is_file():
                            rel = f.name
                            generated_files[rel] = f.read_bytes()

                end_time = datetime.now(timezone.utc)

                # Determine adapter status
                if termination == "timeout":
                    status = AdapterStatus.FAILED
                elif exit_code == 0:
                    status = AdapterStatus.SUCCEEDED
                else:
                    status = AdapterStatus.FAILED

                return CandidateExecutionResult(
                    execution_id=execution_id,
                    run_id=run_id,
                    status=status,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    termination_status=termination,
                    timeout_applied=termination == "timeout",
                    timeout_duration=self._config.timeout_seconds if termination == "timeout" else None,
                    generated_files=generated_files if generated_files else None,
                )

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            return CandidateExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                status=AdapterStatus.FAILED,
                exit_code=None,
                stdout=b"",
                stderr=str(e).encode(),
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
            )
