"""Contract models for the validation engine.

These models represent the authoritative contracts that govern the validation system.
Contracts are loaded, validated, and enforced — never silently weakened or bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar


class ContractVersion(Enum):
    """Supported contract versions."""
    V1_0 = "1.0"


@dataclass(frozen=True)
class ArtifactType:
    """A registered artifact type in the V1 registry."""
    name: str
    compared_as: str
    notes: str = ""

    VALID_TYPES: ClassVar[set[str]] = frozenset({
        "STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"
    })

    def __post_init__(self) -> None:
        if self.name not in self.VALID_TYPES:
            raise ValueError(f"artifact_type must be one of {self.VALID_TYPES}, got {self.name}")


@dataclass(frozen=True)
class NormalizationPolicy:
    """Permitted normalizations for artifact comparison."""
    allowed_normalizations: tuple[str, ...] = ()

    FORBIDDEN: ClassVar[frozenset[str]] = frozenset({
        "case_folding", "whitespace_normalization", "encoding_conversion",
        "trailing_whitespace_removal", "trailing_newline_removal",
        "substring_containment",
    })

    def __post_init__(self) -> None:
        for norm in self.allowed_normalizations:
            if norm in self.FORBIDDEN:
                raise ValueError(f"Normalization '{norm}' is permanently forbidden")


@dataclass(frozen=True)
class OrderingPolicy:
    """Ordering rules for artifact comparison."""
    order: str = "SEQUENTIAL"  # SEQUENTIAL, SORTED, UNORDERED

    def __post_init__(self) -> None:
        if self.order not in ("SEQUENTIAL", "SORTED", "UNORDERED"):
            raise ValueError(f"Invalid ordering: {self.order}")


@dataclass(frozen=True)
class FailurePolicy:
    """Failure behavior for missing/malformed artifacts."""
    on_missing: str = "UNAVAILABLE"  # UNAVAILABLE or FAILED
    on_malformed: str = "INCONCLUSIVE"
    on_extra: str = "MISMATCH"

    def __post_init__(self) -> None:
        if self.on_missing not in ("UNAVAILABLE", "FAILED"):
            raise ValueError(f"Invalid on_missing: {self.on_missing}")
        if self.on_malformed not in ("INCONCLUSIVE", "MISMATCH"):
            raise ValueError(f"Invalid on_malformed: {self.on_malformed}")


@dataclass(frozen=True)
class ComparatorSpec:
    """Specification for a comparator."""
    comparator_id: str
    version: str
    artifact_type: str
    normalization_policy: NormalizationPolicy = field(default_factory=NormalizationPolicy)
    ordering_policy: OrderingPolicy = field(default_factory=OrderingPolicy)
    failure_policy: FailurePolicy = field(default_factory=FailurePolicy)


@dataclass(frozen=True)
class ArtifactContract:
    """Artifact contract specification."""
    contract_id: str
    version: ContractVersion
    artifact_types: tuple[ArtifactType, ...]
    comparators: tuple[ComparatorSpec, ...]
    permanently_forbidden: tuple[str, ...] = ("substring_containment",)

    def get_comparator(self, artifact_type: str) -> ComparatorSpec | None:
        """Get comparator for an artifact type."""
        for comp in self.comparators:
            if comp.artifact_type == artifact_type:
                return comp
        return None

    def is_type_supported(self, artifact_type: str) -> bool:
        """Check if an artifact type is in the V1 registry."""
        return artifact_type in {at.name for at in self.artifact_types}


@dataclass(frozen=True)
class OracleContract:
    """Oracle contract specification."""
    contract_id: str
    version: ContractVersion
    oracle_id: str  # V1: "gnucobol-3.1.2"
    compiler_version: str
    preprocessor_version: str | None = None
    base_image: str | None = None

    def validate_identity(self, oracle_id: str, image_digest: str) -> bool:
        """Validate oracle identity matches contract."""
        return (
            oracle_id == self.oracle_id
            and image_digest.startswith("sha256:")
        )


@dataclass(frozen=True)
class CandidateContract:
    """Java candidate contract specification."""
    contract_id: str
    version: ContractVersion
    requires_build_system: bool = False
    requires_external_dependencies: bool = False
    requires_network: bool = False

    # V1: plain source tree, no build system, no external deps, no network
    def validate_candidate_shape(self, has_build_files: bool, has_external_deps: bool) -> bool:
        """Validate candidate shape matches contract."""
        if has_build_files and not self.requires_build_system:
            return False
        return not has_external_deps or self.requires_external_dependencies


@dataclass(frozen=True)
class VerdictContract:
    """Verdict contract specification."""
    contract_id: str
    version: ContractVersion
    allowed_states: tuple[str, ...] = (
        "VERIFIED", "PARTIAL", "FAILED", "UNPROVEN",
        "UNAVAILABLE", "UNSUPPORTED", "ERROR"
    )

    def is_valid_state(self, state: str) -> bool:
        """Check if a verdict state is valid."""
        return state in self.allowed_states

    def validate_derivation(self, executed_checks: int, has_evidence: bool) -> bool:
        """Validate verdict derivation rules."""
        # Zero checks cannot become VERIFIED
        if executed_checks == 0:
            return False
        # Missing evidence cannot become VERIFIED
        return has_evidence


@dataclass(frozen=True)
class ProducerContract:
    """Transformation producer contract specification."""
    contract_id: str
    version: ContractVersion
    requires_manifest: bool = True
    requires_mutation_regeneration: bool = True

    MANDATORY_MANIFEST_FIELDS: ClassVar[tuple[str, ...]] = (
        "producer_identity", "producer_version", "candidate_identity",
        "workload_identity", "source_hash", "generated_files", "entrypoint",
        "java_version", "dependency_declaration", "runtime_requirements",
        "generation_metadata", "mutation_regeneration_capability",
    )

    def validate_manifest(self, manifest: dict[str, Any]) -> list[str]:
        """Validate producer manifest. Returns list of missing fields."""
        missing = []
        for field_name in self.MANDATORY_MANIFEST_FIELDS:
            if field_name not in manifest:
                missing.append(field_name)
        return missing


# ---------------------------------------------------------------------------
# Contract registry
# ---------------------------------------------------------------------------

@dataclass
class ContractRegistry:
    """Registry of all active contracts."""
    artifact: ArtifactContract | None = None
    oracle: OracleContract | None = None
    candidate: CandidateContract | None = None
    verdict: VerdictContract | None = None
    producer: ProducerContract | None = None

    def is_complete(self) -> bool:
        """Check if all required contracts are loaded."""
        return all([
            self.artifact is not None,
            self.oracle is not None,
            self.candidate is not None,
            self.verdict is not None,
            self.producer is not None,
        ])

    def get_missing_contracts(self) -> list[str]:
        """Get list of missing contract names."""
        missing = []
        if self.artifact is None:
            missing.append("ARTIFACT")
        if self.oracle is None:
            missing.append("ORACLE")
        if self.candidate is None:
            missing.append("JAVA_CANDIDATE")
        if self.verdict is None:
            missing.append("VERDICT")
        if self.producer is None:
            missing.append("PRODUCER")
        return missing
