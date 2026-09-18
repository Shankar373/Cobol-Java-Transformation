"""Tests for contract loading and validation."""

import pytest

from engine.contracts.models import (
    ArtifactType,
    ContractRegistry,
    ContractVersion,
    FailurePolicy,
    NormalizationPolicy,
    OrderingPolicy,
)
from engine.contracts.validator import (
    ContractValidationError,
    ContractValidator,
    NoContractError,
    load_artifact_contract,
    load_candidate_contract,
    load_oracle_contract,
    load_producer_contract,
    load_verdict_contract,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

VALID_ARTIFACT_CONTRACT_DATA = {
    "contract_id": "artifact-v1",
    "version": "1.0",
    "artifact_types": [
        {"name": "STDOUT", "compared_as": "Process stdout bytes"},
        {"name": "STDERR", "compared_as": "Process stderr bytes"},
        {"name": "EXIT_STATUS", "compared_as": "Observed process exit code"},
        {"name": "TEXT_FILE", "compared_as": "Text file bytes"},
        {"name": "FIXED_RECORD", "compared_as": "Fixed-length record sequence"},
    ],
    "comparators": [
        {"comparator_id": "STDOUT_COMPARATOR", "artifact_type": "STDOUT"},
        {"comparator_id": "STDERR_COMPARATOR", "artifact_type": "STDERR"},
        {"comparator_id": "EXIT_STATUS_COMPARATOR", "artifact_type": "EXIT_STATUS"},
        {"comparator_id": "TEXT_FILE_COMPARATOR", "artifact_type": "TEXT_FILE"},
        {"comparator_id": "FIXED_RECORD_COMPARATOR", "artifact_type": "FIXED_RECORD"},
    ],
}

VALID_ORACLE_CONTRACT_DATA = {
    "contract_id": "oracle-v1",
    "version": "1.0",
    "oracle_id": "gnucobol-3.1.2",
    "compiler_version": "3.1.2.0",
    "preprocessor_version": "1.4",
    "base_image": "alpine:3.19",
}

VALID_CANDIDATE_CONTRACT_DATA = {
    "contract_id": "candidate-v1",
    "version": "1.0",
    "requires_build_system": False,
    "requires_external_dependencies": False,
    "requires_network": False,
}

VALID_VERDICT_CONTRACT_DATA = {
    "contract_id": "verdict-v1",
    "version": "1.0",
    "allowed_states": [
        "VERIFIED", "PARTIAL", "FAILED", "UNPROVEN",
        "UNAVAILABLE", "UNSUPPORTED", "ERROR"
    ],
}

VALID_PRODUCER_CONTRACT_DATA = {
    "contract_id": "producer-v1",
    "version": "1.0",
    "requires_manifest": True,
    "requires_mutation_regeneration": True,
}


# ---------------------------------------------------------------------------
# Artifact contract tests
# ---------------------------------------------------------------------------

class TestArtifactContractLoading:
    def test_load_valid_contract(self):
        contract = load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA)
        assert contract.version == ContractVersion.V1_0
        assert len(contract.artifact_types) == 5
        assert len(contract.comparators) == 5

    def test_invalid_version_raises(self):
        data = {**VALID_ARTIFACT_CONTRACT_DATA, "version": "2.0"}
        with pytest.raises(ContractValidationError, match="Unsupported version"):
            load_artifact_contract(data)

    def test_unsupported_artifact_type_raises(self):
        data = {
            **VALID_ARTIFACT_CONTRACT_DATA,
            "artifact_types": [{"name": "INDEXED", "compared_as": "binary"}],
        }
        with pytest.raises(ContractValidationError, match="artifact_type"):
            load_artifact_contract(data)


class TestArtifactType:
    def test_valid_types(self):
        for name in ["STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"]:
            at = ArtifactType(name=name, compared_as="test")
            assert at.name == name

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="artifact_type"):
            ArtifactType(name="INDEXED", compared_as="binary")


class TestNormalizationPolicy:
    def test_empty_policy(self):
        policy = NormalizationPolicy()
        assert policy.allowed_normalizations == ()

    def test_allowed_crlf(self):
        policy = NormalizationPolicy(allowed_normalizations=("crlf_to_lf",))
        assert "crlf_to_lf" in policy.allowed_normalizations

    def test_forbidden_normalization_raises(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("case_folding",))

    def test_substring_containment_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("substring_containment",))


class TestOrderingPolicy:
    def test_valid_orderings(self):
        for order in ["SEQUENTIAL", "SORTED", "UNORDERED"]:
            policy = OrderingPolicy(order=order)
            assert policy.order == order

    def test_invalid_ordering_raises(self):
        with pytest.raises(ValueError, match="Invalid ordering"):
            OrderingPolicy(order="RANDOM")


class TestFailurePolicy:
    def test_default_policy(self):
        policy = FailurePolicy()
        assert policy.on_missing == "UNAVAILABLE"
        assert policy.on_malformed == "INCONCLUSIVE"

    def test_invalid_on_missing_raises(self):
        with pytest.raises(ValueError, match="Invalid on_missing"):
            FailurePolicy(on_missing="SKIP")


# ---------------------------------------------------------------------------
# Oracle contract tests
# ---------------------------------------------------------------------------

class TestOracleContractLoading:
    def test_load_valid_contract(self):
        contract = load_oracle_contract(VALID_ORACLE_CONTRACT_DATA)
        assert contract.version == ContractVersion.V1_0
        assert contract.oracle_id == "gnucobol-3.1.2"
        assert contract.compiler_version == "3.1.2.0"

    def test_empty_oracle_id_raises(self):
        data = {**VALID_ORACLE_CONTRACT_DATA, "oracle_id": ""}
        with pytest.raises(ContractValidationError, match="oracle_id is required"):
            load_oracle_contract(data)

    def test_empty_compiler_version_raises(self):
        data = {**VALID_ORACLE_CONTRACT_DATA, "compiler_version": ""}
        with pytest.raises(ContractValidationError, match="compiler_version is required"):
            load_oracle_contract(data)

    def test_validate_identity(self):
        contract = load_oracle_contract(VALID_ORACLE_CONTRACT_DATA)
        assert contract.validate_identity(
            "gnucobol-3.1.2",
            "sha256:" + "a" * 64
        )
        assert not contract.validate_identity(
            "wrong-oracle",
            "sha256:" + "a" * 64
        )
        assert not contract.validate_identity(
            "gnucobol-3.1.2",
            "latest"
        )


# ---------------------------------------------------------------------------
# Candidate contract tests
# ---------------------------------------------------------------------------

class TestCandidateContractLoading:
    def test_load_valid_contract(self):
        contract = load_candidate_contract(VALID_CANDIDATE_CONTRACT_DATA)
        assert contract.version == ContractVersion.V1_0
        assert contract.requires_build_system is False

    def test_validate_candidate_shape(self):
        contract = load_candidate_contract(VALID_CANDIDATE_CONTRACT_DATA)
        assert contract.validate_candidate_shape(
            has_build_files=False,
            has_external_deps=False,
        )
        assert not contract.validate_candidate_shape(
            has_build_files=True,
            has_external_deps=False,
        )


# ---------------------------------------------------------------------------
# Verdict contract tests
# ---------------------------------------------------------------------------

class TestVerdictContractLoading:
    def test_load_valid_contract(self):
        contract = load_verdict_contract(VALID_VERDICT_CONTRACT_DATA)
        assert contract.version == ContractVersion.V1_0
        assert len(contract.allowed_states) == 7

    def test_valid_state(self):
        contract = load_verdict_contract(VALID_VERDICT_CONTRACT_DATA)
        assert contract.is_valid_state("VERIFIED")
        assert contract.is_valid_state("ERROR")
        assert not contract.is_valid_state("PASS")

    def test_validate_derivation(self):
        contract = load_verdict_contract(VALID_VERDICT_CONTRACT_DATA)
        # Zero checks cannot become VERIFIED
        assert not contract.validate_derivation(executed_checks=0, has_evidence=True)
        # Missing evidence cannot become VERIFIED
        assert not contract.validate_derivation(executed_checks=5, has_evidence=False)
        # Valid case
        assert contract.validate_derivation(executed_checks=5, has_evidence=True)


# ---------------------------------------------------------------------------
# Producer contract tests
# ---------------------------------------------------------------------------

class TestProducerContractLoading:
    def test_load_valid_contract(self):
        contract = load_producer_contract(VALID_PRODUCER_CONTRACT_DATA)
        assert contract.version == ContractVersion.V1_0

    def test_validate_manifest_complete(self):
        contract = load_producer_contract(VALID_PRODUCER_CONTRACT_DATA)
        manifest = {field: "value" for field in contract.MANDATORY_MANIFEST_FIELDS}
        missing = contract.validate_manifest(manifest)
        assert missing == []

    def test_validate_manifest_missing_fields(self):
        contract = load_producer_contract(VALID_PRODUCER_CONTRACT_DATA)
        manifest = {"producer_identity": "test"}
        missing = contract.validate_manifest(manifest)
        assert len(missing) > 0
        assert "producer_version" in missing


# ---------------------------------------------------------------------------
# Contract registry tests
# ---------------------------------------------------------------------------

class TestContractRegistry:
    def test_empty_registry(self):
        registry = ContractRegistry()
        assert not registry.is_complete()
        assert len(registry.get_missing_contracts()) == 5

    def test_partial_registry(self):
        registry = ContractRegistry(
            artifact=load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA),
            oracle=load_oracle_contract(VALID_ORACLE_CONTRACT_DATA),
        )
        assert not registry.is_complete()
        missing = registry.get_missing_contracts()
        assert "ARTIFACT" not in missing
        assert "ORACLE" not in missing
        assert "JAVA_CANDIDATE" in missing


# ---------------------------------------------------------------------------
# Contract validator tests
# ---------------------------------------------------------------------------

class TestContractValidator:
    def test_require_all_contracts_pass(self):
        registry = ContractRegistry(
            artifact=load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA),
            oracle=load_oracle_contract(VALID_ORACLE_CONTRACT_DATA),
            candidate=load_candidate_contract(VALID_CANDIDATE_CONTRACT_DATA),
            verdict=load_verdict_contract(VALID_VERDICT_CONTRACT_DATA),
            producer=load_producer_contract(VALID_PRODUCER_CONTRACT_DATA),
        )
        validator = ContractValidator(registry=registry)
        validator.require_all_contracts()  # Should not raise

    def test_require_all_contracts_fail(self):
        registry = ContractRegistry()
        validator = ContractValidator(registry=registry)
        with pytest.raises(ContractValidationError, match="Missing contracts"):
            validator.require_all_contracts()

    def test_no_contract_error(self):
        registry = ContractRegistry()
        validator = ContractValidator(registry=registry)
        with pytest.raises(NoContractError, match="ARTIFACT"):
            validator.require_artifact_contract()

    def test_validate_artifact_type_supported(self):
        registry = ContractRegistry(
            artifact=load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA),
        )
        validator = ContractValidator(registry=registry)
        validator.validate_artifact_type("STDOUT")  # Should not raise

    def test_validate_artifact_type_unsupported(self):
        registry = ContractRegistry(
            artifact=load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA),
        )
        validator = ContractValidator(registry=registry)
        with pytest.raises(ContractValidationError, match="Unsupported artifact type"):
            validator.validate_artifact_type("INDEXED")

    def test_validate_comparator(self):
        registry = ContractRegistry(
            artifact=load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA),
        )
        validator = ContractValidator(registry=registry)
        comp = validator.validate_comparator("STDOUT_COMPARATOR", "STDOUT")
        assert comp.artifact_type == "STDOUT"

    def test_validate_comparator_wrong_id(self):
        registry = ContractRegistry(
            artifact=load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA),
        )
        validator = ContractValidator(registry=registry)
        with pytest.raises(ContractValidationError, match="Comparator ID mismatch"):
            validator.validate_comparator("WRONG_COMPARATOR", "STDOUT")
