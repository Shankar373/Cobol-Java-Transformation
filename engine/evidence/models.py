"""Evidence model and content addressing.

Implements the evidence subsystem as defined by EVIDENCE_SPEC.md.
Evidence is the platform's only source of truth.
A verdict is a pure function of an evidence manifest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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
    java_version: str | None = None
    maven_version: str | None = None
    python_version: str | None = None
    docker_version: str | None = None
    cobol_compiler: str | None = None
    image_digest: str | None = None
    producer_identity: str | None = None
    producer_version: str | None = None
    provenance_hash: ContentHash | None = None

    def __post_init__(self) -> None:
        if self.provenance_hash is None:
            payload = {
                "execution_id": self.execution_id.value,
                "run_id": self.run_id.value,
                "runtime_id": self.runtime_id,
                "command": self.command,
                "working_directory": self.working_directory,
                "environment_variables": dict(self.environment_variables),
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
                "java_version": self.java_version,
                "maven_version": self.maven_version,
                "python_version": self.python_version,
                "docker_version": self.docker_version,
                "cobol_compiler": self.cobol_compiler,
                "image_digest": self.image_digest,
                "producer_identity": self.producer_identity,
                "producer_version": self.producer_version,
            }
            object.__setattr__(
                self,
                "provenance_hash",
                ContentHash.from_string(json.dumps(payload, sort_keys=True)),
            )

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
            "java_version": self.java_version,
            "maven_version": self.maven_version,
            "python_version": self.python_version,
            "docker_version": self.docker_version,
            "cobol_compiler": self.cobol_compiler,
            "image_digest": self.image_digest,
            "producer_identity": self.producer_identity,
            "producer_version": self.producer_version,
            "provenance_hash": str(self.provenance_hash) if self.provenance_hash else None,
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
    ordering_applied: str = "SEQUENTIAL"
    failure_policy: str = ""

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
            "ordering_applied": self.ordering_applied,
            "failure_policy": self.failure_policy,
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
    producer_identity: str | None = None
    producer_version: str | None = None
    require_trusted_provenance: bool = False
    verdict_evidence: VerdictEvidence | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stored_manifest_hash: ContentHash | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.stored_manifest_hash is None:
            object.__setattr__(self, "stored_manifest_hash", self._compute_manifest_hash())

    def canonical_serialization(self) -> bytes:
        """Serialize security-relevant evidence deterministically.

        Manifest creation and verdict-derivation timestamps are recording
        metadata, not evidence identity. They must not make equivalent
        evidence hash differently. Evidence collections are canonicalized by
        stable identity keys so construction order cannot alter the digest.
        All substantive fields remain in the canonical payload.
        """
        payload = asdict(self)
        payload.pop("stored_manifest_hash", None)
        payload.pop("created_at", None)

        collection_keys = (
            ("execution_evidence", "execution_id"),
            ("artifact_evidence", "artifact", "artifact_id"),
            ("comparison_evidence", "comparison_id"),
            ("environment_identities", "runtime_id"),
        )
        for spec in collection_keys:
            collection_name, *path = spec
            collection = payload.get(collection_name)
            if not isinstance(collection, list):
                continue
            if len(path) == 1:
                collection.sort(key=lambda item: str(item.get(path[0], "")))
            else:
                collection.sort(
                    key=lambda item: str(
                        item.get(path[0], {}).get(path[1], "")
                    )
                )

        verdict = payload.get("verdict_evidence")
        if isinstance(verdict, dict):
            verdict.pop("derivation_timestamp", None)

        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")

    def _compute_manifest_hash(self) -> ContentHash:
        return ContentHash.from_bytes(self.canonical_serialization())

    @property
    def manifest_hash(self) -> ContentHash:
        return self.stored_manifest_hash or self._compute_manifest_hash()

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
            "producer_identity": self.producer_identity,
            "producer_version": self.producer_version,
            "require_trusted_provenance": self.require_trusted_provenance,
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

    # -- storage round-trip ---------------------------------------------------
    #
    # ``to_dict()`` above is a *summary* for API/report payloads. The storage
    # round-trip below is full fidelity: every field required to rebuild an
    # identical manifest (including execution, artifact and comparison
    # evidence) so persistence never depends on Python pickle.

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialize every field to JSON-compatible primitives."""
        return {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id.value,
            "workload_id": self.workload_id.value,
            "source_identity": _source_identity_to(self.source_identity),
            "candidate_identity": (
                _candidate_identity_to(self.candidate_identity)
                if self.candidate_identity is not None else None
            ),
            "oracle_identity": _oracle_identity_to(self.oracle_identity),
            "environment_identities": [
                _environment_identity_to(e) for e in self.environment_identities
            ],
            "controlled_input": _input_identity_to(self.controlled_input),
            "execution_evidence": [
                e.to_dict() for e in self.execution_evidence
            ],
            "artifact_evidence": [
                _artifact_evidence_to(a) for a in self.artifact_evidence
            ],
            "comparison_evidence": [
                _comparison_evidence_to(c) for c in self.comparison_evidence
            ],
            "producer_identity": self.producer_identity,
            "producer_version": self.producer_version,
            "require_trusted_provenance": self.require_trusted_provenance,
            "verdict_evidence": (
                _verdict_evidence_to(self.verdict_evidence)
                if self.verdict_evidence is not None else None
            ),
            "created_at": self.created_at,
            "stored_manifest_hash": _hash_to_str(self.stored_manifest_hash),
        }

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> EvidenceManifest:
        """Rebuild a manifest from ``to_storage_dict`` output.

        Raises ``ValueError`` on a malformed payload so callers fail closed
        instead of persisting a silently lossy manifest.
        """
        if not isinstance(data, dict):
            raise ValueError("evidence manifest payload must be an object")
        try:
            manifest = cls(
                manifest_version=str(data["manifest_version"]),
                run_id=RunId(str(data["run_id"])),
                workload_id=WorkloadId(str(data["workload_id"])),
                source_identity=_source_identity_from(data["source_identity"]),
                candidate_identity=(
                    _candidate_identity_from(data["candidate_identity"])
                    if data.get("candidate_identity") is not None else None
                ),
                oracle_identity=_oracle_identity_from(data["oracle_identity"]),
                environment_identities=tuple(
                    _environment_identity_from(e)
                    for e in (data.get("environment_identities") or [])
                ),
                controlled_input=_input_identity_from(data["controlled_input"]),
                execution_evidence=tuple(
                    _execution_evidence_from(e)
                    for e in (data.get("execution_evidence") or [])
                ),
                artifact_evidence=tuple(
                    _artifact_evidence_from(a)
                    for a in (data.get("artifact_evidence") or [])
                ),
                comparison_evidence=tuple(
                    _comparison_evidence_from(c)
                    for c in (data.get("comparison_evidence") or [])
                ),
                producer_identity=data.get("producer_identity"),
                producer_version=data.get("producer_version"),
                require_trusted_provenance=bool(
                    data.get("require_trusted_provenance", False)
                ),
                verdict_evidence=(
                    _verdict_evidence_from(data["verdict_evidence"])
                    if data.get("verdict_evidence") is not None else None
                ),
                created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
                stored_manifest_hash=_hash_from_str(
                    data.get("stored_manifest_hash")
                ),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"incomplete evidence manifest payload: {exc}") from exc
        return manifest


# ---------------------------------------------------------------------------
# Storage round-trip helpers (JSON-safe primitives, no pickle)
# ---------------------------------------------------------------------------

def _hash_to_str(value: ContentHash | None) -> str | None:
    return str(value) if value is not None else None


def _hash_from_str(value: str | None) -> ContentHash | None:
    if value is None or value == "":
        return None
    text = value[7:] if value.startswith("sha256:") else value
    return ContentHash(digest=text)


def _require_hash(value: str | None) -> ContentHash:
    decoded = _hash_from_str(value)
    if decoded is None:
        raise ValueError("required content hash is missing")
    return decoded


def _source_identity_to(obj: SourceIdentity) -> dict[str, Any]:
    return {
        "source_id": obj.source_id,
        "source_hash": str(obj.source_hash),
        "file_count": obj.file_count,
        "total_size_bytes": obj.total_size_bytes,
    }


def _source_identity_from(data: dict[str, Any]) -> SourceIdentity:
    return SourceIdentity(
        source_id=str(data["source_id"]),
        source_hash=_require_hash(data["source_hash"]),
        file_count=int(data["file_count"]),
        total_size_bytes=int(data["total_size_bytes"]),
    )


def _candidate_identity_to(obj: CandidateIdentity | None) -> dict[str, Any]:
    assert obj is not None
    return {
        "candidate_id": obj.candidate_id,
        "candidate_hash": str(obj.candidate_hash),
        "source_hash": str(obj.source_hash),
        "file_count": obj.file_count,
        "total_size_bytes": obj.total_size_bytes,
        "producer_identity": obj.producer_identity,
        "producer_version": obj.producer_version,
        "runtime_image_digest": obj.runtime_image_digest,
        "java_version": obj.java_version,
        "maven_version": obj.maven_version,
    }


def _candidate_identity_from(data: dict[str, Any]) -> CandidateIdentity:
    return CandidateIdentity(
        candidate_id=str(data["candidate_id"]),
        candidate_hash=_require_hash(data["candidate_hash"]),
        source_hash=_require_hash(data["source_hash"]),
        file_count=int(data["file_count"]),
        total_size_bytes=int(data["total_size_bytes"]),
        producer_identity=data.get("producer_identity"),
        producer_version=data.get("producer_version"),
        runtime_image_digest=data.get("runtime_image_digest"),
        java_version=data.get("java_version"),
        maven_version=data.get("maven_version"),
    )


def _oracle_identity_to(obj: OracleIdentity) -> dict[str, Any]:
    return {
        "oracle_id": obj.oracle_id,
        "image_digest": obj.image_digest,
        "compiler_version": obj.compiler_version,
        "preprocessor_version": obj.preprocessor_version,
        "base_image": obj.base_image,
    }


def _oracle_identity_from(data: dict[str, Any]) -> OracleIdentity:
    return OracleIdentity(
        oracle_id=str(data["oracle_id"]),
        image_digest=str(data["image_digest"]),
        compiler_version=str(data["compiler_version"]),
        preprocessor_version=data.get("preprocessor_version"),
        base_image=data.get("base_image"),
    )


def _environment_identity_to(obj: EnvironmentIdentity) -> dict[str, Any]:
    return {
        "runtime_id": obj.runtime_id,
        "java_version": obj.java_version,
        "maven_version": obj.maven_version,
        "python_version": obj.python_version,
        "docker_version": obj.docker_version,
        "cobol_compiler": obj.cobol_compiler,
        "image_digest": obj.image_digest,
        "os_base": obj.os_base,
        "network_policy": obj.network_policy,
        "resource_limits": dict(obj.resource_limits),
    }


def _environment_identity_from(data: dict[str, Any]) -> EnvironmentIdentity:
    return EnvironmentIdentity(
        runtime_id=str(data["runtime_id"]),
        java_version=data.get("java_version"),
        maven_version=data.get("maven_version"),
        python_version=data.get("python_version"),
        docker_version=data.get("docker_version"),
        cobol_compiler=data.get("cobol_compiler"),
        image_digest=data.get("image_digest"),
        os_base=data.get("os_base"),
        network_policy=str(data.get("network_policy") or "none"),
        resource_limits={
            str(k): str(v)
            for k, v in (data.get("resource_limits") or {}).items()
        },
    )


def _input_identity_to(obj: InputIdentity) -> dict[str, Any]:
    return {
        "input_id": obj.input_id,
        "stdin_hash": _hash_to_str(obj.stdin_hash),
        "input_files": {
            path: str(digest) for path, digest in obj.input_files.items()
        },
    }


def _input_identity_from(data: dict[str, Any]) -> InputIdentity:
    return InputIdentity(
        input_id=str(data["input_id"]),
        stdin_hash=_hash_from_str(data.get("stdin_hash")),
        input_files={
            str(path): _require_hash(digest)
            for path, digest in (data.get("input_files") or {}).items()
        },
    )


def _execution_evidence_from(data: dict[str, Any]) -> ExecutionEvidence:
    try:
        return ExecutionEvidence(
            execution_id=ExecutionId(str(data["execution_id"])),
            run_id=RunId(str(data["run_id"])),
            runtime_id=str(data["runtime_id"]),
            command=str(data["command"]),
            working_directory=str(data["working_directory"]),
            environment_variables={
                str(k): str(v)
                for k, v in (data.get("environment_variables") or {}).items()
            },
            start_time=str(data["start_time"]),
            end_time=str(data["end_time"]),
            exit_code=(
                int(data["exit_code"]) if data.get("exit_code") is not None
                else None
            ),
            stdout_hash=_require_hash(data["stdout_hash"]),
            stderr_hash=_require_hash(data["stderr_hash"]),
            generated_files={
                str(k): _require_hash(v)
                for k, v in (data.get("generated_files") or {}).items()
            },
            source_tree_hash_before=_require_hash(data["source_tree_hash_before"]),
            source_tree_hash_after=_require_hash(data["source_tree_hash_after"]),
            termination_status=str(data["termination_status"]),
            timeout_applied=bool(data.get("timeout_applied", False)),
            timeout_duration=(
                int(data["timeout_duration"])
                if data.get("timeout_duration") is not None else None
            ),
            java_version=data.get("java_version"),
            maven_version=data.get("maven_version"),
            python_version=data.get("python_version"),
            docker_version=data.get("docker_version"),
            cobol_compiler=data.get("cobol_compiler"),
            image_digest=data.get("image_digest"),
            producer_identity=data.get("producer_identity"),
            producer_version=data.get("producer_version"),
            provenance_hash=_hash_from_str(data.get("provenance_hash")),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"incomplete execution evidence payload: {exc}") from exc


def _artifact_evidence_to(obj: ArtifactEvidence) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": obj.artifact.artifact_id,
            "artifact_type": obj.artifact.artifact_type,
            "logical_name": obj.artifact.logical_name,
            "producer_role": obj.artifact.producer_role,
            "content_hash": str(obj.artifact.content_hash),
            "size_bytes": obj.artifact.size_bytes,
            "record_count": obj.artifact.record_count,
            "availability": obj.artifact.availability,
        },
        "execution_id": obj.execution_id.value,
        "capture_time": obj.capture_time,
        "content_hash": str(obj.content_hash),
        "size_bytes": obj.size_bytes,
        "record_count": obj.record_count,
    }


def _artifact_evidence_from(data: dict[str, Any]) -> ArtifactEvidence:
    try:
        artifact = data["artifact"]
        return ArtifactEvidence(
            artifact=ArtifactIdentity(
                artifact_id=str(artifact["artifact_id"]),
                artifact_type=str(artifact["artifact_type"]),
                logical_name=str(artifact["logical_name"]),
                producer_role=str(artifact["producer_role"]),
                content_hash=_require_hash(artifact["content_hash"]),
                size_bytes=int(artifact["size_bytes"]),
                record_count=(
                    int(artifact["record_count"])
                    if artifact.get("record_count") is not None else None
                ),
                availability=str(artifact.get("availability") or "PRESENT"),
            ),
            execution_id=ExecutionId(str(data["execution_id"])),
            capture_time=str(data["capture_time"]),
            content_hash=_require_hash(data["content_hash"]),
            size_bytes=int(data["size_bytes"]),
            record_count=(
                int(data["record_count"])
                if data.get("record_count") is not None else None
            ),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"incomplete artifact evidence payload: {exc}") from exc


def _comparison_evidence_to(obj: ComparisonEvidence) -> dict[str, Any]:
    return {
        "comparison_id": obj.comparison_id,
        "run_id": obj.run_id.value,
        "comparator_id": obj.comparator_id,
        "comparator_version": obj.comparator_version,
        "oracle_artifact_id": obj.oracle_artifact_id,
        "candidate_artifact_id": obj.candidate_artifact_id,
        "artifact_type": obj.artifact_type,
        "result": obj.result,
        "normalization_applied": list(obj.normalization_applied),
        "differences": list(obj.differences),
        "field_level_results": [dict(r) for r in obj.field_level_results],
        "content_hash": str(obj.content_hash),
        "ordering_applied": obj.ordering_applied,
        "failure_policy": obj.failure_policy,
    }


def _comparison_evidence_from(data: dict[str, Any]) -> ComparisonEvidence:
    try:
        return ComparisonEvidence(
            comparison_id=str(data["comparison_id"]),
            run_id=RunId(str(data["run_id"])),
            comparator_id=str(data["comparator_id"]),
            comparator_version=str(data["comparator_version"]),
            oracle_artifact_id=str(data["oracle_artifact_id"]),
            candidate_artifact_id=str(data["candidate_artifact_id"]),
            artifact_type=str(data["artifact_type"]),
            result=str(data["result"]),
            normalization_applied=tuple(
                str(v) for v in (data.get("normalization_applied") or [])
            ),
            differences=tuple(
                str(v) for v in (data.get("differences") or [])
            ),
            field_level_results=tuple(
                dict(v) for v in (data.get("field_level_results") or [])
            ),
            content_hash=_require_hash(data["content_hash"]),
            ordering_applied=str(data.get("ordering_applied") or "SEQUENTIAL"),
            failure_policy=str(data.get("failure_policy") or ""),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"incomplete comparison evidence payload: {exc}") from exc


def _verdict_evidence_to(obj: VerdictEvidence) -> dict[str, Any]:
    return {
        "run_id": obj.run_id.value,
        "workload_id": obj.workload_id.value,
        "verdict_state": obj.verdict_state,
        "executed_check_count": obj.executed_check_count,
        "skipped_count": obj.skipped_count,
        "unavailable_count": obj.unavailable_count,
        "supported_scope_statement": obj.supported_scope_statement,
        "evidence_manifest_hash": str(obj.evidence_manifest_hash),
        "derivation_timestamp": obj.derivation_timestamp,
    }


def _verdict_evidence_from(data: dict[str, Any]) -> VerdictEvidence:
    try:
        return VerdictEvidence(
            run_id=RunId(str(data["run_id"])),
            workload_id=WorkloadId(str(data["workload_id"])),
            verdict_state=str(data["verdict_state"]),
            executed_check_count=int(data["executed_check_count"]),
            skipped_count=int(data["skipped_count"]),
            unavailable_count=int(data["unavailable_count"]),
            supported_scope_statement=str(data["supported_scope_statement"]),
            evidence_manifest_hash=_require_hash(data["evidence_manifest_hash"]),
            derivation_timestamp=str(data["derivation_timestamp"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"incomplete verdict evidence payload: {exc}") from exc


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
