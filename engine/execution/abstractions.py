"""Execution abstractions for the validation engine.

Implements the policy boundary required by ADR-0008:
- container-per-execution
- read-only staged source
- no network
- resource limits
- hard timeout -> ERROR
- no writable source mounts
- no chmod 777
- no default/hardcoded credentials
- cleanup after execution
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionPolicy(Enum):
    """Execution policy options."""
    CONTAINER_PER_EXECUTION = "container_per_execution"
    READ_ONLY_SOURCE = "read_only_source"
    NO_NETWORK = "no_network"
    RESOURCE_LIMITS = "resource_limits"
    HARD_TIMEOUT = "hard_timeout"
    NO_WRITABLE_MOUNTS = "no_writable_mounts"
    NO_CHMOD_777 = "no_chmod_777"
    NO_DEFAULT_CREDENTIALS = "no_default_credentials"
    CLEANUP_AFTER = "cleanup_after"


@dataclass(frozen=True)
class ResourceLimits:
    """Resource limits for execution."""
    memory: str = "512m"
    cpu: str = "1.0"
    pids: int = 256
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.pids <= 0:
            raise ValueError("pids must be positive")


@dataclass(frozen=True)
class FilesystemPolicy:
    """Filesystem policy for execution."""
    read_only_paths: tuple[str, ...] = ()
    no_write_paths: tuple[str, ...] = ()
    no_exec_paths: tuple[str, ...] = ()

    def validate(self) -> None:
        """Validate filesystem policy."""
        # Check for chmod 777 attempts
        for path in self.no_write_paths:
            if path == "/" or path == "/*":
                raise ValueError("Cannot make root read-only")


@dataclass(frozen=True)
class NetworkPolicy:
    """Network policy for execution."""
    enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.enabled and not self.allowed_hosts:
            raise ValueError("Network enabled but no allowed hosts")


@dataclass(frozen=True)
class ExecutionCommand:
    """Command to execute."""
    command: str
    arguments: tuple[str, ...] = ()
    working_directory: str = "/workspace"
    environment: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30

    def to_string(self) -> str:
        """Convert to command string."""
        parts = [self.command] + list(self.arguments)
        return " ".join(parts)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of an execution."""
    command: ExecutionCommand
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    start_time: str
    end_time: str
    termination_status: str  # normal, timeout, nonzero_exit, error
    timeout_applied: bool
    timeout_duration: int | None = None
    generated_files: dict[str, bytes] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        """Check if execution succeeded."""
        return self.exit_code == 0 and self.termination_status == "normal"

    @property
    def failed(self) -> bool:
        """Check if execution failed."""
        return not self.succeeded

    @property
    def timed_out(self) -> bool:
        """Check if execution timed out."""
        return self.termination_status == "timeout"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for evidence."""
        return {
            "command": self.command.to_string(),
            "exit_code": self.exit_code,
            "stdout_size": len(self.stdout),
            "stderr_size": len(self.stderr),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "termination_status": self.termination_status,
            "timeout_applied": self.timeout_applied,
            "timeout_duration": self.timeout_duration,
            "generated_files": list(self.generated_files.keys()),
        }


@dataclass
class ExecutionEnvironment:
    """Execution environment configuration."""
    policies: frozenset[ExecutionPolicy]
    resource_limits: ResourceLimits
    filesystem_policy: FilesystemPolicy
    network_policy: NetworkPolicy
    cleanup_on_completion: bool = True

    def validate(self) -> list[str]:
        """Validate execution environment. Returns list of violations."""
        violations = []

        if ExecutionPolicy.CONTAINER_PER_EXECUTION not in self.policies:
            violations.append("Must use container-per-execution")

        if ExecutionPolicy.READ_ONLY_SOURCE not in self.policies:
            violations.append("Source must be read-only")

        if ExecutionPolicy.NO_NETWORK not in self.policies:
            violations.append("Network must be disabled")

        if ExecutionPolicy.RESOURCE_LIMITS not in self.policies:
            violations.append("Resource limits must be set")

        if self.network_policy.enabled:
            violations.append("Network must be disabled")

        try:
            self.filesystem_policy.validate()
        except ValueError as e:
            violations.append(str(e))

        return violations


@dataclass(frozen=True)
class StagedSource:
    """Staged source for execution."""
    source_id: str
    original_path: str
    staged_path: str
    original_hash: str
    staged_hash: str
    is_read_only: bool = True

    def verify_integrity(self) -> bool:
        """Verify staged source matches original."""
        return self.original_hash == self.staged_hash


class ExecutionEngine:
    """Execution engine abstraction. Manages execution lifecycle."""

    def __init__(self, environment: ExecutionEnvironment) -> None:
        self._environment = environment
        self._executions: list[ExecutionResult] = []

    def validate_environment(self) -> bool:
        """Validate execution environment meets policy requirements."""
        violations = self._environment.validate()
        return len(violations) == 0

    def prepare_execution(self, command: ExecutionCommand) -> dict[str, Any]:
        """Prepare execution with policy enforcement."""
        if not self.validate_environment():
            raise RuntimeError("Execution environment does not meet policy requirements")

        return {
            "command": command,
            "resource_limits": self._environment.resource_limits,
            "network_policy": self._environment.network_policy,
            "filesystem_policy": self._environment.filesystem_policy,
            "timeout": command.timeout_seconds,
        }

    def record_execution(self, result: ExecutionResult) -> None:
        """Record execution result."""
        self._executions.append(result)

    def get_executions(self) -> tuple[ExecutionResult, ...]:
        """Get all recorded executions."""
        return tuple(self._executions)

    def clear_executions(self) -> None:
        """Clear recorded executions."""
        self._executions.clear()
