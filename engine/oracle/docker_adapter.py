"""Real Docker-backed Oracle adapter for GnuCOBOL execution.

Implements the oracle adapter with real Docker execution:
- container-per-execution
- read-only staged source
- no network
- resource limits
- hard timeout
- source hash before/after
- real stdout/stderr capture
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.identities import (
    AdapterStatus,
    ContentHash,
    ExecutionId,
    RunId,
)
from engine.oracle.adapter import (
    OracleAdapter,
    OracleAdapterConfig,
    OracleExecutionResult,
)


class DockerOracleAdapter(OracleAdapter):
    """Real Docker-backed GnuCOBOL oracle adapter."""

    V1_IMAGE = "gnucobol-ocesql:latest"
    V1_DIGEST = "sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780"

    def __init__(self, config: OracleAdapterConfig) -> None:
        super().__init__(config)
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
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

    def probe(self) -> AdapterStatus:
        if not self._docker_available:
            self._status = AdapterStatus.UNAVAILABLE
            return self._status

        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.V1_IMAGE],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                self._status = AdapterStatus.AVAILABLE
            else:
                self._status = AdapterStatus.UNAVAILABLE
        except Exception:
            self._status = AdapterStatus.UNAVAILABLE

        return self._status

    def _compute_source_hash(self, source_path: str) -> ContentHash:
        hasher = hashlib.sha256()
        path = Path(source_path)
        if path.is_file():
            hasher.update(path.read_bytes())
        elif path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    hasher.update(str(f.relative_to(path)).encode())
                    hasher.update(f.read_bytes())
        return ContentHash(digest=hasher.hexdigest())

    def execute(
        self,
        run_id: RunId,
        source_path: str,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> OracleExecutionResult:
        execution_id = ExecutionId(
            value=f"oracle-{run_id.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        start_time = datetime.now(timezone.utc)

        source_hash_before = self._compute_source_hash(source_path)

        if not self._docker_available:
            end_time = datetime.now(timezone.utc)
            return OracleExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                oracle_id=self._config.oracle_id,
                status=AdapterStatus.UNAVAILABLE,
                exit_code=None,
                stdout=b"",
                stderr=b"Docker is not available",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
                source_tree_hash_before=source_hash_before,
                source_tree_hash_after=source_hash_before,
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cobol_source = Path(source_path)
                if cobol_source.is_file():
                    dest = Path(tmpdir) / "src" / cobol_source.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(cobol_source.read_bytes())
                    container_src = "/workspace/src"
                else:
                    import shutil
                    dest = Path(tmpdir) / "src"
                    shutil.copytree(str(cobol_source), str(dest))
                    container_src = "/workspace/src"

                main_file = cobol_source.name if cobol_source.is_file() else None
                if main_file is None:
                    for f in Path(tmpdir, "src").glob("*.cob"):
                        main_file = f.name
                        break
                    for f in Path(tmpdir, "src").glob("*.cbl"):
                        main_file = f.name
                        break

                if main_file is None:
                    end_time = datetime.now(timezone.utc)
                    return OracleExecutionResult(
                        execution_id=execution_id,
                        run_id=run_id,
                        oracle_id=self._config.oracle_id,
                        status=AdapterStatus.FAILED,
                        exit_code=1,
                        stdout=b"",
                        stderr=b"No COBOL source file found",
                        start_time=start_time.isoformat(),
                        end_time=end_time.isoformat(),
                        termination_status="nonzero_exit",
                        timeout_applied=False,
                        source_tree_hash_before=source_hash_before,
                        source_tree_hash_after=source_hash_before,
                    )

                output_dir = Path(tmpdir) / "output"
                output_dir.mkdir()

                input_dir = Path(tmpdir) / "input"
                input_mount_args: list[str] = []
                if input_files:
                    input_dir.mkdir()
                    for name, content in input_files.items():
                        (input_dir / name).write_bytes(content)
                    input_mount_args = [
                        "-v", f"{os.path.abspath(input_dir)}:/workspace/input:ro",
                    ]

                compile_cmd = (
                    f"cd {container_src} && "
                    f"cobc -x {main_file} -o /tmp/oracle_prog && "
                    f"cd /workspace && "
                    f"/tmp/oracle_prog"
                )

                docker_cmd = [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--memory", "512m",
                    "--cpus", "1.0",
                    "--pids-limit", "256",
                    "--workdir", "/workspace",
                    "-v", f"{os.path.abspath(tmpdir)}/src:{container_src}:ro",
                    "-v", f"{os.path.abspath(output_dir)}:/workspace/output",
                    *input_mount_args,
                    self.V1_IMAGE,
                    "sh", "-c", compile_cmd,
                ]

                try:
                    proc = subprocess.run(
                        docker_cmd,
                        capture_output=True,
                        timeout=self._config.timeout_seconds + 5,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    stdout = proc.stdout
                    stderr = proc.stderr
                    exit_code = proc.returncode
                    termination = "normal" if exit_code == 0 else "nonzero_exit"

                except subprocess.TimeoutExpired:
                    stdout = b""
                    stderr = b"Oracle execution timeout"
                    exit_code = None
                    termination = "timeout"

                generated_files: dict[str, bytes] = {}
                if output_dir.is_dir():
                    for f in sorted(output_dir.rglob("*")):
                        if f.is_file():
                            rel = f.name
                            generated_files[rel] = f.read_bytes()

            end_time = datetime.now(timezone.utc)
            source_hash_after = self._compute_source_hash(source_path)

            return OracleExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                oracle_id=self._config.oracle_id,
                status=AdapterStatus.SUCCEEDED if exit_code == 0 else AdapterStatus.FAILED,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status=termination,
                timeout_applied=termination == "timeout",
                timeout_duration=self._config.timeout_seconds,
                generated_files=generated_files if generated_files else None,
                source_tree_hash_before=source_hash_before,
                source_tree_hash_after=source_hash_after,
            )

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            return OracleExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                oracle_id=self._config.oracle_id,
                status=AdapterStatus.FAILED,
                exit_code=None,
                stdout=b"",
                stderr=str(e).encode(),
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
                source_tree_hash_before=source_hash_before,
                source_tree_hash_after=source_hash_before,
            )
