"""Pipeline progress-hook tests (Docker-free).

Proves VerticalSlicePipeline.run() emits truthful phase notifications
(EXECUTING_ORACLE -> BUILDING -> EXECUTING_GENERATED -> COMPARING ->
VALIDATING_EVIDENCE) as each phase STARTS, without changing execution,
comparison, evidence, or verdict semantics. A failed build never emits
EXECUTING_GENERATED.
"""

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
    RunId,
)
from engine.oracle.adapter import OracleExecutionResult
from engine.pipeline import PipelineConfig, VerticalSlicePipeline


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeOracle:
    def get_identity(self):
        from engine.domain.identities import OracleIdentity
        return OracleIdentity(
            oracle_id="test-oracle",
            image_digest="sha256:test",
            compiler_version="test",
        )

    def execute(self, run_id, source_path, input_data=None, input_files=None):
        return OracleExecutionResult(
            execution_id=ExecutionId(value=f"oracle-{run_id.value}"),
            run_id=run_id,
            oracle_id="test-oracle",
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"oracle-out",
            stderr=b"",
            start_time=_now(),
            end_time=_now(),
            termination_status="normal",
            timeout_applied=False,
        )


class _FakeCandidate:
    def __init__(self, build_ok: bool = True):
        self._build_ok = build_ok

    def compile(self, candidate_path, manifest):
        if not self._build_ok:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=("synthetic build boom",),
            )
        return CompilationResult(success=True, class_files={"A.class": b"cafebabe"})

    def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
        return CandidateExecutionResult(
            execution_id=ExecutionId(value=f"candidate-{run_id.value}"),
            run_id=run_id,
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"candidate-out",
            stderr=b"",
            start_time=_now(),
            end_time=_now(),
            termination_status="normal",
            timeout_applied=False,
        )


def _make_pipeline(tmp_path: Path, build_ok: bool = True) -> VerticalSlicePipeline:
    src = tmp_path / "HELLO.cob"
    src.write_text("HELLO", encoding="utf-8")
    cand = tmp_path / "cand"
    cand.mkdir()
    config = PipelineConfig(
        workload_id="wl-progress",
        cobol_source_path=str(src),
        java_candidate_path=str(cand),
        java_entrypoint="Main",
        workload=None,
        use_docker_java=True,
    )
    pipe = VerticalSlicePipeline(config, candidate_adapter=_FakeCandidate(build_ok))
    pipe._oracle_adapter = _FakeOracle()
    return pipe


class TestProgressPhases:
    def test_full_phase_sequence(self, tmp_path: Path) -> None:
        phases: list[str] = []
        result = _make_pipeline(tmp_path).run(progress=phases.append)

        assert phases == [
            "EXECUTING_ORACLE",
            "BUILDING",
            "EXECUTING_GENERATED",
            "COMPARING",
            "VALIDATING_EVIDENCE",
        ]
        assert result.verdict is not None
        assert result.evidence_manifest is not None

    def test_no_progress_callback_still_runs(self, tmp_path: Path) -> None:
        result = _make_pipeline(tmp_path).run()
        assert result.verdict is not None

    def test_failed_build_never_reports_execution(self, tmp_path: Path) -> None:
        phases: list[str] = []
        result = _make_pipeline(tmp_path, build_ok=False).run(progress=phases.append)

        assert phases == ["EXECUTING_ORACLE", "BUILDING", "COMPARING", "VALIDATING_EVIDENCE"]
        assert "EXECUTING_GENERATED" not in phases
        assert result.verdict is not None
