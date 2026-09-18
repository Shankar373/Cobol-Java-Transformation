"""Tests for evidence model and content addressing."""

import pytest

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
    ContentAddressedStorage,
    EvidenceManifest,
    EvidenceType,
    ExecutionEvidence,
)
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
def sample_execution_evidence(sample_run_id: RunId) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(value="exec-001"),
        run_id=sample_run_id,
        runtime_id="oracle-gnucobol-3.1.2",
        command="cobc -x test.cbl && ./test",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-14T00:00:00Z",
        end_time="2026-09-14T00:00:01Z",
        exit_code=0,
        stdout_hash=make_hash("stdout"),
        stderr_hash=make_hash("stderr"),
        generated_files={},
        source_tree_hash_before=make_hash("source-before"),
        source_tree_hash_after=make_hash("source-after"),
        termination_status="normal",
        timeout_applied=False,
    )


# ---------------------------------------------------------------------------
# ContentHash tests
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_from_bytes(self):
        h = ContentHash.from_bytes(b"test data")
        assert h.verify(b"test data")
        assert not h.verify(b"different data")

    def test_from_string(self):
        h = ContentHash.from_string("test data")
        assert h.verify(b"test data")

    def test_deterministic(self):
        h1 = ContentHash.from_string("same")
        h2 = ContentHash.from_string("same")
        assert h1 == h2


# ---------------------------------------------------------------------------
# ContentAddressedStorage tests
# ---------------------------------------------------------------------------

class TestContentAddressedStorage:
    def test_store_and_retrieve(self):
        storage = ContentAddressedStorage()
        content = b"test content"
        content_hash = storage.store(content)
        
        retrieved = storage.retrieve(content_hash)
        assert retrieved == content

    def test_verify_integrity(self):
        storage = ContentAddressedStorage()
        content = b"test content"
        content_hash = storage.store(content)
        
        assert storage.verify(content_hash)

    def test_nonexistent_hash(self):
        storage = ContentAddressedStorage()
        fake_hash = ContentHash.from_string("nonexistent")
        
        assert storage.retrieve(fake_hash) is None
        assert not storage.exists(fake_hash)
        assert not storage.verify(fake_hash)

    def test_content_deduplication(self):
        storage = ContentAddressedStorage()
        content = b"shared content"
        hash1 = storage.store(content)
        hash2 = storage.store(content)
        
        assert hash1 == hash2
        assert len(storage._store) == 1


# ---------------------------------------------------------------------------
# ExecutionEvidence tests
# ---------------------------------------------------------------------------

class TestExecutionEvidence:
    def test_creation(self, sample_execution_evidence: ExecutionEvidence):
        assert sample_execution_evidence.execution_id.value == "exec-001"
        assert sample_execution_evidence.termination_status == "normal"

    def test_to_dict(self, sample_execution_evidence: ExecutionEvidence):
        d = sample_execution_evidence.to_dict()
        assert d["execution_id"] == "exec-001"
        assert d["termination_status"] == "normal"
        assert "stdout_hash" in d
        assert "stderr_hash" in d


# ---------------------------------------------------------------------------
# ArtifactEvidence tests
# ---------------------------------------------------------------------------

class TestArtifactEvidence:
    def test_creation(self, sample_run_id: RunId):
        artifact = ArtifactIdentity(
            artifact_id="art-001",
            artifact_type="STDOUT",
            logical_name="OUTPUT",
            producer_role="ORACLE",
            content_hash=make_hash("output"),
            size_bytes=100,
        )
        evidence = ArtifactEvidence(
            artifact=artifact,
            execution_id=ExecutionId(value="exec-001"),
            capture_time="2026-09-14T00:00:01Z",
            content_hash=make_hash("output"),
            size_bytes=100,
        )
        assert evidence.artifact.artifact_id == "art-001"
        assert evidence.size_bytes == 100


# ---------------------------------------------------------------------------
# ComparisonEvidence tests
# ---------------------------------------------------------------------------

class TestComparisonEvidence:
    def test_creation(self, sample_run_id: RunId):
        evidence = ComparisonEvidence(
            comparison_id="comp-001",
            run_id=sample_run_id,
            comparator_id="STDOUT_COMPARATOR",
            comparator_version="1.0.0",
            oracle_artifact_id="art-oracle-001",
            candidate_artifact_id="art-cand-001",
            artifact_type="STDOUT",
            result="MATCH",
            normalization_applied=("crlf_to_lf",),
            differences=(),
            field_level_results=(),
            content_hash=make_hash("comparison"),
        )
        assert evidence.result == "MATCH"
        assert "crlf_to_lf" in evidence.normalization_applied


# ---------------------------------------------------------------------------
# EvidenceManifest tests
# ---------------------------------------------------------------------------

class TestEvidenceManifest:
    def test_creation(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_candidate_identity: CandidateIdentity,
        sample_input_identity: InputIdentity,
        sample_execution_evidence: ExecutionEvidence,
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
            execution_evidence=(sample_execution_evidence,),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        assert manifest.manifest_version == "1.0"
        assert manifest.run_id == sample_run_id

    def test_manifest_hash_deterministic(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_input_identity: InputIdentity,
        sample_execution_evidence: ExecutionEvidence,
    ):
        manifest1 = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=None,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(sample_execution_evidence,),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        manifest2 = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=None,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(sample_execution_evidence,),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        assert manifest1.manifest_hash == manifest2.manifest_hash

    def test_is_complete_incomplete(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_input_identity: InputIdentity,
    ):
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=None,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        assert not manifest.is_complete()

    def test_to_dict(
        self,
        sample_run_id: RunId,
        sample_workload_id: WorkloadId,
        sample_source_identity: SourceIdentity,
        sample_oracle_identity: OracleIdentity,
        sample_input_identity: InputIdentity,
    ):
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=sample_run_id,
            workload_id=sample_workload_id,
            source_identity=sample_source_identity,
            candidate_identity=None,
            oracle_identity=sample_oracle_identity,
            environment_identities=(),
            controlled_input=sample_input_identity,
            execution_evidence=(),
            artifact_evidence=(),
            comparison_evidence=(),
        )
        d = manifest.to_dict()
        assert d["manifest_version"] == "1.0"
        assert d["run_id"] == "run-001"
        assert "manifest_hash" in d


# ---------------------------------------------------------------------------
# EvidenceType tests
# ---------------------------------------------------------------------------

class TestEvidenceType:
    def test_all_types(self):
        types = list(EvidenceType)
        assert len(types) == 7
        assert EvidenceType.ORACLE_EXECUTION in types
        assert EvidenceType.CANDIDATE_EXECUTION in types
        assert EvidenceType.ARTIFACT_CAPTURE in types
        assert EvidenceType.ARTIFACT_CONTRACT_VALIDATION in types
        assert EvidenceType.COMPARISON_RESULT in types
        assert EvidenceType.MUTATION_RESULT in types
        assert EvidenceType.VERDICT_DERIVATION in types
