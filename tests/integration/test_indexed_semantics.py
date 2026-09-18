"""Integration tests for Indexed File Semantic Validation workload.

Tests the indexed workload which exercises:
- WRITE, READ, REWRITE, DELETE on indexed file
- Canonical dump via stdout (key|data format)
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

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workload-indexed"
COBOL_SOURCE = str(FIXTURES / "cobol" / "INDEXED.cob")
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_MUTATED_DIR = str(FIXTURES / "java-candidate-mutated")

MUTATIONS = {
    "missing-key": ("IndexedMissingKey", "K003 removed from output"),
    "extra-key": ("IndexedExtraKey", "K004 added to output"),
    "wrong-key": ("IndexedWrongKey", "K003 replaced with K999"),
    "changed-content": ("IndexedChangedContent", "K003 content changed"),
    "wrong-mapping": ("IndexedWrongMapping", "K001/K002 content swapped"),
    "duplicate-record": ("IndexedDuplicateRecord", "K001 written twice"),
    "incorrect-delete": ("IndexedIncorrectDelete", "K002 not deleted"),
    "incorrect-rewrite": ("IndexedIncorrectRewrite", "K002 not rewritten"),
}


def _make_config(
    candidate_path: str,
    entrypoint: str,
    workload: WorkloadDefinition | None = None,
) -> PipelineConfig:
    return PipelineConfig(
        workload_id="indexed",
        cobol_source_path=COBOL_SOURCE,
        java_candidate_path=candidate_path,
        java_entrypoint=entrypoint,
        use_docker_java=True,
        workload=workload,
    )


def _indexed_workload() -> WorkloadDefinition:
    return WorkloadDefinition(
        workload_id="indexed",
        description="Indexed File Semantic Validation",
        artifacts=(
            WorkloadArtifact(
                logical_name="indexed-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )


class TestIndexedValidCandidate:
    def test_correct_candidate_verified(self):
        config = _make_config(JAVA_CANDIDATE, "IndexedDump", _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "VERIFIED", (
            f"Expected VERIFIED, got {result.verdict.state.value}: {result.verdict.reason}"
        )

    def test_oracle_stdout_contains_expected_records(self):
        config = _make_config(JAVA_CANDIDATE, "IndexedDump", _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        expected = {"K001|RECORD-ONE--0001", "K003|RECORD-THREE-003"}
        stdout_lines = set()
        for line in result.oracle_stdout.decode(errors="replace").splitlines():
            if "|" in line and not line.startswith("FILESTATUS") and not line.startswith("END"):
                stdout_lines.add(line.strip())
        assert expected.issubset(stdout_lines), f"Missing records: {expected - stdout_lines}"


class TestIndexedMutations:
    def test_missing_key_failed(self):
        cls_name, _ = MUTATIONS["missing-key"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Missing key should FAIL, got {result.verdict.state.value}"
        )

    def test_extra_key_failed(self):
        cls_name, _ = MUTATIONS["extra-key"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Extra key should FAIL, got {result.verdict.state.value}"
        )

    def test_wrong_key_failed(self):
        cls_name, _ = MUTATIONS["wrong-key"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Wrong key should FAIL, got {result.verdict.state.value}"
        )

    def test_changed_content_failed(self):
        cls_name, _ = MUTATIONS["changed-content"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Changed content should FAIL, got {result.verdict.state.value}"
        )

    def test_wrong_mapping_failed(self):
        cls_name, _ = MUTATIONS["wrong-mapping"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Wrong mapping should FAIL, got {result.verdict.state.value}"
        )

    def test_duplicate_record_failed(self):
        cls_name, _ = MUTATIONS["duplicate-record"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Duplicate record should FAIL, got {result.verdict.state.value}"
        )

    def test_incorrect_delete_failed(self):
        cls_name, _ = MUTATIONS["incorrect-delete"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Incorrect delete should FAIL, got {result.verdict.state.value}"
        )

    def test_incorrect_rewrite_failed(self):
        cls_name, _ = MUTATIONS["incorrect-rewrite"]
        config = _make_config(JAVA_MUTATED_DIR, cls_name, _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED", (
            f"Incorrect rewrite should FAIL, got {result.verdict.state.value}"
        )


class TestIndexedEvidence:
    def test_evidence_has_comparison(self):
        config = _make_config(JAVA_CANDIDATE, "IndexedDump", _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert len(result.comparison_evidence) >= 1, "No comparison evidence"

    def test_stdout_comparison_match(self):
        config = _make_config(JAVA_CANDIDATE, "IndexedDump", _indexed_workload())
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        stdout_comps = [c for c in result.comparison_evidence if c.artifact_type == "STDOUT"]
        assert len(stdout_comps) >= 1, "No STDOUT comparison"
        assert stdout_comps[0].result == "MATCH", (
            f"STDOUT comparison should be MATCH, got {stdout_comps[0].result}"
        )


class TestIndexedDeterminism:
    def test_deterministic_result(self):
        config = _make_config(JAVA_CANDIDATE, "IndexedDump", _indexed_workload())
        r1 = VerticalSlicePipeline(config).run()
        r2 = VerticalSlicePipeline(config).run()
        assert r1.verdict.state.value == r2.verdict.state.value
        assert r1.oracle_stdout == r2.oracle_stdout
        assert r1.candidate_stdout == r2.candidate_stdout
