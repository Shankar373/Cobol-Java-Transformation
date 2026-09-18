"""Tests for verdict derivation."""

import pytest

from engine.domain.identities import (
    CandidateIdentity,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import derive_verdict
from tests.common import make_hash

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_run_id() -> RunId:
    return RunId(value="run-001")

@pytest.fixture
def sample_workload_id() -> WorkloadId:
    return WorkloadId(value="wl-001")

@pytest.fixture
def sample_source_identity() -> SourceIdentity:
    return SourceIdentity(
        source_id="src-001",
        source_hash=make_hash("source"),
        file_count=10,
        total_size_bytes=1000,
    )

@pytest.fixture
def sample_oracle_identity() -> OracleIdentity:
    return OracleIdentity(
        oracle_id="gnucobol-3.1.2",
        image_digest="sha256:" + "a" * 64,
        compiler_version="3.1.2.0",
    )

@pytest.fixture
def sample_candidate_identity() -> CandidateIdentity:
    return CandidateIdentity(
        candidate_id="cand-001",
        candidate_hash=make_hash("candidate"),
        source_hash=make_hash("source"),
        file_count=5,
        total_size_bytes=500,
    )

@pytest.fixture
def sample_input_identity() -> InputIdentity:
    return InputIdentity(
        input_id="inp-001",
        stdin_hash=make_hash("input"),
    )

@pytest.fixture
def successful_oracle_execution(sample_run_id: RunId) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(value="exec-oracle-001"),
        run_id=sample_run_id,
        runtime_id="oracle-gnucobol-3.1.2",
        command="cobc -x test.cbl && ./test",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-14T00:00:00Z",
        end_time="2026-09-14T00:00:01Z",
        exit_code=0,
        stdout_hash=make_hash("oracle-stdout"),
        stderr_hash=make_hash("oracle-stderr"),
        generated_files={},
        source_tree_hash_before=make_hash("source-before"),
        source_tree_hash_after=make_hash("source-after"),
        termination_status="normal",
        timeout_applied=False,
    )

@pytest.fixture
def successful_candidate_execution(sample_run_id: RunId) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(value="exec-cand-001"),
        run_id=sample_run_id,
        runtime_id="candidate-java",
        command="javac Main.java && java Main",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-14T00:00:02Z",
        end_time="2026-09-14T00:00:03Z",
        exit_code=0,
        stdout_hash=make_hash("candidate-stdout"),
        stderr_hash=make_hash("candidate-stderr"),
        generated_files={},
        source_tree_hash_before=make_hash("source-before"),
        source_tree_hash_after=make_hash("source-after"),
        termination_status="normal",
        timeout_applied=False,
    )

@pytest.fixture
def matching_comparison(sample_run_id: RunId) -> ComparisonEvidence:
    return ComparisonEvidence(
        comparison_id="comp-001",
        run_id=sample_run_id,
        comparator_id="STDOUT_COMPARATOR",
        comparator_version="1.0.0",
        oracle_artifact_id="art-oracle-001",
        candidate_artifact_id="art-cand-001",
        artifact_type="STDOUT",
        result="MATCH",
        normalization_applied=(),
        differences=(),
        field_level_results=(),
        content_hash=make_hash("comparison"),
    )

@pytest.fixture
def mismatching_comparison(sample_run_id: RunId) -> ComparisonEvidence:
    return ComparisonEvidence(
        comparison_id="comp-002",
        run_id=sample_run_id,
        comparator_id="STDOUT_COMPARATOR",
        comparator_version="1.0.0",
        oracle_artifact_id="art-oracle-001",
        candidate_artifact_id="art-cand-001",
        artifact_type="STDOUT",
        result="MISMATCH",
        normalization_applied=(),
        differences=("Output differs at line 1",),
        field_level_results=(),
        content_hash=make_hash("comparison-mismatch"),
    )


# ---------------------------------------------------------------------------
# VerdictDeriver tests
# ---------------------------------------------------------------------------

class TestVerdictDeriver:
    def test_verified_when_all_match(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
        successful_candidate_execution: ExecutionEvidence,
        matching_comparison: ComparisonEvidence,
    ):
        from engine.domain.identities import ArtifactIdentity
        
        # Create minimal artifact evidence
        oracle_artifact = ArtifactIdentity(
            artifact_id="art-oracle-001",
            artifact_type="STDOUT",
            logical_name="STDOUT",
            producer_role="ORACLE",
            content_hash=make_hash("oracle-stdout"),
            size_bytes=100,
        )
        candidate_artifact = ArtifactIdentity(
            artifact_id="art-cand-001",
            artifact_type="STDOUT",
            logical_name="STDOUT",
            producer_role="CANDIDATE",
            content_hash=make_hash("candidate-stdout"),
            size_bytes=100,
        )
        oracle_artifact_evidence = ArtifactEvidence(
            artifact=oracle_artifact,
            execution_id=ExecutionId(value="exec-oracle-001"),
            capture_time="2026-09-14T00:00:01Z",
            content_hash=make_hash("oracle-stdout"),
            size_bytes=100,
        )
        candidate_artifact_evidence = ArtifactEvidence(
            artifact=candidate_artifact,
            execution_id=ExecutionId(value="exec-cand-001"),
            capture_time="2026-09-14T00:00:03Z",
            content_hash=make_hash("candidate-stdout"),
            size_bytes=100,
        )
        
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, successful_candidate_execution),
            artifact_evidence=(oracle_artifact_evidence, candidate_artifact_evidence),
            comparison_evidence=(matching_comparison,),
        )
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.VERIFIED
        assert verdict.executed_check_count == 1

    def test_failed_when_mismatch(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
        successful_candidate_execution: ExecutionEvidence,
        mismatching_comparison: ComparisonEvidence,
    ):
        from engine.domain.identities import ArtifactIdentity
        
        # Create minimal artifact evidence
        oracle_artifact = ArtifactIdentity(
            artifact_id="art-oracle-001",
            artifact_type="STDOUT",
            logical_name="STDOUT",
            producer_role="ORACLE",
            content_hash=make_hash("oracle-stdout"),
            size_bytes=100,
        )
        candidate_artifact = ArtifactIdentity(
            artifact_id="art-cand-001",
            artifact_type="STDOUT",
            logical_name="STDOUT",
            producer_role="CANDIDATE",
            content_hash=make_hash("candidate-stdout"),
            size_bytes=100,
        )
        oracle_artifact_evidence = ArtifactEvidence(
            artifact=oracle_artifact,
            execution_id=ExecutionId(value="exec-oracle-001"),
            capture_time="2026-09-14T00:00:01Z",
            content_hash=make_hash("oracle-stdout"),
            size_bytes=100,
        )
        candidate_artifact_evidence = ArtifactEvidence(
            artifact=candidate_artifact,
            execution_id=ExecutionId(value="exec-cand-001"),
            capture_time="2026-09-14T00:00:03Z",
            content_hash=make_hash("candidate-stdout"),
            size_bytes=100,
        )
        
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, successful_candidate_execution),
            artifact_evidence=(oracle_artifact_evidence, candidate_artifact_evidence),
            comparison_evidence=(mismatching_comparison,),
        )
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.FAILED
        assert len(verdict.differences) > 0

    def test_unproven_when_zero_checks(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
        successful_candidate_execution: ExecutionEvidence,
    ):
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, successful_candidate_execution),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNPROVEN

    def test_unavailable_when_oracle_fails(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_candidate_execution: ExecutionEvidence,
    ):
        failed_oracle_execution = ExecutionEvidence(
            execution_id=ExecutionId(value="exec-oracle-fail"),
            run_id=sample_run_id,
            runtime_id="oracle-gnucobol-3.1.2",
            command="cobc -x test.cbl",
            working_directory="/workspace",
            environment_variables={},
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            exit_code=1,
            stdout_hash=make_hash(""),
            stderr_hash=make_hash("error"),
            generated_files={},
            source_tree_hash_before=make_hash("source-before"),
            source_tree_hash_after=make_hash("source-after"),
            termination_status="nonzero_exit",
            timeout_applied=False,
        )
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(failed_oracle_execution, successful_candidate_execution),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_error_when_timeout(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
    ):
        timeout_execution = ExecutionEvidence(
            execution_id=ExecutionId(value="exec-cand-timeout"),
            run_id=sample_run_id,
            runtime_id="candidate-java",
            command="javac Main.java && java Main",
            working_directory="/workspace",
            environment_variables={},
            start_time="2026-09-14T00:00:02Z",
            end_time="2026-09-14T00:00:32Z",
            exit_code=None,
            stdout_hash=make_hash(""),
            stderr_hash=make_hash("timeout"),
            generated_files={},
            source_tree_hash_before=make_hash("source-before"),
            source_tree_hash_after=make_hash("source-after"),
            termination_status="timeout",
            timeout_applied=True,
            timeout_duration=30,
        )
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, timeout_execution),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR

    def test_verdict_is_deterministic(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
        successful_candidate_execution: ExecutionEvidence,
        matching_comparison: ComparisonEvidence,
    ):
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, successful_candidate_execution),
            artifact_evidence=(),
            comparison_evidence=(matching_comparison,),
        )
        verdict1 = derive_verdict(manifest)
        verdict2 = derive_verdict(manifest)
        # Verdict state and key fields should be deterministic
        assert verdict1.state == verdict2.state
        assert verdict1.executed_check_count == verdict2.executed_check_count
        assert verdict1.workload_id == verdict2.workload_id

    def test_verdict_has_complete_scope(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
        successful_candidate_execution: ExecutionEvidence,
        matching_comparison: ComparisonEvidence,
    ):
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, successful_candidate_execution),
            artifact_evidence=(),
            comparison_evidence=(matching_comparison,),
        )
        verdict = derive_verdict(manifest)
        assert verdict.workload_id == sample_workload_id
        assert verdict.run_id == sample_run_id.value
        assert verdict.oracle_id == sample_oracle_identity.oracle_id
        assert verdict.oracle_digest == sample_oracle_identity.image_digest
        assert verdict.supported_scope_statement != ""

    def test_verdict_to_dict(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        successful_oracle_execution: ExecutionEvidence,
        successful_candidate_execution: ExecutionEvidence,
        matching_comparison: ComparisonEvidence,
    ):
        from engine.domain.identities import ArtifactIdentity
        
        # Create minimal artifact evidence
        oracle_artifact = ArtifactIdentity(
            artifact_id="art-oracle-001",
            artifact_type="STDOUT",
            logical_name="STDOUT",
            producer_role="ORACLE",
            content_hash=make_hash("oracle-stdout"),
            size_bytes=100,
        )
        candidate_artifact = ArtifactIdentity(
            artifact_id="art-cand-001",
            artifact_type="STDOUT",
            logical_name="STDOUT",
            producer_role="CANDIDATE",
            content_hash=make_hash("candidate-stdout"),
            size_bytes=100,
        )
        oracle_artifact_evidence = ArtifactEvidence(
            artifact=oracle_artifact,
            execution_id=ExecutionId(value="exec-oracle-001"),
            capture_time="2026-09-14T00:00:01Z",
            content_hash=make_hash("oracle-stdout"),
            size_bytes=100,
        )
        candidate_artifact_evidence = ArtifactEvidence(
            artifact=candidate_artifact,
            execution_id=ExecutionId(value="exec-cand-001"),
            capture_time="2026-09-14T00:00:03Z",
            content_hash=make_hash("candidate-stdout"),
            size_bytes=100,
        )
        
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=sample_candidate_identity,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(successful_oracle_execution, successful_candidate_execution),
            artifact_evidence=(oracle_artifact_evidence, candidate_artifact_evidence),
            comparison_evidence=(matching_comparison,),
        )
        verdict = derive_verdict(manifest)
        d = verdict.to_dict()
        assert d["state"] == "VERIFIED"
        assert d["workload_id"] == "wl-001"
        assert d["oracle_id"] == "gnucobol-3.1.2"
        assert "executed_check_count" in d
        assert "supported_scope_statement" in d
