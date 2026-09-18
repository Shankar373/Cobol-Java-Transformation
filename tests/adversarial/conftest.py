"""Shared fixtures for adversarial testing.

Every fixture creates minimal valid EvidenceManifest objects that can be
mutated to test specific attack vectors. The goal is to isolate the
verdict derivation logic and prove it resists manipulation.
"""

from __future__ import annotations

from engine.domain.identities import (
    ArtifactIdentity,
    CandidateIdentity,
    ContentHash,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    WorkloadId,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)


def _hash(s: str) -> ContentHash:
    return ContentHash.from_string(s)


def make_oracle_exec(
    run_id: RunId,
    exec_id: str = "oracle-exec-1",
    status: str = "normal",
    timeout: bool = False,
) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(value=exec_id),
        run_id=run_id,
        runtime_id="oracle-gnucobol-3.1.2",
        command="cobc -x /workspace/src/prog.cbl && /workspace/prog",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-15T00:00:00Z",
        end_time="2026-09-15T00:00:01Z",
        exit_code=0 if status == "normal" else 1,
        stdout_hash=_hash(f"oracle-stdout-{exec_id}"),
        stderr_hash=_hash(f"oracle-stderr-{exec_id}"),
        generated_files={},
        source_tree_hash_before=_hash("source-before"),
        source_tree_hash_after=_hash("source-after"),
        termination_status=status,
        timeout_applied=timeout,
    )


def make_candidate_exec(
    run_id: RunId,
    exec_id: str = "candidate-exec-1",
    status: str = "normal",
    timeout: bool = False,
) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(value=exec_id),
        run_id=run_id,
        runtime_id="candidate-java",
        command="java -cp /workspace/classes Main",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-15T00:00:00Z",
        end_time="2026-09-15T00:00:01Z",
        exit_code=0 if status == "normal" else 1,
        stdout_hash=_hash(f"candidate-stdout-{exec_id}"),
        stderr_hash=_hash(f"candidate-stderr-{exec_id}"),
        generated_files={},
        source_tree_hash_before=_hash("source-before"),
        source_tree_hash_after=_hash("source-after"),
        termination_status=status,
        timeout_applied=timeout,
    )


def make_artifact(
    artifact_id: str,
    artifact_type: str,
    producer_role: str,
    content: bytes,
    record_count: int | None = None,
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        logical_name=f"{artifact_type.lower()}-{producer_role.lower()}",
        producer_role=producer_role,
        content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content),
        record_count=record_count,
    )


def make_artifact_evidence(
    artifact: ArtifactIdentity,
    execution_id: str = "oracle-exec-1",
) -> ArtifactEvidence:
    return ArtifactEvidence(
        artifact=artifact,
        execution_id=ExecutionId(value=execution_id),
        capture_time="2026-09-15T00:00:01Z",
        content_hash=artifact.content_hash,
        size_bytes=artifact.size_bytes,
        record_count=artifact.record_count,
    )


def make_comparison(
    run_id: RunId,
    result: str = "MATCH",
    artifact_type: str = "STDOUT",
    oracle_id: str = "art-oracle-stdout",
    candidate_id: str = "art-candidate-stdout",
    differences: tuple[str, ...] = (),
) -> ComparisonEvidence:
    return ComparisonEvidence(
        comparison_id=f"comp-{oracle_id}-{candidate_id}",
        run_id=run_id,
        comparator_id=f"{artifact_type}_COMPARATOR",
        comparator_version="1.0.0",
        oracle_artifact_id=oracle_id,
        candidate_artifact_id=candidate_id,
        artifact_type=artifact_type,
        result=result,
        normalization_applied=("crlf_to_lf",) if artifact_type in ("STDOUT", "STDERR", "TEXT_FILE") else (),
        differences=differences,
        field_level_results=(),
        content_hash=_hash(f"comp-{result}-{oracle_id}-{candidate_id}"),
    )


def make_manifest(
    run_id: RunId | None = None,
    workload_id: str = "test-workload",
    oracle_exec: ExecutionEvidence | None = None,
    candidate_exec: ExecutionEvidence | None = None,
    artifacts: tuple[ArtifactEvidence, ...] = (),
    comparisons: tuple[ComparisonEvidence, ...] = (),
    source_hash_str: str = "source-hash-1",
    oracle_id_str: str = "gnucobol-3.1.2",
    oracle_digest: str = "sha256:" + "a" * 64,
    candidate_identity: CandidateIdentity | None = None,
) -> EvidenceManifest:
    if run_id is None:
        run_id = RunId(value="run-test-20260915000000")
    if oracle_exec is None:
        oracle_exec = make_oracle_exec(run_id)
    if candidate_exec is None:
        candidate_exec = make_candidate_exec(run_id)

    return EvidenceManifest(
        manifest_version="1.0",
        run_id=run_id,
        workload_id=WorkloadId(value=workload_id),
        source_identity=SourceIdentity(
            source_id="cobol-source",
            source_hash=_hash(source_hash_str),
            file_count=1,
            total_size_bytes=100,
        ),
        candidate_identity=candidate_identity or CandidateIdentity(
            candidate_id="java-candidate",
            candidate_hash=_hash("candidate-hash-1"),
            source_hash=_hash(source_hash_str),
            file_count=1,
            total_size_bytes=100,
        ),
        oracle_identity=OracleIdentity(
            oracle_id=oracle_id_str,
            image_digest=oracle_digest,
            compiler_version="3.1.2.0",
        ),
        environment_identities=(),
        controlled_input=InputIdentity(
            input_id="input-1",
            stdin_hash=_hash("input-data"),
        ),
        execution_evidence=(oracle_exec, candidate_exec),
        artifact_evidence=artifacts,
        comparison_evidence=comparisons,
    )
