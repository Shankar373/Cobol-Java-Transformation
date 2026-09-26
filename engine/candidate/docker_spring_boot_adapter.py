"""Docker-backed Spring Boot candidate adapter with Maven build and JAR execution.

Build phase:
- Maven builds the Spring Boot project inside a Docker container
- Source is mounted read-write (Maven needs to write target/)
- Offline mode with pre-cached dependencies

Execution phase:
- java -jar runs inside a disposable Docker container
- JAR is mounted read-only
- Network disabled (--network none)
- Resource limits (--memory, --cpus, --pids-limit)

Security model:
- Container-per-execution (--rm)
- Network disabled for execution (--network none)
- Resource limits for execution
- Read-only JAR mount for execution
- Hard timeout with explicit termination/cleanup lifecycle
- Fail-closed immutable image provenance:
  - registry RepoDigest takes precedence when Docker reports one;
  - locally built images without a RepoDigest use their immutable Image ID;
  - runtime execution additionally requires a RepoDigest identity;
  - expected and observed identities must match exactly.
"""

from __future__ import annotations

import hashlib
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
from engine.candidate.image_provenance import (
    DEFAULT_PROVENANCE_PATH,
    DockerImageObservation,
    load_adapter_provenance,
    resolve_docker_image_identity,
    verify_image_identity,
)
from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    RunId,
)


@dataclass(frozen=True)
class DockerSpringBootConfig:
    """Configuration for Docker-backed Spring Boot candidate adapter.

    ``build_identity`` is the exact immutable identity provisioned for the
    current deployment: a registry RepoDigest when Docker reports one, or the
    immutable local Image ID for an image built locally. It may be supplied
    directly or through a validated provenance record at ``provenance_path``.
    An empty build identity always fails closed.
    """
    build_image: str = "maven-offline-springboot:latest"
    build_identity: str = ""
    runtime_image: str = "eclipse-temurin:21-jdk"
    runtime_digest: str = "eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026"
    provenance_path: str = str(DEFAULT_PROVENANCE_PATH)
    build_timeout_seconds: int = 240
    execution_timeout_seconds: int = 30
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    pids_limit: int = 256


class DockerSpringBootCandidateAdapter(CandidateAdapter):
    """Docker-backed Spring Boot candidate adapter.

    Build phase: Maven builds inside Docker container.
    Execution phase: java -jar inside disposable Docker container.
    """

    def __init__(self, config: DockerSpringBootConfig | None = None) -> None:
        super().__init__()
        self._config = config or DockerSpringBootConfig()
        self._docker_available = self._check_docker()
        self._build_observation = DockerImageObservation(
            requested_ref=self._config.build_image
        )
        self._runtime_observation = DockerImageObservation(
            requested_ref=self._config.runtime_image
        )
        self._java_version = ""
        self._maven_version = ""

        if self._docker_available:
            self._build_observation = self._resolve_build_observation()
            self._runtime_observation = self._resolve_runtime_observation()
            self._java_version = self._detect_java_version()
            self._maven_version = self._detect_maven_version()

            build_verified = verify_image_identity(
                expected_identity=self._expected_build_identity(),
                observed=self._build_observation,
                require_repo_digest=False,
            )
            runtime_verified = verify_image_identity(
                expected_identity=self._config.runtime_digest,
                observed=self._runtime_observation,
                require_repo_digest=True,
            )
            self._status = (
                AdapterStatus.AVAILABLE
                if build_verified and runtime_verified
                else AdapterStatus.UNAVAILABLE
            )
        else:
            self._status = AdapterStatus.UNAVAILABLE

    def _expected_build_identity(self) -> str:
        """Return the explicit provisioned build identity, if any."""
        explicit_identity = self._config.build_identity.strip()
        if explicit_identity:
            return explicit_identity
        if not self._config.provenance_path.strip():
            return ""
        try:
            provenance = load_adapter_provenance(self._config.provenance_path)
        except (OSError, ValueError):
            return ""
        if provenance.build_image.strip() != self._config.build_image.strip():
            return ""
        return provenance.build_identity

    def _check_docker(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _resolve_image_observation(self, image: str) -> DockerImageObservation:
        """Resolve immutable Docker identity evidence for one image reference."""
        return resolve_docker_image_identity(image)

    def _resolve_build_observation(self) -> DockerImageObservation:
        return self._resolve_image_observation(self._config.build_image)

    def _resolve_runtime_observation(self) -> DockerImageObservation:
        return self._resolve_image_observation(self._config.runtime_image)

    def _detect_java_version(self) -> str:
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "--network", "none",
                 self._config.runtime_image, "java", "-version"],
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                stderr = result.stderr.decode(errors="replace")
                for line in stderr.splitlines():
                    if "version" in line:
                        return line.strip()
            return ""
        except Exception:
            return ""

    def _detect_maven_version(self) -> str:
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "--network", "none",
                 self._config.build_image, "mvn", "-version"],
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                stdout = result.stdout.decode(errors="replace")
                for line in stdout.splitlines():
                    if "Maven" in line:
                        return line.strip()
            return ""
        except Exception:
            return ""

    @property
    def available(self) -> bool:
        return self._status == AdapterStatus.AVAILABLE

    @property
    def build_identity(self) -> str:
        return self._build_observation.identity

    @property
    def build_identity_kind(self) -> str:
        return self._build_observation.identity_kind

    @property
    def build_resolved_digest(self) -> str:
        """Compatibility alias for the selected immutable build identity."""
        return self._build_observation.identity

    @property
    def runtime_identity(self) -> str:
        return self._runtime_observation.identity

    @property
    def runtime_identity_kind(self) -> str:
        return self._runtime_observation.identity_kind

    @property
    def runtime_resolved_digest(self) -> str:
        """Compatibility alias for the selected immutable runtime identity."""
        return self._runtime_observation.identity

    @property
    def java_version(self) -> str:
        return self._java_version

    @property
    def maven_version(self) -> str:
        return self._maven_version

    @staticmethod
    def _cleanup_container(container_name: str) -> tuple[bool, str]:
        _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
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

        try:
            inspect_result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                timeout=10,
                creationflags=_flags,
            )
            exists = inspect_result.returncode == 0
        except Exception:
            exists = True

        removed = rm_ok and not exists
        detail = f"stop={stop_ok}, rm={rm_ok}, exists_after={exists}"
        return removed, detail

    def probe(self) -> AdapterStatus:
        return self._status

    def validate_candidate(self, candidate_path: str, manifest: CandidateManifest) -> list[str]:
        violations = []
        missing = manifest.validate()
        if missing:
            violations.append(f"Missing manifest fields: {', '.join(missing)}")

        candidate_dir = Path(candidate_path)
        pom_path = candidate_dir / "pom.xml"
        if not pom_path.exists():
            violations.append("No pom.xml found (Spring Boot project required)")

        for rel_path in manifest.generated_files:
            full_path = candidate_dir / rel_path
            if not full_path.exists():
                violations.append(f"Declared file not found: {rel_path}")

        return violations

    def compile(self, candidate_path: str, manifest: CandidateManifest) -> CompilationResult:
        """Build Spring Boot project using Maven inside Docker.

        Source is mounted read-write (Maven needs to write target/).
        Offline mode with pre-cached dependencies.
        """
        if not self.available:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=("Docker or Maven image not available",),
            )

        start_time = datetime.now(timezone.utc)
        _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                candidate_dir = Path(candidate_path)

                # Copy project to temp directory (writable for Maven)
                staged_project = Path(tmpdir) / "project"
                staged_project.mkdir()

                # Copy all files except target/
                for item in candidate_dir.rglob("*"):
                    if item.is_file() and "target" not in item.parts:
                        rel = item.relative_to(candidate_dir)
                        dest = staged_project / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(item.read_bytes())

                # Output directory for JAR
                output_dir = Path(tmpdir) / "output"
                output_dir.mkdir()

                container_name = f"maven-{uuid.uuid4().hex[:12]}"

                # Maven runs as root in the build image so it can use the
                # pre-cached /root/.m2 repository. Because the project and output
                # directories are bind-mounted from the host, Maven can otherwise
                # leave root-owned files behind and make TemporaryDirectory cleanup
                # fail on Linux CI. Reconcile ownership before the container exits.
                maven_cmd = "mvn -o -B -Dmaven.test.skip=true package"
                host_uid = os.getuid() if hasattr(os, "getuid") else None
                host_gid = os.getgid() if hasattr(os, "getgid") else None

                if host_uid is not None and host_gid is not None:
                    build_shell = (
                        f"{maven_cmd}; build_status=$?; "
                        f"if [ $build_status -eq 0 ]; then "
                        f"jar_status=0; "
                        f"for jar in target/*.jar; do "
                        f"if [ -f \"$jar\" ] && [ \"$jar\" != \"*.jar\" ]; then "
                        f"cp \"$jar\" /workspace/output/ || jar_status=$?; "
                        f"fi; "
                        f"done; "
                        f"if [ $jar_status -ne 0 ]; then build_status=$jar_status; fi; "
                        f"fi; "
                        f"chown -R {host_uid}:{host_gid} /workspace/project /workspace/output "
                        f"2>/dev/null || true; "
                        f"exit $build_status"
                    )
                else:
                    # Docker Desktop/Windows does not expose POSIX uid/gid semantics
                    # through this process; retain the existing build behavior there.
                    build_shell = (
                        f"{maven_cmd} && "
                        f"cp target/*.jar /workspace/output/ 2>/dev/null || true"
                    )

                docker_cmd = [
                    "docker", "run", "--rm",
                    "--name", container_name,
                    "--network", "none",
                    "--memory", self._config.memory_limit,
                    "--cpus", self._config.cpu_limit,
                    "--pids-limit", str(self._config.pids_limit),
                    "--workdir", "/workspace/project",
                    "-v", f"{os.path.abspath(staged_project)}:/workspace/project",
                    "-v", f"{os.path.abspath(output_dir)}:/workspace/output",
                    self._config.build_image,
                    "sh", "-c", build_shell,
                ]

                proc = None
                try:
                    proc = subprocess.run(
                        docker_cmd,
                        capture_output=True,
                        timeout=self._config.build_timeout_seconds + 10,
                        creationflags=_flags,
                    )

                    if proc.returncode != 0:
                        stdout = proc.stdout.decode(errors="replace")
                        stderr = proc.stderr.decode(errors="replace")
                        diagnostics = "\n".join(
                            part for part in (stdout, stderr) if part
                        )
                        return CompilationResult(
                            success=False,
                            class_files={},
                            compilation_errors=(f"Maven build failed: {diagnostics}",),
                            compilation_time_ms=int(
                                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                            ),
                        )

                    # Collect produced JAR
                    class_files = {}
                    jar_files = list(output_dir.rglob("*.jar"))
                    for jar in jar_files:
                        if jar.name.endswith(".jar") and not jar.name.endswith(".original"):
                            rel = jar.name
                            jar_bytes = jar.read_bytes()
                            class_files[rel] = jar_bytes
                            # Write JAR back to candidate_path so execute() can find it
                            target_dir = Path(candidate_path) / "target"
                            target_dir.mkdir(parents=True, exist_ok=True)
                            (target_dir / jar.name).write_bytes(jar_bytes)

                    if not class_files:
                        return CompilationResult(
                            success=False,
                            class_files={},
                            compilation_errors=("Maven build produced no JAR files",),
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
                    if proc is not None:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except Exception:
                            pass

                    self._cleanup_container(container_name)

                    return CompilationResult(
                        success=False,
                        class_files={},
                        compilation_errors=("Maven build timed out",),
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
        """Execute compiled Spring Boot JAR inside Docker container.

        java -jar runs INSIDE the container.
        JAR is mounted read-only.
        Full timeout/termination/cleanup lifecycle implemented.
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
                stderr=b"Docker or Maven image not available",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Stage JAR files
                staged_jars = Path(tmpdir) / "jars"
                staged_jars.mkdir()

                compiled_dir = Path(compiled_path)
                jar_name = None
                for f in compiled_dir.rglob("*.jar"):
                    if not f.name.endswith(".original"):
                        dest = staged_jars / f.name
                        dest.write_bytes(f.read_bytes())
                        jar_name = f.name

                if not jar_name:
                    return CandidateExecutionResult(
                        execution_id=execution_id,
                        run_id=run_id,
                        status=AdapterStatus.FAILED,
                        exit_code=None,
                        stdout=b"",
                        stderr=b"No JAR file found in compiled path",
                        start_time=start_time.isoformat(),
                        end_time=datetime.now(timezone.utc).isoformat(),
                        termination_status="error",
                        timeout_applied=False,
                    )

                # Output directory (writable)
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

                container_name = f"java-{uuid.uuid4().hex[:12]}"

                java_cmd = f"java -jar /workspace/jars/{jar_name}"

                docker_cmd = [
                    "docker", "run", "--rm",
                    "--name", container_name,
                    "--network", "none",
                    "--memory", self._config.memory_limit,
                    "--cpus", self._config.cpu_limit,
                    "--pids-limit", str(self._config.pids_limit),
                    "--workdir", "/workspace",
                    "-v", f"{os.path.abspath(staged_jars)}:/workspace/jars:ro",
                    "-v", f"{os.path.abspath(output_dir)}:/workspace/output",
                    *input_mount_args,
                    self._config.runtime_image,
                    "sh", "-c", java_cmd,
                ]

                proc = None
                stdout = b""
                stderr = b""
                exit_code: int | None = None
                termination = "error"

                try:
                    proc = subprocess.run(
                        docker_cmd,
                        capture_output=True,
                        timeout=self._config.execution_timeout_seconds + 5,
                        creationflags=_flags,
                    )
                    stdout = proc.stdout
                    stderr = proc.stderr
                    exit_code = proc.returncode
                    termination = "normal" if exit_code == 0 else "nonzero_exit"

                except subprocess.TimeoutExpired:
                    if proc is not None:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except Exception:
                            pass

                    stdout = proc.stdout if proc else b""

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
                    timeout_duration=self._config.execution_timeout_seconds if termination == "timeout" else None,
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
