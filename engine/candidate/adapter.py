"""Java candidate adapter interface for the validation engine.

Implements the platform-side Java Candidate Adapter contract.
V1 candidate shape:
- plain Java source tree
- platform-controlled javac
- explicit entrypoint manifest
- no Maven
- no Gradle
- no external dependencies
- batch/console execution
- no server/network requirement
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from engine.domain.identities import (
    AdapterStatus,
    ContentHash,
    ExecutionId,
    RunId,
)
from engine.evidence.models import ExecutionEvidence


@dataclass(frozen=True)
class CandidateManifest:
    """Candidate manifest fields."""
    candidate_id: str
    workload_id: str
    source_hash: str  # hash of COBOL source
    generated_files: dict[str, str]  # path -> hash
    entrypoint: str  # main class
    java_version: str = "17"
    dependencies: tuple[str, ...] = ()  # V1: empty or vendored
    runtime_requirements: dict[str, str] = field(default_factory=dict)
    producer_identity: str = ""
    producer_version: str = ""
    generation_timestamp: str = ""
    mutation_regeneration_capability: bool = False

    def validate(self) -> list[str]:
        """Validate manifest fields. Returns list of missing fields."""
        missing = []
        if not self.candidate_id:
            missing.append("candidate_id")
        if not self.workload_id:
            missing.append("workload_id")
        if not self.source_hash:
            missing.append("source_hash")
        if not self.generated_files:
            missing.append("generated_files")
        if not self.entrypoint:
            missing.append("entrypoint")
        return missing


class CandidateAdapter(ABC):
    """Abstract base class for candidate adapters."""

    def __init__(self) -> None:
        self._status = AdapterStatus.UNAVAILABLE

    @property
    def status(self) -> AdapterStatus:
        return self._status

    @abstractmethod
    def validate_candidate(self, candidate_path: str, manifest: CandidateManifest) -> list[str]:
        """Validate candidate package. Returns list of violations."""
        ...

    @abstractmethod
    def compile(self, candidate_path: str, manifest: CandidateManifest) -> CompilationResult:
        """Compile candidate Java source."""
        ...

    @abstractmethod
    def execute(
        self,
        run_id: RunId,
        compiled_path: str,
        manifest: CandidateManifest,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> CandidateExecutionResult:
        """Execute compiled candidate."""
        ...


@dataclass(frozen=True)
class CompilationResult:
    """Result of candidate compilation."""
    success: bool
    class_files: dict[str, bytes]  # path -> bytecode
    compilation_errors: tuple[str, ...] = ()
    compilation_time_ms: int = 0


@dataclass(frozen=True)
class CandidateExecutionResult:
    """Result of candidate execution."""
    execution_id: ExecutionId
    run_id: RunId
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
            runtime_id="candidate-java",
            command="javac + java execution",
            working_directory="/workspace",
            environment_variables={},
            start_time=self.start_time,
            end_time=self.end_time,
            exit_code=self.exit_code,
            stdout_hash=stdout_hash,
            stderr_hash=stderr_hash,
            generated_files=generated_files_hashed,
            source_tree_hash_before=ContentHash.from_string(""),
            source_tree_hash_after=ContentHash.from_string(""),
            termination_status=self.termination_status,
            timeout_applied=self.timeout_applied,
            timeout_duration=self.timeout_duration,
        )


class PlainJavaCandidateAdapter(CandidateAdapter):
    """Plain Java candidate adapter implementation (V1)."""

    def __init__(self) -> None:
        super().__init__()

    def validate_candidate(self, candidate_path: str, manifest: CandidateManifest) -> list[str]:
        """Validate candidate package."""
        violations = []

        # Validate manifest fields
        missing = manifest.validate()
        if missing:
            violations.append(f"Missing manifest fields: {', '.join(missing)}")

        # V1: no build system allowed
        # In real implementation, would check for pom.xml, build.gradle, etc.

        # V1: no external dependencies allowed
        if manifest.dependencies:
            violations.append("V1 does not allow external dependencies")

        # Validate generated files
        if not manifest.generated_files:
            violations.append("No generated files declared")

        # Validate entrypoint
        if not manifest.entrypoint:
            violations.append("No entrypoint declared")

        return violations

    def compile(self, candidate_path: str, manifest: CandidateManifest) -> CompilationResult:
        """Compile candidate Java source."""
        # In real implementation, this would:
        # 1. Stage candidate read-only
        # 2. Run platform-controlled javac
        # 3. Capture compilation output
        # For now, return placeholder
        return CompilationResult(
            success=True,
            class_files={},
            compilation_time_ms=0,
        )

    def execute(
        self,
        run_id: RunId,
        compiled_path: str,
        manifest: CandidateManifest,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> CandidateExecutionResult:
        """Execute compiled candidate."""
        from datetime import datetime, timezone

        execution_id = ExecutionId(value=f"candidate-{run_id.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        start_time = datetime.now(timezone.utc).isoformat()

        # In real implementation, this would:
        # 1. Create container with pinned JDK
        # 2. Stage compiled classes read-only
        # 3. Execute with controlled inputs
        # 4. Capture output
        # For now, return placeholder
        end_time = datetime.now(timezone.utc).isoformat()

        return CandidateExecutionResult(
            execution_id=execution_id,
            run_id=run_id,
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"",
            stderr=b"",
            start_time=start_time,
            end_time=end_time,
            termination_status="normal",
            timeout_applied=False,
        )
