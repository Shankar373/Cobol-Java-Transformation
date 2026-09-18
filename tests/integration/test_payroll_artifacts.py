"""Integration tests for Phase 5A: multi-artifact semantic validation.

Tests the payroll workload which exercises all 5 V1 artifact types:
- STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD

Required scenarios:
1. All 5 artifact types captured and compared
2. Positive path: correct candidate -> VERIFIED
3. Each mutation -> FAILED (false-PASS defense)
4. Determinism proof (two runs produce identical evidence)
5. Manifest completeness
6. Artifact capture for new types
"""

from __future__ import annotations

from pathlib import Path

from engine.domain.identities import (
    ExecutionId,
    RunId,
)
from engine.execution.artifacts import ArtifactCapturer
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.pipeline import PipelineConfig, VerticalSlicePipeline

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workload-payroll"
COBOL_SOURCE = str(FIXTURES / "cobol" / "PAYROLL.cob")
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_MUTATED_DIR = str(FIXTURES / "java-candidate-mutated")

MUTATIONS = {
    "wrong-bonus": ("PayrollWrongBonus", "bonus multiplied by 3 instead of 2"),
    "wrong-format": ("PayrollWrongFormat", "stdout format lacks leading zeros"),
    "no-report-file": ("PayrollNoReportFile", "report.txt not generated"),
    "extra-employee": ("PayrollExtraEmployee", "6 employees instead of 5"),
    "wrong-name": ("PayrollWrongName", "ALICE renamed to ALICE2"),
    "wrong-total": ("PayrollWrongTotal", "per-employee total off by 1"),
    "wrong-delimiter": ("PayrollWrongDelimiter", "records.dat uses comma instead of pipe"),
    "reversed-order": ("PayrollReversedOrder", "employees listed in reverse order"),
    "missing-stderr": ("PayrollMissingStderr", "STDERR warnings omitted entirely"),
}


def _make_config(
    workload_id: str,
    candidate_path: str,
    entrypoint: str,
) -> PipelineConfig:
    return PipelineConfig(
        workload_id=workload_id,
        cobol_source_path=COBOL_SOURCE,
        java_candidate_path=candidate_path,
        java_entrypoint=entrypoint,
        use_docker_java=True,
    )


# ---------------------------------------------------------------------------
# 1. Oracle E2E
# ---------------------------------------------------------------------------

class TestPayrollOracleE2E:
    """Oracle execution produces correct output for payroll workload."""

    def test_oracle_execution(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=60,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-payroll-oracle")

        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)

        assert result.exit_code == 0
        assert result.termination_status == "normal"
        assert b"TOTAL_PAYROLL=" in result.stdout
        assert b"EMPLOYEE_COUNT=5" in result.stdout
        assert b"AVERAGE_PAY=" in result.stdout

    def test_oracle_generates_output_files(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=60,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-payroll-oracle-files")

        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)

        assert result.generated_files is not None
        assert "report.txt" in result.generated_files
        assert "records.dat" in result.generated_files
        assert b"ALICE" in result.generated_files["report.txt"]
        assert b"ALICE|10000" in result.generated_files["records.dat"]


# ---------------------------------------------------------------------------
# 2. Positive path: all 5 artifact types, VERIFIED
# ---------------------------------------------------------------------------

class TestPayrollVerified:
    """Correct candidate produces VERIFIED across all 5 artifact types."""

    def test_verified_candidate(self):
        config = _make_config(
            "payroll-verified", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.verdict.state.value == "VERIFIED"
        assert result.oracle_exit_code == 0
        assert result.candidate_exit_code == 0

    def test_all_five_artifact_types_captured(self):
        config = _make_config(
            "payroll-5artifacts", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        types = {e.artifact.artifact_type for e in result.artifact_evidence}
        assert "STDOUT" in types
        assert "STDERR" in types
        assert "EXIT_STATUS" in types
        assert "TEXT_FILE" in types
        assert "FIXED_RECORD" in types

    def test_five_comparisons(self):
        config = _make_config(
            "payroll-5comp", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert len(result.comparison_evidence) >= 5

    def test_all_comparisons_match(self):
        config = _make_config(
            "payroll-allmatch", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        for comp in result.comparison_evidence:
            assert comp.result == "MATCH", (
                f"{comp.comparator_id} failed: {comp.differences}"
            )

    def test_manifest_completeness(self):
        config = _make_config(
            "payroll-complete", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.evidence_manifest.is_complete()

    def test_text_file_content_matches(self):
        config = _make_config(
            "payroll-text", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_comps = [
            c for c in result.comparison_evidence
            if c.artifact_type == "TEXT_FILE"
        ]
        assert len(text_comps) == 1
        assert text_comps[0].result == "MATCH"

    def test_fixed_record_content_matches(self):
        config = _make_config(
            "payroll-fixed", JAVA_CANDIDATE, "Payroll",
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        fixed_comps = [
            c for c in result.comparison_evidence
            if c.artifact_type == "FIXED_RECORD"
        ]
        assert len(fixed_comps) == 1
        assert fixed_comps[0].result == "MATCH"


# ---------------------------------------------------------------------------
# 3. Mutation tests: each mutation -> FAILED
# ---------------------------------------------------------------------------

class TestPayrollMutations:
    """Each mutation must be detected and produce FAILED verdict."""

    def test_wrong_bonus_detected(self):
        entrypoint, _ = MUTATIONS["wrong-bonus"]
        config = _make_config(
            "payroll-mut-bonus",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_wrong_format_detected(self):
        entrypoint, _ = MUTATIONS["wrong-format"]
        config = _make_config(
            "payroll-mut-format",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_no_report_file_detected(self):
        entrypoint, _ = MUTATIONS["no-report-file"]
        config = _make_config(
            "payroll-mut-noreport",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_extra_employee_detected(self):
        entrypoint, _ = MUTATIONS["extra-employee"]
        config = _make_config(
            "payroll-mut-extra",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_wrong_name_detected(self):
        entrypoint, _ = MUTATIONS["wrong-name"]
        config = _make_config(
            "payroll-mut-name",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_wrong_total_detected(self):
        entrypoint, _ = MUTATIONS["wrong-total"]
        config = _make_config(
            "payroll-mut-total",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_wrong_delimiter_detected(self):
        entrypoint, _ = MUTATIONS["wrong-delimiter"]
        config = _make_config(
            "payroll-mut-delimiter",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_reversed_order_detected(self):
        entrypoint, _ = MUTATIONS["reversed-order"]
        config = _make_config(
            "payroll-mut-reverse",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_mutations_fail_on_stdout(self):
        entrypoint, _ = MUTATIONS["wrong-format"]
        config = _make_config(
            "payroll-mut-stdout",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence
            if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_mutations_fail_on_text_file(self):
        entrypoint, _ = MUTATIONS["no-report-file"]
        config = _make_config(
            "payroll-mut-textfile",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_comp = next(
            c for c in result.comparison_evidence
            if c.artifact_type == "TEXT_FILE"
        )
        assert text_comp.result == "MISMATCH"

    def test_mutations_fail_on_fixed_record(self):
        entrypoint, _ = MUTATIONS["wrong-delimiter"]
        config = _make_config(
            "payroll-mut-fixedrec",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        fixed_comp = next(
            c for c in result.comparison_evidence
            if c.artifact_type == "FIXED_RECORD"
        )
        assert fixed_comp.result == "MISMATCH"

    def test_missing_stderr_detected(self):
        entrypoint, _ = MUTATIONS["missing-stderr"]
        config = _make_config(
            "payroll-mut-nostderr",
            str(FIXTURES / "java-candidate-mutated"),
            entrypoint,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

        stderr_comp = next(
            c for c in result.comparison_evidence
            if c.artifact_type == "STDERR"
        )
        assert stderr_comp.result == "MISMATCH"


# ---------------------------------------------------------------------------
# 4. Determinism proof
# ---------------------------------------------------------------------------

class TestPayrollDeterminism:
    """Two runs with identical input produce identical evidence."""

    def test_deterministic_verdict(self):
        config = _make_config(
            "payroll-det", JAVA_CANDIDATE, "Payroll",
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        assert result1.source_identity.source_hash == result2.source_identity.source_hash
        assert result1.candidate_identity.candidate_hash == result2.candidate_identity.candidate_hash
        assert result1.verdict.state == result2.verdict.state

    def test_deterministic_comparisons(self):
        config = _make_config(
            "payroll-det-comp", JAVA_CANDIDATE, "Payroll",
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        assert len(result1.comparison_evidence) == len(result2.comparison_evidence)
        for c1, c2 in zip(result1.comparison_evidence, result2.comparison_evidence):
            assert c1.comparator_id == c2.comparator_id
            assert c1.result == c2.result

    def test_deterministic_artifact_hashes(self):
        config = _make_config(
            "payroll-det-hash", JAVA_CANDIDATE, "Payroll",
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        hashes1 = {e.artifact.artifact_type: str(e.content_hash) for e in result1.artifact_evidence}
        hashes2 = {e.artifact.artifact_type: str(e.content_hash) for e in result2.artifact_evidence}
        assert hashes1 == hashes2


# ---------------------------------------------------------------------------
# 5. Artifact capture for new types
# ---------------------------------------------------------------------------

class TestPayrollArtifactCapture:
    """Capturer correctly handles TEXT_FILE and FIXED_RECORD."""

    def test_capture_text_file_from_bytes(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-capture-text")
        content = b"NAME      BASE  YEARS BONUS  TOTAL\n"

        artifact = capturer.capture_text_file_from_bytes(
            exec_id, content, "report.txt",
        )

        assert artifact.artifact.artifact_type == "TEXT_FILE"
        assert artifact.content == content
        assert artifact.size_bytes == len(content)
        assert artifact.content_hash.verify(content)

    def test_capture_fixed_record(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-capture-fixed")
        content = b"ALICE|10000|03|00600|010600\n"

        artifact = capturer.capture_fixed_record(
            exec_id, content, "records.dat",
        )

        assert artifact.artifact.artifact_type == "FIXED_RECORD"
        assert artifact.content == content
        assert artifact.size_bytes == len(content)
        assert artifact.content_hash.verify(content)

    def test_evidence_conversion_text_file(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-ev-text")
        content = b"test content"

        artifact = capturer.capture_text_file_from_bytes(
            exec_id, content, "test.txt",
        )
        evidence = artifact.to_evidence()

        assert evidence.artifact.artifact_type == "TEXT_FILE"
        assert evidence.size_bytes == len(content)

    def test_evidence_conversion_fixed_record(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-ev-fixed")
        content = b"A|1|2"

        artifact = capturer.capture_fixed_record(
            exec_id, content, "test.dat",
        )
        evidence = artifact.to_evidence()

        assert evidence.artifact.artifact_type == "FIXED_RECORD"
        assert evidence.size_bytes == len(content)
