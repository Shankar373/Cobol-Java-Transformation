"""Real Docker execution engine for the validation engine.

Implements container-per-execution with:
- read-only staged source
- no network
- resource limits
- hard timeout
- isolated working directory
- cleanup after execution
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.identities import ContentHash
from engine.execution.abstractions import (
    ExecutionCommand,
    ExecutionResult,
)


@dataclass(frozen=True)
class DockerRunConfig:
    """Configuration for a Docker run."""
    image: str
    command: str
    arguments: tuple[str, ...] = ()
    mount_ro: tuple[str, str] = ()  # (host_path, container_path)
    network_disabled: bool = True
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    pids_limit: int = 256
    timeout_seconds: int = 30
    workdir: str = "/workspace"
    environment: dict[str, str] = field(default_factory=dict)


class DockerRunner:
    """Real Docker execution engine."""

    def __init__(self) -> None:
        self._docker_available = self._check_docker()

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

    @property
    def available(self) -> bool:
        return self._docker_available

    def compute_source_hash(self, source_path: str) -> ContentHash:
        """Compute SHA-256 hash of source directory contents."""
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

    def execute(self, config: DockerRunConfig) -> ExecutionResult:
        """Execute a command in a Docker container."""
        if not self._docker_available:
            raise RuntimeError("Docker is not available")

        start_time = datetime.now(timezone.utc)

        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none" if config.network_disabled else "bridge",
            "--memory", config.memory_limit,
            "--cpus", config.cpu_limit,
            "--pids-limit", str(config.pids_limit),
            "--workdir", config.workdir,
        ]

        for host_path, container_path in config.mount_ro:
            docker_cmd.extend(["-v", f"{host_path}:{container_path}:ro"])

        for key, value in config.environment.items():
            docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.append(config.image)
        docker_cmd.extend([config.command] + list(config.arguments))

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=config.timeout_seconds + 5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            end_time = datetime.now(timezone.utc)
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
            termination = "normal" if exit_code == 0 else "nonzero_exit"

        except subprocess.TimeoutExpired:
            end_time = datetime.now(timezone.utc)
            stdout = b""
            stderr = b"Timeout exceeded"
            exit_code = None
            termination = "timeout"

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            stdout = b""
            stderr = str(e).encode()
            exit_code = None
            termination = "error"

        return ExecutionResult(
            command=ExecutionCommand(
                command="docker",
                arguments=tuple(docker_cmd[1:]),
            ),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            termination_status=termination,
            timeout_applied=termination == "timeout",
            timeout_duration=config.timeout_seconds,
        )
