"""Tests for core domain identity types."""

import pytest

from engine.domain.identities import (
    AdapterStatus,
    ArtifactIdentity,
    CandidateIdentity,
    ComparatorId,
    ComparisonId,
    ContentHash,
    ContractId,
    EnvironmentIdentity,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from tests.common import make_hash


class TestContentHash:
    def test_from_bytes(self):
        h = ContentHash.from_bytes(b"hello")
        assert h.algorithm == "sha256"
        assert len(h.digest) == 64
        assert h.verify(b"hello")
        assert not h.verify(b"world")

    def test_from_string(self):
        h = ContentHash.from_string("test data")
        assert h.verify(b"test data")

    def test_invalid_length(self):
        with pytest.raises(ValueError, match="64 hex chars"):
            ContentHash(digest="too-short")

    def test_invalid_algorithm(self):
        with pytest.raises(ValueError, match="sha256"):
            ContentHash(algorithm="md5", digest="a" * 64)

    def test_str_representation(self):
        h = make_hash("test")
        assert str(h).startswith("sha256:")

    def test_equality(self):
        h1 = ContentHash.from_string("same")
        h2 = ContentHash.from_string("same")
        assert h1 == h2

    def test_inequality(self):
        h1 = ContentHash.from_string("one")
        h2 = ContentHash.from_string("two")
        assert h1 != h2


class TestWorkloadId:
    def test_valid(self):
        w = WorkloadId(value="wl-001")
        assert w.value == "wl-001"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            WorkloadId(value="")


class TestRunId:
    def test_valid(self):
        r = RunId(value="run-001")
        assert r.value == "run-001"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            RunId(value="")


class TestSourceIdentity:
    def test_valid(self):
        s = SourceIdentity(
            source_id="src-001",
            source_hash=make_hash("source"),
            file_count=10,
            total_size_bytes=1000,
        )
        assert s.source_id == "src-001"

    def test_empty_source_id_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            SourceIdentity(
                source_id="",
                source_hash=make_hash(),
                file_count=0,
                total_size_bytes=0,
            )


class TestCandidateIdentity:
    def test_valid(self):
        c = CandidateIdentity(
            candidate_id="cand-001",
            candidate_hash=make_hash("candidate"),
            source_hash=make_hash("source"),
            file_count=5,
            total_size_bytes=500,
        )
        assert c.candidate_id == "cand-001"

    def test_empty_candidate_id_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            CandidateIdentity(
                candidate_id="",
                candidate_hash=make_hash(),
                source_hash=make_hash(),
                file_count=0,
                total_size_bytes=0,
            )


class TestOracleIdentity:
    def test_valid(self):
        o = OracleIdentity(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        )
        assert o.oracle_id == "gnucobol-3.1.2"
        assert o.preprocessor_version is None

    def test_empty_oracle_id_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            OracleIdentity(
                oracle_id="",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            )

    def test_non_sha256_digest_raises(self):
        with pytest.raises(ValueError, match="sha256-pinned"):
            OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="latest",
                compiler_version="3.1.2.0",
            )

    def test_empty_compiler_version_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="",
            )


class TestEnvironmentIdentity:
    def test_valid(self):
        e = EnvironmentIdentity(runtime_id="env-001")
        assert e.runtime_id == "env-001"
        assert e.network_policy == "none"

    def test_with_limits(self):
        e = EnvironmentIdentity(
            runtime_id="env-001",
            resource_limits={"memory": "512m", "cpu": "1.0"},
        )
        assert e.resource_limits["memory"] == "512m"


class TestInputIdentity:
    def test_valid(self):
        i = InputIdentity(input_id="inp-001")
        assert i.input_id == "inp-001"

    def test_combined_hash_empty(self):
        i = InputIdentity(input_id="inp-001")
        h = i.combined_hash
        assert h.algorithm == "sha256"

    def test_combined_hash_with_stdin(self):
        i = InputIdentity(
            input_id="inp-001",
            stdin_hash=make_hash("stdin"),
        )
        h = i.combined_hash
        assert h.verify(b"stdin") is False  # combined hash differs

    def test_combined_hash_deterministic(self):
        i1 = InputIdentity(
            input_id="inp-001",
            stdin_hash=make_hash("data"),
        )
        i2 = InputIdentity(
            input_id="inp-001",
            stdin_hash=make_hash("data"),
        )
        assert i1.combined_hash == i2.combined_hash


class TestArtifactIdentity:
    def test_valid_types(self):
        for artifact_type in ["STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"]:
            a = ArtifactIdentity(
                artifact_id="art-001",
                artifact_type=artifact_type,
                logical_name="OUTPUT",
                producer_role="ORACLE",
                content_hash=make_hash(),
                size_bytes=100,
            )
            assert a.artifact_type == artifact_type

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="artifact_type"):
            ArtifactIdentity(
                artifact_id="art-001",
                artifact_type="INDEXED",
                logical_name="OUTPUT",
                producer_role="ORACLE",
                content_hash=make_hash(),
                size_bytes=100,
            )

    def test_valid_producer_roles(self):
        for role in ["ORACLE", "CANDIDATE"]:
            a = ArtifactIdentity(
                artifact_id="art-001",
                artifact_type="STDOUT",
                logical_name="OUTPUT",
                producer_role=role,
                content_hash=make_hash(),
                size_bytes=100,
            )
            assert a.producer_role == role

    def test_invalid_producer_role_raises(self):
        with pytest.raises(ValueError, match="producer_role"):
            ArtifactIdentity(
                artifact_id="art-001",
                artifact_type="STDOUT",
                logical_name="OUTPUT",
                producer_role="UNKNOWN",
                content_hash=make_hash(),
                size_bytes=100,
            )


class TestExecutionId:
    def test_valid(self):
        e = ExecutionId(value="exec-001")
        assert e.value == "exec-001"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            ExecutionId(value="")


class TestComparisonId:
    def test_valid(self):
        c = ComparisonId(value="comp-001")
        assert c.value == "comp-001"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            ComparisonId(value="")


class TestContractId:
    def test_valid_types(self):
        for ct in ["ORACLE", "ARTIFACT", "VERDICT", "JAVA_CANDIDATE", "PRODUCER"]:
            c = ContractId(contract_type=ct, version="1.0")
            assert c.contract_type == ct

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="contract_type"):
            ContractId(contract_type="INVALID", version="1.0")


class TestComparatorId:
    def test_valid(self):
        c = ComparatorId(comparator_id="STDOUT_COMPARATOR", version="1.0.0")
        assert c.comparator_id == "STDOUT_COMPARATOR"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            ComparatorId(comparator_id="", version="1.0.0")


class TestAdapterStatus:
    def test_all_values(self):
        statuses = list(AdapterStatus)
        assert len(statuses) == 4
        assert AdapterStatus.AVAILABLE in statuses
        assert AdapterStatus.UNAVAILABLE in statuses
        assert AdapterStatus.FAILED in statuses
        assert AdapterStatus.SUCCEEDED in statuses


class TestVerdictState:
    def test_all_seven_states(self):
        states = list(VerdictState)
        assert len(states) == 7
        expected = {"VERIFIED", "PARTIAL", "FAILED", "UNPROVEN", "UNAVAILABLE", "UNSUPPORTED", "ERROR"}
        actual = {s.value for s in states}
        assert actual == expected
