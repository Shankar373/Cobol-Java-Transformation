"""Evidence model and content addressing.

Implements the evidence subsystem as defined by EVIDENCE_SPEC.md.
Evidence is the platform's only source of truth.
A verdict is a pure function of an evidence manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from engine.domain.identities import (
    ArtifactIdentity,
    CandidateIdentity,
    ContentHash,
    EnvironmentIdentity,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    WorkloadId,
)

# ---------------------------------------------------------------------------
# Evidence types
# ---------------------------------------------------------------------------

class EvidenceType(Enum):
    """Evidence types in the V1 registry."""
    ORACLE_EXECUTION = "oracle_execution"
    CANDIDATE_EXECUTION = "candidate_execution"
    ARTIFACT_CAPTURE = "artifact_capture"
    ARTIFACT_CONTRACT_VALIDATION = "artifact_contract_validation"
    COMPARISON_RESULT = "comparison_result"
    MUTATION_RESULT = "mutation_result"
    VERDICT_DERIVATION = "verdict_derivation"


# ---------------------------------------------------------------------------
# Evidence envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceEnvelope:
    """Wrapper for all evidence objects."""
    evidence_id: str
    evidence_type: EvidenceType
    schema_version: str
    created_at: str  # ISO-8601
    content_hash: ContentHash
    content: dict[str, Any]

    def verify_integrity(self) -> bool:
        """Verify evidence content hasn't been tampered with."""
        import json
        content_bytes = json.dumps(self.content, sort_keys=True).encode("utf-8")
        return self.content_hash.verify(content_bytes)


# ---------------------------------------------------------------------------
# Execution evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionEvidence:
    """Evidence from a single execution (oracle or candidate)."""
    execution_id: ExecutionId
    run_id: RunId
    runtime_id: str
    command: str
    working_directory: str
    environment_variables: dict[str, str]
    start_time: str
    end_time: str
    exit_code: int | None
    stdout_hash: ContentHash
    stderr_hash: ContentHash
    generated_files: dict[str, ContentHash]
    source_tree_hash_before: ContentHash
    source_tree_hash_after: ContentHash
    termination_status: str  # normal, timeout, nonzero_exit, error
    timeout_applied: bool
    timeout_duration: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "execution_id": self.execution_id.value,
            "run_id": self.run_id.value,
            "runtime_id": self.runtime_id,
            "command": self.command,
            "working_directory": self.working_directory,
            "environment_variables": self.environment_variables,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "exit_code": self.exit_code,
            "stdout_hash": str(self.stdout_hash),
            "stderr_hash": str(self.stderr_hash),
            "generated_files": {k: str(v) for k, v in self.generated_files.items()},
            "source_tree_hash_before": str(self.source_tree_hash_before),
            "source_tree_hash_after": str(self.source_tree_hash_after),
            "termination_status": self.termination_status,
            "timeout_applied": self.timeout_applied,
            "timeout_duration": self.timeout_duration,
        }


# ---------------------------------------------------------------------------
# Artifact evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactEvidence:
    """Evidence of artifact capture."""
    artifact: ArtifactIdentity
    execution_id: ExecutionId
    capture_time: str
    content_hash: ContentHash
    size_bytes: int
    record_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact.artifact_id,
            "artifact_type": self.artifact.artifact_type,
            "logical_name": self.artifact.logical_name,
            "producer_role": self.artifact.producer_role,
            "execution_id": self.execution_id.value,
            "capture_time": self.capture_time,
            "content_hash": str(self.content_hash),
            "size_bytes": self.size_bytes,
            "record_count": self.record_count,
        }


# ---------------------------------------------------------------------------
# Comparison evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComparisonEvidence:
    """Evidence from artifact comparison."""
    comparison_id: str
    run_id: RunId
    comparator_id: str
    comparator_version: str
    oracle_artifact_id: str
    candidate_artifact_id: str
    artifact_type: str
    result: str  # MATCH, MISMATCH, INCONCLUSIVE
    normalization_applied: tuple[str, ...]
    differences: tuple[str, ...]
    field_level_results: tuple[dict[str, Any], ...]
    content_hash: ContentHash

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "run_id": self.run_id.value,
            "comparator_id": self.comparator_id,
            "comparator_version": self.comparator_version,
            "oracle_artifact_id": self.oracle_artifact_id,
            "candidate_artifact_id": self.candidate_artifact_id,
            "artifact_type": self.artifact_type,
            "result": self.result,
            "normalization_applied": list(self.normalization_applied),
            "differences": list(self.differences),
            "field_level_results": list(self.field_level_results),
        }


# ---------------------------------------------------------------------------
# Verdict evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerdictEvidence:
    """Evidence of verdict derivation."""
    run_id: RunId
    workload_id: WorkloadId
    verdict_state: str
    executed_check_count: int
    skipped_count: int
    unavailable_count: int
    supported_scope_statement: str
    evidence_manifest_hash: ContentHash
    derivation_timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "workload_id": self.workload_id.value,
            "verdict_state": self.verdict_state,
            "executed_check_count": self.executed_check_count,
            "skipped_count": self.skipped_count,
            "unavailable_count": self.unavailable_count,
            "supported_scope_statement": self.supported_scope_statement,
            "evidence_manifest_hash": str(self.evidence_manifest_hash),
            "derivation_timestamp": self.derivation_timestamp,
        }


# ---------------------------------------------------------------------------
# Evidence manifest
# ---------------------------------------------------------------------------

@dataclass
class EvidenceManifest:
    """Complete evidence manifest for a workload-run."""
    manifest_version: str
    run_id: RunId
    workload_id: WorkloadId
    source_identity: SourceIdentity
    candidate_identity: CandidateIdentity | None
    oracle_identity: OracleIdentity
    environment_identities: tuple[EnvironmentIdentity, ...]
    controlled_input: InputIdentity
    execution_evidence: tuple[ExecutionEvidence, ...]
    artifact_evidence: tuple[ArtifactEvidence, ...]
    comparison_evidence: tuple[ComparisonEvidence, ...]
    verdict_evidence: VerdictEvidence | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def manifest_hash(self) -> ContentHash:
        """Compute hash covering the complete evidence graph.

        Covers: all identity fields, all execution evidence,
        all artifact identities and content hashes, all comparison
        evidence and content hashes. Any modification to any evidence
        field changes this hash.
        """
        graph: dict[str, Any] = {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id.value,
            "workload_id": self.workload_id.value,
            "source_identity": {
                "source_id": self.source_identity.source_id,
                "source_hash": str(self.source_identity.source_hash),
                "file_count": self.source_identity.file_count,
                "total_size_bytes": self.source_identity.total_size_bytes,
            },
            "oracle_identity": {
                "oracle_id": self.oracle_identity.oracle_id if self.oracle_identity else None,
                "image_digest": self.oracle_identity.image_digest if self.oracle_identity else None,
                "compiler_version": self.oracle_identity.compiler_version if self.oracle_identity else None,
            } if self.oracle_identity else None,
            "controlled_input": {
                "input_id": self.controlled_input.input_id,
                "stdin_hash": str(self.controlled_input.stdin_hash) if self.controlled_input.stdin_hash else None,
            },
            "execution_evidence": [
                {
                    "execution_id": e.execution_id.value,
                    "run_id": e.run_id.value,
                    "runtime_id": e.runtime_id,
                    "termination_status": e.termination_status,
                    "timeout_applied": e.timeout_applied,
                    "exit_code": e.exit_code,
                    "stdout_hash": str(e.stdout_hash),
                    "stderr_hash": str(e.stderr_hash),
                }
                for e in self.execution_evidence
            ],
            "artifact_evidence": [
                {
                    "artifact_id": a.artifact.artifact_id,
                    "artifact_type": a.artifact.artifact_type,
                    "producer_role": a.artifact.producer_role,
                    "content_hash": str(a.content_hash),
                    "execution_id": a.execution_id.value,
                }
                for a in self.artifact_evidence
            ],
            "comparison_evidence": [
                {
                    "comparison_id": c.comparison_id,
                    "run_id": c.run_id.value,
                    "oracle_artifact_id": c.oracle_artifact_id,
                    "candidate_artifact_id": c.candidate_artifact_id,
                    "result": c.result,
                    "artifact_type": c.artifact_type,
                    "content_hash": str(c.content_hash),
                }
                for c in self.comparison_evidence
            ],
        }
        if self.candidate_identity is not None:
            graph["candidate_identity"] = {
                "candidate_id": self.candidate_identity.candidate_id,
                "candidate_hash": str(self.candidate_identity.candidate_hash),
                "source_hash": str(self.candidate_identity.source_hash),
            }
        content_bytes = json.dumps(graph, sort_keys=True, default=str).encode("utf-8")
        return ContentHash.from_bytes(content_bytes)

    def is_complete(self) -> bool:
        """Check if manifest is complete for VERIFIED verdict.

        A candidate execution with "nonzero_exit" is still considered complete —
        the program ran and produced output; it just failed logically.
        Only "error" and "timeout" indicate incomplete execution.
        """
        incomplete_statuses = {"error", "timeout"}

        # Must have oracle execution
        if not any(
            e.termination_status not in incomplete_statuses
            for e in self.execution_evidence
            if e.runtime_id.startswith("oracle")
        ):
            return False

        # Must have candidate execution
        if not any(
            e.termination_status not in incomplete_statuses
            for e in self.execution_evidence
            if e.runtime_id.startswith("candidate")
        ):
            return False

        # Must have artifact evidence
        if len(self.artifact_evidence) == 0:
            return False

        # Must have comparison evidence
        return len(self.comparison_evidence) != 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id.value,
            "workload_id": self.workload_id.value,
            "source_identity": {
                "source_id": self.source_identity.source_id,
                "source_hash": str(self.source_identity.source_hash),
                "file_count": self.source_identity.file_count,
                "total_size_bytes": self.source_identity.total_size_bytes,
            },
            "oracle_identity": {
                "oracle_id": self.oracle_identity.oracle_id if self.oracle_identity else None,
                "image_digest": self.oracle_identity.image_digest if self.oracle_identity else None,
                "compiler_version": self.oracle_identity.compiler_version if self.oracle_identity else None,
            } if self.oracle_identity else None,
            "execution_count": len(self.execution_evidence),
            "artifact_count": len(self.artifact_evidence),
            "comparison_count": len(self.comparison_evidence),
            "manifest_hash": str(self.manifest_hash),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Content-addressed storage
# ---------------------------------------------------------------------------

class ContentAddressedStorage:
    """Content-addressed storage for evidence artifacts."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def store(self, content: bytes) -> ContentHash:
        """Store content and return its hash."""
        content_hash = ContentHash.from_bytes(content)
        self._store[content_hash.digest] = content
        return content_hash

    def retrieve(self, content_hash: ContentHash) -> bytes | None:
        """Retrieve content by hash."""
        return self._store.get(content_hash.digest)

    def exists(self, content_hash: ContentHash) -> bool:
        """Check if content exists."""
        return content_hash.digest in self._store

    def verify(self, content_hash: ContentHash) -> bool:
        """Verify content integrity."""
        content = self.retrieve(content_hash)
        if content is None:
            return False
        return content_hash.verify(content)
