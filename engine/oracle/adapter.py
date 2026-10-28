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
    """Configuration for oracle adapter.

    ``image`` is the declared (mutable) image reference used only as a lookup
    key; execution identity comes from ``image_digest``.

    ``image_digest`` is the declared immutable pin (``sha256:...``). An empty
    value means "auto-pin": the adapter resolves the image's immutable
    identity at execution time and records it as the executed identity. A
    non-empty value must equal the resolved identity exactly, otherwise
    execution fails closed.
    """
    oracle_id: str  # V1: "gnucobol-3.1.2"
    image_digest: str  # sha256:... or "" to auto-pin at execution time
    compiler_version: str
    preprocessor_version: str | None = None
    base_image: str | None = None
    timeout_seconds: int = 30
    image: str = "gnucobol-ocesql:latest"

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
    compilation_diagnostics: dict[str, str] | None = None
    # Immutable identity (sha256:...) of the image actually executed;
    # None when no container was run or identity could not be resolved.
    image_digest: str | None = None

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
            compilation_diagnostics=self.compilation_diagnostics,
            generated_files=generated_files_hashed,
            source_tree_hash_before=self.source_tree_hash_before or ContentHash.from_string(""),
            source_tree_hash_after=self.source_tree_hash_after or ContentHash.from_string(""),
            termination_status=self.termination_status,
            timeout_applied=self.timeout_applied,
            timeout_duration=self.timeout_duration,
            image_digest=self.image_digest,
        )


class GnuCOBOLAdapter(OracleAdapter):
    """GnuCOBOL oracle adapter implementation."""

    def __init__(self, config: OracleAdapterConfig) -> None:
        super().__init__(config)
        if config.oracle_id != "gnucobol-3.1.2":
            raise ValueError(f"GnuCOBOL adapter requires oracle_id='gnucobol-3.1.2', got {config.oracle_id}")

    def probe(self) -> AdapterStatus:
        """Probe GnuCOBOL availability.

        A config-shaped probe cannot establish that a compiler exists
        (audit D-6): the old body reported AVAILABLE whenever the config
        fields were non-empty, which let callers believe a GnuCOBOL oracle
        was reachable on a host with neither Docker nor cobc.  Real
        availability lives in ``engine/oracle/docker_adapter.py``.
        """
        raise NotImplementedError(
            "GnuCOBOLAdapter.probe cannot verify compiler availability; "
            "reporting AVAILABLE from config validation alone would "
            "fabricate an oracle. Use DockerOracleAdapter, which inspects "
            "the pinned image."
        )

    def execute(
        self,
        run_id: RunId,
        source_path: str,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> OracleExecutionResult:
        """Execute GnuCOBOL oracle.

        The old body returned SUCCEEDED/exit 0 with empty stdout for any
        source (audit D-6) — a fabricated oracle run whose empty output
        would then be "compared" against candidate output.  Oracle
        execution is now fail-closed; the real implementation is
        ``engine/oracle/docker_adapter.py`` (staged, network-disabled,
        digest-checked).
        """
        raise NotImplementedError(
            "GnuCOBOLAdapter has no execution implementation; returning "
            "SUCCEEDED would fabricate an oracle evidence record. Use "
            "DockerOracleAdapter."
        )

