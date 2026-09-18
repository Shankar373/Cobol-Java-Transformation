"""Tests for Java candidate adapter interface."""

from engine.candidate.adapter import (
    CandidateExecutionResult,
    CandidateManifest,
    PlainJavaCandidateAdapter,
)
from engine.domain.identities import AdapterStatus, ExecutionId, RunId

# ---------------------------------------------------------------------------
# CandidateManifest tests
# ---------------------------------------------------------------------------

class TestCandidateManifest:
    def test_valid_manifest(self):
        manifest = CandidateManifest(
            candidate_id="cand-001",
            workload_id="wl-001",
            source_hash="abc123",
            generated_files={"Main.java": "hash1"},
            entrypoint="com.example.Main",
        )
        assert manifest.validate() == []

    def test_missing_fields(self):
        manifest = CandidateManifest(
            candidate_id="",
            workload_id="",
            source_hash="",
            generated_files={},
            entrypoint="",
        )
        missing = manifest.validate()
        assert len(missing) == 5
        assert "candidate_id" in missing
        assert "workload_id" in missing
        assert "source_hash" in missing
        assert "generated_files" in missing
        assert "entrypoint" in missing


# ---------------------------------------------------------------------------
# PlainJavaCandidateAdapter tests
# ---------------------------------------------------------------------------

class TestPlainJavaCandidateAdapter:
    def test_valid_creation(self):
        adapter = PlainJavaCandidateAdapter()
        assert adapter.status == AdapterStatus.UNAVAILABLE

    def test_validate_candidate_valid(self):
        adapter = PlainJavaCandidateAdapter()
        manifest = CandidateManifest(
            candidate_id="cand-001",
            workload_id="wl-001",
            source_hash="abc123",
            generated_files={"Main.java": "hash1"},
            entrypoint="com.example.Main",
        )
        violations = adapter.validate_candidate("/workspace/candidate", manifest)
        assert len(violations) == 0

    def test_validate_candidate_missing_manifest(self):
        adapter = PlainJavaCandidateAdapter()
        manifest = CandidateManifest(
            candidate_id="",
            workload_id="",
            source_hash="",
            generated_files={},
            entrypoint="",
        )
        violations = adapter.validate_candidate("/workspace/candidate", manifest)
        assert len(violations) > 0

    def test_validate_candidate_external_deps(self):
        adapter = PlainJavaCandidateAdapter()
        manifest = CandidateManifest(
            candidate_id="cand-001",
            workload_id="wl-001",
            source_hash="abc123",
            generated_files={"Main.java": "hash1"},
            entrypoint="com.example.Main",
            dependencies=("org.example:lib:1.0",),
        )
        violations = adapter.validate_candidate("/workspace/candidate", manifest)
        assert any("external dependencies" in v for v in violations)

    def test_compile(self):
        adapter = PlainJavaCandidateAdapter()
        manifest = CandidateManifest(
            candidate_id="cand-001",
            workload_id="wl-001",
            source_hash="abc123",
            generated_files={"Main.java": "hash1"},
            entrypoint="com.example.Main",
        )
        result = adapter.compile("/workspace/candidate", manifest)
        assert result.success

    def test_execute(self):
        adapter = PlainJavaCandidateAdapter()
        manifest = CandidateManifest(
            candidate_id="cand-001",
            workload_id="wl-001",
            source_hash="abc123",
            generated_files={"Main.java": "hash1"},
            entrypoint="com.example.Main",
        )
        result = adapter.execute(
            run_id=RunId(value="run-001"),
            compiled_path="/workspace/compiled",
            manifest=manifest,
        )
        assert result.status == AdapterStatus.SUCCEEDED
        assert result.exit_code == 0
        assert result.termination_status == "normal"


# ---------------------------------------------------------------------------
# CandidateExecutionResult tests
# ---------------------------------------------------------------------------

class TestCandidateExecutionResult:
    def test_to_execution_evidence(self):
        result = CandidateExecutionResult(
            execution_id=ExecutionId(value="exec-001"),
            run_id=RunId(value="run-001"),
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"hello",
            stderr=b"",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="normal",
            timeout_applied=False,
        )
        evidence = result.to_execution_evidence()
        assert evidence.exit_code == 0
        assert evidence.termination_status == "normal"
        assert evidence.runtime_id == "candidate-java"
