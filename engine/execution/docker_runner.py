"""Real Docker execution engine for the validation engine.

.. deprecated:: BL-117 (2026-10-21)
    This module has zero importers outside itself and is NOT the canonical
    execution path. The canonical Docker execution is in
    ``engine/candidate/docker_spring_boot_adapter.py`` and
    ``engine/oracle/docker_adapter.py``. This module is retained for
    historical reference and test-only contracts; do not wire new code to it.

Implements container-per-execution with:
- read-only staged source
- no network
- resource limits
- hard timeout
- isolated working directory
- cleanup after execution
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from engine.docker_cli import check_docker_available
from engine.domain.identities import ContentHash
from engine.execution.abstractions import (
    ExecutionCommand,
    ExecutionResult,
)
from engine.execution.sandbox_paths import to_host_path
from engine.source_hash import compute_source_tree_hash


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
        return check_docker_available()

    @property
    def available(self) -> bool:
        return self._docker_available

    def compute_source_hash(self, source_path: str) -> ContentHash:
        """Compute SHA-256 hash of source directory contents."""
        return compute_source_tree_hash(source_path)

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
            # Translate container-visible staging paths to the host-visible
            # bind source so the host daemon resolves the intended workspace
            # (identity mapping outside the configured staging root).
            docker_cmd.extend(["-v", f"{to_host_path(host_path)}:{container_path}:ro"])

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
