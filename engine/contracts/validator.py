"""Contract validation and loading.

Implements strict contract validation as required by the Phase-2 specification.
NO_CONTRACT must be an explicit refusal state.
There must be NO fallback comparator behavior.
There must be NO "best effort" contract interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.contracts.models import (
    ArtifactContract,
    ArtifactType,
    CandidateContract,
    ComparatorSpec,
    ContractRegistry,
    ContractVersion,
    FailurePolicy,
    NormalizationPolicy,
    OracleContract,
    OrderingPolicy,
    ProducerContract,
    VerdictContract,
)


class ContractValidationError(Exception):
    """Raised when contract validation fails."""

    def __init__(self, contract_type: str, reason: str):
        self.contract_type = contract_type
        self.reason = reason
        super().__init__(f"{contract_type} contract validation failed: {reason}")


class NoContractError(Exception):
    """Raised when a required contract is missing (NO_CONTRACT refusal)."""

    def __init__(self, contract_type: str):
        self.contract_type = contract_type
        super().__init__(f"NO_CONTRACT: {contract_type} contract not loaded")


@dataclass
class ContractValidator:
    """Validates and loads contracts. Fails closed on any error."""

    registry: ContractRegistry

    def __post_init__(self) -> None:
        if self.registry is None:
            raise ValueError("ContractRegistry cannot be None")

    def require_artifact_contract(self) -> ArtifactContract:
        """Require artifact contract to be loaded and valid."""
        if self.registry.artifact is None:
            raise NoContractError("ARTIFACT")
        return self.registry.artifact

    def require_oracle_contract(self) -> OracleContract:
        """Require oracle contract to be loaded and valid."""
        if self.registry.oracle is None:
            raise NoContractError("ORACLE")
        return self.registry.oracle

    def require_candidate_contract(self) -> CandidateContract:
        """Require candidate contract to be loaded and valid."""
        if self.registry.candidate is None:
            raise NoContractError("JAVA_CANDIDATE")
        return self.registry.candidate

    def require_verdict_contract(self) -> VerdictContract:
        """Require verdict contract to be loaded and valid."""
        if self.registry.verdict is None:
            raise NoContractError("VERDICT")
        return self.registry.verdict

    def require_producer_contract(self) -> ProducerContract:
        """Require producer contract to be loaded and valid."""
        if self.registry.producer is None:
            raise NoContractError("PRODUCER")
        return self.registry.producer

    def require_all_contracts(self) -> None:
        """Require all contracts to be loaded."""
        missing = self.registry.get_missing_contracts()
        if missing:
            raise ContractValidationError(
                "REGISTRY",
                f"Missing contracts: {', '.join(missing)}"
            )

    def validate_artifact_type(self, artifact_type: str) -> None:
        """Validate an artifact type is in the V1 registry."""
        artifact_contract = self.require_artifact_contract()
        if not artifact_contract.is_type_supported(artifact_type):
            raise ContractValidationError(
                "ARTIFACT",
                f"Unsupported artifact type: {artifact_type}"
            )

    def validate_comparator(self, comparator_id: str, artifact_type: str) -> ComparatorSpec:
        """Validate and return comparator for an artifact type."""
        artifact_contract = self.require_artifact_contract()
        comparator = artifact_contract.get_comparator(artifact_type)
        if comparator is None:
            raise ContractValidationError(
                "ARTIFACT",
                f"No comparator registered for artifact type: {artifact_type}"
            )
        if comparator.comparator_id != comparator_id:
            raise ContractValidationError(
                "ARTIFACT",
                f"Comparator ID mismatch: expected {comparator.comparator_id}, got {comparator_id}"
            )
        return comparator


# ---------------------------------------------------------------------------
# Contract loaders (from dict/JSON)
# ---------------------------------------------------------------------------

def load_artifact_contract(data: dict[str, Any]) -> ArtifactContract:
    """Load artifact contract from dictionary."""
    try:
        version = ContractVersion(data.get("version", "1.0"))
    except ValueError:
        raise ContractValidationError("ARTIFACT", f"Unsupported version: {data.get('version')}")

    artifact_types = []
    for at_data in data.get("artifact_types", []):
        try:
            artifact_types.append(ArtifactType(
                name=at_data["name"],
                compared_as=at_data.get("compared_as", ""),
                notes=at_data.get("notes", ""),
            ))
        except ValueError as e:
            raise ContractValidationError("ARTIFACT", str(e))

    comparators = []
    for comp_data in data.get("comparators", []):
        norm_policy = NormalizationPolicy(
            allowed_normalizations=tuple(comp_data.get("normalizations", []))
        )
        order_policy = OrderingPolicy(order=comp_data.get("ordering", "SEQUENTIAL"))
        failure_policy = FailurePolicy(
            on_missing=comp_data.get("on_missing", "UNAVAILABLE"),
            on_malformed=comp_data.get("on_malformed", "INCONCLUSIVE"),
        )
        comparators.append(ComparatorSpec(
            comparator_id=comp_data["comparator_id"],
            version=comp_data.get("version", "1.0.0"),
            artifact_type=comp_data["artifact_type"],
            normalization_policy=norm_policy,
            ordering_policy=order_policy,
            failure_policy=failure_policy,
        ))

    return ArtifactContract(
        contract_id=data.get("contract_id", "artifact-v1"),
        version=version,
        artifact_types=tuple(artifact_types),
        comparators=tuple(comparators),
    )


def load_oracle_contract(data: dict[str, Any]) -> OracleContract:
    """Load oracle contract from dictionary."""
    try:
        version = ContractVersion(data.get("version", "1.0"))
    except ValueError:
        raise ContractValidationError("ORACLE", f"Unsupported version: {data.get('version')}")

    oracle_id = data.get("oracle_id", "")
    if not oracle_id:
        raise ContractValidationError("ORACLE", "oracle_id is required")

    compiler_version = data.get("compiler_version", "")
    if not compiler_version:
        raise ContractValidationError("ORACLE", "compiler_version is required")

    return OracleContract(
        contract_id=data.get("contract_id", "oracle-v1"),
        version=version,
        oracle_id=oracle_id,
        compiler_version=compiler_version,
        preprocessor_version=data.get("preprocessor_version"),
        base_image=data.get("base_image"),
    )


def load_candidate_contract(data: dict[str, Any]) -> CandidateContract:
    """Load candidate contract from dictionary."""
    try:
        version = ContractVersion(data.get("version", "1.0"))
    except ValueError:
        raise ContractValidationError("JAVA_CANDIDATE", f"Unsupported version: {data.get('version')}")

    return CandidateContract(
        contract_id=data.get("contract_id", "candidate-v1"),
        version=version,
        requires_build_system=data.get("requires_build_system", False),
        requires_external_dependencies=data.get("requires_external_dependencies", False),
        requires_network=data.get("requires_network", False),
    )


def load_verdict_contract(data: dict[str, Any]) -> VerdictContract:
    """Load verdict contract from dictionary."""
    try:
        version = ContractVersion(data.get("version", "1.0"))
    except ValueError:
        raise ContractValidationError("VERDICT", f"Unsupported version: {data.get('version')}")

    allowed_states = tuple(data.get("allowed_states", [
        "VERIFIED", "PARTIAL", "FAILED", "UNPROVEN",
        "UNAVAILABLE", "UNSUPPORTED", "ERROR"
    ]))

    return VerdictContract(
        contract_id=data.get("contract_id", "verdict-v1"),
        version=version,
        allowed_states=allowed_states,
    )


def load_producer_contract(data: dict[str, Any]) -> ProducerContract:
    """Load producer contract from dictionary."""
    try:
        version = ContractVersion(data.get("version", "1.0"))
    except ValueError:
        raise ContractValidationError("PRODUCER", f"Unsupported version: {data.get('version')}")

    return ProducerContract(
        contract_id=data.get("contract_id", "producer-v1"),
        version=version,
        requires_manifest=data.get("requires_manifest", True),
        requires_mutation_regeneration=data.get("requires_mutation_regeneration", True),
    )
