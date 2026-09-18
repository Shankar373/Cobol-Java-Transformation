"""Oracle adapter interface for the validation engine.

Implements the Oracle Adapter interface and V1 identity model.
V1 authoritative oracle: GnuCOBOL 3.1.2.0 + Open-COBOL-ESQL 1.4

Oracle identity MUST include:
- adapter identity
- runtime/compiler identity
- image digest
- relevant version information
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from engine.domain.identities import (
    AdapterStatus,
    ContentHash,
    ExecutionId,
    OracleIdentity,
    RunId,
)
from engine.evidence.models import ExecutionEvidence


@dataclass(frozen=True)
class OracleAdapterConfig:
    """Configuration for oracle adapter."""
    oracle_id: str  # V1: "gnucobol-3.1.2"
    image_digest: str  # sha256:...
    compiler_version: str
    preprocessor_version: str | None = None
    base_image: str | None = None
    timeout_seconds: int = 30

    def validate(self) -> list[str]:
        """Validate oracle configuration."""
        violations = []
        if not self.oracle_id:
            violations.append("oracle_id is required")
        if not self.image_digest.startswith("sha256:"):
            violations.append("image_digest must be sha256-pinned")
        if not self.compiler_version:
            violations.append("compiler_version is required")
        return violations


class OracleAdapter(ABC):
    """Abstract base class for oracle adapters."""

    def __init__(self, config: OracleAdapterConfig) -> None:
        self._config = config
        self._status = AdapterStatus.UNAVAILABLE

    @property
    def config(self) -> OracleAdapterConfig:
        return self._config

    @property
    def status(self) -> AdapterStatus:
        return self._status

    @abstractmethod
    def probe(self) -> AdapterStatus:
        """Probe oracle availability. Returns observed status."""
        ...

    @abstractmethod
    def execute(
        self,
        run_id: RunId,
        source_path: str,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> OracleExecutionResult:
        """Execute oracle and return result."""
        ...

    def get_identity(self) -> OracleIdentity:
        """Get oracle identity."""
        return OracleIdentity(
            oracle_id=self._config.oracle_id,
            image_digest=self._config.image_digest,
            compiler_version=self._config.compiler_version,
            preprocessor_version=self._config.preprocessor_version,
            base_image=self._config.base_image,
        )


@dataclass(frozen=True)
class OracleExecutionResult:
    """Result of oracle execution."""
    execution_id: ExecutionId
    run_id: RunId
    oracle_id: str
    status: AdapterStatus
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    start_time: str
    end_time: str
    termination_status: str  # normal, timeout, nonzero_exit, error
    timeout_applied: bool
    timeout_duration: int | None = None
    generated_files: dict[str, bytes] | None = None
    source_tree_hash_before: ContentHash | None = None
    source_tree_hash_after: ContentHash | None = None

    def to_execution_evidence(self) -> ExecutionEvidence:
        """Convert to execution evidence."""
        stdout_hash = ContentHash.from_bytes(self.stdout)
        stderr_hash = ContentHash.from_bytes(self.stderr)
        
        generated_files_hashed = {}
        if self.generated_files:
            for path, content in self.generated_files.items():
                generated_files_hashed[path] = ContentHash.from_bytes(content)

        return ExecutionEvidence(
            execution_id=self.execution_id,
            run_id=self.run_id,
            runtime_id=f"oracle-{self.oracle_id}",
            command="oracle execution",
            working_directory="/workspace",
            environment_variables={},
            start_time=self.start_time,
            end_time=self.end_time,
            exit_code=self.exit_code,
            stdout_hash=stdout_hash,
            stderr_hash=stderr_hash,
            generated_files=generated_files_hashed,
            source_tree_hash_before=self.source_tree_hash_before or ContentHash.from_string(""),
            source_tree_hash_after=self.source_tree_hash_after or ContentHash.from_string(""),
            termination_status=self.termination_status,
            timeout_applied=self.timeout_applied,
            timeout_duration=self.timeout_duration,
        )


class GnuCOBOLAdapter(OracleAdapter):
    """GnuCOBOL oracle adapter implementation."""

    def __init__(self, config: OracleAdapterConfig) -> None:
        super().__init__(config)
        if config.oracle_id != "gnucobol-3.1.2":
            raise ValueError(f"GnuCOBOL adapter requires oracle_id='gnucobol-3.1.2', got {config.oracle_id}")

    def probe(self) -> AdapterStatus:
        """Probe GnuCOBOL availability."""
        # In real implementation, this would check if Docker image exists
        # For now, return AVAILABLE if config is valid
        violations = self._config.validate()
        if violations:
            self._status = AdapterStatus.UNAVAILABLE
        else:
            self._status = AdapterStatus.AVAILABLE
        return self._status

    def execute(
        self,
        run_id: RunId,
        source_path: str,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> OracleExecutionResult:
        """Execute GnuCOBOL oracle."""
        from datetime import datetime, timezone

        from engine.domain.identities import ExecutionId

        execution_id = ExecutionId(value=f"oracle-{run_id.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        start_time = datetime.now(timezone.utc).isoformat()

        # In real implementation, this would:
        # 1. Create container with pinned image
        # 2. Stage source read-only
        # 3. Compile and execute
        # 4. Capture output
        # For now, return placeholder
        end_time = datetime.now(timezone.utc).isoformat()

        return OracleExecutionResult(
            execution_id=execution_id,
            run_id=run_id,
            oracle_id=self._config.oracle_id,
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"",
            stderr=b"",
            start_time=start_time,
            end_time=end_time,
            termination_status="normal",
            timeout_applied=False,
        )
