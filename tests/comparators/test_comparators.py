"""Tests for typed comparator framework."""

import pytest

from engine.comparators.framework import (
    ComparatorRegistry,
    ComparisonResult,
    ExitStatusComparator,
    FixedRecordComparator,
    StderrComparator,
    StdoutComparator,
    TextFileComparator,
    create_default_registry,
)
from engine.domain.identities import ArtifactIdentity, RunId
from tests.common import make_hash

# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------

def make_artifact(
    artifact_id: str = "art-001",
    artifact_type: str = "STDOUT",
    logical_name: str = "STDOUT",
    producer_role: str = "ORACLE",
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        logical_name=logical_name,
        producer_role=producer_role,
        content_hash=make_hash("content"),
        size_bytes=100,
    )


# ---------------------------------------------------------------------------
# ComparatorRegistry tests
# ---------------------------------------------------------------------------

class TestComparatorRegistry:
    def test_empty_registry(self):
        registry = ComparatorRegistry()
        assert not registry.is_registered("STDOUT")
        assert registry.get("STDOUT") is None

    def test_register_comparator(self):
        registry = ComparatorRegistry()
        comparator = StdoutComparator()
        registry.register(comparator)
        assert registry.is_registered("STDOUT")
        assert registry.get("STDOUT") is comparator

    def test_duplicate_registration_raises(self):
        registry = ComparatorRegistry()
        registry.register(StdoutComparator())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(StdoutComparator())

    def test_get_all(self):
        registry = create_default_registry()
        all_comparators = registry.get_all()
        assert len(all_comparators) == 5
        assert "STDOUT" in all_comparators
        assert "STDERR" in all_comparators
        assert "EXIT_STATUS" in all_comparators
        assert "TEXT_FILE" in all_comparators
        assert "FIXED_RECORD" in all_comparators


# ---------------------------------------------------------------------------
# StdoutComparator tests
# ---------------------------------------------------------------------------

class TestStdoutComparator:
    def test_match(self):
        comparator = StdoutComparator()
        oracle = make_artifact(artifact_type="STDOUT")
        candidate = make_artifact(artifact_id="art-002", artifact_type="STDOUT", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"hello", candidate, b"hello")
        assert result.result == ComparisonResult.MATCH

    def test_mismatch(self):
        comparator = StdoutComparator()
        oracle = make_artifact(artifact_type="STDOUT")
        candidate = make_artifact(artifact_id="art-002", artifact_type="STDOUT", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"hello", candidate, b"world")
        assert result.result == ComparisonResult.MISMATCH
        assert len(result.differences) > 0

    def test_crlf_normalization(self):
        comparator = StdoutComparator()
        oracle = make_artifact(artifact_type="STDOUT")
        candidate = make_artifact(artifact_id="art-002", artifact_type="STDOUT", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"hello\r\n", candidate, b"hello\n")
        assert result.result == ComparisonResult.MATCH
        assert "crlf_to_lf" in result.normalization_applied


# ---------------------------------------------------------------------------
# StderrComparator tests
# ---------------------------------------------------------------------------

class TestStderrComparator:
    def test_match(self):
        comparator = StderrComparator()
        oracle = make_artifact(artifact_type="STDERR")
        candidate = make_artifact(artifact_id="art-002", artifact_type="STDERR", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"error", candidate, b"error")
        assert result.result == ComparisonResult.MATCH

    def test_mismatch(self):
        comparator = StderrComparator()
        oracle = make_artifact(artifact_type="STDERR")
        candidate = make_artifact(artifact_id="art-002", artifact_type="STDERR", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"error1", candidate, b"error2")
        assert result.result == ComparisonResult.MISMATCH


# ---------------------------------------------------------------------------
# ExitStatusComparator tests
# ---------------------------------------------------------------------------

class TestExitStatusComparator:
    def test_match(self):
        comparator = ExitStatusComparator()
        oracle = make_artifact(artifact_type="EXIT_STATUS")
        candidate = make_artifact(artifact_id="art-002", artifact_type="EXIT_STATUS", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"0", candidate, b"0")
        assert result.result == ComparisonResult.MATCH

    def test_mismatch(self):
        comparator = ExitStatusComparator()
        oracle = make_artifact(artifact_type="EXIT_STATUS")
        candidate = make_artifact(artifact_id="art-002", artifact_type="EXIT_STATUS", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"0", candidate, b"1")
        assert result.result == ComparisonResult.MISMATCH

    def test_inconclusive_on_invalid(self):
        comparator = ExitStatusComparator()
        oracle = make_artifact(artifact_type="EXIT_STATUS")
        candidate = make_artifact(artifact_id="art-002", artifact_type="EXIT_STATUS", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"invalid", candidate, b"0")
        assert result.result == ComparisonResult.INCONCLUSIVE


# ---------------------------------------------------------------------------
# TextFileComparator tests
# ---------------------------------------------------------------------------

class TestTextFileComparator:
    def test_match(self):
        comparator = TextFileComparator()
        oracle = make_artifact(artifact_type="TEXT_FILE")
        candidate = make_artifact(artifact_id="art-002", artifact_type="TEXT_FILE", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"file content", candidate, b"file content")
        assert result.result == ComparisonResult.MATCH

    def test_mismatch(self):
        comparator = TextFileComparator()
        oracle = make_artifact(artifact_type="TEXT_FILE")
        candidate = make_artifact(artifact_id="art-002", artifact_type="TEXT_FILE", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"file1", candidate, b"file2")
        assert result.result == ComparisonResult.MISMATCH


# ---------------------------------------------------------------------------
# FixedRecordComparator tests
# ---------------------------------------------------------------------------

class TestFixedRecordComparator:
    def test_match(self):
        comparator = FixedRecordComparator()
        oracle = make_artifact(artifact_type="FIXED_RECORD")
        candidate = make_artifact(artifact_id="art-002", artifact_type="FIXED_RECORD", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"record1record2", candidate, b"record1record2")
        assert result.result == ComparisonResult.MATCH

    def test_mismatch(self):
        comparator = FixedRecordComparator()
        oracle = make_artifact(artifact_type="FIXED_RECORD")
        candidate = make_artifact(artifact_id="art-002", artifact_type="FIXED_RECORD", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"record1", candidate, b"record2")
        assert result.result == ComparisonResult.MISMATCH


# ---------------------------------------------------------------------------
# ComparatorResult tests
# ---------------------------------------------------------------------------

class TestComparatorResult:
    def test_to_comparison_evidence(self):
        comparator = StdoutComparator()
        oracle = make_artifact(artifact_type="STDOUT")
        candidate = make_artifact(artifact_id="art-002", artifact_type="STDOUT", producer_role="CANDIDATE")
        result = comparator.compare(oracle, b"hello", candidate, b"hello")
        evidence = result.to_comparison_evidence(RunId(value="run-001"))
        assert evidence.result == "MATCH"
        assert evidence.artifact_type == "STDOUT"


# ---------------------------------------------------------------------------
# create_default_registry tests
# ---------------------------------------------------------------------------

class TestCreateDefaultRegistry:
    def test_all_v1_types_registered(self):
        registry = create_default_registry()
        v1_types = ["STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"]
        for artifact_type in v1_types:
            assert registry.is_registered(artifact_type)

    def test_no_generic_comparator(self):
        registry = create_default_registry()
        # Should not have a "generic" or "any" comparator
        assert registry.get("generic") is None
        assert registry.get("any") is None
