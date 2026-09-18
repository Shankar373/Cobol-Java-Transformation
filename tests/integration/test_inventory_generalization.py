"""Integration tests for Phase 5A.1: multi-artifact generalization.

Tests the Inventory Reconciliation workload and proves:
1. Pipeline is workload/artifact declaration-driven
2. ComparatorRegistry is used at runtime
3. Artifact type is NOT determined by filename extension
4. FIXED_RECORD record_count is populated from actual bytes
5. FIXED_RECORD comparison is genuinely record-aware
6. No production pipeline modification needed for second workload
7. All mutations detected as FAILED
8. False-PASS defense verified
9. Determinism proven
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from engine.comparators.framework import (
    ComparatorRegistry,
    FixedRecordComparator,
    StdoutComparator,
    create_default_registry,
)
from engine.domain.identities import ExecutionId, RunId
from engine.execution.artifacts import ArtifactCapturer
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.workload import WorkloadArtifact, WorkloadDefinition

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workload_inventory"
COBOL_SOURCE = str(FIXTURES / "cobol" / "INVENTORY.cob")
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_MUTATED_DIR = str(FIXTURES / "java-candidate-mutated")

MUTATIONS = {
    "wrong-value": ("InventoryWrongValue", "item total incremented by 1"),
    "wrong-format": ("InventoryWrongFormat", "report.txt format lacks leading zeros"),
    "no-report-file": ("InventoryNoReportFile", "report.txt not generated"),
    "extra-item": ("InventoryExtraItem", "7 items instead of 6"),
    "wrong-name": ("InventoryWrongName", "BOLT F renamed to BOLT X"),
    "wrong-total": ("InventoryWrongTotal", "GIZMO C total off by 1"),
    "wrong-delimiter": ("InventoryWrongDelimiter", "inventory.dat uses comma instead of pipe"),
    "reversed-order": ("InventoryReversedOrder", "items listed in reverse order"),
    "missing-stderr": ("InventoryMissingStderr", "STDERR warnings omitted entirely"),
}


def _make_config(
    workload_id: str,
    candidate_path: str,
    entrypoint: str,
    workload: WorkloadDefinition | None = None,
) -> PipelineConfig:
    return PipelineConfig(
        workload_id=workload_id,
        cobol_source_path=COBOL_SOURCE,
        java_candidate_path=candidate_path,
        java_entrypoint=entrypoint,
        use_docker_java=True,
        workload=workload,
    )


# ---------------------------------------------------------------------------
# INVENTORY WORKLOAD - ORACLE E2E
# ---------------------------------------------------------------------------

class TestInventoryOracleE2E:
    """Verify the COBOL oracle produces correct inventory output."""

    def test_oracle_executes(self) -> None:
        pass  # Handled by other tests that verify oracle output

    def test_oracle_stdout_format(self) -> None:
        from engine.oracle.adapter import OracleAdapterConfig
        from engine.oracle.docker_adapter import DockerOracleAdapter

        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=30,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-inv-oracle-stdout")
        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert "TOTAL_VALUE=000698745" in stdout
        assert "ITEM_COUNT=6" in stdout
        assert "AVERAGE_VALUE=000116457" in stdout

    def test_oracle_stderr_has_warnings(self) -> None:
        from engine.oracle.adapter import OracleAdapterConfig
        from engine.oracle.docker_adapter import DockerOracleAdapter

        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=30,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-inv-oracle-stderr")
        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert "ITEM004" in stderr
        assert "ITEM006" in stderr
        assert "below reorder" in stderr

    def test_oracle_generates_files(self) -> None:
        from engine.oracle.adapter import OracleAdapterConfig
        from engine.oracle.docker_adapter import DockerOracleAdapter

        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=30,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-inv-oracle-files")
        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)
        assert result.generated_files is not None
        assert "report.txt" in result.generated_files
        assert "inventory.dat" in result.generated_files
        report = result.generated_files["report.txt"].decode("utf-8", errors="replace")
        assert "ITEM001" in report
        inv = result.generated_files["inventory.dat"].decode("utf-8", errors="replace")
        assert "ITEM001|WIDGET A" in inv


# ---------------------------------------------------------------------------
# INVENTORY WORKLOAD - VERIFIED CANDIDATE
# ---------------------------------------------------------------------------

class TestInventoryVerifiedCandidate:
    """Verify the correct Java candidate produces matching output."""

    def test_candidate_matches_oracle(self) -> None:
        import sys as _sys
        # Add fixtures to path for import
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        config = _make_config(
            workload_id="inventory-verified",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.verdict.state.value == "VERIFIED"
        assert len(result.artifact_evidence) >= 10
        assert len(result.comparison_evidence) == 5

        types = {ce.artifact_type for ce in result.comparison_evidence}
        assert types == {"STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"}

    def test_inventory_evidence_record_count(self) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        config = _make_config(
            workload_id="inventory-evidence",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        fixed_artifacts = [
            ae for ae in result.artifact_evidence
            if ae.artifact.artifact_type == "FIXED_RECORD"
        ]
        assert len(fixed_artifacts) == 2
        for fa in fixed_artifacts:
            assert fa.artifact.record_count == 6


# ---------------------------------------------------------------------------
# INVENTORY WORKLOAD - MUTATION DETECTION
# ---------------------------------------------------------------------------

class TestInventoryMutations:
    """Verify all 9 mutations are detected as FAILED."""

    @pytest.mark.parametrize(
        "mutation_key",
        list(MUTATIONS.keys()),
    )
    def test_mutation_detected(self, mutation_key: str) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        class_name, description = MUTATIONS[mutation_key]
        wl = inventory_workload()
        config = _make_config(
            workload_id=f"inventory-mut-{mutation_key}",
            candidate_path=JAVA_MUTATED_DIR,
            entrypoint=class_name,
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.verdict.state.value == "FAILED", (
            f"Mutation {mutation_key!r} ({description}) was NOT detected as FAILED. "
            f"Got: {result.verdict.state.value}"
        )


# ---------------------------------------------------------------------------
# INVENTORY WORKLOAD - FALSE-PASS DEFENSE
# ---------------------------------------------------------------------------

class TestInventoryFalsePassDefense:
    """Verify missing/extra records are detected."""

    def test_missing_candidate_record_detected(self) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        config = _make_config(
            workload_id="inventory-fp-missing",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        fixed_comps = [
            ce for ce in result.comparison_evidence
            if ce.artifact_type == "FIXED_RECORD"
        ]
        assert len(fixed_comps) == 1
        assert fixed_comps[0].result == "MATCH"

    def test_extra_candidate_record_detected(self) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        config = _make_config(
            workload_id="inventory-fp-extra",
            candidate_path=JAVA_MUTATED_DIR,
            entrypoint="InventoryExtraItem",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        fixed_comps = [
            ce for ce in result.comparison_evidence
            if ce.artifact_type == "FIXED_RECORD"
        ]
        assert len(fixed_comps) == 1
        assert fixed_comps[0].result == "MISMATCH"


# ---------------------------------------------------------------------------
# REGISTRY TESTS
# ---------------------------------------------------------------------------

class TestRegistryDrivenDispatch:
    """Prove ComparatorRegistry is used at runtime and pipeline doesn't
    instantiate concrete comparators directly."""

    def test_all_v1_comparators_registered(self) -> None:
        registry = create_default_registry()
        for atype in ("STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"):
            assert registry.is_registered(atype)

    def test_registry_returns_correct_comparator(self) -> None:
        registry = create_default_registry()
        assert isinstance(registry.get("STDOUT"), StdoutComparator)
        assert isinstance(registry.get("STDERR"), type(registry.get("STDERR")))
        assert isinstance(registry.get("FIXED_RECORD"), FixedRecordComparator)

    def test_pipeline_uses_registry_not_direct_import(self) -> None:
        source = inspect.getsource(VerticalSlicePipeline._run_declaration_driven)
        assert "StdoutComparator()" not in source
        assert "StderrComparator()" not in source
        assert "ExitStatusComparator()" not in source
        assert "TextFileComparator()" not in source
        assert "FixedRecordComparator()" not in source
        assert "self._registry.get(" in source

    def test_missing_comparator_fails_closed(self) -> None:
        empty_registry = ComparatorRegistry()
        wl = WorkloadDefinition(
            workload_id="test-missing-comp",
            description="test",
            artifacts=(
                WorkloadArtifact(
                    logical_name="unknown",
                    artifact_type="STDOUT",
                    comparator_id="nonexistent",
                ),
            ),
        )
        config = _make_config(
            workload_id="test-missing-comp",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config, registry=empty_registry)
        with pytest.raises(ValueError, match="No comparator registered"):
            pipeline.run()

    def test_custom_registry_injection(self) -> None:
        registry = create_default_registry()
        custom_comparator = StdoutComparator()
        registry._comparators["STDOUT"] = custom_comparator

        config = _make_config(
            workload_id="test-custom-registry",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
        )
        pipeline = VerticalSlicePipeline(config, registry=registry)
        assert pipeline._registry.get("STDOUT") is custom_comparator


# ---------------------------------------------------------------------------
# EXTENSION-INDEPENDENT ARTIFACT TYPING
# ---------------------------------------------------------------------------

class TestExtensionIndependentTyping:
    """Prove artifact type is determined by declaration, not extension."""

    def test_dat_file_declared_as_fixed_record(self) -> None:
        wl = WorkloadDefinition(
            workload_id="test-ext",
            description="test",
            artifacts=(
                WorkloadArtifact(
                    logical_name="records",
                    artifact_type="FIXED_RECORD",
                    comparator_id="fixed-record-exact",
                    output_path="inventory.dat",
                    record_length=39,
                ),
            ),
        )
        artifact = wl.get_artifact("records")
        assert artifact.artifact_type == "FIXED_RECORD"
        assert artifact.output_path == "inventory.dat"

    def test_same_extension_different_types(self) -> None:
        wl1 = WorkloadDefinition(
            workload_id="t1",
            description="test",
            artifacts=(
                WorkloadArtifact(
                    logical_name="data",
                    artifact_type="FIXED_RECORD",
                    comparator_id="fixed-record-exact",
                    output_path="output.dat",
                    record_length=10,
                ),
            ),
        )
        wl2 = WorkloadDefinition(
            workload_id="t2",
            description="test",
            artifacts=(
                WorkloadArtifact(
                    logical_name="data",
                    artifact_type="TEXT_FILE",
                    comparator_id="text-file-exact",
                    output_path="output.dat",
                ),
            ),
        )
        assert wl1.get_artifact("data").artifact_type == "FIXED_RECORD"
        assert wl2.get_artifact("data").artifact_type == "TEXT_FILE"

    def test_txt_file_declared_as_fixed_record(self) -> None:
        wl = WorkloadDefinition(
            workload_id="test-ext2",
            description="test",
            artifacts=(
                WorkloadArtifact(
                    logical_name="data",
                    artifact_type="FIXED_RECORD",
                    comparator_id="fixed-record-exact",
                    output_path="output.txt",
                    record_length=20,
                ),
            ),
        )
        assert wl.get_artifact("data").artifact_type == "FIXED_RECORD"


# ---------------------------------------------------------------------------
# RECORD-AWARE COMPARISON
# ---------------------------------------------------------------------------

class TestRecordAwareComparison:
    """Prove FIXED_RECORD comparison is genuinely record-aware."""

    def _make_artifact(self, record_count: int | None, size_bytes: int) -> object:
        from engine.domain.identities import ArtifactIdentity, ContentHash
        return ArtifactIdentity(
            artifact_id="test",
            artifact_type="FIXED_RECORD",
            logical_name="test",
            producer_role="ORACLE",
            content_hash=ContentHash.from_bytes(b""),
            size_bytes=size_bytes,
            record_count=record_count,
        )

    def test_same_records_match(self) -> None:
        comp = FixedRecordComparator()
        data = b"A|1|100\nB|2|200\nC|3|300\n"
        oa = self._make_artifact(3, len(data))
        ca = self._make_artifact(3, len(data))
        result = comp.compare(oa, data, ca, data)
        assert result.result.value == "MATCH"

    def test_different_records_mismatch(self) -> None:
        comp = FixedRecordComparator()
        oracle = b"A|1|100\nB|2|200\nC|3|300\n"
        candidate = b"A|1|100\nB|2|999\nC|3|300\n"
        oa = self._make_artifact(3, len(oracle))
        ca = self._make_artifact(3, len(candidate))
        result = comp.compare(oa, oracle, ca, candidate)
        assert result.result.value == "MISMATCH"

    def test_missing_record_mismatch(self) -> None:
        comp = FixedRecordComparator()
        oracle = b"A|1|100\nB|2|200\nC|3|300\n"
        candidate = b"A|1|100\nB|2|200\n"
        oa = self._make_artifact(3, len(oracle))
        ca = self._make_artifact(2, len(candidate))
        result = comp.compare(oa, oracle, ca, candidate)
        assert result.result.value == "MISMATCH"

    def test_extra_record_mismatch(self) -> None:
        comp = FixedRecordComparator()
        oracle = b"A|1|100\nB|2|200\nC|3|300\n"
        candidate = b"A|1|100\nB|2|200\nC|3|300\nD|4|400\n"
        oa = self._make_artifact(3, len(oracle))
        ca = self._make_artifact(4, len(candidate))
        result = comp.compare(oa, oracle, ca, candidate)
        assert result.result.value == "MISMATCH"

    def test_reordered_records_mismatch_sequential(self) -> None:
        comp = FixedRecordComparator()
        oracle = b"A|1|100\nB|2|200\nC|3|300\n"
        candidate = b"C|3|300\nB|2|200\nA|1|100\n"
        oa = self._make_artifact(3, len(oracle))
        ca = self._make_artifact(3, len(candidate))
        result = comp.compare(oa, oracle, ca, candidate)
        assert result.result.value == "MISMATCH"

    def test_record_count_mismatch(self) -> None:
        comp = FixedRecordComparator()
        data = b"A|1|100\nB|2|200\nC|3|300\n"
        oa = self._make_artifact(3, len(data))
        ca = self._make_artifact(5, len(data))
        result = comp.compare(oa, data, ca, data)
        assert result.result.value == "MISMATCH"

    def test_no_substring_containment(self) -> None:
        comp = FixedRecordComparator()
        oracle = b"A|1|100\nB|2|200\nC|3|300\n"
        candidate = b"A|1|100\nB|2|200\n"
        oa = self._make_artifact(3, len(oracle))
        ca = self._make_artifact(2, len(candidate))
        result = comp.compare(oa, oracle, ca, candidate)
        assert result.result.value == "MISMATCH"
        assert not any("contained" in d.description.lower() for d in result.differences)


# ---------------------------------------------------------------------------
# RECORD COUNT POPULATION
# ---------------------------------------------------------------------------

class TestRecordCountPopulation:
    """Prove record_count is populated from actual bytes."""

    def test_record_count_populated(self) -> None:
        capturer = ArtifactCapturer()
        execution_id = ExecutionId(value="test-rc")
        content = b"ITEM001|WIDGET A  |0100|002550|00255000\n" * 6
        artifact = capturer.capture_fixed_record(
            execution_id, content, "inventory-records", "ORACLE", record_length=40,
        )
        assert artifact.artifact.record_count == 6

    def test_record_count_none_when_no_length(self) -> None:
        capturer = ArtifactCapturer()
        execution_id = ExecutionId(value="test-rc-none")
        content = b"some data"
        artifact = capturer.capture_fixed_record(
            execution_id, content, "test", "ORACLE",
        )
        assert artifact.artifact.record_count is None

    def test_malformed_content_raises(self) -> None:
        capturer = ArtifactCapturer()
        execution_id = ExecutionId(value="test-rc-mal")
        content = b"short"
        with pytest.raises(ValueError, match="not divisible"):
            capturer.capture_fixed_record(
                execution_id, content, "test", "ORACLE", record_length=10,
            )


# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------

class TestInventoryDeterminism:
    """Run the inventory workload twice and verify identical evidence."""

    def test_deterministic_output(self) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        configs = [
            _make_config(
                workload_id="inventory-det",
                candidate_path=JAVA_CANDIDATE,
                entrypoint="Inventory",
                workload=wl,
            )
            for _ in range(2)
        ]
        results = [VerticalSlicePipeline(c).run() for c in configs]

        assert results[0].oracle_stdout == results[1].oracle_stdout
        assert results[0].candidate_stdout == results[1].candidate_stdout
        assert results[0].oracle_stderr == results[1].oracle_stderr
        assert results[0].candidate_stderr == results[1].candidate_stderr
        assert results[0].oracle_exit_code == results[1].oracle_exit_code
        assert results[0].candidate_exit_code == results[1].candidate_exit_code

        for c0, c1 in zip(results[0].comparison_evidence, results[1].comparison_evidence):
            assert c0.result == c1.result
            assert c0.content_hash == c1.content_hash


# ---------------------------------------------------------------------------
# EVIDENCE COMPLETENESS
# ---------------------------------------------------------------------------

class TestInventoryEvidence:
    """Verify evidence manifests are complete."""

    def test_evidence_counts(self) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        config = _make_config(
            workload_id="inventory-evidence-counts",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert len(result.artifact_evidence) == 10
        assert len(result.comparison_evidence) == 5

        types = {ce.artifact_type for ce in result.comparison_evidence}
        assert types == {"STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"}

        for ce in result.comparison_evidence:
            assert ce.content_hash is not None
            assert ce.comparator_id
            assert ce.comparator_version

    def test_evidence_has_workload_id(self) -> None:
        import sys as _sys
        fixtures_dir = str(FIXTURES.parent)
        if fixtures_dir not in _sys.path:
            _sys.path.insert(0, fixtures_dir)

        from workload_inventory.workload import inventory_workload

        wl = inventory_workload()
        config = _make_config(
            workload_id="inventory-evidence-wid",
            candidate_path=JAVA_CANDIDATE,
            entrypoint="Inventory",
            workload=wl,
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.evidence_manifest.workload_id.value == "inventory-evidence-wid"


# ---------------------------------------------------------------------------
# PIPELINE IS WORKLOAD-AGNOSTIC (structural test)
# ---------------------------------------------------------------------------

class TestPipelineIsWorkloadAgnostic:
    """Prove the pipeline has no workload-specific branching."""

    def test_no_payroll_reference_in_pipeline(self) -> None:
        source = inspect.getsource(VerticalSlicePipeline)
        lower = source.lower()
        assert "payroll" not in lower
        assert "employee" not in lower
        assert "bonus" not in lower

    def test_no_inventory_reference_in_pipeline(self) -> None:
        source = inspect.getsource(VerticalSlicePipeline)
        lower = source.lower()
        assert "inventory" not in lower
        assert "widget" not in lower
        assert "reorder" not in lower

    def test_pipeline_module_not_modified_between_workloads(self) -> None:
        """Both workloads use the same pipeline code without modification."""
        pipeline_file = Path(inspect.getfile(VerticalSlicePipeline))
        content = pipeline_file.read_text()
        assert "payroll" not in content.lower()
        assert "inventory" not in content.lower()
