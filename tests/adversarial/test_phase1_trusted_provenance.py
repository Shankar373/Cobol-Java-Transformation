"""Phase 1 trust/provenance adversarial tests.

These tests exercise the production trust boundary with trusted provenance
required. A VERIFIED result is valid only when observed runtime, producer,
environment, artifact, and comparison identities remain consistently bound.
"""

from __future__ import annotations

from dataclasses import replace
import json

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
from engine.evidence.integrity import EvidenceIntegrityValidator
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import derive_verdict


RUN = RunId("phase1-trust")
SOURCE_HASH = ContentHash.from_string("source")
ORACLE_DIGEST = "sha256:" + "a" * 64
CANDIDATE_DIGEST = "eclipse-temurin@sha256:" + "b" * 64
JAVA_VERSION = 'openjdk version "21.0.8" 2025-07-15'
PRODUCER_ID = "internal-native-java-producer"
PRODUCER_VERSION = "1.0.0"
COBOL_VERSION = "cobc (GnuCOBOL) 3.1.2"


def _execution(
    execution_id: str,
    runtime_id: str,
    *,
    image_digest: str | None,
    java_version: str | None = None,
    cobol_compiler: str | None = None,
    producer: bool = False,
) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(execution_id),
        run_id=RUN,
        runtime_id=runtime_id,
        command="trusted-test-execution",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-28T00:00:00+00:00",
        end_time="2026-09-28T00:00:01+00:00",
        exit_code=0,
        stdout_hash=ContentHash.from_bytes(b"same"),
        stderr_hash=ContentHash.from_bytes(b""),
        generated_files={},
        source_tree_hash_before=SOURCE_HASH,
        source_tree_hash_after=SOURCE_HASH,
        termination_status="normal",
        timeout_applied=False,
        java_version=java_version,
        docker_version="27.5.1",
        cobol_compiler=cobol_compiler,
        image_digest=image_digest,
        producer_identity=PRODUCER_ID if producer else None,
        producer_version=PRODUCER_VERSION if producer else None,
    )


def _artifact(
    artifact_id: str,
    execution_id: str,
    role: str,
) -> ArtifactEvidence:
    content_hash = ContentHash.from_bytes(b"same")
    identity = ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type="STDOUT",
        logical_name=artifact_id,
        producer_role=role,
        content_hash=content_hash,
        size_bytes=4,
    )
    return ArtifactEvidence(
        artifact=identity,
        execution_id=ExecutionId(execution_id),
        capture_time="2026-09-28T00:00:01+00:00",
        content_hash=content_hash,
        size_bytes=4,
    )


def _manifest(
    *,
    oracle_execution: ExecutionEvidence | None = None,
    candidate_execution: ExecutionEvidence | None = None,
    candidate_identity: CandidateIdentity | None = None,
    oracle_identity: OracleIdentity | None = None,
    environment_identities: tuple[EnvironmentIdentity, ...] | None = None,
    producer_identity: str | None = PRODUCER_ID,
    producer_version: str | None = PRODUCER_VERSION,
    artifacts: tuple[ArtifactEvidence, ...] | None = None,
    comparisons: tuple[ComparisonEvidence, ...] | None = None,
) -> EvidenceManifest:
    oracle_execution = oracle_execution or _execution(
        "oracle-1", "oracle-gnucobol-3.1.2",
        image_digest=ORACLE_DIGEST, cobol_compiler=COBOL_VERSION,
    )
    candidate_execution = candidate_execution or _execution(
        "candidate-1", "candidate-java",
        image_digest=CANDIDATE_DIGEST, java_version=JAVA_VERSION,
        producer=True,
    )
    candidate_identity = candidate_identity or CandidateIdentity(
        candidate_id="candidate",
        candidate_hash=ContentHash.from_string("candidate"),
        source_hash=SOURCE_HASH,
        file_count=1,
        total_size_bytes=4,
        producer_identity=producer_identity,
        producer_version=producer_version,
        runtime_image_digest=CANDIDATE_DIGEST,
        java_version=JAVA_VERSION,
    )
    oracle_identity = oracle_identity or OracleIdentity(
        oracle_id="gnucobol-3.1.2",
        image_digest=ORACLE_DIGEST,
        compiler_version=COBOL_VERSION,
    )
    environment_identities = environment_identities or (
        EnvironmentIdentity(
            runtime_id="oracle-gnucobol-3.1.2",
            cobol_compiler=COBOL_VERSION,
            docker_version="27.5.1",
            image_digest=ORACLE_DIGEST,
        ),
        EnvironmentIdentity(
            runtime_id="candidate-java",
            java_version=JAVA_VERSION,
            docker_version="27.5.1",
            image_digest=CANDIDATE_DIGEST,
        ),
    )
    artifacts = artifacts or (
        _artifact("oracle-stdout", "oracle-1", "ORACLE"),
        _artifact("candidate-stdout", "candidate-1", "CANDIDATE"),
    )
    comparisons = comparisons or (
        ComparisonEvidence(
            comparison_id="comparison-1",
            run_id=RUN,
            comparator_id="stdout-exact",
            comparator_version="1.0",
            oracle_artifact_id="oracle-stdout",
            candidate_artifact_id="candidate-stdout",
            artifact_type="STDOUT",
            result="MATCH",
            normalization_applied=(),
            differences=(),
            field_level_results=(),
            content_hash=ContentHash.from_string(
                json.dumps({"result": "MATCH"}, sort_keys=True)
            ),
        ),
    )
    return EvidenceManifest(
        manifest_version="1.0",
        run_id=RUN,
        workload_id=WorkloadId("phase1-trust"),
        source_identity=SourceIdentity(
            source_id="source",
            source_hash=SOURCE_HASH,
            file_count=1,
            total_size_bytes=10,
        ),
        candidate_identity=candidate_identity,
        oracle_identity=oracle_identity,
        environment_identities=environment_identities,
        controlled_input=InputIdentity("input", ContentHash.from_bytes(b"")),
        execution_evidence=(oracle_execution, candidate_execution),
        artifact_evidence=artifacts,
        comparison_evidence=comparisons,
        producer_identity=producer_identity,
        producer_version=producer_version,
        require_trusted_provenance=True,
    )


def _rejects(manifest: EvidenceManifest) -> None:
    result = EvidenceIntegrityValidator().validate(manifest)
    assert isinstance(result, list)
    assert result
    assert derive_verdict(manifest).state.name != "VERIFIED"


def test_valid_trusted_manifest_can_verify():
    manifest = _manifest()
    assert isinstance(EvidenceIntegrityValidator().validate(manifest), object)
    assert not isinstance(EvidenceIntegrityValidator().validate(manifest), list)
    assert derive_verdict(manifest).state.name == "VERIFIED"


def test_oracle_digest_mismatch_cannot_verify():
    execution = _execution(
        "oracle-1", "oracle-gnucobol-3.1.2",
        image_digest="sha256:" + "c" * 64, cobol_compiler=COBOL_VERSION,
    )
    _rejects(_manifest(oracle_execution=execution))


def test_candidate_runtime_mismatch_cannot_verify():
    execution = _execution(
        "candidate-1", "candidate-java",
        image_digest=CANDIDATE_DIGEST,
        java_version='openjdk version "25.0.1" 2026-01-20',
        producer=True,
    )
    _rejects(_manifest(candidate_execution=execution))


def test_producer_identity_mismatch_cannot_verify():
    execution = _execution(
        "candidate-1", "candidate-java",
        image_digest=CANDIDATE_DIGEST,
        java_version=JAVA_VERSION,
        producer=True,
    )
    candidate = CandidateIdentity(
        candidate_id="candidate",
        candidate_hash=ContentHash.from_string("candidate"),
        source_hash=SOURCE_HASH,
        file_count=1,
        total_size_bytes=4,
        producer_identity="different-producer",
        producer_version=PRODUCER_VERSION,
        runtime_image_digest=CANDIDATE_DIGEST,
        java_version=JAVA_VERSION,
    )
    _rejects(_manifest(candidate_execution=execution, candidate_identity=candidate))


def test_environment_identity_mismatch_cannot_verify():
    env = (
        EnvironmentIdentity(
            runtime_id="oracle-gnucobol-3.1.2",
            cobol_compiler=COBOL_VERSION,
            docker_version="27.5.1",
            image_digest=ORACLE_DIGEST,
        ),
        EnvironmentIdentity(
            runtime_id="candidate-java",
            java_version='openjdk version "25.0.1" 2026-01-20',
            docker_version="27.5.1",
            image_digest=CANDIDATE_DIGEST,
        ),
    )
    _rejects(_manifest(environment_identities=env))


def test_execution_provenance_tampering_cannot_verify():
    original = _execution(
        "candidate-1", "candidate-java",
        image_digest=CANDIDATE_DIGEST,
        java_version=JAVA_VERSION,
        producer=True,
    )
    tampered = replace(original, java_version='openjdk version "25.0.1" 2026-01-20')
    _rejects(_manifest(candidate_execution=tampered))


def test_artifact_identity_tampering_cannot_verify():
    original = _artifact("candidate-stdout", "candidate-1", "CANDIDATE")
    tampered_identity = replace(
        original.artifact,
        content_hash=ContentHash.from_bytes(b"tampered"),
    )
    tampered = replace(original, artifact=tampered_identity)
    artifacts = (
        _artifact("oracle-stdout", "oracle-1", "ORACLE"),
        tampered,
    )
    _rejects(_manifest(artifacts=artifacts))


def test_comparison_from_different_execution_cannot_verify():
    foreign_run = RunId("different-run")
    foreign_execution = replace(
        _execution(
            "candidate-foreign", "candidate-java",
            image_digest=CANDIDATE_DIGEST,
            java_version=JAVA_VERSION,
            producer=True,
        ),
        run_id=foreign_run,
    )
    foreign_artifact = _artifact("candidate-foreign-artifact", "candidate-foreign", "CANDIDATE")
    comparison = ComparisonEvidence(
        comparison_id="comparison-foreign",
        run_id=RUN,
        comparator_id="stdout-exact",
        comparator_version="1.0",
        oracle_artifact_id="oracle-stdout",
        candidate_artifact_id="candidate-foreign-artifact",
        artifact_type="STDOUT",
        result="MATCH",
        normalization_applied=(),
        differences=(),
        field_level_results=(),
        content_hash=ContentHash.from_string("foreign"),
    )
    manifest = _manifest(
        candidate_execution=foreign_execution,
        artifacts=(
            _artifact("oracle-stdout", "oracle-1", "ORACLE"),
            foreign_artifact,
        ),
        comparisons=(comparison,),
    )
    _rejects(manifest)


def test_missing_required_provenance_cannot_verify():
    manifest = _manifest(
        producer_identity=None,
        producer_version=None,
        candidate_execution=_execution(
            "candidate-1", "candidate-java",
            image_digest=None, java_version=None, producer=False,
        ),
        oracle_execution=_execution(
            "oracle-1", "oracle-gnucobol-3.1.2",
            image_digest=None, cobol_compiler=None,
        ),
    )
    _rejects(manifest)
