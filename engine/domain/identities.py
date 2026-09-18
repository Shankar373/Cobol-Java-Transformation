"""Core identity types for the validation engine.

These are immutable value objects that represent cryptographic and logical identities
throughout the system. Every identity is explicit, traceable, and content-addressed
where applicable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

# ---------------------------------------------------------------------------
# Generic hash wrapper
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContentHash:
    """SHA-256 content hash. Immutable by design."""

    digest: str  # hex-encoded
    algorithm: Final[str] = "sha256"

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ValueError(f"V1 only supports sha256, got {self.algorithm}")
        if len(self.digest) != 64:
            raise ValueError(f"SHA-256 digest must be 64 hex chars, got {len(self.digest)}")

    @classmethod
    def from_bytes(cls, data: bytes) -> ContentHash:
        return cls(digest=hashlib.sha256(data).hexdigest())

    @classmethod
    def from_string(cls, text: str) -> ContentHash:
        return cls.from_bytes(text.encode("utf-8"))

    def verify(self, data: bytes) -> bool:
        return self.digest == hashlib.sha256(data).hexdigest()

    def __str__(self) -> str:
        return f"sha256:{self.digest}"


# ---------------------------------------------------------------------------
# Identity types — one per concept
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkloadId:
    """Unique identifier for a COBOL workload being validated."""
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("WorkloadId cannot be empty")


@dataclass(frozen=True)
class RunId:
    """Unique identifier for a single validation run."""
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("RunId cannot be empty")


@dataclass(frozen=True)
class SourceIdentity:
    """Identity of the COBOL source tree."""
    source_id: str
    source_hash: ContentHash
    file_count: int
    total_size_bytes: int

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id cannot be empty")


@dataclass(frozen=True)
class CandidateIdentity:
    """Identity of a Java candidate package."""
    candidate_id: str
    candidate_hash: ContentHash
    source_hash: ContentHash  # binding to the COBOL source
    file_count: int
    total_size_bytes: int

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id cannot be empty")


@dataclass(frozen=True)
class OracleIdentity:
    """Identity of the COBOL oracle. Digest-pinned, never mutable."""
    oracle_id: str  # V1: "gnucobol-3.1.2"
    image_digest: str  # sha256:...
    compiler_version: str
    preprocessor_version: str | None = None
    base_image: str | None = None

    def __post_init__(self) -> None:
        if not self.oracle_id:
            raise ValueError("oracle_id cannot be empty")
        if not self.image_digest.startswith("sha256:"):
            raise ValueError("image_digest must be sha256-pinned (never mutable tag)")
        if not self.compiler_version:
            raise ValueError("compiler_version cannot be empty")


@dataclass(frozen=True)
class EnvironmentIdentity:
    """Identity of the execution environment."""
    runtime_id: str
    java_version: str | None = None
    cobol_compiler: str | None = None
    os_base: str | None = None
    network_policy: str = "none"
    resource_limits: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InputIdentity:
    """Identity of controlled inputs to an execution."""
    input_id: str
    stdin_hash: ContentHash | None = None
    input_files: dict[str, ContentHash] = field(default_factory=dict)

    @property
    def combined_hash(self) -> ContentHash:
        """Compute combined hash of all inputs."""
        parts = []
        if self.stdin_hash:
            parts.append(self.stdin_hash.digest)
        for path in sorted(self.input_files.keys()):
            parts.append(self.input_files[path].digest)
        combined = "".join(parts)
        return ContentHash.from_string(combined)


@dataclass(frozen=True)
class ArtifactIdentity:
    """Identity of a captured artifact."""
    artifact_id: str
    artifact_type: str  # one of V1 registry
    logical_name: str
    producer_role: str  # "ORACLE" or "CANDIDATE"
    content_hash: ContentHash
    size_bytes: int
    record_count: int | None = None

    def __post_init__(self) -> None:
        valid_types = {"STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"}
        if self.artifact_type not in valid_types:
            raise ValueError(f"artifact_type must be one of {valid_types}, got {self.artifact_type}")
        if self.producer_role not in ("ORACLE", "CANDIDATE"):
            raise ValueError(f"producer_role must be ORACLE or CANDIDATE, got {self.producer_role}")


@dataclass(frozen=True)
class ExecutionId:
    """Unique identifier for a single execution."""
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("ExecutionId cannot be empty")


@dataclass(frozen=True)
class ComparisonId:
    """Unique identifier for a single comparison."""
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("ComparisonId cannot be empty")


@dataclass(frozen=True)
class ContractId:
    """Unique identifier for a contract."""
    contract_type: str  # "ORACLE", "ARTIFACT", "VERDICT", "JAVA_CANDIDATE", "PRODUCER"
    version: str

    def __post_init__(self) -> None:
        valid_types = {"ORACLE", "ARTIFACT", "VERDICT", "JAVA_CANDIDATE", "PRODUCER"}
        if self.contract_type not in valid_types:
            raise ValueError(f"contract_type must be one of {valid_types}, got {self.contract_type}")


@dataclass(frozen=True)
class ComparatorId:
    """Unique identifier for a comparator."""
    comparator_id: str
    version: str

    def __post_init__(self) -> None:
        if not self.comparator_id:
            raise ValueError("comparator_id cannot be empty")


# ---------------------------------------------------------------------------
# Adapter status model
# ---------------------------------------------------------------------------

class AdapterStatus(Enum):
    """Adapter status — observed, never inferred."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"


# ---------------------------------------------------------------------------
# Verdict states
# ---------------------------------------------------------------------------

class VerdictState(Enum):
    """Seven-state verdict vocabulary. No more, no less."""
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNPROVEN = "UNPROVEN"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"
