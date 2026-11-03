"""Pipeline integration: business invariants are real evidence, not decoration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engine.candidate.adapter import (
    CandidateExecutionResult,
    CompilationResult,
)
from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    OracleIdentity,
    RunId,
)
from engine.oracle.adapter import OracleExecutionResult
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.verification.business_invariants import (
    BusinessInvariant,
    InvariantKind,
    InvariantSource,
)
from engine.workload import WorkloadArtifact, WorkloadDefinition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeOracle:
    def __init__(self, stdout: bytes, generated_files=None) -> None:
        self._stdout = stdout
        self._generated = generated_files or {}

    def get_identity(self) -> OracleIdentity:
        return OracleIdentity(
            oracle_id="test-oracle",
            image_digest="sha256:" + "a" * 64,
            compiler_version="test",
        )

    def execute(self, run_id: RunId, source_path, input_data=None, input_files=None):
        return OracleExecutionResult(
            execution_id=ExecutionId(value=f"oracle-{run_id.value}"),
            run_id=run_id,
            oracle_id="test-oracle",
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=self._stdout,
            stderr=b"",
            start_time=_now(),
            end_time=_now(),
            termination_status="normal",
            timeout_applied=False,
            generated_files=self._generated,
        )


class _FakeCandidate:
    def __init__(self, stdout: bytes, generated_files=None) -> None:
        self._stdout = stdout
        self._generated = generated_files or {}

    def compile(self, candidate_path, manifest):
        return CompilationResult(success=True, class_files={"Main.class": b"x"})

    def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
        return CandidateExecutionResult(
            execution_id=ExecutionId(value=f"candidate-{run_id.value}"),
            run_id=run_id,
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=self._stdout,
            stderr=b"",
            start_time=_now(),
            end_time=_now(),
            termination_status="normal",
            timeout_applied=False,
            generated_files=self._generated,
        )


def _workload(invariants) -> WorkloadDefinition:
    return WorkloadDefinition(
        workload_id="wl-invariants",
        description="business invariant integration",
        artifacts=(
            WorkloadArtifact(
                logical_name="exit",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
        invariants=invariants,
    )


def _run(
    tmp_path: Path,
    invariants,
    oracle_stdout: bytes = b"OK\n",
    candidate_stdout: bytes = b"OK\n",
    oracle_files=None,
    candidate_files=None,
):
    source = tmp_path / "PROG.cob"
    source.write_text("IDENTIFICATION DIVISION.", encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    config = PipelineConfig(
        workload_id="wl-invariants",
        cobol_source_path=str(source),
        java_candidate_path=str(candidate),
        java_entrypoint="Main",
        workload=_workload(invariants),
    )
    pipeline = VerticalSlicePipeline(
        config,
        candidate_adapter=_FakeCandidate(candidate_stdout, candidate_files),
    )
    pipeline._oracle_adapter = _FakeOracle(oracle_stdout, oracle_files)
    return pipeline.run()


def _comparison(result, artifact_type: str):
    matches = [
        item for item in result.comparison_evidence
        if item.artifact_type == artifact_type
    ]
    assert len(matches) == 1, [item.artifact_type for item in result.comparison_evidence]
    return matches[0]


class TestBusinessInvariantPipeline:
    def test_passing_rules_on_both_sides_are_verified(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            (
                BusinessInvariant(
                    invariant_id="exact-output",
                    kind=InvariantKind.EXACT_LINES,
                    expected=("OK",),
                ),
            ),
        )
        assert result.verdict.state.value == "VERIFIED"
        assert result.evidence_manifest.is_complete()
        assert _comparison(result, "BUSINESS_INVARIANT").result == "MATCH"
        types = {item.artifact.artifact_type for item in result.artifact_evidence}
        assert "BUSINESS_INVARIANT" in types

    def test_business_only_failure_fails_even_when_technical_artifacts_match(
        self, tmp_path: Path
    ) -> None:
        result = _run(
            tmp_path,
            (
                BusinessInvariant(
                    invariant_id="exact-output",
                    kind=InvariantKind.EXACT_LINES,
                    expected=("OK",),
                ),
            ),
            candidate_stdout=b"WRONG\n",
        )
        # EXIT_STATUS still matches: the failure is invisible to the
        # technical artifact set and is caught only by the business gate.
        assert _comparison(result, "EXIT_STATUS").result == "MATCH"
        assert _comparison(result, "BUSINESS_INVARIANT").result == "MISMATCH"
        assert result.verdict.state.value == "FAILED"

    def test_identical_failure_on_both_sides_is_not_verified(
        self, tmp_path: Path
    ) -> None:
        result = _run(
            tmp_path,
            (
                BusinessInvariant(
                    invariant_id="exact-output",
                    kind=InvariantKind.EXACT_LINES,
                    expected=("OK",),
                ),
            ),
            oracle_stdout=b"WRONG\n",
            candidate_stdout=b"WRONG\n",
        )
        assert _comparison(result, "BUSINESS_INVARIANT").result == "MISMATCH"
        assert result.verdict.state.value == "FAILED"

    def test_file_record_count_uses_real_generated_files(
        self, tmp_path: Path
    ) -> None:
        result = _run(
            tmp_path,
            (
                BusinessInvariant(
                    invariant_id="two-records",
                    kind=InvariantKind.RECORD_COUNT,
                    source=InvariantSource.FILE,
                    source_name="out.dat",
                    expected=2,
                    record_length=4,
                ),
            ),
            oracle_files={"out.dat": b"AAAABBBB"},
            candidate_files={"out.dat": b"AAAABBBB"},
        )
        assert result.verdict.state.value == "VERIFIED"
        assert _comparison(result, "BUSINESS_INVARIANT").result == "MATCH"

    def test_candidate_missing_declared_file_fails(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            (
                BusinessInvariant(
                    invariant_id="two-records",
                    kind=InvariantKind.RECORD_COUNT,
                    source=InvariantSource.FILE,
                    source_name="out.dat",
                    expected=2,
                    record_length=4,
                ),
            ),
            oracle_files={"out.dat": b"AAAABBBB"},
            candidate_files={},
        )
        assert _comparison(result, "BUSINESS_INVARIANT").result == "MISMATCH"
        assert result.verdict.state.value == "FAILED"

    def test_workload_without_invariants_is_unchanged(self, tmp_path: Path) -> None:
        result = _run(tmp_path, ())
        types = {item.artifact.artifact_type for item in result.artifact_evidence}
        assert "BUSINESS_INVARIANT" not in types
        assert _comparison(result, "EXIT_STATUS").result == "MATCH"
        assert result.verdict.state.value == "VERIFIED"
