"""Integration tests for Relative File Semantic Validation workload.

Tests the relative workload which exercises:
- WRITE by RRN, READ by RRN, REWRITE on relative file
- Canonical dump via stdout (rrn|data format)
- STDOUT, STDERR, EXIT_STATUS artifact comparison

Required scenarios:
1. Correct candidate -> VERIFIED
2. Each mutation -> FAILED (false-PASS defense)
3. Evidence verification
4. Determinism proof
"""

from __future__ import annotations

from pathlib import Path

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.workload import WorkloadArtifact, WorkloadDefinition

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workload-relative"
COBOL_SOURCE = str(FIXTURES / "cobol" / "RELATIVE.cob")
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_MUTATED_DIR = str(FIXTURES / "java-candidate-mutated")

MUTATIONS = {
    "missing-record": ("RelativeMissingRecord", "RRN 3 removed"),
    "extra-record": ("RelativeExtraRecord", "RRN 4 added"),
    "wrong-rrn": ("RelativeWrongRRN", "RRN 3 moved to RRN 9"),
    "changed-content": ("RelativeChangedContent", "RRN 3 content changed"),
    "shifted-record": ("RelativeShiftedRecord", "All records shifted by 1"),
    "incorrect-rewrite": ("RelativeIncorrectRewrite", "RRN 2 not rewritten"),
}


def _make_config(
    candidate_path: str,
    entrypoint: str,
    workload: WorkloadDefinition | None = None,
) -> PipelineConfig:
    return PipelineConfig(
        workload_id="relative",
        cobol_source_path=COBOL_SOURCE,
        java_candidate_path=candidate_path,
        java_entrypoint=entrypoint,
        use_docker_java=True,
        workload=workload,
    )


def _relative_workload() -> WorkloadDefinition:
    return WorkloadDefinition(
        workload_id="relative",
        description="Relative File Semantic Validation",
        artifacts=(
            WorkloadArtifact(
                logical_name="relative-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="relative-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="relative-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )


class TestRelativeValidCandidate:
    def test_correct_candidate_verified(self):
        config = _make_config(JAVA_CANDIDATE, "RelativeDump", _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "VERIFIED", (
            f"Expected VERIFIED, got {result.verdict.state.value}: {result.verdict.reason}"
        )


class TestRelativeMutations:
    def test_missing_record_failed(self):
        cls_name, _ = MUTATIONS["missing-record"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Missing record should FAIL, got {result.verdict.state.value}"
        )

    def test_extra_record_failed(self):
        cls_name, _ = MUTATIONS["extra-record"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Extra record should FAIL, got {result.verdict.state.value}"
        )

    def test_wrong_rrn_failed(self):
        cls_name, _ = MUTATIONS["wrong-rrn"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Wrong RRN should FAIL, got {result.verdict.state.value}"
        )

    def test_changed_content_failed(self):
        cls_name, _ = MUTATIONS["changed-content"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Changed content should FAIL, got {result.verdict.state.value}"
        )

    def test_shifted_record_failed(self):
        cls_name, _ = MUTATIONS["shifted-record"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Shifted record should FAIL, got {result.verdict.state.value}"
        )

    def test_incorrect_rewrite_failed(self):
        cls_name, _ = MUTATIONS["incorrect-rewrite"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Incorrect rewrite should FAIL, got {result.verdict.state.value}"
        )


class TestRelativeEvidence:
    def test_evidence_has_comparison(self):
        config = _make_config(JAVA_CANDIDATE, "RelativeDump", _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert len(result.comparison_evidence) >= 1, "No comparison evidence"

    def test_stdout_comparison_match(self):
        config = _make_config(JAVA_CANDIDATE, "RelativeDump", _relative_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        stdout_comps = [c for c in result.comparison_evidence if c.artifact_type == "STDOUT"]
        assert len(stdout_comps) >= 1, "No STDOUT comparison"
        assert stdout_comps[0].result == "MATCH", (
            f"STDOUT comparison should be MATCH, got {stdout_comps[0].result}"
        )


class TestRelativeDeterminism:
    def test_deterministic_result(self):
        config = _make_config(JAVA_CANDIDATE, "RelativeDump", _relative_workload())
        r1 = VerticalSlicePipeline(config).run()
        r2 = VerticalSlicePipeline(config).run()
        assert r1.verdict.state.value == r2.verdict.state.value
        assert r1.oracle_stdout == r2.oracle_stdout
        assert r1.candidate_stdout == r2.candidate_stdout
